"""Испытание задачи виртуальной командой (HAC-56).

Идея: до публикации карточку «пробует взять» студенческая команда из сида. Она составляет
план первой недели, опираясь только на карточку, и останавливается там, где сведений нет.
Это не оценка и не баллы: рейтинг начисляется только за подтверждённые поля (ТЗ, раздел 4).
Испытание отвечает на другой вопрос — «можно ли по этой карточке начать работу в понедельник».

Что детерминировано, а что пишет модель:
  * вердикт и состав блокеров — правило, без ИИ: старт блокируют недоборы по показателям
    «Контекст и потребность», «Данные и материалы», «Ожидаемый результат», «Пользователи»;
    недоборы по остальным («Критерии успеха», «Ограничения», «Связь с бизнесом») — риски;
  * текст плана и формулировки причин — LLM через app/llm.py; без ключа — заглушка
    с цитатами из карточки. Числа, которых нет в карточке, считаются выдумкой: такой ответ
    модели целиком заменяется заглушкой (ТЗ, раздел 5: ИИ не добавляет фактов).

Контракт (BRIEF.md): run_trial(card: Card, team: Team) -> Trial — никогда не бросает.
"""

import logging
import re

from pydantic import BaseModel

from app import ai
from app.config import settings
from app.llm import LLMConfigError, LLMResponseError, get_client, llm_available
from app.models import CARD_FIELDS, FIELD_LABELS, LEVEL_LABELS, Card, Team, Trial, TrialBlocker, TrialStep
from app.rating import SCALE, compute_rating, level_for

logger = logging.getLogger(__name__)

# Без этих показателей команде не с чего начать первую неделю. Недоборы по остальным — риски.
BLOCKING_KEYS: tuple[str, ...] = ("context_need", "data", "expected_result", "users")

_FIELDS_BY_KEY: dict[str, list[str]] = {key: fields for key, _label, _weight, fields in SCALE}

_BLOCK_REASONS: dict[str, str] = {
    "context_need": "Непонятно, что происходит сейчас и что должно измениться: у команды нет точки отсчёта.",
    "data": "Нет данных, примеров или источников: команде не с чем начать разбор в первую неделю.",
    "expected_result": "Не описан результат работы: команда не поймёт, что именно сдавать.",
    "users": "Не сказано, для кого решение: нельзя описать сценарий пользователя.",
}
_RISK_REASONS: dict[str, str] = {
    "success_criteria": "Нет измеримых критериев: команда не поймёт, когда задача решена, а бизнес — принимать ли результат.",
    "constraints": "Не указаны сроки, технологии и доступы: команда может выбрать стек или срок, которые бизнесу не подойдут.",
    "business_link": "Нет контакта или формата связи: вопросы команды останутся без ответа.",
}

_MIN_STEPS, _MAX_STEPS = 3, 5
_QUOTE_WORDS = 8
_ORDINAL_MAX = 7  # «день 1», «шаг 3»: номера дней и шагов — не факты о бизнесе
_NUMBER_RE = re.compile(r"\d+")
_SPACED_DIGITS_RE = re.compile(r"(?<=\d)[\s ](?=\d)")

# --- промпт и формат ответа модели (уходят в README дословно) -------------------------

TRIAL_SYSTEM = (
    "Ты — студенческая команда, которая получила карточку бизнес-задачи и пробует взять её в работу.\n"
    "Правила:\n"
    "- Опирайся ТОЛЬКО на карточку. Не добавляй фактов, чисел, названий, сроков и контактов, которых в ней нет.\n"
    "- Составь план первой недели из 3–5 коротких шагов, по одному предложению. Где уместно, цитируй карточку в «кавычках».\n"
    "- Если в списке есть блокеры, последний шаг плана — «Стоп: …» с blocked=true: дальше планировать нельзя. "
    "Если блокеров нет, у всех шагов blocked=false.\n"
    "- Для каждого блокера и риска из списка напиши одной фразой, почему без этих сведений нельзя начать "
    "или что пойдёт не так, ссылаясь на то, чего именно нет в карточке. Ключи (key) бери из списка, новых не добавляй.\n"
    "- Не оценивай бизнес и не предлагай готовых значений для пустых полей.\n"
    "- Пиши только на русском языке."
)


class TrialLLMStep(BaseModel):
    text: str
    blocked: bool


class TrialLLMBlocker(BaseModel):
    key: str
    reason: str


class TrialLLMResponse(BaseModel):
    """Формат выхода модели: план первой недели и формулировки причин по блокерам и рискам."""

    steps: list[TrialLLMStep]
    blockers: list[TrialLLMBlocker]


def build_trial_user_prompt(card: Card, team: Team, blockers: list[TrialBlocker], risks: list[TrialBlocker]) -> str:
    """Формат входа: профиль команды, карточка целиком, блокеры и риски с тем, чего не хватает."""
    profile = (
        f"Команда {team.name}. Интересы: {', '.join(team.interests) or '—'}. "
        f"Навыки: {', '.join(team.skills) or '—'}. Технологии: {', '.join(team.technologies) or '—'}."
    )
    card_lines = "\n".join(
        f"- {FIELD_LABELS[field]}: {getattr(card, field, '').strip() or '— не заполнено'}" for field in CARD_FIELDS
    )

    def fmt(items: list[TrialBlocker]) -> str:
        return "\n".join(f"- key={item.key} — {item.label}: {item.reason}" for item in items) or "- нет"

    return (
        f"{profile}\n\n"
        f"Карточка задачи (отрасль: {card.industry}):\n{card_lines}\n\n"
        f"Блокеры — сведения, без которых начать нельзя:\n{fmt(blockers)}\n\n"
        f"Риски — начать можно, но работа может уйти не туда:\n{fmt(risks)}"
    )


# --- детерминированная часть ---------------------------------------------------------


def _plural(n: int, one: str, few: str, many: str) -> str:
    if 11 <= n % 100 <= 14:
        return many
    if n % 10 == 1:
        return one
    if 2 <= n % 10 <= 4:
        return few
    return many


def _quote(text: str, words: int = _QUOTE_WORDS) -> str:
    parts = " ".join((text or "").split()).split(" ")
    quote = " ".join(p for p in parts[:words] if p)
    return quote + ("…" if len(parts) > words else "")


def _deficits(rating) -> tuple[list[TrialBlocker], list[TrialBlocker]]:
    """Показатели с недобором: блокеры (BLOCKING_KEYS) и риски, по убыванию цены закрытия."""
    blockers: list[TrialBlocker] = []
    risks: list[TrialBlocker] = []
    for item in rating.items:
        if item.awarded >= item.weight:
            continue
        is_blocker = item.key in BLOCKING_KEYS
        reason = (_BLOCK_REASONS if is_blocker else _RISK_REASONS)[item.key]
        if item.awarded:
            reason = f"Описано частично. {reason}"
        if item.hint:
            reason = f"{reason} Что добавить: {item.hint.rstrip('.')}."
        entry = TrialBlocker(key=item.key, label=item.label, reason=reason, gain=item.weight - item.awarded)
        (blockers if is_blocker else risks).append(entry)
    blockers.sort(key=lambda b: -b.gain)
    risks.sort(key=lambda b: -b.gain)
    return blockers, risks


def _stub_steps(card: Card, team: Team, blocked_keys: set[str]) -> list[TrialStep]:
    """План первой недели без модели: цитаты из карточки, «Стоп» на первом блокере."""
    steps: list[TrialStep] = []
    if "context_need" in blocked_keys:
        steps.append(TrialStep(text="Стоп: непонятно, что происходит сейчас и что нужно изменить — план первой недели построить не на чем.", blocked=True))
        return steps
    steps.append(TrialStep(text=f"Разобрать контекст задачи: «{_quote(card.context or card.need)}»."))
    if "users" in blocked_keys:
        steps.append(TrialStep(text="Стоп: не указано, для кого решение — нельзя описать сценарий пользователя.", blocked=True))
        return steps
    steps.append(TrialStep(text=f"Описать сценарий пользователя: «{_quote(card.users)}»."))
    if "data" in blocked_keys:
        steps.append(TrialStep(text="Стоп: в карточке нет данных, примеров или источников — начать разбор не с чего.", blocked=True))
        return steps
    steps.append(TrialStep(text=f"Получить и разобрать данные: «{_quote(card.data)}»."))
    if "expected_result" in blocked_keys:
        steps.append(TrialStep(text="Стоп: не описан результат работы — непонятно, что сдавать.", blocked=True))
        return steps
    steps.append(TrialStep(text=f"Согласовать с бизнесом ожидаемый результат: «{_quote(card.expected_result)}»."))
    stack = ", ".join(team.technologies[:2]) or "своём стеке"
    contact = f" ({_quote(card.contact, 5)})" if card.contact.strip() else ""
    steps.append(TrialStep(text=f"Собрать первый прототип на {stack} и показать бизнесу{contact}."))
    return steps


def _verdict(team: Team, passed: bool, blockers: list[TrialBlocker], risks: list[TrialBlocker]) -> str:
    if passed:
        text = f"{team.name} может начать работу в первую неделю: блокеров в карточке нет."
        if risks:
            text += f" Есть {len(risks)} {_plural(len(risks), 'риск', 'риска', 'рисков')} — лучше закрыть до старта."
        return text
    n = len(blockers)
    return (
        f"{team.name} не сможет начать в первую неделю: {n} {_plural(n, 'блокер', 'блокера', 'блокеров')} в карточке. "
        f"Спланировать можно только то, что уже описано."
    )


def _next_step(rating, blockers: list[TrialBlocker], risks: list[TrialBlocker]) -> str:
    target = blockers or risks
    if not target:
        return "Все сведения на месте. Подтвердите карточку и публикуйте — команда может начать сразу."
    top = target[0]
    new_score = rating.score + top.gain
    new_level = level_for(new_score)
    text = f"Заполните «{top.label}» (+{top.gain}) — балл станет {new_score}"
    if new_level != rating.level:
        text += f", уровень «{LEVEL_LABELS[new_level]}»"
        if rating.score < 40 <= new_score:
            text += ", и задачу можно будет рекомендовать командам"
    rest = len(blockers) - 1 if blockers else 0
    if rest > 0:
        text += f". Затем ещё {rest} {_plural(rest, 'блокер', 'блокера', 'блокеров')} и повторное испытание."
    else:
        text += ". Затем повторите испытание."
    return text


# --- защита от выдуманных фактов и обращение к модели ---------------------------------


def _source_text(card: Card, team: Team) -> str:
    parts = [getattr(card, field, "") for field in CARD_FIELDS] + [card.industry, team.name]
    parts += team.interests + team.skills + team.technologies
    return "\n".join(parts)


def _numbers_grounded(text: str, source: str) -> bool:
    """Все числа в тексте должны быть в источнике; номера дней и шагов (1–7) фактами не считаются."""
    source_numbers = set(_NUMBER_RE.findall(source)) | set(_NUMBER_RE.findall(_SPACED_DIGITS_RE.sub("", source)))
    for number in _NUMBER_RE.findall(_SPACED_DIGITS_RE.sub("", text)):
        if number in source_numbers or 1 <= int(number) <= _ORDINAL_MAX:
            continue
        return False
    return True


def _llm_enrich(
    card: Card, team: Team, blockers: list[TrialBlocker], risks: list[TrialBlocker]
) -> tuple[list[TrialStep], list[TrialBlocker], list[TrialBlocker]] | None:
    """План и причины от модели. None — ответ не прошёл проверку, берём заглушку целиком."""
    response: TrialLLMResponse = get_client().complete(
        [
            {"role": "system", "content": TRIAL_SYSTEM},
            {"role": "user", "content": build_trial_user_prompt(card, team, blockers, risks)},
        ],
        json_schema=TrialLLMResponse,
    )
    source = _source_text(card, team)
    steps = [TrialStep(text=s.text.strip(), blocked=s.blocked) for s in response.steps if s.text.strip()]
    if not _MIN_STEPS <= len(steps) <= _MAX_STEPS:
        return None
    if any(not _numbers_grounded(step.text, source) for step in steps):
        return None
    if blockers and not any(step.blocked for step in steps):
        steps[-1].blocked = True
    if not blockers:
        for step in steps:
            step.blocked = False
    reasons = {b.key: b.reason.strip() for b in response.blockers if b.reason.strip()}

    def enrich(items: list[TrialBlocker]) -> list[TrialBlocker]:
        out = []
        for item in items:
            reason = reasons.get(item.key)
            if reason and _numbers_grounded(reason, source):
                out.append(item.model_copy(update={"reason": reason}))
            else:
                out.append(item)
        return out

    return steps, enrich(blockers), enrich(risks)


# --- публичная граница ---------------------------------------------------------------


def run_trial(card: Card, team: Team) -> Trial:
    """Испытание карточки командой. Никогда не бросает: любой сбой модели = заглушка."""
    rating = compute_rating(card)
    blockers, risks = _deficits(rating)
    passed = not blockers
    steps = _stub_steps(card, team, {b.key for b in blockers})
    mode = "stub"
    if llm_available():
        try:
            enriched = _llm_enrich(card, team, blockers, risks)
        except (LLMConfigError, LLMResponseError) as exc:
            logger.warning("LLM недоступен для испытания, включена заглушка: %s", exc)
            ai.last_fallback_reason = f"Испытание: LLM недоступен, использована заглушка ({exc})"
        except Exception as exc:  # noqa: BLE001 — граница слоя, как в app/ai.py: наружу ничего не уходит
            logger.exception("Непредвиденная ошибка LLM при испытании, включена заглушка")
            ai.last_fallback_reason = f"Испытание: непредвиденная ошибка LLM, использована заглушка ({type(exc).__name__})"
        else:
            if enriched is None:
                logger.warning("Ответ LLM для испытания не прошёл проверку, включена заглушка")
                ai.last_fallback_reason = "Испытание: ответ LLM не прошёл проверку (формат или числа не из карточки), использована заглушка"
            else:
                steps, blockers, risks = enriched
                mode = settings.LLM_PROVIDER
                ai.last_fallback_reason = None
    else:
        ai.last_fallback_reason = None
    return Trial(
        team_id=team.id,
        team_name=team.name,
        passed=passed,
        verdict=_verdict(team, passed, blockers, risks),
        steps=steps,
        blockers=blockers,
        risks=risks,
        next_step=_next_step(rating, blockers, risks),
        score_at=rating.score,
        mode=mode,
    )


def trial_is_current(card: Card) -> bool:
    """Испытание актуально, пока предварительный балл карточки не изменился после него."""
    return card.trial is not None and card.trial.score_at == compute_rating(card).score


def trial_badge(card: Card) -> bool:
    """Знак «прошла испытание» для каталога: подтверждённая версия карточки выдержала испытание."""
    return card.trial is not None and card.trial.passed and card.confirmed and card.trial.score_at == card.score
