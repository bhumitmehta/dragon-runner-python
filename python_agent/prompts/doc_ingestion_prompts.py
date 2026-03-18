"""
Prompt templates for the DocIngestion Agent.

The DocIngestion Agent reads application documentation and extracts
a structured feature list that drives the test plan.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .builder import PromptBuilder


# ── System role ──────────────────────────────────────────────────────

DOC_INGESTION_SYSTEM_ROLE = (
    "You are a senior QA analyst. Given application documentation, "
    "you extract every testable feature as a structured JSON list. "
    "Each feature must have a unique id, name, description, priority "
    "(high/medium/low), and expected_screens (list of screen names "
    "where this feature should be exercised). "
    "Be exhaustive -- even minor UI features like tooltips, loading "
    "states, and edge cases should be captured."
)


class DocIngestionPrompts:
    """Factory for DocIngestion agent prompts using the builder pattern."""

    SYSTEM_ROLE = DOC_INGESTION_SYSTEM_ROLE

    # ── Documentation ingestion ──────────────────────────────────────

    @staticmethod
    def ingest_documentation(
        doc_text: str,
        app_name: str = "Mobile App",
        existing_feature_names: Optional[List[str]] = None,
    ) -> str:
        """Build prompt for extracting testable features from documentation."""
        builder = (
            PromptBuilder()
            .preamble(
                "Analyze the following application documentation and extract "
                "ALL testable features."
            )
            .section("APPLICATION", app_name)
        )

        if existing_feature_names:
            builder.section(
                "ALREADY-KNOWN FEATURES (do NOT duplicate these)",
                json.dumps(existing_feature_names),
            )

        builder.section("DOCUMENTATION", f"---\n{doc_text[:6000]}\n---")

        builder.json_output(
            '[\n'
            '  {\n'
            '    "id": "feat_<number>",\n'
            '    "name": "<short feature name>",\n'
            '    "description": "<what the feature does>",\n'
            '    "priority": "high" | "medium" | "low",\n'
            '    "expected_screens": ["<screen name where this is tested>"],\n'
            '    "verification_hints": [\n'
            '      "<how to verify this feature works>"\n'
            '    ]\n'
            '  }\n'
            ']',
            preamble="Return a JSON array where each element has this exact structure:",
        )

        builder.rules([
            "Extract at least 8 features, up to 25.",
            "priority=high for core user flows (login, add to cart, checkout, navigation).",
            "priority=medium for secondary flows (sort, filter, search, profile).",
            "priority=low for edge cases (empty states, error handling, accessibility).",
            "verification_hints must be concrete and actionable.",
            "Return ONLY the JSON array, no explanation.",
        ])

        return builder.build()

    # ── Feature enrichment with UI elements ──────────────────────────

    @staticmethod
    def enrich_features(
        features: List[Dict[str, Any]],
        ui_elements: Dict[str, List[str]],
    ) -> str:
        """Build prompt for cross-referencing features with actual UI elements."""
        return (
            PromptBuilder()
            .preamble(
                "Given these app features and the current UI elements, match each feature\n"
                "to the actual UI elements that exercise it. Add an \"ui_elements\" key to each feature\n"
                "with the relevant element IDs."
            )
            .section_json("FEATURES", features[:20])
            .ui_elements(
                ui_elements.get("accessibility_ids", []),
                ui_elements.get("resource_ids", []),
                ui_elements.get("clickable_texts", []),
                acc_limit=40,
                res_limit=25,
                txt_limit=25,
            )
            .output(
                'Return the updated JSON array with an added "ui_elements" list per feature.\n'
                "Return ONLY the JSON array, no explanation."
            )
            .build()
        )
