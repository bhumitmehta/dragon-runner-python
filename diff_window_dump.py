import xml.etree.ElementTree as ET
from collections import deque

# Paths to the XML files
dump_a = 'window_dump.xml'
dump_b = 'window_dump1.xml'

# Attributes to compare for each node
ATTRS = ['class', 'resource-id', 'content-desc', 'text', 'bounds']


def node_signature(node):
    """Create a tuple signature for a node based on key attributes."""
    return tuple(node.attrib.get(attr, '') for attr in ATTRS)


def walk_tree(root):
    """Yield node signatures in BFS order."""
    queue = deque([root])
    while queue:
        node = queue.popleft()
        yield node_signature(node)
        queue.extend(list(node))


def diff_xml(file_a, file_b):

    tree_a = ET.parse(file_a)
    tree_b = ET.parse(file_b)
    root_a = tree_a.getroot()
    root_b = tree_b.getroot()

    nodes_a = list(walk_tree(root_a))
    nodes_b = list(walk_tree(root_b))

    set_a = set(nodes_a)
    set_b = set(nodes_b)

    added = set_b - set_a
    removed = set_a - set_b

    print(f"Nodes added in {file_b}:")
    for node in added:
        print("  +", dict(zip(ATTRS, node)))
    print()

    print(f"Nodes removed in {file_b}:")
    for node in removed:
        print("  -", dict(zip(ATTRS, node)))
    print()

    # Compare nodes by position for attribute-level changes
    print("Attribute changes for nodes at the same position:")
    min_len = min(len(nodes_a), len(nodes_b))
    for i in range(min_len):
        node_a = nodes_a[i]
        node_b = nodes_b[i]
        if node_a != node_b:
            diffs = []
            for idx, attr in enumerate(ATTRS):
                if node_a[idx] != node_b[idx]:
                    diffs.append(f"{attr}: '{node_a[idx]}' -> '{node_b[idx]}'")
            if diffs:
                print(f"  Node {i}:")
                for d in diffs:
                    print(f"    {d}")
    print()

if __name__ == '__main__':
    diff_xml(dump_a, dump_b)
