"""Testes para emr_instances.notify.message"""

from __future__ import annotations

from emr_instances.models import ReleaseAlert
from emr_instances.notify.message import compose_notification

LABEL_ALERT: ReleaseAlert = {
    "origin": "Disponível em sa-east-1",
    "previous": "emr-7.13.0",
    "current": "emr-7.14.0",
    "url": "https://docs.aws.amazon.com/x/emr-7140-release.html",
}
ANNOUNCED_ALERT: ReleaseAlert = {
    "origin": "Anunciado pela AWS",
    "previous": "7.13.0",
    "current": "7.14.0",
    "url": "https://docs.aws.amazon.com/x/rss-7140.html",
}


def test_sem_novidade_nenhuma() -> None:
    """Heartbeat: sem instância nova e sem release novo, informa o total."""
    title, message, url = compose_notification([], 42, [])

    assert title == "EMR sa-east-1"
    assert message == "Nenhuma instância nova. Total: 42 tipos suportados."
    assert url is None


def test_so_instancias_novas() -> None:
    """Instâncias novas sem release novo: título normal, sem link."""
    title, message, url = compose_notification(["c6g.large", "c6g.xlarge"], 42, [])

    assert title == "EMR sa-east-1"
    assert message.startswith("2 nova(s) instância(s)")
    assert url is None


def test_so_release_novo() -> None:
    """Release novo sem instância nova: título destacado e link do alerta."""
    title, message, url = compose_notification([], 42, [LABEL_ALERT])

    assert title == "EMR sa-east-1 — release novo"
    assert message.splitlines() == [
        "Disponível em sa-east-1: emr-7.13.0 → emr-7.14.0",
        "Nenhuma instância nova. Total: 42 tipos suportados.",
    ]
    assert url == LABEL_ALERT["url"]


def test_release_novo_com_instancias_novas() -> None:
    """As duas origens viram linhas; o link é o do último alerta (o do RSS)."""
    title, message, url = compose_notification(
        ["c6g.large"], 42, [LABEL_ALERT, ANNOUNCED_ALERT]
    )

    assert title == "EMR sa-east-1 — release novo"
    assert message.splitlines() == [
        "Disponível em sa-east-1: emr-7.13.0 → emr-7.14.0",
        "Anunciado pela AWS: 7.13.0 → 7.14.0",
        "1 nova(s) instância(s) EMR disponível(is) em São Paulo.",
    ]
    assert url == ANNOUNCED_ALERT["url"]
