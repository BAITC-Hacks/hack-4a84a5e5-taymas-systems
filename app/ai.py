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
import re

from app.config import settings
from app.llm import LLMConfigError, LLMResponseError, get_client, llm_available
from app.models import CARD_FIELDS, FIELD_LABELS, Answer, CardFields, Question
from app.prompts import (
    CARD_SYSTEM,
    QUESTIONS_SYSTEM,
    QuestionsResponse,
    build_card_user_prompt,
    build_questions_user_prompt,
)
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

# Отраслевые примеры для заглушки: без ключа API вопрос всё равно должен звучать
# как заданный про эту задачу, а не как строка из анкеты (критерий кейса «вопросы уместны»).
_INDUSTRY_USERS: dict[str, str] = {
    "Образование": "студенты, преподаватели, сотрудники деканата",
    "Финансы": "клиенты, операционисты, риск-менеджеры",
    "Ритейл": "покупатели, продавцы, категорийные менеджеры",
    "Логистика": "курьеры, диспетчеры, получатели заказов",
    "Медицина": "пациенты, врачи, администраторы регистратуры",
    "Госуслуги": "жители, операторы приёма, профильные специалисты",
    "Промышленность": "операторы линии, мастера смены, технологи",
}

_INDUSTRY_DATA: dict[str, str] = {
    "Образование": "журналы, расписание, обращения студентов",
    "Финансы": "выписки, заявки, история платежей",
    "Ритейл": "чеки, остатки, история продаж",
    "Логистика": "маршруты, накладные, треки доставок",
    "Медицина": "расписание приёма, обезличенные карты, записи",
    "Госуслуги": "обращения граждан, реестры, регламенты",
    "Промышленность": "показания датчиков, журналы смен, спецификации",
}

# Вводные слова, с которых бизнес обычно начинает черновик: в цитату они не несут смысла.
_FILLER_PREFIX = {
    "хотим", "хочу", "нужен", "нужна", "нужно", "необходим", "необходимо", "требуется",
    "надо", "нам", "мы", "у", "нас", "есть", "сделать", "создать", "разработать", "чтобы",
}

_QUOTE_WORDS = 4
_MIN_QUOTE_WORDS = 2

_MIN_QUESTIONS = 3
_MAX_QUESTIONS = 6
_FIELD_ENOUGH_LEN = 15  # поле уже достаточно раскрыто в черновике — не переспрашиваем

_WORD_RE = re.compile(r"[а-яёa-z]+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[\w.@+-]{3,}")
_STEM_LEN = 5  # длина "корня" слова для нестрогого сопоставления словоформ

# Честность режима (HAC-19): если ключ есть, но конкретный вызов провалился и сработала
# заглушка — это должно быть видно, а не выглядеть так, будто LLM отработал штатно.
# ai_mode() менять нельзя (её уже читает веб), поэтому это отдельный модульный флаг:
# None — последний вызов либо не нуждался в LLM, либо прошёл успешно; иначе — причина отката.
last_fallback_reason: str | None = None


def _set_fallback_reason(reason: str | None) -> None:
    global last_fallback_reason
    last_fallback_reason = reason


def ai_mode() -> str:
    return settings.LLM_PROVIDER if llm_available() else "stub"


def generate_questions(draft_text: str, industry: str) -> list[Question]:
    preliminary = CardFields(context=draft_text.strip())
    if not llm_available():
        _set_fallback_reason(None)
        return _stub_questions(preliminary, industry)

    questions: list[Question] | None
    try:
        questions = _llm_questions(draft_text, industry, preliminary)
    except (LLMConfigError, LLMResponseError) as exc:
        logger.warning("LLM недоступен для генерации вопросов, включена заглушка: %s", exc)
        _set_fallback_reason(f"Вопросы: LLM недоступен, использована заглушка ({exc})")
        return _stub_questions(preliminary, industry)

    if questions is not None:
        _set_fallback_reason(None)
        return questions

    logger.warning("Ответ LLM не прошёл валидацию вопросов, включена заглушка")
    _set_fallback_reason("Вопросы: ответ LLM не прошёл валидацию, использована заглушка")
    return _stub_questions(preliminary, industry)


def build_card(draft_text: str, industry: str, answers: list[Answer]) -> CardFields:
    stub = _stub_card(draft_text, answers)
    if not llm_available():
        _set_fallback_reason(None)
        return stub

    try:
        card = _llm_card(draft_text, industry, answers, stub)
    except (LLMConfigError, LLMResponseError) as exc:
        logger.warning("LLM недоступен для сборки карточки, использую заглушку: %s", exc)
        _set_fallback_reason(f"Карточка: LLM недоступен, использована заглушка ({exc})")
        return stub

    _set_fallback_reason(None)
    return card


def _stub_card(draft_text: str, answers: list[Answer]) -> CardFields:
    """Черновик идёт в контекст, ответы раскладываются по своим полям как есть."""
    draft = draft_text.strip()
    fields: dict[str, str] = {"context": draft, "title": draft.split("\n")[0][:80]}
    for a in answers:
        answer_text = a.answer.strip()
        if a.field not in FIELD_LABELS or not answer_text:
            continue
        if a.field == "context":
            fields["context"] = f"{fields['context']}\n{answer_text}".strip()
        else:
            fields[a.field] = answer_text
    return CardFields(**fields)


def _llm_card(draft_text: str, industry: str, answers: list[Answer], stub: CardFields) -> CardFields:
    user_prompt = build_card_user_prompt(draft_text, industry, answers)
    client = get_client()
    result: CardFields = client.complete(
        [
            {"role": "system", "content": CARD_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        json_schema=CardFields,
    )
    source_text = draft_text + "\n" + "\n".join(a.answer for a in answers)
    fields: dict[str, str] = {}
    for field in CARD_FIELDS:
        value = getattr(result, field, "").strip()
        if value and not _field_is_grounded(value, source_text):
            logger.warning("Поле %r из LLM не подтверждается входом, заменено заглушкой: %r", field, value)
            value = getattr(stub, field, "")
        fields[field] = value
    return CardFields(**fields)


def _field_is_grounded(value: str, source_text: str) -> bool:
    """Защита от выдуманных фактов: значение поля должно опираться на исходный текст.

    Слова длиной >= _STEM_LEN сверяются по первым _STEM_LEN символам (без регистра),
    чтобы не спотыкаться о словоформы. Нужна половина совпадений. Если длинных слов
    нет (например, контакт или короткое значение), сверяем короткие токены целиком —
    иначе выдуманный e-mail без длинных слов проходил бы проверку автоматически.
    """
    long_words = [w for w in _WORD_RE.findall(value) if len(w) >= _STEM_LEN]
    if long_words:
        source_stems = {w[:_STEM_LEN].lower() for w in _WORD_RE.findall(source_text) if len(w) >= _STEM_LEN}
        matched = sum(1 for w in long_words if w[:_STEM_LEN].lower() in source_stems)
        return matched * 2 >= len(long_words)
    tokens = _TOKEN_RE.findall(value)
    if not tokens:
        return True
    source_lower = source_text.lower()
    return any(token.lower() in source_lower for token in tokens)


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


def _draft_quote(text: str) -> str:
    """Короткая цитата из черновика для подстановки в вопрос.

    Берём первые осмысленные слова, пропустив вводные («хотим», «нужен», «чтобы»).
    Если осмысленного мало — возвращаем пустую строку и вопрос остаётся типовым:
    лучше честный шаблон, чем цитата из мусора.
    """
    text = (text or "").strip()
    matches = list(_WORD_RE.finditer(text))
    skip = 0
    while skip < len(matches) and matches[skip].group().lower() in _FILLER_PREFIX:
        skip += 1
    kept = matches[skip : skip + _QUOTE_WORDS]
    if len(kept) < _MIN_QUOTE_WORDS:
        return ""
    # Срез исходной строки, а не склейка слов: сохраняются дефисы и запятые внутри фразы.
    quote = text[kept[0].start() : kept[-1].end()]
    return quote.strip(" ,;:—-")


def _stub_question_text(field: str, industry: str, quote: str, partial: bool) -> str:
    """Типовой вопрос, приправленный контекстом задачи: цитатой, отраслью, пометкой о недоборе."""
    base = _STUB_QUESTIONS[field]
    if partial:
        base = f"Это описано частично. {base}"
    elif quote:
        base = f"Вы написали «{quote}». {base}"
    examples = _INDUSTRY_USERS.get(industry) if field == "users" else _INDUSTRY_DATA.get(industry) if field == "data" else None
    if examples:
        base = f"{base} Например: {examples}."
    return base


def _stub_questions(card: CardFields, industry: str = "") -> list[Question]:
    """По показателям с недобором — по одному вопросу на поле, в порядке величины недобора.

    Формулировка привязана к конкретной задаче: цитата из черновика в первом вопросе,
    отраслевые примеры там, где они помогают, и пометка, если показатель уже описан частично.
    """
    rating = compute_rating(card)
    quote = _draft_quote(card.context)
    quote_used = False
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
            partial = item.awarded > 0
            text = _stub_question_text(field, industry, "" if quote_used else quote, partial)
            if not partial and quote and not quote_used:
                quote_used = True
            why = f"{item.label} — {item.weight} баллов"
            if partial:
                why = f"{why}, начислено {item.awarded}"
            questions.append(Question(field=field, question=text, why=why))
            seen_fields.add(field)
            if len(questions) >= _MAX_QUESTIONS:
                return questions
    if len(questions) < _MIN_QUESTIONS:
        for field in CARD_FIELDS:
            if field in seen_fields or field not in _STUB_QUESTIONS:
                continue
            questions.append(
                Question(
                    field=field,
                    question=_stub_question_text(field, industry, "", False),
                    why="Поле не заполнено",
                )
            )
            seen_fields.add(field)
            if len(questions) >= _MIN_QUESTIONS:
                break
    return questions
