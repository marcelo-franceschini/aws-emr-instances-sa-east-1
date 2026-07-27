"""Testes para emr_instances.cli.notify"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from emr_instances.cli import notify

Snapshot = Callable[[str, str | None], dict[str, Any]]
PATCH_TARGET = "emr_instances.cli.notify.send_pushover"


def _run(monkeypatch: pytest.MonkeyPatch, new: Path, old: Path) -> None:
    """Roda o emr-notify apontando para os dois snapshots."""
    monkeypatch.setattr(
        sys, "argv", ["emr-notify", "--new", str(new), "--old", str(old)]
    )
    notify.main()


@patch(PATCH_TARGET)
def test_main_notifica_release_novo(
    mock_send: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: Snapshot,
) -> None:
    """Release novo: título destacado, as duas linhas de origem e link clicável."""
    old = tmp_path / "old.json"
    old.write_text(json.dumps(snapshot("emr-7.13.0", "7.13.0")), encoding="utf-8")
    new = tmp_path / "new.json"
    new.write_text(json.dumps(snapshot("emr-7.14.0", "7.14.0")), encoding="utf-8")

    _run(monkeypatch, new, old)

    kwargs = mock_send.call_args.kwargs
    assert "release novo" in kwargs["title"]
    assert "emr-7.13.0 → emr-7.14.0" in kwargs["message"]
    assert "7.13.0 → 7.14.0" in kwargs["message"]
    # o link do anúncio (RSS) tem precedência sobre o derivado
    assert kwargs["url"] == "https://docs.aws.amazon.com/x/emr-7.14.0.html"


@patch(PATCH_TARGET)
def test_main_sem_release_novo_nao_manda_url(
    mock_send: MagicMock,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: Snapshot,
) -> None:
    """Sem mudança de release, a notificação segue sendo o heartbeat sem link."""
    same = tmp_path / "instances.json"
    same.write_text(json.dumps(snapshot("emr-7.13.0", "7.13.0")), encoding="utf-8")

    _run(monkeypatch, same, same)

    kwargs = mock_send.call_args.kwargs
    assert kwargs["title"] == "EMR sa-east-1"
    assert kwargs["url"] is None


@patch(PATCH_TARGET)
def test_main_notifies_even_without_new(
    mock_send: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Notifica em toda execução, inclusive sem instâncias novas (heartbeat)."""
    data = {"instances": [{"instance_type": "m5.large"}]}
    same = tmp_path / "instances.json"
    same.write_text(json.dumps(data), encoding="utf-8")

    _run(monkeypatch, same, same)

    mock_send.assert_called_once()


@patch(PATCH_TARGET)
def test_main_notifies_with_new(
    mock_send: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com instâncias novas, a mensagem informa a quantidade."""
    old = tmp_path / "old.json"
    old.write_text(
        json.dumps({"instances": [{"instance_type": "m5.large"}]}), encoding="utf-8"
    )
    new = tmp_path / "new.json"
    new.write_text(
        json.dumps(
            {
                "instances": [
                    {"instance_type": "m5.large"},
                    {"instance_type": "c6g.large"},
                ]
            }
        ),
        encoding="utf-8",
    )

    _run(monkeypatch, new, old)

    mock_send.assert_called_once()
    assert "1 nova" in mock_send.call_args.kwargs["message"]
