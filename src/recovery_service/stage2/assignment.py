from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import RecoveryCase
from .experiment import compute_configuration_hash, experiment_design_from_record
from .models import (
    CaseAssignmentLinkRecord,
    ExperimentAssignmentRecord,
    ExperimentDesignRecord,
    IdentityBindingRecord,
    IdentityQuarantineRecord,
)
from .schemas import CaseAssignmentLink, ExperimentAssignmentResult


logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "v1"
ASSIGNMENT_ALGORITHM_VERSION = "1.0"


def resolve_production_secret_salt() -> str | None:
    """Authoritative secret salt resolver for F3 experiment assignment.
    
    Returns secret salt strictly from environment variable ASSIGNMENT_SECRET_SALT.
    Returns None if absent, empty, whitespace-only, or invalid type.
    NO fallback to DEFAULT_ASSIGNMENT_SALT or hardcoded secret is permitted.
    """
    try:
        val = os.environ.get("ASSIGNMENT_SECRET_SALT")
        if not val or not isinstance(val, str) or not val.strip():
            return None
        return val.strip()
    except Exception:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def canonical_encode_input(
    protocol_version: str,
    experiment_id: str,
    experiment_version: str,
    merchant_id: str,
    identity_type: str,
    identity_fingerprint: str,
    assignment_salt_version: str,
    assignment_algorithm_version: str,
) -> bytes:
    """Injective length-prefixed canonical encoding (v1.6 Section 16 & I-009).

    Prevents length-prefix collisions or boundary blending (e.g. A + BC vs AB + C).
    """
    fields = [
        protocol_version,
        experiment_id,
        experiment_version,
        merchant_id,
        identity_type,
        identity_fingerprint,
        assignment_salt_version,
        assignment_algorithm_version,
    ]

    parts = []
    for f in fields:
        if f is None:
            parts.append("-1:NULL")
        else:
            val = str(f)
            parts.append(f"{len(val.encode('utf-8'))}:{val}")

    return ":".join(parts).encode("utf-8")


def compute_hmac_assignment_bucket(secret_salt: str, canonical_bytes: bytes) -> tuple[float, str]:
    """Pure HMAC-SHA256 assignment bucket algorithm (v1.6 Section 17 & I-001)."""
    digest_hex = hmac.new(secret_salt.encode("utf-8"), canonical_bytes, hashlib.sha256).hexdigest()
    digest_int = int(digest_hex, 16)
    bucket = (digest_int >> 203) / (1 << 53)
    return bucket, digest_hex


def resolve_assignment_identity(
    case: RecoveryCase,
    configured_strategy: str,
) -> tuple[str, str, str, str]:
    """Resolve merchant-scoped stable identity hierarchy (v1.6 Section 4 & I-008, I-017).

    Returns: (identity_type, resolved_identity_source_key, identity_fingerprint, assignment_unit_type)
    """
    merchant_id = case.merchant_id or "default_merchant"

    # 1. Customer-Stable (if present on RecoveryCase failure_evidence or metadata)
    ev = case.failure_evidence or {}
    cust_id = ev.get("customer_id") or ev.get("user_id")

    if cust_id and configured_strategy in {"MERCHANT_SCOPED_CUSTOMER_STABLE", "ALL"}:
        id_type = "MERCHANT_SCOPED_CUSTOMER_STABLE"
        source_key = f"{merchant_id}:{cust_id}"
        unit_type = "CUSTOMER"
    elif case.payment_id and configured_strategy in {"MERCHANT_SCOPED_CUSTOMER_STABLE", "MERCHANT_SCOPED_PAYMENT_STABLE", "ALL"}:
        id_type = "MERCHANT_SCOPED_PAYMENT_STABLE"
        source_key = f"{merchant_id}:{case.payment_id}"
        unit_type = "PAYMENT"
    else:
        id_type = "MERCHANT_SCOPED_CASE_STABLE"
        source_key = f"{merchant_id}:{case.case_id}"
        unit_type = "CASE"

    # Compute SHA-256 fingerprint of (merchant_id, identity_type, source_key)
    raw_fp = f"{merchant_id}:{id_type}:{source_key}"
    fingerprint = hashlib.sha256(raw_fp.encode("utf-8")).hexdigest()
    return id_type, source_key, fingerprint, unit_type


def assign_experiment_case(
    session: Session,
    case_id: str,
    *,
    experiment_id: str | None = None,
    secret_salt: str | None = None,
) -> tuple[ExperimentAssignmentResult | None, CaseAssignmentLinkRecord | None]:
    """Execute F3 Controlled Experiment Assignment for a RecoveryCase.

    Strictly satisfies Invariants I-001 through I-026.
    """
    now = utc_now()
    try:
        resolved_salt = secret_salt if secret_salt is not None else resolve_production_secret_salt()
    except Exception as exc:
        logger.warning(f"Secret salt resolution exception for case {case_id}: {exc}")
        resolved_salt = None

    case = session.get(RecoveryCase, case_id, with_for_update=True)
    if case is None:
        raise ValueError(f"RecoveryCase {case_id} not found")

    merchant_id = case.merchant_id or "default_merchant"

    # Find active or targeted RUNNING ExperimentDesign with DB row lock (FOR UPDATE)
    if experiment_id:
        exp_rec = session.scalars(
            select(ExperimentDesignRecord)
            .where(ExperimentDesignRecord.experiment_id == experiment_id)
            .order_by(ExperimentDesignRecord.experiment_version.desc())
            .with_for_update()
        ).first()
    else:
        exp_rec = session.scalars(
            select(ExperimentDesignRecord)
            .where(
                ExperimentDesignRecord.population_definition == "ALL_ELIGIBLE_FAILED_RECOVERY_CASES",
                ExperimentDesignRecord.status == "RUNNING",
            )
            .with_for_update()
        ).first()

    # Gate 1: Check Experiment State (I-010, Section 7)
    if exp_rec is None or exp_rec.status != "RUNNING":
        return None, None

    # Secret Salt Fail-Closed Safety Check (I-005, Section 18)
    if not isinstance(resolved_salt, str) or not resolved_salt.strip():
        logger.warning(f"Secret salt missing or invalid for case {case_id}")
        return _record_unassigned_link(
            session, case, exp_rec, "UNASSIGNED", "INFRASTRUCTURE_FAILURE", now
        )

    # Gate 2: Check Existing Immutable Case Assignment Link (I-003, Section 22)
    existing_link = session.scalars(
        select(CaseAssignmentLinkRecord)
        .where(
            CaseAssignmentLinkRecord.case_id == case_id,
            CaseAssignmentLinkRecord.experiment_id == exp_rec.experiment_id,
            CaseAssignmentLinkRecord.experiment_version == exp_rec.experiment_version,
        )
    ).first()
    if existing_link is not None:
        # Immutable case link already exists! Return linked assignment result
        asgn_rec = session.get(ExperimentAssignmentRecord, existing_link.assignment_id)
        bind_rec = session.get(IdentityBindingRecord, existing_link.binding_id)
        if asgn_rec and bind_rec:
            return ExperimentAssignmentResult(
                assignment_id=asgn_rec.assignment_id,
                binding_id=bind_rec.binding_id,
                experiment_id=asgn_rec.experiment_id,
                experiment_version=asgn_rec.experiment_version,
                merchant_id=asgn_rec.merchant_id,
                assignment_arm=asgn_rec.assignment_arm,
                assignment_status=asgn_rec.assignment_status,
                identity_type=bind_rec.identity_type,
                assignment_unit_type=bind_rec.assignment_unit_type,
                assignment_unit_id=bind_rec.assignment_unit_id,
                assignment_algorithm_version=asgn_rec.assignment_algorithm_version,
                assignment_salt_version=asgn_rec.assignment_salt_version,
                configuration_hash=asgn_rec.configuration_hash,
                created_at=asgn_rec.created_at,
            ), existing_link

    # Gate 3: Check Population Entry Boundaries (Section 12, I-006, I-007)
    first_seen = _utc(case.first_seen_at) or now
    start_time = _utc(exp_rec.population_start_time)
    end_time = _utc(exp_rec.population_end_time)

    if start_time and first_seen < start_time:
        # Pre-start case! Must be NOT_ASSIGNED_PRESTART (I-006)
        return _record_unassigned_link(
            session, case, exp_rec, "EXCLUDED", "NOT_ASSIGNED_PRESTART", now
        )

    if end_time and first_seen > end_time:
        # Post-end case! Must be NOT_ASSIGNED_POSTEND (I-007)
        return _record_unassigned_link(
            session, case, exp_rec, "EXCLUDED", "NOT_ASSIGNED_POSTEND", now
        )

    # Gate 4: Verify Approved Configuration Hash Integrity (Section 15, I-010)
    if not exp_rec.approved_configuration_hash:
        return _record_unassigned_link(
            session, case, exp_rec, "UNASSIGNED", "UNASSIGNED_STALE_CONFIGURATION", now
        )

    try:
        current_dto = experiment_design_from_record(exp_rec)
        recomputed_hash = compute_configuration_hash(current_dto)
    except Exception as exc:
        logger.warning(f"Failed to reconstruct or compute configuration hash for experiment {exp_rec.experiment_id}: {exc}")
        return _record_unassigned_link(
            session, case, exp_rec, "UNASSIGNED", "UNASSIGNED_STALE_CONFIGURATION", now
        )

    if recomputed_hash != exp_rec.approved_configuration_hash:
        logger.warning(
            f"Stale/mutated configuration hash for experiment {exp_rec.experiment_id}: "
            f"recomputed={recomputed_hash}, approved={exp_rec.approved_configuration_hash}"
        )
        return _record_unassigned_link(
            session, case, exp_rec, "UNASSIGNED", "UNASSIGNED_STALE_CONFIGURATION", now
        )

    # Resolve Identity
    id_type, source_key, fingerprint, unit_type = resolve_assignment_identity(
        case, exp_rec.assignment_identity_strategy
    )

    # Gate 5: Check Identity Quarantine Status (Section 25, I-019)
    quarantine = session.scalars(
        select(IdentityQuarantineRecord)
        .where(
            IdentityQuarantineRecord.merchant_id == merchant_id,
            IdentityQuarantineRecord.identity_type == id_type,
            IdentityQuarantineRecord.identity_fingerprint == fingerprint,
        )
    ).first()
    if quarantine and quarantine.status in {"QUARANTINED", "ACTIVE_CONFLICT"}:
        return _record_unassigned_link(
            session, case, exp_rec, "EXCLUDED", "QUARANTINED", now
        )

    # Gate 6: Authoritative 5-Column IdentityBinding Lookup (I-002, I-013, I-021)
    binding = session.scalars(
        select(IdentityBindingRecord)
        .where(
            IdentityBindingRecord.experiment_id == exp_rec.experiment_id,
            IdentityBindingRecord.experiment_version == exp_rec.experiment_version,
            IdentityBindingRecord.merchant_id == merchant_id,
            IdentityBindingRecord.identity_type == id_type,
            IdentityBindingRecord.resolved_identity_source_key == source_key,
        )
        .with_for_update()
    ).first()

    if binding is None:
        binding_id = f"bind_{uuid.uuid4().hex}"
        try:
            with session.begin_nested():
                new_binding = IdentityBindingRecord(
                    binding_id=binding_id,
                    experiment_id=exp_rec.experiment_id,
                    experiment_version=exp_rec.experiment_version,
                    merchant_id=merchant_id,
                    identity_type=id_type,
                    resolved_identity_source_key=source_key,
                    identity_fingerprint=fingerprint,
                    resolver_version="1.0",
                    assignment_unit_type=unit_type,
                    assignment_unit_id=source_key,
                    created_at=now,
                )
                session.add(new_binding)
                session.flush()
                binding = new_binding
        except IntegrityError:
            # Race condition! Winning worker created binding concurrently under uq_binding_lookup.
            # Reload winning binding using 5-column composite lookup key.
            binding = session.scalars(
                select(IdentityBindingRecord)
                .where(
                    IdentityBindingRecord.experiment_id == exp_rec.experiment_id,
                    IdentityBindingRecord.experiment_version == exp_rec.experiment_version,
                    IdentityBindingRecord.merchant_id == merchant_id,
                    IdentityBindingRecord.identity_type == id_type,
                    IdentityBindingRecord.resolved_identity_source_key == source_key,
                )
                .with_for_update()
            ).first()

    if binding is None:
        return _record_unassigned_link(
            session, case, exp_rec, "UNASSIGNED", "INFRASTRUCTURE_FAILURE", now
        )

    binding_id = binding.binding_id

    # Gate 7: Pure HMAC Assignment Derivation (Section 17, I-001)
    canonical_bytes = canonical_encode_input(
        PROTOCOL_VERSION,
        exp_rec.experiment_id,
        exp_rec.experiment_version,
        merchant_id,
        id_type,
        fingerprint,
        exp_rec.assignment_salt_version,
        ASSIGNMENT_ALGORITHM_VERSION,
    )

    bucket, _ = compute_hmac_assignment_bucket(resolved_salt, canonical_bytes)
    assigned_arm = "TREATMENT" if bucket < exp_rec.allocation_ratio else "CONTROL"
    assigned_status = f"ASSIGNED_{assigned_arm}"

    # Gate 8: Commit-Time Experiment Validity Verification (I-026 & Section 20)
    # Re-verify experiment status under row-level lock right before persisting assignment
    session.expire(exp_rec)
    recheck_exp = session.scalars(
        select(ExperimentDesignRecord)
        .where(
            ExperimentDesignRecord.id == exp_rec.id,
            ExperimentDesignRecord.status == "RUNNING",
        )
        .with_for_update()
    ).first()
    if recheck_exp is None:
        logger.warning(f"Experiment state invalid at commit boundary for case {case_id}")
        return _record_unassigned_link(
            session, case, exp_rec, "UNASSIGNED", "EXPERIMENT_INACTIVE", now
        )

    # Gate 9: Persist Idempotent ExperimentAssignment & CaseAssignmentLink (Section 19 & 21, I-014, I-015)
    assignment_id = f"asgn_{binding_id}"
    asgn_rec = session.get(ExperimentAssignmentRecord, assignment_id, with_for_update=True)
    if asgn_rec is None:
        try:
            with session.begin_nested():
                new_asgn = ExperimentAssignmentRecord(
                    assignment_id=assignment_id,
                    binding_id=binding_id,
                    experiment_id=exp_rec.experiment_id,
                    experiment_version=exp_rec.experiment_version,
                    merchant_id=merchant_id,
                    assignment_arm=assigned_arm,
                    assignment_status=assigned_status,
                    assignment_algorithm_version=ASSIGNMENT_ALGORITHM_VERSION,
                    assignment_salt_version=exp_rec.assignment_salt_version,
                    configuration_hash=exp_rec.approved_configuration_hash,
                    created_at=now,
                )
                session.add(new_asgn)
                session.flush()
                asgn_rec = new_asgn
        except IntegrityError:
            asgn_rec = session.get(ExperimentAssignmentRecord, assignment_id, with_for_update=True)

    link_id = f"link_{case_id}_{exp_rec.experiment_id}_{exp_rec.experiment_version}"
    link_rec = session.get(CaseAssignmentLinkRecord, link_id, with_for_update=True)
    if link_rec is None:
        try:
            with session.begin_nested():
                new_link = CaseAssignmentLinkRecord(
                    link_id=link_id,
                    case_id=case_id,
                    experiment_id=exp_rec.experiment_id,
                    experiment_version=exp_rec.experiment_version,
                    merchant_id=merchant_id,
                    binding_id=binding_id,
                    assignment_id=asgn_rec.assignment_id if asgn_rec else assignment_id,
                    assignment_arm=assigned_arm,
                    assignment_status=assigned_status,
                    created_at=now,
                )
                session.add(new_link)
                session.flush()
                link_rec = new_link
        except IntegrityError:
            link_rec = session.get(CaseAssignmentLinkRecord, link_id, with_for_update=True)

    result_dto = ExperimentAssignmentResult(
        assignment_id=asgn_rec.assignment_id if asgn_rec else assignment_id,
        binding_id=binding_id,
        experiment_id=exp_rec.experiment_id,
        experiment_version=exp_rec.experiment_version,
        merchant_id=merchant_id,
        assignment_arm=assigned_arm,
        assignment_status=assigned_status,
        identity_type=id_type,
        assignment_unit_type=unit_type,
        assignment_unit_id=source_key,
        assignment_algorithm_version=ASSIGNMENT_ALGORITHM_VERSION,
        assignment_salt_version=exp_rec.assignment_salt_version,
        configuration_hash=exp_rec.approved_configuration_hash,
        created_at=now,
    )

    return result_dto, link_rec


def _record_unassigned_link(
    session: Session,
    case: RecoveryCase,
    exp_rec: ExperimentDesignRecord,
    arm: str,
    status: str,
    now: datetime,
) -> tuple[ExperimentAssignmentResult, CaseAssignmentLinkRecord]:
    """Record an unassigned or excluded case link without creating a treatment/control assignment."""
    merchant_id = case.merchant_id or "default_merchant"
    binding_id = f"bind_unassigned_{case.case_id}"
    assignment_id = f"asgn_unassigned_{case.case_id}"
    link_id = f"link_{case.case_id}_{exp_rec.experiment_id}_{exp_rec.experiment_version}"

    link_rec = session.get(CaseAssignmentLinkRecord, link_id, with_for_update=True)
    if link_rec is None:
        link_rec = CaseAssignmentLinkRecord(
            link_id=link_id,
            case_id=case.case_id,
            experiment_id=exp_rec.experiment_id,
            experiment_version=exp_rec.experiment_version,
            merchant_id=merchant_id,
            binding_id=binding_id,
            assignment_id=assignment_id,
            assignment_arm=arm,
            assignment_status=status,
            created_at=now,
        )
        session.add(link_rec)
        session.flush()

    dto = ExperimentAssignmentResult(
        assignment_id=assignment_id,
        binding_id=binding_id,
        experiment_id=exp_rec.experiment_id,
        experiment_version=exp_rec.experiment_version,
        merchant_id=merchant_id,
        assignment_arm=arm,
        assignment_status=status,
        identity_type="UNASSIGNED",
        assignment_unit_type="CASE",
        assignment_unit_id=case.case_id,
        assignment_algorithm_version=ASSIGNMENT_ALGORITHM_VERSION,
        assignment_salt_version=exp_rec.assignment_salt_version,
        configuration_hash=exp_rec.approved_configuration_hash or "NONE",
        created_at=now,
    )
    return dto, link_rec
