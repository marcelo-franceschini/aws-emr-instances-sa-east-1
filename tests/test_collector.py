"""Testes para emr_instances.collector"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from emr_instances import collector
from emr_instances.errors import CoverageError
from emr_instances.models import (
    AnnouncedRelease,
    InstanceRecord,
    OnDemandInfo,
    SpotInfo,
    SpotInterruption,
)

if TYPE_CHECKING:
    from mypy_boto3_emr.type_defs import SupportedInstanceTypeTypeDef


def test_build_records() -> None:
    """Test construção de records com dados fake."""
    instances: list[SupportedInstanceTypeTypeDef] = [
        {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
        {"Type": "m5.xlarge", "VCPU": 4, "MemoryGB": 16.0, "Architecture": "x86_64"},
    ]
    on_demand: dict[str, OnDemandInfo] = {
        "m5.large": {"usd_hour": 0.096, "network_performance": "Up to 10 Gigabit"},
        "m5.xlarge": {"usd_hour": 0.192, "network_performance": "Up to 10 Gigabit"},
    }
    spot: dict[str, SpotInfo] = {
        "m5.large": {"usd_hour": 0.048, "az": "sa-east-1a"},
        "m5.xlarge": {"usd_hour": 0.096, "az": "sa-east-1b"},
    }
    interruption: dict[str, SpotInterruption] = {
        "m5.large": {"savings_percent": 50, "interruption_rate": 2},
        "m5.xlarge": {"savings_percent": 50, "interruption_rate": 2},
    }

    records = collector.build_records(instances, on_demand, spot, interruption)
    assert len(records) == 2
    assert records[0]["instance_type"] == "m5.large"
    assert records[0]["vcpu"] == 2
    assert records[0]["memory_gb"] == 8.0
    assert records[0]["on_demand_usd_hour"] == 0.096
    assert records[0]["network_performance"] == "Up to 10 Gigabit"
    assert records[0]["network_gbps"] == 10.0
    assert records[0]["spot"] is not None
    assert records[0]["spot"]["usd_hour"] == 0.048
    assert records[0]["spot_interruption"] is not None
    assert records[0]["spot_interruption"]["interruption_rate"] == 2


def test_build_records_missing_price() -> None:
    """Test build_records quando falta preço."""
    instances: list[SupportedInstanceTypeTypeDef] = [
        {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
    ]
    on_demand: dict[str, OnDemandInfo] = {}
    spot: dict[str, SpotInfo] = {}
    interruption: dict[str, SpotInterruption] = {}

    records = collector.build_records(instances, on_demand, spot, interruption)
    assert len(records) == 1
    assert records[0]["on_demand_usd_hour"] is None
    assert records[0]["network_performance"] is None
    assert records[0]["network_gbps"] is None
    assert records[0]["spot"] is None
    assert records[0]["spot_interruption"] is None


def test_build_payload() -> None:
    """O envelope carrega região, release label, contagem e o anúncio do RSS."""
    records = [_record()]
    announced: AnnouncedRelease = {
        "version": "7.13.0",
        "url": "https://docs.aws.amazon.com/x/emr-7130-release.html",
        "published_at": "Tue, 28 Apr 2026 19:00:00 GMT",
    }
    payload = collector.build_payload("emr-7.13.0", records, announced)

    assert payload["region"] == "sa-east-1"
    assert payload["release_label"] == "emr-7.13.0"
    assert payload["instance_count"] == 1
    assert payload["instances"] == records
    assert payload["latest_announced_release"] == announced
    assert payload["generated_at"].endswith("+00:00")  # sempre em UTC


def _record(
    *, has_od: bool = True, has_spot: bool = True, has_net: bool = True
) -> InstanceRecord:
    """Constrói um InstanceRecord de teste, com/sem cada campo opcional."""
    return {
        "instance_type": "m5.large",
        "vcpu": 2,
        "memory_gb": 8.0,
        "architecture": "x86_64",
        "network_performance": "Up to 10 Gigabit" if has_net else None,
        "network_gbps": 10.0 if has_net else None,
        "on_demand_usd_hour": 0.1 if has_od else None,
        "spot": {"usd_hour": 0.05, "az": "sa-east-1a"} if has_spot else None,
        "spot_interruption": None,
    }


def test_validate_coverage_empty_records() -> None:
    """Regressão: records vazio não deve levantar ZeroDivisionError nem abortar."""
    collector.validate_coverage([])


def test_validate_coverage_within_limit() -> None:
    """3% sem on-demand (< 5%) não aborta."""
    records = [_record(has_od=i >= 3) for i in range(100)]
    collector.validate_coverage(records)


def test_validate_coverage_exceeds_limit() -> None:
    """7% sem spot (> 5%) levanta CoverageError."""
    records = [_record(has_spot=i >= 7) for i in range(100)]
    with pytest.raises(CoverageError):
        collector.validate_coverage(records)


def test_validate_coverage_missing_network_never_aborts() -> None:
    """Network faltando é apenas logado — nunca é condição de falha."""
    records = [_record(has_net=False) for _ in range(100)]
    collector.validate_coverage(records)
