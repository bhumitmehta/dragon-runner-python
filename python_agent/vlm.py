import re
import time

from google import genai
from PIL import Image

from . import config

# The new google.genai API uses a Client object instead of genai.configure()

# Retry settings for rate limits
MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 15


class VLMQuotaExceeded(RuntimeError):
    pass


class VLMUnavailable(RuntimeError):
    pass


def _extract_retry_delay(error_msg: str) -> int:
    """Extract retry delay from error message, e.g., 'retry in 58.232s'"""
    match = re.search(r'retry in (\d+)', error_msg.lower())
    if match:
        return int(match.group(1)) + 1  # Add 1 second buffer
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
                    print(f"  Rate limited. Waiting {delay}s before retry {attempt + 2}/{MAX_RETRIES}...")
                    time.sleep(delay)
                    last_error = e
                    continue
            raise
    raise last_error if last_error else RuntimeError("Max retries exceeded")


def get_vlm_response(image_path, prompt):
    """
    Gets a response from the vision-language model.

    Args:
        image_path (str): The path to the image file.
        prompt (str): The prompt to send to the model.

    Returns:
        str: The model's response.
    """
    if not config.VLM_ENABLED:
        raise VLMUnavailable("VLM is disabled in config")
    if not config.GOOGLE_API_KEY:
        raise VLMUnavailable("Missing GOOGLE_API_KEY")

    try:
        def _do_vlm_call():
            client = genai.Client(api_key=config.GOOGLE_API_KEY)
            img = Image.open(image_path)
            response = client.models.generate_content(
                model=config.VLM_MODEL_NAME,
                contents=[prompt, img],
            )
            return response.text
        
        return _call_with_retry(_do_vlm_call)
    except Exception as e:
        msg = str(e).lower()
        # Typical quota / billing errors return HTTP 429
        if "429" in msg or "quota" in msg or "rate" in msg:
            raise VLMQuotaExceeded(str(e)) from e
        print(f"Error getting VLM response: {e}")
        # Re-raise as unavailable for other errors
        raise VLMUnavailable(str(e)) from e


def get_text_response(prompt: str) -> str:
    """
    Gets a text-only response from the language model (no image).
    
    Args:
        prompt (str): The prompt to send to the model.
        
    Returns:
        str: The model's response.
    """
    if not config.VLM_ENABLED:
        raise VLMUnavailable("VLM is disabled in config")
    if not config.GOOGLE_API_KEY:
        raise VLMUnavailable("Missing GOOGLE_API_KEY")

    try:
        def _do_text_call():
            client = genai.Client(api_key=config.GOOGLE_API_KEY)
            response = client.models.generate_content(
                model=config.VLM_MODEL_NAME,
                contents=[prompt],
            )
            return response.text
        
        return _call_with_retry(_do_text_call)
    except Exception as e:
        msg = str(e).lower()
        if "429" in msg or "quota" in msg or "rate" in msg:
            raise VLMQuotaExceeded(str(e)) from e
        print(f"Error getting text response: {e}")
        raise VLMUnavailable(str(e)) from e

