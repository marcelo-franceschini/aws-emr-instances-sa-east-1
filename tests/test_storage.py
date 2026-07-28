"""Testes para emr_instances.storage"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emr_instances.collector import _build_static
from emr_instances.errors import StorageError
from emr_instances.models import Payload
from emr_instances.sources.ec2 import empty_hardware
from emr_instances.storage import load_snapshot, write_output


def _payload() -> Payload:
    """Payload mínimo, com acento para provar que a escrita é UTF-8 sem escape."""
    return {
        "region": "sa-east-1",
        "release_label": "emr-7.13.0",
        "schema_version": 2,
        "latest_announced_release": None,
        "generated_at": "2026-07-27T09:00:00+00:00",
        "instance_count": 1,
        "instances": [
            {
                "instance_type": "m5.large",
                "static": _build_static(
                    {"Type": "m5.large", "MemoryGB": 8.0}, empty_hardware(), [], None
                ),
                "pricing": {
                    "as_of": "2026-07-27T09:00:00+00:00",
                    "on_demand_usd_hour": 0.1,
                    "spot": {"usd_hour": 0.05, "az": "sa-east-1a"},
                    "spot_interruption": None,
                },
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
    """Erro de I/O vira StorageError em vez de estourar OSError cru."""
    path = tmp_path / "sem-esse-diretorio" / "out.json"
    with pytest.raises(StorageError):
        write_output(_payload(), str(path))


def test_load_snapshot_json_corrompido(tmp_path: Path) -> None:
    """JSON truncado vira StorageError em vez de JSONDecodeError cru."""
    path = tmp_path / "corrompido.json"
    path.write_text('{"instances": [', encoding="utf-8")

    with pytest.raises(StorageError):
        load_snapshot(str(path))


def test_load_snapshot_json_que_nao_e_objeto(tmp_path: Path) -> None:
    """JSON válido mas que não é objeto vira StorageError, não AttributeError."""
    path = tmp_path / "lista.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(StorageError):
        load_snapshot(str(path))
