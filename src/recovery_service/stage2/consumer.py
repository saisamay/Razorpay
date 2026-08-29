from __future__ import annotations

from dataclasses import dataclass
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import RecoveryCase
from .models import Stage2Case
from .schemas import RecoveryCaseContract


logger = logging.getLogger(__name__)


class Stage2ConsumerError(ValueError):
    pass


@dataclass(frozen=True)
class RegistrationResult:
    case_id: str
    stage1_state_version: int
    status: str
    duplicate: bool
    is_current: bool


def register_stage2_case(
    session: Session, contract: RecoveryCaseContract, *, worker_id: str | None = None
) -> RegistrationResult:
    """Validate Stage 1 handoff contract and register Stage2Case idempotently."""

    # 1. Schema & Version Validation
    if contract.schema_version not in {"1.0", "1.1", "1.5"}:
        raise Stage2ConsumerError(f"Unsupported schema version: {contract.schema_version}")

    # 2. Idempotent Registration Lookup
    existing = session.get(Stage2Case, (contract.case_id, contract.stage1_state_version), with_for_update=True)
    if existing is not None:
        return RegistrationResult(
            case_id=contract.case_id,
            stage1_state_version=contract.stage1_state_version,
            status=existing.status,
            duplicate=True,
            is_current=existing.is_current,
        )

    # 3. Check Authoritative PostgreSQL Truth for version & eligibility
    authoritative_case = session.get(RecoveryCase, contract.case_id, with_for_update=True)

    is_stale = False
    if authoritative_case is not None:
        if contract.stage1_state_version < authoritative_case.stage1_state_version or not authoritative_case.recovery_eligible:
            is_stale = True
    elif not contract.recovery_eligible:
        is_stale = True

    status = "STALE_SUPERSEDED" if is_stale else "REGISTERED"
    is_current = not is_stale

    if is_current:
        # Mark any previous stage2_cases for this payment_id as no longer current
        previous_cases = session.scalars(
            select(Stage2Case).where(Stage2Case.payment_id == contract.payment_id, Stage2Case.is_current == True).with_for_update()
        ).all()
        for prev in previous_cases:
            prev.is_current = False

    stage2_case = Stage2Case(
        case_id=contract.case_id,
        stage1_state_version=contract.stage1_state_version,
        payment_id=contract.payment_id,
        merchant_id=contract.merchant_id,
        status=status,
        is_current=is_current,
    )
    session.add(stage2_case)
    return RegistrationResult(
        case_id=contract.case_id,
        stage1_state_version=contract.stage1_state_version,
        status=status,
        duplicate=False,
        is_current=is_current,
    )


def process_evidence_manifest(
    session: Session,
    contract: RecoveryCaseContract,
    *,
    timeline_events: list[dict] | None = None,
    reconciliation_evidence: dict | None = None,
    worker_id: str | None = None,
) -> EvidenceManifest:
    """Generate and persist canonical EvidenceManifest artifact, transitioning status to EVIDENCE_READY."""

    from .models import EvidenceManifestRecord
    from .normalizer import normalize_evidence

    reg_res = register_stage2_case(session, contract, worker_id=worker_id)
    manifest = normalize_evidence(contract, timeline_events=timeline_events, reconciliation_evidence=reconciliation_evidence)

    if reg_res.status == "STALE_SUPERSEDED":
        return manifest

    existing_rec = session.get(EvidenceManifestRecord, manifest.manifest_id, with_for_update=True)
    if existing_rec is None:
        rec = EvidenceManifestRecord(
            manifest_id=manifest.manifest_id,
            case_id=contract.case_id,
            stage1_state_version=contract.stage1_state_version,
            payment_id=contract.payment_id,
            merchant_id=contract.merchant_id,
            normalizer_version=manifest.provenance.normalizer_version,
            provenance_hash=manifest.provenance.provenance_hash,
            data=manifest.model_dump(mode="json"),
        )
        session.add(rec)

    stage2_case = session.get(Stage2Case, (contract.case_id, contract.stage1_state_version), with_for_update=True)
    if stage2_case is not None:
        stage2_case.status = "EVIDENCE_READY"

    return manifest


def process_diagnosis(
    session: Session,
    contract: RecoveryCaseContract,
    *,
    timeline_events: list[dict] | None = None,
    reconciliation_evidence: dict | None = None,
    worker_id: str | None = None,
) -> tuple[EvidenceManifest, DiagnosisResult]:
    """Run full Stage 2 deterministic pipeline: Register -> Manifest -> Diagnosis -> Persist."""

    from .diagnosis_engine import evaluate_diagnosis
    from .models import DiagnosisRecord
    from .schemas import DiagnosisResult

    manifest = process_evidence_manifest(
        session, contract, timeline_events=timeline_events, reconciliation_evidence=reconciliation_evidence, worker_id=worker_id
    )

    stage2_case = session.get(Stage2Case, (contract.case_id, contract.stage1_state_version), with_for_update=True)
    if stage2_case is not None and stage2_case.status == "STALE_SUPERSEDED":
        diag_res = evaluate_diagnosis(manifest)
        return manifest, diag_res

    diag_res = evaluate_diagnosis(manifest)

    existing_diag = session.get(DiagnosisRecord, diag_res.diagnosis_id, with_for_update=True)
    if existing_diag is None:
        rec = DiagnosisRecord(
            diagnosis_id=diag_res.diagnosis_id,
            case_id=contract.case_id,
            stage1_state_version=contract.stage1_state_version,
            payment_id=contract.payment_id,
            merchant_id=contract.merchant_id,
            diagnosis_class=diag_res.diagnosis_class,
            score=diag_res.score,
            confidence=diag_res.confidence,
            engine_version=diag_res.engine_version,
            status=diag_res.status,
            evidence_ids=diag_res.evidence_ids,
            contradiction_ids=diag_res.contradiction_ids,
            competing_hypotheses=[h.model_dump(mode="json") for h in diag_res.competing_hypotheses],
        )
        session.add(rec)

    if stage2_case is not None:
        stage2_case.status = "DIAGNOSED"

    return manifest, diag_res


def process_failure_fingerprint(
    session: Session,
    contract: RecoveryCaseContract,
    *,
    timeline_events: list[dict] | None = None,
    reconciliation_evidence: dict | None = None,
    worker_id: str | None = None,
) -> tuple[EvidenceManifest, DiagnosisResult, FailureDNA, TemporalFeatures]:
    """Run full Stage 2 deterministic pipeline up to FailureDNA fingerprinting."""

    from .failure_dna import compute_failure_dna, compute_temporal_features
    from .models import FailureFingerprintRecord
    from .schemas import FailureDNA, TemporalFeatures

    manifest, diag = process_diagnosis(
        session, contract, timeline_events=timeline_events, reconciliation_evidence=reconciliation_evidence, worker_id=worker_id
    )

    fdna = compute_failure_dna(manifest)
    temporal = compute_temporal_features(manifest)

    stage2_case = session.get(Stage2Case, (contract.case_id, contract.stage1_state_version), with_for_update=True)
    if stage2_case is not None and stage2_case.status == "STALE_SUPERSEDED":
        return manifest, diag, fdna, temporal

    fingerprint_id = f"fdna_{fdna.fingerprint_hash[:32]}"
    existing_rec = session.get(FailureFingerprintRecord, fingerprint_id, with_for_update=True)
    if existing_rec is None:
        rec = FailureFingerprintRecord(
            fingerprint_id=fingerprint_id,
            case_id=contract.case_id,
            diagnosis_id=diag.diagnosis_id,
            stage1_state_version=contract.stage1_state_version,
            payment_id=contract.payment_id,
            merchant_id=contract.merchant_id,
            fingerprint_hash=fdna.fingerprint_hash,
            version=fdna.version,
            dimensions=fdna.model_dump(mode="json"),
            temporal_features=temporal.model_dump(mode="json"),
        )
        session.add(rec)

    if stage2_case is not None:
        stage2_case.status = "FINGERPRINTED"

    return manifest, diag, fdna, temporal


def process_p1_pipeline(
    session: Session,
    contract: RecoveryCaseContract,
    *,
    timeline_events: list[dict] | None = None,
    reconciliation_evidence: dict | None = None,
    worker_id: str | None = None,
) -> tuple[RecoveryGenome, DecisionProposal, ShadowEvaluation]:
    """Run full Stage 2 P1 Pipeline: P0-A..E -> Incident -> Compliance -> Genome -> Candidates -> Counterfactual -> Optimizer -> Proposal -> Shadow."""

    from .assignment import assign_experiment_case
    from .capability_matrix import generate_action_candidates
    from .compliance import evaluate_compliance_eligibility
    from .counterfactual import evaluate_counterfactual_candidates
    from .genome import assemble_recovery_genome
    from .incident_clusterer import evaluate_incident_cluster
    from .models import IncidentClusterRecord, RecoveryEligibilityRecord, RecoveryGenomeRecord
    from .optimizer import optimize_recovery_decision
    from .schemas import DecisionProposal, RecoveryGenome, ShadowEvaluation
    from .shadow import create_shadow_evaluation

    # F3 Experiment Assignment (Section 2: Assignment precedes downstream intelligence)
    try:
        assign_experiment_case(session, contract.case_id)
    except Exception as err:
        logger.warning(f"F3 Experiment Assignment fail-closed for case {contract.case_id}: {err}")

    manifest, diag, fdna, temporal = process_failure_fingerprint(
        session, contract, timeline_events=timeline_events, reconciliation_evidence=reconciliation_evidence, worker_id=worker_id
    )

    incident = evaluate_incident_cluster(fdna, temporal, manifest)
    compliance = evaluate_compliance_eligibility(manifest, diag)

    genome = assemble_recovery_genome(manifest, diag, fdna, temporal, incident, compliance)

    stage2_case = session.get(Stage2Case, (contract.case_id, contract.stage1_state_version), with_for_update=True)
    if stage2_case is not None and stage2_case.status == "STALE_SUPERSEDED":
        candidates = generate_action_candidates(genome)
        sims = evaluate_counterfactual_candidates(genome, candidates)
        prop = optimize_recovery_decision(genome, sims)
        shd = create_shadow_evaluation(genome, prop)
        return genome, prop, shd

    if incident.incident_id != "NO_INCIDENT":
        inc_rec = session.get(IncidentClusterRecord, incident.incident_id, with_for_update=True)
        if inc_rec is None:
            session.add(IncidentClusterRecord(
                incident_id=incident.incident_id,
                dimensions=incident.dimensions,
                affected_case_count=incident.affected_case_count,
                affected_volume_bucket=incident.affected_volume_bucket,
                failure_rate_delta=incident.failure_rate_delta,
                baseline_failure_rate=incident.baseline_failure_rate,
                current_failure_rate=incident.current_failure_rate,
                incident_confidence=incident.incident_confidence,
                status=incident.status,
                engine_version=incident.engine_version,
                started_at=incident.started_at,
                last_seen_at=incident.last_seen_at,
            ))

    el_id = f"el_{genome.genome_id}"
    el_rec = session.get(RecoveryEligibilityRecord, el_id, with_for_update=True)
    if el_rec is None:
        session.add(RecoveryEligibilityRecord(
            eligibility_id=el_id,
            case_id=contract.case_id,
            stage1_state_version=contract.stage1_state_version,
            eligibility=compliance.eligibility,
            attempts_remaining=compliance.attempts_remaining,
            advice_code=compliance.advice_code,
            required_delay_seconds=compliance.required_delay,
            projected_penalty=compliance.projected_penalty,
            ruleset_version=compliance.ruleset_version,
            evaluated_at=compliance.evaluated_at,
        ))

    gen_rec = session.get(RecoveryGenomeRecord, genome.genome_id, with_for_update=True)
    if gen_rec is None:
        session.add(RecoveryGenomeRecord(
            genome_id=genome.genome_id,
            case_id=contract.case_id,
            stage1_state_version=contract.stage1_state_version,
            genome_schema_version=genome.provenance.genome_schema_version,
            p0_snapshot=genome.p0_source.model_dump(mode="json"),
            p1_snapshot=genome.p1_source.model_dump(mode="json"),
            source_versions=genome.provenance.model_dump(mode="json"),
            assembled_at=genome.provenance.assembled_at,
        ))

    candidates = generate_action_candidates(genome)
    sims = evaluate_counterfactual_candidates(genome, candidates)

    proposal = optimize_recovery_decision(genome, sims)

    from .models import DecisionProposalRecord, ShadowEvaluationRecord

    prop_rec = session.get(DecisionProposalRecord, proposal.proposal_id, with_for_update=True)
    if prop_rec is None:
        session.add(DecisionProposalRecord(
            proposal_id=proposal.proposal_id,
            case_id=contract.case_id,
            genome_id=genome.genome_id,
            stage1_state_version=contract.stage1_state_version,
            selected_action=proposal.selected_action,
            predicted_success_probability=proposal.predicted_success_probability,
            expected_net_value=proposal.expected_net_value,
            data=proposal.model_dump(mode="json"),
            created_at=proposal.created_at,
        ))

    if stage2_case is not None:
        stage2_case.status = "PROPOSAL_READY"

    shadow_eval = create_shadow_evaluation(genome, proposal)

    shd_rec = session.get(ShadowEvaluationRecord, shadow_eval.shadow_id, with_for_update=True)
    if shd_rec is None:
        session.add(ShadowEvaluationRecord(
            shadow_id=shadow_eval.shadow_id,
            case_id=contract.case_id,
            genome_id=genome.genome_id,
            proposal_id=proposal.proposal_id,
            baseline_action=shadow_eval.baseline_action,
            stage2_proposed_action=shadow_eval.stage2_proposed_action,
            baseline_outcome=shadow_eval.baseline_outcome,
            would_have_recovered_amount=shadow_eval.would_have_recovered_amount,
            decision_delta=shadow_eval.decision_delta,
            created_at=shadow_eval.created_at,
        ))

    if stage2_case is not None:
        stage2_case.status = "PUBLISHED"

    return genome, proposal, shadow_eval
