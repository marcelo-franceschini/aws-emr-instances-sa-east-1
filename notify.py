"""Compara o JSON recém-gerado com o anterior e notifica via Pushover.

Envia uma notificação em TODA execução (também serve de heartbeat diário):
- Release novo do EMR: informa a mudança e manda o link das release notes.
- Com instâncias novas: informa a QUANTIDADE de instâncias novas.
- Sem nenhuma novidade: envia uma confirmação de que a coleta rodou.
- Primeira execução (sem JSON anterior): tudo conta como novo.

Lê PUSHOVER_TOKEN e PUSHOVER_USER do ambiente. Usa só a biblioteca padrão.
"""

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
RELEASE_NOTES_BASE = "https://docs.aws.amazon.com/emr/latest/ReleaseGuide"


class ReleaseAlert(TypedDict):
    origin: str
    previous: str
    current: str
    url: str


def load_snapshot(path: str) -> dict[str, Any]:
    """Lê um JSON gerado pelo main.py (dict vazio se o arquivo não existir)."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def instance_types(snapshot: dict[str, Any]) -> set[str]:
    """Extrai os instance_type de um snapshot já carregado."""
    return {inst["instance_type"] for inst in snapshot.get("instances", [])}


def diff_new(new_types: set[str], old_types: set[str]) -> list[str]:
    """Instance types presentes em `new_types` e ausentes em `old_types`, ordenados."""
    return sorted(new_types - old_types)


def release_notes_url(version: str) -> str:
    """Deriva a URL das release notes: "emr-7.13.0" → ".../emr-7130-release.html"."""
    digits = version.removeprefix("emr-").replace(".", "")
    return f"{RELEASE_NOTES_BASE}/emr-{digits}-release.html"


def _announced(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Bloco latest_announced_release do snapshot (vazio se ausente ou null)."""
    return snapshot.get("latest_announced_release") or {}


def release_alerts(
    new_snapshot: dict[str, Any], old_snapshot: dict[str, Any]
) -> list[ReleaseAlert]:
    """Mudanças de release do EMR entre dois snapshots, de duas fontes distintas.

    Só alerta quando o valor existe nos DOIS lados e é diferente. Sem essa guarda,
    a primeira execução (sem baseline), a primeira após passar a gravar o campo do
    RSS e qualquer indisponibilidade momentânea do feed virariam falso alarme.
    """
    alerts: list[ReleaseAlert] = []

    old_label = old_snapshot.get("release_label")
    new_label = new_snapshot.get("release_label")
    if old_label and new_label and old_label != new_label:
        alerts.append(
            {
                "origin": "Disponível em sa-east-1",
                "previous": old_label,
                "current": new_label,
                "url": release_notes_url(new_label),
            }
        )

    old_version = _announced(old_snapshot).get("version")
    new_announced = _announced(new_snapshot)
    new_version = new_announced.get("version")
    if old_version and new_version and old_version != new_version:
        alerts.append(
            {
                "origin": "Anunciado pela AWS",
                "previous": old_version,
                "current": new_version,
                "url": new_announced.get("url") or release_notes_url(new_version),
            }
        )

    return alerts


def send_pushover(title: str, message: str, url: str | None = None) -> None:
    try:
        token = os.environ["PUSHOVER_TOKEN"]
        user = os.environ["PUSHOVER_USER"]
    except KeyError as missing:
        logger.error(f"Variável de ambiente {missing} não definida.")
        sys.exit(1)
    fields = {"token": token, "user": user, "title": title, "message": message}
    if url:
        fields["url"] = url
        fields["url_title"] = "Ver release notes"
    payload = urllib.parse.urlencode(fields).encode()
    request = urllib.request.Request(PUSHOVER_URL, data=payload)
    try:
        with urllib.request.urlopen(request) as response:
            response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        logger.error(f"Pushover recusou (HTTP {error.code}): {body}")
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", default="instances_sa-east-1.json")
    parser.add_argument("--old", default="previous.json")
    args = parser.parse_args()

    new_snapshot = load_snapshot(args.new)
    old_snapshot = load_snapshot(args.old)

    new_types = instance_types(new_snapshot)
    added = diff_new(new_types, instance_types(old_snapshot))
    logger.info(f"Instâncias novas: {len(added)}")

    alerts = release_alerts(new_snapshot, old_snapshot)
    for alert in alerts:
        logger.info(
            f"Release novo ({alert['origin']}): "
            f"{alert['previous']} → {alert['current']}"
        )

    if added:
        instances_line = (
            f"{len(added)} nova(s) instância(s) EMR disponível(is) em São Paulo."
        )
    else:
        instances_line = (
            f"Nenhuma instância nova. Total: {len(new_types)} tipos suportados."
        )

    if alerts:
        title = "EMR sa-east-1 — release novo"
        lines = [
            f"{alert['origin']}: {alert['previous']} → {alert['current']}"
            for alert in alerts
        ]
        message = "\n".join([*lines, instances_line])
        # quando o alerta do RSS existe ele é o último, e traz o link oficial
        url: str | None = alerts[-1]["url"]
    else:
        title = "EMR sa-east-1"
        message = instances_line
        url = None

    send_pushover(title=title, message=message, url=url)
    logger.info("Notificação enviada via Pushover.")


if __name__ == "__main__":
    main()
