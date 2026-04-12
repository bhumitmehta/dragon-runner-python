import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from google import genai
from PIL import Image

from . import config
from .logging_config import get_logger

logger = get_logger("vlm")

# The new google.genai API uses a Client object instead of genai.configure()

# Retry settings for rate limits
MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 3

# Cloud models available on Ollama
# Vision models support image inputs (multimodal)
VISION_CLOUD_MODELS = [
    "qwen3-vl:235b-cloud",
]
# Text-only models (faster, used when no image is needed)
TEXT_CLOUD_MODELS = [
    "gpt-oss:120b-cloud",
]
# Default single model to use (set to None to use parallel mode)
DEFAULT_TEXT_MODEL = "gpt-oss:120b-cloud"
DEFAULT_VISION_MODEL = "qwen3-vl:235b-cloud"

# Legacy alias kept for _ollama_generate default
PARALLEL_CLOUD_MODELS = TEXT_CLOUD_MODELS

# ── Track whether we already fell back to Ollama this session ───────────
# Gemini and local models disabled  --  using only Ollama cloud for now
_gemini_disabled_this_session = True


class VLMQuotaExceeded(RuntimeError):
    pass


class VLMUnavailable(RuntimeError):
    pass


# ════════════════════════════════════════════════════════════════════════
#  VLM Screen Cache  --  one vision call per unique screen
# ════════════════════════════════════════════════════════════════════════

class VLMCache:
    """Caches per-screen visual analyses so the VLM is called only ONCE
    per unique screen (identified by state_signature).  Subsequent requests
    for the same screen receive the cached visual description and are
    answered by the *text-only* LLM, which is much faster."""

    def __init__(self):
        self._analyses: dict[str, str] = {}   # state_sig → visual description
        self.hits = 0
        self.misses = 0

    def has(self, state_sig: str) -> bool:
        return bool(state_sig) and state_sig in self._analyses

    def get(self, state_sig: str) -> str | None:
        if state_sig and state_sig in self._analyses:
            self.hits += 1
            return self._analyses[state_sig]
        return None

    def store(self, state_sig: str, description: str):
        if state_sig and description:
            self._analyses[state_sig] = description
            self.misses += 1

    def clear(self):
        self._analyses.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> str:
        total = self.hits + self.misses
        pct = (self.hits / total * 100) if total else 0
        return (f"VLM cache: {self.hits} hits, {self.misses} misses "
                f"({pct:.0f}% hit rate), {len(self._analyses)} screens cached")


_vlm_cache = VLMCache()


def get_vlm_cache() -> VLMCache:
    """Return the module-level VLM screen cache."""
    return _vlm_cache


_SCREEN_ANALYSIS_PROMPT = """Analyse this mobile app screenshot in detail.

Describe:
features the screen has , what actions can be performed , give the answer in plain text format
Be concise but thorough. This description will be reused for multiple subsequent reasoning steps about this screen."""


def analyze_screen_once(image_path: str, state_sig: str) -> str:
    """Get a comprehensive visual description of a screen.

    - First call for a given *state_sig*: sends the screenshot to the
      vision model, caches the result, and returns it.
    - Subsequent calls for the same *state_sig*: returns the cached
      description instantly (no VLM call).
    """
    cached = _vlm_cache.get(state_sig)
    if cached:
        logger.info("Screen analysis cache HIT  sig=%s", state_sig[:16])
        return cached

    logger.info("Screen analysis cache MISS sig=%s  --  calling vision model", state_sig[:16])

    # Try with one retry on transient VLM failure
    description = None
    for attempt in range(2):
        try:
            description = get_vlm_response(image_path, _SCREEN_ANALYSIS_PROMPT)
            break
        except Exception as e:
            if attempt == 0:
                logger.warning(
                    "VLM analysis failed (attempt 1), retrying in 3s: %s", e,
                )
                import time as _time
                _time.sleep(3)
            else:
                logger.error(
                    "VLM analysis failed after 2 attempts for sig=%s: %s",
                    state_sig[:16], e,
                )
                # Store a placeholder so we don't retry forever
                description = "(Screen analysis unavailable -- VLM provider error)"

    _vlm_cache.store(state_sig, description)
    return description


def get_vlm_response_cached(
    image_path: str,
    prompt: str,
    state_sig: str | None = None,
) -> str:
    """Smart VLM call: uses cached screen analysis when available.

    If *state_sig* is provided and a cached visual description exists,
    the actual prompt is answered by the **text-only** LLM with the
    cached description prepended (fast path).  Otherwise falls through
    to a real VLM call.
    """
    if state_sig:
        analysis = analyze_screen_once(image_path, state_sig)
        # Answer the real question using text-only + cached visual context
        augmented = (
            f"VISUAL CONTEXT (screenshot analysis of the current screen):\n"
            f"{analysis}\n\n"
            f"{prompt}"
        )
        return get_text_response(augmented)

    # No state_sig  --  fall through to real VLM
    return get_vlm_response(image_path, prompt)


# ════════════════════════════════════════════════════════════════════════
#  Ollama helpers (local LLM)
# ════════════════════════════════════════════════════════════════════════

def _ollama_is_available() -> bool:
    """Check if the Ollama server is reachable."""
    try:
        r = requests.get(f"{config.OLLAMA_HOST}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _ollama_generate_model(prompt: str, model: str, *, images: list[str] | None = None, timeout: int = 180) -> str:
    """Call Ollama /api/generate with a specific model name."""
    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 2048,
        },
    }
    if images:
        payload["images"] = images

    r = requests.post(
        f"{config.OLLAMA_HOST}/api/generate",
        json=payload,
        timeout=timeout,
    )
    r.raise_for_status()
    resp = r.json().get("response", "")
    if not resp or not resp.strip():
        raise VLMUnavailable(f"Empty response from {model}")
    return resp


def _ollama_generate(prompt: str, *, images: list[str] | None = None) -> str:
    """
    Call Ollama /api/generate using a single model.
    Uses DEFAULT_TEXT_MODEL for text-only requests.
    """
    model = DEFAULT_TEXT_MODEL
    if not model:
        # Fallback to parallel mode if no default set
        models_to_try = list(PARALLEL_CLOUD_MODELS)
        return _ollama_generate_parallel(prompt, images=images, models_to_try=models_to_try)

    # Use single model with timeout
    timeout = 60 if model.endswith("-cloud") else 180
    return _ollama_generate_model(prompt, model, images=images, timeout=timeout)


def _ollama_generate_parallel(prompt: str, *, images: list[str] | None = None, models_to_try: list[str] | None = None) -> str:
    """
    Call Ollama /api/generate  --  tries ALL available models in parallel
    (cloud models like gpt-oss, kimi + local llama3) and returns the
    first successful response.
    """
    models_to_try = models_to_try or list(PARALLEL_CLOUD_MODELS)

    with ThreadPoolExecutor(max_workers=len(models_to_try)) as executor:
        futures = {}
        for model in models_to_try:
            # Cloud models get shorter timeout; local model gets longer
            t = 60 if model.endswith("-cloud") else 180
            fut = executor.submit(_ollama_generate_model, prompt, model, images=images, timeout=t)
            futures[fut] = model

        for fut in as_completed(futures):
            model = futures[fut]
            try:
                result = fut.result()
                logger.info("[Ollama] Got response from '%s' (first to finish)", model)
                # Cancel remaining futures
                for other in futures:
                    if other is not fut:
                        other.cancel()
                return result
            except Exception as e:
                logger.debug("[Ollama] Model '%s' failed: %s", model, str(e)[:80])
                continue

    raise VLMUnavailable("All Ollama models failed (tried: %s)" % ", ".join(models_to_try))


def _image_to_base64(image_path: str) -> str:
    """Read an image file and return its base64 encoding."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ════════════════════════════════════════════════════════════════════════
#  Gemini helpers
# ════════════════════════════════════════════════════════════════════════


def _extract_retry_delay(error_msg: str) -> int:
    """Extract retry delay from error message, capped to keep things fast."""
    match = re.search(r'retry in (\d+)', error_msg.lower())
    if match:
        return min(int(match.group(1)) + 1, 3)  # Cap at 3 seconds
    return DEFAULT_RETRY_DELAY


def _call_with_retry(func, *args, **kwargs):
    """Call a function with automatic retry on rate limits."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg or "rate" in msg:
                delay = _extract_retry_delay(str(e))
                if attempt < MAX_RETRIES - 1:
                    logger.warning("Rate limited. Waiting %ds before retry %d/%d...", delay, attempt + 2, MAX_RETRIES)
                    time.sleep(delay)
                    last_error = e
                    continue
            raise
    raise last_error if last_error else RuntimeError("Max retries exceeded")


def get_vlm_response(image_path, prompt):
    """
    Gets a response from a vision-language model using a single model.

    Uses DEFAULT_VISION_MODEL for vision requests.
    Falls back to local Ollama if cloud model fails.

    Args:
        image_path (str): The path to the image file.
        prompt (str): The prompt to send to the model.

    Returns:
        str: The model's response.
    """
    global _gemini_disabled_this_session

    # ── Try single Ollama vision model ─────────────────────────────
    if config.OLLAMA_FALLBACK and DEFAULT_VISION_MODEL:
        img_b64 = _image_to_base64(image_path) if image_path else None
        if img_b64:
            logger.info("VLM: sending screenshot (%s) to vision model '%s'", image_path, DEFAULT_VISION_MODEL)
        else:
            logger.warning("VLM: no image_path  --  falling back to text-only for 'vision' call")

        try:
            images = [img_b64] if img_b64 else None
            result = _ollama_generate_model(prompt, DEFAULT_VISION_MODEL, images=images, timeout=120)
            if result and result.strip():
                logger.info("VLM response from '%s'", DEFAULT_VISION_MODEL)
                return result
        except Exception as e:
            logger.warning("VLM model '%s' failed: %s", DEFAULT_VISION_MODEL, str(e)[:80])

    # ── Fallback: try Gemini if enabled ───────────────────────────
    if config.VLM_ENABLED and config.GOOGLE_API_KEY and not _gemini_disabled_this_session:
        try:
            def _gemini_vlm():
                client = genai.Client(api_key=config.GOOGLE_API_KEY)
                img = Image.open(image_path)
                response = client.models.generate_content(
                    model=config.VLM_MODEL_NAME,
                    contents=[prompt, img],
                )
                return response.text
            result = _call_with_retry(_gemini_vlm)
            if result and result.strip():
                logger.info("VLM response from 'gemini'")
                return result
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg or "rate" in msg:
                logger.warning("Gemini quota exceeded  --  disabling for this session.")
                _gemini_disabled_this_session = True
            logger.debug("VLM provider 'gemini' failed: %s", str(e)[:80])

    raise VLMUnavailable("All VLM providers failed")


def get_text_response(prompt: str) -> str:
    """
    Gets a text-only response from a language model (no image) using a single model.

    Uses DEFAULT_TEXT_MODEL for text requests.
    Falls back to Gemini if cloud model fails.

    Args:
        prompt (str): The prompt to send to the model.

    Returns:
        str: The model's response.
    """
    global _gemini_disabled_this_session

    # ── Try single Ollama text model ──────────────────────────────
    if config.OLLAMA_FALLBACK and DEFAULT_TEXT_MODEL:
        try:
            result = _ollama_generate_model(prompt, DEFAULT_TEXT_MODEL, timeout=60)
            if result and result.strip():
                logger.info("Text response from '%s'", DEFAULT_TEXT_MODEL)
                return result
        except Exception as e:
            logger.warning("Text model '%s' failed: %s", DEFAULT_TEXT_MODEL, str(e)[:80])

    # ── Fallback: try Gemini if enabled ───────────────────────────
    if config.VLM_ENABLED and config.GOOGLE_API_KEY and not _gemini_disabled_this_session:
        try:
            def _gemini_text():
                client = genai.Client(api_key=config.GOOGLE_API_KEY)
                response = client.models.generate_content(
                    model=config.VLM_MODEL_NAME,
                    contents=[prompt],
                )
                return response.text
            result = _call_with_retry(_gemini_text)
            if result and result.strip():
                logger.info("Text response from 'gemini'")
                return result
        except Exception as e:
            msg = str(e).lower()
            if "429" in msg or "quota" in msg or "rate" in msg:
                logger.warning("Gemini quota exceeded  --  disabling for this session.")
                _gemini_disabled_this_session = True
            logger.debug("Text provider 'gemini' failed: %s", str(e)[:80])

    raise VLMUnavailable("All text providers failed")


# ════════════════════════════════════════════════════════════════════════
#  Ollama fallback wrappers
# ════════════════════════════════════════════════════════════════════════

def _ollama_vlm_fallback(image_path: str, prompt: str) -> str:
    """
    Use Ollama as a fallback for vision requests.

    If the Ollama model supports images (e.g. llava, bakllava) the image
    is sent as base64.  For text-only models like llama3 the image is
    skipped and only the prompt (which already contains UI element
    listings) is used  --  the agent loses pixel-level visual context but
    can still reason about the UI structure.
    """
    logger.info("[Ollama] Using local model '%s' for VLM fallback", config.OLLAMA_MODEL)

    # Try sending the image  --  text-only models will just ignore it or
    # the server will strip it, but multimodal models will use it.
    try:
        img_b64 = _image_to_base64(image_path)
        return _ollama_generate(prompt, images=[img_b64])
    except VLMUnavailable:
        raise
    except Exception:
        # If image inclusion caused an issue, retry text-only
        return _ollama_generate(prompt)


def _ollama_text_fallback(prompt: str) -> str:
    """Use Ollama as a fallback for text-only requests."""
    logger.info("[Ollama] Using local model '%s' for text fallback", config.OLLAMA_MODEL)
    return _ollama_generate(prompt)


def reset_gemini_session():
    """
    Reset the Gemini disabled flag  --  useful between separate test runs
    so that the next run tries Gemini again before falling back.
    """
    global _gemini_disabled_this_session
    _gemini_disabled_this_session = False


def reset_vlm_cache():
    """Clear the per-screen VLM analysis cache.  Call between runs."""
    stats = _vlm_cache.stats()
    _vlm_cache.clear()
    logger.info("VLM cache reset.  Previous session: %s", stats)

