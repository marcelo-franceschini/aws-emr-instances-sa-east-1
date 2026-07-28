"""Modelo de domínio — os TypedDicts abaixo são serializados direto para JSON."""

from __future__ import annotations

from typing import TypedDict

# Versão do formato gravado. 1 era um registro plano de 9 campos; 2 separou o
# catálogo em `static` (imutável) e `pricing` (datado). `instance_type` ficou no
# topo do registro nas duas — é o que o diff da notificação compara.
SCHEMA_VERSION = 2


class SpotInfo(TypedDict):
    usd_hour: float
    az: str


class SpotInterruption(TypedDict):
    savings_percent: int | None
    interruption_rate: int | None


class PricingProduct(TypedDict):
    """O que a Price List API sabe sobre um tipo: preço e três campos de catálogo.

    Os três não são preço nem existem em nenhuma outra fonte — o EC2 só informa
    o fabricante do processador ("AWS"), não o nome comercial ("AWS Graviton4
    Processor"), e não tem noção de categoria de família nem de fator de
    normalização.
    """

    usd_hour: float
    processor_name: str | None
    family_category: str | None
    normalization_factor: float | None


class DiskSpec(TypedDict):
    count: int | None
    size_gb: int | None
    type: str | None


class StorageSpec(TypedDict):
    ebs_only: bool | None
    total_gb: int | None
    nvme: str | None
    disks: list[DiskSpec]


class EbsHardware(TypedDict):
    """Parte do bloco `ebs` que vem do EC2 — ver EbsSpec para o bloco completo."""

    baseline_mbps: int | None
    maximum_mbps: int | None
    baseline_iops: int | None
    maximum_iops: int | None
    burstable: bool | None
    nvme: str | None


class EbsSpec(EbsHardware):
    """Bloco `ebs` completo: o hardware do EC2 mais o único campo que só o EMR tem."""

    optimized_by_default: bool | None


class NetworkSpec(TypedDict):
    baseline_gbps: float | None
    peak_gbps: float | None
    burstable: bool | None
    max_interfaces: int | None
    ena: str | None
    efa: bool | None


class GpuSpec(TypedDict):
    name: str | None
    manufacturer: str | None
    count: int | None
    memory_total_gb: float | None


class HardwareSpec(TypedDict):
    """O que ec2:DescribeInstanceTypes sabe sobre um tipo de instância.

    É a maior parte do bloco `static`, mas não o bloco inteiro: memória e família
    do EMR, nome comercial do processador, categoria de família e AZs vêm de
    outras fontes e são juntados pelo collector.
    """

    vcpu: int | None
    cores: int | None
    threads_per_core: int | None
    memory_gb_hardware: float | None
    architecture: str | None
    processor_manufacturer: str | None
    clock_ghz_sustained: float | None
    current_generation: bool | None
    bare_metal: bool | None
    hypervisor: str | None
    burstable_performance: bool | None
    supports_spot: bool | None
    storage: StorageSpec
    ebs: EbsHardware
    network: NetworkSpec
    gpu: GpuSpec | None


class StaticSpec(TypedDict):
    """Tudo que não muda para um dado tipo de instância.

    Junta as quatro fontes de catálogo (EMR, EC2, ofertas por AZ e Price List) e
    pode ser congelado e versionado — só o bloco `pricing` precisa ser datado.

    Os dois campos de memória são propositalmente distintos: `memory_gb_hardware`
    é o que a máquina tem e `memory_gb_emr` é o que o EMR enxerga (menor em 352
    dos 465 tipos). Nenhum dos dois é a memória alocável pelo YARN, que tem um
    corte bem maior e não vem de API nenhuma.
    """

    vcpu: int | None
    cores: int | None
    threads_per_core: int | None
    memory_gb_emr: float | None
    memory_gb_hardware: float | None
    architecture: str | None
    processor_manufacturer: str | None
    processor_name: str | None
    clock_ghz_sustained: float | None
    family_category: str | None
    family_id_emr: str | None
    current_generation: bool | None
    bare_metal: bool | None
    hypervisor: str | None
    burstable_performance: bool | None
    normalization_factor: float | None
    supports_spot: bool | None
    availability_zones: list[str]
    storage: StorageSpec
    ebs: EbsSpec
    network: NetworkSpec
    gpu: GpuSpec | None


class PricingSpec(TypedDict):
    """Tudo que muda de um dia para o outro, sempre datado."""

    as_of: str
    on_demand_usd_hour: float | None
    spot: SpotInfo | None
    spot_interruption: SpotInterruption | None


class InstanceRecord(TypedDict):
    instance_type: str
    static: StaticSpec
    pricing: PricingSpec


class AnnouncedRelease(TypedDict):
    version: str
    url: str
    published_at: str


class Payload(TypedDict):
    region: str
    release_label: str
    schema_version: int
    latest_announced_release: AnnouncedRelease | None
    generated_at: str
    instance_count: int
    instances: list[InstanceRecord]


class SnapshotInstance(TypedDict, total=False):
    """Instância dentro de um snapshot lido de disco.

    Declara só o campo que o caminho de leitura consome — o diff compara
    conjuntos de instance_type e ignora o resto do registro.
    """

    instance_type: str


class Snapshot(TypedDict, total=False):
    """Payload lido de disco — todo campo é opcional.

    O arquivo anterior pode ser de uma versão do schema que ainda não gravava
    algum campo (foi o caso de `latest_announced_release`), ou não existir. Ler
    como `Payload` seria mentira; `total=False` diz a verdade e ainda deixa o
    mypy conferir os nomes das chaves no caminho de leitura.
    """

    region: str
    release_label: str
    schema_version: int
    latest_announced_release: AnnouncedRelease | None
    generated_at: str
    instance_count: int
    instances: list[SnapshotInstance]


class ReleaseAlert(TypedDict):
    origin: str
    previous: str
    current: str
    url: str
