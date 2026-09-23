"""Испытание задачи виртуальной командой (HAC-56): маршруты. Логика — app/trial.py.

    GET  /business/cards/{card_id}/trial            страница: выбор команды и последний результат
    POST /business/cards/{card_id}/trial (team_id)  запустить испытание, сохранить в карточку, 303 на GET
"""

from fastapi import APIRouter

router = APIRouter()
