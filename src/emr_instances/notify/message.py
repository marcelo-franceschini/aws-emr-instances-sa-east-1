"""Composição do título, do corpo e do link da notificação."""

from __future__ import annotations

from emr_instances.models import ReleaseAlert


def compose_notification(
    added: list[str], total_types: int, alerts: list[ReleaseAlert]
) -> tuple[str, str, str | None]:
    """Monta (título, mensagem, url) da notificação a partir do diff.

    Há notificação em toda execução (serve de heartbeat diário): sem novidade
    nenhuma, a mensagem é só a confirmação de que a coleta rodou.
    """
    if added:
        instances_line = (
            f"{len(added)} nova(s) instância(s) EMR disponível(is) em São Paulo."
        )
    else:
        instances_line = (
            f"Nenhuma instância nova. Total: {total_types} tipos suportados."
        )

    if not alerts:
        return "EMR sa-east-1", instances_line, None

    lines = [
        f"{alert['origin']}: {alert['previous']} → {alert['current']}"
        for alert in alerts
    ]
    message = "\n".join([*lines, instances_line])
    # quando o alerta do RSS existe ele é o último, e traz o link oficial
    return "EMR sa-east-1 — release novo", message, alerts[-1]["url"]
