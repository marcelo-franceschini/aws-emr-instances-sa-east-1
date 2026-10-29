"""Escrita do JSON gerado em disco."""

from __future__ import annotations

import json
import logging

from emr_instances.errors import StorageError
from emr_instances.models import Payload

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
