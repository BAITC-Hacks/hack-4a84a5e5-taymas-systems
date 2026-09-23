"""Тесты сравнения откликов (HAC-59).

Правила: факты детерминированы; без ключа — только факты; модель не ранжирует (строки с выбором
отбрасываются); чужие числа и выдуманные id отбрасываются; compare_proposals никогда не бросает.
"""

import pytest
from fastapi.testclient import TestClient

from app import compare as compare_module
from app.compare import CompareLLMResponse, ProposalReview, compare_proposals, proposal_facts
from app.llm import LLMResponseError
from app.models import Card, Proposal, Team, new_id

TEAM = Team(id="t1", name="DataBee", interests=["ритейл"], skills=["анализ данных"], technologies=["Python", "FastAPI", "PostgreSQL"])
CARD = Card(
    id="c1", title="Очереди на кассах", need="Сократить очередь в час пик",
    expected_result="Прототип прогноза нагрузки", success_criteria="Очередь не больше 5 минут", constraints="Срок 6 недель",
)


def _proposal(**overrides) -> Proposal:
    base = dict(
        id="p1", card_id="c1", team_id="t1", idea="Прогноз нагрузки на кассы по чекам",
        plan="1. Собрать чеки за месяц. 2. Обучить модель на Python. 3. Показать дашборд на FastAPI.",
        deadline="4 недели", link="https://example.com/proto",
    )
    base.update(overrides)
    return Proposal(**base)


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.messages = response, error, None

    def complete(self, messages, *, json_schema=None, temperature=0.2):
        self.messages = messages
        if self.error:
            raise self.error
        assert json_schema is CompareLLMResponse
        return self.response


def _with_key(monkeypatch, client):
    monkeypatch.setattr(compare_module, "llm_available", lambda: True)
    monkeypatch.setattr(compare_module.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(compare_module, "get_client", lambda: client)


def _no_key(monkeypatch):
    monkeypatch.setattr(compare_module, "llm_available", lambda: False)


def test_facts_are_deterministic():
    f = proposal_facts(_proposal(), TEAM)
    assert f.team_name == "DataBee" and f.has_link and f.has_deadline and f.deadline == "4 недели"
    assert f.plan_steps == 3
    assert f.technologies == ["Python", "FastAPI"]
    g = proposal_facts(_proposal(id="p2", link="  ", deadline="", plan="Сделаем всё"), None)
    assert g.team_name == "t1" and not g.has_link and not g.has_deadline
    assert g.plan_steps == 1 and g.technologies == []


def test_without_key_only_facts(monkeypatch):
    _no_key(monkeypatch)
    comparison = compare_proposals(CARD, [(_proposal(), TEAM)])
    assert comparison.mode == "stub" and comparison.reviews == {}
    assert len(comparison.facts) == 1 and comparison.fallback_reason == ""


def test_reviews_are_filtered_no_ranking_no_foreign_numbers(monkeypatch):
    response = CompareLLMResponse(reviews=[
        ProposalReview(
            proposal_id="p1",
            strengths=["План опирается на чеки за месяц", "Это лучший отклик из всех", "Обещают 99 % точности"],
            questions=["Какие данные о чеках уже есть?", "Кто будет проверять прогноз в час пик?"],
            risks=["Срок 4 недели короче ограничения в 6 недель — не сказано, что войдёт"],
        ),
        ProposalReview(proposal_id="ghost", strengths=["выдумано"], questions=["?"]),
    ])
    client = _FakeClient(response)
    _with_key(monkeypatch, client)
    comparison = compare_proposals(CARD, [(_proposal(), TEAM)])
    assert comparison.mode == "openai"
    review = comparison.reviews["p1"]
    assert review.strengths == ["План опирается на чеки за месяц"]  # «лучший» и «99 %» отброшены
    assert len(review.questions) == 2
    assert review.risks and "4 недели" in review.risks[0]
    assert "ghost" not in comparison.reviews
    system, user = client.messages
    assert "не рекомендуй" in system["content"].lower()
    assert "proposal_id: p1" in user["content"] and "Очереди на кассах" in user["content"]


def test_model_failure_never_raises(monkeypatch):
    _with_key(monkeypatch, _FakeClient(error=LLMResponseError("boom")))
    comparison = compare_proposals(CARD, [(_proposal(), TEAM)])
    assert comparison.mode == "stub" and "недоступна" in comparison.fallback_reason
    assert len(comparison.facts) == 1

    _with_key(monkeypatch, _FakeClient(error=RuntimeError("transport")))
    comparison = compare_proposals(CARD, [(_proposal(), TEAM)])
    assert comparison.mode == "stub" and "RuntimeError" in comparison.fallback_reason


def test_no_proposals_means_no_model_call(monkeypatch):
    client = _FakeClient(CompareLLMResponse(reviews=[]))
    _with_key(monkeypatch, client)
    comparison = compare_proposals(CARD, [])
    assert comparison.facts == [] and comparison.reviews == {}
    assert client.messages is None


@pytest.fixture
def client(tmp_path):
    from app import store as store_module
    from app.main import app

    store_module.reset_store(tmp_path / "store.json", "data/seed.json")
    return TestClient(app)


def test_compare_page_from_seed_without_key(client, monkeypatch):
    _no_key(monkeypatch)
    from app.store import get_store

    store = get_store()
    card = next(c for c in store.list_cards() if store.list_proposals(c.id))
    page = client.get(f"/tasks/{card.id}/compare")
    assert page.status_code == 200
    assert "Сравнение" in page.text and "не ранжирует" in page.text and "только факты" in page.text
    for proposal in store.list_proposals(card.id):
        team = store.get_team(proposal.team_id)
        assert (team.name if team else proposal.team_id) in page.text
    task_page = client.get(f"/tasks/{card.id}")
    assert f"/tasks/{card.id}/compare" in task_page.text


def test_compare_page_404_and_empty(client, monkeypatch):
    _no_key(monkeypatch)
    from app.store import get_store

    assert client.get("/tasks/no-such-card/compare").status_code == 404
    card = get_store().add_card(Card(id=new_id("c"), title="Без откликов", status="published"))
    page = client.get(f"/tasks/{card.id}/compare")
    assert page.status_code == 200 and "сравнивать нечего" in page.text
