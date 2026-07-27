"""Testes para emr_instances.sources.pricing"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from emr_instances.sources import pricing


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


def test_parse_network_gbps() -> None:
    """Test parse de network performance para Gbps numérico."""
    assert pricing.parse_network_gbps("Up to 10 Gigabit") == 10.0
    assert pricing.parse_network_gbps("25 Gigabit") == 25.0
    assert pricing.parse_network_gbps("Up to 12.5 Gigabit") == 12.5
    assert pricing.parse_network_gbps("Moderate") is None
    assert pricing.parse_network_gbps("High") is None
    assert pricing.parse_network_gbps(None) is None


def test_on_demand_prices() -> None:
    """Test obtenção de preços on-demand com paginação."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator

    product1: dict[str, object] = {
        "product": {
            "attributes": {
                "instanceType": "m5.large",
                "networkPerformance": "Up to 10 Gigabit",
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.096"}}}
                }
            }
        },
    }
    product2: dict[str, object] = {
        "product": {
            "attributes": {
                "instanceType": "m5.xlarge",
                "networkPerformance": "Up to 10 Gigabit",
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.192"}}}
                }
            }
        },
    }

    mock_paginator.paginate.return_value = [
        {"PriceList": [json.dumps(product1), json.dumps(product2)]}
    ]

    result = pricing.on_demand_prices(mock_pricing)
    assert result["m5.large"]["usd_hour"] == 0.096
    assert result["m5.large"]["network_performance"] == "Up to 10 Gigabit"
    assert result["m5.xlarge"]["usd_hour"] == 0.192
    assert result["m5.xlarge"]["network_performance"] == "Up to 10 Gigabit"


def test_network_performance_extraction() -> None:
    """Test extração de network performance."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator

    product_low = {
        "product": {
            "attributes": {
                "instanceType": "t3.micro",
                "networkPerformance": "Up to 5 Gigabit",
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.01"}}}
                }
            }
        },
    }
    product_high = {
        "product": {
            "attributes": {
                "instanceType": "m5.24xlarge",
                "networkPerformance": "25 Gigabit",
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "5.0"}}}
                }
            }
        },
    }

    mock_paginator.paginate.return_value = [
        {"PriceList": [json.dumps(product_low), json.dumps(product_high)]}
    ]

    result = pricing.on_demand_prices(mock_pricing)
    assert result["t3.micro"]["network_performance"] == "Up to 5 Gigabit"
    assert result["m5.24xlarge"]["network_performance"] == "25 Gigabit"
