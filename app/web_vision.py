"""Черновик из фото (HAC-58): маршрут. Логика — app/vision.py.

    POST /business/photo (photo, industry, context)  → JSON PhotoResult

Файл читается в память, уходит в модель и забывается: хранилище не трогается.
Ответ всегда JSON, даже при ошибках: маршрут зовёт скрипт формы черновика, а не браузер.
Коды: 200 — разобрано (ok в теле) · 422 — файл не подходит · 503 — модель недоступна.
"""

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.models import INDUSTRIES
from app.vision import MAX_BYTES, PhotoResult, describe_photo

router = APIRouter()

_STATUS = {"invalid": 422, "unavailable": 503}


@router.post("/business/photo")
async def photo_to_draft(
    photo: UploadFile | None = File(default=None),
    industry: str = Form(default=""),
    context: str = Form(default=""),
) -> JSONResponse:
    if photo is None:
        result = PhotoResult(ok=False, mode="invalid", message="Файл не передан. Приложите фото.")
    else:
        data = await photo.read(MAX_BYTES + 1)  # на байт больше лимита: перебор увидит validate_photo
        await photo.close()
        result = await run_in_threadpool(describe_photo, data, industry if industry in INDUSTRIES else "", context)
    status = 200 if result.ok else _STATUS.get(result.mode, 200)
    return JSONResponse(result.model_dump(), status_code=status)
