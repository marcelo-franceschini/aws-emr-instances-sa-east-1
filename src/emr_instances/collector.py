"""Orquestração da coleta: junta as fontes, valida a cobertura e monta o payload."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, NamedTuple

from emr_instances.config import (
    MAX_MISSING_CATALOG_RATIO,
    MAX_MISSING_PRICE_RATIO,
    REGION,
)
from emr_instances.errors import CoverageError
from emr_instances.models import (
    SCHEMA_VERSION,
    AnnouncedRelease,
    HardwareSpec,
    InstanceRecord,
    Payload,
    PricingProduct,
    SpotInfo,
    SpotInterruption,
    StaticSpec,
)
from emr_instances.sources.ec2 import (
    availability_zones,
    empty_hardware,
    instance_hardware,
)
from emr_instances.sources.emr import supported_instance_types
from emr_instances.sources.pricing import on_demand_prices
from emr_instances.sources.spot import interruption_frequency, spot_prices

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_emr import EMRClient
    from mypy_boto3_emr.type_defs import SupportedInstanceTypeTypeDef
    from mypy_boto3_pricing import PricingClient

logger = logging.getLogger(__name__)


def build_records(
    instances: Iterable[SupportedInstanceTypeTypeDef],
    hardware: dict[str, HardwareSpec],
    zones: dict[str, list[str]],
    products: dict[str, PricingProduct],
    spot: dict[str, SpotInfo],
    interruption: dict[str, SpotInterruption],
    as_of: str,
) -> list[InstanceRecord]:
    """Combina as fontes num registro por instância, ordenado por tipo.

    O universo é sempre o que o EMR devolve: as outras fontes entram por join, e
    tipo que a região oferta mas o release do EMR não suporta fica de fora.
    """
    records: list[InstanceRecord] = []
    for instance in sorted(instances, key=lambda i: i["Type"]):
        instance_type = instance["Type"]
        product = products.get(instance_type)
        records.append(
            {
                "instance_type": instance_type,
                "static": _build_static(
                    instance,
                    hardware.get(instance_type) or empty_hardware(),
                    zones.get(instance_type, []),
                    product,
                ),
                "pricing": {
                    "as_of": as_of,
                    "on_demand_usd_hour": product["usd_hour"] if product else None,
                    "spot": spot.get(instance_type),
                    "spot_interruption": interruption.get(instance_type),
                },
            }
        )
    return records


def _build_static(
    instance: SupportedInstanceTypeTypeDef,
    hardware: HardwareSpec,
    zones: list[str],
    product: PricingProduct | None,
) -> StaticSpec:
    """Monta o bloco `static` juntando EMR, EC2, ofertas por AZ e Price List.

    Onde duas fontes têm o mesmo dado, o hardware do EC2 vence — é numérico, e a
    Price List só teria a string equivalente. Do EMR vêm os três campos que só
    ele tem: a memória que o EMR enxerga, o rótulo de família e o EBS otimizado
    por padrão.
    """
    memory_emr = instance.get("MemoryGB")
    return {
        "vcpu": hardware["vcpu"],
        "cores": hardware["cores"],
        "threads_per_core": hardware["threads_per_core"],
        "memory_gb_emr": round(memory_emr, 2) if memory_emr is not None else None,
        "memory_gb_hardware": hardware["memory_gb_hardware"],
        "architecture": hardware["architecture"],
        "processor_manufacturer": hardware["processor_manufacturer"],
        "processor_name": product["processor_name"] if product else None,
        "clock_ghz_sustained": hardware["clock_ghz_sustained"],
        "family_category": product["family_category"] if product else None,
        "family_id_emr": instance.get("InstanceFamilyId"),
        "current_generation": hardware["current_generation"],
        "bare_metal": hardware["bare_metal"],
        "hypervisor": hardware["hypervisor"],
        "burstable_performance": hardware["burstable_performance"],
        "normalization_factor": product["normalization_factor"] if product else None,
        "supports_spot": hardware["supports_spot"],
        "availability_zones": zones,
        "storage": hardware["storage"],
        "ebs": {
            "baseline_mbps": hardware["ebs"]["baseline_mbps"],
            "maximum_mbps": hardware["ebs"]["maximum_mbps"],
            "baseline_iops": hardware["ebs"]["baseline_iops"],
            "maximum_iops": hardware["ebs"]["maximum_iops"],
            "burstable": hardware["ebs"]["burstable"],
            "nvme": hardware["ebs"]["nvme"],
            "optimized_by_default": instance.get("EbsOptimizedByDefault"),
        },
        "network": hardware["network"],
        "gpu": hardware["gpu"],
    }


def collect_records(
    emr: EMRClient,
    ec2: EC2Client,
    pricing: PricingClient,
    release_label: str,
) -> list[InstanceRecord]:
    """Coleta todas as fontes e devolve os registros já combinados."""
    logger.info(f"Coletando instâncias EMR ({release_label}) em {REGION}...")
    instances = supported_instance_types(emr, release_label)
    logger.info(f"  {len(instances)} tipos de instância")

    logger.info("Coletando catálogo de hardware (ec2:DescribeInstanceTypes)...")
    hardware = instance_hardware(ec2)
    logger.info(f"  {len(hardware)} tipos no catálogo da região")

    logger.info("Coletando ofertas por AZ (ec2:DescribeInstanceTypeOfferings)...")
    zones = availability_zones(ec2)
    logger.info(f"  {len(zones)} tipos ofertados em pelo menos uma AZ")

    logger.info("Coletando preços on-demand (Price List API)...")
    products = on_demand_prices(pricing)
    logger.info(f"  {len(products)} preços on-demand")

    logger.info("Coletando preços spot (menor entre as AZs)...")
    spot = spot_prices(ec2)
    logger.info(f"  {len(spot)} preços spot")

    logger.info("Coletando frequência de interrupção spot (Spot Bid Advisor)...")
    interruption = interruption_frequency(REGION)
    logger.info(f"  {len(interruption)} taxas de interrupção")

    return build_records(
        instances, hardware, zones, products, spot, interruption, _utc_now()
    )


def build_payload(
    release_label: str,
    records: list[InstanceRecord],
    announced: AnnouncedRelease | None,
) -> Payload:
    """Monta o envelope final com metadados e a lista de registros."""
    return {
        "region": REGION,
        "release_label": release_label,
        "schema_version": SCHEMA_VERSION,
        "latest_announced_release": announced,
        "generated_at": _utc_now(),
        "instance_count": len(records),
        "instances": records,
    }


def _utc_now() -> str:
    """Instante atual em UTC, no formato ISO 8601."""
    return datetime.now(UTC).isoformat()


class _Check(NamedTuple):
    """Uma checagem de cobertura sobre um campo do registro.

    `applies` existe porque nem toda ausência é falha: disco local não existe em
    instância EBS-only. Sem ele, 250 instâncias sem disco entrariam na conta e
    esconderiam uma quebra real da fonte.
    """

    label: str
    applies: Callable[[InstanceRecord], bool]
    is_missing: Callable[[InstanceRecord], bool]
    max_missing_ratio: float | None  # None = só loga, nunca aborta


def _always(record: InstanceRecord) -> bool:
    """Campo que se aplica a todo registro."""
    return True


def _has_local_disk(record: InstanceRecord) -> bool:
    """Só instância com disco local pode ter detalhe de disco."""
    return record["static"]["storage"]["ebs_only"] is False


_COVERAGE_CHECKS: list[_Check] = [
    _Check(
        "preço on-demand",
        _always,
        lambda r: r["pricing"]["on_demand_usd_hour"] is None,
        MAX_MISSING_PRICE_RATIO,
    ),
    _Check(
        "preço spot",
        _always,
        lambda r: r["pricing"]["spot"] is None,
        MAX_MISSING_PRICE_RATIO,
    ),
    _Check(
        "hardware do EC2",
        _always,
        lambda r: r["static"]["vcpu"] is None,
        MAX_MISSING_CATALOG_RATIO,
    ),
    _Check(
        "oferta por AZ",
        _always,
        lambda r: not r["static"]["availability_zones"],
        MAX_MISSING_CATALOG_RATIO,
    ),
    _Check(
        "detalhe de disco local",
        _has_local_disk,
        lambda r: not r["static"]["storage"]["disks"],
        MAX_MISSING_CATALOG_RATIO,
    ),
    # Daqui para baixo é só diagnóstico: a própria AWS não publica esses campos
    # para todo tipo (clock e banda de EBS faltam em algumas dezenas), então
    # ausência aqui não é sinal de coleta quebrada.
    _Check(
        "clock sustentado",
        _always,
        lambda r: r["static"]["clock_ghz_sustained"] is None,
        None,
    ),
    _Check(
        "banda de EBS",
        _always,
        lambda r: r["static"]["ebs"]["baseline_mbps"] is None,
        None,
    ),
    _Check(
        "banda de rede",
        _always,
        lambda r: r["static"]["network"]["baseline_gbps"] is None,
        None,
    ),
    _Check(
        "nome do processador",
        _always,
        lambda r: r["static"]["processor_name"] is None,
        None,
    ),
    _Check(
        "fator de normalização",
        _always,
        lambda r: r["static"]["normalization_factor"] is None,
        None,
    ),
]

# Campos cuja ausência é legítima e indistinguível de falha — nada no registro
# diz se a instância *deveria* ter GPU. Não dá para checar cobertura; o que dá é
# contar quantas têm, e comparar com o esperado a olho no log.
_COVERAGE_COUNTS: list[tuple[str, Callable[[InstanceRecord], bool]]] = [
    ("com GPU", lambda r: r["static"]["gpu"] is not None),
    ("com disco local", _has_local_disk),
    ("com burst de EBS", lambda r: r["static"]["ebs"]["burstable"] is True),
    ("com burst de rede", lambda r: r["static"]["network"]["burstable"] is True),
]


def validate_coverage(records: list[InstanceRecord]) -> None:
    """Loga a cobertura campo a campo e aborta se uma fonte essencial falhou.

    A razão é calculada só sobre os registros a que o campo se aplica, para que
    ausência legítima não mascare quebra de coleta. Quem decide o código de
    saída é o CLI.
    """
    for check in _COVERAGE_CHECKS:
        applicable = [r for r in records if check.applies(r)]
        if not applicable:
            continue
        missing = sum(1 for r in applicable if check.is_missing(r))
        ratio = missing / len(applicable)
        logger.info(
            f"  sem {check.label}: {missing}/{len(applicable)} ({ratio * 100:.1f}%)"
        )
        limit = check.max_missing_ratio
        if limit is not None and ratio > limit:
            raise CoverageError(
                f"Proporção sem {check.label} ({ratio * 100:.1f}%) excede o "
                f"limite ({limit * 100}%)"
            )

    for label, has_field in _COVERAGE_COUNTS:
        logger.info(f"  {label}: {sum(1 for r in records if has_field(r))}")
