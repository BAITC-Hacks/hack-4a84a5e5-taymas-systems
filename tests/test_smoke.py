"""Смоук-тест скелета: приложение поднимается, сид читается, главная и /health отвечают."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    from app import store as store_module

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    from app.main import app

    return TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ai_mode"] in {"openai", "nvidia", "stub"}
    assert body["teams"] >= 1


def test_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Challenge Hub" in r.text


def test_store_seed_and_catalog_order(tmp_path):
    from app.models import Card
    from app.store import Store

    s = Store(tmp_path / "s.json", "data/seed.json")
    assert len(s.list_cards()) >= 1
    s.add_card(Card(id="c_low", title="Низкий", status="published", score=10, level="draft"))
    s.add_card(Card(id="c_high", title="Высокий", status="published", score=95, level="priority"))
    ids = [c.id for c in s.list_cards()]
    assert ids.index("c_high") < ids.index("c_low")
    assert "c_low" not in [c.id for c in s.list_cards(level="priority")]


def test_rating_and_ai_stubs():
    from app.ai import build_card, generate_questions
    from app.models import Answer, CardFields
    from app.rating import compute_rating

    qs = generate_questions("Нужен бот для студентов", "Образование")
    assert len(qs) >= 3
    empty = compute_rating(CardFields())
    assert empty.score == 0 and empty.level == "draft"
    card = build_card(
        "Нужен бот для студентов",
        "Образование",
        [Answer(field=q.field, question=q.question, answer=f"Развёрнутый ответ на вопрос: {q.question}") for q in qs],
    )
    assert compute_rating(card).score > empty.score
