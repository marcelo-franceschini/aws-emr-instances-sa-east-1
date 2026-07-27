"""Envio da notificação para a API do Pushover (só biblioteca padrão)."""

from __future__ import annotations

import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from emr_instances.config import PUSHOVER_URL

logger = logging.getLogger(__name__)


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
