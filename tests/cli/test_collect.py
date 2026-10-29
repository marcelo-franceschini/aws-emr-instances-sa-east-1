"""Testes para emr_instances.cli.collect"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from emr_instances import collector
from emr_instances.cli import collect
from emr_instances.errors import CoverageError, EmrInstancesError, SourceFormatError
from emr_instances.sources.yarn import YARN_DOC_URL

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


class _Clock:
    """Fica no lugar do datetime do collector: o relógio parado em NOW."""

    @staticmethod
    def now(tz: tzinfo | None = None) -> datetime:
        return NOW


YARN_DOC = """**m5.large**

| Configuration option | Default value | With HBase installed |
| --- | --- | --- |
| yarn.scheduler.minimum-allocation-mb | 1 | 1 |
| yarn.scheduler.maximum-allocation-mb | 6144 | 3072 |
| yarn.nodemanager.resource.memory-mb | 6144 | 3072 |
"""


def test_main_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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

    # o client EC2 é usado por três operações distintas; cada paginator precisa
    # devolver as páginas da sua, senão uma lê a resposta da outra
    ec2_pages: dict[str, list[dict[str, object]]] = {
        "describe_spot_price_history": [
            {
                # o ID não segue a letra do nome: a AWS sorteia o par por conta
                "SpotPriceHistory": [
                    {
                        "InstanceType": "m5.large",
                        "SpotPrice": "0.048",
                        "AvailabilityZone": "sa-east-1a",
                        "AvailabilityZoneId": "sae1-az3",
                        "Timestamp": NOW - timedelta(days=2),
                    },
                    {
                        "InstanceType": "m5.large",
                        "SpotPrice": "0.050",
                        "AvailabilityZone": "sa-east-1b",
                        "AvailabilityZoneId": "sae1-az1",
                        "Timestamp": NOW - timedelta(days=2),
                    },
                ]
            }
        ],
        "describe_instance_types": [
            {
                "InstanceTypes": [
                    {
                        "InstanceType": "m5.large",
                        "VCpuInfo": {"DefaultVCpus": 2},
                        "MemoryInfo": {"SizeInMiB": 8192},
                        "ProcessorInfo": {"SupportedArchitectures": ["x86_64"]},
                        "SupportedUsageClasses": ["on-demand", "spot"],
                        "InstanceStorageSupported": False,
                    }
                ]
            }
        ],
        "describe_instance_type_offerings": [
            {
                "InstanceTypeOfferings": [
                    {"InstanceType": "m5.large", "Location": "sa-east-1a"},
                    {"InstanceType": "m5.large", "Location": "sa-east-1b"},
                ]
            }
        ],
    }

    def ec2_paginator(operation: str) -> MagicMock:
        paginator = MagicMock()
        paginator.paginate.return_value = ec2_pages[operation]
        return paginator

    mock_ec2 = MagicMock()
    mock_ec2.get_paginator.side_effect = ec2_paginator

    mock_pricing = MagicMock()
    pricing_paginator = MagicMock()
    mock_pricing.get_paginator.return_value = pricing_paginator
    emr_product = {
        "product": {"attributes": {"instanceType": "m5.large", "softwareType": "EMR"}},
        "terms": {
            "OnDemand": {
                "sku.TERM1": {
                    "priceDimensions": {"dim1": {"pricePerUnit": {"USD": "0.024"}}}
                }
            }
        },
    }
    product = {
        "product": {
            "attributes": {
                "instanceType": "m5.large",
                "physicalProcessor": "Intel Xeon Platinum 8175",
                "instanceFamily": "General purpose",
                "normalizationSizeFactor": "4",
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

    def pricing_pages(**kwargs: object) -> list[dict[str, list[str]]]:
        """O mesmo paginator atende o EC2 e o EMR; cada serviço tem a sua página."""
        offer = emr_product if kwargs["ServiceCode"] == "ElasticMapReduce" else product
        return [{"PriceList": [json.dumps(offer)]}]

    pricing_paginator.paginate.side_effect = pricing_pages

    monkeypatch.setattr(
        collect, "build_clients", lambda: (mock_emr, mock_ec2, mock_pricing)
    )

    advisor = {
        "spot_advisor": {"sa-east-1": {"Linux": {"m5.large": {"s": 50, "r": 2}}}}
    }
    advisor_response = MagicMock()
    advisor_response.json.return_value = advisor
    advisor_response.raise_for_status.return_value = None

    yarn_response = MagicMock()
    yarn_response.text = YARN_DOC
    yarn_response.raise_for_status.return_value = None

    def fake_get(url: str, **kwargs: object) -> MagicMock:
        """Roteia por URL: a coleta faz duas chamadas HTTP, em módulos distintos."""
        if url == YARN_DOC_URL:
            return yarn_response
        return advisor_response

    monkeypatch.setattr(collector, "datetime", _Clock)
    output = tmp_path / "out.json"
    # alvo global: spot e yarn chamam requests.get de módulos diferentes
    with patch("requests.get", side_effect=fake_get):
        monkeypatch.setattr(sys, "argv", ["emr-collect", "--output", str(output)])
        collect.main()

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["region"] == "sa-east-1"
    assert payload["release_label"] == "emr-7.13.0"
    assert payload["schema_version"] == 3
    assert payload["instance_count"] == 1
    assert payload["generated_at"] == NOW.isoformat()

    record = payload["instances"][0]
    assert record["instance_type"] == "m5.large"
    # o preço é datado pelo mesmo instante que fecha a janela spot
    assert record["pricing"]["as_of"] == NOW.isoformat()
    # cada campo abaixo vem de uma fonte diferente: se o encanamento de alguma
    # quebrar, o smoke test acusa
    assert record["static"]["memory_gb_emr"] == 8.0  # EMR
    assert record["static"]["vcpu"] == 2  # EC2
    assert record["static"]["availability_zones"] == ["sa-east-1a", "sa-east-1b"]
    # o ID de cada AZ vem do histórico spot, não da letra do nome
    assert record["static"]["availability_zone_ids"] == ["sae1-az1", "sae1-az3"]
    assert record["static"]["family_category"] == "General purpose"  # Price List
    assert record["pricing"]["on_demand_usd_hour"] == 0.096
    assert record["pricing"]["spot"]["usd_hour"] == 0.048
    assert record["pricing"]["spot"]["az_id"] == "sae1-az3"
    assert record["pricing"]["spot_interruption"]["interruption_rate"] == 2
    assert record["pricing"]["emr_fee_usd_hour"] == 0.024  # Price List do EMR
    assert record["pricing"]["spot_by_az"][0]["az"] == "sa-east-1a"
    assert record["pricing"]["spot_by_az"][0]["az_id"] == "sae1-az3"
    assert record["pricing"]["spot_by_az"][0]["price_changes"] == 0
    assert record["emr_yarn"]["nodemanager_memory_mb"] == 6144  # documentação
    # o derived junta tudo: spot 0,048 + taxa do EMR 0,024
    assert record["derived"]["total_spot_usd_hour"] == 0.072
    assert record["derived"]["yarn_memory_gb"] == 6.0


@pytest.mark.parametrize(
    "erro",
    [
        CoverageError("Proporção sem padrões de YARN (100.0%) excede o limite"),
        SourceFormatError("Tabela de YARN de c5.xlarge com a coluna inesperada"),
    ],
)
def test_main_erro_previsto_sai_com_codigo_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    erro: EmrInstancesError,
) -> None:
    """Cobertura baixa ou fonte com formato novo viram exit 1 sem gravar o JSON.

    É o que deixa o workflow vermelho: o passo de publicação nem roda, e a
    branch data fica com o último JSON bom.
    """

    def falha(*args: object) -> None:
        raise erro

    monkeypatch.setattr(
        collect, "build_clients", lambda: (MagicMock(), MagicMock(), MagicMock())
    )
    monkeypatch.setattr(collect, "collect_records", falha)
    output = tmp_path / "out.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["emr-collect", "--release-label", "emr-7.14.0", "--output", str(output)],
    )

    with pytest.raises(SystemExit) as exit_info:
        collect.main()

    assert exit_info.value.code == 1
    assert not output.exists()
