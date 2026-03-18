"""
Text Preprocessor for Bug Localization

Handles preprocessing of bug reports and source code for semantic analysis.
Includes tokenization, lemmatization, stop word removal, and special character handling.
"""

import re
from pathlib import Path
from typing import Optional

# NLTK imports - these are required
try:
    from nltk.stem import WordNetLemmatizer
    from nltk.tokenize import wordpunct_tokenize
    from nltk.corpus import wordnet as wn
    from nltk import pos_tag
    NLTK_AVAILABLE = True
except ImportError:
    NLTK_AVAILABLE = False
    print("Warning: NLTK not available. Run: pip install nltk")


# ── Stop word sets (language-aware) ──────────────────────────────────

# Common English / documentation stop words (language agnostic)
_COMMON_STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of',
    'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been', 'be', 'have',
    'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may',
    'might', 'must', 'shall', 'can', 'need', 'dare', 'ought', 'used', 'i', 'you',
    'he', 'she', 'it', 'we', 'they', 'what', 'which', 'who', 'whom', 'this', 'that',
    'these', 'those', 'am', 'being', 'very', 'just', 'also', 'now', 'then',
}

# Java-specific keywords (original Ladybug set)
_JAVA_STOP_WORDS = {
    'public', 'private', 'protected', 'static', 'final', 'void', 'class', 'interface',
    'extends', 'implements', 'import', 'package', 'return', 'new', 'this', 'super',
    'try', 'catch', 'throw', 'throws', 'finally', 'if', 'else', 'switch', 'case',
    'default', 'for', 'while', 'do', 'break', 'continue', 'true', 'false', 'null',
    'boolean', 'byte', 'char', 'short', 'int', 'long', 'float', 'double', 'string',
    'abstract', 'assert', 'enum', 'instanceof', 'native', 'synchronized',
    'transient', 'volatile',
}

# JavaScript / TypeScript keywords
_JS_TS_STOP_WORDS = {
    'var', 'let', 'const', 'function', 'return', 'if', 'else', 'switch', 'case',
    'default', 'for', 'while', 'do', 'break', 'continue', 'true', 'false', 'null',
    'undefined', 'typeof', 'instanceof', 'new', 'this', 'class', 'extends', 'super',
    'import', 'export', 'from', 'require', 'module', 'async', 'await', 'yield',
    'try', 'catch', 'finally', 'throw', 'void', 'delete', 'in', 'of',
    'interface', 'type', 'enum', 'namespace', 'declare', 'readonly', 'abstract',
    'implements', 'keyof', 'any', 'unknown', 'never', 'string', 'number', 'boolean',
    'object', 'symbol', 'bigint', 'as', 'is', 'satisfies',
    # React / RN common noise
    'react', 'usestate', 'useeffect', 'useref', 'usecallback', 'usememo',
    'props', 'children', 'render', 'component', 'memo', 'fragment',
    'stylesheet', 'view', 'text', 'touchableopacity', 'flatlist', 'scrollview',
    'safeareaview', 'statusbar', 'textinput', 'image', 'button', 'platform',
    'dimensions', 'stylesheet',
}

# Kotlin keywords (Android)
_KOTLIN_STOP_WORDS = {
    'fun', 'val', 'var', 'class', 'object', 'interface', 'abstract', 'override',
    'private', 'protected', 'internal', 'public', 'open', 'final', 'sealed',
    'data', 'enum', 'companion', 'import', 'package', 'return', 'if', 'else',
    'when', 'for', 'while', 'do', 'break', 'continue', 'true', 'false', 'null',
    'this', 'super', 'in', 'is', 'as', 'by', 'lateinit', 'suspend', 'coroutine',
}

# Map language keys to stop-word sets
LANGUAGE_STOP_WORDS = {
    'java':   _JAVA_STOP_WORDS | _COMMON_STOP_WORDS,
    'kotlin': _KOTLIN_STOP_WORDS | _COMMON_STOP_WORDS,
    'js':     _JS_TS_STOP_WORDS | _COMMON_STOP_WORDS,
    'ts':     _JS_TS_STOP_WORDS | _COMMON_STOP_WORDS,
    'tsx':    _JS_TS_STOP_WORDS | _COMMON_STOP_WORDS,
    'jsx':    _JS_TS_STOP_WORDS | _COMMON_STOP_WORDS,
}

# Default combines all language keywords
DEFAULT_STOP_WORDS = _COMMON_STOP_WORDS | _JAVA_STOP_WORDS | _JS_TS_STOP_WORDS | _KOTLIN_STOP_WORDS

# Directories that should NEVER be indexed for source embeddings
SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', 'build', 'dist', '.gradle',
    '.idea', '.vscode', 'coverage', '.next', '.expo', 'android/build',
    'ios/build', 'ios/Pods', 'Pods',
}

# File-name patterns to skip
SKIP_FILE_PATTERNS = {
    '.lock', '.min.js', '.min.css', '.map', '.snap',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
    '.d.ts',   # TypeScript declaration files are pure noise
}


class Preprocessor:
    """
    Preprocessor for bug reports and source code text.
    
    Performs:
    - Special character removal
    - Tokenization (including camelCase splitting)
    - Stop word removal
    - Case normalization
    - Lemmatization
    """
    
    def __init__(self, stop_words: Optional[set] = None, language: Optional[str] = None):
        """
        Initialize the preprocessor.
        
        Args:
            stop_words: Custom set of stop words. Uses default if None.
            language: Language key ('java', 'js', 'ts', 'kotlin') for targetted
                      stop-word removal.  Falls back to DEFAULT_STOP_WORDS.
        """
        if stop_words:
            self.stop_words = stop_words
        elif language and language.lstrip('.') in LANGUAGE_STOP_WORDS:
            self.stop_words = LANGUAGE_STOP_WORDS[language.lstrip('.')]
        else:
            self.stop_words = DEFAULT_STOP_WORDS
        
        if NLTK_AVAILABLE:
            self.lemmatizer = WordNetLemmatizer()
        else:
            self.lemmatizer = None
            
    @staticmethod
    def camel_case_split(identifier: str) -> list[str]:
        """
        Split camelCase and PascalCase identifiers.

        Args:
            identifier: Token to be split

        Returns:
            List of split tokens
        """
        matches = re.finditer(
            '.+?(?:(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])|$)', 
            identifier
        )
        return [m.group(0) for m in matches]
    
    @staticmethod
    def tokenize_text(text: str) -> list[str]:
        """
        Tokenize text into individual words.
        
        Splits camelCase words and handles punctuation.

        Args:
            text: String to be tokenized

        Returns:
            List of tokens
        """
        tokens = []
        
        if NLTK_AVAILABLE:
            for token in wordpunct_tokenize(text):
                for word in Preprocessor.camel_case_split(token):
                    tokens.append(word)
        else:
            # Fallback simple tokenization
            words = re.findall(r'\b\w+\b', text)
            for word in words:
                for split_word in Preprocessor.camel_case_split(word):
                    tokens.append(split_word)
                    
        return tokens
    
    @staticmethod
    def remove_special_characters(text: str) -> str:
        """
        Remove special characters and punctuation from text.

        Args:
            text: String to clean

        Returns:
            Cleaned string
        """
        # Replace escape characters with space
        text = text.replace("\n", " ")
        text = text.replace("\t", " ")
        text = text.replace("\r", " ")
        
        # Replace special characters and numbers with space
        text = re.sub(r"[^A-Za-z\s]+", " ", text)
        
        # Collapse multiple spaces
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    @staticmethod
    def get_pos_tag(token: str):
        """
        Get the WordNet POS tag for a token.

        Args:
            token: Token to be tagged

        Returns:
            WordNet tag constant (e.g., wn.NOUN)
        """
        if not NLTK_AVAILABLE:
            return 'n'  # Default to noun
            
        tag = pos_tag([token])[0][1]

        if tag.startswith('JJ'):
            return wn.ADJ
        elif tag.startswith('NN'):
            return wn.NOUN
        elif tag.startswith('VB'):
            return wn.VERB
        elif tag.startswith('RB'):
            return wn.ADV
        else:
            return wn.NOUN  # Default to noun
        
    def lemmatize_tokens(self, tokens: list[str]) -> list[str]:
        """
        Lemmatize a list of tokens.

        Args:
            tokens: Tokens to be lemmatized
        
        Returns:
            Lemmatized tokens
        """
        if not self.lemmatizer:
            return tokens  # Return as-is if NLTK not available
            
        return [
            self.lemmatizer.lemmatize(token, self.get_pos_tag(token)) 
            for token in tokens
        ]
    
    def preprocess_text(
        self, 
        text: str, 
        stop_words_path: Optional[str] = None,
        verbose: bool = False
    ) -> str:
        """
        Fully preprocess input text.
        
        Steps:
        1. Remove special characters
        2. Tokenize (including camelCase splitting)
        3. Remove stop words
        4. Normalize case
        5. Lemmatize
        6. Remove short tokens (length <= 2)

        Args:
            text: Text to preprocess
            stop_words_path: Optional path to custom stop words file
            verbose: Print debug info

        Returns:
            Preprocessed text as a string
        """
        if verbose:
            print(f"Original text length: {len(text)}")
            
        # Load custom stop words if provided
        stop_words = self.stop_words.copy()
        if stop_words_path:
            try:
                with open(stop_words_path, 'r', encoding='utf-8') as f:
                    custom_words = set(f.read().splitlines())
                    stop_words.update(custom_words)
            except FileNotFoundError:
                print(f"Warning: Stop words file not found: {stop_words_path}")
                
        # Remove special characters
        text = self.remove_special_characters(text)
        
        # Tokenize
        tokens = self.tokenize_text(text)
        
        if verbose:
            print(f"Tokens after tokenization: {len(tokens)}")
            
        # Remove stop words (case-insensitive)
        stop_words_lower = {w.lower() for w in stop_words}
        tokens = [t for t in tokens if t.lower() not in stop_words_lower]
        
        # Normalize case
        tokens = [t.lower() for t in tokens]
        
        # Lemmatize
        tokens = self.lemmatize_tokens(tokens)
        
        # Remove short tokens
        tokens = [t for t in tokens if len(t) > 2]
        
        if verbose:
            print(f"Tokens after preprocessing: {len(tokens)}")
            
        return " ".join(tokens)


def preprocess_bug_report(
    bug_report: str, 
    sc_terms: Optional[list[str]] = None,
    verbose: bool = False
) -> str:
    """
    Preprocess a bug report with optional query expansion using screen component terms.
    
    Args:
        bug_report: Bug report text or path to bug report file
        sc_terms: Screen component terms for query expansion
        verbose: Print debug info
        
    Returns:
        Preprocessed bug report text
    """
    preprocessor = Preprocessor()
    
    # Check if bug_report is a file path
    if Path(bug_report).is_file():
        try:
            with open(bug_report, 'r', encoding='utf-8') as f:
                bug_report = f.read()
        except Exception as e:
            print(f"Error reading bug report file: {e}")
            return ""
    
    # Remove JSON attachment links
    json_url_pattern = r'\[[^\]]*\]\(https?:\/\/github\.com\/\S*?\.json\S*\)'
    bug_report = re.sub(json_url_pattern, '', bug_report, flags=re.IGNORECASE)
    
    # Expand query with screen component terms
    if sc_terms:
        for term in sc_terms:
            bug_report += " " + term
            
    # Preprocess the bug report
    return preprocessor.preprocess_text(bug_report, verbose=verbose)


def preprocess_source_code(
    source_code: str,
    verbose: bool = False
) -> str:
    """
    Preprocess source code for embedding generation.
    
    Args:
        source_code: Source code text
        verbose: Print debug info
        
    Returns:
        Preprocessed source code text
    """
    preprocessor = Preprocessor()
    return preprocessor.preprocess_text(source_code, verbose=verbose)


if __name__ == "__main__":
    # Test preprocessing
    test_bug_report = """
    App crashes when clicking the submitButton in the LoginActivity.
    NullPointerException at line 42 in UserService.java
    Expected: User should be logged in
    Actual: App crashes immediately
    """
    
    print("Testing preprocessor...")
    result = preprocess_bug_report(test_bug_report, sc_terms=['submitButton', 'LoginActivity'], verbose=True)
    print(f"Result: {result}")
