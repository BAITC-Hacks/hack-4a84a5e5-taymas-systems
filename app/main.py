"""Веб-приложение (FastAPI + Jinja2). Владелец файла — поверхность (Анель).

Маршруты и формы — по таблице «Маршруты веба» в BRIEF.md. Фаза 0 оставляет здесь
только скелет: главная и /health. Остальное добавляется тикетами поверхности.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import ai
from app.models import INDUSTRIES, LEVEL_LABELS
from app.store import get_store

BASE_DIR = Path(__file__).parent

app = FastAPI(title="AI Sana Challenge Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(INDUSTRIES=INDUSTRIES, LEVEL_LABELS=LEVEL_LABELS)


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
