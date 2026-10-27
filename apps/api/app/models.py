import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

DEPTHS = ("glance", "explain", "mechanism", "expert")
TAKEAWAY_KINDS = ("takeaway", "idea", "question")


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


def user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id"), nullable=False)


def created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False, server_default="me")
    created_at: Mapped[datetime] = created_at()


# --- Layer 1: exploration ---------------------------------------------------


class Thread(Base):
    __tablename__ = "thread"
    __table_args__ = (CheckConstraint(f"depth in {DEPTHS}", name="thread_depth_check"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    title: Mapped[str | None] = mapped_column(Text)
    root_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="SET NULL")
    )
    current_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="SET NULL")
    )
    depth: Mapped[str] = mapped_column(Text, nullable=False, server_default="explain")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at()
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="thread", order_by="Message.seq", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (
        UniqueConstraint("thread_id", "seq"),
        CheckConstraint("role in ('user', 'assistant')", name="message_role_check"),
        Index("ix_message_concept_id", "concept_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thread.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(Text)  # user turns: ask|dive|branch|switch|spark
    content: Mapped[str] = mapped_column(Text, nullable=False)  # what the UI shows: user text, or card JSON
    card: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Exact content blocks sent to / returned by the API, replayed verbatim as history.
    # Kept separate from `content` because replayed turns (incl. thinking blocks) must never change.
    api_content: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="SET NULL")
    )
    model: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()

    thread: Mapped[Thread] = relationship(back_populates="messages")


# --- Layer 2: concepts & links ----------------------------------------------


class Concept(Base):
    __tablename__ = "concept"
    __table_args__ = (UniqueConstraint("user_id", "slug"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    # False when the concept only exists as a link target and has no card yet.
    explored: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = created_at()


class ConceptLink(Base):
    """Undirected link between two concepts; each pair is stored once with a < b."""

    __tablename__ = "concept_link"
    __table_args__ = (
        UniqueConstraint("a_concept_id", "b_concept_id"),
        CheckConstraint("a_concept_id < b_concept_id", name="concept_link_order_check"),
        Index("ix_concept_link_b_concept_id", "b_concept_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    a_concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    b_concept_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="user")
    created_at: Mapped[datetime] = created_at()

    a: Mapped[Concept] = relationship(foreign_keys=[a_concept_id], lazy="joined")
    b: Mapped[Concept] = relationship(foreign_keys=[b_concept_id], lazy="joined")


# --- Layer 3: insights ------------------------------------------------------

takeaway_concept = Table(
    "takeaway_concept",
    Base.metadata,
    Column("takeaway_id", UUID(as_uuid=True), ForeignKey("takeaway.id", ondelete="CASCADE"), primary_key=True),
    Column("concept_id", UUID(as_uuid=True), ForeignKey("concept.id", ondelete="CASCADE"), primary_key=True),
)


class Takeaway(Base):
    __tablename__ = "takeaway"
    __table_args__ = (CheckConstraint(f"kind in {TAKEAWAY_KINDS}", name="takeaway_kind_check"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thread.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    concepts: Mapped[list[Concept]] = relationship(secondary=takeaway_concept, lazy="selectin")


# --- Usage & cost -----------------------------------------------------------

API_PURPOSES = ("turn", "title", "spark", "translate", "eval", "judge")
BUDGETED_PURPOSES = ("turn", "title", "spark", "translate")  # evals have their own --max-cost guard


class ApiCall(Base):
    """One row per Anthropic API request, with what it cost. The source for budgets and the spend line."""

    __tablename__ = "api_call"
    __table_args__ = (
        CheckConstraint(f"purpose in {API_PURPOSES}", name="api_call_purpose_check"),
        Index("ix_api_call_user_ts", "user_id", "ts"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = user_fk()
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thread.id", ondelete="SET NULL")
    )
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # raw usage block, for audits
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# --- Signals ----------------------------------------------------------------


class InterestEvent(Base):
    __tablename__ = "interest_event"
    __table_args__ = (Index("ix_interest_event_user_ts", "user_id", "ts"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = user_fk()
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("thread.id", ondelete="SET NULL")
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("concept.id", ondelete="SET NULL")
    )
    # spark_shown|ask|dive|branch|switch|skip|depth_set|link|takeaway
    action: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
