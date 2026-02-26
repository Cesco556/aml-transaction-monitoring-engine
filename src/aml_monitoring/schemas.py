"""Pydantic v2 schemas for API and validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# --- Ingest / API input ---
class TransactionCreate(BaseModel):
    """Single transaction for API scoring or ingest validation."""

    account_id: int
    ts: datetime
    amount: float = Field(..., ge=-1e12, le=1e12)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    merchant: str | None = None
    counterparty: str | None = None
    country: str | None = Field(None, min_length=2, max_length=3)
    channel: str | None = None
    direction: str | None = Field(None, pattern="^(in|out)$")
    metadata_json: dict[str, Any] | None = None


class TransactionResponse(BaseModel):
    """Transaction with optional risk score and alerts."""

    id: int
    account_id: int
    ts: datetime
    amount: float
    currency: str
    risk_score: float | None
    alerts: list[AlertResponse] = []

    model_config = {"from_attributes": True}


ALERT_STATUS_VALUES = frozenset({"open", "closed"})
ALERT_DISPOSITION_VALUES = frozenset({"false_positive", "escalate", "sar"})


class AlertPatchRequest(BaseModel):
    """Partial update for PATCH /alerts/{id}. Only provided fields are updated."""

    status: str | None = None
    disposition: str | None = None

    @model_validator(mode="after")
    def check_enum_values(self) -> AlertPatchRequest:
        if self.status is not None and self.status not in ALERT_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(ALERT_STATUS_VALUES)}")
        if self.disposition is not None and self.disposition not in ALERT_DISPOSITION_VALUES:
            raise ValueError(
                f"disposition must be one of {sorted(ALERT_DISPOSITION_VALUES)} or omit"
            )
        return self


class AlertResponse(BaseModel):
    id: int
    transaction_id: int
    rule_id: str
    severity: str
    score: float
    reason: str
    evidence_fields: dict[str, Any] | None
    config_hash: str | None = None
    rules_version: str | None = None
    engine_version: str | None = None
    correlation_id: str | None = None
    status: str = "open"
    disposition: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}

    @field_validator("status", mode="before")
    @classmethod
    def status_default(cls, v: str | None) -> str:
        return v if v in ALERT_STATUS_VALUES else "open"


class ScoreRequest(BaseModel):
    """Request body for /score endpoint."""

    transaction: TransactionCreate


class ScoreResponse(BaseModel):
    """Response for /score: risk score and any rule hits."""

    risk_score: float
    band: str  # low | medium | high
    rule_hits: list[RuleHit]


class RuleHit(BaseModel):
    rule_id: str
    severity: str
    reason: str
    evidence_fields: dict[str, Any] | None = None
    score_delta: float


# --- Rules internal ---
class RuleResult(BaseModel):
    """Output of a single rule evaluation."""

    rule_id: str
    severity: str
    reason: str
    evidence_fields: dict[str, Any] | None = None
    score_delta: float


# --- Case management ---
class CaseCreateRequest(BaseModel):
    """Body for POST /cases."""

    alert_ids: list[int] = []
    transaction_ids: list[int] = []
    priority: str | None = None
    assigned_to: str | None = None
    note: str | None = None

    @field_validator("priority")
    @classmethod
    def priority_enum(cls, v: str | None) -> str | None:
        from aml_monitoring.case_lifecycle import CASE_PRIORITY_VALUES

        if v is not None and v not in CASE_PRIORITY_VALUES:
            raise ValueError(f"priority must be one of {sorted(CASE_PRIORITY_VALUES)}")
        return v


class CaseUpdateRequest(BaseModel):
    """Body for PATCH /cases/{id}."""

    status: str | None = None
    priority: str | None = None
    assigned_to: str | None = None

    @field_validator("status")
    @classmethod
    def status_enum(cls, v: str | None) -> str | None:
        from aml_monitoring.case_lifecycle import CASE_STATUS_VALUES

        if v is not None and v not in CASE_STATUS_VALUES:
            raise ValueError(f"status must be one of {sorted(CASE_STATUS_VALUES)}")
        return v

    @field_validator("priority")
    @classmethod
    def priority_enum(cls, v: str | None) -> str | None:
        from aml_monitoring.case_lifecycle import CASE_PRIORITY_VALUES

        if v is not None and v not in CASE_PRIORITY_VALUES:
            raise ValueError(f"priority must be one of {sorted(CASE_PRIORITY_VALUES)}")
        return v


class CaseNoteRequest(BaseModel):
    """Body for POST /cases/{id}/notes."""

    note: str


class CaseItemResponse(BaseModel):
    id: int
    case_id: int
    alert_id: int | None
    transaction_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CaseNoteResponse(BaseModel):
    id: int
    case_id: int
    note: str
    created_at: datetime
    actor: str
    correlation_id: str

    model_config = {"from_attributes": True}


class CaseResponse(BaseModel):
    id: int
    status: str
    priority: str
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime | None
    correlation_id: str | None
    actor: str | None
    items: list[CaseItemResponse] = []
    notes: list[CaseNoteResponse] = []

    model_config = {"from_attributes": True}


# --- Reporting ---
class SARReportRecord(BaseModel):
    """Single record in SAR-like report."""

    alert_id: int
    transaction_id: int
    rule_id: str
    severity: str
    reason: str
    amount: float
    currency: str
    ts: datetime
    account_id: int
    counterparty: str | None
    country: str | None
    evidence: dict[str, Any] | None
