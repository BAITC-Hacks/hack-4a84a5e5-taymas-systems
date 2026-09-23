"""Тесты каталога и страницы задачи (HAC-12, HAC-13).

Отдельный файл от tests/test_web.py: конструктор и редактор делает другой поток,
общий файл тестов на двоих — конфликт при каждом слиянии.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    from app import store as store_module

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    from app.main import app

    return TestClient(app)


# --- каталог (HAC-12) ------------------------------------------------------


def test_catalog_lists_published_sorted_by_score(client):
    r = client.get("/catalog")
    assert r.status_code == 200
    from app.store import get_store

    cards = get_store().list_cards()
    assert r.text.count('class="task-row') == len(cards)
    # Первой идёт карточка с максимальным баллом.
    positions = [r.text.index(c.title) for c in cards]
    assert positions == sorted(positions)
    assert cards[0].score == max(c.score for c in cards)


def test_catalog_filters_by_level_and_industry(client):
    r = client.get("/catalog?level=priority")
    assert r.status_code == 200
    assert "Рекомендации курсов" in r.text
    assert "Проверка заявок на микрокредиты" not in r.text  # уровень draft

    r = client.get("/catalog?industry=Логистика")
    assert "Планирование маршрутов" in r.text
    assert "Прогноз спроса" not in r.text

    # Оба фильтра вместе, заведомо пустая комбинация.
    r = client.get("/catalog?industry=Логистика&level=priority")
    assert "По этим фильтрам задач нет" in r.text


def test_catalog_ignores_unknown_filter_values(client):
    r = client.get("/catalog?industry=Неизвестно&level=чтототакое")
    assert r.status_code == 200
    assert "Рекомендации курсов" in r.text  # мусор в фильтрах = фильтра нет


def test_catalog_marks_draft_and_priority(client):
    r = client.get("/catalog")
    assert "требует уточнения" in r.text  # низкий рейтинг помечен, но не скрыт
    assert "Проверка заявок на микрокредиты" in r.text
    assert "приоритетная задача" in r.text


# --- страница задачи (HAC-13) ---------------------------------------------


def test_task_page_shows_fields_rating_and_proposals(client):
    r = client.get("/tasks/c_seed0001")
    assert r.status_code == 200
    assert "Из чего складывается рейтинг" in r.text
    assert "Контекст и потребность" in r.text  # расшифровка по показателям
    assert "DataBee" in r.text  # отклик из сида
    assert "Система не назначает исполнителей автоматически" in r.text


def test_task_page_unknown_card_404(client):
    assert client.get("/tasks/нет-такой").status_code == 404


def test_proposal_created_and_visible(client):
    from app.store import get_store

    before = len(get_store().list_proposals("c_seed0003"))
    r = client.post(
        "/tasks/c_seed0003/proposals",
        data={
            "team_id": "t_seed0001",
            "idea": "Собрать сервис маршрутизации на открытых картах",
            "plan": "Неделя на данные, неделя на алгоритм, неделя на интерфейс",
            "deadline": "3 недели",
            "link": "https://example.kz/prototype",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    proposals = get_store().list_proposals("c_seed0003")
    assert len(proposals) == before + 1
    assert proposals[-1].status == "pending"
    assert "Собрать сервис маршрутизации" in client.get("/tasks/c_seed0003").text


def test_proposal_requires_idea_and_plan(client):
    from app.store import get_store

    before = len(get_store().list_proposals("c_seed0003"))
    r = client.post(
        "/tasks/c_seed0003/proposals",
        data={"team_id": "t_seed0001", "idea": "   ", "plan": "План есть"},
    )
    assert r.status_code == 200
    assert "обязательные поля" in r.text
    assert len(get_store().list_proposals("c_seed0003")) == before


def test_proposal_requires_known_team(client):
    r = client.post(
        "/tasks/c_seed0003/proposals",
        data={"team_id": "", "idea": "Идея", "plan": "План"},
    )
    assert r.status_code == 200
    assert "Выберите команду" in r.text


def test_proposal_rejects_bad_link_and_too_long_text(client):
    """Валидация: ссылка не http(s) и километр текста не создают отклик и не роняют страницу."""
    from app.store import get_store

    before = len(get_store().list_proposals("c_seed0003"))
    base = {"team_id": "t_seed0001", "idea": "Идея решения", "plan": "План работ"}

    for bad_link in ("ftp://example.kz/p", "javascript:alert(1)", "example.kz/p"):
        r = client.post("/tasks/c_seed0003/proposals", data={**base, "link": bad_link})
        assert r.status_code == 200
        assert "http:// или https://" in r.text
        assert bad_link in r.text  # введённое не потеряно

    r = client.post("/tasks/c_seed0003/proposals", data={**base, "idea": "х" * 2001})
    assert r.status_code == 200
    assert "не длиннее" in r.text

    assert len(get_store().list_proposals("c_seed0003")) == before

    # Ссылка с https и без ссылки — обе допустимы.
    for ok_link in ("https://example.kz/p", ""):
        r = client.post("/tasks/c_seed0003/proposals", data={**base, "link": ok_link}, follow_redirects=False)
        assert r.status_code == 303
    assert len(get_store().list_proposals("c_seed0003")) == before + 2


def test_business_decides_manually_each_proposal(client):
    """Кейс: бизнес выбирает одну, несколько или ни одной команды."""
    from app.store import get_store

    store = get_store()
    for team in ("t_seed0001", "t_seed0002"):
        client.post(
            "/tasks/c_seed0005/proposals",
            data={"team_id": team, "idea": f"Идея от {team}", "plan": "План работ на месяц"},
            follow_redirects=False,
        )
    first, second = store.list_proposals("c_seed0005")

    r = client.post(f"/proposals/{first.id}/decision", data={"decision": "accept"}, follow_redirects=False)
    assert r.status_code == 303
    # Решение по одному отклику не трогает остальные.
    assert store.get_proposal(first.id).status == "accepted"
    assert store.get_proposal(second.id).status == "pending"

    client.post(f"/proposals/{second.id}/decision", data={"decision": "accept"}, follow_redirects=False)
    assert store.get_proposal(second.id).status == "accepted"  # можно принять несколько


def test_decision_is_not_overwritten_and_rejects_garbage(client):
    from app.store import get_store

    store = get_store()
    client.post(
        "/tasks/c_seed0005/proposals",
        data={"team_id": "t_seed0003", "idea": "Идея", "plan": "План работ"},
        follow_redirects=False,
    )
    proposal = store.list_proposals("c_seed0005")[-1]

    client.post(f"/proposals/{proposal.id}/decision", data={"decision": "reject"}, follow_redirects=False)
    assert store.get_proposal(proposal.id).status == "rejected"

    r = client.post(f"/proposals/{proposal.id}/decision", data={"decision": "accept"})
    assert r.status_code == 200
    assert "решение уже принято" in r.text
    assert store.get_proposal(proposal.id).status == "rejected"

    r = client.post(f"/proposals/{proposal.id}/decision", data={"decision": "чтототакое"})
    assert r.status_code == 200
    assert "Неизвестное действие" in r.text


def test_decision_on_unknown_proposal_404(client):
    assert client.post("/proposals/нет/decision", data={"decision": "accept"}).status_code == 404


# --- безопасность вывода (HAC-38) ------------------------------------------

XSS = "<script>alert(1)</script>"


def test_user_text_is_escaped_everywhere(client):
    """Весь текст на страницах пользовательский — он обязан выходить экранированным."""
    # Черновик → страница вопросов и редактор.
    r = client.post("/business/new", data={"text": f"Хотим бота {XSS}", "industry": "Образование"})
    assert r.status_code == 200
    assert XSS not in r.text and "&lt;script&gt;" in r.text

    # Отклик → страница задачи.
    client.post(
        "/tasks/c_seed0003/proposals",
        data={"team_id": "t_seed0001", "idea": f"Идея {XSS}", "plan": f"План {XSS}"},
        follow_redirects=False,
    )
    r = client.get("/tasks/c_seed0003")
    assert XSS not in r.text and "&lt;script&gt;" in r.text


def test_prototype_link_has_noopener(client):
    client.post(
        "/tasks/c_seed0003/proposals",
        data={"team_id": "t_seed0001", "idea": "Идея", "plan": "План", "link": "https://example.kz/p"},
        follow_redirects=False,
    )
    r = client.get("/tasks/c_seed0003")
    assert 'href="https://example.kz/p" rel="noreferrer noopener"' in r.text


def test_no_safe_filter_in_templates():
    """`|safe` или Markup() отключили бы автоэкранирование молча."""
    import pathlib

    offenders = [
        str(p)
        for p in list(pathlib.Path("app/templates").glob("*.html")) + list(pathlib.Path("app").glob("*.py"))
        if "|safe" in p.read_text(encoding="utf-8") or "Markup(" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


# --- позиция в каталоге и число откликов (HAC-39) --------------------------


def test_task_page_shows_catalog_position(client):
    """Кейс, шаг 5: задача публикуется «на позиции, соответствующей её рейтингу»."""
    from app.store import get_store

    store = get_store()
    size = len(store.list_cards())

    # Карточка с максимальным баллом стоит первой.
    r = client.get("/tasks/c_seed0001")
    assert f"<strong>1</strong> из {size}" in r.text

    # Карточка с минимальным баллом — последней, но из каталога не исчезает.
    r = client.get("/tasks/c_seed0005")
    assert f"<strong>{size}</strong> из {size}" in r.text


def test_unpublished_card_reports_no_catalog_position(client):
    from app.models import Card
    from app.store import get_store

    store = get_store()
    store.add_card(Card(id="c_draft", title="Неопубликованная", status="draft", score=10, level="draft"))
    r = client.get("/tasks/c_draft")
    assert r.status_code == 200
    assert "В каталоге не показывается" in r.text


def test_position_changes_after_confirmed_edit(client):
    """Рейтинг влияет на позицию: подтверждённый рост поднимает задачу."""
    from app.store import get_store

    store = get_store()
    card = store.get_card("c_seed0005")  # 20 баллов, последняя
    size = len(store.list_cards())
    assert f"<strong>{size}</strong> из {size}" in client.get("/tasks/c_seed0005").text

    # 95 баллов — впереди остаётся только сид-карточка со 100, значит вторая позиция.
    card.score, card.level = 95, "priority"
    store.update_card(card)
    assert f"<strong>2</strong> из {size}" in client.get("/tasks/c_seed0005").text


def test_catalog_shows_proposal_counts(client):
    r = client.get("/catalog")
    assert "откликов: 2" in r.text  # c_seed0001 из сида
    assert "откликов пока нет" in r.text  # c_seed0005 без откликов

    client.post(
        "/tasks/c_seed0005/proposals",
        data={"team_id": "t_seed0001", "idea": "Идея решения", "plan": "План работ"},
        follow_redirects=False,
    )
    assert "откликов: 1" in client.get("/catalog").text


def test_task_page_lists_fitting_teams_for_business(client):
    page = client.get("/tasks/c_seed0001")  # Образование, 100 баллов
    assert page.status_code == 200
    assert "Подходящие команды" in page.text
    assert "DataBee" in page.text  # интерес «образование» совпадает с отраслью задачи
    assert "выбирает бизнес вручную" in page.text


def test_task_page_hides_fitting_teams_for_draft(client):
    page = client.get("/tasks/c_seed0005")  # Финансы, 20 баллов — черновик
    assert page.status_code == 200
    assert "Рекомендации открываются с уровня «Рабочая»" in page.text
