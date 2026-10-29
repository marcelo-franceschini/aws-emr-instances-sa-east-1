"""Campos calculados a partir dos outros blocos do registro.

Existem para que quem consome o JSON (jq, pandas, um LLM) filtre e ordene sem
refazer aritmética. Tudo é razão ou soma de dados já presentes em `static`,
`pricing` e `emr_yarn`; nenhuma fonte externa entra aqui.
"""

from __future__ import annotations

from emr_instances.models import (
    DerivedSpec,
    PricingSpec,
    SpotAzStats,
    StaticSpec,
    YarnDefaults,
)

_MB_PER_GB = 1024


def build_derived(
    static: StaticSpec,
    pricing: PricingSpec,
    yarn: YarnDefaults | None,
) -> DerivedSpec:
    """Calcula o bloco `derived` de uma instância.

    Qualquer entrada ausente deixa None só os campos que dependem dela.
    """
    vcpu = static["vcpu"]
    yarn_gb = _div(yarn["nodemanager_memory_mb"], _MB_PER_GB, 3) if yarn else None

    emr_fee = pricing["emr_fee_usd_hour"]
    on_demand = pricing["on_demand_usd_hour"]
    spot = pricing["spot"]
    az_stats = _stats_for_cheapest_az(pricing)

    total_on_demand = _add(on_demand, emr_fee)
    total_spot = _add(spot["usd_hour"] if spot else None, emr_fee)
    total_spot_p95 = _add(az_stats["p95_usd_hour"] if az_stats else None, emr_fee)

    return {
        "memory_gb_per_vcpu": _div(static["memory_gb_hardware"], vcpu, 3),
        "memory_gb_emr_per_vcpu": _div(static["memory_gb_emr"], vcpu, 3),
        "yarn_memory_gb": yarn_gb,
        "yarn_memory_gb_per_vcpu": _div(yarn_gb, vcpu, 3),
        "yarn_memory_share_of_hardware": _div(yarn_gb, static["memory_gb_hardware"], 3),
        "local_disk_gb_per_vcpu": _local_disk_per_vcpu(static),
        "ebs_baseline_mbps_per_vcpu": _div(static["ebs"]["baseline_mbps"], vcpu, 3),
        "network_baseline_gbps_per_vcpu": _div(
            static["network"]["baseline_gbps"], vcpu, 3
        ),
        "total_on_demand_usd_hour": total_on_demand,
        "total_spot_usd_hour": total_spot,
        "total_spot_p95_usd_hour": total_spot_p95,
        "spot_discount_percent": _spot_discount(on_demand, spot["usd_hour"])
        if spot
        else None,
        "spot_volatility_cv": _volatility(az_stats),
        "total_spot_usd_per_vcpu_hour": _div(total_spot, vcpu, 6),
        "total_spot_usd_per_yarn_gb_hour": _div(total_spot, yarn_gb, 6),
        "total_spot_usd_per_normalization_unit_hour": _div(
            total_spot, static["normalization_factor"], 6
        ),
        "total_on_demand_usd_per_vcpu_hour": _div(total_on_demand, vcpu, 6),
        "total_on_demand_usd_per_yarn_gb_hour": _div(total_on_demand, yarn_gb, 6),
    }


def _div(
    numerator: float | None, denominator: float | None, digits: int
) -> float | None:
    """Razão arredondada; None se faltar um lado ou o denominador for zero."""
    if numerator is None or not denominator:
        return None
    return round(numerator / denominator, digits)


def _add(a: float | None, b: float | None) -> float | None:
    """Soma de custos; None se faltar uma das parcelas, para não subestimar."""
    if a is None or b is None:
        return None
    return round(a + b, 6)


def _local_disk_per_vcpu(static: StaticSpec) -> float | None:
    """GB de disco local por vCPU; instância EBS-only tem zero, não ausência."""
    storage = static["storage"]
    if storage["ebs_only"] is True:
        return 0.0
    return _div(storage["total_gb"], static["vcpu"], 3)


def _spot_discount(on_demand: float | None, spot: float) -> float | None:
    """Desconto do spot sobre o on-demand, só da parte do EC2, em pontos percentuais."""
    if not on_demand:
        return None
    return round((1 - spot / on_demand) * 100, 1)


def _stats_for_cheapest_az(pricing: PricingSpec) -> SpotAzStats | None:
    """Estatísticas da AZ onde o spot está mais barato agora."""
    spot = pricing["spot"]
    if spot is None:
        return None
    for stats in pricing["spot_by_az"]:
        if stats["az"] == spot["az"]:
            return stats
    return None


def _volatility(stats: SpotAzStats | None) -> float | None:
    """Coeficiente de variação (desvio sobre a média) do preço spot na janela."""
    if stats is None:
        return None
    return _div(stats["stddev_usd_hour"], stats["mean_usd_hour"], 3)
