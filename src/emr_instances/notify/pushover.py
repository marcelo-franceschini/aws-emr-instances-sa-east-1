"""Envio da notificação para a API do Pushover (só biblioteca padrão)."""

from __future__ import annotations

import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from emr_instances.errors import NotificationError

logger = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def send_pushover(title: str, message: str, url: str | None = None) -> None:
    """Envia a notificação; levanta NotificationError se faltar credencial."""
    try:
        token = os.environ["PUSHOVER_TOKEN"]
        user = os.environ["PUSHOVER_USER"]
    except KeyError as missing:
        raise NotificationError(
            f"Variável de ambiente {missing.args[0]} não definida."
        ) from missing
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
