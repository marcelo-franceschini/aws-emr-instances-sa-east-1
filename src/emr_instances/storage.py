"""Leitura e escrita dos snapshots JSON em disco."""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

from emr_instances.models import Payload

logger = logging.getLogger(__name__)


def write_output(payload: Payload, path: str) -> None:
    """Escreve o payload como JSON UTF-8 indentado; aborta em erro de I/O."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        logger.info(f"Salvo em {path}")
    except OSError as e:
        logger.error(f"Erro ao escrever {path}: {e}")
        sys.exit(1)


def load_snapshot(path: str) -> dict[str, Any]:
    """Lê um JSON gerado pela coleta (dict vazio se o arquivo não existir)."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data
