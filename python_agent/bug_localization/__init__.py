"""
Bug Localization Module for the AI Agent

Implements bug localization following the Ladybug architecture:

1. **Index** source files from the app-under-test directory
   (node_modules / build / generated artefacts are excluded automatically).
2. **Preprocess** source code and bug reports with language-aware stop-word
   removal (Java, JS/TS, Kotlin).
3. **Embed** using the UniXcoder model (Microsoft's code-understanding model).
4. **Rank** files by cosine similarity between bug-report embeddings and
   source-file embeddings.
5. **Boost** files that match GUI Screen (GS) terms extracted from the
   Appium execution trace.

Key Components:
- BugLocalizer: Main class for ranking files by bug likelihood
- UniXcoder: Microsoft's code understanding model wrapper
- Preprocessor: Language-aware text preprocessing for bug reports and source code
- GUIDataExtractor: Extracts SC/GS terms from both Ladybug and Appium traces
- BugLocalizationIntegration: Integration layer for the AI Agent
- collect_source_files: Smart directory walker that skips node_modules etc.
"""

# Lightweight imports that don't need torch
from .preprocessor import (
    Preprocessor,
    preprocess_bug_report,
    preprocess_source_code,
    SKIP_DIRS,
    SKIP_FILE_PATTERNS,
    LANGUAGE_STOP_WORDS,
    DEFAULT_STOP_WORDS,
)
from .gui_data_extractor import (
    GUIDataExtractor, 
    extract_sc_terms, 
    extract_gs_terms,
    build_corpus,
    get_boosted_files,
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
    get_integration,
    collect_source_files,
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
    'collect_source_files',
    # Functions
    'format_results',
    'preprocess_bug_report',
    'preprocess_source_code',
    'extract_sc_terms',
    'extract_gs_terms',
    'build_corpus',
    'get_boosted_files',
    'create_bug_report_from_detection',
    # Constants
    'SKIP_DIRS',
    'SKIP_FILE_PATTERNS',
    'LANGUAGE_STOP_WORDS',
    'DEFAULT_STOP_WORDS',
    'TORCH_AVAILABLE',
]

