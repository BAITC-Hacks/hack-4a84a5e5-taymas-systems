"""Тесты AI-функций ядра: заглушка вопросов и переключение на LLM."""

import time

import pytest

from app import ai
from app.models import CARD_FIELDS, Answer, CardFields, Question
from app.prompts import QuestionsResponse


def test_stub_generates_at_least_three_valid_distinct_questions():
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


def test_stub_covers_all_gaps_up_to_max_for_empty_draft():
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


def test_stub_build_card_places_answers_into_fields():
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


def test_stub_appends_context_answer_instead_of_overwriting():
    answers = [Answer(field="context", question="Уточните контекст", answer="Расписание меняется каждую неделю")]
    card = ai.build_card(_DRAFT, "Образование", answers)
    assert _DRAFT in card.context
    assert "Расписание меняется каждую неделю" in card.context


def test_mini_example_from_ticket_build_card():
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


def test_llm_fabricated_contact_falls_back_to_stub_value(monkeypatch):
    """Кейс из тикета: LLM выдумывает контакт, которого не было во входе — поле не принимаем."""
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
