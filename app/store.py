"""JSON-хранилище. Одно на процесс, файл — settings.DATA_PATH.

Если файла нет, он создаётся из settings.SEED_PATH (data/seed.json).
Владелец файла — обвязка (капитан). Другие потоки зовут get_store(), внутрь не лезут.
"""

import json
import shutil
import threading
from pathlib import Path

from app.config import settings
from app.models import Card, Draft, Proposal, Team, new_id, now

_EMPTY = {"drafts": [], "cards": [], "teams": [], "proposals": []}


class Store:
    def __init__(self, path: str | Path, seed_path: str | Path | None = None) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if seed_path and Path(seed_path).exists():
                shutil.copyfile(seed_path, self.path)
            else:
                self.path.write_text(json.dumps(_EMPTY, ensure_ascii=False, indent=2), encoding="utf-8")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.drafts: dict[str, Draft] = {d["id"]: Draft.model_validate(d) for d in raw.get("drafts", [])}
        self.cards: dict[str, Card] = {c["id"]: Card.model_validate(c) for c in raw.get("cards", [])}
        self.teams: dict[str, Team] = {t["id"]: Team.model_validate(t) for t in raw.get("teams", [])}
        self.proposals: dict[str, Proposal] = {p["id"]: Proposal.model_validate(p) for p in raw.get("proposals", [])}

    # --- persistence -------------------------------------------------------
    def _save(self) -> None:
        payload = {
            "drafts": [d.model_dump(mode="json") for d in self.drafts.values()],
            "cards": [c.model_dump(mode="json") for c in self.cards.values()],
            "teams": [t.model_dump(mode="json") for t in self.teams.values()],
            "proposals": [p.model_dump(mode="json") for p in self.proposals.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # --- drafts ------------------------------------------------------------
    def add_draft(self, text: str, industry: str) -> Draft:
        with self._lock:
            draft = Draft(id=new_id("d"), text=text, industry=industry)
            self.drafts[draft.id] = draft
            self._save()
            return draft

    def get_draft(self, draft_id: str) -> Draft | None:
        return self.drafts.get(draft_id)

    def update_draft(self, draft: Draft) -> Draft:
        with self._lock:
            self.drafts[draft.id] = draft
            self._save()
            return draft

    # --- cards -------------------------------------------------------------
    def add_card(self, card: Card) -> Card:
        with self._lock:
            if not card.id:
                card.id = new_id("c")
            self.cards[card.id] = card
            self._save()
            return card

    def get_card(self, card_id: str) -> Card | None:
        return self.cards.get(card_id)

    def update_card(self, card: Card) -> Card:
        with self._lock:
            self.cards[card.id] = card
            self._save()
            return card

    def list_cards(
        self,
        *,
        published_only: bool = True,
        industry: str | None = None,
        level: str | None = None,
    ) -> list[Card]:
        """Каталог: по рейтингу по убыванию, при равенстве — свежие выше."""
        items = list(self.cards.values())
        if published_only:
            items = [c for c in items if c.status == "published"]
        if industry:
            items = [c for c in items if c.industry == industry]
        if level:
            items = [c for c in items if c.level == level]
        items.sort(key=lambda c: (-c.score, -(c.published_at or c.created_at).timestamp()))
        return items

    # --- teams -------------------------------------------------------------
    def list_teams(self) -> list[Team]:
        return sorted(self.teams.values(), key=lambda t: t.name)

    def get_team(self, team_id: str) -> Team | None:
        return self.teams.get(team_id)

    # --- proposals ---------------------------------------------------------
    def add_proposal(self, proposal: Proposal) -> Proposal:
        with self._lock:
            if not proposal.id:
                proposal.id = new_id("p")
            self.proposals[proposal.id] = proposal
            self._save()
            return proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self.proposals.get(proposal_id)

    def update_proposal(self, proposal: Proposal) -> Proposal:
        with self._lock:
            proposal.decided_at = now() if proposal.status != "pending" else None
            self.proposals[proposal.id] = proposal
            self._save()
            return proposal

    def list_proposals(self, card_id: str) -> list[Proposal]:
        items = [p for p in self.proposals.values() if p.card_id == card_id]
        items.sort(key=lambda p: p.created_at)
        return items


_store: Store | None = None


def get_store() -> Store:
    """Синглтон хранилища. Путь и сид — из настроек."""
    global _store
    if _store is None:
        _store = Store(settings.DATA_PATH, settings.SEED_PATH)
    return _store


def reset_store(path: str | Path | None = None, seed_path: str | Path | None = None) -> Store:
    """Для тестов: пересоздать хранилище по другому пути."""
    global _store
    _store = Store(path or settings.DATA_PATH, seed_path if seed_path is not None else settings.SEED_PATH)
    return _store
