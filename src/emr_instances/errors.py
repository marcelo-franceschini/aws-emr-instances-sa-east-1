"""Exceções de domínio do projeto.

As camadas internas (coleta, storage, notificação) levantam estes erros; só a
camada `cli/` os traduz em código de saída. Isso mantém os módulos reutilizáveis
e testáveis sem precisar capturar `SystemExit`.
"""

from __future__ import annotations


class EmrInstancesError(Exception):
    """Base de todos os erros previstos do projeto."""


class CoverageError(EmrInstancesError):
    """A cobertura de preços ficou abaixo do mínimo aceitável."""


class StorageError(EmrInstancesError):
    """Falha ao gravar ou ler um snapshot em disco."""


class NotificationError(EmrInstancesError):
    """Falha ao enviar a notificação (configuração ausente ou API recusou)."""
