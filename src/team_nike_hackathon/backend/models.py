"""SQLModel tables and Pydantic API models for MatchCare.

The two ``table=True`` models (``Facility`` and ``FacilitySubmission``) are
auto-created on app startup by ``SQLModel.metadata.create_all`` in
``core/lakebase.py``. They must be imported before that call runs; ``app.py``
takes care of that by importing this module via ``router.py``.

The partner's ingest pipeline owns the contents of ``facilities``. The schema
declared here is a **target shape** — if their loader uses a different shape,
``create_all`` is a no-op for existing tables and the partner's columns win.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from .. import __version__


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Misc API models
# ---------------------------------------------------------------------------


class VersionOut(BaseModel):
    version: str

    @classmethod
    def from_metadata(cls) -> "VersionOut":
        return cls(version=__version__)


# ---------------------------------------------------------------------------
# Lakebase tables
# ---------------------------------------------------------------------------


class Facility(SQLModel, table=True):
    """A healthcare facility surfaced to the UI.

    Free-text fields (``raw_description``) are kept alongside extracted
    structured fields so the UI can show *evidence* for every claim. Per-field
    confidence scores live in ``confidence`` (JSONB), keyed by field name.
    """

    __tablename__ = "facilities"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    external_id: str | None = Field(default=None, index=True)

    name: str
    type: str | None = Field(default=None, index=True)

    address: str | None = None
    city: str | None = Field(default=None, index=True)
    state: str | None = Field(default=None, index=True)
    pincode: str | None = None
    country: str = Field(default="IN")

    latitude: float | None = Field(default=None, index=True)
    longitude: float | None = Field(default=None, index=True)

    specialties: list[str] | None = Field(default=None, sa_column=Column(JSONB))
    services: list[str] | None = Field(default=None, sa_column=Column(JSONB))
    equipment: list[str] | None = Field(default=None, sa_column=Column(JSONB))
    procedures: list[str] | None = Field(default=None, sa_column=Column(JSONB))

    raw_description: str | None = None
    confidence: dict[str, float] | None = Field(
        default=None, sa_column=Column(JSONB)
    )

    source: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class SubmissionStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    merged = "merged"


class SubmissionType(str, Enum):
    provider_self_attest = "provider_self_attest"
    fieldwork_surveyor = "fieldwork_surveyor"


class FacilitySubmission(SQLModel, table=True):
    """A provider self-attestation or a fieldwork surveyor record.

    Both entry paths write here; reviewers promote rows into ``facilities``
    out-of-band in SQL. ``payload`` holds the full proposed Facility fields
    so reviewers have everything in one column.
    """

    __tablename__ = "facility_submissions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    status: SubmissionStatus = Field(
        default=SubmissionStatus.pending, index=True
    )
    submission_type: SubmissionType = Field(index=True)

    submitted_by: str | None = Field(default=None, index=True)
    submitted_at: datetime = Field(default_factory=_utcnow)

    payload: dict[str, Any] = Field(sa_column=Column(JSONB))

    captured_lat: float | None = None
    captured_lng: float | None = None
    captured_at: datetime | None = None
    photo_url: str | None = None

    notes: str | None = None
    review_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    merged_facility_id: UUID | None = Field(
        default=None, foreign_key="facilities.id"
    )


# ---------------------------------------------------------------------------
# Search / evidence API models
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """One supporting snippet for a claim about a facility."""

    field: str
    snippet: str
    confidence: float


class FacilityOut(BaseModel):
    """Wire-shape for one facility.

    ``id`` is a string because we surface rows from both Lakebase Postgres
    (UUIDs) and Unity Catalog Delta tables (``unique_id`` strings like
    ``"facility-12345"``). Callers should treat it as opaque.
    """

    id: str
    external_id: str | None = None
    name: str
    type: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    pincode: str | None = None
    country: str = "IN"
    latitude: float | None = None
    longitude: float | None = None
    specialties: list[str] | None = None
    services: list[str] | None = None
    equipment: list[str] | None = None
    procedures: list[str] | None = None
    raw_description: str | None = None
    confidence: dict[str, float] | None = None
    source: str | None = None

    model_config = ConfigDict(from_attributes=True)


class SearchResultItem(BaseModel):
    facility: FacilityOut
    distance_km: float | None = None
    match_score: float
    top_evidence: Evidence | None = None
    reasoning: str | None = None
    evidence: list[Evidence] | None = None
    # Agentic-only enrichments (populated by the LLM pipeline; ``None`` for
    # the deterministic ``quick`` search).
    trust_signal: str | None = None
    trust_rank: int | None = None
    evidence_summary: str | None = None
    missing_evidence: list[str] | None = None
    quality_boost: int | None = None
    quality_reasons: list[str] | None = None
    attributes: dict[str, Any] | None = None
    scoring_method: str | None = None


class SearchOrigin(BaseModel):
    """Resolved location for the search query."""

    lat: float | None = None
    lng: float | None = None
    label: str | None = None


class AgentTraceStep(BaseModel):
    """One row in the LLM pipeline's visible reasoning trace."""

    agent: str
    reasoning: str | None = None
    output: Any | None = None
    method: str | None = None
    latency_ms: float | None = None


class ParsedQueryOut(BaseModel):
    """Structured interpretation of the user's raw natural-language query."""

    raw_query: str | None = None
    capability_text: str | None = None
    location_text: str | None = None
    specialty_terms: list[str] | None = None
    location: dict[str, Any] | None = None
    urgency: str | None = None
    language: str | None = None


class SearchResults(BaseModel):
    origin: SearchOrigin
    results: list[SearchResultItem]
    reasoning_summary: str | None = None
    # The LLM's chain-of-thought for the final recommendation step. Only
    # populated by the agentic pipeline; ``None`` in deterministic mode.
    recommendation_reasoning: str | None = None
    # Per-node trace from the agentic pipeline. Empty list in deterministic
    # mode so the UI can render the panel unconditionally.
    agent_trace: list[AgentTraceStep] = []
    # Structured echo of the LLM's query interpretation (capability,
    # urgency, language). Helps the user see what the model "heard".
    parsed_query: ParsedQueryOut | None = None
    mode: str  # "quick" | "agentic"


class LocationIn(BaseModel):
    lat: float | None = None
    lng: float | None = None
    label: str | None = None


class SearchIn(BaseModel):
    query: str | None = None
    location: LocationIn | None = None
    location_text: str | None = None
    radius_km: int = 100
    specialties: list[str] | None = None
    min_confidence: float = 0.0
    limit: int = 50


# ---------------------------------------------------------------------------
# Submissions API models
# ---------------------------------------------------------------------------


class SubmissionIn(BaseModel):
    submission_type: SubmissionType
    payload: dict[str, Any]
    captured_lat: float | None = None
    captured_lng: float | None = None
    captured_at: datetime | None = None
    photo_url: str | None = None
    notes: str | None = None


class SubmissionOut(BaseModel):
    id: UUID
    status: SubmissionStatus
    submission_type: SubmissionType
    submitted_by: str | None = None
    submitted_at: datetime
    payload: dict[str, Any]
    captured_lat: float | None = None
    captured_lng: float | None = None
    captured_at: datetime | None = None
    photo_url: str | None = None
    notes: str | None = None

    model_config = ConfigDict(from_attributes=True)
