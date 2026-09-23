"""Живой каталог: JSON-срезы состояния для клиента (HAC-57). Только чтение.

Владелец — вторая сессия капитана (тикет HAC-57). Скелет создан Claude, чтобы include
в app/main.py и подключение static/live.js были сделаны один раз и никто не правил чужие файлы.

    GET /catalog.json?industry=&level=   карточки в порядке каталога, позиции 1..N по всему каталогу

Порядок и состав — ровно те, что у HTML-каталога: store.list_cards(). Ничего не пишет.
"""

from datetime import datetime, timezone

from fastapi import APIRouter

from app.models import INDUSTRIES, LEVEL_LABELS
from app.rating import compute_rating
from app.store import get_store

router = APIRouter()


def _clean_choice(value: str | None, allowed) -> str:
    value = (value or "").strip()
    return value if value in allowed else ""


def _trial_passed(card) -> bool:
    """Знак «прошла испытание» действителен, пока карточку не правили после испытания (HAC-56)."""
    trial = getattr(card, "trial", None)
    return bool(trial and trial.passed and trial.score_at == compute_rating(card).score)


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
