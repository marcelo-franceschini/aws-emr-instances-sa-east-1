"""Gera um JSON com as instâncias EMR suportadas em São Paulo (sa-east-1),
incluindo preço on-demand, preço spot (Linux/UNIX) e taxa de interrupção.

Fontes:
- Instâncias:  emr:ListSupportedInstanceTypes
- On-demand:   pricing:GetProducts (Price List API — endpoint em us-east-1)
- Spot:        ec2:DescribeSpotPriceHistory
- Interrupção: Spot Bid Advisor (S3 público)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_emr import EMRClient
    from mypy_boto3_emr.type_defs import SupportedInstanceTypeTypeDef
    from mypy_boto3_pricing import PricingClient

logger = logging.getLogger(__name__)

REGION = "sa-east-1"
PRICING_ENDPOINT_REGION = "us-east-1"
OUTPUT_FILE = "instances_sa-east-1.json"
MAX_MISSING_PRICE_RATIO = 0.05  # 5% de preços faltando é limite de alerta/erro


# --------------------------------------------------------------------------- #
# Modelo de domínio (serializado diretamente para JSON)
# --------------------------------------------------------------------------- #
class SpotInfo(TypedDict):
    usd_hour: float
    az: str


class SpotInterruption(TypedDict):
    savings_percent: int | None
    interruption_rate: int | None


class OnDemandInfo(TypedDict):
    usd_hour: float
    network_performance: str | None


class InstanceRecord(TypedDict):
    instance_type: str
    vcpu: int | None
    memory_gb: float | None
    architecture: str | None
    network_performance: str | None
    network_gbps: float | None
    on_demand_usd_hour: float | None
    spot: SpotInfo | None
    spot_interruption: SpotInterruption | None


class Payload(TypedDict):
    region: str
    release_label: str
    generated_at: str
    instance_count: int
    instances: list[InstanceRecord]


# --------------------------------------------------------------------------- #
# Instâncias suportadas pelo EMR
# --------------------------------------------------------------------------- #
def latest_release_label(emr: EMRClient) -> str:
    """Retorna o release label mais recente do EMR disponível na região."""
    labels: list[str] = []
    marker = None
    while True:
        kwargs: dict[str, Any] = {"Marker": marker} if marker else {}
        response = emr.list_release_labels(**kwargs)
        labels.extend(response.get("ReleaseLabels", []))
        marker = response.get("Marker")
        if not marker:
            break
    return max(labels, key=_version_key)


def _version_key(label: str) -> tuple[int, ...]:
    version = label.removeprefix("emr-")
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def supported_instance_types(
    emr: EMRClient, release_label: str
) -> list[SupportedInstanceTypeTypeDef]:
    """Retorna todos os tipos de instância suportados para um release label."""
    instance_types: list[SupportedInstanceTypeTypeDef] = []
    marker = None
    while True:
        kwargs: dict[str, Any] = {"ReleaseLabel": release_label}
        if marker:
            kwargs["Marker"] = marker
        response = emr.list_supported_instance_types(**kwargs)
        instance_types.extend(response.get("SupportedInstanceTypes", []))
        marker = response.get("Marker")
        if not marker:
            break
    return instance_types


# --------------------------------------------------------------------------- #
# Preço on-demand (Price List API)
# --------------------------------------------------------------------------- #
def on_demand_prices(pricing: PricingClient) -> dict[str, OnDemandInfo]:
    """Mapeia {instance_type: OnDemandInfo} para a região inteira.

    Faz uma única varredura paginada em vez de uma chamada por instância.
    Extrai preço on-demand e network performance (ex.: "Up to 10 Gigabit").
    """
    prices: dict[str, OnDemandInfo] = {}
    paginator = pricing.get_paginator("get_products")
    pages = paginator.paginate(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": REGION},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ],
    )
    for page in pages:
        for raw in page["PriceList"]:
            product = json.loads(raw)
            attrs = product["product"]["attributes"]
            instance_type = attrs.get("instanceType")
            price = _extract_on_demand_usd(product)
            if instance_type and price is not None:
                prices[instance_type] = {
                    "usd_hour": price,
                    "network_performance": attrs.get("networkPerformance"),
                }
    return prices


def _extract_on_demand_usd(product: dict[str, Any]) -> float | None:
    """Extrai o preço USD/hora dos termos OnDemand de um produto."""
    on_demand = product.get("terms", {}).get("OnDemand", {})
    for term in on_demand.values():
        for dimension in term.get("priceDimensions", {}).values():
            usd = dimension.get("pricePerUnit", {}).get("USD")
            if usd is not None:
                return round(float(usd), 6)
    return None


_NETWORK_GBPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*Gigabit", re.IGNORECASE)


def _parse_network_gbps(network_performance: str | None) -> float | None:
    """Extrai o valor numérico em Gbps de strings como "Up to 10 Gigabit" → 10.0.

    Retorna None para valores qualitativos ("Low", "Moderate", "High") ou ausentes.
    O prefixo "Up to" é ignorado — guardamos apenas o teto numérico.
    """
    if not network_performance:
        return None
    match = _NETWORK_GBPS_RE.search(network_performance)
    return float(match.group(1)) if match else None


# --------------------------------------------------------------------------- #
# Preço spot (menor entre as AZs)
# --------------------------------------------------------------------------- #
def spot_prices(ec2: EC2Client) -> dict[str, SpotInfo]:
    """Mapeia {instance_type: SpotInfo} com o menor preço spot entre as AZs.

    Uma única varredura pega o preço spot atual de todas as instâncias/AZs;
    fica com o menor preço entre as AZs e registra em qual AZ estava.
    """
    cheapest: dict[str, SpotInfo] = {}
    paginator = ec2.get_paginator("describe_spot_price_history")
    pages = paginator.paginate(
        StartTime=datetime.now(UTC),  # só o preço atualmente vigente
        ProductDescriptions=["Linux/UNIX"],
    )
    for page in pages:
        for entry in page["SpotPriceHistory"]:
            instance_type = entry["InstanceType"]
            price = float(entry["SpotPrice"])
            current = cheapest.get(instance_type)
            if current is None or price < current["usd_hour"]:
                cheapest[instance_type] = {
                    "usd_hour": round(price, 6),
                    "az": entry["AvailabilityZone"],
                }
    return cheapest


# --------------------------------------------------------------------------- #
# Frequência de interrupção spot (Spot Bid Advisor)
# --------------------------------------------------------------------------- #
def interruption_frequency(region: str) -> dict[str, SpotInterruption]:
    """Mapeia {instance_type: SpotInterruption} com savings e taxa de interrupção.

    Busca dados do Spot Bid Advisor (S3 público) que inclui taxa de interrupção
    (1 = <5%, 2 = 5-10%, 3 = 10-15%, 4 = 15-20%, 5 = >20%) e economia esperada.
    """
    data: dict[str, SpotInterruption] = {}
    try:
        response = requests.get(
            "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json",
            timeout=10,
        )
        response.raise_for_status()
        advisor = response.json()
        advisor_data = advisor.get("spot_advisor", {}).get(region, {}).get("Linux", {})
        for instance_type, metrics in advisor_data.items():
            data[instance_type] = {
                "savings_percent": metrics.get("s"),
                "interruption_rate": metrics.get("r"),
            }
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"Erro ao buscar dados de interrupção do Spot Bid Advisor: {e}")
    return data


# --------------------------------------------------------------------------- #
# Montagem dos registros
# --------------------------------------------------------------------------- #
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
                "network_gbps": _parse_network_gbps(network_performance),
                "on_demand_usd_hour": od["usd_hour"] if od else None,
                "spot": spot.get(instance_type),
                "spot_interruption": interruption.get(instance_type),
            }
        )
    return records


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #
def build_clients() -> tuple[EMRClient, EC2Client, PricingClient]:
    """Cria os clients boto3 com retry adaptativo compartilhado."""
    retry_config = Config(retries={"max_attempts": 5, "mode": "adaptive"})
    emr = boto3.client("emr", region_name=REGION, config=retry_config)
    ec2 = boto3.client("ec2", region_name=REGION, config=retry_config)
    pricing = boto3.client(
        "pricing", region_name=PRICING_ENDPOINT_REGION, config=retry_config
    )
    return emr, ec2, pricing


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


def build_payload(release_label: str, records: list[InstanceRecord]) -> Payload:
    """Monta o envelope final com metadados e a lista de registros."""
    return {
        "region": REGION,
        "release_label": release_label,
        "generated_at": datetime.now(UTC).isoformat(),
        "instance_count": len(records),
        "instances": records,
    }


def write_output(payload: Payload, path: str) -> None:
    """Escreve o payload como JSON UTF-8 indentado; aborta em erro de I/O."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"Salvo em {path}")
    except OSError as e:
        logger.error(f"Erro ao escrever {path}: {e}")
        sys.exit(1)


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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-label",
        help="Release label do EMR (ex.: emr-7.13.0). "
        "Se omitido, usa o mais recente disponível.",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help=f"Arquivo JSON de saída (padrão: {OUTPUT_FILE}).",
    )
    args = parser.parse_args()

    try:
        emr, ec2, pricing = build_clients()
        release_label = args.release_label or latest_release_label(emr)
        records = collect_records(emr, ec2, pricing, release_label)
        validate_coverage(records)
        write_output(build_payload(release_label, records), args.output)
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Erro ao chamar API AWS: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
