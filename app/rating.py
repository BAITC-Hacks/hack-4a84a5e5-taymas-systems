"""Рейтинг готовности задачи, 0–100. Детерминированные правила, без LLM.

Контракт (BRIEF.md): compute_rating(card: CardFields) -> Rating, level_for(score) -> Level.
Шкала кейса (раздел 4): контекст и потребность 20 · данные 20 · ожидаемый результат 15 ·
критерии успеха 15 · ограничения 10 · пользователи 10 · связь с бизнесом 10.

Формула (для README): у каждого показателя три уровня начисления — 0, половина или полный
вес. Половина — поле заполнено достаточным текстом. Полный вес — текст ещё и содержит
конкретику, которую требует кейс (цифры, артефакт, срок, роль и т.п.). Поле "заполнено",
если после strip() его длина не меньше порога и текст не входит в список пустышек
("нет", "-", "не знаю" и т.п.) — иначе просто непустая строка засчитывалась бы как ответ.
"""

import re

from app.models import LEVEL_LABELS, CardFields, Level, Rating, RatingItem

# (ключ показателя, подпись, вес, какие поля карточки его закрывают)
SCALE: list[tuple[str, str, int, list[str]]] = [
    ("context_need", "Контекст и потребность", 20, ["context", "need"]),
    ("data", "Данные и материалы", 20, ["data"]),
    ("expected_result", "Ожидаемый результат", 15, ["expected_result"]),
    ("success_criteria", "Критерии успеха", 15, ["success_criteria"]),
    ("constraints", "Ограничения", 10, ["constraints"]),
    ("users", "Пользователи", 10, ["users"]),
    ("business_link", "Связь с бизнесом", 10, ["contact", "interaction_format"]),
]

_STUB_PHRASES = {
    "нет", "-", "—", "нет данных", "не знаю", "n/a", "пока нет",
    "неизвестно", "уточняется", "todo", "тбд", "не указано",
}

_DATA_HINTS = re.compile(r"\d|csv|excel|json|pdf|api|база|выгрузк|таблиц|пример|записей", re.IGNORECASE)
_ARTIFACT_WORDS = re.compile(r"прототип|сервис|отчёт|модель|дашборд|приложени|бот|api|интерфейс|документ", re.IGNORECASE)
_MEASURABLE_WORDS = re.compile(r"\d|%|сниз|увелич|повыси|сократ|не менее|не более|точност|время|доля", re.IGNORECASE)
_DEADLINE_WORDS = re.compile(r"\d|недел|месяц|дней|дата", re.IGNORECASE)
_TECH_ACCESS_WORDS = re.compile(r"технолог|доступ|бюджет|лицензи|оборудован|инфраструктур|стек|сервер|конфиденциальн", re.IGNORECASE)
_ROLE_COUNT_WORDS = re.compile(
    r"\d|человек|менеджер|администратор|куратор|оператор|клиент|студент|врач|"
    r"пользовател|сотрудник|диспетчер|заведующ|пациент|жител",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"\+?\d[\d\-\s()]{6,}\d")


def _clean(text: str | None) -> str:
    return (text or "").strip()


def _is_stub(text: str) -> bool:
    return text.lower().rstrip(".!?") in _STUB_PHRASES


def _filled(text: str | None, min_len: int) -> bool:
    cleaned = _clean(text)
    return len(cleaned) >= min_len and not _is_stub(cleaned)


def _score_context_need(card: CardFields) -> tuple[int, str]:
    context_ok = _filled(card.context, 20)
    need_ok = _filled(card.need, 20)
    awarded = (10 if context_ok else 0) + (10 if need_ok else 0)
    missing_parts = []
    if not context_ok:
        missing_parts.append("текущую ситуацию (контекст)")
    if not need_ok:
        missing_parts.append("что нужно изменить (потребность)")
    hint = f"Опишите {' и '.join(missing_parts)}" if missing_parts else ""
    return awarded, hint


def _score_data(card: CardFields) -> tuple[int, str]:
    text = _clean(card.data)
    if not _filled(text, 20):
        return 0, "Опишите доступные данные: формат, объём и пример"
    if _DATA_HINTS.search(text):
        return 20, ""
    return 10, "Добавьте конкретику о данных: формат (CSV/Excel/PDF/API), объём или пример записи"


def _score_expected_result(card: CardFields) -> tuple[int, str]:
    text = _clean(card.expected_result)
    if not _filled(text, 20):
        return 0, "Опишите ожидаемый результат: что именно должно получиться"
    if len(text) >= 60 or _ARTIFACT_WORDS.search(text):
        return 15, ""
    return 8, "Уточните ожидаемый результат: какой артефакт получится (прототип, сервис, отчёт, модель...) и в каком объёме"


def _score_success_criteria(card: CardFields) -> tuple[int, str]:
    text = _clean(card.success_criteria)
    if not _filled(text, 20):
        return 0, "Опишите критерии успеха: как поймёте, что решение сработало"
    if _MEASURABLE_WORDS.search(text):
        return 15, ""
    return 8, "Добавьте измеримый признак: число, процент или срок"


def _score_constraints(card: CardFields) -> tuple[int, str]:
    text = _clean(card.constraints)
    if not _filled(text, 10):
        return 0, "Укажите ограничения: сроки, технологии или доступы"
    if _DEADLINE_WORDS.search(text) or _TECH_ACCESS_WORDS.search(text):
        return 10, ""
    return 5, "Добавьте конкретику: срок (недели/месяцы/дата) или технологии и доступы"


def _score_users(card: CardFields) -> tuple[int, str]:
    text = _clean(card.users)
    if not _filled(text, 10):
        return 0, "Опишите пользователей: кто и сколько будет использовать решение"
    if len(text) >= 30 or _ROLE_COUNT_WORDS.search(text):
        return 10, ""
    return 5, "Уточните пользователей: роли и примерное количество"


def _score_business_link(card: CardFields) -> tuple[int, str]:
    contact = _clean(card.contact)
    fmt = _clean(card.interaction_format)
    contact_ok = bool(contact) and not _is_stub(contact) and (
        "@" in contact or bool(_PHONE_RE.search(contact)) or len(contact) >= 5
    )
    fmt_ok = _filled(fmt, 10)
    awarded = (5 if contact_ok else 0) + (5 if fmt_ok else 0)
    missing_parts = []
    if not contact_ok:
        missing_parts.append("контакт (почта или телефон)")
    if not fmt_ok:
        missing_parts.append("формат консультаций и порядок обратной связи")
    hint = f"Укажите {', '.join(missing_parts)}" if missing_parts else ""
    return awarded, hint


_SCORERS = {
    "context_need": _score_context_need,
    "data": _score_data,
    "expected_result": _score_expected_result,
    "success_criteria": _score_success_criteria,
    "constraints": _score_constraints,
    "users": _score_users,
    "business_link": _score_business_link,
}


def level_for(score: int) -> Level:
    if score >= 90:
        return "priority"
    if score >= 70:
        return "ready"
    if score >= 40:
        return "workable"
    return "draft"


def compute_rating(card: CardFields) -> Rating:
    items: list[RatingItem] = []
    deficits: list[tuple[int, str]] = []
    for key, label, weight, _fields in SCALE:
        awarded, hint = _SCORERS[key](card)
        items.append(RatingItem(key=key, label=label, weight=weight, awarded=awarded, hint=hint))
        if hint:
            deficits.append((weight - awarded, f"{label}: {hint}"))
    deficits.sort(key=lambda pair: pair[0], reverse=True)
    missing = [text for _, text in deficits]
    score = sum(i.awarded for i in items)
    level = level_for(score)
    return Rating(score=score, level=level, level_label=LEVEL_LABELS[level], items=items, missing=missing)


def progress_bar(score: int, width: int = 10) -> str:
    """Текстовый прогресс-бар рейтинга, например «████████░░ 80/100». Для логов и консоли."""
    clamped = max(0, min(100, score))
    filled = round(width * clamped / 100)
    return f"{'█' * filled}{'░' * (width - filled)} {clamped}/100"


def next_best_action(rating: Rating) -> str | None:
    """Самая весомая подсказка, что дописать дальше (rating.missing уже отсортирован по недобору).

    None, если рейтинг полный и дописывать нечего.
    """
    return rating.missing[0] if rating.missing else None


def rating_summary(rating: Rating) -> str:
    """Однострочная сводка рейтинга: балл, уровень и самая весомая подсказка."""
    summary = f"{rating.score}/100 — {rating.level_label}"
    hint = next_best_action(rating)
    if hint:
        summary = f"{summary}. Не хватает: {hint}"
    return summary
