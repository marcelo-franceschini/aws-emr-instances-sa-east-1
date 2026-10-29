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

from emr_instances.errors import SourceFormatError
from emr_instances.models import YarnDefaults

logger = logging.getLogger(__name__)

YARN_DOC_URL = (
    "https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-hadoop-task-config.md"
)

# Cada tabela é precedida por uma linha só com o tipo em negrito: **c5.xlarge**
_TYPE_LINE = re.compile(r"^\*\*([a-z0-9][a-z0-9-]*\.[a-z0-9-]+)\*\*\s*$")
# Cabeçalho da tabela, com o nome da primeira coluna de valor
_HEADER = re.compile(r"^\|\s*Configuration option\s*\|\s*([^|]*?)\s*\|")
# Linha de tabela com a propriedade e o valor da primeira coluna de valor
_ROW = re.compile(r"^\|\s*(yarn\.[\w.-]+)\s*\|\s*([^|]*?)\s*\|")

_DEFAULT_COLUMN = "Default value"
_NODEMANAGER = "yarn.nodemanager.resource.memory-mb"
_MAX_ALLOCATION = "yarn.scheduler.maximum-allocation-mb"
_MIN_ALLOCATION = "yarn.scheduler.minimum-allocation-mb"
_USED = (_NODEMANAGER, _MAX_ALLOCATION, _MIN_ALLOCATION)


def parse_yarn_defaults(markdown: str) -> dict[str, YarnDefaults]:
    """Extrai {instance_type: YarnDefaults} do Markdown da página.

    Só a coluna de valor padrão é lida; a coluna "com HBase" é ignorada. Um tipo
    sem a linha do NodeManager é descartado, porque sem ela o registro não teria
    o campo que justifica a coleta; a falta aparece na cobertura.

    O que mostra que a página não é a esperada levanta SourceFormatError, para a
    coleta falhar em vez de publicar valor errado: cabeçalho cuja primeira coluna
    de valor não é a padrão (lê-la traria os valores "com HBase") e valor que não
    é número numa das três propriedades usadas.
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
        if line.startswith("#"):
            # seção nova: tabela que vier antes do próximo tipo não é do anterior
            close()
            current, values = None, {}
            continue
        if current is None:
            continue
        header_match = _HEADER.match(line)
        if header_match and header_match.group(1) != _DEFAULT_COLUMN:
            raise SourceFormatError(
                f"Tabela de YARN de {current} com a coluna "
                f"{header_match.group(1)!r} no lugar de {_DEFAULT_COLUMN!r}"
            )
        row_match = _ROW.match(line)
        if row_match and row_match.group(1) in _USED:
            name, value = row_match.groups()
            values[name] = _megabytes(current, name, value)
    close()
    return defaults


def _megabytes(instance_type: str, name: str, value: str) -> int:
    """Valor da coluna padrão em MB inteiros.

    A página usa inteiros e, em pelo menos um tipo (is4gen.xlarge, `17572.12`),
    decimal; os dois valem. Qualquer outra coisa é formato novo.
    """
    try:
        return round(float(value))
    except (ValueError, OverflowError):
        raise SourceFormatError(
            f"{name} de {instance_type} não é número: {value!r}"
        ) from None


def yarn_defaults() -> dict[str, YarnDefaults]:
    """Baixa a página e devolve os padrões de YARN por tipo de instância.

    Página fora do ar devolve vazio, e a falta derruba a coleta na checagem de
    cobertura. Página no ar sem nenhuma tabela reconhecida levanta
    SourceFormatError, como as anomalias que o parser encontra: nos dois casos a
    coleta falha e o workflow fica vermelho, em vez de publicar nulos.
    """
    try:
        response = requests.get(YARN_DOC_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(f"Erro ao buscar a página Task configuration do EMR: {e}")
        return {}
    defaults = parse_yarn_defaults(response.text)
    if not defaults:
        raise SourceFormatError(
            "A página Task configuration foi baixada, mas nenhuma tabela foi "
            "reconhecida: o formato da documentação provavelmente mudou."
        )
    return defaults
