"""Compara o JSON recém-gerado com o anterior e notifica via Pushover.

Envia uma notificação em TODA execução (também serve de heartbeat diário):
- Release novo do EMR: informa a mudança e manda o link das release notes.
- Com instâncias novas: informa a QUANTIDADE de instâncias novas.
- Sem nenhuma novidade: envia uma confirmação de que a coleta rodou.
- Primeira execução (sem JSON anterior): tudo conta como novo.

Lê PUSHOVER_TOKEN e PUSHOVER_USER do ambiente. Usa só a biblioteca padrão.
"""

from __future__ import annotations

import argparse
import logging
import sys

from emr_instances.config import OUTPUT_FILE, PREVIOUS_FILE
from emr_instances.errors import EmrInstancesError
from emr_instances.notify.diff import diff_new, instance_types, release_alerts
from emr_instances.notify.message import compose_notification
from emr_instances.notify.pushover import send_pushover
from emr_instances.storage import load_snapshot

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new", default=OUTPUT_FILE)
    parser.add_argument("--old", default=PREVIOUS_FILE)
    args = parser.parse_args()

    try:
        new_snapshot = load_snapshot(args.new)
        old_snapshot = load_snapshot(args.old)

        new_types = instance_types(new_snapshot)
        added = diff_new(new_types, instance_types(old_snapshot))
        logger.info(f"Instâncias novas: {len(added)}")

        alerts = release_alerts(new_snapshot, old_snapshot)
        for alert in alerts:
            logger.info(
                f"Release novo ({alert['origin']}): "
                f"{alert['previous']} → {alert['current']}"
            )

        title, message, url = compose_notification(added, len(new_types), alerts)
        send_pushover(title=title, message=message, url=url)
    except EmrInstancesError as e:
        logger.error(f"{e}")
        sys.exit(1)
    logger.info("Notificação enviada via Pushover.")


if __name__ == "__main__":
    main()
