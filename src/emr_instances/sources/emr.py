"""Instâncias suportadas pelo EMR (emr:ListSupportedInstanceTypes)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_emr import EMRClient
    from mypy_boto3_emr.type_defs import SupportedInstanceTypeTypeDef


def latest_release_label(emr: EMRClient) -> str:
    """Retorna o release label mais recente do EMR disponível na região."""
    labels: list[str] = []
    marker = None
    while True:
        kwargs: dict[str, Any] = {"Marker": marker} if marker else {}
        response = emr.list_release_labels(**kwargs)
        labels.extend(response.get("ReleaseLabels", []))
        marker = response.get("Marker")
        if not marker:
            break
    return max(labels, key=_version_key)


def _version_key(label: str) -> tuple[int, ...]:
    version = label.removeprefix("emr-")
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def supported_instance_types(
    emr: EMRClient, release_label: str
) -> list[SupportedInstanceTypeTypeDef]:
    """Retorna todos os tipos de instância suportados para um release label."""
    instance_types: list[SupportedInstanceTypeTypeDef] = []
    marker = None
    while True:
        kwargs: dict[str, Any] = {"ReleaseLabel": release_label}
        if marker:
            kwargs["Marker"] = marker
        response = emr.list_supported_instance_types(**kwargs)
        instance_types.extend(response.get("SupportedInstanceTypes", []))
        marker = response.get("Marker")
        if not marker:
            break
    return instance_types
