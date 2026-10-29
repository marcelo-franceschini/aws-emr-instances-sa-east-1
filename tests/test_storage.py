"""Testes para emr_instances.storage"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emr_instances.collector import _build_static
from emr_instances.derived import build_derived
from emr_instances.errors import StorageError
from emr_instances.models import Payload, PricingSpec
from emr_instances.sources.ec2 import empty_hardware
from emr_instances.storage import write_output


def _payload() -> Payload:
    """Payload mínimo, com acento para provar que a escrita é UTF-8 sem escape."""
    static = _build_static(
        {"Type": "m5.large", "MemoryGB": 8.0}, empty_hardware(), [], None
    )
    pricing: PricingSpec = {
        "as_of": "2026-07-27T09:00:00+00:00",
        "on_demand_usd_hour": 0.1,
        "emr_fee_usd_hour": 0.024,
        "spot": {"usd_hour": 0.05, "az": "sa-east-1a"},
        "spot_by_az": [],
        "spot_interruption": None,
    }
    return {
        "region": "sa-east-1",
        "release_label": "emr-7.13.0",
        "schema_version": 3,
        "generated_at": "2026-07-27T09:00:00+00:00",
        "instance_count": 1,
        "instances": [
            {
                "instance_type": "m5.large",
                "static": static,
                "pricing": pricing,
                "emr_yarn": None,
                "derived": build_derived(static, pricing, None),
            }
        ],
    }


def test_write_output_round_trip(tmp_path: Path) -> None:
    """O que write_output grava é exatamente o payload, como JSON."""
    path = tmp_path / "out.json"
    payload = _payload()

    write_output(payload, str(path))

    content = path.read_text(encoding="utf-8")
    assert json.loads(content) == payload
    assert content.endswith("\n")
    assert '"instance_type": "m5.large"' in content  # indentado, não compactado


def test_write_output_io_error(tmp_path: Path) -> None:
    """Erro de I/O vira StorageError em vez de estourar OSError cru."""
    path = tmp_path / "sem-esse-diretorio" / "out.json"
    with pytest.raises(StorageError):
        write_output(_payload(), str(path))
