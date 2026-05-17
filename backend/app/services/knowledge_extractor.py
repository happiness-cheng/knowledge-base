import json
from app.services.claude_client import claude_client


SYSTEM_PROMPT = """You are a knowledge extraction assistant. Given a markdown document, extract structured knowledge.

Return ONLY valid JSON with these fields:
{
  "title": "concise title",
  "summary": "2-3 sentence summary of the key knowledge",
  "category": "one of: Technology, Science, Mathematics, Philosophy, Business, Personal, Other",
  "tags": ["tag1", "tag2", "tag3"],
  "importance": 0.7
}

Importance is 0-1 where 1 is most important foundational knowledge.
Tags should be 3-8 relevant keywords."""


def extract_knowledge(title: str, content: str) -> dict:
    try:
        text = f"# {title}\n\n{content}"
        if len(text) > 8000:
            text = text[:8000] + "\n\n[truncated]"

        response = claude_client.complete(
            system=SYSTEM_PROMPT,
            user=text,
            max_tokens=1024,
        )

        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        return json.loads(response)
    except Exception as e:
        return {
            "title": title,
            "summary": None,
            "category": "Other",
            "tags": [],
            "importance": 0.5,
        }
