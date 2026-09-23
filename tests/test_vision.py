"""HAC-58: контекст + фото → предложение, отдельное от фактов и записи."""
import pytest
from fastapi.testclient import TestClient
from app import vision
from app.vision import PhotoDescription, describe_photo, sniff_mime, validate_photo

PNG = b'\x89PNG\r\n\x1a\n' + b'\x00'*64
JPEG = b'\xff\xd8\xff\xe0' + b'\x00'*64
CONTEXT = 'На стройке теряем материалы. Хотим упростить их учёт и поиск.'
DESCRIPTION = PhotoDescription(
    seen='Материалы лежат в разных местах площадки.',
    problem='Пользователь сообщает о потерях материалов.',
    intent='Упростить учёт и поиск материалов.',
    proposal='Предлагаю рассмотреть прототип учёта расположения материалов.',
    unclear='Неизвестны объём номенклатуры и текущий способ учёта.',
    questions=['Как сейчас учитываются материалы?', 'Кто будет пользоваться решением?'],
    draft='На стройке теряем материалы и хотим упростить их поиск. Предлагаем команде согласовать прототип учёта расположения материалов. Состав данных и критерии проверки нужно уточнить.'
)

class FakeClient:
    def __init__(self, response=DESCRIPTION, error=None):
        self.response, self.error, self.messages = response, error, None
    def complete(self, messages, **kwargs):
        self.messages = messages
        assert kwargs['json_schema'] is PhotoDescription
        if self.error:
            raise self.error
        return self.response

def with_key(monkeypatch, fake=None):
    fake = fake or FakeClient()
    monkeypatch.setattr(vision.settings, 'LLM_PROVIDER', 'openai')
    monkeypatch.setattr(vision, 'llm_available', lambda: True)
    monkeypatch.setattr(vision, 'get_client', lambda: fake)
    return fake

@pytest.fixture
def setup(tmp_path):
    from app.main import app
    from app.store import reset_store
    return TestClient(app), reset_store(tmp_path/'store.json', 'data/seed.json')

def test_sniff_and_validation():
    assert sniff_mime(PNG) == 'image/png'
    assert sniff_mime(JPEG) == 'image/jpeg'
    assert sniff_mime(b'GIF89a'+b'0'*8) == 'image/gif'
    assert sniff_mime(b'RIFF0000WEBP0000') == 'image/webp'
    assert sniff_mime(b'<html>photo.png</html>') is None
    assert validate_photo(b'') and validate_photo(b'not a photo')
    assert validate_photo(PNG) is None

@pytest.mark.parametrize('context', ['', 'abc', 'x'*4001])
def test_context_required_before_model(monkeypatch, context):
    fake = with_key(monkeypatch)
    result = describe_photo(PNG, 'Промышленность', context)
    assert result.mode == 'invalid' and not result.ok
    assert fake.messages is None

def test_file_limit_before_model(monkeypatch):
    fake = with_key(monkeypatch)
    monkeypatch.setattr(vision, 'MAX_BYTES', 20)
    assert describe_photo(PNG, context=CONTEXT).mode == 'invalid'
    assert fake.messages is None

def test_text_and_photo_both_reach_model(monkeypatch):
    fake = with_key(monkeypatch)
    result = describe_photo(PNG, 'Промышленность', CONTEXT)
    assert result.ok and result.draft == DESCRIPTION.draft
    assert result.context == CONTEXT
    # Наблюдение не дублируется длинной описью в тексте задачи.
    assert DESCRIPTION.seen not in result.draft
    assert result.description.proposal == DESCRIPTION.proposal
    text, image = fake.messages[1]['content']
    assert CONTEXT in text['text'] and 'Промышленность' in text['text']
    assert image['image_url']['url'].startswith('data:image/png;base64,')
    assert 'гипотеза' in fake.messages[0]['content']

def test_no_key_and_text_provider_honest(monkeypatch):
    fake = with_key(monkeypatch)
    monkeypatch.setattr(vision, 'llm_available', lambda: False)
    result = describe_photo(PNG, context=CONTEXT)
    assert result.mode == 'unavailable' and 'ключ' in result.message
    monkeypatch.setattr(vision.settings, 'LLM_PROVIDER', 'nvidia')
    assert describe_photo(PNG, context=CONTEXT).mode == 'unavailable'
    assert fake.messages is None

def test_provider_check_failure_does_not_raise(monkeypatch):
    with_key(monkeypatch)
    def fail():
        raise RuntimeError('private details')
    monkeypatch.setattr(vision, 'llm_available', fail)
    result = describe_photo(PNG, context=CONTEXT)
    assert not result.ok and 'private details' not in result.message

def test_model_failure_or_invalid_response(monkeypatch):
    with_key(monkeypatch, FakeClient(error=RuntimeError('private details')))
    result = describe_photo(JPEG, context=CONTEXT)
    assert not result.ok and result.mode == 'unavailable'
    assert 'private details' not in result.message
    with_key(monkeypatch, FakeClient(response='wrong schema'))
    assert describe_photo(PNG, context=CONTEXT).mode == 'unavailable'

def test_insufficient_context_shows_questions_without_draft(monkeypatch):
    with_key(monkeypatch, FakeClient(PhotoDescription(seen='Фото не относится к запросу.', draft='', questions=['Какую проблему вы хотите решить?'])))
    result = describe_photo(PNG, context='Хочу что-нибудь полезное.')
    assert not result.ok and result.description.questions and not result.draft

def test_irrelevant_photo_can_still_help_clear_text_goal(monkeypatch):
    response = DESCRIPTION.model_copy(update={'seen':'Фото не относится к описанной рабочей ситуации.'})
    with_key(monkeypatch, FakeClient(response))
    assert describe_photo(PNG, context=CONTEXT).ok

def test_draft_length_cap(monkeypatch):
    with_key(monkeypatch, FakeClient(PhotoDescription(seen='Материалы', draft='я'*3000)))
    assert len(describe_photo(PNG, context=CONTEXT).draft) == vision.MAX_DRAFT_CHARS

def test_route_context_json_and_no_persistence(setup, monkeypatch):
    client, store = setup
    fake = with_key(monkeypatch)
    before = store.path.read_bytes()
    response = client.post('/business/photo', files={'photo':('site.png',PNG,'image/png')}, data={'context':CONTEXT,'industry':'<script>'})
    assert response.status_code == 200
    assert response.json()['draft'] == DESCRIPTION.draft
    assert response.json()['context'] == CONTEXT
    assert '<script>' not in fake.messages[1]['content'][0]['text']
    assert store.path.read_bytes() == before

def test_route_rejects_invalid_requests(setup, monkeypatch):
    client, _ = setup
    fake = with_key(monkeypatch)
    for files, data in [(None, {'context':CONTEXT}), ({'photo':('x.png',b'garbage','image/png')}, {'context':CONTEXT}), ({'photo':('x.png',PNG,'image/png')}, {})]:
        response = client.post('/business/photo', files=files, data=data)
        assert response.status_code == 422 and not response.json()['ok']
    assert fake.messages is None

def test_route_without_key(setup, monkeypatch):
    client, _ = setup
    with_key(monkeypatch)
    monkeypatch.setattr(vision, 'llm_available', lambda: False)
    response = client.post('/business/photo', files={'photo':('x.png',PNG,'image/png')}, data={'context':CONTEXT})
    assert response.status_code == 503 and response.json()['mode'] == 'unavailable'

def test_new_page_has_explicit_review_step(setup):
    client, _ = setup
    response = client.get('/business/new')
    assert response.status_code == 200
    assert 'Использовать этот черновик' in response.text
    assert 'Собрать задачу из текста и фото' in response.text
    assert 'photo-processing' in response.text
    assert client.get('/static/photo.js').status_code == 200
