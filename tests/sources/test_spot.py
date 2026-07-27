"""Testes para emr_instances.sources.spot"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import requests

from emr_instances.sources import spot


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

    result = spot.spot_prices(mock_ec2)
    assert result["m5.large"]["usd_hour"] == 0.048
    assert result["m5.large"]["az"] == "sa-east-1a"
    assert result["m5.xlarge"]["usd_hour"] == 0.096


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

    with patch("emr_instances.sources.spot.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.json.return_value = advisor_data
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = spot.interruption_frequency("sa-east-1")
        assert len(result) == 2
        assert result["m5.large"]["interruption_rate"] == 2
        assert result["m5.large"]["savings_percent"] == 50
        assert result["m5.xlarge"]["interruption_rate"] == 3


def test_interruption_frequency_error() -> None:
    """Test quando Spot Bid Advisor fica indisponível."""
    with patch("emr_instances.sources.spot.requests.get") as mock_get:
        mock_get.side_effect = requests.RequestException("Connection error")

        result = spot.interruption_frequency("sa-east-1")
        assert result == {}  # Retorna vazio em caso de erro
