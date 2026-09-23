"""Тесты испытания задачи виртуальной командой (HAC-56).

Правила: вердикт и блокеры детерминированы, без ключа работает заглушка, ответ модели
с числами не из карточки отбрасывается, run_trial никогда не бросает.
"""

import pytest
from fastapi.testclient import TestClient

from app import ai
from app import trial as trial_module
from app.models import Card, Team, new_id
from app.trial import TrialLLMBlocker, TrialLLMResponse, TrialLLMStep, _numbers_grounded, run_trial, trial_badge

TEAM = Team(id="t_test", name="DataBee", interests=["образование"], skills=["анализ данных"], technologies=["Python", "FastAPI"])


def _weak_card() -> Card:
    return Card(
        id=new_id("c"),
        title="Подбор наставников для первокурсников",
        context="В первый семестр около трети первокурсников не находят наставника, кураторы распределяют вручную по спискам групп.",
        need="Нужен сервис, который предлагает куратору трёх подходящих наставников на каждого первокурсника.",
        users="Кураторы факультетов и первокурсники.",
    )


@pytest.fixture(autouse=True)
def _stub_only(monkeypatch):
    monkeypatch.setattr(trial_module, "llm_available", lambda: False)


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error

    def complete(self, messages, *, json_schema=None, temperature=0.2):
        if self.error:
            raise self.error
        assert json_schema is TrialLLMResponse
        return self.response


def test_weak_card_fails_with_priced_blockers():
    card = _weak_card()
    trial = run_trial(card, TEAM)
    assert trial.passed is False
    assert trial.mode == "stub"
    keys = {b.key for b in trial.blockers}
    assert {"data", "expected_result"} <= keys
    assert all(b.gain > 0 for b in trial.blockers)
    assert trial.blockers[0].gain >= trial.blockers[-1].gain
    assert trial.steps and trial.steps[-1].blocked is True
    assert "Стоп" in trial.steps[-1].text
    assert "первокурсников" in trial.steps[0].text  # цитата из карточки, а не общий шаблон
    top = trial.blockers[0]
    assert top.label in trial.next_step
    assert str(trial.score_at + top.gain) in trial.next_step
    assert "DataBee" in trial.verdict


def test_full_seed_card_passes(tmp_path):
    from app import store as store_module

    store = store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    card = store.get_card("c_seed0001")
    trial = run_trial(card, TEAM)
    assert trial.passed is True
    assert trial.blockers == [] and trial.risks == []
    assert not any(step.blocked for step in trial.steps)
    assert 3 <= len(trial.steps) <= 5
    assert "может начать" in trial.verdict
    assert trial.score_at == 100


def test_stub_is_deterministic():
    card = _weak_card()
    first, second = run_trial(card, TEAM), run_trial(card, TEAM)
    assert first.model_dump(exclude={"created_at"}) == second.model_dump(exclude={"created_at"})


def test_numbers_grounding_rule():
    source = "Выгрузка 900 обращений за год, 1 200 студентов"
    assert _numbers_grounded("Разобрать 900 обращений", source)
    assert _numbers_grounded("Проверить выгрузку по 1200 студентам", source)
    assert _numbers_grounded("День 3: созвон с куратором", "")
    assert not _numbers_grounded("Обработать 5000 обращений", source)


def test_llm_answer_with_invented_numbers_is_rejected(monkeypatch):
    monkeypatch.setattr(trial_module, "llm_available", lambda: True)
    response = TrialLLMResponse(
        steps=[
            TrialLLMStep(text="Разобрать контекст задачи", blocked=False),
            TrialLLMStep(text="Опросить 5000 первокурсников", blocked=False),
            TrialLLMStep(text="Стоп: нет данных", blocked=True),
        ],
        blockers=[],
    )
    monkeypatch.setattr(trial_module, "get_client", lambda: _FakeClient(response))
    trial = run_trial(_weak_card(), TEAM)
    assert trial.mode == "stub"
    assert not any("5000" in step.text for step in trial.steps)
    assert ai.last_fallback_reason and "Испытание" in ai.last_fallback_reason


def test_grounded_llm_answer_is_used_and_unknown_keys_ignored(monkeypatch):
    monkeypatch.setattr(trial_module, "llm_available", lambda: True)
    monkeypatch.setattr(trial_module.settings, "LLM_PROVIDER", "openai")
    response = TrialLLMResponse(
        steps=[
            TrialLLMStep(text="Разобрать, почему «около трети первокурсников не находят наставника»", blocked=False),
            TrialLLMStep(text="Описать сценарий куратора", blocked=False),
            TrialLLMStep(text="Стоп: в карточке нет ни анкет наставников, ни списков групп", blocked=True),
        ],
        blockers=[
            TrialLLMBlocker(key="data", reason="В карточке нет ни выгрузки, ни примеров анкет наставников"),
            TrialLLMBlocker(key="users", reason="эта причина не нужна — пользователи описаны"),
            TrialLLMBlocker(key="whatever", reason="неизвестный ключ"),
        ],
    )
    monkeypatch.setattr(trial_module, "get_client", lambda: _FakeClient(response))
    trial = run_trial(_weak_card(), TEAM)
    assert trial.mode == "openai"
    assert trial.passed is False
    assert [step.text for step in trial.steps][0].startswith("Разобрать, почему")
    data = next(b for b in trial.blockers if b.key == "data")
    assert data.reason == "В карточке нет ни выгрузки, ни примеров анкет наставников"
    assert "whatever" not in {b.key for b in trial.blockers + trial.risks}
    assert ai.last_fallback_reason is None


def test_llm_crash_never_escapes(monkeypatch):
    monkeypatch.setattr(trial_module, "llm_available", lambda: True)
    monkeypatch.setattr(trial_module, "get_client", lambda: _FakeClient(error=RuntimeError("boom")))
    trial = run_trial(_weak_card(), TEAM)
    assert trial.mode == "stub"
    assert trial.passed is False
    assert "непредвиденная" in ai.last_fallback_reason


@pytest.fixture()
def client(tmp_path):
    from app import store as store_module

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    from app.main import app

    return TestClient(app)


def test_trial_routes_and_catalog_badge(client):
    from app.store import get_store

    page = client.get("/business/cards/c_seed0001/trial")
    assert page.status_code == 200
    assert "Испытание задачи" in page.text
    assert "Проверить глазами команды" in page.text

    assert client.get("/business/cards/nope/trial").status_code == 404
    assert client.post("/business/cards/c_seed0001/trial", data={"team_id": "nope"}).status_code == 400

    response = client.post("/business/cards/c_seed0001/trial", data={"team_id": "t_seed0001"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/business/cards/c_seed0001/trial"

    result = client.get("/business/cards/c_seed0001/trial")
    assert "Выдержала" in result.text
    assert "Повторить испытание" in result.text
    card = get_store().get_card("c_seed0001")
    assert card.trial is not None and card.trial.passed and trial_badge(card)

    assert "прошла испытание" in client.get("/catalog").text
    assert "прошла испытание командой" in client.get("/tasks/c_seed0001").text
    assert client.get("/catalog.json").json()["cards"][0]["trial_passed"] is True

    # Правка карточки после испытания: знак снимается, страница испытания говорит, что результат устарел.
    edit = client.post("/business/cards/c_seed0001/edit", data={"data": ""})
    assert edit.status_code == 200
    assert "прошла испытание" not in client.get("/catalog").text
    assert "устарел" in client.get("/business/cards/c_seed0001/trial").text


def test_weak_card_trial_page_shows_blockers(client):
    from app.models import Card
    from app.store import get_store

    card = get_store().add_card(Card(id="c_weak", title="Слабая", context="Жители пишут обращения, их разбирают вручную", need="Нужно распределять обращения по отделам автоматически"))
    response = client.post(f"/business/cards/{card.id}/trial", data={"team_id": "t_seed0001"}, follow_redirects=True)
    assert response.status_code == 200
    assert "Не выдержала" in response.text
    assert "Стоп" in response.text
    assert "+20" in response.text


def test_trial_page_suggests_matching_team(client):
    page = client.get("/business/cards/c_seed0001/trial")
    assert "Подсказка: задаче по профилю подходит <strong>DataBee</strong>" in page.text
    assert 'value="t_seed0001" selected' in page.text
