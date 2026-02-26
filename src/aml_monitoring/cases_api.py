"""Cases API router: explicit registration for /cases endpoints."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from aml_monitoring.audit_context import get_correlation_id
from aml_monitoring.auth import require_api_key_write
from aml_monitoring.case_lifecycle import validate_case_status_transition
from aml_monitoring.db import session_scope
from aml_monitoring.models import AuditLog, Case, CaseItem, CaseNote
from aml_monitoring.schemas import (
    CaseCreateRequest,
    CaseItemResponse,
    CaseNoteRequest,
    CaseNoteResponse,
    CaseResponse,
    CaseUpdateRequest,
)

cases_router = APIRouter(tags=["cases"])


def _case_to_response(case: Case) -> CaseResponse:
    return CaseResponse(
        id=case.id,
        status=case.status,
        priority=case.priority,
        assigned_to=case.assigned_to,
        created_at=case.created_at,
        updated_at=case.updated_at,
        correlation_id=case.correlation_id,
        actor=case.actor,
        items=[CaseItemResponse.model_validate(i) for i in case.items],
        notes=[CaseNoteResponse.model_validate(n) for n in case.notes],
    )


@cases_router.post("/cases", response_model=CaseResponse)
def create_case(
    body: CaseCreateRequest, _actor: str = Depends(require_api_key_write)
) -> CaseResponse:
    """Create a case with optional items and initial note. Audited."""
    cid = get_correlation_id()
    actor = _actor
    priority = body.priority if body.priority is not None else "MEDIUM"
    with session_scope() as session:
        case = Case(
            status="NEW",
            priority=priority,
            assigned_to=body.assigned_to,
            correlation_id=cid,
            actor=actor,
        )
        session.add(case)
        session.flush()
        session.add(
            AuditLog(
                correlation_id=cid,
                action="case_create",
                entity_type="case",
                entity_id=str(case.id),
                actor=actor,
                details_json={"priority": priority},
            )
        )
        for aid in body.alert_ids or []:
            item = CaseItem(case_id=case.id, alert_id=aid, transaction_id=None)
            session.add(item)
            session.flush()
            session.add(
                AuditLog(
                    correlation_id=cid,
                    action="case_item_add",
                    entity_type="case",
                    entity_id=str(case.id),
                    actor=actor,
                    details_json={"case_item_id": item.id, "alert_id": aid},
                )
            )
        for tid in body.transaction_ids or []:
            item = CaseItem(case_id=case.id, alert_id=None, transaction_id=tid)
            session.add(item)
            session.flush()
            session.add(
                AuditLog(
                    correlation_id=cid,
                    action="case_item_add",
                    entity_type="case",
                    entity_id=str(case.id),
                    actor=actor,
                    details_json={"case_item_id": item.id, "transaction_id": tid},
                )
            )
        if body.note:
            note = CaseNote(
                case_id=case.id,
                note=body.note,
                actor=actor,
                correlation_id=cid,
            )
            session.add(note)
            session.flush()
            session.add(
                AuditLog(
                    correlation_id=cid,
                    action="case_note_add",
                    entity_type="case",
                    entity_id=str(case.id),
                    actor=actor,
                    details_json={"case_note_id": note.id},
                )
            )
        session.refresh(case, ["items", "notes"])
        return _case_to_response(case)


@cases_router.get("/cases", response_model=list[CaseResponse])
def list_cases(
    status: str | None = Query(None),
    assigned_to: str | None = Query(None),
    priority: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[CaseResponse]:
    """List cases with optional filters."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    with session_scope() as session:
        stmt = (
            select(Case)
            .options(selectinload(Case.items), selectinload(Case.notes))
            .order_by(Case.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(Case.status == status)
        if assigned_to is not None:
            stmt = stmt.where(Case.assigned_to == assigned_to)
        if priority is not None:
            stmt = stmt.where(Case.priority == priority)
        cases = list(session.execute(stmt).scalars().all())
        return [_case_to_response(c) for c in cases]


@cases_router.get("/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: int) -> CaseResponse:
    """Get case by ID with items and notes."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    with session_scope() as session:
        stmt = (
            select(Case)
            .where(Case.id == case_id)
            .options(selectinload(Case.items), selectinload(Case.notes))
        )
        case = session.execute(stmt).scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return _case_to_response(case)


@cases_router.patch("/cases/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: int, body: CaseUpdateRequest, _actor: str = Depends(require_api_key_write)
) -> CaseResponse:
    """Update case status, priority, or assigned_to. Status transitions validated. Audited."""
    from sqlalchemy import select

    with session_scope() as session:
        case = session.execute(select(Case).where(Case.id == case_id)).scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        cid = get_correlation_id()
        actor = _actor
        details: dict[str, Any] = {}
        if body.status is not None:
            try:
                validate_case_status_transition(case.status, body.status)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e
            details["old_status"] = case.status
            details["new_status"] = body.status
            case.status = body.status
        if body.priority is not None:
            details["old_priority"] = case.priority
            details["new_priority"] = body.priority
            case.priority = body.priority
        if body.assigned_to is not None:
            details["old_assigned_to"] = case.assigned_to
            details["new_assigned_to"] = body.assigned_to
            case.assigned_to = body.assigned_to
        case.updated_at = datetime.now(UTC)
        case.correlation_id = cid
        case.actor = actor
        session.add(
            AuditLog(
                correlation_id=cid,
                action="case_update",
                entity_type="case",
                entity_id=str(case_id),
                actor=actor,
                details_json=details or None,
            )
        )
        session.flush()
        session.refresh(case, ["items", "notes"])
        return _case_to_response(case)


@cases_router.post("/cases/{case_id}/notes", response_model=CaseNoteResponse)
def add_case_note(
    case_id: int, body: CaseNoteRequest, _actor: str = Depends(require_api_key_write)
) -> CaseNoteResponse:
    """Add a note to a case. Audited."""
    from sqlalchemy import select

    with session_scope() as session:
        case = session.execute(select(Case).where(Case.id == case_id)).scalar_one_or_none()
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        cid = get_correlation_id()
        actor = _actor
        note = CaseNote(case_id=case_id, note=body.note, actor=actor, correlation_id=cid)
        session.add(note)
        session.flush()
        session.add(
            AuditLog(
                correlation_id=cid,
                action="case_note_add",
                entity_type="case",
                entity_id=str(case_id),
                actor=actor,
                details_json={"case_note_id": note.id},
            )
        )
        session.refresh(note)
        return CaseNoteResponse.model_validate(note)
