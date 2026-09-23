"""Тесты обёртки над LLM. Тест с реальным вызовом пропускается без ключа."""

import pytest

from app import llm
from app.config import settings


def test_llm_available_false_without_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert llm.llm_available() is False


def test_llm_available_true_with_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    assert llm.llm_available() is True


def test_unknown_provider_raises_config_error(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "anthropic")
    with pytest.raises(llm.LLMConfigError):
        llm.llm_available()


def test_get_client_without_key_raises_config_error(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(llm, "_client", None)
    with pytest.raises(llm.LLMConfigError):
        llm.get_client()


@pytest.mark.skipif(not settings.OPENAI_API_KEY, reason="нужен OPENAI_API_KEY для реального вызова")
def test_complete_returns_string_with_real_key(monkeypatch):
    monkeypatch.setattr(llm, "_client", None)
    client = llm.get_client()
    result = client.complete([{"role": "user", "content": "Ответь одним словом: ok"}])
    assert isinstance(result, str)
    assert result.strip()
