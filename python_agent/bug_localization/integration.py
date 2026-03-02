"""
Bug Localization Integration for AI Agent

This module provides integration between the Bug Localizer and the AI Agent.
It can analyze detected bugs and identify potential source file locations.
"""

import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# Import bug localization components (torch may be absent)
from .gui_data_extractor import GUIDataExtractor
try:
    from .bug_localizer import BugLocalizer, LocalizationResult, format_results
    TORCH_AVAILABLE = True
except ImportError:
    BugLocalizer = None  # type: ignore[assignment,misc]
    LocalizationResult = None  # type: ignore[assignment,misc]
    format_results = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


class BugLocalizationIntegration:
    """
    Integration layer between the AI Agent and Bug Localization.
    
    Provides methods to:
    - Track execution traces during testing
    - Analyze detected bugs to find likely source locations
    - Generate reports with localization results
    """
    
    def __init__(
        self, 
        source_code_dir: Optional[str] = None,
        file_extensions: Optional[List[str]] = None
    ):
        """
        Initialize the integration.
        
        Args:
            source_code_dir: Directory containing the app source code
            file_extensions: File extensions to consider (default: common mobile extensions)
        """
        self.source_code_dir = source_code_dir
        self.file_extensions = file_extensions or [
            '.java', '.kt', '.py', '.js', '.ts', '.tsx', '.jsx', '.swift', '.m'
        ]
        
        # Lazy-load the bug localizer (it loads heavy ML models)
        self._localizer: Optional[BugLocalizer] = None
        
        # Track execution trace
        self.execution_trace: Dict[str, Any] = {
            "steps": [],
            "start_time": None,
            "end_time": None
        }
        
        # Store localization results
        self.localization_results: List[Dict[str, Any]] = []
        
    @property
    def localizer(self):
        """Lazy-load the bug localizer. Returns None when torch is missing."""
        if self._localizer is None:
            if not TORCH_AVAILABLE or BugLocalizer is None:
                return None
            print("Initializing Bug Localizer (loading UniXcoder model)...")
            self._localizer = BugLocalizer()
            print("Bug Localizer ready!")
        return self._localizer
        
    def start_trace(self):
        """Start a new execution trace."""
        self.execution_trace = {
            "steps": [],
            "start_time": datetime.now().isoformat(),
            "end_time": None
        }
        
    def add_trace_step(
        self,
        action: Dict[str, Any],
        ui_state: Optional[Dict[str, Any]] = None,
        screenshot_path: Optional[str] = None
    ):
        """
        Add a step to the execution trace.
        
        Args:
            action: Action performed (from agent)
            ui_state: Current UI state info
            screenshot_path: Path to screenshot for this step
        """
        step = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "screen": ui_state or {},
            "screenshot": screenshot_path
        }
        self.execution_trace["steps"].append(step)
        
    def end_trace(self):
        """End the current execution trace."""
        self.execution_trace["end_time"] = datetime.now().isoformat()
        
    def get_trace_for_localization(self) -> Dict[str, Any]:
        """Get the trace in a format suitable for bug localization."""
        return self.execution_trace
        
    def localize_bug(
        self,
        bug_description: str,
        use_trace: bool = True,
        top_n: int = 10,
        verbose: bool = False
    ) -> List[LocalizationResult]:
        """
        Localize a detected bug to source files.
        
        Args:
            bug_description: Description of the bug (from agent detection)
            use_trace: Whether to use the execution trace for boosting
            top_n: Number of top results to return
            verbose: Print debug info
            
        Returns:
            List of LocalizationResult objects
        """
        if not self.source_code_dir:
            print("Warning: No source code directory configured for localization.")
            return []
            
        trace_data = self.get_trace_for_localization() if use_trace else None
        
        try:
            if self.localizer is None:
                print("Warning: Bug localizer unavailable (torch not installed). Skipping localization.")
                return []
            results = self.localizer.localize_from_directory(
                bug_report=bug_description,
                source_dir=self.source_code_dir,
                file_extensions=self.file_extensions,
                trace_data=trace_data,
                top_n=top_n,
                verbose=verbose
            )
            
            # Store for reporting
            self.localization_results.append({
                "bug_description": bug_description,
                "timestamp": datetime.now().isoformat(),
                "results": [
                    {
                        "file": r.file_path,
                        "score": r.similarity_score,
                        "rank": r.rank,
                        "boosted": r.is_boosted
                    }
                    for r in results
                ]
            })
            
            return results
            
        except Exception as e:
            print(f"Bug localization failed: {e}")
            return []
            
    def analyze_detected_bug(
        self,
        bug_report: str,
        page_source: Optional[str] = None,
        screenshot_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Comprehensive analysis of a detected bug.
        
        Args:
            bug_report: Bug description from detection
            page_source: Current page XML source
            screenshot_path: Path to screenshot
            
        Returns:
            Analysis results including localization
        """
        # Add current state to trace if provided
        if page_source or screenshot_path:
            ui_state = {"page_source_length": len(page_source) if page_source else 0}
            self.add_trace_step(
                action={"type": "bug_detected", "description": bug_report[:100]},
                ui_state=ui_state,
                screenshot_path=screenshot_path
            )
            
        # Perform localization
        localization_results = self.localize_bug(bug_report, use_trace=True, verbose=False)
        
        # Extract GUI terms for context
        gui_extractor = GUIDataExtractor(self.execution_trace)
        
        analysis = {
            "bug_report": bug_report,
            "timestamp": datetime.now().isoformat(),
            "trace_steps": len(self.execution_trace["steps"]),
            "screen_components": gui_extractor.sc_terms,
            "gui_screens": gui_extractor.gs_terms,
            "localization": {
                "top_files": [
                    {
                        "path": r.file_path,
                        "score": round(r.similarity_score, 4),
                        "boosted": r.is_boosted
                    }
                    for r in localization_results[:5]
                ],
                "total_ranked": len(localization_results)
            }
        }
        
        return analysis
        
    def generate_report(self, output_path: Optional[str] = None) -> str:
        """
        Generate a bug localization report.
        
        Args:
            output_path: Optional path to save the report
            
        Returns:
            Report as JSON string
        """
        report = {
            "generated_at": datetime.now().isoformat(),
            "execution_trace_summary": {
                "start": self.execution_trace.get("start_time"),
                "end": self.execution_trace.get("end_time"),
                "steps": len(self.execution_trace.get("steps", []))
            },
            "bugs_analyzed": len(self.localization_results),
            "localizations": self.localization_results
        }
        
        report_json = json.dumps(report, indent=2)
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_json)
            print(f"Report saved to: {output_path}")
            
        return report_json
        
    def save_trace(self, output_path: str):
        """
        Save the execution trace to a file.
        
        Args:
            output_path: Path to save the trace JSON
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.execution_trace, f, indent=2)
        print(f"Trace saved to: {output_path}")
        
    def load_trace(self, input_path: str):
        """
        Load an execution trace from a file.
        
        Args:
            input_path: Path to the trace JSON
        """
        with open(input_path, 'r', encoding='utf-8') as f:
            self.execution_trace = json.load(f)
        print(f"Trace loaded from: {input_path}")


def create_bug_report_from_detection(
    detection_output: str,
    ui_state: Optional[Dict[str, Any]] = None,
    action_history: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Create a structured bug report from agent detection output.
    
    Args:
        detection_output: Raw detection output from the agent
        ui_state: Current UI state information
        action_history: Recent action history
        
    Returns:
        Formatted bug report string
    """
    lines = [detection_output]
    
    if ui_state:
        activity = ui_state.get("activity", ui_state.get("current_screen", "Unknown"))
        lines.append(f"\nScreen: {activity}")
        
        components = ui_state.get("visible_components", [])
        if components:
            lines.append(f"Components: {', '.join(components[:10])}")
            
    if action_history:
        lines.append("\nRecent actions:")
        for action in action_history[-5:]:
            action_type = action.get("action", "unknown")
            target = action.get("element_id", "unknown")
            lines.append(f"  - {action_type} on {target}")
            
    return "\n".join(lines)


# Singleton instance for easy integration
_integration_instance: Optional[BugLocalizationIntegration] = None


def get_integration(source_code_dir: Optional[str] = None) -> BugLocalizationIntegration:
    """
    Get or create the bug localization integration instance.
    
    Args:
        source_code_dir: Optional source code directory to set
        
    Returns:
        BugLocalizationIntegration instance
    """
    global _integration_instance
    
    if _integration_instance is None:
        _integration_instance = BugLocalizationIntegration(source_code_dir)
    elif source_code_dir:
        _integration_instance.source_code_dir = source_code_dir
        
    return _integration_instance


if __name__ == "__main__":
    # Demo usage
    print("Bug Localization Integration Demo")
    print("=" * 50)
    
    # Create integration (would normally set source_code_dir)
    integration = BugLocalizationIntegration()
    
    # Simulate a trace
    integration.start_trace()
    
    integration.add_trace_step(
        action={"action": "click", "element_id": "login_button"},
        ui_state={"activity": "LoginActivity", "fragment": "LoginFragment"}
    )
    
    integration.add_trace_step(
        action={"action": "input", "element_id": "username_field", "text": "test"},
        ui_state={"activity": "LoginActivity"}
    )
    
    integration.end_trace()
    
    # Show trace
    print("\nExecution Trace:")
    print(json.dumps(integration.execution_trace, indent=2))
