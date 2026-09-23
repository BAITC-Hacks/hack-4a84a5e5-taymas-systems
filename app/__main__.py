"""Точка входа: `python -m app` поднимает веб-сервер."""

import uvicorn

from app.config import settings


def main() -> None:
    uvicorn.run("app.main:app", host=settings.APP_HOST, port=settings.APP_PORT, log_level=settings.LOG_LEVEL.lower())


if __name__ == "__main__":
    main()
