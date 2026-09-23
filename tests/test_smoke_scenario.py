"""Сквозной смоук-тест обязательной демонстрации кейса (HAC-16).

Кейс, раздел 11: «слабое описание → дополнение → рост рейтинга → публикация →
отклик команды → бизнес вручную принимает/отклоняет. Все переходы должны работать
в MVP, а не на слайдах».

Этот файл — приёмка демо-пути целиком, один проход от пустого хранилища до
принятого отклика. Маршруты и имена полей форм берутся из раздела «Контракт»
в BRIEF.md дословно: если реализация от него отошла, падает именно здесь,
а не на живом показе.
"""

import pytest
from fastapi.testclient import TestClient

# Слабый черновик из data/demo-scenario.md — тот же текст, что показываем жюри.
WEAK_DRAFT = "Хотим чат-бота для студентов, чтобы отвечал на вопросы"

# Чем дозаполняем карточку в редакторе, чтобы рейтинг дошёл до верхнего уровня.
FULL_FIELDS = {
    "title": "Чат-бот поддержки студентов колледжа",
    "context": (
        "В колледже 1200 студентов, приёмная комиссия и деканат получают около 200 однотипных "
        "вопросов в неделю про расписание, справки и пересдачи; ответы занимают до двух дней."
    ),
    "need": (
        "Нужен бот, который отвечает на типовые вопросы круглосуточно и передаёт человеку только "
        "то, что не смог закрыть сам."
    ),
    "users": "Студенты 1–4 курса, 1200 человек, и два сотрудника деканата, которые ведут переписку.",
    "data": (
        "Выгрузка 900 обращений за год в CSV, регламенты в PDF, расписание из внутренней системы "
        "через API."
    ),
    "constraints": (
        "Срок 3 месяца, бюджет на внешние сервисы ограничен, персональные данные студентов "
        "за пределы контура не передаются, стек Python."
    ),
    "expected_result": (
        "Работающий бот в Telegram и веб-виджет на сайте колледжа с панелью для сотрудника деканата."
    ),
    "success_criteria": (
        "Доля обращений, закрытых без человека, не менее 60% за семестр; среднее время ответа "
        "снижается с двух дней до 5 минут."
    ),
    "contact": "Руководитель учебного отдела, ok@example.kz, +7 700 000 00 00",
    "interaction_format": "Созвон раз в неделю по средам, демо раз в две недели, вопросы в Telegram.",
}


@pytest.fixture()
def client(tmp_path):
    from app import store as store_module

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    from app.main import app

    return TestClient(app)


def test_full_demo_scenario(client):
    from app.store import get_store

    store = get_store()

    # --- шаг 1. Черновик -------------------------------------------------
    assert client.get("/business/new").status_code == 200, "нет страницы ввода черновика"

    r = client.post(
        "/business/new",
        data={"text": WEAK_DRAFT, "industry": "Образование"},
        follow_redirects=True,
    )
    assert r.status_code == 200, "черновик не принят"

    drafts = list(store.drafts.values())
    assert drafts, "черновик не сохранён в хранилище"
    draft = max(drafts, key=lambda d: d.created_at)

    # --- шаг 2. Уточнение: кейс требует не менее трёх вопросов ------------
    assert len(draft.questions) >= 3, f"вопросов меньше трёх: {len(draft.questions)}"

    # --- шаг 3. Карточка из ответов --------------------------------------
    answers = {
        f"answer_{i}": f"{q.question} — отвечаем развёрнуто, с конкретикой и цифрами."
        for i, q in enumerate(draft.questions)
    }
    r = client.post(f"/business/drafts/{draft.id}/answers", data=answers, follow_redirects=False)
    assert r.status_code in (302, 303), "ответы не ведут к карточке"

    cards = [c for c in store.cards.values() if c.draft_id == draft.id]
    assert len(cards) == 1, "карточка из ответов не создана"
    card = cards[0]
    assert card.status == "draft" and not card.confirmed, "карточка опубликована без подтверждения человека"

    # --- шаг 4. Рейтинг слабой карточки ----------------------------------
    from app.rating import compute_rating

    score_before = compute_rating(card).score
    assert client.get(f"/business/cards/{card.id}/edit").status_code == 200, "нет редактора карточки"

    # --- шаг 5. Дозаполнение: сохранение не подтверждает балл ------------
    r = client.post(f"/business/cards/{card.id}/edit", data=FULL_FIELDS, follow_redirects=True)
    assert r.status_code == 200, "карточка не сохраняется"

    card = store.get_card(card.id)
    assert card.title == FULL_FIELDS["title"], "правки не сохранились"
    assert not card.confirmed, "сохранение не должно подтверждать карточку"

    score_after = compute_rating(card).score
    assert score_after > score_before, f"рейтинг не вырос: {score_before} → {score_after}"
    assert score_after >= 70, f"дозаполненная карточка должна выйти хотя бы на «готовую», а не {score_after}"

    # --- шаг 6. Подтверждение и публикация -------------------------------
    r = client.post(
        f"/business/cards/{card.id}/publish",
        data={"confirmed": "on"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), "карточка не публикуется"

    card = store.get_card(card.id)
    assert card.status == "published", "карточка не в каталоге после подтверждения"
    assert card.confirmed, "подтверждение не записалось"
    assert card.score == score_after, "подтверждённый балл разошёлся с пересчётом"

    # --- шаг 7. Каталог: позиция по рейтингу ------------------------------
    r = client.get("/catalog")
    assert r.status_code == 200
    assert card.title in r.text, "опубликованной задачи нет в каталоге"

    published = store.list_cards()
    scores = [c.score for c in published]
    assert scores == sorted(scores, reverse=True), "каталог не отсортирован по рейтингу"

    # --- шаг 8. Отклик команды -------------------------------------------
    assert client.get(f"/tasks/{card.id}").status_code == 200

    team = store.list_teams()[0]
    r = client.post(
        f"/tasks/{card.id}/proposals",
        data={
            "team_id": team.id,
            "idea": "Бот на готовой модели с базой регламентов и передачей сложных вопросов человеку",
            "plan": "Неделя на данные, две на бота, неделя на панель деканата",
            "deadline": "4 недели",
            "link": "https://example.kz/prototype",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, "отклик не принят"

    proposals = store.list_proposals(card.id)
    assert len(proposals) == 1 and proposals[0].status == "pending"

    # --- шаг 9. Бизнес решает вручную ------------------------------------
    proposal = proposals[0]
    r = client.post(
        f"/proposals/{proposal.id}/decision",
        data={"decision": "accept"},
        follow_redirects=False,
    )
    assert r.status_code == 303, "решение бизнеса не проходит"
    assert store.get_proposal(proposal.id).status == "accepted"

    # Кейс: автоматического назначения нет — до нажатия человеком статус не менялся.
    assert store.get_proposal(proposal.id).decided_at is not None


def test_empty_draft_is_rejected(client):
    """Надёжность: очевидный мусор на входе обрабатывается, а не роняет сценарий."""
    r = client.post("/business/new", data={"text": "   ", "industry": "Образование"})
    assert r.status_code in (200, 422), "пустой черновик должен вернуть понятный ответ, а не 500"
