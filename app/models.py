from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    chat_id: str
    sender_id: str
    text: str
    sent_at: datetime
    is_from_rally: bool = False


@dataclass
class PlanFacts:
    goal: str = ""
    activity: str = ""
    participants: list[str] = field(default_factory=list)
    party_size: int | None = None
    date: str | None = None
    time: str | None = None
    earliest_time: str | None = None
    location: str | None = None
    excluded_cuisines: list[str] = field(default_factory=list)
    preferred_cuisines: list[str] = field(default_factory=list)
    objections: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    confidence: float = 0.0
    abandoned: bool = False


@dataclass
class Plan:
    id: str
    chat_id: str
    version: int
    facts: PlanFacts
    state: str
    last_human_at: datetime
    last_intervention_version: int | None = None
    pending_proposal_id: str | None = None


@dataclass(frozen=True)
class Proposal:
    id: str
    plan_id: str
    version: int
    venue_id: str
    venue_name: str
    venue_address: str
    date: str
    time: str
    party_size: int
    status: str = "pending"
    created_at: str = ""


@dataclass(frozen=True)
class Reservation:
    proposal_id: str
    confirmation_id: str
    status: str
