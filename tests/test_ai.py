"""Тесты AI-функций ядра: заглушка вопросов и переключение на LLM."""

import time

import pytest

from app import ai
from app.models import CARD_FIELDS, Answer, CardFields, Question
from app.prompts import QuestionsResponse


def test_stub_generates_at_least_three_valid_distinct_questions(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    start = time.monotonic()
    questions = ai.generate_questions("Хотим бота для ответов студентам про расписание", "Образование")
    elapsed_ms = (time.monotonic() - start) * 1000

    assert len(questions) >= 3
    assert elapsed_ms < 100
    fields = [q.field for q in questions]
    assert len(fields) == len(set(fields))
    for q in questions:
        assert q.field in CARD_FIELDS
        assert q.question.strip()


def test_stub_covers_all_gaps_up_to_max_for_empty_draft(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    questions = ai.generate_questions("", "Образование")
    assert 3 <= len(questions) <= 6


def test_ai_mode_is_stub_without_key(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    assert ai.ai_mode() == "stub"


def test_ai_mode_reports_provider_with_key(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai.settings, "LLM_PROVIDER", "openai")
    assert ai.ai_mode() == "openai"


class _FakeClient:
    def __init__(self, questions: list[Question]):
        self._questions = questions

    def complete(self, messages, *, json_schema=None, temperature=0.2):
        assert json_schema is QuestionsResponse
        return QuestionsResponse(questions=self._questions)


def test_llm_response_used_when_valid(monkeypatch):
    llm_questions = [
        Question(field="context", question="Какие детали ещё есть про студентов?", why="llm"),
        Question(field="data", question="Какие данные о расписании доступны?", why="llm"),
        Question(field="expected_result", question="Что должно получиться в итоге?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(llm_questions))

    questions = ai.generate_questions("Хотим бота для ответов студентам про расписание", "Образование")

    assert questions == llm_questions


def test_invalid_llm_response_falls_back_to_stub(monkeypatch):
    """Модель вернула всего 2 вопроса — это не проходит валидацию (< 3)."""
    invalid_questions = [
        Question(field="context", question="Вопрос один?", why="llm"),
        Question(field="data", question="Вопрос два?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(invalid_questions))

    questions = ai.generate_questions("Хотим бота для ответов студентам про расписание", "Образование")

    assert len(questions) >= 3
    fields = [q.field for q in questions]
    assert len(fields) == len(set(fields))


def test_invalid_llm_response_duplicate_fields_falls_back_to_stub(monkeypatch):
    dup_questions = [
        Question(field="context", question="A?", why="llm"),
        Question(field="context", question="B?", why="llm"),
        Question(field="data", question="C?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(dup_questions))

    questions = ai.generate_questions("Хотим бота для ответов студентам про расписание", "Образование")

    assert len(questions) >= 3


class _ExplodingClient:
    def complete(self, messages, *, json_schema=None, temperature=0.2):
        from app.llm import LLMResponseError

        raise LLMResponseError("сеть недоступна")


def test_llm_error_falls_back_to_stub_without_raising(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _ExplodingClient())

    questions = ai.generate_questions("Хотим бота для ответов студентам про расписание", "Образование")

    assert len(questions) >= 3


# --- build_card ---------------------------------------------------------

_DRAFT = "Хотим бота для ответов студентам про расписание"


def test_stub_build_card_places_answers_into_fields(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    answers = [
        Answer(field="data", question="Какие данные?", answer="Расписание в Excel на семестр, 300 групп"),
        Answer(field="users", question="Кто пользователи?", answer="Студенты и деканат"),
    ]
    card = ai.build_card(_DRAFT, "Образование", answers)
    assert card.title == _DRAFT[:80]
    assert card.context == _DRAFT
    assert card.data == "Расписание в Excel на семестр, 300 групп"
    assert card.users == "Студенты и деканат"
    assert card.contact == ""


def test_stub_appends_context_answer_instead_of_overwriting(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    answers = [Answer(field="context", question="Уточните контекст", answer="Расписание меняется каждую неделю")]
    card = ai.build_card(_DRAFT, "Образование", answers)
    assert _DRAFT in card.context
    assert "Расписание меняется каждую неделю" in card.context


def test_mini_example_from_ticket_build_card(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    card = ai.build_card(
        _DRAFT,
        "Образование",
        [Answer(field="data", question="Какие данные?", answer="Расписание в Excel на семестр, 300 групп")],
    )
    assert card.title
    assert card.context
    assert card.data
    assert card.contact == ""


class _FakeCardClient:
    def __init__(self, card: CardFields):
        self._card = card

    def complete(self, messages, *, json_schema=None, temperature=0.2):
        assert json_schema is CardFields
        return self._card


def test_ai_function_rejects_fabricated_fact_not_reported_by_user(monkeypatch):
    """Требование кейса: ИИ не добавляет фактов, которых не сообщил пользователь.

    LLM выдумывает контакт, которого не было ни в черновике, ни в ответах — поле
    отбрасывается и заменяется значением из заглушки (здесь — пустой строкой).
    """
    answers = [Answer(field="data", question="Какие данные?", answer="Расписание в Excel на семестр, 300 групп")]
    fabricated = CardFields(
        title="Бот для расписания",
        context=_DRAFT,
        data="Расписание в Excel на семестр, 300 групп",
        contact="ivan@corp.kz",
    )
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeCardClient(fabricated))

    card = ai.build_card(_DRAFT, "Образование", answers)

    assert card.contact == ""
    assert card.data == "Расписание в Excel на семестр, 300 групп"


class _ExplodingCardClient:
    def complete(self, messages, *, json_schema=None, temperature=0.2):
        from app.llm import LLMResponseError

        raise LLMResponseError("сеть недоступна")


def test_llm_error_falls_back_to_stub_card_entirely(monkeypatch):
    answers = [Answer(field="data", question="Какие данные?", answer="Расписание в Excel на семестр, 300 групп")]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _ExplodingCardClient())

    card = ai.build_card(_DRAFT, "Образование", answers)

    assert card == ai._stub_card(_DRAFT, answers)


# --- HAC-19: устойчивость к мусорному вводу -----------------------------

_GARBAGE_DRAFTS = {
    "emoji_only": "🎉🎉🎉😀🔥",
    "repeated_char": "а" * 4000,
    "english_text": "We want a bot that answers students about the schedule and exams.",
    "kazakh_text": "Біз колледж студенттеріне сабақ кестесі туралы жауап беретін бот қалаймыз.",
    "long_4000_chars": "Нужен бот для расписания. " * 150,  # > 4000 символов
    "html_tags": "<script>alert(1)</script><b>Нужен бот</b> для <i>расписания</i> студентам",
    "empty": "",
    "whitespace_only": "   \n\t  ",
}


@pytest.mark.parametrize("draft", _GARBAGE_DRAFTS.values(), ids=_GARBAGE_DRAFTS.keys())
def test_stub_questions_survive_garbage_input(draft, monkeypatch):
    """Мусорный вход (эмодзи, повтор символа, чужой язык, HTML, 4000+ символов, пустота)
    не роняет generate_questions и всё равно даёт >= 3 разных вопроса по разным полям.

    Явно проверяем именно заглушку (monkeypatch llm_available=False) — поведение не
    должно молча зависеть от того, стоит ли в окружении реальный ключ.
    """
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    questions = ai.generate_questions(draft, "Образование")
    assert len(questions) >= 3
    fields = [q.field for q in questions]
    assert len(fields) == len(set(fields)), "вопросы должны быть по разным полям, а не три одинаковых"
    for q in questions:
        assert q.field in CARD_FIELDS
        assert q.question.strip()


@pytest.mark.parametrize("draft", _GARBAGE_DRAFTS.values(), ids=_GARBAGE_DRAFTS.keys())
def test_stub_build_card_survives_garbage_input(draft, monkeypatch):
    """То же самое для сборки карточки: результат всегда валидный CardFields, без исключений."""
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    answers = [Answer(field="data", question="Какие данные?", answer=draft)]
    card = ai.build_card(draft, "Образование", answers)
    assert isinstance(card, CardFields)


def test_garbage_input_stub_is_still_fast(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    start = time.monotonic()
    ai.generate_questions("🎉" * 500, "Образование")
    elapsed_ms = (time.monotonic() - start) * 1000
    assert elapsed_ms < 200


# --- HAC-19: полный набор невалидных ответов LLM для вопросов -----------

def test_invalid_llm_response_unknown_field_falls_back_to_stub(monkeypatch):
    bad_questions = [
        Question(field="not_a_real_field", question="Вопрос про то, чего нет в карточке?", why="llm"),
        Question(field="data", question="Какие данные есть?", why="llm"),
        Question(field="users", question="Кто пользователи?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(bad_questions))

    questions = ai.generate_questions(_DRAFT, "Образование")

    assert len(questions) >= 3
    assert all(q.field in CARD_FIELDS for q in questions)


def test_invalid_llm_response_empty_question_text_falls_back_to_stub(monkeypatch):
    bad_questions = [
        Question(field="context", question="   ", why="llm"),
        Question(field="data", question="Какие данные есть?", why="llm"),
        Question(field="users", question="Кто пользователи?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(bad_questions))

    questions = ai.generate_questions(_DRAFT, "Образование")

    assert len(questions) >= 3
    assert all(q.question.strip() for q in questions)


# --- HAC-19: last_fallback_reason — честность режима при сбое LLM --------

def test_fallback_reason_is_none_when_llm_not_configured(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    ai._set_fallback_reason("что-то из прошлого вызова")
    ai.generate_questions(_DRAFT, "Образование")
    assert ai.last_fallback_reason is None


def test_fallback_reason_is_none_after_successful_llm_call(monkeypatch):
    llm_questions = [
        Question(field="context", question="Какие детали ещё есть?", why="llm"),
        Question(field="data", question="Какие данные доступны?", why="llm"),
        Question(field="expected_result", question="Что должно получиться?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(llm_questions))

    ai.generate_questions(_DRAFT, "Образование")

    assert ai.last_fallback_reason is None


def test_fallback_reason_is_set_when_llm_errors_on_questions(monkeypatch):
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _ExplodingClient())

    ai.generate_questions(_DRAFT, "Образование")

    assert ai.last_fallback_reason is not None
    assert "Вопросы" in ai.last_fallback_reason


def test_fallback_reason_is_set_when_llm_response_invalid_for_questions(monkeypatch):
    invalid_questions = [
        Question(field="context", question="A?", why="llm"),
        Question(field="data", question="B?", why="llm"),
    ]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeClient(invalid_questions))

    ai.generate_questions(_DRAFT, "Образование")

    assert ai.last_fallback_reason is not None


def test_fallback_reason_is_set_when_llm_errors_on_card(monkeypatch):
    answers = [Answer(field="data", question="Какие данные?", answer="Расписание в Excel на семестр, 300 групп")]
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _ExplodingCardClient())

    ai.build_card(_DRAFT, "Образование", answers)

    assert ai.last_fallback_reason is not None
    assert "Карточка" in ai.last_fallback_reason


def test_fallback_reason_is_none_after_successful_card_build(monkeypatch):
    answers = [Answer(field="data", question="Какие данные?", answer="Расписание в Excel на семестр, 300 групп")]
    fine_card = CardFields(title="Бот для расписания", context=_DRAFT, data="Расписание в Excel на семестр, 300 групп")
    monkeypatch.setattr(ai, "llm_available", lambda: True)
    monkeypatch.setattr(ai, "get_client", lambda: _FakeCardClient(fine_card))

    ai.build_card(_DRAFT, "Образование", answers)

    assert ai.last_fallback_reason is None


# --- уместность вопросов заглушки (HAC-33) ---------------------------------

DRAFT_EDU = "Хотим чат-бота для студентов, чтобы отвечал на вопросы."
DRAFT_LOG = "Курьеры опаздывают, клиенты жалуются. Нужно что-то с маршрутами."


def test_stub_quotes_the_draft(monkeypatch):
    """Критерий кейса «вопросы уместны»: без ключа вопрос всё равно про эту задачу."""
    from app.ai import generate_questions

    monkeypatch.setattr(ai, "llm_available", lambda: False)
    questions = generate_questions(DRAFT_EDU, "Образование")
    quoted = [q for q in questions if "чат-бота для студентов" in q.question]
    assert quoted, [q.question for q in questions]
    assert "Вы написали" in quoted[0].question


def test_stub_questions_differ_between_drafts(monkeypatch):
    from app.ai import generate_questions

    monkeypatch.setattr(ai, "llm_available", lambda: False)
    edu = {q.question for q in generate_questions(DRAFT_EDU, "Образование")}
    log = {q.question for q in generate_questions(DRAFT_LOG, "Логистика")}
    assert edu != log
    # Отраслевые примеры не путаются между собой.
    assert any("студенты, преподаватели" in q for q in edu)
    assert any("курьеры, диспетчеры" in q for q in log)
    assert not any("курьеры" in q for q in edu)


def test_stub_marks_partially_covered_indicator(monkeypatch):
    """Черновик уже даёт контекст — про него не спрашивают с нуля."""
    from app.ai import generate_questions

    monkeypatch.setattr(ai, "llm_available", lambda: False)
    questions = generate_questions(DRAFT_EDU, "Образование")
    partial = [q for q in questions if q.field == "need"]
    assert partial and "частично" in partial[0].question
    assert "начислено" in partial[0].why


def test_stub_quote_skipped_for_meaningless_draft(monkeypatch):
    """Мусор в черновике не должен попадать в вопрос цитатой."""
    from app.ai import _draft_quote, generate_questions

    assert _draft_quote("😀😀😀") == ""
    assert _draft_quote("нужно") == ""
    monkeypatch.setattr(ai, "llm_available", lambda: False)
    questions = generate_questions("😀😀😀", "Другое")
    assert len(questions) >= 3
    assert not any("Вы написали" in q.question for q in questions)


def test_stub_quote_preserves_punctuation_inside_phrase():
    from app.ai import _draft_quote

    assert _draft_quote(DRAFT_EDU) == "чат-бота для студентов"
    assert _draft_quote(DRAFT_LOG) == "Курьеры опаздывают, клиенты жалуются"


def test_stub_questions_cover_distinct_fields_for_any_input(monkeypatch):
    """Три разных вопроса по трём разным полям — на любом входе, включая мусор."""
    from app.ai import generate_questions

    monkeypatch.setattr(ai, "llm_available", lambda: False)
    for draft in [DRAFT_EDU, "ааааааааа", "😀", "x" * 4000, "<script>alert(1)</script>", ""]:
        questions = generate_questions(draft, "Другое")
        assert len(questions) >= 3, draft[:30]
        fields = [q.field for q in questions]
        assert len(set(fields)) == len(fields), fields
        assert all(q.question.strip() for q in questions)


def test_unexpected_llm_exception_never_escapes(monkeypatch):
    """Граница слоя: любая ошибка SDK выглядит для пользователя как работа заглушки, а не 500.

    Обёртка переводит ошибки провайдера в LLMResponseError, но транспорт может бросить
    своё — например, UnicodeEncodeError, если в ключе оказались не-ASCII символы.
    """
    import app.ai as ai_module
    from app.models import Answer

    def boom(*_args, **_kwargs):
        raise UnicodeEncodeError("ascii", "ключ", 0, 1, "ordinal not in range(128)")

    monkeypatch.setattr(ai_module, "llm_available", lambda: True)
    monkeypatch.setattr(ai_module, "_llm_questions", boom)
    monkeypatch.setattr(ai_module, "_llm_card", boom)

    questions = ai_module.generate_questions("Хотим чат-бота для студентов", "Образование")
    assert len(questions) >= 3
    assert "непредвиденная ошибка" in (ai_module.last_fallback_reason or "")

    card = ai_module.build_card(
        "Хотим чат-бота для студентов",
        "Образование",
        [Answer(field="data", question="Какие данные?", answer="FAQ на 120 вопросов в Google Docs.")],
    )
    assert card.data
    assert "непредвиденная ошибка" in (ai_module.last_fallback_reason or "")
