"""Modelo de domínio — os TypedDicts abaixo são serializados direto para JSON."""

from __future__ import annotations

from typing import TypedDict

# Versão do formato gravado. 1 era um registro plano de 9 campos; 2 separou o
# catálogo em `static` (imutável) e `pricing` (datado); 3 acrescentou a taxa do
# EMR, o spot por AZ com estatísticas, os padrões de YARN e o bloco `derived`.
# `instance_type` ficou no topo do registro em todas, para o consumidor
# achar a chave do registro sem procurar.
SCHEMA_VERSION = 3


class SpotInfo(TypedDict):
    usd_hour: float
    az: str


class SpotAzStats(TypedDict):
    """Preço spot de uma AZ: o vigente agora e a distribuição na janela.

    As estatísticas são ponderadas pelo tempo em que cada preço esteve em vigor
    (o histórico da AWS só registra mudanças), então um preço que durou dois dias
    pesa mais que um que durou dez minutos.
    """

    az: str
    current_usd_hour: float
    window_days: int
    min_usd_hour: float
    mean_usd_hour: float
    median_usd_hour: float
    p95_usd_hour: float
    max_usd_hour: float
    stddev_usd_hour: float
    price_changes: int


class YarnDefaults(TypedDict):
    """Padrões de YARN que o EMR aplica a um tipo de instância (coluna padrão).

    Vêm da página Task configuration da documentação, que segue o release mais
    recente do EMR. A coluna "com HBase" não entra. Um cluster que sobrescreve
    `yarn-site` tem outro valor efetivo.
    """

    nodemanager_memory_mb: int
    scheduler_max_allocation_mb: int | None
    scheduler_min_allocation_mb: int | None


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
    corte bem maior e fica no bloco `emr_yarn`, porque depende do release do EMR.
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
    """Tudo que muda de um dia para o outro, sempre datado.

    `emr_fee_usd_hour` é a taxa do EMR cobrada por instância-hora além do EC2. Ela
    varia por tipo e não é proporcional ao preço do EC2. `spot` é o menor preço
    vigente entre as AZs; `spot_by_az` traz cada AZ com a distribuição na janela.
    """

    as_of: str
    on_demand_usd_hour: float | None
    emr_fee_usd_hour: float | None
    spot: SpotInfo | None
    spot_by_az: list[SpotAzStats]
    spot_interruption: SpotInterruption | None


class DerivedSpec(TypedDict):
    """Campos calculados a partir dos outros blocos, para filtrar sem aritmética.

    Nada aqui é dado novo: tudo é razão ou soma de campos de `static`, `pricing`
    e `emr_yarn`. Fica no JSON para que um consumidor (jq, pandas, um LLM) ordene
    e filtre sem refazer a conta. Qualquer entrada ausente deixa o resultado None.

    Os custos "total" somam a taxa do EMR ao preço do EC2. Para spot, a taxa é a
    de on-demand, na premissa de que o EMR não a desconta (confira na fatura).
    """

    memory_gb_per_vcpu: float | None
    memory_gb_emr_per_vcpu: float | None
    yarn_memory_gb: float | None
    yarn_memory_gb_per_vcpu: float | None
    yarn_memory_share_of_hardware: float | None
    local_disk_gb_per_vcpu: float | None
    ebs_baseline_mbps_per_vcpu: float | None
    network_baseline_gbps_per_vcpu: float | None
    total_on_demand_usd_hour: float | None
    total_spot_usd_hour: float | None
    total_spot_p95_usd_hour: float | None
    spot_discount_percent: float | None
    spot_volatility_cv: float | None
    total_spot_usd_per_vcpu_hour: float | None
    total_spot_usd_per_yarn_gb_hour: float | None
    total_spot_usd_per_normalization_unit_hour: float | None
    total_on_demand_usd_per_vcpu_hour: float | None
    total_on_demand_usd_per_yarn_gb_hour: float | None


class InstanceRecord(TypedDict):
    instance_type: str
    static: StaticSpec
    pricing: PricingSpec
    emr_yarn: YarnDefaults | None
    derived: DerivedSpec


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
