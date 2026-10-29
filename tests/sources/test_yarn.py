"""Testes para emr_instances.sources.yarn"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from emr_instances.sources import yarn

# Recorte no formato real da página Task configuration (versão em Markdown):
# cada tabela vem depois de uma linha só com o tipo em negrito.
DOC_FIXTURE = """# Task configuration

Texto introdutório que menciona yarn.nodemanager.resource.memory-mb sem tabela.

### c5 instances
<a name="emr-hadoop-task-config-c5"></a>


**c5.xlarge**

| Configuration option | Default value | With HBase installed |
| --- | --- | --- |
| mapreduce.map.java.opts | -Xmx1229m | -Xmx1229m |
| mapreduce.map.memory.mb | 1536 | 1536 |
| yarn.scheduler.minimum-allocation-mb | 1 | 1 |
| yarn.scheduler.maximum-allocation-mb | 6144 | 3072 |
| yarn.nodemanager.resource.memory-mb | 6144 | 3072 |


**c5.9xlarge**

| Configuration option | Default value | With HBase installed |
| --- | --- | --- |
| yarn.scheduler.minimum-allocation-mb | 1 | 1 |
| yarn.scheduler.maximum-allocation-mb | 90112 | 30048 |
| yarn.nodemanager.resource.memory-mb | 90112 | 30048 |

### c7i-flex instances
<a name="emr-hadoop-task-config-c7i-flex"></a>


**c7i-flex.large**

| Configuration option | Default value | With HBase installed |
| --- | --- | --- |
| yarn.nodemanager.resource.memory-mb | 3072 | 1536 |


**m5.large**

| Configuration option | Default value | With HBase installed |
| --- | --- | --- |
| mapreduce.map.memory.mb | 1536 | 1536 |
"""


def test_parse_le_a_coluna_padrao_e_ignora_a_de_hbase() -> None:
    """Os valores vêm da primeira coluna; a de HBase não entra."""
    result = yarn.parse_yarn_defaults(DOC_FIXTURE)

    assert result["c5.xlarge"] == {
        "nodemanager_memory_mb": 6144,
        "scheduler_max_allocation_mb": 6144,
        "scheduler_min_allocation_mb": 1,
    }
    # o padrão é 90112; com HBase seria 30048
    assert result["c5.9xlarge"]["nodemanager_memory_mb"] == 90112


def test_parse_aceita_tipo_com_hifen_e_campos_opcionais_ausentes() -> None:
    """`c7i-flex.large` só tem a linha do NodeManager: os outros campos ficam None."""
    result = yarn.parse_yarn_defaults(DOC_FIXTURE)

    assert result["c7i-flex.large"] == {
        "nodemanager_memory_mb": 3072,
        "scheduler_max_allocation_mb": None,
        "scheduler_min_allocation_mb": None,
    }


def test_parse_descarta_tipo_sem_a_linha_do_nodemanager() -> None:
    """Sem `yarn.nodemanager.resource.memory-mb` o registro não teria o que importa."""
    assert "m5.large" not in yarn.parse_yarn_defaults(DOC_FIXTURE)


def test_parse_ignora_texto_fora_de_tabela() -> None:
    """A menção solta à propriedade no texto introdutório não vira registro."""
    assert set(yarn.parse_yarn_defaults(DOC_FIXTURE)) == {
        "c5.xlarge",
        "c5.9xlarge",
        "c7i-flex.large",
    }


def test_parse_markdown_sem_tabelas_devolve_vazio() -> None:
    """Formato desconhecido não levanta: devolve vazio."""
    assert yarn.parse_yarn_defaults("# Outra página\n\nsem tabelas") == {}
    assert yarn.parse_yarn_defaults("") == {}


def test_yarn_defaults_baixa_a_pagina_e_interpreta() -> None:
    """Fluxo completo com a requisição HTTP mockada."""
    response = MagicMock()
    response.text = DOC_FIXTURE
    response.raise_for_status.return_value = None

    with patch("emr_instances.sources.yarn.requests.get", return_value=response) as get:
        result = yarn.yarn_defaults()

    assert get.call_args.args[0] == yarn.YARN_DOC_URL
    assert result["c5.xlarge"]["nodemanager_memory_mb"] == 6144


def test_yarn_defaults_pagina_indisponivel_devolve_vazio(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Falha de rede não derruba a coleta: avisa e devolve vazio."""
    with (
        patch(
            "emr_instances.sources.yarn.requests.get",
            side_effect=requests.RequestException("sem rede"),
        ),
        caplog.at_level(logging.WARNING),
    ):
        assert yarn.yarn_defaults() == {}

    assert "Task configuration" in caplog.text


def test_yarn_defaults_formato_mudou_loga_erro(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Página no ar sem nenhuma tabela reconhecida é mudança de formato: erro."""
    response = MagicMock()
    response.text = "# Task configuration\n\nA documentação foi reescrita."
    response.raise_for_status.return_value = None

    with (
        patch("emr_instances.sources.yarn.requests.get", return_value=response),
        caplog.at_level(logging.ERROR),
    ):
        assert yarn.yarn_defaults() == {}

    assert "formato" in caplog.text
