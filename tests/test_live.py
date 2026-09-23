"""Срез каталога и лента отражают хранилище без мутаций."""
import pytest
from fastapi.testclient import TestClient
from app.store import reset_store

@pytest.fixture
def setup(tmp_path):
    from app.main import app
    store = reset_store(tmp_path / 'store.json', 'data/seed.json')
    return TestClient(app), store

def test_catalog_positions_and_filters(setup):
    client, store = setup
    result = client.get('/catalog.json').json()
    assert [c['id'] for c in result['cards']] == [c.id for c in store.list_cards()]
    assert [c['position'] for c in result['cards']] == list(range(1, result['total'] + 1))
    result = client.get('/catalog.json', params={'industry': 'Образование'}).json()
    assert all(c['industry'] == 'Образование' for c in result['cards'])
    positions = {c.id: i + 1 for i,c in enumerate(store.list_cards())}
    assert all(c['position'] == positions[c['id']] for c in result['cards'])
    assert client.get('/catalog.json?industry=<bad>&level=bad').status_code == 200

def test_feed_sorted_read_only_and_decisions(setup):
    client, store = setup
    proposal = next(iter(store.proposals.values()))
    proposal.status = 'accepted'
    store.update_proposal(proposal)
    before = store.path.read_bytes()
    events = client.get('/feed.json').json()['events']
    assert len(events) == 10
    assert [e['at'] for e in events] == sorted((e['at'] for e in events), reverse=True)
    assert {'published', 'proposal', 'decision'} <= {e['kind'] for e in events}
    assert store.path.read_bytes() == before

def test_feed_empty_and_draft_private(setup):
    client, store = setup
    for card in store.cards.values():
        card.status = 'draft'
    assert client.get('/feed.json').json() == {'events': []}
    store.cards.clear(); store.proposals.clear()
    assert client.get('/feed.json').json() == {'events': []}
    assert client.get('/catalog.json').json()['cards'] == []
