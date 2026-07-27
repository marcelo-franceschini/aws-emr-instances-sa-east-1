"""Orquestração da coleta: junta as fontes, valida a cobertura e monta o payload."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from emr_instances.config import MAX_MISSING_PRICE_RATIO, REGION
from emr_instances.models import (
    AnnouncedRelease,
    InstanceRecord,
    OnDemandInfo,
    Payload,
    SpotInfo,
    SpotInterruption,
)
from emr_instances.sources.emr import supported_instance_types
from emr_instances.sources.pricing import on_demand_prices, parse_network_gbps
from emr_instances.sources.spot import interruption_frequency, spot_prices

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_emr import EMRClient
    from mypy_boto3_pricing import PricingClient

logger = logging.getLogger(__name__)


def build_records(
    instances: Iterable[Mapping[str, Any]],
    on_demand: dict[str, OnDemandInfo],
    spot: dict[str, SpotInfo],
    interruption: dict[str, SpotInterruption],
) -> list[InstanceRecord]:
    """Combina as quatro fontes num registro por instância, ordenado por tipo."""
    records: list[InstanceRecord] = []
    for instance in sorted(instances, key=lambda i: i["Type"]):
        instance_type = instance["Type"]
        memory = instance.get("MemoryGB")
        memory_gb = round(memory, 2) if isinstance(memory, (int, float)) else None
        od = on_demand.get(instance_type)
        network_performance = od["network_performance"] if od else None
        records.append(
            {
                "instance_type": instance_type,
                "vcpu": instance.get("VCPU"),
                "memory_gb": memory_gb,
                "architecture": instance.get("Architecture"),
                "network_performance": network_performance,
                "network_gbps": parse_network_gbps(network_performance),
                "on_demand_usd_hour": od["usd_hour"] if od else None,
                "spot": spot.get(instance_type),
                "spot_interruption": interruption.get(instance_type),
            }
        )
    return records


def collect_records(
    emr: EMRClient,
    ec2: EC2Client,
    pricing: PricingClient,
    release_label: str,
) -> list[InstanceRecord]:
    """Coleta as quatro fontes e devolve os registros já combinados."""
    logger.info(f"Coletando instâncias EMR ({release_label}) em {REGION}...")
    instances = supported_instance_types(emr, release_label)
    logger.info(f"  {len(instances)} tipos de instância")

    logger.info("Coletando preços on-demand (Price List API)...")
    on_demand = on_demand_prices(pricing)
    logger.info(f"  {len(on_demand)} preços on-demand")

    logger.info("Coletando preços spot (menor entre as AZs)...")
    spot = spot_prices(ec2)
    logger.info(f"  {len(spot)} preços spot")

    logger.info("Coletando frequência de interrupção spot (Spot Bid Advisor)...")
    interruption = interruption_frequency(REGION)
    logger.info(f"  {len(interruption)} taxas de interrupção")

    return build_records(instances, on_demand, spot, interruption)


def build_payload(
    release_label: str,
    records: list[InstanceRecord],
    announced: AnnouncedRelease | None,
) -> Payload:
    """Monta o envelope final com metadados e a lista de registros."""
    return {
        "region": REGION,
        "release_label": release_label,
        "latest_announced_release": announced,
        "generated_at": datetime.now(UTC).isoformat(),
        "instance_count": len(records),
        "instances": records,
    }


# (rótulo, predicado "está faltando?", se estoura o limite é erro fatal)
_COVERAGE_CHECKS: list[tuple[str, Callable[[InstanceRecord], bool], bool]] = [
    ("preço on-demand", lambda r: r["on_demand_usd_hour"] is None, True),
    ("preço spot", lambda r: r["spot"] is None, True),
    ("network performance", lambda r: r["network_performance"] is None, False),
]


def validate_coverage(records: list[InstanceRecord]) -> None:
    """Loga a cobertura de cada campo e aborta se on-demand/spot excederem o limite."""
    for label, is_missing, enforce in _COVERAGE_CHECKS:
        missing = sum(1 for r in records if is_missing(r))
        ratio = missing / len(records) if records else 0.0
        logger.info(f"  sem {label}: {missing} ({ratio * 100:.1f}%)")
        if enforce and ratio > MAX_MISSING_PRICE_RATIO:
            logger.error(
                f"Proporção sem {label} ({ratio * 100:.1f}%) excede o "
                f"limite ({MAX_MISSING_PRICE_RATIO * 100}%)"
            )
            sys.exit(1)
