"""Веб-приложение (FastAPI + Jinja2). Владелец файла — поверхность (Анель).

Маршруты и формы — по таблице «Маршруты веба» в BRIEF.md. Фаза 0 оставляет здесь
только скелет: главная и /health. Остальное добавляется тикетами поверхности.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import ai
from app.models import CARD_FIELDS, FIELD_LABELS, INDUSTRIES, LEVEL_LABELS, Answer, Card, new_id
from app.rating import compute_rating
from app.store import get_store
from app.web_catalog import router as catalog_router

BASE_DIR = Path(__file__).parent

app = FastAPI(title="AI Sana Challenge Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(INDUSTRIES=INDUSTRIES, LEVEL_LABELS=LEVEL_LABELS)

# Каталог и страница задачи живут в своём модуле (HAC-12, HAC-13).
app.include_router(catalog_router)


@app.get("/health")
def health() -> dict:
    store = get_store()
    return {"status": "ok", "ai_mode": ai.ai_mode(), "cards": len(store.cards), "teams": len(store.teams)}


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"published": len(store.list_cards()), "teams": len(store.list_teams()), "ai_mode": ai.ai_mode()},
    )
@app.get("/business/new", response_class=HTMLResponse)
def new_business_task(request: Request):
    return templates.TemplateResponse(request, "business_new.html", {"ai_mode": ai.ai_mode()})


@app.post("/business/new", response_class=HTMLResponse)
async def create_business_draft(request: Request):
    form = await request.form()
    text = str(form.get("text", "")).strip()
    industry = str(form.get("industry", "")).strip()
    if not text:
        return templates.TemplateResponse(request, "business_new.html", {"ai_mode": ai.ai_mode(), "error": "Describe the task before continuing.", "text": text, "industry": industry}, status_code=400)
    if industry not in INDUSTRIES:
        industry = INDUSTRIES[-1]
    store = get_store()
    draft = store.add_draft(text, industry)
    draft.questions = ai.generate_questions(draft.text, draft.industry)
    store.update_draft(draft)
    return templates.TemplateResponse(request, "business_questions.html", {"draft": draft, "ai_mode": ai.ai_mode()})


@app.post("/business/drafts/{draft_id}/answers")
async def save_answers(request: Request, draft_id: str):
    store = get_store()
    draft = store.get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    form = await request.form()
    answers = [Answer(field=q.field, question=q.question, answer=str(form.get(f"answer_{i}", "")).strip()) for i, q in enumerate(draft.questions)]
    fields = ai.build_card(draft.text, draft.industry, answers)
    card = store.add_card(Card(id=new_id("c"), draft_id=draft.id, industry=draft.industry, answers=answers, **fields.model_dump()))
    return RedirectResponse(url=f"/business/cards/{card.id}/edit", status_code=303)


@app.get("/business/cards/{card_id}/edit", response_class=HTMLResponse)
def edit_card(request: Request, card_id: str):
    card = get_store().get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return templates.TemplateResponse(request, "business_card_edit.html", {"card": card, "rating": compute_rating(card), "field_labels": FIELD_LABELS, "ai_mode": ai.ai_mode()})


@app.post("/business/cards/{card_id}/edit")
async def update_card(request: Request, card_id: str):
    store = get_store()
    card = store.get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    form = await request.form()
    for field in CARD_FIELDS:
        setattr(card, field, str(form.get(field, "")).strip())
    card.confirmed = False
    store.update_card(card)
    return RedirectResponse(url=f"/business/cards/{card.id}/edit", status_code=303)

