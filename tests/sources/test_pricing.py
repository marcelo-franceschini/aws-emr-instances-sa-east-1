"""Testes para emr_instances.sources.pricing"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from emr_instances.sources import pricing


def _product(instance_type: str, usd: str, **attrs: str) -> dict[str, Any]:
    """Produto da Price List API com os atributos que a coleta lê."""
    return {
        "product": {
            "attributes": {
                "instanceType": instance_type,
                "physicalProcessor": "AWS Graviton4 Processor",
                "instanceFamily": "Memory optimized",
                "normalizationSizeFactor": "32",
                **attrs,
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": usd}}}
                }
            }
        },
    }


def test_extract_on_demand_usd_success() -> None:
    """Test extração de preço on-demand válido."""
    product: dict[str, object] = {
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.123456"}}}
                }
            }
        }
    }
    price = pricing._extract_on_demand_usd(product)
    assert price == 0.123456


def test_extract_on_demand_usd_missing() -> None:
    """Test retorna None quando não há preço."""
    product: dict[str, object] = {"terms": {}}
    price = pricing._extract_on_demand_usd(product)
    assert price is None

    product2: dict[str, object] = {"terms": {"OnDemand": {}}}
    price2 = pricing._extract_on_demand_usd(product2)
    assert price2 is None


def test_on_demand_prices() -> None:
    """Test obtenção de preços on-demand com paginação."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {
            "PriceList": [
                json.dumps(_product("r8gd.4xlarge", "1.8616")),
                json.dumps(_product("r8gd.8xlarge", "3.7232")),
            ]
        }
    ]

    result = pricing.on_demand_prices(mock_pricing)
    assert result["r8gd.4xlarge"]["usd_hour"] == 1.8616
    assert result["r8gd.8xlarge"]["usd_hour"] == 3.7232


def test_on_demand_prices_atributos_de_catalogo() -> None:
    """Os três campos que só a Price List tem entram junto com o preço."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = [
        {"PriceList": [json.dumps(_product("r8gd.4xlarge", "1.8616"))]}
    ]

    product = pricing.on_demand_prices(mock_pricing)["r8gd.4xlarge"]
    assert product["processor_name"] == "AWS Graviton4 Processor"
    assert product["family_category"] == "Memory optimized"
    assert product["normalization_factor"] == 32


def test_on_demand_prices_atributos_ausentes() -> None:
    """Produto sem os atributos de catálogo ainda entra, com None nos três."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator
    product_raw: dict[str, Any] = {
        "product": {"attributes": {"instanceType": "m5.large"}},
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.096"}}}
                }
            }
        },
    }
    mock_paginator.paginate.return_value = [{"PriceList": [json.dumps(product_raw)]}]

    product = pricing.on_demand_prices(mock_pricing)["m5.large"]
    assert product["usd_hour"] == 0.096
    assert product["processor_name"] is None
    assert product["family_category"] is None
    assert product["normalization_factor"] is None


def test_parse_normalization_factor() -> None:
    """Fator inteiro sai int (JSON `32`), fracionário sai float, "NA" vira None."""
    assert pricing._parse_normalization_factor("32") == 32
    assert isinstance(pricing._parse_normalization_factor("32"), int)
    assert pricing._parse_normalization_factor("0.25") == 0.25
    assert pricing._parse_normalization_factor("NA") is None
    assert pricing._parse_normalization_factor(None) is None
