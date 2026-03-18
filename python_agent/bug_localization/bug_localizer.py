"""
Bug Localizer - Main class for bug localization using UniXcoder embeddings.

This module uses semantic code understanding to rank source files by their
likelihood of containing a reported bug. It integrates:
- UniXcoder embeddings for semantic similarity
- Text preprocessing for bug reports and source code
- GUI data extraction for boosting relevant files

Adapted from the Ladybug project for use with our AI Agent.
"""

import os
import json
import torch
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from .unixcoder import UniXcoder
from .preprocessor import Preprocessor, preprocess_bug_report
from .gui_data_extractor import GUIDataExtractor, extract_sc_terms, extract_gs_terms


@dataclass
class LocalizationResult:
    """Result of bug localization analysis."""
    file_path: str
    similarity_score: float
    rank: int
    is_boosted: bool = False


class BugLocalizer:
    """
    Main class for bug localization using UniXcoder embeddings.
    
    Uses semantic similarity between bug reports and source code files
    to rank files by their likelihood of containing the bug.
    """
    
    def __init__(self, model_name: str = "microsoft/unixcoder-base"):
        """
        Initialize the Bug Localizer.
        
        Args:
            model_name: HuggingFace model to use for embeddings
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"BugLocalizer using device: {self.device}")
        
        # Initialize UniXcoder model
        self.model = UniXcoder(model_name)
        self.model.to(self.device)
        self.model.eval()
        
        # Initialize preprocessor
        self.preprocessor = Preprocessor()
        
        # GUI data extractor (optional)
        self.gui_extractor: Optional[GUIDataExtractor] = None
        
        # Cache for embeddings
        self._embedding_cache: dict[str, list] = {}
        
    def encode_text(self, text: str, chunk_size: int = 500, verbose: bool = False) -> list:
        """
        Encode text into embeddings, handling long texts by chunking.
        
        Args:
            text: Text to encode
            chunk_size: Character chunk size for splitting long texts
            verbose: Print debug info
            
        Returns:
            List of embeddings for each chunk
        """
        embeddings = []
        
        # Split text into chunks
        for i in range(0, len(text), chunk_size):
            text_chunk = text[i:i + chunk_size]
            if verbose:
                print(f"Processing chunk {i // chunk_size + 1}")
                
            # Tokenize the chunk
            tokens = self.model.tokenize([text_chunk], mode="<encoder-only>")[0]
            source_ids = torch.tensor([tokens]).to(self.device)
            
            try:
                with torch.no_grad():
                    _, embedding = self.model(source_ids)
                    norm_embedding = torch.nn.functional.normalize(embedding, p=2, dim=1)
                    embeddings.append(norm_embedding.tolist())
            except Exception as e:
                if verbose:
                    print(f"Error encoding chunk {i // chunk_size + 1}: {e}")
                continue
                
        return embeddings
    
    def preprocess_and_encode_bug_report(
        self, 
        bug_report: str,
        sc_terms: Optional[list[str]] = None,
        verbose: bool = False
    ) -> list:
        """
        Preprocess a bug report and generate embeddings.
        
        Args:
            bug_report: Bug report text or file path
            sc_terms: Screen component terms for query expansion
            verbose: Print debug info
            
        Returns:
            List of embeddings
        """
        # Preprocess
        preprocessed = preprocess_bug_report(bug_report, sc_terms, verbose)
        
        # Generate embeddings
        return self.encode_text(preprocessed, verbose=verbose)
    
    def preprocess_and_encode_source_file(
        self,
        content: str,
        file_path: Optional[str] = None,
        verbose: bool = False
    ) -> list:
        """
        Preprocess source code and generate embeddings.
        
        Args:
            content: Source code content
            file_path: Optional file path for caching
            verbose: Print debug info
            
        Returns:
            List of embeddings
        """
        # Check cache
        if file_path and file_path in self._embedding_cache:
            return self._embedding_cache[file_path]
            
        # Preprocess
        preprocessed = self.preprocessor.preprocess_text(content, verbose=verbose)
        
        # Generate embeddings
        embeddings = self.encode_text(preprocessed, verbose=verbose)
        
        # Cache if file_path provided
        if file_path:
            self._embedding_cache[file_path] = embeddings
            
        return embeddings
    
    def rank_files(
        self, 
        query_embeddings: list, 
        file_embeddings: list[tuple[str, list]]
    ) -> list[tuple[str, float]]:
        """
        Rank files based on similarity to the query embeddings.
        
        Args:
            query_embeddings: Embeddings for the bug report query
            file_embeddings: List of (file_path, embeddings) tuples
            
        Returns:
            Sorted list of (file_path, similarity_score) tuples
        """
        similarities = []
        
        for file_id, file_embeds in file_embeddings:
            max_similarity = float('-inf')
            
            # Compare each query embedding with each file embedding
            for query_embedding in query_embeddings:
                query_tensor = torch.tensor(query_embedding, device=self.device)
                
                for file_embedding in file_embeds:
                    file_tensor = torch.tensor(file_embedding, device=self.device)
                    
                    # Compute cosine similarity
                    similarity = torch.nn.functional.cosine_similarity(
                        query_tensor, file_tensor, dim=1
                    ).item()
                    
                    if similarity > max_similarity:
                        max_similarity = similarity
                        
            similarities.append((file_id, max_similarity))
            
        # Sort by similarity descending
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities
    
    def reorder_rankings(
        self, 
        ranked_files: list[tuple[str, float]], 
        boosted_files: list[str]
    ) -> list[tuple[str, float]]:
        """
        Boost specified files to the top of rankings while preserving their order.
        
        Args:
            ranked_files: List of (file_path, score) tuples
            boosted_files: List of file paths to boost
            
        Returns:
            Reordered list with boosted files first
        """
        boosted_ranked = [item for item in ranked_files if item[0] in boosted_files]
        non_boosted = [item for item in ranked_files if item[0] not in boosted_files]
        return boosted_ranked + non_boosted
    
    def load_gui_trace(self, trace_data: str | dict):
        """
        Load GUI execution trace for enhanced localization.
        
        Args:
            trace_data: JSON string or dict containing the trace
        """
        self.gui_extractor = GUIDataExtractor(trace_data)
        
    def localize_bug(
        self,
        bug_report: str,
        source_files: list[tuple[str, str, str]],
        trace_data: Optional[str | dict] = None,
        top_n: int = 10,
        verbose: bool = False
    ) -> list[LocalizationResult]:
        """
        Localize a bug by ranking source files.
        
        This is the main entry point for bug localization.
        
        Args:
            bug_report: Bug report text or file path
            source_files: List of (file_path, filename, content) tuples
            trace_data: Optional GUI execution trace for boosting
            top_n: Number of top results to return
            verbose: Print debug info
            
        Returns:
            List of LocalizationResult objects sorted by likelihood
        """
        # Load GUI trace if provided
        sc_terms = []
        gs_terms = []
        boosted_files = []
        
        if trace_data:
            self.load_gui_trace(trace_data)
            sc_terms = self.gui_extractor.sc_terms
            gs_terms = self.gui_extractor.gs_terms
            boosted_files = self.gui_extractor.get_boosted_files(source_files)
            
            if verbose:
                print(f"SC Terms: {sc_terms}")
                print(f"GS Terms: {gs_terms}")
                print(f"Boosted files: {boosted_files}")
        
        # Encode bug report
        if verbose:
            print("Encoding bug report...")
        query_embeddings = self.preprocess_and_encode_bug_report(
            bug_report, sc_terms, verbose
        )
        
        # Encode source files
        if verbose:
            print(f"Encoding {len(source_files)} source files...")
            
        file_embeddings = []
        for file_path, filename, content in source_files:
            embeddings = self.preprocess_and_encode_source_file(
                content, file_path, verbose=False
            )
            if embeddings:
                file_embeddings.append((file_path, embeddings))
                
        # Rank files
        if verbose:
            print("Ranking files...")
        ranked_files = self.rank_files(query_embeddings, file_embeddings)
        
        # Apply boosting if GUI data available
        if boosted_files:
            ranked_files = self.reorder_rankings(ranked_files, boosted_files)
            
        # Create results
        results = []
        for rank, (file_path, score) in enumerate(ranked_files[:top_n], start=1):
            results.append(LocalizationResult(
                file_path=file_path,
                similarity_score=score,
                rank=rank,
                is_boosted=file_path in boosted_files
            ))
            
        return results
    
    def localize_from_directory(
        self,
        bug_report: str,
        source_dir: str,
        file_extensions: list[str] = None,
        trace_data: Optional[str | dict] = None,
        top_n: int = 10,
        verbose: bool = False
    ) -> list[LocalizationResult]:
        """
        Localize a bug by scanning a directory for source files.
        
        Uses ``collect_source_files`` to automatically skip node_modules,
        build outputs, and other non-source directories — matching Ladybug's
        filter_files() behaviour.
        
        Args:
            bug_report: Bug report text or file path
            source_dir: Directory containing source code
            file_extensions: List of extensions to include (e.g., ['.java', '.py'])
            trace_data: Optional GUI execution trace
            top_n: Number of top results to return
            verbose: Print debug info
            
        Returns:
            List of LocalizationResult objects
        """
        from .integration import collect_source_files

        # Default extensions for mobile apps
        if file_extensions is None:
            file_extensions = ['.java', '.kt', '.py', '.js', '.ts', '.tsx', '.jsx']
            
        # Collect source files using smart filter (skips node_modules etc.)
        source_files = collect_source_files(source_dir, file_extensions)
                            
        if verbose:
            print(f"Found {len(source_files)} source files (after filtering)")
            
        return self.localize_bug(
            bug_report, source_files, trace_data, top_n, verbose
        )
    
    def clear_cache(self):
        """Clear the embedding cache."""
        self._embedding_cache.clear()
        
    def save_embeddings(self, file_path: str):
        """
        Save cached embeddings to a file.
        
        Args:
            file_path: Path to save embeddings JSON
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self._embedding_cache, f)
            
    def load_embeddings(self, file_path: str):
        """
        Load embeddings from a file.
        
        Args:
            file_path: Path to embeddings JSON
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            self._embedding_cache = json.load(f)


def format_results(results: list[LocalizationResult]) -> str:
    """
    Format localization results for display.
    
    Args:
        results: List of LocalizationResult objects
        
    Returns:
        Formatted string for display
    """
    lines = ["Bug Localization Results:", "=" * 50]
    
    for result in results:
        boost_marker = " [BOOSTED]" if result.is_boosted else ""
        lines.append(
            f"{result.rank}. {result.file_path}{boost_marker}"
            f"\n   Score: {result.similarity_score:.4f}"
        )
        
    return "\n".join(lines)


if __name__ == "__main__":
    # Test the bug localizer
    print("Testing Bug Localizer...")
    
    # Initialize
    localizer = BugLocalizer()
    
    # Sample bug report
    bug_report = """
    App crashes when user clicks the login button with empty password field.
    NullPointerException in UserAuthenticator.validateCredentials()
    Expected: Show validation error message
    Actual: App crashes immediately
    """
    
    # Sample source files
    source_files = [
        ("UserAuthenticator.java", "UserAuthenticator.java", 
         "class UserAuthenticator { void validateCredentials(String user, String pass) {} }"),
        ("LoginActivity.java", "LoginActivity.java",
         "class LoginActivity { void onLoginClick() { authenticator.validateCredentials(); } }"),
        ("HomeActivity.java", "HomeActivity.java",
         "class HomeActivity { void showDashboard() {} }"),
    ]
    
    # Sample trace
    trace = {
        "steps": [
            {
                "screen": {
                    "activity": "LoginActivity",
                    "dynGuiComponents": [
                        {"idXml": "com.app:id/login_button"},
                        {"idXml": "com.app:id/password_field"}
                    ]
                }
            }
        ]
    }
    
    # Localize
    results = localizer.localize_bug(
        bug_report,
        source_files,
        trace_data=trace,
        verbose=True
    )
    
    print("\n" + format_results(results))
