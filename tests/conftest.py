"""Fixtures compartilhadas entre os testes."""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from emr_instances.models import AnnouncedRelease, Snapshot

RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Amazon EMR Release Notes</title>
  <item>
    <title>Release emr-spark-8.0.0 now available</title>
    <link>https://docs.aws.amazon.com/x/emr-spark800-release.html#relnotes</link>
    <pubDate>Thu, 21 May 2026 19:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Release 7.13.0 now available</title>
    <link>https://docs.aws.amazon.com/x/emr-7130-release.html#emr-7130-relnotes</link>
    <pubDate>Tue, 28 Apr 2026 19:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Release 7.12.0 now available</title>
    <link>https://docs.aws.amazon.com/x/emr-7120-release.html#emr-7120-relnotes</link>
    <pubDate>Fri, 21 Nov 2025 19:00:00 GMT</pubDate>
  </item>
  <item>
    <title>EMR notebooks run kernels on cluster with 5.30.0 and later</title>
    <link>https://docs.aws.amazon.com/x/emr-managed-notebooks.html</link>
    <pubDate>Wed, 3 Jun 2020 19:00:00 GMT</pubDate>
  </item>
</channel></rss>
"""


@pytest.fixture
def rss_response() -> Callable[[], MagicMock]:
    """Fábrica de resposta requests fake servindo o RSS de release notes."""

    def build() -> MagicMock:
        response = MagicMock()
        response.content = RSS_FIXTURE.encode()
        response.raise_for_status.return_value = None
        return response

    return build


@pytest.fixture
def snapshot() -> Callable[[str, str | None], Snapshot]:
    """Fábrica de snapshot mínimo com os dois campos de release comparados."""

    def build(label: str, announced_version: str | None) -> Snapshot:
        announced: AnnouncedRelease | None = (
            {
                "version": announced_version,
                "url": f"https://docs.aws.amazon.com/x/emr-{announced_version}.html",
                "published_at": "Tue, 28 Apr 2026 19:00:00 GMT",
            }
            if announced_version
            else None
        )
        return {"release_label": label, "latest_announced_release": announced}

    return build
