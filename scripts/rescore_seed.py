"""Пересчитать score/level карточек в data/seed.json по текущей формуле рейтинга.

Запуск из корня: python scripts/rescore_seed.py
Нужен после изменений в app/rating.py, чтобы сид соответствовал формуле из README.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import Card  # noqa: E402
from app.rating import compute_rating  # noqa: E402

SEED = Path("data/seed.json")


def main() -> None:
    raw = json.loads(SEED.read_text(encoding="utf-8"))
    for item in raw["cards"]:
        card = Card.model_validate(item)
        rating = compute_rating(card)
        item["score"], item["level"] = rating.score, rating.level
        print(f"{card.id}  {rating.score:3d}  {rating.level:9s}  {card.title}")
    SEED.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
