"""Тесты черновика из фото (HAC-58).

Правила: файл проверяется по байтам, без ключа — честный отказ, а не заглушка; только провайдер openai;
describe_photo никогда не бросает; в черновик попадает только описание видимого.
"""

import pytest
from fastapi.testclient import TestClient

from app import vision
from app.llm import LLMResponseError
from app.vision import MAX_DRAFT_CHARS, PhotoDescription, describe_photo, sniff_mime, validate_photo

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64

CASH_DESK = PhotoDescription(
    seen="Кассовый аппарат с надписью «Ошибка E-42» на экране, перед ним очередь из пяти человек",
    problem="На экране кассы ошибка E-42",
    unclear="Как часто это происходит и сколько касс в магазине",
    draft="У нас касса показывает ошибку E-42, перед ней стоит очередь.",
)


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.messages = response, error, None

    def complete(self, messages, *, json_schema=None, temperature=0.2):
        self.messages = messages
        if self.error:
            raise self.error
        assert json_schema is PhotoDescription
        return self.response


def _with_key(monkeypatch, client, provider="openai"):
    monkeypatch.setattr(vision, "llm_available", lambda: True)
    monkeypatch.setattr(vision.settings, "LLM_PROVIDER", provider)
    monkeypatch.setattr(vision, "get_client", lambda: client)


def _no_key(monkeypatch):
    monkeypatch.setattr(vision, "llm_available", lambda: False)


def test_sniff_mime_reads_bytes_not_names():
    assert sniff_mime(PNG) == "image/png"
    assert sniff_mime(JPEG) == "image/jpeg"
    assert sniff_mime(WEBP) == "image/webp"
    assert sniff_mime(b"GIF89a" + b"\x00" * 8) == "image/gif"
    assert sniff_mime(b"<html>photo.png</html>") is None
    assert sniff_mime(b"") is None


def test_validate_rejects_garbage(monkeypatch):
    assert "пустой" in validate_photo(b"")
    assert "не изображение" in validate_photo(b"hello, world")
    monkeypatch.setattr(vision, "MAX_BYTES", 100)
    assert "больше" in validate_photo(PNG + b"\x00" * 200)
    assert validate_photo(PNG) is None


def test_no_key_is_honest_refusal_not_a_stub(monkeypatch):
    _no_key(monkeypatch)
    result = describe_photo(PNG, "Ритейл")
    assert result.ok is False
    assert result.mode == "unavailable"
    assert "ключ" in result.message
    assert result.draft == "" and result.description is None


def test_text_only_provider_declines_before_calling_model(monkeypatch):
    client = _FakeClient(CASH_DESK)
    _with_key(monkeypatch, client, provider="nvidia")
    result = describe_photo(PNG)
    assert result.ok is False and result.mode == "unavailable"
    assert "OpenAI" in result.message
    assert client.messages is None


def test_invalid_file_never_reaches_model(monkeypatch):
    client = _FakeClient(CASH_DESK)
    _with_key(monkeypatch, client)
    result = describe_photo(b"definitely not an image", "Ритейл")
    assert result.mode == "invalid"
    assert client.messages is None


def test_model_description_lands_in_draft_with_photo_in_request(monkeypatch):
    client = _FakeClient(CASH_DESK)
    _with_key(monkeypatch, client)
    result = describe_photo(PNG, "Ритейл")
    assert result.ok is True and result.mode == "openai"
    assert result.draft.startswith(CASH_DESK.draft)
    assert "На фото:" in result.draft and "E-42" in result.draft
    assert "Что похоже на проблему:" in result.draft
    system, user = client.messages
    assert system["role"] == "system" and "только то, что действительно видно" in system["content"]
    text_part, image_part = user["content"]
    assert "Ритейл" in text_part["text"]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_model_failure_never_raises(monkeypatch):
    _with_key(monkeypatch, _FakeClient(error=LLMResponseError("boom")))
    result = describe_photo(JPEG)
    assert result.ok is False and result.mode == "unavailable"
    assert "словами" in result.message

    _with_key(monkeypatch, _FakeClient(error=RuntimeError("transport")))
    result = describe_photo(JPEG)
    assert result.ok is False and result.mode == "unavailable"
    assert "RuntimeError" in result.message


def test_not_a_work_photo_gives_no_draft(monkeypatch):
    _with_key(monkeypatch, _FakeClient(PhotoDescription(seen="Селфи на фоне моря", draft="")))
    result = describe_photo(WEBP)
    assert result.ok is False and result.mode == "openai"
    assert result.draft == ""
    assert "не видно" in result.message and "Селфи" in result.message


def test_long_draft_is_capped(monkeypatch):
    _with_key(monkeypatch, _FakeClient(PhotoDescription(seen="а" * 3000, draft="б" * 3000)))
    result = describe_photo(PNG)
    assert result.ok is True
    assert len(result.draft) <= MAX_DRAFT_CHARS


@pytest.fixture
def client(tmp_path):
    from app import store as store_module
    from app.main import app

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    return TestClient(app)


def test_route_without_key_returns_503_json(client, monkeypatch):
    _no_key(monkeypatch)
    response = client.post("/business/photo", files={"photo": ("cash.png", PNG, "image/png")}, data={"industry": "Ритейл"})
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False and body["mode"] == "unavailable"


def test_route_rejects_garbage_and_missing_file(client, monkeypatch):
    _no_key(monkeypatch)
    garbage = client.post("/business/photo", files={"photo": ("x.png", b"hello", "image/png")})
    assert garbage.status_code == 422 and garbage.json()["mode"] == "invalid"
    missing = client.post("/business/photo", data={"industry": "Ритейл"})
    assert missing.status_code == 422 and missing.json()["ok"] is False


def test_route_returns_draft_and_sanitizes_industry(client, monkeypatch):
    fake = _FakeClient(CASH_DESK)
    _with_key(monkeypatch, fake)
    response = client.post("/business/photo", files={"photo": ("cash.jpg", JPEG, "image/jpeg")}, data={"industry": "Мусор<script>"})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["draft"].startswith(CASH_DESK.draft)
    assert body["description"]["unclear"] == CASH_DESK.unclear
    assert "не указал" in fake.messages[1]["content"][0]["text"]


def test_new_page_has_photo_block(client):
    page = client.get("/business/new")
    assert page.status_code == 200
    assert "Приложить фото" in page.text
    assert "/static/photo.js" in page.text
    assert client.get("/static/photo.js").status_code == 200
    assert client.get("/static/photo.css").status_code == 200
