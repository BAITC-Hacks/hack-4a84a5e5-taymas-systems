"""Обёртка над LLM: единая точка вызова моделей, провайдер меняется настройкой.

Все вызовы моделей идут только отсюда — app/ai.py строит на этом доменную логику
(вопросы, сборка карточки). Отсутствие ключа — не ошибка, а режим: llm_available()
возвращает False, и вызывающий код переключается на локальную заглушку.
"""

import json

import pydantic
from openai import OpenAI, OpenAIError

from app.config import settings

_PROVIDERS = {"openai", "nvidia"}


class LLMConfigError(Exception):
    """Провайдер не поддерживается или для него не задан ключ."""


class LLMResponseError(Exception):
    """Модель вернула невалидный ответ (JSON/схема) или запрос не удался после ретраев SDK."""


def _provider_key(provider: str) -> str:
    if provider == "openai":
        return settings.OPENAI_API_KEY
    if provider == "nvidia":
        return settings.NVIDIA_API_KEY
    raise LLMConfigError(
        f"Неизвестный LLM_PROVIDER={provider!r}, ожидается 'openai' или 'nvidia'"
    )


def llm_available() -> bool:
    """Есть ли непустой ключ для провайдера, выбранного в settings.LLM_PROVIDER."""
    return bool(_provider_key(settings.LLM_PROVIDER).strip())


class LLMClient:
    def __init__(self) -> None:
        provider = settings.LLM_PROVIDER
        key = _provider_key(provider)
        if not key.strip():
            raise LLMConfigError(
                f"Нет ключа для провайдера {provider!r}: заполните "
                f"{provider.upper()}_API_KEY в .env"
            )
        base_url = settings.OPENAI_BASE_URL if provider == "openai" else settings.NVIDIA_BASE_URL
        model = settings.OPENAI_MODEL if provider == "openai" else settings.NVIDIA_MODEL
        self._provider = provider
        self._model = model
        self._client = OpenAI(api_key=key, base_url=base_url, timeout=30, max_retries=2)

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: type[pydantic.BaseModel] | None = None,
        temperature: float = 0.2,
    ) -> str | pydantic.BaseModel:
        if json_schema is None:
            return self._complete_text(messages, temperature)
        return self._complete_json(messages, json_schema, temperature)

    def _complete_text(self, messages: list[dict[str, str]], temperature: float) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self._model, messages=messages, temperature=temperature,
            )
        except OpenAIError as exc:
            raise LLMResponseError(f"Запрос к {self._provider} не удался: {exc}") from exc
        content = response.choices[0].message.content
        if not content:
            raise LLMResponseError(f"{self._provider} вернул пустой ответ")
        return content

    def _complete_json(
        self,
        messages: list[dict[str, str]],
        json_schema: type[pydantic.BaseModel],
        temperature: float,
    ) -> pydantic.BaseModel:
        schema_messages = self._with_schema_instruction(messages, json_schema)
        try:
            return self._request_json(schema_messages, json_schema, temperature)
        except (pydantic.ValidationError, json.JSONDecodeError, LLMResponseError) as exc:
            retry_messages = schema_messages + [{
                "role": "user",
                "content": f"Ответ не прошёл проверку схемы: {exc}. Пришли только исправленный валидный JSON.",
            }]
            try:
                return self._request_json(retry_messages, json_schema, temperature)
            except (pydantic.ValidationError, json.JSONDecodeError, LLMResponseError) as exc2:
                raise LLMResponseError(
                    f"{self._provider} дважды вернул невалидный ответ: {exc2}"
                ) from exc2

    def _with_schema_instruction(
        self, messages: list[dict[str, str]], json_schema: type[pydantic.BaseModel],
    ) -> list[dict[str, str]]:
        instruction = f"Отвечай только JSON по схеме: {json_schema.model_json_schema()}"
        out = list(messages)
        if out and out[0].get("role") == "system":
            out[0] = {"role": "system", "content": out[0]["content"] + "\n\n" + instruction}
        else:
            out.insert(0, {"role": "system", "content": instruction})
        return out

    def _request_json(
        self,
        messages: list[dict[str, str]],
        json_schema: type[pydantic.BaseModel],
        temperature: float,
    ) -> pydantic.BaseModel:
        try:
            if self._provider == "openai":
                response = self._client.chat.completions.parse(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    response_format=json_schema,
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise LLMResponseError("openai не смог разобрать ответ по заданной схеме")
                return parsed
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise LLMResponseError(f"{self._provider} вернул пустой ответ")
            return json_schema.model_validate_json(content)
        except OpenAIError as exc:
            raise LLMResponseError(f"Запрос к {self._provider} не удался: {exc}") from exc


_client: LLMClient | None = None


def get_client() -> LLMClient:
    """Синглтон клиента. Без ключа для выбранного провайдера — LLMConfigError."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
