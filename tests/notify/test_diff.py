"""Testes para emr_instances.notify.diff"""

from __future__ import annotations

from collections.abc import Callable

from emr_instances.models import Snapshot
from emr_instances.notify.diff import (
    diff_new,
    instance_types,
    release_alerts,
    release_notes_url,
)

SnapshotFactory = Callable[[str, str | None], Snapshot]


def test_instance_types() -> None:
    """Test extração dos instance_type de um snapshot."""
    snapshot: Snapshot = {
        "instances": [
            {"instance_type": "m5.large"},
            {"instance_type": "m5.xlarge"},
            {"instance_type": "t3.micro"},
        ]
    }
    assert instance_types(snapshot) == {"m5.large", "m5.xlarge", "t3.micro"}


def test_instance_types_snapshot_vazio() -> None:
    """Snapshot vazio ou sem a chave instances devolve conjunto vazio."""
    assert instance_types({}) == set()
    assert instance_types({"instances": []}) == set()


def test_diff_new_instances() -> None:
    """Test detecção de instâncias novas entre dois snapshots."""
    old: Snapshot = {"instances": [{"instance_type": "m5.large"}]}
    new: Snapshot = {
        "instances": [
            {"instance_type": "m5.large"},
            {"instance_type": "m5.xlarge"},
            {"instance_type": "t3.micro"},
        ]
    }
    added = diff_new(instance_types(new), instance_types(old))
    assert added == ["m5.xlarge", "t3.micro"]


def test_no_new_instances() -> None:
    """Test quando não há instâncias novas."""
    snapshot: Snapshot = {"instances": [{"instance_type": "m5.large"}]}
    types = instance_types(snapshot)
    assert diff_new(types, types) == []


def test_diff_new() -> None:
    """Test diff_new direto sobre conjuntos de instance types."""
    new = {"m5.large", "m5.xlarge", "t3.micro"}
    old = {"m5.large"}
    assert diff_new(new, old) == ["m5.xlarge", "t3.micro"]
    assert diff_new(old, old) == []
    assert diff_new(set(), old) == []


def test_release_notes_url() -> None:
    """Test derivação da URL das release notes a partir da versão."""
    base = "https://docs.aws.amazon.com/emr/latest/ReleaseGuide"
    assert release_notes_url("emr-7.13.0") == f"{base}/emr-7130-release.html"
    assert release_notes_url("7.13.0") == f"{base}/emr-7130-release.html"
    assert release_notes_url("7.9.0") == f"{base}/emr-790-release.html"
    assert release_notes_url("emr-8.0.0") == f"{base}/emr-800-release.html"


def test_release_alerts_sem_baseline(snapshot: SnapshotFactory) -> None:
    """Primeira execução (sem JSON anterior) não deve alertar release novo."""
    assert release_alerts(snapshot("emr-7.13.0", "7.13.0"), {}) == []


def test_release_alerts_sem_mudanca(snapshot: SnapshotFactory) -> None:
    """Release igual nos dois lados não gera alerta."""
    same = snapshot("emr-7.13.0", "7.13.0")
    assert release_alerts(same, same) == []


def test_release_alerts_campo_ausente_no_antigo(snapshot: SnapshotFactory) -> None:
    """Baseline antiga sem latest_announced_release não vira falso alarme."""
    old: Snapshot = {"release_label": "emr-7.13.0"}
    assert release_alerts(snapshot("emr-7.13.0", "7.13.0"), old) == []


def test_release_alerts_rss_indisponivel(snapshot: SnapshotFactory) -> None:
    """RSS fora do ar (campo null) não vira falso alarme."""
    new = snapshot("emr-7.13.0", None)
    old = snapshot("emr-7.13.0", "7.13.0")
    assert release_alerts(new, old) == []
    assert release_alerts(old, new) == []


def test_release_alerts_label_mudou(snapshot: SnapshotFactory) -> None:
    """Release novo disponível em sa-east-1: um alerta, com URL derivada."""
    alerts = release_alerts(
        snapshot("emr-7.14.0", "7.13.0"), snapshot("emr-7.13.0", "7.13.0")
    )

    assert len(alerts) == 1
    assert alerts[0]["origin"] == "Disponível em sa-east-1"
    assert alerts[0]["previous"] == "emr-7.13.0"
    assert alerts[0]["current"] == "emr-7.14.0"
    assert alerts[0]["url"].endswith("/emr-7140-release.html")


def test_release_alerts_anuncio_mudou(snapshot: SnapshotFactory) -> None:
    """Anúncio novo no RSS: um alerta, com a URL vinda do próprio feed."""
    alerts = release_alerts(
        snapshot("emr-7.13.0", "7.14.0"), snapshot("emr-7.13.0", "7.13.0")
    )

    assert len(alerts) == 1
    assert alerts[0]["origin"] == "Anunciado pela AWS"
    assert alerts[0]["url"] == "https://docs.aws.amazon.com/x/emr-7.14.0.html"


def test_release_alerts_ambos_mudaram(snapshot: SnapshotFactory) -> None:
    """Quando as duas fontes mudam no mesmo dia, vêm os dois alertas."""
    alerts = release_alerts(
        snapshot("emr-7.14.0", "7.14.0"), snapshot("emr-7.13.0", "7.13.0")
    )
    origins = [alert["origin"] for alert in alerts]
    assert origins == ["Disponível em sa-east-1", "Anunciado pela AWS"]
