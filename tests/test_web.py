from fastapi.testclient import TestClient


def test_business_constructor_creates_editable_card(tmp_path):
    from app import store as store_module
    from app.main import app

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    client = TestClient(app)
    assert client.get("/business/new").status_code == 200

    questions = client.post("/business/new", data={"text": "A service is needed to process resident requests", "industry": "Other"})
    assert questions.status_code == 200
    assert "answer_0" in questions.text

    draft = list(store_module.get_store().drafts.values())[-1]
    response = client.post(f"/business/drafts/{draft.id}/answers", data={f"answer_{i}": f"Detailed answer {i}" for i, _ in enumerate(draft.questions)}, follow_redirects=False)
    assert response.status_code == 303
    editor = client.get(response.headers["location"])
    assert editor.status_code == 200
    assert "Предварительный балл" in editor.text
    assert 'name="success_criteria"' in editor.text


def _weak_card(tmp_path):
    from app import store as store_module
    from app.models import Card, new_id

    store = store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    card = store.add_card(Card(
        id=new_id("c"),
        title="Обработка обращений",
        context="Жители пишут обращения в акимат, их разбирают вручную",
        need="Нужно автоматически распределять обращения по отделам",
    ))
    return store, card


def test_edit_recalculates_preview_without_touching_confirmed_score(tmp_path):
    from app.main import app
    from app.rating import compute_rating

    store, card = _weak_card(tmp_path)
    client = TestClient(app)
    before = compute_rating(card).score
    confirmed_before = card.score

    response = client.post(f"/business/cards/{card.id}/edit", data={
        **{f: getattr(card, f) for f in ("title", "context", "need")},
        "data": "Выгрузка 5000 обращений за 2025 год в CSV: текст, дата, отдел",
        "success_criteria": "Не менее 85% обращений распределяются в верный отдел",
        "industry": "Госуслуги",
    })
    assert response.status_code == 200

    saved = store.get_card(card.id)
    after = compute_rating(saved).score
    assert after > before
    assert f"было {before} → стало {after}" in response.text
    assert saved.score == confirmed_before
    assert saved.confirmed is False
    assert saved.industry == "Госуслуги"


def test_publish_requires_confirmation(tmp_path):
    from app.main import app

    store, card = _weak_card(tmp_path)
    client = TestClient(app)

    response = client.post(f"/business/cards/{card.id}/publish", data={}, follow_redirects=False)
    assert response.status_code == 200
    assert "Подтверждаю, что карточка составлена верно" in response.text
    assert store.get_card(card.id).status == "draft"
    assert card.id not in [c.id for c in store.list_cards()]


def test_publish_with_confirmation_scores_and_lists_card(tmp_path):
    from app.main import app
    from app.rating import compute_rating

    store, card = _weak_card(tmp_path)
    client = TestClient(app)

    response = client.post(f"/business/cards/{card.id}/publish", data={"confirmed": "on"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/tasks/{card.id}"

    saved = store.get_card(card.id)
    rating = compute_rating(saved)
    assert saved.status == "published"
    assert saved.confirmed is True
    assert saved.score == rating.score
    assert saved.level == rating.level
    assert saved.published_at is not None
    assert card.id in [c.id for c in store.list_cards()]


def test_published_card_edit_then_confirm_changes(tmp_path):
    from app.main import app

    store, card = _weak_card(tmp_path)
    client = TestClient(app)
    client.post(f"/business/cards/{card.id}/publish", data={"confirmed": "on"})
    published = store.get_card(card.id)
    first_score, first_published_at = published.score, published.published_at

    editor = client.post(f"/business/cards/{card.id}/edit", data={"data": "Выгрузка 5000 обращений в CSV"})
    assert "Подтвердить изменения" in editor.text
    assert store.get_card(card.id).score == first_score

    client.post(f"/business/cards/{card.id}/publish", data={"confirmed": "on"})
    saved = store.get_card(card.id)
    assert saved.status == "published"
    assert saved.score > first_score
    assert saved.published_at == first_published_at

