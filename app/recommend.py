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
_MAX_REASONS = 2  # объяснение прозрачное, но не превращается в простыню


def _text_mentions(card: Card, keyword: str) -> bool:
    keyword = keyword.strip().lower()
    if not keyword:
        return False
    haystack = " ".join(getattr(card, field, "") for field in _TEXT_FIELDS).lower()
    return keyword in haystack


def _match(team: Team, card: Card) -> tuple[int, str] | None:
    """Сила совпадения (2 — по отрасли, 1 — по тексту карточки) и объяснение, либо None.

    Объяснение собирает до двух причин через «; »: совпадение по отрасли — самая
    сильная и всегда первая, затем конкретные упоминания интересов или технологий
    в тексте карточки — это делает рекомендацию прозрачнее одной общей фразы.
    """
    reasons: list[str] = []
    signal = 0

    for interest in team.interests:
        if interest.strip().lower() == card.industry.strip().lower():
            reasons.append(f'совпадает интерес „{interest}“ с отраслью задачи')
            signal = _INDUSTRY_SIGNAL
            break

    for interest in team.interests:
        if len(reasons) >= _MAX_REASONS:
            break
        if _text_mentions(card, interest):
            reasons.append(f'в задаче упоминается „{interest}“ — есть в интересах команды')
            signal = max(signal, _TEXT_SIGNAL)

    if len(reasons) < _MAX_REASONS:
        for technology in team.technologies:
            if len(reasons) >= _MAX_REASONS:
                break
            if _text_mentions(card, technology):
                reasons.append(f'в задаче упоминается „{technology}“ — есть среди технологий команды')
                signal = max(signal, _TEXT_SIGNAL)

    if not reasons:
        return None
    explanation = "; ".join(reasons)
    return signal, explanation[0].upper() + explanation[1:]


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
