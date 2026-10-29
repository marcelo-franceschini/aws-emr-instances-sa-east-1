"""Padrões de YARN por tipo de instância, da página Task configuration do EMR.

Não existe API para isso: a memória que o YARN pode alocar por nó
(`yarn.nodemanager.resource.memory-mb`) só está publicada nessa página da
documentação, numa tabela por tipo. Usa a versão em Markdown da página, que é
bem mais estável de ler que o HTML.
"""

from __future__ import annotations

import logging
import re

import requests

from emr_instances.models import YarnDefaults

logger = logging.getLogger(__name__)

YARN_DOC_URL = (
    "https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-hadoop-task-config.md"
)

# Cada tabela é precedida por uma linha só com o tipo em negrito: **c5.xlarge**
_TYPE_LINE = re.compile(r"^\*\*([a-z0-9][a-z0-9-]*\.[a-z0-9-]+)\*\*\s*$")
# Linha de tabela com a propriedade e o valor da coluna padrão (a primeira)
_ROW = re.compile(r"^\|\s*(yarn\.[\w.-]+)\s*\|\s*(\d+)\s*\|")

_NODEMANAGER = "yarn.nodemanager.resource.memory-mb"
_MAX_ALLOCATION = "yarn.scheduler.maximum-allocation-mb"
_MIN_ALLOCATION = "yarn.scheduler.minimum-allocation-mb"


def parse_yarn_defaults(markdown: str) -> dict[str, YarnDefaults]:
    """Extrai {instance_type: YarnDefaults} do Markdown da página.

    Só a coluna de valor padrão é lida; a coluna "com HBase" é ignorada. Um tipo
    sem a linha do NodeManager é descartado, porque sem ela o registro não teria
    o campo que justifica a coleta.
    """
    defaults: dict[str, YarnDefaults] = {}
    current: str | None = None
    values: dict[str, int] = {}

    def close() -> None:
        if current is not None and _NODEMANAGER in values:
            defaults[current] = {
                "nodemanager_memory_mb": values[_NODEMANAGER],
                "scheduler_max_allocation_mb": values.get(_MAX_ALLOCATION),
                "scheduler_min_allocation_mb": values.get(_MIN_ALLOCATION),
            }

    for line in markdown.splitlines():
        type_match = _TYPE_LINE.match(line)
        if type_match:
            close()
            current, values = type_match.group(1), {}
            continue
        row_match = _ROW.match(line)
        if row_match and current is not None:
            values[row_match.group(1)] = int(row_match.group(2))
    close()
    return defaults


def yarn_defaults() -> dict[str, YarnDefaults]:
    """Baixa a página e devolve os padrões de YARN por tipo de instância.

    Indisponibilidade da página ou mudança de formato não derruba a coleta: o
    bloco `emr_yarn` fica None e a falta aparece no log de cobertura. Zero tipos
    lidos com a página no ar indica que o formato mudou, e isso é logado como erro.
    """
    try:
        response = requests.get(YARN_DOC_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Erro ao buscar a página Task configuration do EMR: {e}")
        return {}
    defaults = parse_yarn_defaults(response.text)
    if not defaults:
        logger.error(
            "A página Task configuration foi baixada, mas nenhuma tabela foi "
            "reconhecida: o formato da documentação provavelmente mudou."
        )
    return defaults
