"""Рейтинг готовности задачи, 0–100. ЗАГЛУШКА фазы 1 — заменяется в тикете ядра.

Контракт (BRIEF.md): compute_rating(card: CardFields) -> Rating, level_for(score) -> Level.
Шкала кейса (раздел 4): контекст и потребность 20 · данные 20 · ожидаемый результат 15 ·
критерии успеха 15 · ограничения 10 · пользователи 10 · связь с бизнесом 10.
"""

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


def level_for(score: int) -> Level:
    if score >= 90:
        return "priority"
    if score >= 70:
        return "ready"
    if score >= 40:
        return "workable"
    return "draft"


def compute_rating(card: CardFields) -> Rating:
    """Заглушка: поле считается закрытым, если в нём есть хоть какой-то текст."""
    items: list[RatingItem] = []
    missing: list[str] = []
    for key, label, weight, fields in SCALE:
        filled = sum(1 for f in fields if getattr(card, f, "").strip())
        awarded = round(weight * filled / len(fields))
        hint = "" if filled == len(fields) else f"Заполните: {', '.join(fields)}"
        items.append(RatingItem(key=key, label=label, weight=weight, awarded=awarded, hint=hint))
        if hint:
            missing.append(f"{label}: {hint}")
    score = sum(i.awarded for i in items)
    level = level_for(score)
    return Rating(score=score, level=level, level_label=LEVEL_LABELS[level], items=items, missing=missing)
