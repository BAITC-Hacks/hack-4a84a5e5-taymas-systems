"""Рекомендации задач студенческим командам по интересам и навыкам.

Кейс (раздел 5, ключевой принцип): «Система может рекомендовать задачи студентам,
но не назначает команды». Список рекомендаций — необязательная надстройка над
каталогом, а не замена ему: он ничего не скрывает и не фильтрует `list_cards`,
только подсказывает сверху несколько вероятно интересных задач.

Правило кейса (раздел 4, уровень 40–69): «системе разрешено рекомендовать задачу»
только начиная с уровня «рабочая» — черновик (балл < 40) не рекомендуется никому,
даже при полном совпадении интересов.

Детерминированно, без LLM: совпадение интереса команды с отраслью задачи —
самый сильный сигнал, упоминание интереса или технологии в тексте карточки —
более слабый; при равенстве сигнала выше та задача, у которой больше балл.
"""

from app.models import Card, Team

MIN_SCORE = 40

_TEXT_FIELDS = ("title", "context", "need", "expected_result")

_INDUSTRY_SIGNAL = 2
_TEXT_SIGNAL = 1


def _text_mentions(card: Card, keyword: str) -> bool:
    keyword = keyword.strip().lower()
    if not keyword:
        return False
    haystack = " ".join(getattr(card, field, "") for field in _TEXT_FIELDS).lower()
    return keyword in haystack


def _match(team: Team, card: Card) -> tuple[int, str] | None:
    """Сила совпадения (2 — по отрасли, 1 — по тексту карточки) и объяснение, либо None."""
    for interest in team.interests:
        if interest.strip().lower() == card.industry.strip().lower():
            return _INDUSTRY_SIGNAL, f'Совпадает интерес „{interest}“ с отраслью задачи'
    for interest in team.interests:
        if _text_mentions(card, interest):
            return _TEXT_SIGNAL, f'В задаче упоминается „{interest}“ — есть в интересах команды'
    for technology in team.technologies:
        if _text_mentions(card, technology):
            return _TEXT_SIGNAL, f'В задаче упоминается „{technology}“ — есть среди технологий команды'
    return None


def recommend_tasks(team: Team, cards: list[Card], limit: int = 3) -> list[tuple[Card, str]]:
    """Задачи, подходящие команде, с объяснением «почему». Детерминированно, без LLM."""
    candidates: list[tuple[int, int, Card, str]] = []
    for card in cards:
        if card.score < MIN_SCORE:
            continue
        match = _match(team, card)
        if match is None:
            continue
        signal, reason = match
        candidates.append((signal, card.score, card, reason))
    candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
    return [(card, reason) for _signal, _score, card, reason in candidates[:limit]]
