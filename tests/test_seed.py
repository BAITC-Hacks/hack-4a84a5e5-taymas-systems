"""Согласованность исходных данных (HAC-37).

Сид — то, что эксперт увидит первым в каталоге. Если формула рейтинга изменится,
а баллы в data/seed.json нет, страница задачи покажет расшифровку, которая
не сходится с баллом в каталоге. Этот файл ловит расхождение до жюри.
Требования к сиду — раздел 6 ТЗ.
"""

import json
from pathlib import Path

import pytest

from app.models import Card, Draft, Proposal, Team
from app.rating import compute_rating, level_for

SEED = json.loads(Path("data/seed.json").read_text(encoding="utf-8"))


def _cards() -> list[Card]:
    return [Card.model_validate(c) for c in SEED["cards"]]


@pytest.mark.parametrize("card", _cards(), ids=lambda c: c.id)
def test_seed_card_score_matches_formula(card: Card):
    rating = compute_rating(card)
    assert card.score == rating.score, f"{card.id}: в сиде {card.score}, формула даёт {rating.score}"
    assert card.level == level_for(card.score)
    assert card.level == rating.level


@pytest.mark.parametrize("card", _cards(), ids=lambda c: c.id)
def test_seed_published_card_is_confirmed(card: Card):
    if card.status == "published":
        assert card.confirmed, f"{card.id} опубликована без подтверждения"
        assert card.published_at is not None


def test_seed_volumes_match_case_section_6():
    """Раздел 6 ТЗ: по 5 черновиков, карточек, команд и откликов."""
    for key in ("drafts", "cards", "teams", "proposals"):
        assert len(SEED[key]) >= 5, f"{key}: {len(SEED[key])} < 5"


def test_seed_drafts_vary_in_completeness():
    """Раздел 6 ТЗ: черновики — «сведения разной степени полноты»."""
    lengths = [len(Draft.model_validate(d).text) for d in SEED["drafts"]]
    assert min(lengths) < 100, "нет слабого черновика"
    assert max(lengths) > 300, "нет подробного черновика"


def test_seed_proposals_reference_existing_cards_and_teams():
    card_ids = {c["id"] for c in SEED["cards"]}
    team_ids = {t["id"] for t in SEED["teams"]}
    for raw in SEED["proposals"]:
        p = Proposal.model_validate(raw)
        assert p.card_id in card_ids, f"{p.id} → нет карточки {p.card_id}"
        assert p.team_id in team_ids, f"{p.id} → нет команды {p.team_id}"
        assert p.idea and p.plan


def test_seed_teams_have_profile_fields():
    """Раздел 6 ТЗ: «Название, интересы, навыки и технологии»."""
    for raw in SEED["teams"]:
        t = Team.model_validate(raw)
        assert t.name and t.interests and t.skills and t.technologies, f"{t.id} неполный профиль"


def test_seed_levels_cover_the_scale():
    """Каталог должен показывать все четыре уровня, иначе фильтр по уровню нечем проверить."""
    levels = {c.level for c in _cards()}
    assert levels == {"draft", "workable", "ready", "priority"}, levels
