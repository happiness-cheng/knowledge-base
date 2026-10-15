from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.services import claude_client as module


def test_default_provider_uses_deepseek_anthropic_protocol():
    config = Settings(_env_file=None)
    assert config.ai_base_url == "https://api.deepseek.com/anthropic"
    assert config.ai_model_name == "deepseek-flash"


@pytest.mark.parametrize("key", ["explicit-test-key", ""])
def test_production_never_reads_personal_provider(monkeypatch, key):
    from app import config

    monkeypatch.setattr(config.settings, "app_env", "production")
    monkeypatch.setattr(config.settings, "ai_api_key", key)
    personal = Mock(side_effect=AssertionError("personal config accessed"))
    factory = Mock()
    monkeypatch.setattr(module, "_load_cc_switch_config", personal)
    monkeypatch.setattr(module.anthropic, "Anthropic", factory)
    client = module.AIClient()
    personal.assert_not_called()
    assert client.source == ("env" if key else "none")
    assert factory.call_count == bool(key)


def test_user_defaults_use_same_protocol(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(module.anthropic, "Anthropic", factory)
    monkeypatch.setattr(module, "decrypt_user_api_key", lambda key: key)
    user = SimpleNamespace(ai_api_key="test-key", ai_base_url="", ai_model_name="")
    client = module.get_client_for_user(user)
    assert client.model == "deepseek-flash"
    assert factory.call_args.kwargs["base_url"] == "https://api.deepseek.com/anthropic"


def test_tools_sdk_disables_implicit_physical_retries():
    client = module.AIClient.__new__(module.AIClient)
    client.client = Mock()
    client.model = "synthetic"
    client.chat_with_tools("system", [{"role": "user", "content": "q"}], [])
    client.client.with_options.assert_called_once_with(max_retries=0, timeout=20)


def test_development_does_not_implicitly_choose_personal_gateway(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, 'app_env', 'development')
    monkeypatch.setattr(config.settings, 'ai_api_key', '')
    personal = Mock(side_effect=AssertionError('implicit personal gateway'))
    monkeypatch.setattr(module, '_load_cc_switch_config', personal)
    assert module.AIClient().source == 'none'
    personal.assert_not_called()
