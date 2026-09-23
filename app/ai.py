"""AI-функции: уточняющие вопросы и сборка карточки. ЗАГЛУШКА фазы 1 — заменяется в тикете ядра.

Контракт (BRIEF.md):
  generate_questions(draft_text, industry) -> list[Question]   # len >= 3
  build_card(draft_text, industry, answers) -> CardFields
  ai_mode() -> "openai" | "nvidia" | "stub"

Правила кейса (раздел 5): ИИ не добавляет фактов, которых не сообщил пользователь;
результат редактируется и подтверждается человеком; без внешнего API работает локальная заглушка.
"""

from app.models import FIELD_LABELS, Answer, CardFields, Question

_STUB_QUESTIONS: list[Question] = [
    Question(field="context", question="Что происходит сейчас и что именно не устраивает?", why="Контекст и потребность — 20 баллов"),
    Question(field="data", question="Какие данные, примеры или источники вы можете передать команде?", why="Данные и материалы — 20 баллов"),
    Question(field="expected_result", question="Что конкретно должно получиться в конце работы команды?", why="Ожидаемый результат — 15 баллов"),
    Question(field="success_criteria", question="По каким измеримым признакам вы поймёте, что решение принято?", why="Критерии успеха — 15 баллов"),
]


def ai_mode() -> str:
    return "stub"


def generate_questions(draft_text: str, industry: str) -> list[Question]:
    """Заглушка: фиксированный набор вопросов по самым весомым показателям."""
    return list(_STUB_QUESTIONS)


def build_card(draft_text: str, industry: str, answers: list[Answer]) -> CardFields:
    """Заглушка: черновик идёт в контекст, ответы раскладываются по своим полям как есть."""
    fields: dict[str, str] = {"context": draft_text.strip(), "title": draft_text.strip().split("\n")[0][:80]}
    for a in answers:
        if a.field in FIELD_LABELS and a.answer.strip():
            fields[a.field] = a.answer.strip()
    return CardFields(**fields)
