"""Testes para emr_instances.cli.collect"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from emr_instances.cli import collect
from emr_instances.config import RELEASE_NOTES_RSS


def test_main_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rss_response: Callable[[], MagicMock],
) -> None:
    """Smoke test do fio inteiro: main() com clients boto3 e HTTP mockados.

    Cobre a orquestração (build_clients → collect → validate → write) que os
    testes unitários não tocam, pegando regressões de encanamento.
    """
    mock_emr = MagicMock()
    mock_emr.list_release_labels.return_value = {
        "ReleaseLabels": ["emr-7.0.0", "emr-7.13.0"],
        "Marker": None,
    }
    mock_emr.list_supported_instance_types.return_value = {
        "SupportedInstanceTypes": [
            {"Type": "m5.large", "VCPU": 2, "MemoryGB": 8.0, "Architecture": "x86_64"},
        ],
        "Marker": None,
    }

    mock_ec2 = MagicMock()
    ec2_paginator = MagicMock()
    mock_ec2.get_paginator.return_value = ec2_paginator
    ec2_paginator.paginate.return_value = [
        {
            "SpotPriceHistory": [
                {
                    "InstanceType": "m5.large",
                    "SpotPrice": "0.048",
                    "AvailabilityZone": "sa-east-1a",
                },
            ]
        }
    ]

    mock_pricing = MagicMock()
    pricing_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = pricing_paginator
    product = {
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
    pricing_paginator.paginate.return_value = [{"PriceList": [json.dumps(product)]}]

    monkeypatch.setattr(
        collect, "build_clients", lambda: (mock_emr, mock_ec2, mock_pricing)
    )

    advisor = {
        "spot_advisor": {"sa-east-1": {"Linux": {"m5.large": {"s": 50, "r": 2}}}}
    }
    advisor_response = MagicMock()
    advisor_response.json.return_value = advisor
    advisor_response.raise_for_status.return_value = None

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        """Roteia por URL: a coleta faz duas chamadas HTTP, em módulos distintos."""
        return rss_response() if url == RELEASE_NOTES_RSS else advisor_response

    output = tmp_path / "out.json"
    # alvo global: release_notes e spot chamam requests.get de módulos diferentes
    with patch("requests.get", side_effect=fake_get):
        monkeypatch.setattr(sys, "argv", ["emr-collect", "--output", str(output)])
        collect.main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["region"] == "sa-east-1"
    assert payload["release_label"] == "emr-7.13.0"
    assert payload["instance_count"] == 1
    assert payload["latest_announced_release"]["version"] == "7.13.0"
    assert payload["latest_announced_release"]["url"].endswith("emr-7130-release.html")

    record = payload["instances"][0]
    assert record["instance_type"] == "m5.large"
    assert record["on_demand_usd_hour"] == 0.096
    assert record["network_gbps"] == 10.0
    assert record["spot"]["usd_hour"] == 0.048
    assert record["spot_interruption"]["interruption_rate"] == 2
