"""Testes para main.py"""

from unittest.mock import MagicMock, patch

import pytest

import main


def test_version_key() -> None:
    """Test parsing de version string."""
    assert main._version_key("emr-7.13.0") == (7, 13, 0)
    assert main._version_key("emr-6.10.0") == (6, 10, 0)
    assert main._version_key("emr-7.9.1") == (7, 9, 1)
    assert main._version_key("emr-7.13.0") > main._version_key("emr-7.12.0")
    assert main._version_key("emr-7.13.0") > main._version_key("emr-6.10.0")


def test_extract_on_demand_usd_success() -> None:
    """Test extração de preço on-demand válido."""
    product: dict[str, object] = {
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {
                        "dim1": {
                            "pricePerUnit": {
                                "USD": "0.123456"
                            }
                        }
                    }
                }
            }
        }
    }
    price = main._extract_on_demand_usd(product)
    assert price == 0.123456


def test_extract_on_demand_usd_missing() -> None:
    """Test retorna None quando não há preço."""
    product: dict[str, object] = {"terms": {}}
    price = main._extract_on_demand_usd(product)
    assert price is None

    product2: dict[str, object] = {"terms": {"OnDemand": {}}}
    price2 = main._extract_on_demand_usd(product2)
    assert price2 is None


def test_build_records() -> None:
    """Test construção de records com dados fake."""
    instances = [
        {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
        {"Type": "m5.xlarge", "VCPU": 4, "MemoryGB": 16.0, "Architecture": "x86_64"},
    ]
    on_demand: dict[str, dict[str, object]] = {
        "m5.large": {"usd_hour": 0.096, "network_performance": "Up to 10 Gigabit"},
        "m5.xlarge": {"usd_hour": 0.192, "network_performance": "Up to 10 Gigabit"},
    }
    spot = {
        "m5.large": {"usd_hour": 0.048, "az": "sa-east-1a"},
        "m5.xlarge": {"usd_hour": 0.096, "az": "sa-east-1b"},
    }

    records = main.build_records(instances, on_demand, spot)
    assert len(records) == 2
    assert records[0]["instance_type"] == "m5.large"
    assert records[0]["vcpu"] == 2
    assert records[0]["memory_gb"] == 8.0
    assert records[0]["on_demand_usd_hour"] == 0.096
    assert records[0]["network_performance"] == "Up to 10 Gigabit"
    assert records[0]["spot"]["usd_hour"] == 0.048


def test_build_records_missing_price() -> None:
    """Test build_records quando falta preço."""
    instances = [
        {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
    ]
    on_demand: dict[str, dict[str, object]] = {}
    spot: dict[str, dict[str, object]] = {}

    records = main.build_records(instances, on_demand, spot)
    assert len(records) == 1
    assert records[0]["on_demand_usd_hour"] is None
    assert records[0]["network_performance"] is None
    assert records[0]["spot"] is None


def test_latest_release_label() -> None:
    """Test obtenção do release label mais recente."""
    mock_emr = MagicMock()
    mock_emr.list_release_labels.return_value = {
        "ReleaseLabels": ["emr-6.10.0", "emr-7.0.0", "emr-7.13.0"],
        "Marker": None,
    }

    result = main.latest_release_label(mock_emr)
    assert result == "emr-7.13.0"


def test_latest_release_label_paginated() -> None:
    """Test obtenção de release labels com paginação."""
    mock_emr = MagicMock()
    mock_emr.list_release_labels.side_effect = [
        {
            "ReleaseLabels": ["emr-6.10.0", "emr-7.0.0"],
            "Marker": "marker1",
        },
        {
            "ReleaseLabels": ["emr-7.13.0"],
            "Marker": None,
        },
    ]

    result = main.latest_release_label(mock_emr)
    assert result == "emr-7.13.0"
    assert mock_emr.list_release_labels.call_count == 2


def test_supported_instance_types() -> None:
    """Test obtenção de tipos de instância suportados."""
    mock_emr = MagicMock()
    mock_emr.list_supported_instance_types.return_value = {
        "SupportedInstanceTypes": [
            {"Type": "m5.large"},
            {"Type": "m5.xlarge"},
        ],
        "Marker": None,
    }

    result = main.supported_instance_types(mock_emr, "emr-7.13.0")
    assert len(result) == 2
    assert result[0]["Type"] == "m5.large"


def test_on_demand_prices() -> None:
    """Test obtenção de preços on-demand com paginação."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator

    product1: dict[str, object] = {
        "product": {
            "attributes": {
                "instanceType": "m5.large",
                "networkPerformance": "Up to 10 Gigabit"
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {
                        "dim1": {
                            "pricePerUnit": {"USD": "0.096"}
                        }
                    }
                }
            }
        }
    }
    product2: dict[str, object] = {
        "product": {
            "attributes": {
                "instanceType": "m5.xlarge",
                "networkPerformance": "Up to 10 Gigabit"
            }
        },
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {
                        "dim1": {
                            "pricePerUnit": {"USD": "0.192"}
                        }
                    }
                }
            }
        }
    }

    import json
    mock_paginator.paginate.return_value = [
        {"PriceList": [json.dumps(product1), json.dumps(product2)]}
    ]

    result = main.on_demand_prices(mock_pricing)
    assert result["m5.large"]["usd_hour"] == 0.096
    assert result["m5.large"]["network_performance"] == "Up to 10 Gigabit"
    assert result["m5.xlarge"]["usd_hour"] == 0.192
    assert result["m5.xlarge"]["network_performance"] == "Up to 10 Gigabit"


def test_spot_prices() -> None:
    """Test obtenção de preços spot (menor entre AZs)."""
    mock_ec2 = MagicMock()
    mock_paginator = MagicMock()
    mock_ec2.get_paginator.return_value = mock_paginator

    mock_paginator.paginate.return_value = [
        {
            "SpotPriceHistory": [
                {
                    "InstanceType": "m5.large",
                    "SpotPrice": "0.048",
                    "AvailabilityZone": "sa-east-1a",
                },
                {
                    "InstanceType": "m5.large",
                    "SpotPrice": "0.050",
                    "AvailabilityZone": "sa-east-1b",
                },
                {
                    "InstanceType": "m5.xlarge",
                    "SpotPrice": "0.096",
                    "AvailabilityZone": "sa-east-1a",
                },
            ]
        }
    ]

    result = main.spot_prices(mock_ec2)
    assert result["m5.large"]["usd_hour"] == 0.048
    assert result["m5.large"]["az"] == "sa-east-1a"
    assert result["m5.xlarge"]["usd_hour"] == 0.096


def test_price_ratio_calculation() -> None:
    """Test cálculo de proporção de preços faltando."""
    # Simula 100 records, 3 sem on-demand (3%)
    records = [
        {
            "instance_type": f"m5.type{i}",
            "on_demand_usd_hour": 0.1 if i < 97 else None,
            "network_performance": "Up to 10 Gigabit",
            "spot": {"usd_hour": 0.05, "az": "sa-east-1a"},
        }
        for i in range(100)
    ]

    missing_od = sum(1 for r in records if r["on_demand_usd_hour"] is None)
    ratio_od = missing_od / len(records)

    assert missing_od == 3
    assert ratio_od == 0.03
    assert ratio_od < main.MAX_MISSING_PRICE_RATIO  # 3% < 5%


def test_network_performance_extraction() -> None:
    """Test extração de network performance."""
    mock_pricing = MagicMock()
    mock_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = mock_paginator

    product_low = {
        "product": {
            "attributes": {
                "instanceType": "t3.micro",
                "networkPerformance": "Up to 5 Gigabit"
            }
        },
        "terms": {"OnDemand": {"sku.TERM1": {"priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.01"}}}}}}
    }
    product_high = {
        "product": {
            "attributes": {
                "instanceType": "m5.24xlarge",
                "networkPerformance": "25 Gigabit"
            }
        },
        "terms": {"OnDemand": {"sku.TERM1": {"priceDimensions": {"dim1": {"pricePerUnit": {"USD": "5.0"}}}}}}
    }

    import json
    mock_paginator.paginate.return_value = [
        {"PriceList": [json.dumps(product_low), json.dumps(product_high)]}
    ]

    result = main.on_demand_prices(mock_pricing)
    assert result["t3.micro"]["network_performance"] == "Up to 5 Gigabit"
    assert result["m5.24xlarge"]["network_performance"] == "25 Gigabit"


def test_price_ratio_exceeds_limit() -> None:
    """Test quando proporção de preços exceeds limite."""
    # Simula 100 records, 7 sem spot (7%)
    records = [
        {
            "instance_type": f"m5.type{i}",
            "on_demand_usd_hour": 0.1,
            "network_performance": "Up to 10 Gigabit",
            "spot": {"usd_hour": 0.05, "az": "sa-east-1a"} if i < 93 else None,
        }
        for i in range(100)
    ]

    missing_spot = sum(1 for r in records if r["spot"] is None)
    ratio_spot = missing_spot / len(records)

    assert missing_spot == 7
    assert ratio_spot == 0.07
    assert ratio_spot > main.MAX_MISSING_PRICE_RATIO  # 7% > 5%
