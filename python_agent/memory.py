import datetime
import hashlib


class Memory:
    def __init__(self):
        self.short_term_memory = []  # Stores (action, state) tuples for the current session
        self.long_term_memory = []   # Stores summaries of past sessions or critical findings

    def add_to_short_term(self, action, state_summary):
        """Adds an action and its resulting state to short-term memory."""
        timestamp = datetime.datetime.now()
        self.short_term_memory.append({
            "timestamp": timestamp,
            "action": action,
            "state_summary": state_summary
        })

    def add_state_signature(self, signature: str):
        timestamp = datetime.datetime.now()
        self.short_term_memory.append({
            "timestamp": timestamp,
            "action": {"action": "_state"},
            "state_summary": signature,
        })

    def get_short_term_history(self, last_n=5):
        """Retrieves the last N actions and states from short-term memory."""
        return self.short_term_memory[-last_n:]

    def has_been_in_loop(self, state_summary, lookback=3):
        """
        Checks if the agent has been in a loop by seeing if the same state
        has appeared multiple times recently.
        """
        if len(self.short_term_memory) < lookback:
            return False
        
        recent_states = [mem["state_summary"] for mem in self.short_term_memory[-lookback:]]
        return recent_states.count(state_summary) > 1

    def count_recent_state(self, signature: str, window: int = 10) -> int:
        recent = [m["state_summary"] for m in self.short_term_memory[-window:]]
        return recent.count(signature)

    def clear_short_term(self):
        """Clears the short-term memory, typically at the end of a session."""
        self.short_term_memory = []

    def add_to_long_term(self, finding):
        """Adds a significant finding (like a bug) to long-term memory."""
        timestamp = datetime.datetime.now()
        self.long_term_memory.append({
            "timestamp": timestamp,
            "finding": finding
        })


def state_signature_from_xml(page_source: str) -> str:
    normalized = " ".join((page_source or "").split())
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]
