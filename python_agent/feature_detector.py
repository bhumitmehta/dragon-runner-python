"""Feature Detection & Clustering -- group screens into feature areas.

Phase 5: Cluster screens by shared UI elements and infer feature areas.
Bias exploration toward underexplored feature clusters.

Examples:
- Login cluster: login, reset_password, register screens share auth elements
- Catalog cluster: product_list, product_detail, search share product-related UI
- Cart cluster: cart, checkout, order_confirmation share transaction UI
"""
from __future__ import annotations

from typing import Dict, List, Set, Optional
from collections import defaultdict

from .logging_config import get_logger
from .session_memory import SessionMemory

logger = get_logger("feature_detector")


class FeatureCluster:
    """A group of related screens forming a feature area."""
    
    def __init__(self, cluster_id: str, screens: Set[str], shared_elements: Set[str]):
        self.id = cluster_id
        self.screens = screens  # Set of screen signatures
        self.shared_elements = shared_elements  # Elements present in all/most screens
        self.coverage = 0.0  # 0-1: how many screens in cluster have been visited
    
    def compute_coverage(self, memory: SessionMemory) -> float:
        """Compute coverage of this cluster (screens visited / total screens)."""
        if not self.screens:
            return 0.0
        
        visited = sum(
            1 for sig in self.screens
            if memory.get_screen_visit_count(sig) > 0
        )
        self.coverage = visited / len(self.screens) if self.screens else 0.0
        return self.coverage


class FeatureDetector:
    """Detect and manage feature clusters."""
    
    _MIN_CLUSTER_SIZE = 2
    _MIN_ELEMENT_OVERLAP = 0.5  # 50% element overlap to be in same cluster
    
    @staticmethod
    def cluster_screens(memory: SessionMemory) -> List[FeatureCluster]:
        """Cluster screens by shared elements.
        
        Algorithm:
        1. Build element → screens map
        2. Start with high-frequency elements (appear in 2+ screens)
        3. Group screens that share many elements
        4. Use agglomerative clustering with element overlap threshold
        
        Returns list of FeatureCluster objects.
        """
        if not memory.screens:
            return []
        
        # Build element -> screens map
        element_screens: Dict[str, Set[str]] = defaultdict(set)
        for sig, node in memory.screens.items():
            for elem in node.elements_snapshot:
                element_screens[elem].add(sig)
        
        # Filter to navigation elements (appear in 2+ screens)
        shared_elements = {
            elem: screens
            for elem, screens in element_screens.items()
            if len(screens) >= 2
        }
        
        if not shared_elements:
            return []
        
        # Compute pairwise element overlap between screens
        screens_list = list(memory.screens.keys())
        screen_elements: Dict[str, Set[str]] = {}
        for sig, node in memory.screens.items():
            screen_elements[sig] = set(node.elements_snapshot)
        
        # Build adjacency: screens with high overlap
        clusters = []
        processed = set()
        
        for i, sig1 in enumerate(screens_list):
            if sig1 in processed:
                continue
            
            cluster_screens = {sig1}
            elem1 = screen_elements[sig1]
            
            # Find all screens with high overlap
            for sig2 in screens_list[i+1:]:
                if sig2 in processed:
                    continue
                
                elem2 = screen_elements[sig2]
                if not elem1 or not elem2:
                    continue
                
                # Jaccard similarity
                overlap = len(elem1 & elem2) / (len(elem1 | elem2) + 0.001)
                
                if overlap >= FeatureDetector._MIN_ELEMENT_OVERLAP:
                    cluster_screens.add(sig2)
            
            # Only create cluster if meets minimum size
            if len(cluster_screens) >= FeatureDetector._MIN_CLUSTER_SIZE:
                # Find shared elements
                cluster_elems = set()
                if cluster_screens:
                    cluster_elems = screen_elements[sig1].copy()
                    for sig in cluster_screens:
                        cluster_elems &= screen_elements[sig]
                
                cluster = FeatureCluster(
                    f"cluster_{len(clusters)}",
                    cluster_screens,
                    cluster_elems
                )
                clusters.append(cluster)
                processed.update(cluster_screens)
            else:
                processed.add(sig1)
        
        # Compute coverage for each cluster
        for cluster in clusters:
            cluster.compute_coverage(memory)
            logger.info(
                "Feature cluster %s: %d screens, %d shared elements, coverage=%.1f%%",
                cluster.id, len(cluster.screens), len(cluster.shared_elements),
                cluster.coverage * 100
            )
        
        return clusters
    
    @staticmethod
    def find_underexplored_clusters(
        clusters: List[FeatureCluster],
        threshold: float = 0.5
    ) -> List[FeatureCluster]:
        """Return clusters with coverage below threshold.
        
        These should be biased during exploration.
        """
        return [
            c for c in clusters
            if c.coverage < threshold
        ]
    
    @staticmethod
    def get_feature_bias_score(
        screen_sig: str,
        clusters: List[FeatureCluster]
    ) -> float:
        """Get exploration bias score for a screen based on its cluster coverage.
        
        Returns 0.0-1.0 bonus/penalty:
        - Underexplored cluster: +0.2 to +0.5 bonus
        - Well-explored cluster: -0.1 to 0.0 penalty
        """
        # Find which cluster (if any) this screen belongs to
        for cluster in clusters:
            if screen_sig in cluster.screens:
                # Penalize well-explored clusters
                if cluster.coverage > 0.8:
                    return -0.1
                elif cluster.coverage > 0.5:
                    return 0.0
                else:
                    # Underexplored: bonus proportional to gap
                    return 0.5 * (1.0 - cluster.coverage)
        
        # Unclustered screen: neutral
        return 0.0


if __name__ == "__main__":
    # Example usage
    from pathlib import Path
    
    # Would load real session data here
    print("Feature clustering module ready")
    print(f"Min cluster size: {FeatureDetector._MIN_CLUSTER_SIZE}")
    print(f"Min element overlap: {FeatureDetector._MIN_ELEMENT_OVERLAP}")
