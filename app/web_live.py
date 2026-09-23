"""Живой каталог: JSON-срезы состояния для клиента (HAC-57). Только чтение.

Владелец — вторая сессия капитана (тикет HAC-57). Скелет создан Claude, чтобы include
в app/main.py и подключение static/live.js были сделаны один раз и никто не правил чужие файлы.

    GET /catalog.json?industry=&level=   карточки в порядке каталога, позиции 1..N по всему каталогу

Порядок и состав — ровно те, что у HTML-каталога: store.list_cards(). Ничего не пишет.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.models import INDUSTRIES, LEVEL_LABELS
from app.store import get_store
from app.trial import trial_badge

router = APIRouter()


def _clean_choice(value: str | None, allowed) -> str:
    value = (value or "").strip()
    return value if value in allowed else ""


def _trial_passed(card) -> bool:
    """Знак «прошла испытание» — тот же, что в HTML-каталоге (app/trial.py, HAC-56)."""
    return trial_badge(card)


@router.get("/catalog.json")
def catalog_json(industry: str = "", level: str = "") -> dict:
    store = get_store()
    industry = _clean_choice(industry, INDUSTRIES)
    level = _clean_choice(level, LEVEL_LABELS)
    published = store.list_cards()
    positions = {card.id: index + 1 for index, card in enumerate(published)}
    shown = store.list_cards(industry=industry or None, level=level or None)
    proposal_counts: dict[str, int] = {}
    for proposal in store.proposals.values():
        proposal_counts[proposal.card_id] = proposal_counts.get(proposal.card_id, 0) + 1
    return {
        "cards": [
            {
                "id": card.id,
                "title": card.title,
                "industry": card.industry,
                "score": card.score,
                "level": card.level,
                "level_label": card.level_label,
                "position": positions[card.id],
                "proposals": proposal_counts.get(card.id, 0),
                "trial_passed": _trial_passed(card),
                "published_at": card.published_at.isoformat() if card.published_at else None,
            }
            for card in shown
        ],
        "total": len(published),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/feed.json")
def feed_json() -> dict:
    """Последние события опубликованных задач; только существующие отметки времени."""
    store = get_store()
    events = []

    def event(at, kind, text, card_id):
        # Старые сиды могли содержать даты без часового пояса.
        at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at
        events.append({"at": at.astimezone(timezone.utc).isoformat(), "kind": kind,
                       "text": text, "card_id": card_id})

    published = {c.id: c for c in store.list_cards()}
    for card in published.values():
        if card.published_at:
            event(card.published_at, "published", f'Опубликована задача «{card.title or "Без названия"}»', card.id)
    for proposal in list(store.proposals.values()):
        card = published.get(proposal.card_id)
        if not card:
            continue
        team = store.get_team(proposal.team_id)
        name = team.name if team else "Команда"
        event(proposal.created_at, "proposal", f'{name}: отклик на «{card.title}»', card.id)
        if proposal.decided_at and proposal.status in {"accepted", "rejected"}:
            decision = "принят" if proposal.status == "accepted" else "отклонён"
            event(proposal.decided_at, "decision", f'Отклик {name} на «{card.title}» {decision} бизнесом', card.id)
    events.sort(key=lambda e: e["at"], reverse=True)
    return {"events": events[:10]}
