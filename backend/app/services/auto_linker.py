"""Auto-relationship detection via keyword overlap (zero LLM cost).

Inspired by GBrain's approach of rule-based link extraction.
Uses jieba for Chinese word segmentation + Jaccard similarity.
"""

import re
from typing import List, Tuple


def _extract_keywords(text: str) -> set:
    """Extract keywords from text (Chinese + English)."""
    try:
        import jieba
        words = set(jieba.cut_for_search(text))
    except ImportError:
        # Fallback: simple split
        words = set(re.findall(r'[\w一-鿿]+', text.lower()))

    # Filter: keep words with len >= 2, skip common stop words
    stop_words = {
        '什么', '怎么', '为什么', '哪些', '如何', '分别', '区别', '常见',
        '有什么', '是什么', '一下', '通常', '情况', '可以', '就是', '这个',
        '那个', '不是', '因为', '所以', '但是', '而且', '或者', '如果',
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'can', 'shall', 'to', 'of',
        'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
        'about', 'between', 'through', 'after', 'before', 'during',
    }
    return set(w for w in words if len(w) >= 2 and w not in stop_words)


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Calculate Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


def detect_links(
    source_title: str,
    source_content: str,
    candidates: List[dict],
    threshold: float = 0.12,
    max_results: int = 5,
) -> List[dict]:
    """
    Detect potential links between a source node and candidate nodes.

    Args:
        source_title: Title of the source node
        source_content: Content of the source node
        candidates: List of dicts with keys: id, title, content (or summary)
        threshold: Minimum Jaccard similarity to consider as a link
        max_results: Maximum number of results to return

    Returns:
        List of dicts with: target_id, similarity, shared_keywords
    """
    # Combine title (weighted 3x) and content for keyword extraction
    source_text = f"{source_title} {source_title} {source_title} {source_content[:2000]}"
    source_keywords = _extract_keywords(source_text)

    if not source_keywords:
        return []

    results = []
    for cand in candidates:
        cand_text = f"{cand['title']} {cand['title']} {cand['title']} {cand.get('content', '')[:2000]}"
        cand_keywords = _extract_keywords(cand_text)

        sim = _jaccard_similarity(source_keywords, cand_keywords)
        if sim >= threshold:
            shared = source_keywords & cand_keywords
            # Filter out very short shared words
            meaningful_shared = [w for w in shared if len(w) >= 2]
            if meaningful_shared:
                results.append({
                    "target_id": cand["id"],
                    "target_title": cand["title"],
                    "similarity": round(sim, 3),
                    "shared_keywords": list(meaningful_shared)[:8],
                })

    # Sort by similarity descending
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:max_results]


def detect_links_for_node(node_id: int, node_title: str, node_content: str, all_nodes: List[dict]) -> List[dict]:
    """
    Convenience function: detect links between one node and all others.

    Args:
        node_id: ID of the source node
        node_title: Title of the source node
        node_content: Content of the source node
        all_nodes: List of dicts with keys: id, title, content

    Returns:
        List of suggested links
    """
    candidates = [n for n in all_nodes if n["id"] != node_id]
    return detect_links(node_title, node_content, candidates)
