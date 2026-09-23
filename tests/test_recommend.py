"""Тесты рекомендаций задач командам.

Правила из кейса: рекомендовать можно только карточки с баллом >= 40 (не черновики),
рекомендации не ограничивают каталог, совпадение детерминированное — без LLM.
"""

from app.models import Card, Team
from app.recommend import recommend_tasks


def _card(id_: str, industry: str, score: int, *, title: str = "", context: str = "", need: str = "", expected_result: str = "") -> Card:
    return Card(
        id=id_,
        industry=industry,
        status="published",
        confirmed=True,
        score=score,
        level="workable" if score >= 40 else "draft",
        title=title,
        context=context,
        need=need,
        expected_result=expected_result,
    )


DATA_BEE = Team(
    id="t1", name="DataBee",
    interests=["образование", "рекомендательные системы", "чат-боты"],
    skills=[], technologies=["Python", "FastAPI"],
)
ROUTE_MINDS = Team(
    id="t2", name="RouteMinds",
    interests=["логистика", "оптимизация", "геоданные"],
    skills=[], technologies=["Python", "OR-Tools"],
)
CIVIC_STACK = Team(
    id="t5", name="CivicStack",
    interests=["госуслуги", "финансы", "документооборот"],
    skills=[], technologies=["Java", "Spring Boot"],
)

CARD_EDU = _card("c_seed0001", "Образование", 100, title="Рекомендации курсов для студентов колледжа")
CARD_RETAIL = _card("c_seed0002", "Ритейл", 85, title="Прогноз спроса на скоропортящиеся товары для сети из 12 магазинов")
CARD_LOG = _card("c_seed0003", "Логистика", 50, title="Планирование маршрутов курьеров городской доставки")
CARD_MED = _card("c_seed0004", "Медицина", 45, title="Онлайн-запись к врачу с напоминаниями для частной клиники")
CARD_FIN_DRAFT = _card("c_seed0005", "Финансы", 20, title="Проверка заявок на микрокредиты")

ALL_CARDS = [CARD_EDU, CARD_RETAIL, CARD_LOG, CARD_MED, CARD_FIN_DRAFT]


def test_databee_gets_education_card_first():
    result = recommend_tasks(DATA_BEE, ALL_CARDS)
    assert result
    assert result[0][0].id == CARD_EDU.id


def test_routeminds_gets_logistics_card():
    result = recommend_tasks(ROUTE_MINDS, ALL_CARDS)
    assert result
    assert result[0][0].id == CARD_LOG.id


def test_draft_level_card_never_recommended_even_with_matching_interest():
    """CivicStack интересуется финансами, но «Проверка заявок» — балл 20 (черновик)."""
    result = recommend_tasks(CIVIC_STACK, ALL_CARDS)
    assert all(card.id != CARD_FIN_DRAFT.id for card, _ in result)


def test_every_recommendation_has_non_empty_reason():
    result = recommend_tasks(DATA_BEE, ALL_CARDS)
    assert result
    assert all(reason.strip() for _, reason in result)


def test_team_without_any_match_gets_empty_list():
    stranger = Team(id="t9", name="Stranger", interests=["астрономия"], skills=[], technologies=["COBOL"])
    result = recommend_tasks(stranger, ALL_CARDS)
    assert result == []


def test_recommend_does_not_mutate_input_cards_list():
    snapshot = list(ALL_CARDS)
    recommend_tasks(DATA_BEE, ALL_CARDS)
    assert ALL_CARDS == snapshot
    assert [c.id for c in ALL_CARDS] == [c.id for c in snapshot]


def test_industry_match_outranks_text_mention():
    """Прямое совпадение отрасли — сильнее, чем упоминание интереса в тексте другой отрасли."""
    text_only_match = _card(
        "c6", "Другое", 90,
        title="Внутренний сервис", context="Помогает наладить образование сотрудников банка.",
    )
    result = recommend_tasks(DATA_BEE, [text_only_match, CARD_EDU])
    ids = [c.id for c, _ in result]
    assert CARD_EDU.id in ids and text_only_match.id in ids
    assert ids.index(CARD_EDU.id) < ids.index(text_only_match.id)


def test_tie_break_by_score_when_signal_equal():
    low_score = _card("c7", "Другое", 45, title="Сервис на Python для склада")
    high_score = _card("c8", "Другое", 90, title="Сервис на Python для склада с прогнозированием")
    result = recommend_tasks(DATA_BEE, [low_score, high_score])
    ids = [c.id for c, _ in result]
    assert ids.index(high_score.id) < ids.index(low_score.id)


def test_limit_caps_number_of_recommendations():
    matches = [_card(f"c{i}", "Другое", 40 + i, title="Сервис на Python") for i in range(5)]
    result = recommend_tasks(DATA_BEE, matches, limit=2)
    assert len(result) == 2
    # ограничение не произвольное: остаются задачи с наибольшим баллом
    assert {c.id for c, _ in result} == {"c4", "c3"}
