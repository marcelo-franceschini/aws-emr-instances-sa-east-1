"""Testes para emr_instances.notify.pushover"""

from __future__ import annotations

import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from emr_instances.notify.pushover import send_pushover

CREDENTIALS = {"PUSHOVER_TOKEN": "atoken123", "PUSHOVER_USER": "ukey456"}


@patch("urllib.request.urlopen")
def test_send_pushover_success(mock_urlopen: MagicMock) -> None:
    """Test send_pushover com sucesso."""
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = b'{"status": 1}'
    mock_urlopen.return_value = mock_response

    with patch.dict(os.environ, CREDENTIALS):
        send_pushover("Test Title", "Test message")
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
        patch.dict(os.environ, CREDENTIALS),
        pytest.raises(urllib.error.HTTPError),
    ):
        send_pushover("Test Title", "Test message")


@patch("urllib.request.urlopen")
def test_send_pushover_com_url(mock_urlopen: MagicMock) -> None:
    """Com url, o POST leva os campos url e url_title (link clicável)."""
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    with patch.dict(os.environ, CREDENTIALS):
        send_pushover("Titulo", "Mensagem", url="https://example.com/rel.html")

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

    with patch.dict(os.environ, CREDENTIALS):
        send_pushover("Titulo", "Mensagem")

    body = mock_urlopen.call_args.args[0].data.decode()
    assert "url_title" not in body


@patch("urllib.request.urlopen")
def test_send_pushover_sem_credenciais(mock_urlopen: MagicMock) -> None:
    """Sem PUSHOVER_TOKEN/PUSHOVER_USER no ambiente, aborta antes de chamar a API."""
    with patch.dict(os.environ, {}, clear=True), pytest.raises(SystemExit):
        send_pushover("Titulo", "Mensagem")

    mock_urlopen.assert_not_called()
