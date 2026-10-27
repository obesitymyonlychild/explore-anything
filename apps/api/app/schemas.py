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


DiagramKind = Literal["none", "flow", "cycle", "timeline", "compare", "bars", "causes"]


class DiagramItem(BaseModel):
    """One element of a diagram; which fields matter depends on the kind (see services/diagrams.py)."""

    label: str
    detail: str
    detail_b: str  # compare: the second column; otherwise ""
    value: float  # bars: the quantity; otherwise 0
    value_text: str  # bars: the quantity as shown ("2,700 L"); otherwise ""


class Diagram(BaseModel):
    """A small visual drawn by the page. kind="none" when no visual adds anything."""

    kind: DiagramKind
    title: str
    columns: list[str]  # compare: the two column headings; otherwise []
    items: list[DiagramItem]


class Picture(BaseModel):
    """A Wikipedia article whose lead image shows the concept; the server resolves it to an image."""

    wikipedia_title: str
    caption: str


class Card(BaseModel):
    """One assistant turn. Field order matches llm/card_schema.py (= streaming order)."""

    concept: str = Field(min_length=1)
    kind: Literal["intro", "deeper", "answer"]
    depth: Depth
    one_liner: str
    example: str
    diagram: Diagram
    highlights: list[str]
    bridge: str
    body_md: str
    pictures: list[Picture]
    branches: list[Branch]


class TurnRequest(BaseModel):
    action: TurnAction
    text: str | None = None
    concept: str | None = None  # branch / spark: the concept to move to
    depth: Depth | None = None  # explicit depth for this and later turns
    takeaway_id: uuid.UUID | None = None  # ask: a question-type takeaway to send
    topic_area: str | None = None  # spark: the area it was picked from (logged, so areas rotate)
    angle: str | None = None  # spark: the kind of question (how-it-works, day-in-the-life, …)


class UsageOut(BaseModel):
    today_usd: float
    month_usd: float
    daily_budget_usd: float  # 0 = no limit
    monthly_budget_usd: float
    warn: bool  # at 80% of a budget
    blocked: bool
    reason: str | None
    month_by_purpose: dict[str, float]  # includes eval/judge, which don't count toward budgets


class SparkOut(BaseModel):
    concept: str
    question: str  # sent back as the spark turn's text
    teaser: str
    topic_area: str
    angle: str
