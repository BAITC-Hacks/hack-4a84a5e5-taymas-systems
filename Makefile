.PHONY: run check build verify reset dev test gate

# Поднять проект
run:
	docker compose up --build

# Проверить основной сценарий
check:
	docker compose run --rm app python -m pytest -q

# Честная проверка воспроизводимости: сборка без кеша.
# Локальный кеш врёт — у эксперта его нет.
build:
	docker compose build --no-cache

# Полная проверка перед закрытием репозитория:
# собрать с нуля и прогнать основной сценарий.
verify: build check

# Сбросить состояние к исходным данным (data/seed.json)
reset:
	rm -f data/store.json

# Запуск без Docker (запасной путь), нужен .venv с requirements.txt
dev:
	python -m app

# Тесты без Docker
test:
	python -m pytest -q

# Приёмка демо-пути: сквозной сценарий кейса от черновика до принятого отклика.
# Зелёный gate = обязательная демонстрация из раздела 11 кейса работает целиком.
gate:
	python -m pytest -q tests/test_e2e.py
