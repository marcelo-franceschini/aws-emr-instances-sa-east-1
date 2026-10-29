"""Exceções de domínio do projeto.

As camadas internas (coleta, storage) levantam estes erros; só a
camada `cli/` os traduz em código de saída. Isso mantém os módulos reutilizáveis
e testáveis sem precisar capturar `SystemExit`.
"""

from __future__ import annotations


class EmrInstancesError(Exception):
    """Base de todos os erros previstos do projeto."""


class CoverageError(EmrInstancesError):
    """A cobertura de preços ficou abaixo do mínimo aceitável."""


class StorageError(EmrInstancesError):
    """Falha ao gravar o JSON em disco."""


class SourceFormatError(EmrInstancesError):
    """Uma fonte de fora das APIs mudou de formato e o parser não a reconhece.

    Existe para a coleta falhar alto em vez de publicar valores errados ou nulos:
    quem lê a página por regex não tem outro jeito de saber que ela mudou.
    """
