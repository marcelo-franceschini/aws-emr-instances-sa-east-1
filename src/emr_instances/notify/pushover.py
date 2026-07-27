"""Envio da notificação para a API do Pushover (só biblioteca padrão)."""

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request

from emr_instances.errors import NotificationError

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


def send_pushover(title: str, message: str, url: str | None = None) -> None:
    """Envia a notificação via Pushover.

    Levanta NotificationError nos três modos de falha previstos: credencial
    ausente, API recusando o envio e rede indisponível. Nada de urllib vaza
    daqui — o CLI trata só erros de domínio.
    """
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
        # HTTPError é subclasse de URLError, então vem primeiro
        body = error.read().decode(errors="replace")
        raise NotificationError(
            f"Pushover recusou (HTTP {error.code}): {body}"
        ) from error
    except urllib.error.URLError as error:
        raise NotificationError(
            f"Erro de rede ao chamar o Pushover: {error.reason}"
        ) from error
