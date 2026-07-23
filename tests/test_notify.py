"""Testes para notify.py"""

import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import notify


def test_load_instance_types_missing_file() -> None:
    """Test load_instance_types com arquivo inexistente retorna set vazio."""
    result = notify.load_instance_types("/nonexistent/path.json")
    assert result == set()


def test_load_instance_types_valid_file() -> None:
    """Test load_instance_types com arquivo válido."""
    data: dict[str, object] = {
        "instances": [
            {"instance_type": "m5.large"},
            {"instance_type": "m5.xlarge"},
            {"instance_type": "t3.micro"},
        ]
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    try:
        result = notify.load_instance_types(temp_path)
        assert result == {"m5.large", "m5.xlarge", "t3.micro"}
    finally:
        os.unlink(temp_path)


def test_load_instance_types_empty_instances() -> None:
    """Test load_instance_types com JSON sem instâncias."""
    data: dict[str, object] = {}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    try:
        result = notify.load_instance_types(temp_path)
        assert result == set()
    finally:
        os.unlink(temp_path)


@patch("urllib.request.urlopen")
def test_send_pushover_success(mock_urlopen: MagicMock) -> None:
    """Test send_pushover com sucesso."""
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = b'{"status": 1}'
    mock_urlopen.return_value = mock_response

    with patch.dict(
        os.environ,
        {
            "PUSHOVER_TOKEN": "atoken123",
            "PUSHOVER_USER": "ukey456",
        },
    ):
        notify.send_pushover("Test Title", "Test message")
        mock_urlopen.assert_called_once()


@patch("urllib.request.urlopen")
def test_send_pushover_http_error(mock_urlopen: MagicMock) -> None:
    """Test send_pushover com erro HTTP."""
    error = urllib.error.HTTPError(
        "https://api.pushover.net/1/messages.json",
        400,
        "Bad Request",
        {},  # type: ignore
        None,
    )
    mock_urlopen.side_effect = error

    with (
        patch.dict(
            os.environ,
            {
                "PUSHOVER_TOKEN": "atoken123",
                "PUSHOVER_USER": "ukey456",
            },
        ),
        pytest.raises(urllib.error.HTTPError),
    ):
        notify.send_pushover("Test Title", "Test message")


def test_diff_new_instances() -> None:
    """Test detecção de instâncias novas."""
    old_data: dict[str, object] = {"instances": [{"instance_type": "m5.large"}]}
    new_data: dict[str, object] = {
        "instances": [
            {"instance_type": "m5.large"},
            {"instance_type": "m5.xlarge"},
            {"instance_type": "t3.micro"},
        ]
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f_old:
        json.dump(old_data, f_old)
        old_path = f_old.name

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f_new:
        json.dump(new_data, f_new)
        new_path = f_new.name

    try:
        old_types = notify.load_instance_types(old_path)
        new_types = notify.load_instance_types(new_path)
        added = notify.diff_new(new_types, old_types)
        assert added == ["m5.xlarge", "t3.micro"]
    finally:
        os.unlink(old_path)
        os.unlink(new_path)


def test_no_new_instances() -> None:
    """Test quando não há instâncias novas."""
    data: dict[str, object] = {"instances": [{"instance_type": "m5.large"}]}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    try:
        old_types = notify.load_instance_types(temp_path)
        new_types = notify.load_instance_types(temp_path)
        added = notify.diff_new(new_types, old_types)
        assert added == []
    finally:
        os.unlink(temp_path)


def test_diff_new() -> None:
    """Test diff_new direto sobre conjuntos de instance types."""
    new = {"m5.large", "m5.xlarge", "t3.micro"}
    old = {"m5.large"}
    assert notify.diff_new(new, old) == ["m5.xlarge", "t3.micro"]
    assert notify.diff_new(old, old) == []
    assert notify.diff_new(set(), old) == []


@patch("notify.send_pushover")
def test_main_notifies_even_without_new(
    mock_send: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Notifica em toda execução, inclusive sem instâncias novas (heartbeat)."""
    data = {"instances": [{"instance_type": "m5.large"}]}
    same = tmp_path / "instances.json"
    same.write_text(json.dumps(data), encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["notify.py", "--new", str(same), "--old", str(same)]
    )
    notify.main()

    mock_send.assert_called_once()


@patch("notify.send_pushover")
def test_main_notifies_with_new(
    mock_send: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Com instâncias novas, a mensagem informa a quantidade."""
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"instances": [{"instance_type": "m5.large"}]}), "utf-8")
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
        "utf-8",
    )

    monkeypatch.setattr(
        sys, "argv", ["notify.py", "--new", str(new), "--old", str(old)]
    )
    notify.main()

    mock_send.assert_called_once()
    assert "1 nova" in mock_send.call_args.kwargs["message"]
