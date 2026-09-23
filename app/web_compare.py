"""Сравнение откликов (HAC-59): маршрут. Логика — app/compare.py.

    GET /tasks/{card_id}/compare   отклики рядом: факты по каждому и разбор моделью без ранжирования

Решение «принять / отклонить» остаётся на странице задачи: здесь только материал для решения.
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from app import ai
from app.compare import compare_proposals
from app.store import get_store
from app.web_catalog import templates  # общий Jinja-env каталога: глобалы ai_status и LEVEL_LABELS

router = APIRouter()

STATUS_LABELS = {"pending": "На рассмотрении", "accepted": "Принят", "rejected": "Отклонён"}


@router.get("/tasks/{card_id}/compare", response_class=HTMLResponse)
def compare_page(request: Request, card_id: str):
    store = get_store()
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    proposals = store.list_proposals(card.id)
    pairs = [(p, store.get_team(p.team_id)) for p in proposals]
    comparison = compare_proposals(card, pairs)
    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "card": card,
            "pairs": pairs,
            "comparison": comparison,
            "facts_by_id": {f.proposal_id: f for f in comparison.facts},
            "status_labels": STATUS_LABELS,
            "ai_mode": ai.ai_mode(),
        },
    )
