"""Отдельные маршруты помощников: чтение, диалог и предпросмотр без записи."""
import json
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from app import ai
from app.assistants import coach_report, mission_plan, preview_fields, student_search, position_for, review_proposal, _card_result
from app.models import CARD_FIELDS, FIELD_LABELS
from app.rating import compute_rating
from app.store import get_store

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / 'templates')
templates.env.globals['ai_status'] = ai.ai_mode

class SearchInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=2, max_length=1200)
    history: list[Annotated[str, Field(max_length=1200)]] = Field(default_factory=list, max_length=5)
    team_id: str = Field(default='', max_length=100)

    @field_validator('message')
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('Опишите интересы или навыки.')
        return value.strip()

class CoachInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(default='', max_length=1200)

class PreviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fields: dict[str, Annotated[str, Field(max_length=2000)]] = Field(max_length=11)

    @field_validator('fields')
    @classmethod
    def allowed_fields(cls, fields):
        if not set(fields) <= set(CARD_FIELDS):
            raise ValueError('Неизвестное поле карточки.')
        return fields


def _card(card_id, public=False):
    card = get_store().get_card(card_id)
    if card is None or (public and card.status != 'published'):
        raise HTTPException(404, 'Карточка не найдена')
    return card


def _page(request, **context):
    return templates.TemplateResponse(request, 'assistants.html', {
        'teams': get_store().list_teams(), 'history': [], 'query': '', 'result': None,
        'card': None, 'error': '', 'preview': None, 'field_labels': FIELD_LABELS,
        'ai_mode': ai.ai_mode(), **context})


def _search(data):
    store = get_store()
    team = store.get_team(data.team_id) if data.team_id else None
    if data.team_id and team is None:
        raise HTTPException(400, 'Команда не найдена')
    return student_search(data.message, data.history, store.list_cards(), team)


@router.get('/assistants')
@router.get('/assistants/student')
def student_page(request: Request):
    return _page(request, kind='student')


@router.post('/assistants/student')
async def student_form(request: Request):
    form = await request.form()
    try:
        data = SearchInput(message=str(form.get('message', '')), team_id=str(form.get('team_id', '')),
                           history=json.loads(str(form.get('history', '[]'))))
    except (ValidationError, ValueError, TypeError):
        return _page(request, kind='student', error='Введите запрос от 2 до 1200 символов. История — не более пяти уточнений.')
    result = await run_in_threadpool(_search, data)
    return _page(request, kind='student', result=result, query=data.message,
                 history=[*data.history, data.message][-5:], selected_team=data.team_id)


@router.post('/assistants/student.json')
def student_json(data: SearchInput):
    return _search(data)


@router.get('/business/cards/{card_id}/coach')
def coach_page(request: Request, card_id: str):
    card = _card(card_id)
    return _page(request, kind='coach', card=card,
                 result=coach_report(card, list(get_store().cards.values())))


@router.post('/business/cards/{card_id}/coach')
async def coach_form(request: Request, card_id: str):
    card = _card(card_id)
    form = await request.form()
    query = str(form.get('message', ''))
    if len(query) > 1200:
        return _page(request, kind='coach', card=card, error='Вопрос не длиннее 1200 символов.', result=coach_report(card, list(get_store().cards.values())))
    result = await run_in_threadpool(coach_report, card, list(get_store().cards.values()), query, True)
    return _page(request, kind='coach', card=card, result=result, query=query)


@router.post('/business/cards/{card_id}/coach.json')
def coach_json(card_id: str, data: CoachInput):
    return coach_report(_card(card_id), list(get_store().cards.values()), data.message, True)


@router.post('/business/cards/{card_id}/preview.json')
def preview_json(card_id: str, data: PreviewInput):
    return preview_fields(_card(card_id), data.fields, list(get_store().cards.values()))


@router.post('/business/cards/{card_id}/coach/preview')
async def preview_form(request: Request, card_id: str):
    card = _card(card_id)
    form = await request.form()
    try:
        data = PreviewInput(fields={str(form.get('field', '')): str(form.get('value', ''))})
    except ValidationError:
        raise HTTPException(400, 'Выберите поле и введите не более 2000 символов.')
    return _page(request, kind='coach', card=card, result=coach_report(card, list(get_store().cards.values())),
                 preview=preview_fields(card, data.fields, list(get_store().cards.values())))


@router.get('/assistants/tasks/{card_id}/plan.json')
def plan_json(card_id: str):
    return mission_plan(_card(card_id, public=True))


@router.get('/assistants/compare.json')
def compare_json(ids: Annotated[list[str], Query(min_length=1, max_length=3)]):
    cards = [_card(cid, public=True) for cid in dict.fromkeys(ids)]
    return {'cards': [_card_result(card) for card in cards],
            'notice': 'Сравнение фактов карточек. Балл показывает готовность постановки задачи, а не её соответствие вашей команде.'}


@router.get('/business/cards/{card_id}/position.json')
def position_json(card_id: str, score: Annotated[int | None, Query(ge=0, le=100)] = None):
    card = _card(card_id)
    return position_for(card, compute_rating(card).score if score is None else score, list(get_store().cards.values()))


class ProposalReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idea: str = Field(min_length=1, max_length=2000)
    plan: str = Field(min_length=1, max_length=2000)

    @field_validator('idea', 'plan')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Заполните идею и план.')
        return value.strip()


@router.post('/assistants/tasks/{card_id}/review.json')
def review_json(card_id: str, data: ProposalReviewInput):
    return review_proposal(_card(card_id, public=True), data.idea, data.plan)
