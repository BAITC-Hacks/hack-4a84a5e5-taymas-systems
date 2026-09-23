"""Сравнение откликов (HAC-59): бизнес сравнивает предложения команд и сам выбирает — шаг 7 кейса.

Две части. Факты по каждому отклику считаются детерминированно и показываются всегда: срок указан,
есть ли ссылка на прототип, сколько шагов в плане, объём, какие технологии из профиля команды
названы в отклике. Разбор моделью — только по тексту отклика и карточки: сильные стороны, вопросы
команде, риски. Модель не ранжирует, не рекомендует и не выбирает — раздел 5 ТЗ: «ИИ не выбирает
команду за бизнес». Строки с чужими числами или с формулировками выбора отбрасываются.

Ничего не сохраняется: страница строится на каждый запрос. compare_proposals() никогда не бросает.
"""

import logging
import re

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import LLMConfigError, LLMResponseError, get_client, llm_available
from app.models import Card, Proposal, Team
from app.trial import _numbers_grounded

logger = logging.getLogger(__name__)

MAX_LINE_CHARS = 160
# Формулировки выбора: такие строки модели отбрасываются, решение принимает бизнес.
_RANKING_RE = re.compile(
    r"лучш|сильнее (других|остальных)|рекоменд|стоит выбрать|выбрать команду|победител|предпочт|"
    r"оптимальн(ый|ая) (выбор|вариант)|самый (сильный|слабый)",
    re.IGNORECASE,
)
_STEP_SPLIT_RE = re.compile(r"\n+|(?<=[.;!?])\s+|\s(?=\d+[.)]\s)")


class ProposalFacts(BaseModel):
    proposal_id: str
    team_name: str
    status: str
    has_deadline: bool
    deadline: str = ""
    has_link: bool
    plan_steps: int
    idea_words: int
    plan_words: int
    technologies: list[str] = Field(default_factory=list)  # из профиля команды, названы в отклике


class ProposalReview(BaseModel):
    """Разбор одного отклика моделью. Только по тексту, без выбора."""

    proposal_id: str = Field(description="Скопировать из входа без изменений")
    strengths: list[str] = Field(description="1–3 сильные стороны, видные в тексте отклика")
    questions: list[str] = Field(description="2–3 конкретных вопроса команде, которые помогут бизнесу решить")
    risks: list[str] = Field(default_factory=list, description="0–2 риска, видных в тексте: нет срока, нет данных, план без проверки")


class CompareLLMResponse(BaseModel):
    reviews: list[ProposalReview]


class Comparison(BaseModel):
    card_id: str
    mode: str  # "openai" | "nvidia" — разбор моделью · "stub" — только факты
    facts: list[ProposalFacts]
    reviews: dict[str, ProposalReview] = Field(default_factory=dict)  # по proposal_id
    fallback_reason: str = ""


SYSTEM_PROMPT = """Ты помогаешь представителю бизнеса сравнить отклики студенческих команд на его задачу.

Правила:
1. Пиши только по тексту отклика и карточки задачи. Не додумывай опыт команды и качество прототипа по ссылке.
2. Не ранжируй, не называй лучший отклик, не рекомендуй, кого выбрать: решение принимает бизнес сам.
3. По каждому отклику: strengths — 1–3 сильные стороны, видные в тексте; questions — 2–3 конкретных вопроса команде, ответы на которые помогут бизнесу решить; risks — 0–2 риска, видных в тексте (нет срока, нет данных, план без проверки результата).
4. Числа — только из отклика или карточки. Ничего не выдумывай.
5. Коротко, по-русски, каждая строка до 140 символов. proposal_id копируй из входа без изменений."""


def _words(text: str) -> int:
    return len(text.split())


def _plan_steps(plan: str) -> int:
    parts = [p.strip() for p in _STEP_SPLIT_RE.split(plan) if p and p.strip()]
    return len([p for p in parts if not re.fullmatch(r"\d+[.)]?", p)])  # «1.» — нумерация, не шаг


def proposal_facts(proposal: Proposal, team: Team | None) -> ProposalFacts:
    text = f"{proposal.idea}\n{proposal.plan}".lower()
    technologies = [t for t in (team.technologies if team else []) if t.lower() in text]
    return ProposalFacts(
        proposal_id=proposal.id,
        team_name=team.name if team else proposal.team_id,
        status=proposal.status,
        has_deadline=bool(proposal.deadline.strip()),
        deadline=proposal.deadline.strip(),
        has_link=bool(proposal.link.strip()),
        plan_steps=_plan_steps(proposal.plan),
        idea_words=_words(proposal.idea),
        plan_words=_words(proposal.plan),
        technologies=technologies,
    )


def _card_summary(card: Card) -> str:
    fields = [
        ("Название", card.title), ("Потребность", card.need), ("Ожидаемый результат", card.expected_result),
        ("Критерии успеха", card.success_criteria), ("Ограничения", card.constraints), ("Данные", card.data),
    ]
    return "\n".join(f"{label}: {value.strip()}" for label, value in fields if value.strip())


def _proposal_block(proposal: Proposal, team: Team | None) -> str:
    return (
        f"proposal_id: {proposal.id}\nКоманда: {team.name if team else proposal.team_id}\n"
        f"Идея: {proposal.idea.strip()}\nПлан: {proposal.plan.strip()}\n"
        f"Срок: {proposal.deadline.strip() or 'не указан'}\nСсылка на прототип: {'есть' if proposal.link.strip() else 'нет'}"
    )


def _clean_lines(lines: list[str], source: str, limit: int) -> list[str]:
    """Оставить строки без формулировок выбора и без чужих чисел, обрезать по длине и числу."""
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or _RANKING_RE.search(line) or not _numbers_grounded(line, source):
            continue
        if len(line) > MAX_LINE_CHARS:
            line = line[: MAX_LINE_CHARS - 1].rstrip() + "…"
        out.append(line)
        if len(out) == limit:
            break
    return out


def _llm_reviews(card: Card, pairs: list[tuple[Proposal, Team | None]]) -> dict[str, ProposalReview]:
    user = "Карточка задачи:\n" + _card_summary(card) + "\n\nОтклики:\n\n" + "\n\n".join(
        _proposal_block(p, t) for p, t in pairs
    )
    response = get_client().complete(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        json_schema=CompareLLMResponse,
        temperature=0.2,
    )
    if not isinstance(response, CompareLLMResponse):
        raise LLMResponseError("ответ не по схеме CompareLLMResponse")
    by_id = {p.id: (p, t) for p, t in pairs}
    reviews: dict[str, ProposalReview] = {}
    for review in response.reviews:
        if review.proposal_id not in by_id or review.proposal_id in reviews:
            continue  # выдуманный или повторный id — отбрасываем
        proposal, _ = by_id[review.proposal_id]
        source = f"{_card_summary(card)}\n{proposal.idea}\n{proposal.plan}\n{proposal.deadline}"
        cleaned = ProposalReview(
            proposal_id=review.proposal_id,
            strengths=_clean_lines(review.strengths, source, 3),
            questions=_clean_lines(review.questions, source, 3),
            risks=_clean_lines(review.risks, source, 2),
        )
        if cleaned.strengths or cleaned.questions or cleaned.risks:
            reviews[review.proposal_id] = cleaned
    return reviews


def compare_proposals(card: Card, pairs: list[tuple[Proposal, Team | None]]) -> Comparison:
    """Факты всегда; разбор моделью — если есть ключ и модель ответила по правилам. Никогда не бросает."""
    facts = [proposal_facts(p, t) for p, t in pairs]
    result = Comparison(card_id=card.id, mode="stub", facts=facts)
    if not pairs or not llm_available():
        return result
    try:
        result.reviews = _llm_reviews(card, pairs)
        result.mode = settings.LLM_PROVIDER
    except (LLMConfigError, LLMResponseError) as exc:
        logger.warning("Сравнение откликов: модель недоступна: %s", exc)
        result.fallback_reason = f"модель недоступна ({exc})"
    except Exception as exc:  # noqa: BLE001 — граница слоя, как в app/ai.py: наружу ничего не уходит
        logger.exception("Сравнение откликов: непредвиденная ошибка модели")
        result.fallback_reason = f"непредвиденная ошибка модели ({type(exc).__name__})"
    return result
