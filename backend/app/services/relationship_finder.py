import json
from app.services.claude_client import claude_client

SYSTEM_PROMPT = """You are a knowledge relationship analyzer. Given a list of knowledge nodes (title + summary), identify meaningful relationships between them.

Return ONLY valid JSON array:
[
  {
    "source_title": "exact title of source node",
    "target_title": "exact title of target node",
    "rel_type": "one of: related_to, part_of, leads_to, contradicts, supports, similar_to, prerequisite",
    "strength": 0.8,
    "label": "brief description of the relationship"
  }
]

Only identify STRONG relationships (strength >= 0.6). Return empty array if no strong relationships found.
Max 20 relationships per call."""


def find_relationships_batch(nodes: list) -> list[dict]:
    if len(nodes) < 2:
        return []

    node_info = []
    for n in nodes:
        node_info.append({
            "title": n.title,
            "summary": n.summary or n.content[:200],
        })

    user_text = json.dumps(node_info, ensure_ascii=False, indent=2)
    if len(user_text) > 12000:
        user_text = user_text[:12000]

    try:
        response = claude_client.complete(
            system=SYSTEM_PROMPT,
            user=user_text,
            max_tokens=2048,
        )

        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        return json.loads(response)
    except Exception:
        return []