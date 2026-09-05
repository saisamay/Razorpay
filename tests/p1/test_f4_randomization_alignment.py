from __future__ import annotations

from datetime import datetime, timezone

import pytest

from recovery_service.stage2.experiment import (
    ExperimentDesign,
    RandomizationDesign,
    compute_configuration_hash,
)
from recovery_service.stage2.f4 import (
    ArmType,
    SimulationConfig,
    SyntheticExperimentGenerator,
)


def test_1_bernoulli_count_variability():
    """Test 1: Verify Bernoulli randomization design produces variable treatment unit counts across repetitions."""
    counts = []
    for seed in range(50):
        cfg = SimulationConfig(
            scenario_name=f"bern_var_{seed}",
            population_size=1000,
            cluster_size=5,  # 200 clusters
            treatment_allocation_p=0.50,
            random_seed=seed + 100,
            randomization_design="BERNOULLI",
        )
        dataset = SyntheticExperimentGenerator.generate(cfg)
        treatment_clusters = set(
            o.assignment_unit_id for o in dataset.eligible_observations if o.arm == ArmType.TREATMENT
        )
        counts.append(len(treatment_clusters))

    assert min(counts) < 100, f"Expected min treatment count < 100, got {min(counts)}"
    assert max(counts) > 100, f"Expected max treatment count > 100, got {max(counts)}"


def test_2_allocation_probability():
    """Test 2: Across independent simulation repetitions, mean(K_t / K) is approximately equal to p."""
    proportions = []
    for seed in range(100):
        cfg = SimulationConfig(
            scenario_name=f"bern_prob_{seed}",
            population_size=1000,
            cluster_size=5,  # 200 clusters
            treatment_allocation_p=0.50,
            random_seed=seed + 500,
            randomization_design="BERNOULLI",
        )
        dataset = SyntheticExperimentGenerator.generate(cfg)
        treatment_clusters = set(
            o.assignment_unit_id for o in dataset.eligible_observations if o.arm == ArmType.TREATMENT
        )
        proportions.append(len(treatment_clusters) / 200.0)

    mean_prop = sum(proportions) / len(proportions)
    assert mean_prop == pytest.approx(0.50, abs=0.03)


def test_3_non_50_50_allocation():
    """Test 3: Non-50/50 allocation ratio (p = 0.70) yields empirical mean allocation approx 0.70."""
    proportions = []
    for seed in range(100):
        cfg = SimulationConfig(
            scenario_name=f"bern_70_{seed}",
            population_size=1000,
            cluster_size=5,  # 200 clusters
            treatment_allocation_p=0.70,
            random_seed=seed + 1000,
            randomization_design="BERNOULLI",
        )
        dataset = SyntheticExperimentGenerator.generate(cfg)
        treatment_clusters = set(
            o.assignment_unit_id for o in dataset.eligible_observations if o.arm == ArmType.TREATMENT
        )
        proportions.append(len(treatment_clusters) / 200.0)

    mean_prop = sum(proportions) / len(proportions)
    assert mean_prop == pytest.approx(0.70, abs=0.03)


def test_4_reproducibility():
    """Test 4: Same seed/configuration produces identical simulation dataset; different seed produces different assignments."""
    cfg1 = SimulationConfig(scenario_name="repr_1", population_size=500, random_seed=42, randomization_design="BERNOULLI")
    cfg2 = SimulationConfig(scenario_name="repr_2", population_size=500, random_seed=42, randomization_design="BERNOULLI")
    cfg3 = SimulationConfig(scenario_name="repr_3", population_size=500, random_seed=99, randomization_design="BERNOULLI")

    ds1 = SyntheticExperimentGenerator.generate(cfg1)
    ds2 = SyntheticExperimentGenerator.generate(cfg2)
    ds3 = SyntheticExperimentGenerator.generate(cfg3)

    # Same seed -> identical observations
    assert len(ds1.eligible_observations) == len(ds2.eligible_observations)
    for o1, o2 in zip(ds1.eligible_observations, ds2.eligible_observations):
        assert o1.case_id == o2.case_id
        assert o1.arm == o2.arm

    # Different seed -> different assignments
    ds1_arms = [o.arm for o in ds1.eligible_observations]
    ds3_arms = [o.arm for o in ds3.eligible_observations]
    assert ds1_arms != ds3_arms


def test_5_fixed_count_mode():
    """Test 5: COMPLETE_RANDOMIZATION mode fixes K_t == configured treatment count for every repetition."""
    for seed in range(20):
        cfg = SimulationConfig(
            scenario_name=f"fixed_{seed}",
            population_size=1000,
            cluster_size=5,  # 200 clusters
            treatment_allocation_p=0.50,
            random_seed=seed + 2000,
            randomization_design="COMPLETE_RANDOMIZATION",
        )
        dataset = SyntheticExperimentGenerator.generate(cfg)
        treatment_clusters = set(
            o.assignment_unit_id for o in dataset.eligible_observations if o.arm == ArmType.TREATMENT
        )
        assert len(treatment_clusters) == 100, f"Expected exactly 100 treatment clusters, got {len(treatment_clusters)}"


def test_6_configuration_controls_simulation():
    """Test 6: Changing randomization_design alters simulation assignment mechanism."""
    cfg_bern = SimulationConfig(scenario_name="cfg_b", population_size=1000, cluster_size=5, random_seed=42, randomization_design="BERNOULLI")
    cfg_comp = SimulationConfig(scenario_name="cfg_c", population_size=1000, cluster_size=5, random_seed=42, randomization_design="COMPLETE_RANDOMIZATION")

    ds_bern = SyntheticExperimentGenerator.generate(cfg_bern)
    ds_comp = SyntheticExperimentGenerator.generate(cfg_comp)

    t_bern = set(o.assignment_unit_id for o in ds_bern.eligible_observations if o.arm == ArmType.TREATMENT)
    t_comp = set(o.assignment_unit_id for o in ds_comp.eligible_observations if o.arm == ArmType.TREATMENT)

    assert t_bern != t_comp, "Expected different assignment sets between BERNOULLI and COMPLETE_RANDOMIZATION modes"


def test_7_production_simulation_allocation_ratio():
    """Test 7: Verify both production ExperimentDesign and SimulationConfig consume registered allocation_ratio."""
    now = datetime.now(timezone.utc)
    exp_dto = ExperimentDesign(
        experiment_id="exp_test_7",
        population_start_time=now,
        created_at=now,
        allocation_ratio=0.65,
        randomization_design=RandomizationDesign.BERNOULLI.value,
    )
    sim_cfg = SimulationConfig(
        scenario_name="sim_test_7",
        treatment_allocation_p=exp_dto.allocation_ratio,
        randomization_design=exp_dto.randomization_design,
    )

    assert exp_dto.allocation_ratio == sim_cfg.treatment_allocation_p == 0.65
    assert exp_dto.randomization_design == sim_cfg.randomization_design == "BERNOULLI"


def test_8_configuration_hash_mutates_with_randomization_design():
    """Test 8: Changing randomization_design BERNOULLI -> COMPLETE_RANDOMIZATION mutates compute_configuration_hash."""
    now = datetime.now(timezone.utc)
    exp1 = ExperimentDesign(
        experiment_id="exp_hash_1",
        population_start_time=now,
        created_at=now,
        allocation_ratio=0.50,
        randomization_design=RandomizationDesign.BERNOULLI.value,
    )
    exp2 = ExperimentDesign(
        experiment_id="exp_hash_1",
        population_start_time=now,
        created_at=now,
        allocation_ratio=0.50,
        randomization_design=RandomizationDesign.COMPLETE_RANDOMIZATION.value,
    )

    hash1 = compute_configuration_hash(exp1)
    hash2 = compute_configuration_hash(exp2)

    assert hash1 != hash2, "Changing randomization_design must mutate canonical configuration hash"
