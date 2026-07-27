"""Testes para emr_instances.sources.release_notes"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import requests

from emr_instances.sources import release_notes

PATCH_TARGET = "emr_instances.sources.release_notes.requests.get"


def test_announced_version_release_padrao() -> None:
    """Test títulos de release do EMR on EC2 padrão."""
    announced_version = release_notes._announced_version
    assert announced_version("Release 7.13.0 now available") == (7, 13, 0)
    assert announced_version("Release 7.9.0 now available") == (7, 9, 0)
    assert announced_version("Release 6.15.0 now available") == (6, 15, 0)


def test_announced_version_ignora_linha_especial() -> None:
    """Linha especial (emr-spark) não conta como release novo do EMR on EC2."""
    title = "Release emr-spark-8.0.0 now available"
    assert release_notes._announced_version(title) is None


def test_announced_version_ignora_nao_release() -> None:
    """Itens do feed que não anunciam release são ignorados."""
    title = "EMR notebooks run kernels with 5.30.0"
    assert release_notes._announced_version(title) is None
    assert release_notes._announced_version("Release Guide updated") is None


def test_announced_version_multiplos_patches() -> None:
    """Anúncio com vários patches fica com o maior."""
    title = "Releases 6.11.1, 6.10.1, 6.9.1, and 6.8.1 now available"
    assert release_notes._announced_version(title) == (6, 11, 1)


def test_latest_announced_release(rss_response: Callable[[], MagicMock]) -> None:
    """Pega o maior release padrão do feed, não o item mais recente por data."""
    with patch(PATCH_TARGET, return_value=rss_response()):
        announced = release_notes.latest_announced_release()

    assert announced is not None
    assert announced["version"] == "7.13.0"
    # o fragmento #... é removido
    assert announced["url"] == "https://docs.aws.amazon.com/x/emr-7130-release.html"
    assert announced["published_at"] == "Tue, 28 Apr 2026 19:00:00 GMT"


def test_latest_announced_release_erro_de_rede() -> None:
    """Feed fora do ar devolve None, sem derrubar a coleta."""
    with patch(PATCH_TARGET, side_effect=requests.RequestException("boom")):
        assert release_notes.latest_announced_release() is None


def test_latest_announced_release_xml_invalido() -> None:
    """XML corrompido devolve None, sem derrubar a coleta."""
    response = MagicMock()
    response.content = b"<rss><channel><item></rss>"
    response.raise_for_status.return_value = None
    with patch(PATCH_TARGET, return_value=response):
        assert release_notes.latest_announced_release() is None


def test_latest_announced_release_feed_sem_release() -> None:
    """Feed só com linhas especiais devolve None."""
    response = MagicMock()
    response.content = (
        b"<rss><channel><item><title>Release emr-spark-8.0.0 now available"
        b"</title><link>https://x/y.html</link></item></channel></rss>"
    )
    response.raise_for_status.return_value = None
    with patch(PATCH_TARGET, return_value=response):
        assert release_notes.latest_announced_release() is None
