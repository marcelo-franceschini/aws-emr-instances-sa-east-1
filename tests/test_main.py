"""Testes para main.py"""

import json
from unittest.mock import MagicMock, patch

import pytest
import requests

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
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.123456"}}}
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


def test_parse_network_gbps() -> None:
    """Test parse de network performance para Gbps numérico."""
    assert main._parse_network_gbps("Up to 10 Gigabit") == 10.0
    assert main._parse_network_gbps("25 Gigabit") == 25.0
    assert main._parse_network_gbps("Up to 12.5 Gigabit") == 12.5
    assert main._parse_network_gbps("Moderate") is None
    assert main._parse_network_gbps("High") is None
    assert main._parse_network_gbps(None) is None


def test_build_records() -> None:
    """Test construção de records com dados fake."""
    instances = [
        {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
        {"Type": "m5.xlarge", "VCPU": 4, "MemoryGB": 16.0, "Architecture": "x86_64"},
    ]
    on_demand: dict[str, main.OnDemandInfo] = {
        "m5.large": {"usd_hour": 0.096, "network_performance": "Up to 10 Gigabit"},
        "m5.xlarge": {"usd_hour": 0.192, "network_performance": "Up to 10 Gigabit"},
    }
    spot: dict[str, main.SpotInfo] = {
        "m5.large": {"usd_hour": 0.048, "az": "sa-east-1a"},
        "m5.xlarge": {"usd_hour": 0.096, "az": "sa-east-1b"},
    }
    interruption: dict[str, main.SpotInterruption] = {
        "m5.large": {"savings_percent": 50, "interruption_rate": 2},
        "m5.xlarge": {"savings_percent": 50, "interruption_rate": 2},
    }

    records = main.build_records(instances, on_demand, spot, interruption)
    assert len(records) == 2
    assert records[0]["instance_type"] == "m5.large"
    assert records[0]["vcpu"] == 2
    assert records[0]["memory_gb"] == 8.0
    assert records[0]["on_demand_usd_hour"] == 0.096
    assert records[0]["network_performance"] == "Up to 10 Gigabit"
    assert records[0]["network_gbps"] == 10.0
    assert records[0]["spot"] is not None
    assert records[0]["spot"]["usd_hour"] == 0.048
    assert records[0]["spot_interruption"] is not None
    assert records[0]["spot_interruption"]["interruption_rate"] == 2


def test_build_records_missing_price() -> None:
    """Test build_records quando falta preço."""
    instances = [
        {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
    ]
    on_demand: dict[str, main.OnDemandInfo] = {}
    spot: dict[str, main.SpotInfo] = {}
    interruption: dict[str, main.SpotInterruption] = {}

    records = main.build_records(instances, on_demand, spot, interruption)
    assert len(records) == 1
    assert records[0]["on_demand_usd_hour"] is None
    assert records[0]["network_performance"] is None
    assert records[0]["network_gbps"] is None
    assert records[0]["spot"] is None
    assert records[0]["spot_interruption"] is None


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
        {"ReleaseLabels": ["emr-6.10.0", "emr-7.0.0"], "Marker": "marker1"},
        {"ReleaseLabels": ["emr-7.13.0"], "Marker": None},
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

    result = main.on_demand_prices(mock_pricing)
    assert result["t3.micro"]["network_performance"] == "Up to 5 Gigabit"
    assert result["m5.24xlarge"]["network_performance"] == "25 Gigabit"


def _record(
    *, has_od: bool = True, has_spot: bool = True, has_net: bool = True
) -> main.InstanceRecord:
    """Constrói um InstanceRecord de teste, com/sem cada campo opcional."""
    return {
        "instance_type": "m5.large",
        "vcpu": 2,
        "memory_gb": 8.0,
        "architecture": "x86_64",
        "network_performance": "Up to 10 Gigabit" if has_net else None,
        "network_gbps": 10.0 if has_net else None,
        "on_demand_usd_hour": 0.1 if has_od else None,
        "spot": {"usd_hour": 0.05, "az": "sa-east-1a"} if has_spot else None,
        "spot_interruption": None,
    }


def test_validate_coverage_empty_records() -> None:
    """Regressão: records vazio não deve levantar ZeroDivisionError nem abortar."""
    main.validate_coverage([])


def test_validate_coverage_within_limit() -> None:
    """3% sem on-demand (< 5%) não aborta."""
    records = [_record(has_od=i >= 3) for i in range(100)]
    main.validate_coverage(records)


def test_validate_coverage_exceeds_limit() -> None:
    """7% sem spot (> 5%) aborta com SystemExit."""
    records = [_record(has_spot=i >= 7) for i in range(100)]
    with pytest.raises(SystemExit):
        main.validate_coverage(records)


def test_validate_coverage_missing_network_never_aborts() -> None:
    """Network faltando é apenas logado — nunca é condição de falha."""
    records = [_record(has_net=False) for _ in range(100)]
    main.validate_coverage(records)


def test_interruption_frequency_success() -> None:
    """Test obtenção de frequência de interrupção do Spot Bid Advisor."""
    advisor_data = {
        "spot_advisor": {
            "sa-east-1": {
                "Linux": {
                    "m5.large": {"s": 50, "r": 2},
                    "m5.xlarge": {"s": 50, "r": 3},
                }
            }
        }
    }

    with patch("main.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = advisor_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = main.interruption_frequency("sa-east-1")
        assert len(result) == 2
        assert result["m5.large"]["interruption_rate"] == 2
        assert result["m5.large"]["savings_percent"] == 50
        assert result["m5.xlarge"]["interruption_rate"] == 3


def test_interruption_frequency_error() -> None:
    """Test quando Spot Bid Advisor fica indisponível."""
    with patch("main.requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("Connection error")

        result = main.interruption_frequency("sa-east-1")
        assert result == {}  # Retorna vazio em caso de erro
