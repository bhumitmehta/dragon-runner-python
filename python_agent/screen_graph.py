"""
ScreenGraph -- NetworkX-backed directed graph of app screens & transitions.

This module provides:
- Real graph algorithms: shortest path, reachability, cycles, hub detection
- Rich per-node metadata: description, screenshot, scripts, visit stats
- Rich per-edge metadata: element ID, action type, reliability score
- Frontend-ready JSON/D3 export for visualisation dashboards
- Persistent: rebuilt from KnowledgeBase on startup, updated live

Architecture:
    TinyDB (persistence)  →  NetworkX DiGraph (runtime)  →  Explorer / API
         ↑                          ↑
    KB.screens table          rebuilt on load()
    KB.element_behaviors      updated on every add_transition()
"""
from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from .logging_config import get_logger

logger = get_logger("screen_graph")


class ScreenGraph:
    """In-memory directed graph of screens with rich metadata.

    Each **node** (screen) carries:
      - ``sig``           : screen state signature (node ID)
      - ``name``          : human-readable label
      - ``description``   : LLM-generated screen description (from VLM)
      - ``screenshot``    : path to latest screenshot file
      - ``elements``      : list of element IDs visible on this screen
      - ``input_fields``  : list of input field locators
      - ``scripts``       : list of test script IDs that run from this screen
      - ``visit_count``   : total visits across all runs
      - ``first_seen``    : ISO timestamp
      - ``last_seen``     : ISO timestamp
      - ``tags``          : user/agent labels (e.g. "login", "home")
      - ``todo``          : list of things still to test on this screen

    Each **edge** (transition) carries:
      - ``element_id``    : the UI element that triggers the transition
      - ``action_type``   : click / long_press / input / scroll / back
      - ``click_count``   : how often this transition has been triggered
      - ``reliability``   : click_count / total_attempts  (0.0 – 1.0)
      - ``first_seen``    : ISO timestamp
      - ``last_seen``     : ISO timestamp
    """

    def __init__(self):
        self._g: nx.DiGraph = nx.DiGraph()

    # ── Load / rebuild from persistence ──────────────────────────────

    def load_from_kb(self, kb) -> int:
        """Rebuild the in-memory graph from a KnowledgeBase instance.

        Call this once at startup (``kb.start_run()``) so the graph
        contains everything learned from previous sessions.

        Returns the number of edges loaded.
        """
        self._g.clear()
        all_screens = kb.screens.all()
        edge_count = 0

        for scr in all_screens:
            sig = scr.get("signature", "")
            if not sig:
                continue
            self._g.add_node(sig, **{
                "name": scr.get("name", ""),
                "description": scr.get("description", ""),
                "screenshot": scr.get("screenshot", ""),
                "elements": scr.get("elements", []),
                "input_fields": scr.get("input_fields", []),
                "scripts": scr.get("scripts", []),
                "visit_count": scr.get("visit_count", 0),
                "first_seen": scr.get("first_seen", ""),
                "last_seen": scr.get("last_seen", ""),
                "tags": scr.get("tags", []),
                "todo": scr.get("todo", []),
            })

            for action_desc, target_sig in scr.get("transitions", {}).items():
                if not target_sig:
                    continue
                # Look up behavior data for reliability
                behavior = kb.get_element_behavior(action_desc, sig)
                cc = behavior.get("click_count", 1) if behavior else 1
                nc = behavior.get("nav_count", 1) if behavior else 1
                self._g.add_edge(sig, target_sig, **{
                    "element_id": action_desc,
                    "action_type": (behavior or {}).get("action_type", "click"),
                    "click_count": cc,
                    "reliability": nc / max(cc, 1),
                    "first_seen": (behavior or {}).get("first_seen", ""),
                    "last_seen": (behavior or {}).get("last_seen", ""),
                })
                edge_count += 1

        logger.info(
            "ScreenGraph loaded: %d nodes, %d edges",
            self._g.number_of_nodes(), edge_count,
        )
        return edge_count

    # ── Live updates ─────────────────────────────────────────────────

    def add_screen(
        self,
        sig: str,
        *,
        name: str = "",
        description: str = "",
        screenshot: str = "",
        elements: Optional[List[str]] = None,
        input_fields: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ):
        """Add or update a screen node."""
        now = datetime.utcnow().isoformat() + "Z"
        if self._g.has_node(sig):
            data = self._g.nodes[sig]
            data["visit_count"] = data.get("visit_count", 0) + 1
            data["last_seen"] = now
            if name:
                data["name"] = name
            if description:
                data["description"] = description
            if screenshot:
                data["screenshot"] = screenshot
            if elements is not None:
                data["elements"] = elements[:60]
            if input_fields is not None:
                data["input_fields"] = input_fields
            if tags:
                data["tags"] = list(set(data.get("tags", []) + tags))
        else:
            self._g.add_node(sig, **{
                "name": name,
                "description": description,
                "screenshot": screenshot,
                "elements": (elements or [])[:60],
                "input_fields": input_fields or [],
                "scripts": [],
                "visit_count": 1,
                "first_seen": now,
                "last_seen": now,
                "tags": tags or [],
                "todo": [],
            })

    def add_transition(
        self,
        from_sig: str,
        to_sig: str,
        element_id: str,
        *,
        action_type: str = "click",
        reliability: float = 1.0,
    ):
        """Add or update a transition edge."""
        now = datetime.utcnow().isoformat() + "Z"
        # Ensure both nodes exist
        if not self._g.has_node(from_sig):
            self.add_screen(from_sig)
        if not self._g.has_node(to_sig):
            self.add_screen(to_sig)

        if self._g.has_edge(from_sig, to_sig):
            data = self._g.edges[from_sig, to_sig]
            data["click_count"] = data.get("click_count", 0) + 1
            data["reliability"] = reliability
            data["last_seen"] = now
        else:
            self._g.add_edge(from_sig, to_sig, **{
                "element_id": element_id,
                "action_type": action_type,
                "click_count": 1,
                "reliability": reliability,
                "first_seen": now,
                "last_seen": now,
            })

    def set_screen_description(self, sig: str, description: str):
        """Store an LLM-generated screen description (from VLM screenshot analysis)."""
        if self._g.has_node(sig):
            self._g.nodes[sig]["description"] = description

    def set_screen_screenshot(self, sig: str, screenshot_path: str):
        """Update the latest screenshot path for a screen."""
        if self._g.has_node(sig):
            self._g.nodes[sig]["screenshot"] = screenshot_path

    def add_screen_script(self, sig: str, script_id: int):
        """Associate a test/verification script with a screen."""
        if self._g.has_node(sig):
            scripts = self._g.nodes[sig].setdefault("scripts", [])
            if script_id not in scripts:
                scripts.append(script_id)

    def add_screen_todo(self, sig: str, todo_item: str):
        """Add a test-todo note to a screen."""
        if self._g.has_node(sig):
            todos = self._g.nodes[sig].setdefault("todo", [])
            if todo_item not in todos:
                todos.append(todo_item)

    def set_screen_tags(self, sig: str, tags: List[str]):
        """Overwrite tags for a screen."""
        if self._g.has_node(sig):
            self._g.nodes[sig]["tags"] = tags

    # ── Graph algorithms ─────────────────────────────────────────────

    def shortest_path(self, from_sig: str, to_sig: str) -> Optional[List[str]]:
        """Return the shortest list of screen sigs from source to target,
        or None if unreachable.
        """
        try:
            return nx.shortest_path(self._g, from_sig, to_sig)
        except (nx.NodeNotFound, nx.NetworkXNoPath):
            return None

    def shortest_action_path(self, from_sig: str, to_sig: str) -> Optional[List[Dict[str, str]]]:
        """Return step-by-step actions to navigate from one screen to another.

        Each step is: {from, to, element_id, action_type}.
        Returns None if no path exists.
        """
        path = self.shortest_path(from_sig, to_sig)
        if not path or len(path) < 2:
            return None
        steps = []
        for i in range(len(path) - 1):
            edge = self._g.edges.get((path[i], path[i + 1]), {})
            steps.append({
                "from": path[i],
                "to": path[i + 1],
                "element_id": edge.get("element_id", ""),
                "action_type": edge.get("action_type", "click"),
            })
        return steps

    def unreachable_screens(self, root_sig: str) -> List[str]:
        """Return screen sigs NOT reachable from the root (home) screen."""
        if root_sig not in self._g:
            return list(self._g.nodes)
        reachable = nx.descendants(self._g, root_sig) | {root_sig}
        return [s for s in self._g.nodes if s not in reachable]

    def dead_end_screens(self) -> List[str]:
        """Return screens with no outgoing transitions (potential dead ends)."""
        return [n for n in self._g.nodes if self._g.out_degree(n) == 0]

    def hub_screens(self, top_n: int = 5) -> List[Tuple[str, float]]:
        """Return the top-N hub screens by betweenness centrality.

        Hub screens are screens that sit on many shortest paths between
        other screens -- they're the most important for navigation.
        """
        if self._g.number_of_nodes() < 3:
            return [(n, 0.0) for n in self._g.nodes]
        centrality = nx.betweenness_centrality(self._g)
        ranked = sorted(centrality.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_n]

    def find_cycles(self, max_length: int = 6) -> List[List[str]]:
        """Return simple cycles up to max_length nodes.

        Useful for finding navigation loops in the app.
        """
        cycles = []
        try:
            for cycle in nx.simple_cycles(self._g, length_bound=max_length):
                cycles.append(cycle)
                if len(cycles) > 50:
                    break  # cap to avoid explosion
        except Exception:
            pass
        return cycles

    def coverage_gaps(self) -> Dict[str, Any]:
        """Analyse the graph to find testing gaps.

        Returns:
        - unvisited_screens: screens with visit_count == 0
        - low_visit_screens: screens with visit_count <= 2
        - dead_ends: screens with no outgoing edges
        - untested_screens: screens with no associated scripts
        - todo_items: aggregated todos across all screens
        """
        unvisited = []
        low_visit = []
        untested = []
        all_todos = []

        for sig, data in self._g.nodes(data=True):
            vc = data.get("visit_count", 0)
            if vc == 0:
                unvisited.append(sig)
            elif vc <= 2:
                low_visit.append(sig)
            if not data.get("scripts"):
                untested.append(sig)
            for todo in data.get("todo", []):
                all_todos.append({"screen": sig, "todo": todo})

        return {
            "unvisited_screens": unvisited,
            "low_visit_screens": low_visit,
            "dead_ends": self.dead_end_screens(),
            "untested_screens": untested,
            "todo_items": all_todos,
            "total_screens": self._g.number_of_nodes(),
            "total_transitions": self._g.number_of_edges(),
        }

    def screen_distance_matrix(self) -> Dict[str, Dict[str, int]]:
        """Return all-pairs shortest path lengths (useful for frontend heatmaps)."""
        try:
            return dict(nx.all_pairs_shortest_path_length(self._g))
        except Exception:
            return {}

    # ── Query helpers ────────────────────────────────────────────────

    def get_screen(self, sig: str) -> Optional[Dict[str, Any]]:
        """Return all metadata for a screen node."""
        if not self._g.has_node(sig):
            return None
        data = dict(self._g.nodes[sig])
        data["sig"] = sig
        data["out_edges"] = [
            {"target": t, **self._g.edges[sig, t]}
            for t in self._g.successors(sig)
        ]
        data["in_edges"] = [
            {"source": s, **self._g.edges[s, sig]}
            for s in self._g.predecessors(sig)
        ]
        return data

    def get_all_screens(self) -> List[Dict[str, Any]]:
        """Return a list of all screen summaries."""
        results = []
        for sig, data in self._g.nodes(data=True):
            results.append({
                "sig": sig,
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "visit_count": data.get("visit_count", 0),
                "tags": data.get("tags", []),
                "element_count": len(data.get("elements", [])),
                "script_count": len(data.get("scripts", [])),
                "todo_count": len(data.get("todo", [])),
                "out_degree": self._g.out_degree(sig),
                "in_degree": self._g.in_degree(sig),
                "has_screenshot": bool(data.get("screenshot")),
            })
        return results

    def get_neighbors(self, sig: str) -> Dict[str, Any]:
        """Return immediate neighbors (1-hop) for a screen."""
        if not self._g.has_node(sig):
            return {"predecessors": [], "successors": []}
        return {
            "predecessors": [
                {"sig": s, "element_id": self._g.edges[s, sig].get("element_id", "")}
                for s in self._g.predecessors(sig)
            ],
            "successors": [
                {"sig": t, "element_id": self._g.edges[sig, t].get("element_id", "")}
                for t in self._g.successors(sig)
            ],
        }

    @property
    def node_count(self) -> int:
        return self._g.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._g.number_of_edges()

    # ── Export (for frontend / dashboard) ────────────────────────────

    def to_d3_json(self) -> Dict[str, Any]:
        """Export graph as D3.js force-directed compatible JSON.

        Format:
        {
            "nodes": [{"id": sig, "name": ..., "visit_count": ..., ...}],
            "links": [{"source": sig_a, "target": sig_b, "element_id": ..., ...}],
            "stats": {summary statistics}
        }
        """
        nodes = []
        for sig, data in self._g.nodes(data=True):
            nodes.append({
                "id": sig,
                "name": data.get("name", sig[:16]),
                "description": data.get("description", ""),
                "screenshot": data.get("screenshot", ""),
                "visit_count": data.get("visit_count", 0),
                "element_count": len(data.get("elements", [])),
                "script_count": len(data.get("scripts", [])),
                "tags": data.get("tags", []),
                "todo": data.get("todo", []),
                "out_degree": self._g.out_degree(sig),
                "in_degree": self._g.in_degree(sig),
            })

        links = []
        for src, tgt, data in self._g.edges(data=True):
            links.append({
                "source": src,
                "target": tgt,
                "element_id": data.get("element_id", ""),
                "action_type": data.get("action_type", "click"),
                "click_count": data.get("click_count", 0),
                "reliability": round(data.get("reliability", 0), 2),
            })

        gaps = self.coverage_gaps()

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "total_screens": self._g.number_of_nodes(),
                "total_transitions": self._g.number_of_edges(),
                "dead_ends": len(gaps["dead_ends"]),
                "untested_screens": len(gaps["untested_screens"]),
                "total_todos": len(gaps["todo_items"]),
            },
        }

    def to_cytoscape_json(self) -> Dict[str, Any]:
        """Export graph for Cytoscape.js (another popular frontend graph lib)."""
        elements = []
        for sig, data in self._g.nodes(data=True):
            elements.append({
                "group": "nodes",
                "data": {
                    "id": sig,
                    "label": data.get("name", sig[:16]),
                    "visit_count": data.get("visit_count", 0),
                    "description": data.get("description", ""),
                    "screenshot": data.get("screenshot", ""),
                    "tags": data.get("tags", []),
                },
            })
        for src, tgt, data in self._g.edges(data=True):
            elements.append({
                "group": "edges",
                "data": {
                    "source": src,
                    "target": tgt,
                    "label": data.get("element_id", ""),
                    "action_type": data.get("action_type", "click"),
                    "reliability": round(data.get("reliability", 0), 2),
                },
            })
        return {"elements": elements}

    def to_mermaid(self) -> str:
        """Export graph as a Mermaid flowchart string (for docs / markdown)."""
        lines = ["graph LR"]
        # Build safe node labels
        node_labels: Dict[str, str] = {}
        for i, (sig, data) in enumerate(self._g.nodes(data=True)):
            label = data.get("name") or sig[:12]
            safe_id = f"S{i}"
            node_labels[sig] = safe_id
            lines.append(f'    {safe_id}["{label}"]')

        for src, tgt, data in self._g.edges(data=True):
            eid = data.get("element_id", "?")
            src_id = node_labels.get(src, src[:8])
            tgt_id = node_labels.get(tgt, tgt[:8])
            lines.append(f"    {src_id} -->|{eid}| {tgt_id}")

        return "\n".join(lines)

    def summary_for_llm(self) -> str:
        """Compact text summary of the graph for LLM prompts."""
        n = self._g.number_of_nodes()
        e = self._g.number_of_edges()
        if n == 0:
            return "Screen graph: empty (no screens discovered)"
        lines = [f"Screen graph: {n} screens, {e} transitions"]
        # Top 5 by visit count
        top = sorted(
            self._g.nodes(data=True),
            key=lambda x: x[1].get("visit_count", 0),
            reverse=True,
        )[:5]
        for sig, data in top:
            name = data.get("name") or sig[:16]
            lines.append(
                f"  {name}: {data.get('visit_count', 0)} visits, "
                f"{self._g.out_degree(sig)} exits, "
                f"{len(data.get('scripts', []))} scripts"
            )
        # Coverage gaps
        gaps = self.coverage_gaps()
        if gaps["dead_ends"]:
            lines.append(f"  Dead-end screens: {len(gaps['dead_ends'])}")
        if gaps["untested_screens"]:
            lines.append(f"  Untested screens: {len(gaps['untested_screens'])}")
        return "\n".join(lines)
