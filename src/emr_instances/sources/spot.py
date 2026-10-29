"""Preço spot (ec2:DescribeSpotPriceHistory) e interrupção (Spot Bid Advisor)."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import requests

from emr_instances.config import SPOT_HISTORY_DAYS
from emr_instances.models import SpotAzStats, SpotInfo, SpotInterruption

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client

logger = logging.getLogger(__name__)

SPOT_ADVISOR_URL = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"

# {instance_type: {az: [(instante da mudança, preço USD/h), ...]}}, em ordem
# cronológica. A AWS só registra quando o preço muda, não amostras regulares.
SpotSeries = dict[str, dict[str, list[tuple[datetime, float]]]]


def spot_price_history(
    ec2: EC2Client,
    now: datetime | None = None,
    days: int = SPOT_HISTORY_DAYS,
) -> SpotSeries:
    """Baixa o histórico spot de todas as instâncias e AZs na janela.

    Uma única varredura paginada serve às duas saídas: o preço vigente (último
    evento de cada AZ) e as estatísticas da janela.
    """
    now = now or datetime.now(UTC)
    series: SpotSeries = {}
    paginator = ec2.get_paginator("describe_spot_price_history")
    pages = paginator.paginate(
        StartTime=now - timedelta(days=days),
        EndTime=now,
        ProductDescriptions=["Linux/UNIX"],
    )
    for page in pages:
        for entry in page["SpotPriceHistory"]:
            by_az = series.setdefault(entry["InstanceType"], {})
            by_az.setdefault(entry["AvailabilityZone"], []).append(
                (entry["Timestamp"], float(entry["SpotPrice"]))
            )
    for by_az in series.values():
        for events in by_az.values():
            events.sort(key=lambda event: event[0])
    return series


def cheapest_current(series: SpotSeries) -> dict[str, SpotInfo]:
    """Mapeia {instance_type: SpotInfo} com o menor preço vigente entre as AZs.

    O preço vigente de uma AZ é o do evento mais recente dela. Fica com o menor
    entre as AZs e registra em qual AZ estava.
    """
    cheapest: dict[str, SpotInfo] = {}
    for instance_type, by_az in series.items():
        for az, events in by_az.items():
            price = events[-1][1]
            current = cheapest.get(instance_type)
            if current is None or price < current["usd_hour"]:
                cheapest[instance_type] = {"usd_hour": round(price, 6), "az": az}
    return cheapest


def az_statistics(
    series: SpotSeries,
    now: datetime | None = None,
    days: int = SPOT_HISTORY_DAYS,
) -> dict[str, list[SpotAzStats]]:
    """Mapeia {instance_type: [SpotAzStats por AZ]}, AZs em ordem alfabética."""
    now = now or datetime.now(UTC)
    window_start = now - timedelta(days=days)
    result: dict[str, list[SpotAzStats]] = {}
    for instance_type, by_az in series.items():
        result[instance_type] = [
            _window_stats(az, events, window_start, now, days)
            for az, events in sorted(by_az.items())
        ]
    return result


def _window_stats(
    az: str,
    events: list[tuple[datetime, float]],
    window_start: datetime,
    now: datetime,
    days: int,
) -> SpotAzStats:
    """Estatísticas ponderadas pelo tempo de vigência de cada preço.

    Cada evento vale do seu instante até o próximo (o último vale até `now`).
    O trecho da janela anterior ao primeiro evento é desconhecido e fica de fora.
    Se todos os pesos forem zero (um único evento em `now`), o preço conta como
    peso 1 em vez de dividir por zero.
    """
    weighted: list[tuple[float, float]] = []  # (preço, segundos em vigor)
    for index, (timestamp, price) in enumerate(events):
        start = max(timestamp, window_start)
        end = events[index + 1][0] if index + 1 < len(events) else now
        seconds = (end - start).total_seconds()
        if seconds > 0:
            weighted.append((price, seconds))
    if not weighted:
        weighted = [(events[-1][1], 1.0)]

    total = sum(weight for _, weight in weighted)
    mean = sum(price * weight for price, weight in weighted) / total
    variance = sum(weight * (price - mean) ** 2 for price, weight in weighted) / total
    prices = [price for price, _ in weighted]
    return {
        "az": az,
        "current_usd_hour": round(events[-1][1], 6),
        "window_days": days,
        "min_usd_hour": round(min(prices), 6),
        "mean_usd_hour": round(mean, 6),
        "median_usd_hour": round(_weighted_quantile(weighted, 0.5), 6),
        "p95_usd_hour": round(_weighted_quantile(weighted, 0.95), 6),
        "max_usd_hour": round(max(prices), 6),
        "stddev_usd_hour": round(math.sqrt(variance), 6),
        "price_changes": len(events) - 1,  # o primeiro evento é o preço-base
    }


def _weighted_quantile(weighted: list[tuple[float, float]], quantile: float) -> float:
    """Menor preço cujo peso acumulado alcança a fração `quantile` do total."""
    total = sum(weight for _, weight in weighted)
    cumulative = 0.0
    for price, weight in sorted(weighted):
        cumulative += weight
        if cumulative >= quantile * total:
            return price
    return max(price for price, _ in weighted)


def interruption_frequency(region: str) -> dict[str, SpotInterruption]:
    """Mapeia {instance_type: SpotInterruption} com savings e taxa de interrupção.

    Busca dados do Spot Bid Advisor (S3 público) que inclui taxa de interrupção
    (1 = <5%, 2 = 5-10%, 3 = 10-15%, 4 = 15-20%, 5 = >20%) e economia esperada.
    """
    data: dict[str, SpotInterruption] = {}
    try:
        response = requests.get(SPOT_ADVISOR_URL, timeout=10)
        response.raise_for_status()
        advisor = response.json()
        advisor_data = advisor.get("spot_advisor", {}).get(region, {}).get("Linux", {})
        for instance_type, metrics in advisor_data.items():
            data[instance_type] = {
                "savings_percent": metrics.get("s"),
                "interruption_rate": metrics.get("r"),
            }
    except (requests.RequestException, ValueError) as e:
        logger.warning(f"Erro ao buscar dados de interrupção do Spot Bid Advisor: {e}")
    return data
