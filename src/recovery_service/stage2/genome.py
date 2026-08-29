from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .schemas import (
    DiagnosisResult,
    EvidenceManifest,
    FailureDNA,
    GenomeProvenance,
    IncidentCluster,
    P0GenomeSource,
    P1GenomeSource,
    RecoveryEligibility,
    RecoveryGenome,
    TemporalFeatures,
)


GENOME_SCHEMA_VERSION = "1.0"


def assemble_recovery_genome(
    manifest: EvidenceManifest,
    diagnosis: DiagnosisResult,
    fdna: FailureDNA,
    temporal: TemporalFeatures,
    incident: IncidentCluster,
    compliance: RecoveryEligibility,
) -> RecoveryGenome:
    """Assemble immutable RecoveryGenome snapshot combining P0 and P1 context."""

    now = datetime.now(timezone.utc)

    p0_source = P0GenomeSource(
        diagnosis_id=diagnosis.diagnosis_id,
        diagnosis_class=diagnosis.diagnosis_class,
        diagnosis_confidence=diagnosis.confidence,
        failure_dna_fingerprint=fdna.fingerprint_hash,
        failure_dna_features=fdna.model_dump(mode="json"),
        temporal_features=temporal.model_dump(mode="json"),
        rail="card",
        rail_subtype="credit",
        geography_bucket=fdna.geography_bucket,
        recoverable_amount=manifest.failure.raw_details.get("amount") or 0,
    )

    p1_source = P1GenomeSource(
        incident_id=incident.incident_id,
        incident_confidence=incident.incident_confidence,
        compliance_eligibility=compliance.eligibility,
        compliance_attempts_remaining=compliance.attempts_remaining,
        compliance_advice_code_action=compliance.advice_code,
    )

    provenance = GenomeProvenance(
        genome_schema_version=GENOME_SCHEMA_VERSION,
        diagnosis_engine_version=diagnosis.engine_version,
        fingerprint_version=fdna.version,
        incident_engine_version=incident.engine_version,
        compliance_ruleset_version=compliance.ruleset_version,
        assembled_at=now,
    )

    raw_payload = {
        "case_id": manifest.identity.case_id,
        "stage1_state_version": manifest.state.stage1_state_version,
        "diagnosis_id": diagnosis.diagnosis_id,
        "fingerprint_hash": fdna.fingerprint_hash,
        "incident_id": incident.incident_id,
        "eligibility": compliance.eligibility,
        "schema_version": GENOME_SCHEMA_VERSION,
    }

    genome_hash = hashlib.sha256(json.dumps(raw_payload, sort_keys=True).encode("utf-8")).hexdigest()[:32]
    genome_id = f"genome_{genome_hash}"

    return RecoveryGenome(
        genome_id=genome_id,
        case_id=manifest.identity.case_id,
        p0_source=p0_source,
        p1_source=p1_source,
        provenance=provenance,
    )
