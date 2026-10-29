"""Testes para emr_instances.sources.spot"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from emr_instances.sources import spot

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def _ago(days: float) -> datetime:
    """Instante `days` dias antes de NOW."""
    return NOW - timedelta(days=days)


def _entry(
    instance_type: str, az: str, price: str, timestamp: datetime
) -> dict[str, Any]:
    """Entrada do DescribeSpotPriceHistory com os campos que a coleta lê."""
    return {
        "InstanceType": instance_type,
        "AvailabilityZone": az,
        "SpotPrice": price,
        "Timestamp": timestamp,
    }


def _ec2_with(entries: list[dict[str, Any]]) -> tuple[MagicMock, MagicMock]:
    """Client EC2 fake cujo paginator devolve as entradas numa página só."""
    mock_ec2 = MagicMock()
    paginator = MagicMock()
    mock_ec2.get_paginator.return_value = paginator
    paginator.paginate.return_value = [{"SpotPriceHistory": entries}]
    return mock_ec2, paginator


def test_spot_price_history_agrupa_por_tipo_e_az_em_ordem_cronologica() -> None:
    """As entradas chegam em ordem decrescente da API e saem ordenadas por tempo."""
    mock_ec2, _ = _ec2_with(
        [
            _entry("m5.large", "sa-east-1a", "0.060", _ago(1)),
            _entry("m5.large", "sa-east-1a", "0.048", _ago(3)),
            _entry("m5.large", "sa-east-1b", "0.050", _ago(2)),
            _entry("m5.xlarge", "sa-east-1a", "0.096", _ago(2)),
        ]
    )

    series = spot.spot_price_history(mock_ec2, now=NOW)

    assert series["m5.large"]["sa-east-1a"] == [(_ago(3), 0.048), (_ago(1), 0.060)]
    assert series["m5.large"]["sa-east-1b"] == [(_ago(2), 0.050)]
    assert series["m5.xlarge"]["sa-east-1a"] == [(_ago(2), 0.096)]


def test_spot_price_history_pede_a_janela_e_o_linux() -> None:
    """A janela vai de `days` atrás até agora, só para Linux/UNIX."""
    mock_ec2, paginator = _ec2_with([])

    spot.spot_price_history(mock_ec2, now=NOW, days=30)

    paginator.paginate.assert_called_once_with(
        StartTime=_ago(30), EndTime=NOW, ProductDescriptions=["Linux/UNIX"]
    )


def test_cheapest_current_usa_o_ultimo_preco_de_cada_az() -> None:
    """O vigente é o evento mais recente; fica a AZ mais barata agora."""
    series: spot.SpotSeries = {
        "m5.large": {
            # a AZ "a" já foi a mais barata, mas o último preço dela subiu
            "sa-east-1a": [(_ago(5), 0.040), (_ago(1), 0.060)],
            "sa-east-1b": [(_ago(2), 0.050)],
        },
        "m5.xlarge": {"sa-east-1a": [(_ago(2), 0.096)]},
    }

    result = spot.cheapest_current(series)

    assert result["m5.large"] == {"usd_hour": 0.05, "az": "sa-east-1b"}
    assert result["m5.xlarge"] == {"usd_hour": 0.096, "az": "sa-east-1a"}


def test_az_statistics_pondera_pelo_tempo_em_vigor() -> None:
    """Cada preço pesa pelo tempo que durou: 10 dias a 0,10, 5 a 0,30 e 5 a 0,20."""
    series: spot.SpotSeries = {
        "m5.large": {
            "sa-east-1a": [(_ago(20), 0.10), (_ago(10), 0.30), (_ago(5), 0.20)]
        }
    }

    stats = spot.az_statistics(series, now=NOW)["m5.large"][0]

    assert stats["az"] == "sa-east-1a"
    assert stats["current_usd_hour"] == 0.20
    assert stats["window_days"] == 30
    assert stats["price_changes"] == 2
    assert stats["min_usd_hour"] == 0.10
    assert stats["max_usd_hour"] == 0.30
    assert stats["mean_usd_hour"] == pytest.approx(0.175)
    assert stats["median_usd_hour"] == 0.10
    assert stats["p95_usd_hour"] == 0.30
    assert stats["stddev_usd_hour"] == pytest.approx(0.082916, abs=1e-6)


def test_az_statistics_recorta_o_evento_anterior_a_janela() -> None:
    """O preço que já vigorava antes da janela só conta a partir do início dela."""
    series: spot.SpotSeries = {
        "m5.large": {"sa-east-1a": [(_ago(40), 0.50), (_ago(20), 1.00)]}
    }

    stats = spot.az_statistics(series, now=NOW)["m5.large"][0]

    # 10 dias a 0,50 (de 30 a 20 dias atrás) e 20 dias a 1,00
    assert stats["mean_usd_hour"] == pytest.approx(25 / 30, abs=1e-6)


def test_az_statistics_evento_unico_agora_nao_divide_por_zero() -> None:
    """Um único evento em `now` tem peso zero; o preço vale como peso 1."""
    series: spot.SpotSeries = {"m5.large": {"sa-east-1a": [(NOW, 0.07)]}}

    stats = spot.az_statistics(series, now=NOW)["m5.large"][0]

    assert stats["mean_usd_hour"] == 0.07
    assert stats["median_usd_hour"] == 0.07
    assert stats["p95_usd_hour"] == 0.07
    assert stats["stddev_usd_hour"] == 0.0
    assert stats["price_changes"] == 0


def test_az_statistics_ordena_as_azs_por_nome() -> None:
    """A lista sai em ordem alfabética de AZ, para o JSON ser estável entre dias."""
    series: spot.SpotSeries = {
        "m5.large": {
            "sa-east-1c": [(_ago(2), 0.07)],
            "sa-east-1a": [(_ago(2), 0.05)],
            "sa-east-1b": [(_ago(2), 0.06)],
        }
    }

    stats = spot.az_statistics(series, now=NOW)["m5.large"]

    assert [s["az"] for s in stats] == ["sa-east-1a", "sa-east-1b", "sa-east-1c"]


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
