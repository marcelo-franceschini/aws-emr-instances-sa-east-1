"""Gera um JSON com as instâncias EMR suportadas em São Paulo (sa-east-1),
incluindo preço on-demand e preço spot (Linux/UNIX).

Fontes:
- Instâncias:  emr:ListSupportedInstanceTypes
- On-demand:   pricing:GetProducts (Price List API — endpoint em us-east-1)
- Spot:        ec2:DescribeSpotPriceHistory
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

import boto3
import requests
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

REGION = "sa-east-1"
PRICING_ENDPOINT_REGION = "us-east-1"
OUTPUT_FILE = "instances_sa-east-1.json"
MAX_MISSING_PRICE_RATIO = 0.05  # 5% de preços faltando é limite de alerta/erro


# --------------------------------------------------------------------------- #
# Instâncias suportadas pelo EMR
# --------------------------------------------------------------------------- #
def latest_release_label(emr: Any) -> str:
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


def supported_instance_types(emr: Any, release_label: str) -> list[dict[str, Any]]:
    """Retorna todos os tipos de instância suportados para um release label."""
    instance_types: list[dict[str, Any]] = []
    marker = None
    while True:
        kwargs = {"ReleaseLabel": release_label}
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
def on_demand_prices(pricing: Any) -> dict[str, dict[str, Any]]:
    """Mapeia {instance_type: {preço, network_performance}} para a região inteira.

    Faz uma única varredura paginada em vez de uma chamada por instância.
    Extrai preço on-demand e network performance (ex: "Up to 10 Gigabit").
    """
    prices: dict[str, dict[str, Any]] = {}
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
            network_perf = attrs.get("networkPerformance")
            if instance_type and price is not None:
                prices[instance_type] = {
                    "usd_hour": price,
                    "network_performance": network_perf,
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


# --------------------------------------------------------------------------- #
# Preço spot (menor entre as AZs)
# --------------------------------------------------------------------------- #
def spot_prices(ec2: Any) -> dict[str, dict[str, Any]]:
    """Mapeia {instance_type: {"usd_hour": menor preço, "az": AZ}}.

    Uma única varredura pega o preço spot atual de todas as instâncias/AZs;
    fica com o menor preço entre as AZs e registra em qual AZ estava.
    """
    cheapest: dict[str, dict[str, Any]] = {}
    paginator = ec2.get_paginator("describe_spot_price_history")
    pages = paginator.paginate(
        StartTime=datetime.now(timezone.utc),  # só o preço atualmente vigente
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
def interruption_frequency(region: str) -> dict[str, dict[str, Any]]:
    """Mapeia {instance_type: {"savings": %, "interruption_rate": 1-5}}.

    Busca dados do Spot Bid Advisor (S3 público) que inclui taxa de interrupção
    (1 = <5%, 2 = 5-10%, 3 = 10-15%, 4 = 15-20%, 5 = >20%) e economia esperada.
    """
    data: dict[str, dict[str, Any]] = {}
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
def build_records(
    instances: list[dict[str, Any]],
    on_demand: dict[str, dict[str, Any]],
    spot: dict[str, dict[str, Any]],
    interruption: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for instance in sorted(instances, key=lambda i: i["Type"]):
        instance_type = instance["Type"]
        memory = instance.get("MemoryGB")
        od = on_demand.get(instance_type)
        irrupt = interruption.get(instance_type)
        records.append(
            {
                "instance_type": instance_type,
                "vcpu": instance.get("VCPU"),
                "memory_gb": round(memory, 2) if isinstance(memory, (int, float)) else None,
                "architecture": instance.get("Architecture"),
                "network_performance": od.get("network_performance") if od else None,
                "on_demand_usd_hour": od.get("usd_hour") if od else None,
                "spot": spot.get(instance_type),
                "spot_interruption": irrupt,
            }
        )
    return records


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )

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
        retry_config = Config(
            retries={"max_attempts": 5, "mode": "adaptive"}
        )
        emr = boto3.client("emr", region_name=REGION, config=retry_config)
        ec2 = boto3.client("ec2", region_name=REGION, config=retry_config)
        pricing = boto3.client(
            "pricing", region_name=PRICING_ENDPOINT_REGION, config=retry_config
        )

        release_label = args.release_label or latest_release_label(emr)
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

        records = build_records(instances, on_demand, spot, interruption)
        payload: dict[str, Any] = {
            "region": REGION,
            "release_label": release_label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "instance_count": len(records),
            "instances": records,
        }

        try:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            logger.info(f"Salvo em {args.output}")
        except OSError as e:
            logger.error(f"Erro ao escrever {args.output}: {e}")
            sys.exit(1)

        missing_od = sum(1 for r in records if r["on_demand_usd_hour"] is None)
        missing_spot = sum(1 for r in records if r["spot"] is None)
        missing_net = sum(1 for r in records if r["network_performance"] is None)
        ratio_od = missing_od / len(records) if records else 0
        ratio_spot = missing_spot / len(records) if records else 0

        logger.info(f"  sem preço on-demand:     {missing_od} ({ratio_od*100:.1f}%)")
        logger.info(f"  sem preço spot:          {missing_spot} ({ratio_spot*100:.1f}%)")
        logger.info(f"  sem network performance: {missing_net} ({missing_net/len(records)*100:.1f}%)")

        if ratio_od > MAX_MISSING_PRICE_RATIO:
            logger.error(
                f"Proporção de on-demand sem preço ({ratio_od*100:.1f}%) "
                f"excede o limite ({MAX_MISSING_PRICE_RATIO*100}%)"
            )
            sys.exit(1)

        if ratio_spot > MAX_MISSING_PRICE_RATIO:
            logger.error(
                f"Proporção de spot sem preço ({ratio_spot*100:.1f}%) "
                f"excede o limite ({MAX_MISSING_PRICE_RATIO*100}%)"
            )
            sys.exit(1)

    except (ClientError, BotoCoreError) as e:
        logger.error(f"Erro ao chamar API AWS: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
