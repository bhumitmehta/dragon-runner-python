"""
DocIngestion Agent -- reads application documentation and extracts a
structured feature list that drives the test plan.

Input:  raw text (markdown, txt, README) describing the app under test.
Output: list of Feature dicts ready to store in the KnowledgeBase.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseAgent
from ..logging_config import get_logger

logger = get_logger("agents.doc_ingestion")


class DocIngestionAgent(BaseAgent):
    name = "doc_ingestion"
    system_role = (
        "You are a senior QA analyst. Given application documentation, "
        "you extract every testable feature as a structured JSON list. "
        "Each feature must have a unique id, name, description, priority "
        "(high/medium/low), and expected_screens (list of screen names "
        "where this feature should be exercised). "
        "Be exhaustive -- even minor UI features like tooltips, loading "
        "states, and edge cases should be captured."
    )

    # ── Public API ───────────────────────────────────────────────────

    def ingest_documentation(
        self,
        doc_text: str,
        *,
        app_name: str = "Mobile App",
        existing_features: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Parse documentation and return a list of feature dicts.

        Each dict has keys: id, name, description, priority, expected_screens,
        verification_hints (list of strings describing how to verify).
        """
        existing_hint = ""
        if existing_features:
            names = [f.get("name", "") for f in existing_features[:20]]
            existing_hint = (
                f"\n\nAlready-known features (do NOT duplicate these): {json.dumps(names)}"
            )

        prompt = f"""Analyze the following application documentation and extract ALL testable features.

APPLICATION: {app_name}
{existing_hint}

DOCUMENTATION:
---
{doc_text[:6000]}
---

Return a JSON array where each element has this exact structure:
[
  {{
    "id": "feat_<number>",
    "name": "<short feature name>",
    "description": "<what the feature does>",
    "priority": "high" | "medium" | "low",
    "expected_screens": ["<screen name where this is tested>"],
    "verification_hints": [
      "<how to verify this feature works, e.g. 'sort products ascending and check first price < last price'>"
    ]
  }}
]

RULES:
- Extract at least 8 features, up to 25.
- priority=high for core user flows (login, add to cart, checkout, navigation).
- priority=medium for secondary flows (sort, filter, search, profile).
- priority=low for edge cases (empty states, error handling, accessibility).
- verification_hints must be concrete and actionable.
- Return ONLY the JSON array, no explanation.
"""
        raw = self.ask_text(prompt)
        return self._parse_features(raw)

    def ingest_from_file(self, doc_path: Path, **kwargs) -> List[Dict[str, Any]]:
        """Read a documentation file and ingest it."""
        if not doc_path.exists():
            logger.warning("Doc file not found: %s", doc_path)
            return []
        text = doc_path.read_text(encoding="utf-8", errors="replace")
        return self.ingest_documentation(text, **kwargs)

    def ingest_from_directory(self, docs_dir: Path, **kwargs) -> List[Dict[str, Any]]:
        """Read all .md / .txt files in a directory and ingest."""
        if not docs_dir.exists():
            logger.warning("Docs directory not found: %s", docs_dir)
            return []
        combined = []
        for ext in ("*.md", "*.txt", "*.rst"):
            for f in sorted(docs_dir.glob(ext)):
                combined.append(f"=== {f.name} ===\n{f.read_text(encoding='utf-8', errors='replace')}\n")
        if not combined:
            logger.warning("No documentation files found in %s", docs_dir)
            return []
        full_text = "\n".join(combined)
        return self.ingest_documentation(full_text, **kwargs)

    def enrich_features_with_ui(
        self,
        features: List[Dict[str, Any]],
        ui_elements: Dict[str, List[str]],
    ) -> List[Dict[str, Any]]:
        """
        Refine feature list by cross-referencing with actual UI elements.
        Links features to real element IDs visible on screen.
        """
        acc = json.dumps(ui_elements.get("accessibility_ids", [])[:40])
        res = json.dumps(ui_elements.get("resource_ids", [])[:25])
        txt = json.dumps(ui_elements.get("clickable_texts", [])[:25])
        feat_json = json.dumps(features[:20], indent=2)

        prompt = f"""Given these app features and the current UI elements, match each feature
to the actual UI elements that exercise it. Add an "ui_elements" key to each feature
with the relevant element IDs.

FEATURES:
{feat_json}

CURRENT UI ELEMENTS:
Accessibility IDs: {acc}
Resource IDs: {res}
Clickable Texts: {txt}

Return the updated JSON array with an added "ui_elements" list per feature.
Return ONLY the JSON array, no explanation.
"""
        raw = self.ask_text(prompt)
        enriched = self._parse_features(raw)
        if enriched:
            return enriched
        # Fallback: return originals unchanged
        return features

    # ── Parsing ──────────────────────────────────────────────────────

    def _parse_features(self, raw: str) -> List[Dict[str, Any]]:
        obj = self.parse_json(raw)
        if isinstance(obj, list):
            return [f for f in obj if isinstance(f, dict) and "name" in f]
        if isinstance(obj, dict):
            # Might be wrapped: {"features": [...]}
            for key in ("features", "feature_list", "testable_features"):
                if key in obj and isinstance(obj[key], list):
                    return [f for f in obj[key] if isinstance(f, dict) and "name" in f]
        logger.warning("Could not parse feature list from LLM response (len=%d)", len(raw))
        return []
