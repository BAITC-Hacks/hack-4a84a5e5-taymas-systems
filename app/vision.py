"""Черновик из фото (HAC-58): модель описывает, что видно на снимке, текст ложится в поле черновика.

Рамки — раздел 5 ТЗ: «ИИ не должен добавлять факты, которых не сообщил пользователь» и
«сформированный текст редактируется и подтверждается человеком». Поэтому модель не решает,
что нужно сделать, а только описывает видимое; результат попадает в поле черновика, где его
правит представитель бизнеса, и дальше идёт обычный путь конструктора.

Ничего не сохраняется: ни файл, ни ответ модели. Фото живёт в памяти на время одного запроса.
Заглушки нет: без ключа функция честно сообщает, что недоступна. Только провайдер openai,
NVIDIA-резерв текстовый и изображений не видит.

describe_photo() никогда не бросает — как и остальные границы слоя ИИ (app/ai.py, app/trial.py).
"""

import base64
import logging

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import LLMConfigError, LLMResponseError, get_client, llm_available

logger = logging.getLogger(__name__)

MAX_BYTES = 5 * 1024 * 1024  # больше — это уже не фото с телефона, а мусор или удар по памяти
MAX_DRAFT_CHARS = 1500  # поле черновика принимает 4000, оставляем место словам человека

# Тип определяется по первым байтам, а не по расширению и не по Content-Type от браузера.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff_mime(data: bytes) -> str | None:
    for signature, mime in _SIGNATURES:
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class PhotoDescription(BaseModel):
    """Формат ответа модели. Все поля — про видимое, а не про то, что делать."""

    seen: str = Field(description="Что видно на фото: объекты, обстановка, текст и надписи дословно")
    problem: str = Field(
        default="",
        description="Что на фото похоже на проблему или неисправность. Только если это видно; иначе пустая строка",
    )
    unclear: str = Field(default="", description="Что по фото определить нельзя и стоит уточнить у автора")
    draft: str = Field(description="Черновик задачи от первого лица бизнеса, 2–4 предложения, только по видимому")


class PhotoResult(BaseModel):
    ok: bool
    mode: str  # "openai" — разобрано моделью · "unavailable" — нет ключа или сбой · "invalid" — файл не подходит
    message: str = ""  # человеку: что случилось или что делать
    description: PhotoDescription | None = None
    draft: str = ""  # готовый текст для поля черновика


SYSTEM_PROMPT = """Ты помогаешь представителю бизнеса описать задачу для студенческой команды по фотографии.

Правила:
1. Описывай только то, что действительно видно на фото. Не додумывай, что это за компания, где это снято, кто на фото и чем занимаются люди.
2. Если на фото есть текст, надписи, экраны, таблицы или документы — перескажи их содержимое дословно, не дополняя.
3. Не предлагай решений, технологий и планов: что делать, решит человек. Не пиши «нужно внедрить» или «стоит разработать».
4. Проблему называй только если она видна на снимке (поломка, очередь, беспорядок, ошибка на экране). Если не видна — оставь поле problem пустым.
5. В поле unclear перечисли, чего по фото определить нельзя: масштаб, сроки, кто пользователи, какие есть данные.
6. Поле draft — 2–4 предложения от первого лица бизнеса («У нас…», «На фото…»), только по видимому, без выводов и предложений.
7. Пиши по-русски. Если это не фото рабочей ситуации (селфи, пейзаж, мем), честно скажи об этом в seen и оставь draft пустым."""


def _unavailable(message: str) -> PhotoResult:
    return PhotoResult(ok=False, mode="unavailable", message=message)


def _invalid(message: str) -> PhotoResult:
    return PhotoResult(ok=False, mode="invalid", message=message)


def validate_photo(data: bytes) -> str | None:
    """Сообщение об ошибке для человека или None, если файл похож на фото."""
    if not data:
        return "Файл пустой. Приложите фото в формате JPEG, PNG, WebP или GIF."
    if len(data) > MAX_BYTES:
        return f"Фото больше {MAX_BYTES // (1024 * 1024)} МБ. Уменьшите снимок или сделайте скриншот."
    if sniff_mime(data) is None:
        return "Это не изображение. Подходят JPEG, PNG, WebP и GIF."
    return None


def _compose_draft(description: PhotoDescription) -> str:
    """Текст для поля черновика: черновик модели, затем что видно — чтобы человек правил по фактам."""
    draft = description.draft.strip()
    if not draft:
        return ""  # пустой draft — знак модели, что рабочей ситуации на фото нет (правило 7 промпта)
    parts: list[str] = [draft]
    seen = description.seen.strip()
    if seen and seen not in draft:
        parts.append(f"На фото: {seen}")
    problem = description.problem.strip()
    if problem and problem not in draft:
        parts.append(f"Что похоже на проблему: {problem}")
    text = "\n\n".join(parts).strip()
    if len(text) > MAX_DRAFT_CHARS:
        text = text[: MAX_DRAFT_CHARS - 1].rstrip() + "…"
    return text


def describe_photo(data: bytes, industry: str = "") -> PhotoResult:
    """Разобрать фото моделью. Никогда не бросает: любая беда — PhotoResult с ok=False."""
    error = validate_photo(data)
    if error:
        return _invalid(error)
    if not llm_available():
        return _unavailable(
            "Анализ фото работает только с ключом OpenAI (OPENAI_API_KEY в .env). "
            "Опишите задачу словами — дальше всё работает и без ключа."
        )
    if settings.LLM_PROVIDER != "openai":
        return _unavailable(
            "Анализ фото доступен только с провайдером OpenAI (LLM_PROVIDER=openai): "
            "резервная модель не видит изображений. Опишите задачу словами."
        )

    mime = sniff_mime(data)
    encoded = base64.b64encode(data).decode("ascii")
    industry_note = (
        f"Отрасль, которую выбрал пользователь: {industry}." if industry else "Отрасль пользователь не указал."
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"{industry_note} Опиши, что на фото, по правилам."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ],
        },
    ]
    try:
        description = get_client().complete(messages, json_schema=PhotoDescription, temperature=0.1)
    except (LLMConfigError, LLMResponseError) as exc:
        logger.warning("Фото: модель недоступна: %s", exc)
        return _unavailable("Модель не ответила по фото. Попробуйте ещё раз или опишите задачу словами.")
    except Exception as exc:  # noqa: BLE001 — граница слоя, как в app/ai.py: наружу ничего не уходит
        logger.exception("Фото: непредвиденная ошибка модели")
        return _unavailable(f"Не удалось разобрать фото ({type(exc).__name__}). Опишите задачу словами.")
    if not isinstance(description, PhotoDescription):
        return _unavailable("Модель вернула ответ не по формату. Опишите задачу словами.")

    draft = _compose_draft(description)
    if not draft:
        return PhotoResult(
            ok=False,
            mode="openai",
            message="На фото не видно рабочей ситуации, черновик по нему не собрать. " + description.seen.strip(),
            description=description,
        )
    return PhotoResult(
        ok=True,
        mode="openai",
        message="Описание с фото вставлено в черновик. Проверьте и поправьте: модель описала только то, что видно.",
        description=description,
        draft=draft,
    )
