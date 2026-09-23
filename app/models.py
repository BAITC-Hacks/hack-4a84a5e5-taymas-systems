"""Доменные модели. Контракт между потоками — см. BRIEF.md, раздел «Контракт».

Владелец файла — обвязка (капитан). Правки полей согласовывать, а не вносить молча.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

# Поля карточки задачи — ровно те, что требует кейс (раздел 3, «Карточка задачи»).
CARD_FIELDS: list[str] = [
    "title",
    "context",
    "need",
    "users",
    "data",
    "constraints",
    "expected_result",
    "success_criteria",
    "contact",
    "interaction_format",
]

FIELD_LABELS: dict[str, str] = {
    "title": "Название",
    "context": "Контекст: что происходит сейчас",
    "need": "Потребность: что нужно изменить",
    "users": "Пользователи: для кого решение",
    "data": "Данные и материалы",
    "constraints": "Ограничения: сроки, технологии, доступы",
    "expected_result": "Ожидаемый результат",
    "success_criteria": "Критерии успеха",
    "contact": "Контакт",
    "interaction_format": "Формат взаимодействия и обратной связи",
}

INDUSTRIES: list[str] = [
    "Образование",
    "Финансы",
    "Ритейл",
    "Логистика",
    "Медицина",
    "Госуслуги",
    "Промышленность",
    "Другое",
]

Level = Literal["draft", "workable", "ready", "priority"]

LEVEL_LABELS: dict[str, str] = {
    "draft": "Черновик",
    "workable": "Рабочая",
    "ready": "Готовая",
    "priority": "Приоритетная",
}

CardStatus = Literal["draft", "published"]
ProposalStatus = Literal["pending", "accepted", "rejected"]


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


class Draft(BaseModel):
    """Черновик: то, что бизнес ввёл на первом шаге."""

    id: str
    text: str
    industry: str
    questions: list["Question"] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)


class Question(BaseModel):
    """Уточняющий вопрос. `field` — ключ из CARD_FIELDS, который закрывает ответ."""

    field: str
    question: str
    why: str = ""


class Answer(BaseModel):
    field: str
    question: str
    answer: str


class CardFields(BaseModel):
    """Только содержательные поля карточки. По ним считается рейтинг."""

    title: str = ""
    context: str = ""
    need: str = ""
    users: str = ""
    data: str = ""
    constraints: str = ""
    expected_result: str = ""
    success_criteria: str = ""
    contact: str = ""
    interaction_format: str = ""


class Card(CardFields):
    """Карточка задачи в хранилище. score/level — результат последнего подтверждённого пересчёта."""

    id: str
    draft_id: str | None = None
    industry: str = "Другое"
    status: CardStatus = "draft"
    confirmed: bool = False
    score: int = 0
    level: Level = "draft"
    answers: list[Answer] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=now)
    published_at: datetime | None = None

    @property
    def level_label(self) -> str:
        return LEVEL_LABELS[self.level]


class RatingItem(BaseModel):
    """Одна строка расшифровки: показатель, вес, начислено, что добавить."""

    key: str
    label: str
    weight: int
    awarded: int
    hint: str = ""


class Rating(BaseModel):
    score: int
    level: Level
    level_label: str
    items: list[RatingItem]
    missing: list[str]


class Team(BaseModel):
    id: str
    name: str
    interests: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Proposal(BaseModel):
    id: str
    card_id: str
    team_id: str
    idea: str
    plan: str
    deadline: str = ""
    link: str = ""
    status: ProposalStatus = "pending"
    created_at: datetime = Field(default_factory=now)
    decided_at: datetime | None = None
