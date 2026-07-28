"""Testes para emr_instances.sources.ec2"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from emr_instances.sources import ec2


def _instance_info(**overrides: Any) -> dict[str, Any]:
    """InstanceTypeInfo completo (r8gd.4xlarge), com sobrescrita por chave."""
    info: dict[str, Any] = {
        "InstanceType": "r8gd.4xlarge",
        "CurrentGeneration": True,
        "BareMetal": False,
        "Hypervisor": "nitro",
        "BurstablePerformanceSupported": False,
        "SupportedUsageClasses": ["on-demand", "spot"],
        "VCpuInfo": {
            "DefaultVCpus": 16,
            "DefaultCores": 16,
            "DefaultThreadsPerCore": 1,
        },
        "MemoryInfo": {"SizeInMiB": 131072},
        "ProcessorInfo": {
            "SupportedArchitectures": ["arm64"],
            "Manufacturer": "AWS",
            "SustainedClockSpeedInGhz": 2.8,
        },
        "InstanceStorageSupported": True,
        "InstanceStorageInfo": {
            "TotalSizeInGB": 950,
            "NvmeSupport": "required",
            "Disks": [{"SizeInGB": 950, "Count": 1, "Type": "ssd"}],
        },
        "EbsInfo": {
            "NvmeSupport": "required",
            "EbsOptimizedInfo": {
                "BaselineBandwidthInMbps": 5000,
                "MaximumBandwidthInMbps": 10000,
                "BaselineIops": 20000,
                "MaximumIops": 40000,
            },
        },
        "NetworkInfo": {
            "MaximumNetworkInterfaces": 8,
            "EnaSupport": "required",
            "EfaSupported": False,
            "DefaultNetworkCardIndex": 0,
            "NetworkCards": [
                {
                    "NetworkCardIndex": 0,
                    "BaselineBandwidthInGbps": 7.5,
                    "PeakBandwidthInGbps": 15.0,
                }
            ],
        },
    }
    info.update(overrides)
    return info


def _paginated(*pages: dict[str, Any]) -> MagicMock:
    """Client EC2 fake cujo paginator devolve as páginas informadas."""
    mock_ec2 = MagicMock()
    mock_paginator = MagicMock()
    mock_ec2.get_paginator.return_value = mock_paginator
    mock_paginator.paginate.return_value = list(pages)
    return mock_ec2


def test_instance_hardware() -> None:
    """Test tradução de um InstanceTypeInfo completo para HardwareSpec."""
    mock_ec2 = _paginated({"InstanceTypes": [_instance_info()]})

    result = ec2.instance_hardware(mock_ec2)
    hardware = result["r8gd.4xlarge"]

    assert hardware["vcpu"] == 16
    assert hardware["cores"] == 16
    assert hardware["threads_per_core"] == 1
    assert hardware["memory_gb_hardware"] == 128.0  # 131072 MiB
    assert hardware["architecture"] == "arm64"
    assert hardware["processor_manufacturer"] == "AWS"
    assert hardware["clock_ghz_sustained"] == 2.8
    assert hardware["current_generation"] is True
    assert hardware["bare_metal"] is False
    assert hardware["hypervisor"] == "nitro"
    assert hardware["burstable_performance"] is False
    assert hardware["supports_spot"] is True
    assert hardware["gpu"] is None


def test_instance_hardware_storage_and_network() -> None:
    """Test os blocos aninhados de disco local, EBS e rede."""
    mock_ec2 = _paginated({"InstanceTypes": [_instance_info()]})

    hardware = ec2.instance_hardware(mock_ec2)["r8gd.4xlarge"]

    assert hardware["storage"] == {
        "ebs_only": False,
        "total_gb": 950,
        "nvme": "required",
        "disks": [{"count": 1, "size_gb": 950, "type": "ssd"}],
    }
    assert hardware["ebs"] == {
        "baseline_mbps": 5000,
        "maximum_mbps": 10000,
        "baseline_iops": 20000,
        "maximum_iops": 40000,
        "burstable": True,
        "nvme": "required",
    }
    assert hardware["network"] == {
        "baseline_gbps": 7.5,
        "peak_gbps": 15.0,
        "burstable": True,
        "max_interfaces": 8,
        "ena": "required",
        "efa": False,
    }


def test_instance_hardware_ebs_only() -> None:
    """Instância sem disco local: ebs_only True e o resto do bloco vazio."""
    info = _instance_info(InstanceType="m5.large", InstanceStorageSupported=False)
    del info["InstanceStorageInfo"]
    mock_ec2 = _paginated({"InstanceTypes": [info]})

    storage = ec2.instance_hardware(mock_ec2)["m5.large"]["storage"]

    assert storage == {
        "ebs_only": True,
        "total_gb": None,
        "nvme": None,
        "disks": [],
    }


def test_instance_hardware_gpu() -> None:
    """Instância com GPU traz nome, fabricante, contagem e memória total."""
    info = _instance_info(
        InstanceType="g5.xlarge",
        GpuInfo={
            "Gpus": [{"Name": "A10G", "Manufacturer": "NVIDIA", "Count": 1}],
            "TotalGpuMemoryInMiB": 24576,
        },
    )
    mock_ec2 = _paginated({"InstanceTypes": [info]})

    gpu = ec2.instance_hardware(mock_ec2)["g5.xlarge"]["gpu"]

    assert gpu == {
        "name": "A10G",
        "manufacturer": "NVIDIA",
        "count": 1,
        "memory_total_gb": 24.0,
    }


def test_instance_hardware_campos_ausentes() -> None:
    """API sem nenhum sub-bloco não estoura: vira HardwareSpec só de None."""
    mock_ec2 = _paginated({"InstanceTypes": [{"InstanceType": "m1.small"}]})

    hardware = ec2.instance_hardware(mock_ec2)["m1.small"]

    assert hardware["vcpu"] is None
    assert hardware["memory_gb_hardware"] is None
    assert hardware["architecture"] is None
    assert hardware["supports_spot"] is None
    assert hardware["storage"]["ebs_only"] is None
    assert hardware["ebs"]["burstable"] is None
    assert hardware["network"]["baseline_gbps"] is None
    assert hardware["gpu"] is None


def test_instance_hardware_pagina() -> None:
    """Test que todas as páginas entram no resultado."""
    mock_ec2 = _paginated(
        {"InstanceTypes": [_instance_info(InstanceType="m5.large")]},
        {"InstanceTypes": [_instance_info(InstanceType="m5.xlarge")]},
    )

    result = ec2.instance_hardware(mock_ec2)

    assert set(result) == {"m5.large", "m5.xlarge"}


def test_architecture_prefere_x86_sobre_i386() -> None:
    """Geração antiga anuncia ["i386", "x86_64"]; o rótulo útil é o segundo."""
    info = _instance_info(
        InstanceType="m1.small",
        ProcessorInfo={"SupportedArchitectures": ["i386", "x86_64"]},
    )
    mock_ec2 = _paginated({"InstanceTypes": [info]})

    assert ec2.instance_hardware(mock_ec2)["m1.small"]["architecture"] == "x86_64"


def test_burstable_false_quando_teto_igual_ao_baseline() -> None:
    """Sem burst o teto é igual ao baseline — False, não None."""
    info = _instance_info(
        EbsInfo={
            "EbsOptimizedInfo": {
                "BaselineBandwidthInMbps": 10000,
                "MaximumBandwidthInMbps": 10000,
            }
        }
    )
    mock_ec2 = _paginated({"InstanceTypes": [info]})

    assert ec2.instance_hardware(mock_ec2)["r8gd.4xlarge"]["ebs"]["burstable"] is False


def test_burstable_none_quando_falta_um_dos_lados() -> None:
    """Faltando baseline ou teto, "não sei" não vira "não faz burst"."""
    info = _instance_info(
        EbsInfo={"EbsOptimizedInfo": {"BaselineBandwidthInMbps": 10000}}
    )
    mock_ec2 = _paginated({"InstanceTypes": [info]})

    assert ec2.instance_hardware(mock_ec2)["r8gd.4xlarge"]["ebs"]["burstable"] is None


def test_network_usa_indice_declarado_como_padrao() -> None:
    """A placa padrão é a do DefaultNetworkCardIndex, não a primeira da lista."""
    info = _instance_info(
        NetworkInfo={
            "DefaultNetworkCardIndex": 1,
            "NetworkCards": [
                {
                    "NetworkCardIndex": 0,
                    "BaselineBandwidthInGbps": 1.0,
                    "PeakBandwidthInGbps": 2.0,
                },
                {
                    "NetworkCardIndex": 1,
                    "BaselineBandwidthInGbps": 50.0,
                    "PeakBandwidthInGbps": 50.0,
                },
            ],
        }
    )
    mock_ec2 = _paginated({"InstanceTypes": [info]})

    network = ec2.instance_hardware(mock_ec2)["r8gd.4xlarge"]["network"]
    assert network["baseline_gbps"] == 50.0
    assert network["burstable"] is False


def test_availability_zones() -> None:
    """Test agrupamento das ofertas por instance_type, ordenado e sem repetição."""
    mock_ec2 = _paginated(
        {
            "InstanceTypeOfferings": [
                {"InstanceType": "m5.large", "Location": "sa-east-1c"},
                {"InstanceType": "m5.large", "Location": "sa-east-1a"},
                {"InstanceType": "m1.small", "Location": "sa-east-1a"},
            ]
        },
        {
            "InstanceTypeOfferings": [
                {"InstanceType": "m5.large", "Location": "sa-east-1b"},
                {"InstanceType": "m5.large", "Location": "sa-east-1a"},
            ]
        },
    )

    result = ec2.availability_zones(mock_ec2)

    assert result["m5.large"] == ["sa-east-1a", "sa-east-1b", "sa-east-1c"]
    assert result["m1.small"] == ["sa-east-1a"]


def test_availability_zones_filtra_por_availability_zone() -> None:
    """A consulta precisa pedir AZ — region seria a resposta errada."""
    mock_ec2 = _paginated({"InstanceTypeOfferings": []})

    ec2.availability_zones(mock_ec2)

    mock_ec2.get_paginator.assert_called_once_with("describe_instance_type_offerings")
    paginate = mock_ec2.get_paginator.return_value.paginate
    paginate.assert_called_once_with(LocationType="availability-zone")
