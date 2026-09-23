"""Помощники: факты из каталога, безопасный fallback, предпросмотр без записи."""
import pytest
from fastapi.testclient import TestClient
from app import assistants, llm
from app.models import Card
from app.store import reset_store

@pytest.fixture
def setup(tmp_path, monkeypatch):
    from app.main import app
    store = reset_store(tmp_path / 'store.json', 'data/seed.json')
    monkeypatch.setattr(llm, 'llm_available', lambda: False)
    return TestClient(app), store


def test_search_grounded_and_read_only(setup):
    client, store = setup
    before = store.path.read_bytes()
    result = client.post('/assistants/student.json', json={'message':'Образование чат-бот'}).json()
    assert result['mode'] == 'stub'
    assert result['cards']
    for item in result['cards']:
        card = store.get_card(item['id'])
        assert card.status == 'published' and card.score >= 40
        assert any(item['evidence'] in getattr(card, field) for field in assistants.PUBLIC_FIELDS)
    assert store.path.read_bytes() == before


def test_no_recommendation_for_low_score_or_draft(setup):
    client, store = setup
    for card in store.cards.values():
        card.score = 39
    result = client.post('/assistants/student.json', json={'message':'образование'}).json()
    assert result['cards'] == []
    for card in store.cards.values():
        card.score = 100; card.status = 'draft'
    assert client.post('/assistants/student.json', json={'message':'образование'}).json()['cards'] == []


def test_unknown_search_has_no_fake_matches(setup):
    client, _ = setup
    result = client.post('/assistants/student.json', json={'message':'астрономическая спектроскопия'}).json()
    assert result['cards'] == []


def test_real_model_path_validates_evidence(setup, monkeypatch):
    client, store = setup
    card = store.list_cards()[0]
    answer = assistants.SearchAnswer(selections=[assistants.Selection(card_id=card.id, field='title', evidence=card.title)])
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    class Fake:
        def complete(self, messages, **kwargs):
            assert kwargs['json_schema'] is assistants.SearchAnswer
            assert 'contact' not in messages[1]['content']
            return answer
    monkeypatch.setattr(llm, 'get_client', Fake)
    result = client.post('/assistants/student.json', json={'message':'подбери задачу'}).json()
    assert result['mode'] != 'stub'
    assert result['cards'][0]['id'] == card.id
    answer.selections[0].evidence = 'Выдуманная цитата 100500'
    result = client.post('/assistants/student.json', json={'message':'образование'}).json()
    assert result['mode'] == 'stub'
    assert all(c['evidence'] != 'Выдуманная цитата 100500' for c in result['cards'])
    answer.selections[0].card_id = 'not-a-card'
    assert client.post('/assistants/student.json', json={'message':'образование'}).json()['mode'] == 'stub'


def test_model_failure_is_private_fallback(setup, monkeypatch):
    client, _ = setup
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    def fail():
        raise RuntimeError('secret-provider-details')
    monkeypatch.setattr(llm, 'get_client', fail)
    response = client.post('/assistants/student.json', json={'message':'образование'})
    assert response.status_code == 200
    assert response.json()['mode'] == 'stub'
    assert 'secret-provider-details' not in response.text


@pytest.mark.parametrize('body', [
    {'message':' '}, {'message':'x'*1201}, {'message':'abc', 'history':['x']*6},
    {'message':'abc', 'history':['x'*1201]}, {'message':'abc','team_id':'unknown'},
])
def test_invalid_search(setup, body):
    client, _ = setup
    assert 400 <= client.post('/assistants/student.json', json=body).status_code < 500


def test_coach_missions_exact_rating_and_preview_never_write(setup):
    client, store = setup
    card = store.add_card(Card(id='c_coach', title='Слабая карточка'))
    before = store.path.read_bytes()
    result = client.post('/business/cards/c_coach/coach.json', json={'message':'как улучшить?'}).json()
    assert result['rating']['score'] == 0
    assert sum(m['gain'] for m in result['missions']) == 100
    assert result['next_at'] == 40
    assert result['mode'] == 'stub'
    from tests.test_e2e import FULL_FIELDS
    preview = client.post('/business/cards/c_coach/preview.json', json={'fields':FULL_FIELDS}).json()
    assert (preview['before'], preview['after'], preview['delta']) == (0,100,100)
    assert preview['position']['position'] == 1
    assert store.get_card(card.id).score == 0
    assert store.get_card(card.id).status == 'draft'
    assert store.path.read_bytes() == before


def test_coach_rejects_invented_numeric_question(setup, monkeypatch):
    client, store = setup
    card = store.add_card(Card(id='weak'))
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    class Fake:
        def complete(self, *a, **k):
            return assistants.CoachAnswer(focus_keys=['data'], question='Есть ли у вас 10000 записей?')
    monkeypatch.setattr(llm, 'get_client', Fake)
    result = client.post(f'/business/cards/{card.id}/coach.json', json={}).json()
    assert result['mode'] == 'stub'
    assert '10000' not in result['question']


@pytest.mark.parametrize('fields', [{'score':'100'}, {'data':'x'*2001}, {'confirmed':'true'}])
def test_preview_rejects_system_fields(setup, fields):
    client, store = setup
    cid = store.list_cards()[0].id
    assert client.post(f'/business/cards/{cid}/preview.json', json={'fields':fields}).status_code == 400


def test_plan_compare_and_not_found(setup):
    client, store = setup
    card = store.list_cards()[0]
    plan = client.get(f'/assistants/tasks/{card.id}/plan.json').json()
    assert len(plan['steps']) == 4
    assert plan['steps'][1]['evidence'] == card.data
    before = store.path.read_bytes()
    ids = [c.id for c in store.list_cards()[:3]]
    result = client.get('/assistants/compare.json', params=[('ids', cid) for cid in ids]).json()
    assert [c['id'] for c in result['cards']] == ids
    assert client.get('/assistants/compare.json', params=[('ids', c.id) for c in store.list_cards()[:4]]).status_code == 400
    assert client.get('/assistants/tasks/nope/plan.json').status_code == 404
    assert client.get('/business/cards/nope/coach').status_code == 404
    store.add_card(Card(id='hidden'))
    assert client.get('/assistants/tasks/hidden/plan.json').status_code == 404
    assert client.get('/assistants/compare.json?ids=hidden').status_code == 404


def test_no_js_forms_and_escaping(setup):
    client, store = setup
    card = store.add_card(Card(id='html', title='<script>alert(1)</script>'))
    page = client.get('/business/cards/html/coach')
    assert page.status_code == 200
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in page.text
    response = client.post('/assistants/student', data={'message':'образование', 'history':'[]'})
    assert response.status_code == 200 and 'Локальный помощник' in response.text
    response = client.post('/business/cards/html/coach/preview', data={'field':'data','value':'CSV с учебными данными и описанием формата'})
    assert response.status_code == 200 and 'Предпросмотр' in response.text
    response = client.post('/assistants/student', data={'message':'hello', 'history':'broken'})
    assert response.status_code == 200 and 'Введите запрос' in response.text


def test_position_same_score_uses_original_publication_date(setup):
    from datetime import datetime, timezone
    client, store = setup
    old = datetime(2026, 9, 20, tzinfo=timezone.utc)
    newer = datetime(2026, 9, 21, tzinfo=timezone.utc)
    store.cards.clear()
    store.add_card(Card(id='old', score=20, status='published', published_at=old))
    store.add_card(Card(id='new', score=70, status='published', published_at=newer))
    result = client.get('/business/cards/old/position.json?score=70').json()
    assert result['position'] == 2
    assert result['current_position'] == 2
    # Полностью равные ключи — исходный порядок вставки, а не прежняя позиция.
    store.cards['new'].published_at = old
    result = client.get('/business/cards/old/position.json?score=70').json()
    assert result['position'] == 1
    assert result['current_position'] == 2
    assert client.get('/business/cards/old/position.json?score=101').status_code == 400


def test_coach_accepts_valid_structured_ai_question(setup, monkeypatch):
    client, store = setup
    store.add_card(Card(id='coach-ai'))
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    class Fake:
        def complete(self, *args, **kwargs):
            return assistants.CoachAnswer(focus_keys=['data'], question='В каком формате доступны данные для команды?')
    monkeypatch.setattr(llm, 'get_client', Fake)
    result = client.post('/business/cards/coach-ai/coach.json', json={'message':'помоги с данными'}).json()
    assert result['mode'] != 'stub'
    assert result['missions'][0]['key'] == 'data'
    assert result['question'] == 'В каком формате доступны данные для команды?'


def test_injection_in_catalog_is_only_text(setup):
    client, store = setup
    card = store.list_cards()[0]
    card.title = 'Образование <img src=x onerror=alert(1)>'
    response = client.post('/assistants/student', data={'message':'Образование', 'history':'[]'})
    assert '<img src=x onerror=alert(1)>' not in response.text
    assert '&lt;img' in response.text


def test_duplicate_valid_citations_are_one_recommendation(setup, monkeypatch):
    client, store = setup
    card = store.list_cards()[0]
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    class Fake:
        def complete(self, *a, **k):
            return assistants.SearchAnswer(selections=[
                assistants.Selection(card_id=card.id, field='title', evidence=card.title),
                assistants.Selection(card_id=card.id, field='industry', evidence=card.industry)])
    monkeypatch.setattr(llm, 'get_client', Fake)
    result = client.post('/assistants/student.json', json={'message':'образование'}).json()
    assert result['mode'] != 'stub' and len(result['cards']) == 1


def test_proposal_review_never_sends_or_decides(setup, monkeypatch):
    client, store = setup
    card = store.list_cards()[0]
    before = store.path.read_bytes()
    body = {'idea':'Предлагаем прототип интерфейса для пользователей задачи.', 'plan':'Уточнить задачу, проверить данные, собрать прототип и провести демо.'}
    result = client.post(f'/assistants/tasks/{card.id}/review.json', json=body).json()
    assert result['mode'] == 'stub'
    assert len(result['questions']) == 3
    assert store.path.read_bytes() == before
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    class Fake:
        def complete(self, *a, **k):
            return assistants.ProposalAdvice(questions=['Как вы проверите результат на доступных данных?'])
    monkeypatch.setattr(llm, 'get_client', Fake)
    assert client.post(f'/assistants/tasks/{card.id}/review.json', json=body).json()['mode'] != 'stub'
    assert client.post(f'/assistants/tasks/{card.id}/review.json', json={'idea':'  ','plan':'x'}).status_code == 400
    assert store.path.read_bytes() == before


def test_local_search_ignores_common_words_and_inside_word_matches(setup):
    client, store = setup
    # Изолированный регрессионный набор: новые тематические задачи не должны
    # менять проверку, что «про» не совпадает с «прогноз» и «прототип».
    store.cards = {key: card for key, card in store.cards.items() if key.startswith('c_seed')}
    result = client.post('/assistants/student.json', json={'message':'Хочу задачу про образование и чат-ботов'}).json()
    assert [c['id'] for c in result['cards']] == ['c_seed0001']
