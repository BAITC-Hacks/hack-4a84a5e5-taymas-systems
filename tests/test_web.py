from fastapi.testclient import TestClient


def test_business_constructor_creates_editable_card(tmp_path):
    from app import store as store_module
    from app.main import app

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    client = TestClient(app)
    assert client.get("/business/new").status_code == 200

    questions = client.post("/business/new", data={"text": "A service is needed to process resident requests", "industry": "Другое"})
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



def _client(tmp_path, **kwargs):
    from app import store as store_module
    from app.main import app

    store = store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    return store, TestClient(app, **kwargs)


def test_long_draft_is_rejected_with_message_not_500(tmp_path):
    store, client = _client(tmp_path)
    drafts_before = len(store.drafts)
    text = "а" * 4001

    response = client.post("/business/new", data={"text": text, "industry": "Образование"})
    assert response.status_code == 400
    assert "Не длиннее 4000 символов" in response.text
    assert text in response.text
    assert len(store.drafts) == drafts_before


def test_unknown_industry_is_rejected_not_silently_replaced(tmp_path):
    store, client = _client(tmp_path)
    drafts_before = len(store.drafts)

    response = client.post("/business/new", data={"text": "Нужен бот для записи студентов", "industry": "мусор"})
    assert response.status_code == 400
    assert "Выберите отрасль из списка" in response.text
    assert "Нужен бот для записи студентов" in response.text
    assert len(store.drafts) == drafts_before


def test_draft_post_redirects_so_refresh_does_not_duplicate(tmp_path):
    store, client = _client(tmp_path)
    drafts_before = len(store.drafts)

    response = client.post("/business/new", data={"text": "Нужен бот для записи студентов", "industry": "Образование"}, follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/business/drafts/")

    assert client.get(location).status_code == 200
    assert client.get(location).status_code == 200
    assert len(store.drafts) == drafts_before + 1


def test_all_answers_skipped_still_builds_card_and_says_so(tmp_path):
    store, client = _client(tmp_path)
    client.post("/business/new", data={"text": "Нужен бот для записи студентов на консультации", "industry": "Образование"})
    draft = max(store.drafts.values(), key=lambda d: d.created_at)

    response = client.post(f"/business/drafts/{draft.id}/answers", data={})
    assert response.status_code == 200
    assert f"заполнено полей: 0 из {len(draft.questions)}" in response.text


def test_too_long_card_field_is_not_saved_and_input_kept(tmp_path):
    from app.main import app

    store, card = _weak_card(tmp_path)
    client = TestClient(app)
    long_data = "д" * 2001

    response = client.post(f"/business/cards/{card.id}/edit", data={"title": "Новое название", "data": long_data})
    assert response.status_code == 400
    assert "Не длиннее 2000 символов" in response.text
    assert long_data in response.text
    saved = store.get_card(card.id)
    assert saved.title == "Обработка обращений"
    assert saved.data == ""

    publish = client.post(f"/business/cards/{card.id}/publish", data={"data": long_data, "confirmed": "on"}, follow_redirects=False)
    assert publish.status_code == 400
    assert store.get_card(card.id).status == "draft"


def test_unknown_url_gives_html_404_not_json(tmp_path):
    _, client = _client(tmp_path)

    response = client.get("/nonexistent")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("text/html")
    assert "Страница не найдена" in response.text
    assert 'href="/catalog"' in response.text

    missing_card = client.get("/business/cards/nope/edit")
    assert missing_card.status_code == 404
    assert "Карточка не найдена" in missing_card.text


def test_server_error_gives_html_500(tmp_path, monkeypatch):
    from app import main

    store, client = _client(tmp_path, raise_server_exceptions=False)
    card = next(iter(store.cards.values()))

    def boom(_card):
        raise RuntimeError("сбой")

    monkeypatch.setattr(main, "compute_rating", boom)
    response = client.get(f"/business/cards/{card.id}/edit")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "На главную" in response.text


def test_editor_fields_have_placeholders_and_weights(tmp_path):
    from app.main import FIELD_PLACEHOLDERS, app
    from app.models import CARD_FIELDS

    _, card = _weak_card(tmp_path)
    page = TestClient(app).get(f"/business/cards/{card.id}/edit").text

    assert set(FIELD_PLACEHOLDERS) == set(CARD_FIELDS)
    for text in FIELD_PLACEHOLDERS.values():
        assert f'placeholder="{text}"' in page
    assert page.count('class="weight-tag') == len(CARD_FIELDS) - 1
    assert "Данные и материалы · 0 из 20 баллов" in page
    assert "Контекст и потребность · 20 из 20 баллов" in page


def test_health_reports_mode_counters_and_version(tmp_path, monkeypatch):
    from app import ai

    monkeypatch.setenv("APP_VERSION", "abc1234")
    monkeypatch.setattr(ai, "last_fallback_reason", "Вопросы: LLM недоступен")
    store, client = _client(tmp_path)

    body = client.get("/health").json()
    expected = {"status", "ai_mode", "ai_fallback", "cards_total", "cards_published",
                "teams", "proposals", "drafts", "store", "version"}
    assert expected <= set(body)
    assert body["status"] == "ok"
    assert body["ai_mode"] in {"openai", "nvidia", "stub"}
    assert body["ai_fallback"] == "Вопросы: LLM недоступен"
    assert 0 <= body["cards_published"] <= body["cards_total"] == len(store.cards)
    assert body["store"].endswith("store.json")
    assert body["version"] == "abc1234"

    monkeypatch.delenv("APP_VERSION")
    assert client.get("/health").json()["version"] == "dev"
