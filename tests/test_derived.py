"""Testes para emr_instances.derived"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emr_instances import collector
from emr_instances.models import (
    DerivedSpec,
    HardwareSpec,
    InstanceRecord,
    PricingProduct,
    SpotAzStats,
    YarnDefaults,
)
from emr_instances.sources.ec2 import empty_hardware

if TYPE_CHECKING:
    from mypy_boto3_emr.type_defs import SupportedInstanceTypeTypeDef

AS_OF = "2026-10-29T09:00:00+00:00"
INSTANCE = "r8gd.4xlarge"


def _hardware(*, ebs_only: bool = False, vcpu: int | None = 16) -> HardwareSpec:
    """Hardware de um r8gd.4xlarge: 16 vCPU, 128 GB, 950 GB de NVMe."""
    hardware = empty_hardware()
    hardware["vcpu"] = vcpu
    hardware["memory_gb_hardware"] = 128.0
    hardware["storage"] = {
        "ebs_only": ebs_only,
        "total_gb": None if ebs_only else 950,
        "nvme": None if ebs_only else "required",
        "disks": [] if ebs_only else [{"count": 1, "size_gb": 950, "type": "ssd"}],
    }
    hardware["ebs"] = {
        "baseline_mbps": 5000,
        "maximum_mbps": 10000,
        "baseline_iops": 20000,
        "maximum_iops": 40000,
        "burstable": True,
        "nvme": "required",
    }
    hardware["network"] = {
        "baseline_gbps": 8.0,
        "peak_gbps": 15.0,
        "burstable": True,
        "max_interfaces": 8,
        "ena": "required",
        "efa": False,
    }
    return hardware


def _stats(az: str = "sa-east-1c") -> SpotAzStats:
    """Estatística de spot de uma AZ: média 1,20, desvio 0,06 e P95 1,30."""
    return {
        "az": az,
        "az_id": None,  # o derived não usa o ID
        "current_usd_hour": 1.1793,
        "window_days": 30,
        "min_usd_hour": 1.1,
        "mean_usd_hour": 1.2,
        "median_usd_hour": 1.19,
        "p95_usd_hour": 1.3,
        "max_usd_hour": 1.4,
        "stddev_usd_hour": 0.06,
        "price_changes": 12,
    }


def _record(
    *,
    hardware: HardwareSpec | None = None,
    fee: float | None = 0.4,
    yarn: bool = True,
    spot: bool = True,
    stats_az: str = "sa-east-1c",
) -> InstanceRecord:
    """Registro completo de r8gd.4xlarge, ligando e desligando cada fonte."""
    instance: SupportedInstanceTypeTypeDef = {"Type": INSTANCE, "MemoryGB": 122.0}
    products: dict[str, PricingProduct] = {
        INSTANCE: {
            "usd_hour": 1.8616,
            "processor_name": "AWS Graviton4 Processor",
            "family_category": "Memory optimized",
            "normalization_factor": 32,
        }
    }
    yarn_defaults: dict[str, YarnDefaults] = (
        {
            INSTANCE: {
                "nodemanager_memory_mb": 114688,
                "scheduler_max_allocation_mb": 114688,
                "scheduler_min_allocation_mb": 1,
            }
        }
        if yarn
        else {}
    )
    records = collector.build_records(
        [instance],
        {INSTANCE: hardware or _hardware()},
        {},
        products,
        {INSTANCE: {"usd_hour": 1.1793, "az": "sa-east-1c", "az_id": None}}
        if spot
        else {},
        {},
        AS_OF,
        fees={INSTANCE: fee} if fee is not None else {},
        spot_stats={INSTANCE: [_stats(stats_az)]} if spot else {},
        yarn=yarn_defaults,
    )
    return records[0]


def _derived(**kwargs: object) -> DerivedSpec:
    return _record(**kwargs)["derived"]  # type: ignore[arg-type]


def test_derived_completo() -> None:
    """Com todas as fontes, cada campo é a razão ou soma esperada."""
    assert _record()["derived"] == {
        "memory_gb_per_vcpu": 8.0,  # 128 / 16
        "memory_gb_emr_per_vcpu": 7.625,  # 122 / 16
        "yarn_memory_gb": 112.0,  # 114688 / 1024
        "yarn_memory_gb_per_vcpu": 7.0,
        "yarn_memory_share_of_hardware": 0.875,  # 112 / 128
        "local_disk_gb_per_vcpu": 59.375,  # 950 / 16
        "ebs_baseline_mbps_per_vcpu": 312.5,
        "network_baseline_gbps_per_vcpu": 0.5,
        "total_on_demand_usd_hour": 2.2616,  # 1,8616 + 0,40
        "total_spot_usd_hour": 1.5793,  # 1,1793 + 0,40
        "total_spot_p95_usd_hour": 1.7,  # 1,30 + 0,40
        "spot_discount_percent": 36.7,
        "spot_volatility_cv": 0.05,  # 0,06 / 1,20
        "total_spot_usd_per_vcpu_hour": 0.098706,
        "total_spot_usd_per_yarn_gb_hour": 0.014101,
        "total_spot_usd_per_normalization_unit_hour": 0.049353,  # / 32
        "total_on_demand_usd_per_vcpu_hour": 0.14135,
        "total_on_demand_usd_per_yarn_gb_hour": 0.020193,
    }


def test_derived_sem_taxa_do_emr_nao_subestima_o_custo() -> None:
    """Sem a taxa, os custos totais ficam None em vez de sair só com o EC2.

    Um total que ignora a taxa pareceria barato e distorceria o ranking; o
    desconto do spot, que é só da parte do EC2, continua calculável.
    """
    derived = _derived(fee=None)

    assert derived["total_on_demand_usd_hour"] is None
    assert derived["total_spot_usd_hour"] is None
    assert derived["total_spot_p95_usd_hour"] is None
    assert derived["total_spot_usd_per_vcpu_hour"] is None
    assert derived["total_spot_usd_per_yarn_gb_hour"] is None
    assert derived["spot_discount_percent"] == 36.7
    assert derived["memory_gb_per_vcpu"] == 8.0


def test_derived_sem_yarn_so_perde_os_campos_de_yarn() -> None:
    """Sem os padrões de YARN, só o que depende deles fica None."""
    derived = _derived(yarn=False)

    assert derived["yarn_memory_gb"] is None
    assert derived["yarn_memory_gb_per_vcpu"] is None
    assert derived["yarn_memory_share_of_hardware"] is None
    assert derived["total_spot_usd_per_yarn_gb_hour"] is None
    assert derived["total_on_demand_usd_per_yarn_gb_hour"] is None
    # o que não depende de YARN continua
    assert derived["total_spot_usd_hour"] == 1.5793
    assert derived["total_spot_usd_per_vcpu_hour"] == 0.098706


def test_derived_sem_spot_deixa_so_os_campos_de_spot_vazios() -> None:
    """Sem spot, os custos on-demand e as razões de hardware seguem."""
    derived = _derived(spot=False)

    assert derived["total_spot_usd_hour"] is None
    assert derived["total_spot_p95_usd_hour"] is None
    assert derived["spot_discount_percent"] is None
    assert derived["spot_volatility_cv"] is None
    assert derived["total_on_demand_usd_hour"] == 2.2616


def test_derived_az_vigente_sem_estatistica() -> None:
    """Se a AZ mais barata não tem estatística, P95 e volatilidade ficam None."""
    derived = _derived(stats_az="sa-east-1a")

    assert derived["total_spot_usd_hour"] == 1.5793
    assert derived["total_spot_p95_usd_hour"] is None
    assert derived["spot_volatility_cv"] is None


def test_derived_ebs_only_tem_zero_de_disco_local() -> None:
    """Instância EBS-only não tem disco local: o valor é 0, e não ausente."""
    derived = _derived(hardware=_hardware(ebs_only=True))

    assert derived["local_disk_gb_per_vcpu"] == 0.0


def test_derived_sem_vcpu_nao_divide_por_zero() -> None:
    """vCPU ausente ou zero zera só as razões por vCPU; os totais seguem."""
    for vcpu in (None, 0):
        derived = _derived(hardware=_hardware(vcpu=vcpu))

        assert derived["memory_gb_per_vcpu"] is None
        assert derived["yarn_memory_gb_per_vcpu"] is None
        assert derived["total_spot_usd_per_vcpu_hour"] is None
        assert derived["total_spot_usd_hour"] == 1.5793
        assert derived["yarn_memory_gb"] == 112.0
