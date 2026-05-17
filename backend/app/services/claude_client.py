import json
import os
import anthropic


def _load_cc_switch_config():
    """Read API config from cc-switch settings (~/.claude/settings.json)."""
    settings_path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        env = data.get("env", {})
        base_url = env.get("ANTHROPIC_BASE_URL", "")
        api_key = env.get("ANTHROPIC_AUTH_TOKEN", "")
        model = env.get("ANTHROPIC_MODEL", "mimo-v2-pro")
        # Strip context window suffix like [1m], [200k] etc
        import re
        model = re.sub(r'\[.*?\]$', '', model).strip()
        if base_url and api_key:
            return {"base_url": base_url, "api_key": api_key, "model": model}
    except Exception:
        pass
    return None


class AIClient:
    def __init__(self):
        # Try cc-switch config first
        cc = _load_cc_switch_config()
        if cc:
            self.client = anthropic.Anthropic(
                api_key=cc["api_key"],
                base_url=cc["base_url"],
            )
            self.model = cc["model"]
            self.source = "cc-switch"
            return

        # Fallback to .env config
        from app.config import settings
        if settings.ai_api_key and settings.ai_api_key != "your_api_key_here":
            self.client = anthropic.Anthropic(
                api_key=settings.ai_api_key,
                base_url=settings.ai_base_url,
            )
            self.model = settings.ai_model_name
            self.source = "env"
        else:
            self.client = None
            self.model = "unknown"
            self.source = "none"

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        return self.chat(system, [{"role": "user", "content": user}], max_tokens)

    def chat(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        if not self.client:
            raise RuntimeError("AI not configured. Check cc-switch or .env settings.")

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        # Extract text blocks, fallback to thinking blocks if no text
        texts = []
        thinkings = []
        for block in resp.content:
            if hasattr(block, "text"):
                texts.append(block.text)
            elif block.type == "thinking" and hasattr(block, "thinking"):
                thinkings.append(block.thinking)
        result = "\n".join(texts) if texts else "\n".join(thinkings)
        return result if result else "[No response]"


claude_client = AIClient()
