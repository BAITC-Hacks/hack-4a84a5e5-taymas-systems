"""Испытание задачи виртуальной командой (HAC-56): маршруты. Логика — app/trial.py.

    GET  /business/cards/{card_id}/trial            страница: выбор команды и последний результат
    POST /business/cards/{card_id}/trial (team_id)  запустить испытание, сохранить в карточку, 303 на GET

PRG как у конструктора: F5 на странице результата не запускает модель повторно.
"""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app import ai
from app.models import Card
from app.rating import compute_rating
from app.recommend import recommend_tasks
from app.store import get_store
from app.trial import run_trial, trial_badge, trial_is_current
from app.web_catalog import templates  # общий Jinja-env каталога: там уже глобалы ai_status и LEVEL_LABELS

router = APIRouter()
templates.env.globals["trial_badge"] = trial_badge


def _card_or_404(card_id: str) -> Card:
    card = get_store().get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    return card


def _suggest_team(card: Card, teams, score: int):
    """Команда, которой задача подходит по профилю (правила app/recommend.py, по предварительному баллу)."""
    preview = card.model_copy(update={"score": score})
    for team in teams:
        matched = recommend_tasks(team, [preview], limit=1)
        if matched:
            return team, matched[0][1]
    return None


def _page(request: Request, card: Card, *, error: str = "", status_code: int = 200):
    rating = compute_rating(card)
    teams = get_store().list_teams()
    return templates.TemplateResponse(
        request,
        "business_trial.html",
        {
            "card": card,
            "rating": rating,
            "teams": teams,
            "suggested": _suggest_team(card, teams, rating.score),
            "trial": card.trial,
            "current": trial_is_current(card),
            "error": error,
            "ai_mode": ai.ai_mode(),
        },
        status_code=status_code,
    )


@router.get("/business/cards/{card_id}/trial", response_class=HTMLResponse)
def trial_page(request: Request, card_id: str):
    return _page(request, _card_or_404(card_id))


@router.post("/business/cards/{card_id}/trial")
def start_trial(request: Request, card_id: str, team_id: str = Form("")):
    card = _card_or_404(card_id)
    store = get_store()
    team = store.get_team(team_id.strip())
    if team is None:
        return _page(request, card, error="Выберите команду из списка.", status_code=400)
    card.trial = run_trial(card, team)
    store.update_card(card)
    return RedirectResponse(url=f"/business/cards/{card.id}/trial", status_code=303)
