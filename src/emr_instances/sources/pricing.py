"""Preço on-demand via Price List API (pricing:GetProducts, endpoint us-east-1)."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from emr_instances.config import REGION
from emr_instances.models import OnDemandInfo

if TYPE_CHECKING:
    from mypy_boto3_pricing import PricingClient


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


def parse_network_gbps(network_performance: str | None) -> float | None:
    """Extrai o valor numérico em Gbps de strings como "Up to 10 Gigabit" → 10.0.

    Retorna None para valores qualitativos ("Low", "Moderate", "High") ou ausentes.
    O prefixo "Up to" é ignorado — guardamos apenas o teto numérico.
    """
    if not network_performance:
        return None
    match = _NETWORK_GBPS_RE.search(network_performance)
    return float(match.group(1)) if match else None
