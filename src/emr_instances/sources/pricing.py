"""Preço on-demand via Price List API (pricing:GetProducts, endpoint us-east-1)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from emr_instances.config import REGION
from emr_instances.models import PricingProduct

if TYPE_CHECKING:
    from mypy_boto3_pricing import PricingClient


def on_demand_prices(pricing: PricingClient) -> dict[str, PricingProduct]:
    """Mapeia {instance_type: PricingProduct} para a região inteira.

    Faz uma única varredura paginada em vez de uma chamada por instância. Além do
    preço, extrai os três atributos de catálogo que não existem em nenhuma outra
    fonte: nome comercial do processador, categoria de família e fator de
    normalização. Todo o resto do catálogo vem do EC2, que é numérico em vez de
    string.
    """
    prices: dict[str, PricingProduct] = {}
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
                    "processor_name": attrs.get("physicalProcessor"),
                    "family_category": attrs.get("instanceFamily"),
                    "normalization_factor": _parse_normalization_factor(
                        attrs.get("normalizationSizeFactor")
                    ),
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


def _parse_normalization_factor(value: str | None) -> float | None:
    """Converte o fator de normalização, que a API entrega como string.

    Devolve int quando o valor é inteiro para o JSON sair `32` em vez de `32.0`;
    os tamanhos menores são fracionários (`0.25`, `0.5`) e continuam float.
    Valores não numéricos (a API usa "NA" em alguns produtos) viram None.
    """
    if value is None:
        return None
    try:
        factor = float(value)
    except ValueError:
        return None
    return int(factor) if factor.is_integer() else factor
