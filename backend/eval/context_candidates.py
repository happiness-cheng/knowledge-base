"""冻结语料上的相邻块候选；相邻关系只取服务端源文件顺序。"""

from collections import defaultdict

from eval.retrieval_candidates import RankedChunk


def expand_neighbors(ranked, ordered_chunks, *, user_id, enabled=False):
    documents = defaultdict(list)
    canonical = {}
    for chunk in ordered_chunks:
        if chunk.user_id != user_id:
            continue
        if chunk.chunk_id in canonical:
            raise ValueError('duplicate source chunk identity')
        canonical[chunk.chunk_id] = chunk
        documents[chunk.node_id].append(chunk)
    positions = {chunk.chunk_id: (chunks, index) for chunks in documents.values()
                 for index, chunk in enumerate(chunks)}
    anchors = []
    seen = set()
    for item in ranked:
        if item.chunk.user_id != user_id or item.chunk.chunk_id in seen:
            continue
        if canonical.get(item.chunk.chunk_id) != item.chunk:
            raise ValueError('ranked chunk differs from authorized source snapshot')
        seen.add(item.chunk.chunk_id)
        anchors.append(item)
    if not enabled:
        return anchors, {'enabled': False, 'added_neighbors': 0}
    result, included = [], set()
    anchor_ids = {item.chunk.chunk_id for item in anchors}
    for item in anchors:
        chunks, index = positions[item.chunk.chunk_id]
        candidates = [item]
        for offset in (-1, 1):
            neighbor = index + offset
            if 0 <= neighbor < len(chunks):
                candidates.append(RankedChunk(chunks[neighbor], item.score, 'adjacent'))
        for candidate in candidates:
            if candidate.chunk.chunk_id not in included:
                included.add(candidate.chunk.chunk_id)
                result.append(candidate)
    return result, {'enabled': True, 'added_neighbors': len(included - anchor_ids),
                    'policy': 'anchor then previous then next; radius1; same owner/document only'}
