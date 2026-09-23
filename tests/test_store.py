"""Хранилище: сид, сортировка каталога, фильтры, отклики, персистентность."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import Card, Proposal
from app.store import Store

SEED = "data/seed.json"


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "store.json", SEED)


def test_seed_volume(store):
    assert (len(store.drafts), len(store.cards), len(store.teams), len(store.proposals)) == (5, 5, 9, 5)


def test_catalog_sorted_by_score_then_recency(store):
    now = datetime.now(timezone.utc)
    store.add_card(Card(id="c_old", title="Старая", status="published", score=60, level="workable",
                        published_at=now - timedelta(days=1)))
    store.add_card(Card(id="c_new", title="Новая", status="published", score=60, level="workable",
                        published_at=now))
    cards = store.list_cards()
    scores = [c.score for c in cards]
    assert scores == sorted(scores, reverse=True)
    ids = [c.id for c in cards]
    assert ids.index("c_new") < ids.index("c_old")


def test_filters_combine(store):
    only = store.list_cards(industry="Образование", level="priority")
    assert [c.id for c in only] == ["c_seed0001"]
    assert store.list_cards(industry="Образование", level="draft") == []


def test_unpublished_hidden_from_catalog_but_listable(store):
    store.add_card(Card(id="c_draft", title="Черновик", status="draft", score=10, level="draft"))
    assert "c_draft" not in [c.id for c in store.list_cards()]
    assert "c_draft" in [c.id for c in store.list_cards(published_only=False)]


def test_proposal_decision_sets_decided_at(store):
    p = store.add_proposal(Proposal(id="", card_id="c_seed0003", team_id="t_seed0001", idea="Идея", plan="План"))
    assert p.id.startswith("p_") and p.status == "pending" and p.decided_at is None
    p.status = "accepted"
    store.update_proposal(p)
    saved = store.get_proposal(p.id)
    assert saved.status == "accepted" and saved.decided_at is not None
    assert [x.id for x in store.list_proposals("c_seed0003")][-1] == p.id


def test_persistence_across_instances(tmp_path):
    path = tmp_path / "store.json"
    first = Store(path, SEED)
    draft = first.add_draft("Хотим бота", "Образование")
    second = Store(path, SEED)
    assert second.get_draft(draft.id).text == "Хотим бота"
    assert len(second.cards) == 5
