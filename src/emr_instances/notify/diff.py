"""Diferenças entre dois snapshots: instâncias novas e mudanças de release."""

from __future__ import annotations

from typing import Any

from emr_instances.config import RELEASE_NOTES_BASE
from emr_instances.models import ReleaseAlert


def instance_types(snapshot: dict[str, Any]) -> set[str]:
    """Extrai os instance_type de um snapshot já carregado."""
    return {inst["instance_type"] for inst in snapshot.get("instances", [])}


def diff_new(new_types: set[str], old_types: set[str]) -> list[str]:
    """Instance types presentes em `new_types` e ausentes em `old_types`, ordenados."""
    return sorted(new_types - old_types)


def release_notes_url(version: str) -> str:
    """Deriva a URL das release notes: "emr-7.13.0" → ".../emr-7130-release.html"."""
    digits = version.removeprefix("emr-").replace(".", "")
    return f"{RELEASE_NOTES_BASE}/emr-{digits}-release.html"


def _announced(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bloco latest_announced_release do snapshot (vazio se ausente ou null)."""
    return snapshot.get("latest_announced_release") or {}


def release_alerts(
    new_snapshot: dict[str, Any], old_snapshot: dict[str, Any]
) -> list[ReleaseAlert]:
    """Mudanças de release do EMR entre dois snapshots, de duas fontes distintas.

    Só alerta quando o valor existe nos DOIS lados e é diferente. Sem essa guarda,
    a primeira execução (sem baseline), a primeira após passar a gravar o campo do
    RSS e qualquer indisponibilidade momentânea do feed virariam falso alarme.
    """
    alerts: list[ReleaseAlert] = []

    old_label = old_snapshot.get("release_label")
    new_label = new_snapshot.get("release_label")
    if old_label and new_label and old_label != new_label:
        alerts.append(
            {
                "origin": "Disponível em sa-east-1",
                "previous": old_label,
                "current": new_label,
                "url": release_notes_url(new_label),
            }
        )

    old_version = _announced(old_snapshot).get("version")
    new_announced = _announced(new_snapshot)
    new_version = new_announced.get("version")
    if old_version and new_version and old_version != new_version:
        alerts.append(
            {
                "origin": "Anunciado pela AWS",
                "previous": old_version,
                "current": new_version,
                "url": new_announced.get("url") or release_notes_url(new_version),
            }
        )

    return alerts
