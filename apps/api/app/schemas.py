import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Depth = Literal["glance", "explain", "mechanism", "expert"]
TakeawayKind = Literal["takeaway", "idea", "question"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Threads & messages -----------------------------------------------------


class ThreadCreate(BaseModel):
    title: str | None = None


class ThreadUpdate(BaseModel):
    title: str | None = None
    depth: Depth | None = None
    archived: bool | None = None


class ThreadOut(ORM):
    id: uuid.UUID
    title: str | None
    root_concept_id: uuid.UUID | None
    current_concept_id: uuid.UUID | None
    depth: Depth
    archived: bool
    created_at: datetime
    last_active_at: datetime


class MessageOut(ORM):
    id: uuid.UUID
    thread_id: uuid.UUID
    seq: int
    role: Literal["user", "assistant"]
    action: str | None
    content: str
    card: dict[str, Any] | None
    concept_id: uuid.UUID | None
    created_at: datetime


class ThreadDetail(ThreadOut):
    messages: list[MessageOut]


# --- Concepts & links -------------------------------------------------------


class ConceptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ConceptOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    explored: bool
    created_at: datetime


class ConceptRef(ORM):
    id: uuid.UUID
    name: str


class LinkCreate(BaseModel):
    a_concept_id: uuid.UUID
    b_concept_id: uuid.UUID
    note: str = ""


class LinkUpdate(BaseModel):
    note: str


class LinkOut(BaseModel):
    id: uuid.UUID
    a: ConceptRef
    b: ConceptRef
    note: str
    created_by: str
    created_at: datetime


class LinkedConcept(BaseModel):
    """A link seen from one concept's side: the concept on the other end."""

    link_id: uuid.UUID
    concept: ConceptRef
    note: str
    created_by: str
    created_at: datetime


# --- Takeaways --------------------------------------------------------------


class TakeawayCreate(BaseModel):
    body: str = Field(min_length=1)
    kind: TakeawayKind = "takeaway"
    concept_ids: list[uuid.UUID] = Field(min_length=1)
    message_id: uuid.UUID | None = None


class TakeawayUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1)
    kind: TakeawayKind | None = None
    concept_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)


class TakeawayOut(ORM):
    id: uuid.UUID
    kind: TakeawayKind
    body: str
    thread_id: uuid.UUID | None
    message_id: uuid.UUID | None
    concepts: list[ConceptRef]
    created_at: datetime
    updated_at: datetime


class ConceptDetail(BaseModel):
    concept: ConceptOut
    cards: list[MessageOut]  # assistant messages whose card is about this concept
    links: list[LinkedConcept]
    takeaways: list[TakeawayOut]


# --- Hook cards & turns -----------------------------------------------------

TurnAction = Literal["ask", "dive", "branch", "switch", "spark"]


class Branch(BaseModel):
    kind: Literal["deeper", "related", "switch"]
    label: str
    concept: str


class Card(BaseModel):
    """One assistant turn. Field order matches llm/card_schema.py (= streaming order)."""

    concept: str = Field(min_length=1)
    kind: Literal["intro", "deeper", "answer"]
    depth: Depth
    one_liner: str
    example: str
    highlights: list[str]
    bridge: str
    body_md: str
    branches: list[Branch]


class TurnRequest(BaseModel):
    action: TurnAction
    text: str | None = None
    concept: str | None = None  # branch / spark: the concept to move to
    depth: Depth | None = None  # explicit depth for this and later turns
    takeaway_id: uuid.UUID | None = None  # ask: a question-type takeaway to send
