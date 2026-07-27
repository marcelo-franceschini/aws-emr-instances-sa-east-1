"""Leitura e escrita dos snapshots JSON em disco."""

from __future__ import annotations

import json
import logging
import os
from typing import cast

from emr_instances.errors import StorageError
from emr_instances.models import Payload, Snapshot

logger = logging.getLogger(__name__)


def write_output(payload: Payload, path: str) -> None:
    """Escreve o payload como JSON UTF-8 indentado.

    Levanta StorageError em falha de I/O — quem decide o código de saída é o CLI.
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"Salvo em {path}")
    except OSError as e:
        raise StorageError(f"Erro ao escrever {path}: {e}") from e


def load_snapshot(path: str) -> Snapshot:
    """Lê um snapshot gerado pela coleta (vazio se o arquivo não existir).

    Arquivo ausente é normal (primeira execução) e devolve vazio. Arquivo que
    existe mas está ilegível ou corrompido vira StorageError, pela mesma razão
    que em write_output — quem decide o código de saída é o CLI.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise StorageError(f"Erro ao ler {path}: {e}") from e
    if not isinstance(data, dict):
        raise StorageError(f"{path} não contém um objeto JSON.")
    return cast(Snapshot, data)
