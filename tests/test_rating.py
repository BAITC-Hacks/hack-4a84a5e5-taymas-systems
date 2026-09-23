"""Тесты рейтинга готовности. Примеры недостаточных ответов идут в README как тестовые сценарии."""

import pytest

from app.models import CardFields
from app.rating import SCALE, compute_rating, level_for, next_best_action, progress_bar, rating_summary

SEED_CARD_FULL = CardFields(
    title="Рекомендации курсов для студентов колледжа",
    context="Колледж ведёт 40 курсов дополнительного образования, студенты выбирают их вслепую: "
            "30% бросают курс в первый месяц.",
    need="Нужен сервис, который подсказывает студенту 3–5 подходящих курсов по его специальности, "
         "успеваемости и интересам.",
    users="Студенты 1–3 курса и кураторы групп.",
    data="Обезличенная выгрузка: 1 200 студентов, история записей на курсы за 2 года, "
         "оценки (CSV). Описания курсов в PDF.",
    constraints="Срок — 6 недель. Только веб, без мобильного приложения. "
                "Персональные данные не покидают колледж.",
    expected_result="Работающий веб-сервис с рекомендациями и админ-панель для кураторов.",
    success_criteria="Доля отчислившихся с курса в первый месяц снижается с 30% до 20% за семестр; "
                      "70% студентов оценивают рекомендации как полезные.",
    contact="Айгерим Сейткали, замдиректора по УМР, a.seitkali@example.kz",
    interaction_format="Созвон раз в неделю по вторникам, вопросы в Telegram, демо раз в две недели.",
)


def _invariants(card: CardFields) -> None:
    rating = compute_rating(card)
    assert len(rating.items) == len(SCALE)
    assert [i.key for i in rating.items] == [key for key, *_ in SCALE]
    assert sum(i.awarded for i in rating.items) == rating.score
    assert 0 <= rating.score <= 100
    for item in rating.items:
        assert 0 <= item.awarded <= item.weight
        if item.awarded == item.weight:
            assert item.hint == ""
        else:
            assert item.hint != ""


def test_empty_card_is_zero_draft():
    rating = compute_rating(CardFields())
    assert rating.score == 0
    assert rating.level == "draft"
    _invariants(CardFields())


def test_seed_card_is_priority_and_high():
    rating = compute_rating(SEED_CARD_FULL)
    assert rating.score >= 90
    assert rating.level == "priority"
    _invariants(SEED_CARD_FULL)


def test_partially_filled_card_is_workable():
    card = CardFields(
        context="Колледж ведёт 40 курсов, студенты выбирают вслепую",
        need="Нужны рекомендации курсов по специальности",
        data="Есть данные о студентах и их курсах, но без деталей формата.",
        users="Студенты колледжа.",
    )
    rating = compute_rating(card)
    assert 40 <= rating.score <= 69
    assert rating.level == "workable"
    _invariants(card)


def test_adding_text_never_lowers_score():
    base = CardFields(context="Колледж ведёт 40 курсов, студенты выбирают вслепую")
    richer = base.model_copy(update={
        "need": "Нужен сервис, который подсказывает студенту подходящие курсы по специальности",
    })
    assert compute_rating(richer).score >= compute_rating(base).score


@pytest.mark.parametrize("stub", ["нет", "-", "—", "не знаю", "n/a", "нет данных", "пока нет", "НЕТ"])
def test_stub_phrases_are_not_counted_as_filled(stub):
    card = CardFields(context=stub, need=stub, data=stub, users=stub, constraints=stub)
    rating = compute_rating(card)
    assert rating.score == 0
    assert rating.level == "draft"


def test_success_criteria_without_measurable_signal_gets_half():
    """Пример из отчёта: общие слова без цифр — половина веса, конкретная подсказка."""
    card = CardFields(success_criteria="Сделать удобно и быстро для пользователей")
    rating = compute_rating(card)
    item = next(i for i in rating.items if i.key == "success_criteria")
    assert item.awarded == 8
    assert "измеримый признак" in item.hint


def test_success_criteria_with_measurable_signal_gets_full():
    card = CardFields(success_criteria="Время обработки заявки снижается не менее чем на 30%")
    item = next(i for i in compute_rating(card).items if i.key == "success_criteria")
    assert item.awarded == 15
    assert item.hint == ""


def test_business_link_name_only_gets_half():
    """Пример из отчёта: только имя без контакта и формата — половина веса."""
    card = CardFields(contact="Марат")
    item = next(i for i in compute_rating(card).items if i.key == "business_link")
    assert item.awarded == 5
    assert "формат консультаций" in item.hint


def test_business_link_with_contact_and_format_gets_full():
    card = CardFields(contact="Марат, mmarat@example.kz", interaction_format="Звонок раз в неделю")
    item = next(i for i in compute_rating(card).items if i.key == "business_link")
    assert item.awarded == 10
    assert item.hint == ""


def test_data_without_concrete_details_gets_half():
    card = CardFields(data="У нас есть какие-то данные о клиентах компании в целом")
    item = next(i for i in compute_rating(card).items if i.key == "data")
    assert item.awarded == 10
    assert "формат" in item.hint.lower()


def test_data_with_concrete_details_gets_full():
    card = CardFields(data="Выгрузка из 1С за 2 года, около 400 000 строк, формат CSV")
    item = next(i for i in compute_rating(card).items if i.key == "data")
    assert item.awarded == 20
    assert item.hint == ""


def test_mini_example_from_ticket():
    assert compute_rating(CardFields()).score == 0
    card = CardFields(
        context="Колледж ведёт 40 курсов, студенты выбирают вслепую",
        need="Нужны рекомендации курсов по специальности",
    )
    assert compute_rating(card).score == 20


@pytest.mark.parametrize("level, lo, hi", [("draft", 0, 39), ("workable", 40, 69), ("ready", 70, 89), ("priority", 90, 100)])
def test_level_for_thresholds(level, lo, hi):
    assert level_for(lo) == level
    assert level_for(hi) == level


# --- progress_bar / next_best_action / rating_summary --------------------

def test_progress_bar_extremes_and_length():
    assert progress_bar(0) == "░░░░░░░░░░ 0/100"
    assert progress_bar(100) == "██████████ 100/100"
    bar = progress_bar(50)
    assert bar == "█████░░░░░ 50/100"
    assert bar.count("█") + bar.count("░") == 10


def test_progress_bar_clamps_out_of_range_scores():
    assert progress_bar(-10) == progress_bar(0)
    assert progress_bar(150) == progress_bar(100)


def test_progress_bar_custom_width():
    bar = progress_bar(20, width=5)
    assert bar == "█░░░░ 20/100"


def test_next_best_action_returns_top_hint_for_empty_card():
    rating = compute_rating(CardFields())
    hint = next_best_action(rating)
    assert hint is not None
    assert hint == rating.missing[0]


def test_next_best_action_is_none_when_rating_full():
    rating = compute_rating(SEED_CARD_FULL)
    assert next_best_action(rating) is None


def test_rating_summary_mentions_score_level_and_hint():
    rating = compute_rating(CardFields())
    summary = rating_summary(rating)
    assert "0/100" in summary
    assert "Черновик" in summary
    assert "Не хватает" in summary


def test_rating_summary_has_no_hint_when_full():
    rating = compute_rating(SEED_CARD_FULL)
    summary = rating_summary(rating)
    assert summary == f"{rating.score}/100 — {rating.level_label}"
    assert "Не хватает" not in summary
