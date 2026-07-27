"""Release mais recente anunciado pela AWS (RSS de release notes do EMR)."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests

from emr_instances.models import AnnouncedRelease

logger = logging.getLogger(__name__)

RELEASE_NOTES_RSS = (
    "https://docs.aws.amazon.com/emr/latest/ReleaseGuide/amazon-emr-release-notes.rss"
)

_SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
# rótulo textual de linha especial: "emr-spark-8.0.0". Um release padrão vem como
# "7.14.0" ou "emr-7.14.0", onde o caractere após "emr-" é dígito, não letra.
_LABELED_LINE_RE = re.compile(r"emr-[a-z]", re.IGNORECASE)


def _announced_version(title: str) -> tuple[int, ...] | None:
    """Extrai a versão de um título do RSS; None se não for EMR on EC2 padrão.

    O feed mistura linhas especiais ("Release emr-spark-8.0.0 now available") e
    itens que nem são release ("EMR notebooks run kernels..."). Só interessam os
    títulos "Release(s) X.Y.Z ... now available"; quando um anúncio cobre vários
    patches ("Releases 6.11.1, 6.10.1, ... now available"), fica com o maior.
    """
    if not title.startswith("Release") or _LABELED_LINE_RE.search(title):
        return None
    versions = [
        tuple(int(part) for part in version.split("."))
        for version in _SEMVER_RE.findall(title)
    ]
    return max(versions) if versions else None


def latest_announced_release() -> AnnouncedRelease | None:
    """Maior release do EMR on EC2 anunciado no RSS de release notes.

    Percorre o feed inteiro em vez de pegar o primeiro item: o mais recente por
    data pode ser de uma linha especial (hoje é o emr-spark-8.0.0).

    Best-effort como o Spot Bid Advisor: falha de rede ou XML inválido devolve
    None, sem derrubar a coleta de instâncias.
    """
    try:
        response = requests.get(RELEASE_NOTES_RSS, timeout=10)
        response.raise_for_status()
        feed = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError) as e:
        logger.warning(f"Erro ao buscar o RSS de release notes do EMR: {e}")
        return None

    latest: AnnouncedRelease | None = None
    latest_version: tuple[int, ...] = ()
    for item in feed.findall("./channel/item"):
        version = _announced_version((item.findtext("title") or "").strip())
        if version is None or version <= latest_version:
            continue
        latest_version = version
        link = (item.findtext("link") or "").strip()
        latest = {
            "version": ".".join(str(part) for part in version),
            "url": link.split("#")[0],  # o fragmento aponta pro mesmo documento
            "published_at": (item.findtext("pubDate") or "").strip(),
        }
    return latest
