"""Каталог задач и страница задачи с откликами команд (HAC-12, HAC-13).

Отдельный роутер, а не маршруты в `app/main.py`: веб-слой делают два человека
одновременно, и общий файл на двоих — гарантированный конфликт при слиянии.
Подключается одной строкой в `app/main.py`.

Маршруты — по таблице «Маршруты веба» в BRIEF.md:
    GET  /catalog?industry=&level=      каталог, сортировка по рейтингу, фильтры
    GET  /tasks/{card_id}               карточка, расшифровка рейтинга, отклики
    POST /tasks/{card_id}/proposals     отклик команды
    POST /proposals/{proposal_id}/decision  ручное решение бизнеса

Границы кейса, которые здесь соблюдаются буквально:
  * низкий рейтинг задачу не скрывает и не запрещает отклик;
  * число откликов не ограничивается;
  * решение по отклику принимает только человек, автоназначения нет;
  * решение по одному отклику не меняет статусы остальных.
"""

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import ai
from app.models import (
    FIELD_LABELS,
    INDUSTRIES,
    LEVEL_LABELS,
    Proposal,
    new_id,
)
from app.rating import compute_rating
from app.store import get_store

BASE_DIR = Path(__file__).parent

router = APIRouter()
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(
    INDUSTRIES=INDUSTRIES,
    LEVEL_LABELS=LEVEL_LABELS,
    FIELD_LABELS=FIELD_LABELS,
)

PROPOSAL_STATUS_LABELS = {
    "pending": "на рассмотрении",
    "accepted": "выбрана",
    "rejected": "отклонена",
}

# Границы отклика. Не «безопасность», а защита от мусора: эксперт по критерию
# «валидация» пришлёт и километр текста, и javascript: в ссылке.
PROPOSAL_TEXT_MAX = 2000
LINK_PREFIXES = ("http://", "https://")


def _proposal_error(team, idea: str, plan: str, link: str) -> str:
    """Первая найденная ошибка формы отклика, пустая строка если всё в порядке."""
    if team is None:
        return "Выберите команду из списка."
    if not idea or not plan:
        return "Идея решения и план — обязательные поля. Опишите их хотя бы парой предложений."
    if len(idea) > PROPOSAL_TEXT_MAX or len(plan) > PROPOSAL_TEXT_MAX:
        return f"Идея и план — не длиннее {PROPOSAL_TEXT_MAX} символов каждое."
    if link and not link.lower().startswith(LINK_PREFIXES):
        return "Ссылка на прототип должна начинаться с http:// или https://."
    return ""


def _clean_choice(value: str | None, allowed) -> str:
    """Значение фильтра, которого нет в справочнике, считаем не заданным.

    Кейс требует фильтры по теме и уровню; мусор в query не должен ронять страницу.
    """
    value = (value or "").strip()
    return value if value in allowed else ""


@router.get("/catalog", response_class=HTMLResponse)
def catalog(request: Request, industry: str = "", level: str = ""):
    store = get_store()
    industry = _clean_choice(industry, INDUSTRIES)
    level = _clean_choice(level, LEVEL_LABELS)
    shown = store.list_cards(industry=industry or None, level=level or None)
    total = len(store.list_cards())
    return templates.TemplateResponse(
        request,
        "catalog.html",
        {
            "cards": shown,
            "shown": len(shown),
            "total": total,
            "industry": industry,
            "level": level,
            "ai_mode": ai.ai_mode(),
        },
    )


def _task_context(request: Request, card_id: str, *, error: str = "", form: dict | None = None) -> dict:
    store = get_store()
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    proposals = store.list_proposals(card.id)
    teams = {t.id: t for t in store.list_teams()}
    return {
        "request": request,
        "card": card,
        "rating": compute_rating(card),
        "proposals": [(p, teams.get(p.team_id)) for p in proposals],
        "teams": store.list_teams(),
        "status_labels": PROPOSAL_STATUS_LABELS,
        "error": error,
        "form": form or {},
        "ai_mode": ai.ai_mode(),
    }


@router.get("/tasks/{card_id}", response_class=HTMLResponse)
def task_page(request: Request, card_id: str):
    context = _task_context(request, card_id)
    return templates.TemplateResponse(request, "task.html", context)


@router.post("/tasks/{card_id}/proposals")
def create_proposal(
    request: Request,
    card_id: str,
    team_id: str = Form(""),
    idea: str = Form(""),
    plan: str = Form(""),
    deadline: str = Form(""),
    link: str = Form(""),
):
    store = get_store()
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    idea, plan, link = idea.strip(), plan.strip(), link.strip()
    team = store.get_team(team_id.strip())
    error = _proposal_error(team, idea, plan, link)

    if error:
        context = _task_context(
            request,
            card_id,
            error=error,
            form={"team_id": team_id, "idea": idea, "plan": plan, "deadline": deadline, "link": link},
        )
        return templates.TemplateResponse(request, "task.html", context, status_code=200)

    store.add_proposal(
        Proposal(
            id=new_id("p"),
            card_id=card.id,
            team_id=team.id,
            idea=idea,
            plan=plan,
            deadline=deadline.strip(),
            link=link,
        )
    )
    return RedirectResponse(f"/tasks/{card.id}#proposals", status_code=303)


@router.post("/proposals/{proposal_id}/decision")
def decide_proposal(request: Request, proposal_id: str, decision: str = Form("")):
    store = get_store()
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Отклик не найден")

    decision = decision.strip()
    if decision not in {"accept", "reject"}:
        context = _task_context(request, proposal.card_id, error="Неизвестное действие по отклику.")
        return templates.TemplateResponse(request, "task.html", context, status_code=200)

    if proposal.status != "pending":
        # Решение уже принято человеком раньше — молча не перезаписываем.
        context = _task_context(
            request,
            proposal.card_id,
            error=f"По этому отклику решение уже принято: {PROPOSAL_STATUS_LABELS[proposal.status]}.",
        )
        return templates.TemplateResponse(request, "task.html", context, status_code=200)

    # Решение только по этому отклику. Остальные не трогаем: кейс разрешает
    # бизнесу выбрать одну команду, несколько или ни одной.
    proposal.status = "accepted" if decision == "accept" else "rejected"
    store.update_proposal(proposal)
    return RedirectResponse(f"/tasks/{proposal.card_id}#proposals", status_code=303)
