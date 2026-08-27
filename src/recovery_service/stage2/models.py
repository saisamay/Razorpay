from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Stage2Case(Base):
    """Registered RecoveryCase processing state in Stage 2.

    Composite Primary Key (case_id, stage1_state_version) guarantees idempotent
    registration across duplicate stream deliveries.
    """

    __tablename__ = "stage2_cases"

    case_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RECEIVED", index=True)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class EvidenceManifestRecord(Base):
    """Normalized evidence manifest artifact in Stage 2."""

    __tablename__ = "evidence_manifests"
    __table_args__ = (UniqueConstraint("case_id", "stage1_state_version", "normalizer_version", name="uq_manifest_case_version"),)

    manifest_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    normalizer_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    provenance_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class DiagnosisRecord(Base):
    """Immutable diagnosis artifact in Stage 2."""

    __tablename__ = "diagnoses"
    __table_args__ = (
        UniqueConstraint("case_id", "stage1_state_version", "engine_version", name="uq_diagnosis_case_version_engine"),
    )

    diagnosis_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    diagnosis_class: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    score: Mapped[float] = mapped_column(nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="CURRENT", index=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contradiction_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    competing_hypotheses: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class FailureFingerprintRecord(Base):
    """Versioned FailureDNA fingerprint & temporal features in Stage 2."""

    __tablename__ = "failure_fingerprints"
    __table_args__ = (
        UniqueConstraint("case_id", "stage1_state_version", "version", name="uq_fingerprint_case_version"),
    )

    fingerprint_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    diagnosis_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    stage1_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    merchant_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    fingerprint_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0")
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False)
    temporal_features: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
