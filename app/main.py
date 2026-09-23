"""Веб-приложение (FastAPI + Jinja2). Владелец файла — поверхность (Анель).

Маршруты и формы — по таблице «Маршруты веба» в BRIEF.md. Фаза 0 оставляет здесь
только скелет: главная и /health. Остальное добавляется тикетами поверхности.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import ai
from app.models import CARD_FIELDS, FIELD_LABELS, INDUSTRIES, LEVEL_LABELS, Answer, Card, new_id, now
from app.rating import SCALE, compute_rating
from app.store import get_store
from app.web_catalog import router as catalog_router
from app.web_catalog import templates as catalog_templates

BASE_DIR = Path(__file__).parent

app = FastAPI(title="AI Sana Challenge Hub", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals.update(INDUSTRIES=INDUSTRIES, LEVEL_LABELS=LEVEL_LABELS)

# Каталог и страница задачи живут в своём модуле (HAC-12, HAC-13).
app.include_router(catalog_router)

_PROVIDER_NAMES = {"openai": "OpenAI", "nvidia": "NVIDIA"}


def ai_status() -> str:
    """Подпись режима ИИ для подвала: при откате на заглушку после сбоя вызова говорит об этом прямо."""
    mode = ai.ai_mode()
    reason = ai.last_fallback_reason
    if mode == "stub" or not reason:
        return mode
    if len(reason) > 160:
        reason = reason[:157] + "…"
    return f"заглушка ({_PROVIDER_NAMES.get(mode, mode)} недоступен: {reason})"


# У роутера каталога свой объект шаблонов — подвал общий, поэтому глобал ставится в оба.
for _env in (templates.env, catalog_templates.env):
    _env.globals["ai_status"] = ai_status

logger = logging.getLogger(__name__)

_ERROR_TITLES = {
    400: "Некорректный запрос",
    404: "Страница не найдена",
    405: "Такое действие здесь недоступно",
}


def _error_page(request: Request, status_code: int, detail: str = ""):
    title = _ERROR_TITLES.get(status_code, "Что-то пошло не так" if status_code >= 500 else "Запрос не выполнен")
    # Стандартные английские detail Starlette («Not Found») человеку не показываем.
    if not detail or detail.isascii():
        detail = "Проверьте адрес или вернитесь на главную." if status_code < 500 else "Ошибка на сервере. Попробуйте ещё раз чуть позже."
    context = {"status_code": status_code, "title": title, "detail": detail, "ai_mode": ai.ai_mode()}
    return templates.TemplateResponse(request, "error.html", context, status_code=status_code)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return _error_page(request, exc.status_code, str(exc.detail or ""))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return _error_page(request, 400, "Форма заполнена некорректно. Вернитесь назад и проверьте поля.")


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    logger.exception("Необработанная ошибка на %s", request.url.path)
    return _error_page(request, 500)


@app.get("/health")
def health() -> dict:
    store = get_store()
    return {
        "status": "ok",
        "ai_mode": ai.ai_mode(),
        "ai_fallback": ai.last_fallback_reason,
        "cards_total": len(store.cards),
        "cards_published": len(store.list_cards()),
        "teams": len(store.teams),
        "proposals": len(store.proposals),
        "drafts": len(store.drafts),
        "store": store.path.as_posix(),
        "version": os.environ.get("APP_VERSION") or "dev",
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    store = get_store()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"published": len(store.list_cards()), "teams": len(store.list_teams()), "ai_mode": ai.ai_mode()},
    )
# Подсказки полей — из колонки «Как считать» раздела 4 ТЗ.
FIELD_PLACEHOLDERS = {
    "title": "Коротко: что нужно сделать и для кого",
    "context": "Что происходит сейчас: объёмы, сроки, кто страдает",
    "need": "Что необходимо изменить",
    "users": "Для кого создаётся решение: роли и количество",
    "data": "Доступные данные, примеры или источники: формат, объём, где лежат",
    "constraints": "Сроки, технологии, доступы или иные границы",
    "expected_result": "Конкретный результат работы команды: сервис, прототип, отчёт",
    "success_criteria": "Измеримые признаки: проценты, время, доля",
    "contact": "Кто отвечает на вопросы команды",
    "interaction_format": "Формат консультаций и порядок обратной связи",
}

MAX_DRAFT_LEN = 4000
MAX_FIELD_LEN = 2000


def _too_long(value: str, limit: int) -> str:
    return f"Не длиннее {limit} символов, сейчас {len(value)}. Сократите текст."


def _page(request: Request, name: str, context: dict, status_code: int = 200):
    return templates.TemplateResponse(request, name, {"ai_mode": ai.ai_mode(), **context}, status_code=status_code)


@app.get("/business/new", response_class=HTMLResponse)
def new_business_task(request: Request):
    return _page(request, "business_new.html", {"errors": {}})


@app.post("/business/new", response_class=HTMLResponse)
async def create_business_draft(request: Request):
    form = await request.form()
    text = str(form.get("text", "")).strip()
    industry = str(form.get("industry", "")).strip()
    errors = {}
    if not text:
        errors["text"] = "Опишите задачу — черновик не может быть пустым."
    elif len(text) > MAX_DRAFT_LEN:
        errors["text"] = _too_long(text, MAX_DRAFT_LEN) + " Детали можно добавить в ответах на вопросы и в редакторе."
    if industry not in INDUSTRIES:
        errors["industry"] = "Выберите отрасль из списка."
    if errors:
        context = {"errors": errors, "error": "Проверьте поля формы.", "text": text, "industry": industry}
        return _page(request, "business_new.html", context, status_code=400)
    store = get_store()
    draft = store.add_draft(text, industry)
    draft.questions = ai.generate_questions(draft.text, draft.industry)
    store.update_draft(draft)
    # PRG: F5 на странице вопросов не создаёт второй черновик и не зовёт LLM повторно.
    return RedirectResponse(url=f"/business/drafts/{draft.id}", status_code=303)


def _get_draft_or_404(draft_id: str):
    draft = get_store().get_draft(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Черновик не найден")
    return draft


@app.get("/business/drafts/{draft_id}", response_class=HTMLResponse)
def draft_questions(request: Request, draft_id: str):
    return _page(request, "business_questions.html", {"draft": _get_draft_or_404(draft_id), "answers": {}, "errors": {}})


@app.post("/business/drafts/{draft_id}/answers")
async def save_answers(request: Request, draft_id: str):
    store = get_store()
    draft = _get_draft_or_404(draft_id)
    form = await request.form()
    values = {i: str(form.get(f"answer_{i}", "")).strip() for i in range(len(draft.questions))}
    errors = {i: _too_long(v, MAX_FIELD_LEN) for i, v in values.items() if len(v) > MAX_FIELD_LEN}
    if errors:
        context = {"draft": draft, "answers": values, "errors": errors, "error": "Проверьте ответы."}
        return _page(request, "business_questions.html", context, status_code=400)
    answers = [Answer(field=q.field, question=q.question, answer=values[i]) for i, q in enumerate(draft.questions)]
    fields = ai.build_card(draft.text, draft.industry, answers)
    card = store.add_card(Card(id=new_id("c"), draft_id=draft.id, industry=draft.industry, answers=answers, **fields.model_dump()))
    return RedirectResponse(url=f"/business/cards/{card.id}/edit", status_code=303)


def _get_card_or_404(card_id: str) -> Card:
    card = get_store().get_card(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Карточка не найдена")
    return card


def _editor(
    request: Request,
    card: Card,
    *,
    message: str = "",
    error: str = "",
    form_card: Card | None = None,
    errors: dict | None = None,
    change: dict | None = None,
):
    """form_card — то, что показывать в полях (введённое при ошибке), card — сохранённая версия для рейтинга."""
    rating = compute_rating(card)
    items = {item.key: item for item in rating.items}
    field_items = {field: items[key] for key, _label, _weight, fields in SCALE for field in fields}
    return _page(
        request,
        "business_card_edit.html",
        {
            "card": card,
            "form_card": form_card or card,
            "rating": rating,
            "field_items": field_items,
            "item_fields": {key: fields[0] for key, _label, _weight, fields in SCALE},
            "placeholders": FIELD_PLACEHOLDERS,
            "card_fields": CARD_FIELDS,
            "field_labels": FIELD_LABELS,
            "answered": sum(1 for a in card.answers if a.answer),
            "message": message,
            "error": error,
            "errors": errors or {},
            "change": change,
        },
        status_code=400 if errors else 200,
    )


def _field_errors(form) -> dict:
    errors = {}
    for field in CARD_FIELDS:
        value = str(form.get(field, "")).strip()
        if len(value) > MAX_FIELD_LEN:
            errors[field] = _too_long(value, MAX_FIELD_LEN)
    if "industry" in form and str(form.get("industry", "")).strip() not in INDUSTRIES:
        errors["industry"] = "Выберите отрасль из списка."
    return errors


def _rejected(request: Request, card: Card, form, errors: dict):
    """Ничего не сохраняет, возвращает редактор с введённым текстом и ошибками у полей."""
    draft_copy = card.model_copy(deep=True)
    for field in CARD_FIELDS:
        if field in form:
            setattr(draft_copy, field, str(form.get(field, "")).strip())
    return _editor(request, card, form_card=draft_copy, errors=errors, error="Изменения не сохранены: проверьте отмеченные поля.")


def _apply_form(card: Card, form) -> bool:
    """Переносит поля формы в карточку. Отсутствующие в форме поля не трогает."""
    changed = False
    for field in CARD_FIELDS:
        if field in form:
            value = str(form.get(field, "")).strip()
            if value != getattr(card, field):
                setattr(card, field, value)
                changed = True
    if "industry" in form:
        industry = str(form.get("industry", "")).strip()
        if industry in INDUSTRIES and industry != card.industry:
            card.industry = industry
            changed = True
    return changed


def _confirmed_note(card: Card) -> str:
    if card.status == "published":
        return f"Подтверждено: {card.score}. Подтвердите изменения, чтобы зачесть новый балл."
    return "Карточка ещё не подтверждена. Подтвердите, чтобы опубликовать и зачесть балл."


@app.get("/business/cards/{card_id}/edit", response_class=HTMLResponse)
def edit_card(request: Request, card_id: str):
    return _editor(request, _get_card_or_404(card_id))


@app.post("/business/cards/{card_id}/edit", response_class=HTMLResponse)
async def update_card(request: Request, card_id: str):
    card = _get_card_or_404(card_id)
    form = await request.form()
    errors = _field_errors(form)
    if errors:
        return _rejected(request, card, form, errors)
    before = compute_rating(card).score
    _apply_form(card, form)
    # Балл зачитывается только при подтверждении: score/level здесь не трогаем.
    card.confirmed = False
    get_store().update_card(card)
    after = compute_rating(card).score
    return _editor(request, card, message=_confirmed_note(card), change={"before": before, "after": after})


@app.post("/business/cards/{card_id}/publish", response_class=HTMLResponse)
async def publish_card(request: Request, card_id: str):
    card = _get_card_or_404(card_id)
    form = await request.form()
    errors = _field_errors(form)
    if errors:
        return _rejected(request, card, form, errors)
    store = get_store()
    if _apply_form(card, form):
        card.confirmed = False
        store.update_card(card)
    if form.get("confirmed") != "on":
        error = "Отметьте «Подтверждаю, что карточка составлена верно» — без подтверждения баллы не начисляются."
        return _editor(request, card, error=error)
    rating = compute_rating(card)
    card.score = rating.score
    card.level = rating.level
    card.confirmed = True
    card.status = "published"
    if card.published_at is None:
        card.published_at = now()
    store.update_card(card)
    return RedirectResponse(url=f"/tasks/{card.id}", status_code=303)

