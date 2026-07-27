"""Modelo de domínio — os TypedDicts abaixo são serializados direto para JSON."""

from __future__ import annotations

from typing import TypedDict


class SpotInfo(TypedDict):
    usd_hour: float
    az: str


class SpotInterruption(TypedDict):
    savings_percent: int | None
    interruption_rate: int | None


class OnDemandInfo(TypedDict):
    usd_hour: float
    network_performance: str | None


class InstanceRecord(TypedDict):
    instance_type: str
    vcpu: int | None
    memory_gb: float | None
    architecture: str | None
    network_performance: str | None
    network_gbps: float | None
    on_demand_usd_hour: float | None
    spot: SpotInfo | None
    spot_interruption: SpotInterruption | None


class AnnouncedRelease(TypedDict):
    version: str
    url: str
    published_at: str


class Payload(TypedDict):
    region: str
    release_label: str
    latest_announced_release: AnnouncedRelease | None
    generated_at: str
    instance_count: int
    instances: list[InstanceRecord]


class SnapshotInstance(TypedDict, total=False):
    """Instância dentro de um snapshot lido de disco.

    Declara só o campo que o caminho de leitura consome — o diff compara
    conjuntos de instance_type e ignora o resto do registro.
    """

    instance_type: str


class Snapshot(TypedDict, total=False):
    """Payload lido de disco — todo campo é opcional.

    O arquivo anterior pode ser de uma versão do schema que ainda não gravava
    algum campo (foi o caso de `latest_announced_release`), ou não existir. Ler
    como `Payload` seria mentira; `total=False` diz a verdade e ainda deixa o
    mypy conferir os nomes das chaves no caminho de leitura.
    """

    region: str
    release_label: str
    latest_announced_release: AnnouncedRelease | None
    generated_at: str
    instance_count: int
    instances: list[SnapshotInstance]


class ReleaseAlert(TypedDict):
    origin: str
    previous: str
    current: str
    url: str
