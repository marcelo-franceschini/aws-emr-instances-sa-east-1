"""Testes para emr_instances.storage"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emr_instances.models import Payload
from emr_instances.storage import load_snapshot, write_output


def _payload() -> Payload:
    """Payload mínimo, com acento para provar que a escrita é UTF-8 sem escape."""
    return {
        "region": "sa-east-1",
        "release_label": "emr-7.13.0",
        "latest_announced_release": None,
        "generated_at": "2026-07-27T09:00:00+00:00",
        "instance_count": 1,
        "instances": [
            {
                "instance_type": "m5.large",
                "vcpu": 2,
                "memory_gb": 8.0,
                "architecture": "x86_64",
                "network_performance": "Up to 10 Gigabit",
                "network_gbps": 10.0,
                "on_demand_usd_hour": 0.1,
                "spot": {"usd_hour": 0.05, "az": "sa-east-1a"},
                "spot_interruption": None,
            }
        ],
    }


def test_load_snapshot_missing_file() -> None:
    """Test load_snapshot com arquivo inexistente retorna dict vazio."""
    assert load_snapshot("/nonexistent/path.json") == {}


def test_load_snapshot_reads_json(tmp_path: Path) -> None:
    """Test load_snapshot devolve o JSON já parseado."""
    path = tmp_path / "snapshot.json"
    data = {"instances": [{"instance_type": "m5.large"}]}
    path.write_text(json.dumps(data), encoding="utf-8")

    assert load_snapshot(str(path)) == data


def test_write_output_round_trip(tmp_path: Path) -> None:
    """O que write_output grava é exatamente o que load_snapshot lê de volta."""
    path = tmp_path / "out.json"
    payload = _payload()

    write_output(payload, str(path))

    assert load_snapshot(str(path)) == payload
    content = path.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert '"instance_type": "m5.large"' in content  # indentado, não compactado


def test_write_output_io_error(tmp_path: Path) -> None:
    """Erro de I/O aborta com SystemExit em vez de estourar OSError."""
    path = tmp_path / "sem-esse-diretorio" / "out.json"
    with pytest.raises(SystemExit):
        write_output(_payload(), str(path))
