"""
Bug Localization Module for the AI Agent

This module implements bug localization functionality inspired by the Ladybug project.
It uses the UniXcoder model for semantic code understanding and bug report analysis.

Key Components:
- BugLocalizer: Main class for ranking files by bug likelihood
- UnixCoder: Microsoft's code understanding model wrapper
- Preprocessor: Text preprocessing for bug reports and source code
- GUIDataExtractor: Extracts screen component and GUI screen terms from execution traces
- BugLocalizationIntegration: Integration layer for the AI Agent
"""

# Lightweight imports that don't need torch
from .preprocessor import Preprocessor, preprocess_bug_report, preprocess_source_code
from .gui_data_extractor import (
    GUIDataExtractor, 
    extract_sc_terms, 
    extract_gs_terms,
    build_corpus,
    get_boosted_files
)

# Heavy imports that require torch - degrade gracefully when unavailable
try:
    from .bug_localizer import BugLocalizer, LocalizationResult, format_results
    from .unixcoder import UniXcoder
    TORCH_AVAILABLE = True
except ImportError:
    BugLocalizer = None  # type: ignore[assignment,misc]
    LocalizationResult = None  # type: ignore[assignment,misc]
    format_results = None  # type: ignore[assignment]
    UniXcoder = None  # type: ignore[assignment,misc]
    TORCH_AVAILABLE = False

from .integration import (
    BugLocalizationIntegration,
    create_bug_report_from_detection,
    get_integration
)

__all__ = [
    # Core classes
    'BugLocalizer',
    'UniXcoder', 
    'Preprocessor',
    'GUIDataExtractor',
    'LocalizationResult',
    # Integration
    'BugLocalizationIntegration',
    'get_integration',
    # Functions
    'format_results',
    'preprocess_bug_report',
    'preprocess_source_code',
    'extract_sc_terms',
    'extract_gs_terms',
    'build_corpus',
    'get_boosted_files',
    'create_bug_report_from_detection',
]

