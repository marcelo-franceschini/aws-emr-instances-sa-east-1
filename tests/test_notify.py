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


def test_load_snapshot_missing_file() -> None:
    """Test load_snapshot com arquivo inexistente retorna dict vazio."""
    snapshot = notify.load_snapshot("/nonexistent/path.json")
    assert snapshot == {}
    assert notify.instance_types(snapshot) == set()


def test_load_instance_types_valid_file() -> None:
    """Test load_snapshot + instance_types com arquivo válido."""
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
        result = notify.instance_types(notify.load_snapshot(temp_path))
        assert result == {"m5.large", "m5.xlarge", "t3.micro"}
    finally:
        os.unlink(temp_path)


def test_load_instance_types_empty_instances() -> None:
    """Test instance_types com JSON sem instâncias."""
    data: dict[str, object] = {}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(data, f)
        temp_path = f.name

    try:
        result = notify.instance_types(notify.load_snapshot(temp_path))
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
        old_types = notify.instance_types(notify.load_snapshot(old_path))
        new_types = notify.instance_types(notify.load_snapshot(new_path))
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
        old_types = notify.instance_types(notify.load_snapshot(temp_path))
        new_types = notify.instance_types(notify.load_snapshot(temp_path))
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


def test_release_notes_url() -> None:
    """Test derivação da URL das release notes a partir da versão."""
    base = "https://docs.aws.amazon.com/emr/latest/ReleaseGuide"
    assert notify.release_notes_url("emr-7.13.0") == f"{base}/emr-7130-release.html"
    assert notify.release_notes_url("7.13.0") == f"{base}/emr-7130-release.html"
    assert notify.release_notes_url("7.9.0") == f"{base}/emr-790-release.html"
    assert notify.release_notes_url("emr-8.0.0") == f"{base}/emr-800-release.html"


def _snapshot(label: str, announced_version: str | None) -> dict[str, object]:
    """Snapshot mínimo com os dois campos de release que o notify compara."""
    announced = (
        {
            "version": announced_version,
            "url": f"https://docs.aws.amazon.com/x/emr-{announced_version}.html",
            "published_at": "Tue, 28 Apr 2026 19:00:00 GMT",
        }
        if announced_version
        else None
    )
    return {"release_label": label, "latest_announced_release": announced}


def test_release_alerts_sem_baseline() -> None:
    """Primeira execução (sem JSON anterior) não deve alertar release novo."""
    assert notify.release_alerts(_snapshot("emr-7.13.0", "7.13.0"), {}) == []


def test_release_alerts_sem_mudanca() -> None:
    """Release igual nos dois lados não gera alerta."""
    snapshot = _snapshot("emr-7.13.0", "7.13.0")
    assert notify.release_alerts(snapshot, snapshot) == []


def test_release_alerts_campo_ausente_no_antigo() -> None:
    """Baseline antiga sem latest_announced_release não vira falso alarme."""
    old: dict[str, object] = {"release_label": "emr-7.13.0"}
    alerts = notify.release_alerts(_snapshot("emr-7.13.0", "7.13.0"), old)
    assert alerts == []


def test_release_alerts_rss_indisponivel() -> None:
    """RSS fora do ar (campo null) não vira falso alarme."""
    new = _snapshot("emr-7.13.0", None)
    old = _snapshot("emr-7.13.0", "7.13.0")
    assert notify.release_alerts(new, old) == []
    assert notify.release_alerts(old, new) == []


def test_release_alerts_label_mudou() -> None:
    """Release novo disponível em sa-east-1: um alerta, com URL derivada."""
    new = _snapshot("emr-7.14.0", "7.13.0")
    old = _snapshot("emr-7.13.0", "7.13.0")
    alerts = notify.release_alerts(new, old)

    assert len(alerts) == 1
    assert alerts[0]["origin"] == "Disponível em sa-east-1"
    assert alerts[0]["previous"] == "emr-7.13.0"
    assert alerts[0]["current"] == "emr-7.14.0"
    assert alerts[0]["url"].endswith("/emr-7140-release.html")


def test_release_alerts_anuncio_mudou() -> None:
    """Anúncio novo no RSS: um alerta, com a URL vinda do próprio feed."""
    new = _snapshot("emr-7.13.0", "7.14.0")
    old = _snapshot("emr-7.13.0", "7.13.0")
    alerts = notify.release_alerts(new, old)

    assert len(alerts) == 1
    assert alerts[0]["origin"] == "Anunciado pela AWS"
    assert alerts[0]["url"] == "https://docs.aws.amazon.com/x/emr-7.14.0.html"


def test_release_alerts_ambos_mudaram() -> None:
    """Quando as duas fontes mudam no mesmo dia, vêm os dois alertas."""
    alerts = notify.release_alerts(
        _snapshot("emr-7.14.0", "7.14.0"), _snapshot("emr-7.13.0", "7.13.0")
    )
    origins = [alert["origin"] for alert in alerts]
    assert origins == ["Disponível em sa-east-1", "Anunciado pela AWS"]


@patch("urllib.request.urlopen")
def test_send_pushover_com_url(mock_urlopen: MagicMock) -> None:
    """Com url, o POST leva os campos url e url_title (link clicável)."""
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    with patch.dict(
        os.environ, {"PUSHOVER_TOKEN": "atoken123", "PUSHOVER_USER": "ukey456"}
    ):
        notify.send_pushover("Titulo", "Mensagem", url="https://example.com/rel.html")

    body = mock_urlopen.call_args.args[0].data.decode()
    assert "url=https%3A%2F%2Fexample.com%2Frel.html" in body
    assert "url_title=" in body


@patch("urllib.request.urlopen")
def test_send_pushover_sem_url(mock_urlopen: MagicMock) -> None:
    """Sem url, o POST não leva os campos de link."""
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    with patch.dict(
        os.environ, {"PUSHOVER_TOKEN": "atoken123", "PUSHOVER_USER": "ukey456"}
    ):
        notify.send_pushover("Titulo", "Mensagem")

    body = mock_urlopen.call_args.args[0].data.decode()
    assert "url_title" not in body


@patch("notify.send_pushover")
def test_main_notifica_release_novo(
    mock_send: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release novo: título destacado, as duas linhas de origem e link clicável."""
    old = tmp_path / "old.json"
    old.write_text(json.dumps(_snapshot("emr-7.13.0", "7.13.0")), encoding="utf-8")
    new = tmp_path / "new.json"
    new.write_text(json.dumps(_snapshot("emr-7.14.0", "7.14.0")), encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["notify.py", "--new", str(new), "--old", str(old)]
    )
    notify.main()

    kwargs = mock_send.call_args.kwargs
    assert "release novo" in kwargs["title"]
    assert "emr-7.13.0 → emr-7.14.0" in kwargs["message"]
    assert "7.13.0 → 7.14.0" in kwargs["message"]
    # o link do anúncio (RSS) tem precedência sobre o derivado
    assert kwargs["url"] == "https://docs.aws.amazon.com/x/emr-7.14.0.html"


@patch("notify.send_pushover")
def test_main_sem_release_novo_nao_manda_url(
    mock_send: MagicMock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem mudança de release, a notificação segue sendo o heartbeat sem link."""
    same = tmp_path / "instances.json"
    same.write_text(json.dumps(_snapshot("emr-7.13.0", "7.13.0")), encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["notify.py", "--new", str(same), "--old", str(same)]
    )
    notify.main()

    kwargs = mock_send.call_args.kwargs
    assert kwargs["title"] == "EMR sa-east-1"
    assert kwargs["url"] is None


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
