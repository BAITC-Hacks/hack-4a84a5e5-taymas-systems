.PHONY: run check build verify

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
