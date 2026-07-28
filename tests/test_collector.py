"""Testes para emr_instances.collector"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from emr_instances import collector
from emr_instances.errors import CoverageError
from emr_instances.models import (
    AnnouncedRelease,
    HardwareSpec,
    InstanceRecord,
    PricingProduct,
    SpotInfo,
    SpotInterruption,
)
from emr_instances.sources.ec2 import empty_hardware

if TYPE_CHECKING:
    from mypy_boto3_emr.type_defs import SupportedInstanceTypeTypeDef

AS_OF = "2026-07-27T09:00:00+00:00"


def _hardware() -> HardwareSpec:
    """HardwareSpec preenchido, como o EC2 devolveria para r8gd.4xlarge."""
    hardware = empty_hardware()
    hardware.update(
        {
            "vcpu": 16,
            "cores": 16,
            "threads_per_core": 1,
            "memory_gb_hardware": 128.0,
            "architecture": "arm64",
            "processor_manufacturer": "AWS",
            "clock_ghz_sustained": 2.8,
            "current_generation": True,
            "bare_metal": False,
            "hypervisor": "nitro",
            "burstable_performance": False,
            "supports_spot": True,
        }
    )
    hardware["ebs"] = {
        "baseline_mbps": 5000,
        "maximum_mbps": 10000,
        "baseline_iops": 20000,
        "maximum_iops": 40000,
        "burstable": True,
        "nvme": "required",
    }
    return hardware


def _emr_instance() -> SupportedInstanceTypeTypeDef:
    """Instância como o ListSupportedInstanceTypes devolveria."""
    return {
        "Type": "r8gd.4xlarge",
        "VCPU": 16,
        "MemoryGB": 122.0,
        "Architecture": "AARCH64",
        "InstanceFamilyId": "HI_MEM_CURRENT_GEN",
        "EbsOptimizedByDefault": True,
    }


def _build_one(
    *,
    hardware: bool = True,
    product: bool = True,
    zones: bool = True,
) -> InstanceRecord:
    """Roda build_records com uma instância só, ligando/desligando cada fonte."""
    hardware_by_type: dict[str, HardwareSpec] = (
        {"r8gd.4xlarge": _hardware()} if hardware else {}
    )
    products: dict[str, PricingProduct] = (
        {
            "r8gd.4xlarge": {
                "usd_hour": 1.8616,
                "processor_name": "AWS Graviton4 Processor",
                "family_category": "Memory optimized",
                "normalization_factor": 32,
            }
        }
        if product
        else {}
    )
    zones_by_type = (
        {"r8gd.4xlarge": ["sa-east-1a", "sa-east-1b", "sa-east-1c"]} if zones else {}
    )
    spot: dict[str, SpotInfo] = {
        "r8gd.4xlarge": {"usd_hour": 1.1793, "az": "sa-east-1c"}
    }
    interruption: dict[str, SpotInterruption] = {
        "r8gd.4xlarge": {"savings_percent": 46, "interruption_rate": 4}
    }
    records = collector.build_records(
        [_emr_instance()],
        hardware_by_type,
        zones_by_type,
        products,
        spot,
        interruption,
        AS_OF,
    )
    assert len(records) == 1
    return records[0]


def test_build_records_static() -> None:
    """Test o bloco `static` juntando as quatro fontes de catálogo."""
    static = _build_one()["static"]

    # do EC2
    assert static["vcpu"] == 16
    assert static["cores"] == 16
    assert static["threads_per_core"] == 1
    assert static["memory_gb_hardware"] == 128.0
    assert static["architecture"] == "arm64"
    assert static["processor_manufacturer"] == "AWS"
    assert static["clock_ghz_sustained"] == 2.8
    assert static["current_generation"] is True
    assert static["hypervisor"] == "nitro"
    assert static["supports_spot"] is True
    # do EMR
    assert static["memory_gb_emr"] == 122.0
    assert static["family_id_emr"] == "HI_MEM_CURRENT_GEN"
    assert static["ebs"]["optimized_by_default"] is True
    # da Price List
    assert static["processor_name"] == "AWS Graviton4 Processor"
    assert static["family_category"] == "Memory optimized"
    assert static["normalization_factor"] == 32
    # das ofertas por AZ
    assert static["availability_zones"] == ["sa-east-1a", "sa-east-1b", "sa-east-1c"]


def test_build_records_guarda_as_duas_memorias() -> None:
    """EMR e EC2 discordam de memória; os dois valores ficam, com nomes distintos."""
    static = _build_one()["static"]

    assert static["memory_gb_emr"] == 122.0
    assert static["memory_gb_hardware"] == 128.0


def test_build_records_ebs_mistura_ec2_e_emr() -> None:
    """O bloco `ebs` é o hardware do EC2 mais o campo que só o EMR tem."""
    ebs = _build_one()["static"]["ebs"]

    assert ebs == {
        "baseline_mbps": 5000,
        "maximum_mbps": 10000,
        "baseline_iops": 20000,
        "maximum_iops": 40000,
        "burstable": True,
        "nvme": "required",
        "optimized_by_default": True,
    }


def test_build_records_pricing() -> None:
    """Test o bloco `pricing`, datado e com as três fontes de preço."""
    record = _build_one()

    assert record["instance_type"] == "r8gd.4xlarge"
    assert record["pricing"] == {
        "as_of": AS_OF,
        "on_demand_usd_hour": 1.8616,
        "spot": {"usd_hour": 1.1793, "az": "sa-east-1c"},
        "spot_interruption": {"savings_percent": 46, "interruption_rate": 4},
    }


def test_build_records_sem_hardware() -> None:
    """Tipo que o EC2 não devolveu mantém a forma do registro, tudo None.

    O bloco `static` continua existindo com os campos do EMR e da Price List
    preenchidos — quem consome nunca precisa checar se o bloco existe.
    """
    static = _build_one(hardware=False)["static"]

    assert static["vcpu"] is None
    assert static["memory_gb_hardware"] is None
    assert static["network"]["baseline_gbps"] is None
    assert static["storage"]["disks"] == []
    assert static["gpu"] is None
    # o que não vem do EC2 continua lá
    assert static["memory_gb_emr"] == 122.0
    assert static["processor_name"] == "AWS Graviton4 Processor"
    assert static["ebs"]["optimized_by_default"] is True


def test_build_records_sem_preco() -> None:
    """Sem produto na Price List, some o preço e os três campos de catálogo."""
    record = _build_one(product=False)

    assert record["pricing"]["on_demand_usd_hour"] is None
    assert record["static"]["processor_name"] is None
    assert record["static"]["family_category"] is None
    assert record["static"]["normalization_factor"] is None


def test_build_records_sem_ofertas() -> None:
    """Sem oferta por AZ, a lista fica vazia em vez de ausente."""
    assert _build_one(zones=False)["static"]["availability_zones"] == []


def test_build_records_universo_e_o_do_emr() -> None:
    """Tipo que a região oferta mas o EMR não suporta não entra no resultado."""
    hardware = {"r8gd.4xlarge": _hardware(), "m6in.large": _hardware()}
    records = collector.build_records(
        [_emr_instance()], hardware, {}, {}, {}, {}, AS_OF
    )

    assert [r["instance_type"] for r in records] == ["r8gd.4xlarge"]


def test_build_records_ordena_por_tipo() -> None:
    """Os registros saem ordenados por instance_type."""
    instances: list[SupportedInstanceTypeTypeDef] = [
        {"Type": "m5.xlarge"},
        {"Type": "c5.large"},
        {"Type": "m5.large"},
    ]
    records = collector.build_records(instances, {}, {}, {}, {}, {}, AS_OF)

    assert [r["instance_type"] for r in records] == [
        "c5.large",
        "m5.large",
        "m5.xlarge",
    ]


def test_build_payload() -> None:
    """O envelope carrega região, release, contagem, versão do schema e o RSS."""
    records = [_record()]
    announced: AnnouncedRelease = {
        "version": "7.13.0",
        "url": "https://docs.aws.amazon.com/x/emr-7130-release.html",
        "published_at": "Tue, 28 Apr 2026 19:00:00 GMT",
    }
    payload = collector.build_payload("emr-7.13.0", records, announced)

    assert payload["region"] == "sa-east-1"
    assert payload["release_label"] == "emr-7.13.0"
    assert payload["schema_version"] == 2
    assert payload["instance_count"] == 1
    assert payload["instances"] == records
    assert payload["latest_announced_release"] == announced
    assert payload["generated_at"].endswith("+00:00")  # sempre em UTC


def _record(*, has_od: bool = True, has_spot: bool = True) -> InstanceRecord:
    """InstanceRecord com o catálogo completo, variando só os preços."""
    record = _build_one()
    record["pricing"]["on_demand_usd_hour"] = 0.1 if has_od else None
    record["pricing"]["spot"] = (
        {"usd_hour": 0.05, "az": "sa-east-1a"} if has_spot else None
    )
    return record


def _record_com_disco(*, detalhado: bool) -> InstanceRecord:
    """Instância com disco local, com ou sem o detalhe dos discos."""
    record = _build_one()
    record["static"]["storage"] = {
        "ebs_only": False,
        "total_gb": 950 if detalhado else None,
        "nvme": "required" if detalhado else None,
        "disks": [{"count": 1, "size_gb": 950, "type": "ssd"}] if detalhado else [],
    }
    return record


def _record_ebs_only() -> InstanceRecord:
    """Instância EBS-only: não tem disco local nem deveria ter."""
    record = _build_one()
    record["static"]["storage"] = {
        "ebs_only": True,
        "total_gb": None,
        "nvme": None,
        "disks": [],
    }
    return record


def test_validate_coverage_empty_records() -> None:
    """Regressão: records vazio não deve levantar ZeroDivisionError nem abortar."""
    collector.validate_coverage([])


def test_validate_coverage_within_limit() -> None:
    """3% sem on-demand (< 5%) não aborta."""
    records = [_record(has_od=i >= 3) for i in range(100)]
    collector.validate_coverage(records)


def test_validate_coverage_exceeds_limit() -> None:
    """7% sem spot (> 5%) levanta CoverageError."""
    records = [_record(has_spot=i >= 7) for i in range(100)]
    with pytest.raises(CoverageError):
        collector.validate_coverage(records)


def test_validate_coverage_sem_hardware_aborta() -> None:
    """Join com o EC2 falhando inteiro é quebra de coleta, não ausência legítima."""
    records = [_build_one(hardware=False) for _ in range(100)]
    with pytest.raises(CoverageError):
        collector.validate_coverage(records)


def test_validate_coverage_sem_ofertas_aborta() -> None:
    """Idem para as ofertas por AZ, que cobrem 100% do universo do EMR."""
    records = [_build_one(zones=False) for _ in range(100)]
    with pytest.raises(CoverageError):
        collector.validate_coverage(records)


def test_validate_coverage_ebs_only_sem_disco_nao_e_falha() -> None:
    """Instância EBS-only não tem disco local — ausência legítima, não conta."""
    collector.validate_coverage([_record_ebs_only() for _ in range(100)])


def test_validate_coverage_disco_conta_so_quem_tem_disco() -> None:
    """As EBS-only saem do denominador em vez de mascarar a cobertura.

    Sem o predicado `applies`, as 90 EBS-only entrariam como 90% de ausência e
    derrubariam a coleta; com ele, o denominador é só as 10 que têm disco.
    """
    records = [
        *(_record_ebs_only() for _ in range(90)),
        *(_record_com_disco(detalhado=True) for _ in range(10)),
    ]
    collector.validate_coverage(records)


def test_validate_coverage_disco_ausente_em_quem_tem_disco_aborta() -> None:
    """Instância com disco local e sem o detalhe é falha de verdade."""
    records = [_record_com_disco(detalhado=i >= 7) for i in range(100)]
    with pytest.raises(CoverageError):
        collector.validate_coverage(records)


def test_validate_coverage_campos_de_diagnostico_nunca_abortam() -> None:
    """Clock, banda e nome do processador faltando são só logados.

    A própria AWS não publica esses campos para todo tipo; tratá-los como falha
    derrubaria a coleta por um dado que nunca existiu.
    """
    records = [_record() for _ in range(100)]
    for record in records:
        record["static"]["clock_ghz_sustained"] = None
        record["static"]["processor_name"] = None
        record["static"]["normalization_factor"] = None
        record["static"]["ebs"]["baseline_mbps"] = None
        record["static"]["network"]["baseline_gbps"] = None

    collector.validate_coverage(records)


def test_validate_coverage_gpu_nunca_aborta() -> None:
    """GPU não vira checagem: nada no registro diz se a instância deveria ter uma."""
    records = [_record() for _ in range(100)]
    assert all(r["static"]["gpu"] is None for r in records)

    collector.validate_coverage(records)
