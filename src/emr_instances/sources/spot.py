"""Preço spot (ec2:DescribeSpotPriceHistory) e interrupção (Spot Bid Advisor)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import requests

from emr_instances.models import SpotInfo, SpotInterruption

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client

logger = logging.getLogger(__name__)

SPOT_ADVISOR_URL = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"


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


def interruption_frequency(region: str) -> dict[str, SpotInterruption]:
    """Mapeia {instance_type: SpotInterruption} com savings e taxa de interrupção.

    Busca dados do Spot Bid Advisor (S3 público) que inclui taxa de interrupção
    (1 = <5%, 2 = 5-10%, 3 = 10-15%, 4 = 15-20%, 5 = >20%) e economia esperada.
    """
    data: dict[str, SpotInterruption] = {}
    try:
        response = requests.get(SPOT_ADVISOR_URL, timeout=10)
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
