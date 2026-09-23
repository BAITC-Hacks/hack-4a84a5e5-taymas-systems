"""AI-функции: уточняющие вопросы и сборка карточки.

Контракт (BRIEF.md):
  generate_questions(draft_text, industry) -> list[Question]   # len >= 3
  build_card(draft_text, industry, answers) -> CardFields
  ai_mode() -> "openai" | "nvidia" | "stub"

Правила кейса (раздел 5): ИИ не добавляет фактов, которых не сообщил пользователь;
результат редактируется и подтверждается человеком; без внешнего API работает локальная заглушка.
Все вызовы модели идут только через app/llm.py.
"""

import logging

from app.config import settings
from app.llm import LLMConfigError, LLMResponseError, get_client, llm_available
from app.models import CARD_FIELDS, FIELD_LABELS, Answer, CardFields, Question
from app.prompts import QUESTIONS_SYSTEM, QuestionsResponse, build_questions_user_prompt
from app.rating import SCALE, compute_rating

logger = logging.getLogger(__name__)

# показатель рейтинга -> поля карточки, которые он закрывает (для заглушки и промпта)
_FIELDS_BY_INDICATOR: dict[str, list[str]] = {key: fields for key, _label, _weight, fields in SCALE}

# заглушка: один типовой вопрос на поле карточки (кроме title — его не уточняем)
_STUB_QUESTIONS: dict[str, str] = {
    "context": "Что происходит сейчас и что именно не устраивает?",
    "need": "Что должно измениться, если задачу решить?",
    "data": "Какие данные, примеры или источники вы можете передать команде?",
    "expected_result": "Что конкретно должно получиться в конце работы команды?",
    "success_criteria": "По каким измеримым признакам вы поймёте, что решение принято?",
    "constraints": "Какие сроки, технологии или доступы нужно учитывать?",
    "users": "Кто и в каком количестве будет пользоваться решением?",
    "contact": "Как с вами связаться — почта или телефон?",
    "interaction_format": "В каком формате и как часто удобно обсуждать задачу с командой?",
}

_MIN_QUESTIONS = 3
_MAX_QUESTIONS = 6
_FIELD_ENOUGH_LEN = 15  # поле уже достаточно раскрыто в черновике — не переспрашиваем


def ai_mode() -> str:
    return settings.LLM_PROVIDER if llm_available() else "stub"


def generate_questions(draft_text: str, industry: str) -> list[Question]:
    preliminary = CardFields(context=draft_text.strip())
    if llm_available():
        questions: list[Question] | None
        try:
            questions = _llm_questions(draft_text, industry, preliminary)
        except (LLMConfigError, LLMResponseError) as exc:
            logger.warning("LLM недоступен для генерации вопросов, включена заглушка: %s", exc)
            questions = None
        if questions is not None:
            return questions
        logger.warning("Ответ LLM не прошёл валидацию вопросов, включена заглушка")
    return _stub_questions(preliminary)


def build_card(draft_text: str, industry: str, answers: list[Answer]) -> CardFields:
    """Заглушка: черновик идёт в контекст, ответы раскладываются по своим полям как есть."""
    fields: dict[str, str] = {"context": draft_text.strip(), "title": draft_text.strip().split("\n")[0][:80]}
    for a in answers:
        if a.field in FIELD_LABELS and a.answer.strip():
            fields[a.field] = a.answer.strip()
    return CardFields(**fields)


def _llm_questions(draft_text: str, industry: str, card: CardFields) -> list[Question] | None:
    rating = compute_rating(card)
    gaps = [
        (item.label, item.weight, item.awarded)
        for item in sorted(rating.items, key=lambda i: i.weight - i.awarded, reverse=True)
        if item.awarded < item.weight
    ]
    user_prompt = build_questions_user_prompt(draft_text, industry, gaps)
    client = get_client()
    response = client.complete(
        [
            {"role": "system", "content": QUESTIONS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        json_schema=QuestionsResponse,
    )
    return _validate_llm_questions(response.questions)


def _validate_llm_questions(questions: list[Question]) -> list[Question] | None:
    if len(questions) < _MIN_QUESTIONS:
        return None
    seen_fields: set[str] = set()
    valid: list[Question] = []
    for q in questions:
        if q.field not in CARD_FIELDS or not q.question.strip() or q.field in seen_fields:
            return None
        seen_fields.add(q.field)
        valid.append(q)
    return valid[:_MAX_QUESTIONS]


def _stub_questions(card: CardFields) -> list[Question]:
    """По показателям с недобором — по одному вопросу на поле, в порядке величины недобора."""
    rating = compute_rating(card)
    gaps = sorted(
        (item for item in rating.items if item.awarded < item.weight),
        key=lambda item: item.weight - item.awarded,
        reverse=True,
    )
    questions: list[Question] = []
    seen_fields: set[str] = set()
    for item in gaps:
        for field in _FIELDS_BY_INDICATOR[item.key]:
            if field in seen_fields or field not in _STUB_QUESTIONS:
                continue
            if len(getattr(card, field, "").strip()) >= _FIELD_ENOUGH_LEN:
                continue
            questions.append(
                Question(field=field, question=_STUB_QUESTIONS[field], why=f"{item.label} — {item.weight} баллов")
            )
            seen_fields.add(field)
            if len(questions) >= _MAX_QUESTIONS:
                return questions
    if len(questions) < _MIN_QUESTIONS:
        for field in CARD_FIELDS:
            if field in seen_fields or field not in _STUB_QUESTIONS:
                continue
            questions.append(
                Question(field=field, question=_STUB_QUESTIONS[field], why="Поле не заполнено")
            )
            seen_fields.add(field)
            if len(questions) >= _MIN_QUESTIONS:
                break
    return questions
