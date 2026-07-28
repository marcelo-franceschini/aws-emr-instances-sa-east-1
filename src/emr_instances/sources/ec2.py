"""Catálogo de hardware (ec2:DescribeInstanceTypes / DescribeInstanceTypeOfferings).

Fonte da verdade para hardware: vCPU, memória, disco, EBS, rede, clock e GPU.
Vem tudo numérico e estruturado, o que dispensa parsear as strings da Price List
API — que para disco chega a ter 93 formatos diferentes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from emr_instances.models import (
    EbsHardware,
    GpuSpec,
    HardwareSpec,
    NetworkSpec,
    StorageSpec,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_ec2.type_defs import (
        EbsInfoTypeDef,
        EbsOptimizedInfoTypeDef,
        GpuDeviceInfoTypeDef,
        InstanceStorageInfoTypeDef,
        InstanceTypeInfoTypeDef,
        NetworkCardInfoTypeDef,
        NetworkInfoTypeDef,
        ProcessorInfoTypeDef,
        VCpuInfoTypeDef,
    )

# Arquiteturas em ordem de preferência: as gerações antigas anunciam
# ["i386", "x86_64"] e o primeiro item da lista seria o rótulo errado.
_ARCHITECTURE_PRIORITY = ("arm64", "x86_64", "i386")


def instance_hardware(ec2: EC2Client) -> dict[str, HardwareSpec]:
    """Mapeia {instance_type: HardwareSpec} para a região inteira.

    Pagina sem filtro de InstanceTypes: uma varredura devolve todos os tipos
    ofertados na região e o join com o universo do EMR fica com o collector.
    Filtrar exigiria lotes de 100 e um cast, porque os stubs tipam InstanceTypes
    como Literal e os tipos vindos do EMR são str.
    """
    hardware: dict[str, HardwareSpec] = {}
    paginator = ec2.get_paginator("describe_instance_types")
    for page in paginator.paginate():
        for info in page["InstanceTypes"]:
            instance_type = info.get("InstanceType")
            if instance_type:
                hardware[instance_type] = _build_hardware(info)
    return hardware


def availability_zones(ec2: EC2Client) -> dict[str, list[str]]:
    """Mapeia {instance_type: [az, ...]} com as AZs que ofertam cada tipo.

    Nem todo tipo está nas três AZs de sa-east-1, e a AZ do menor preço spot não
    serve de resposta — ela diz onde está barato, não onde é possível subir.
    """
    zones: dict[str, set[str]] = {}
    paginator = ec2.get_paginator("describe_instance_type_offerings")
    for page in paginator.paginate(LocationType="availability-zone"):
        for offering in page["InstanceTypeOfferings"]:
            instance_type = offering.get("InstanceType")
            location = offering.get("Location")
            if instance_type and location:
                zones.setdefault(instance_type, set()).add(location)
    return {instance_type: sorted(azs) for instance_type, azs in zones.items()}


def empty_hardware() -> HardwareSpec:
    """HardwareSpec só de ausências, para o tipo que o EC2 não devolveu.

    Mantém a forma do registro uniforme — o consumidor nunca precisa distinguir
    "campo ausente" de "bloco ausente" — e deixa a falta visível para o
    validate_coverage contar.
    """
    return {
        "vcpu": None,
        "cores": None,
        "threads_per_core": None,
        "memory_gb_hardware": None,
        "architecture": None,
        "processor_manufacturer": None,
        "clock_ghz_sustained": None,
        "current_generation": None,
        "bare_metal": None,
        "hypervisor": None,
        "burstable_performance": None,
        "supports_spot": None,
        "storage": {"ebs_only": None, "total_gb": None, "nvme": None, "disks": []},
        "ebs": {
            "baseline_mbps": None,
            "maximum_mbps": None,
            "baseline_iops": None,
            "maximum_iops": None,
            "burstable": None,
            "nvme": None,
        },
        "network": {
            "baseline_gbps": None,
            "peak_gbps": None,
            "burstable": None,
            "max_interfaces": None,
            "ena": None,
            "efa": None,
        },
        "gpu": None,
    }


def _build_hardware(info: InstanceTypeInfoTypeDef) -> HardwareSpec:
    """Traduz um InstanceTypeInfo da API para o nosso HardwareSpec."""
    vcpu: VCpuInfoTypeDef = info.get("VCpuInfo", {})
    processor: ProcessorInfoTypeDef = info.get("ProcessorInfo", {})
    usage_classes = info.get("SupportedUsageClasses")
    return {
        "vcpu": vcpu.get("DefaultVCpus"),
        "cores": vcpu.get("DefaultCores"),
        "threads_per_core": vcpu.get("DefaultThreadsPerCore"),
        "memory_gb_hardware": _gib(info.get("MemoryInfo", {}).get("SizeInMiB")),
        "architecture": _architecture(processor.get("SupportedArchitectures", [])),
        "processor_manufacturer": processor.get("Manufacturer"),
        "clock_ghz_sustained": processor.get("SustainedClockSpeedInGhz"),
        "current_generation": info.get("CurrentGeneration"),
        "bare_metal": info.get("BareMetal"),
        "hypervisor": info.get("Hypervisor"),
        "burstable_performance": info.get("BurstablePerformanceSupported"),
        "supports_spot": "spot" in usage_classes if usage_classes else None,
        "storage": _build_storage(info),
        "ebs": _build_ebs(info),
        "network": _build_network(info),
        "gpu": _build_gpu(info),
    }


def _build_storage(info: InstanceTypeInfoTypeDef) -> StorageSpec:
    """Disco local. Em instância EBS-only tudo além de `ebs_only` fica vazio."""
    storage: InstanceStorageInfoTypeDef = info.get("InstanceStorageInfo", {})
    supported = info.get("InstanceStorageSupported")
    return {
        "ebs_only": not supported if supported is not None else None,
        "total_gb": storage.get("TotalSizeInGB"),
        "nvme": storage.get("NvmeSupport"),
        "disks": [
            {
                "count": disk.get("Count"),
                "size_gb": disk.get("SizeInGB"),
                "type": disk.get("Type"),
            }
            for disk in storage.get("Disks", [])
        ],
    }


def _build_ebs(info: InstanceTypeInfoTypeDef) -> EbsHardware:
    """Banda e IOPS de EBS. `optimized_by_default` não vem daqui — vem do EMR."""
    ebs: EbsInfoTypeDef = info.get("EbsInfo", {})
    optimized: EbsOptimizedInfoTypeDef = ebs.get("EbsOptimizedInfo", {})
    baseline = optimized.get("BaselineBandwidthInMbps")
    maximum = optimized.get("MaximumBandwidthInMbps")
    return {
        "baseline_mbps": baseline,
        "maximum_mbps": maximum,
        "baseline_iops": optimized.get("BaselineIops"),
        "maximum_iops": optimized.get("MaximumIops"),
        "burstable": _burstable(baseline, maximum),
        "nvme": ebs.get("NvmeSupport"),
    }


def _build_network(info: InstanceTypeInfoTypeDef) -> NetworkSpec:
    """Banda de rede da placa padrão, com baseline e pico separados."""
    network: NetworkInfoTypeDef = info.get("NetworkInfo", {})
    card = _default_network_card(network)
    baseline = card.get("BaselineBandwidthInGbps")
    peak = card.get("PeakBandwidthInGbps")
    return {
        "baseline_gbps": baseline,
        "peak_gbps": peak,
        "burstable": _burstable(baseline, peak),
        "max_interfaces": network.get("MaximumNetworkInterfaces"),
        "ena": network.get("EnaSupport"),
        "efa": network.get("EfaSupported"),
    }


def _default_network_card(network: NetworkInfoTypeDef) -> NetworkCardInfoTypeDef:
    """Placa de rede padrão da instância, ou vazia se a API não trouxe nenhuma.

    Procura o índice que a própria API declara como padrão em vez de assumir a
    primeira posição da lista.
    """
    cards = network.get("NetworkCards", [])
    default_index = network.get("DefaultNetworkCardIndex", 0)
    for card in cards:
        if card.get("NetworkCardIndex") == default_index:
            return card
    return cards[0] if cards else {}


def _build_gpu(info: InstanceTypeInfoTypeDef) -> GpuSpec | None:
    """Primeiro modelo de GPU da instância, ou None quando não tem GPU.

    `count` já é a quantidade daquele modelo; no conjunto do EMR nenhum tipo
    mistura modelos diferentes.
    """
    gpu_info = info.get("GpuInfo")
    if not gpu_info:
        return None
    gpus = gpu_info.get("Gpus", [])
    gpu: GpuDeviceInfoTypeDef = gpus[0] if gpus else {}
    return {
        "name": gpu.get("Name"),
        "manufacturer": gpu.get("Manufacturer"),
        "count": gpu.get("Count"),
        "memory_total_gb": _gib(gpu_info.get("TotalGpuMemoryInMiB")),
    }


def _architecture(architectures: Sequence[str]) -> str | None:
    """Reduz a lista de arquiteturas suportadas a um único rótulo."""
    for architecture in _ARCHITECTURE_PRIORITY:
        if architecture in architectures:
            return architecture
    return architectures[0] if architectures else None


def _burstable(baseline: float | None, maximum: float | None) -> bool | None:
    """True quando o teto supera o baseline — poupa o consumidor de comparar.

    None quando falta um dos dois: "não sei" é diferente de "não faz burst".
    """
    if baseline is None or maximum is None:
        return None
    return maximum > baseline


def _gib(mib: int | None) -> float | None:
    """Converte MiB para GiB com duas casas, preservando a ausência."""
    return round(mib / 1024, 2) if mib is not None else None
