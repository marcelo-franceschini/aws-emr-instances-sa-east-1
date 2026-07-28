"""Gera um JSON com as instâncias EMR suportadas em São Paulo (sa-east-1),
com o catálogo de hardware, preço on-demand, preço spot (Linux/UNIX) e taxa de
interrupção.

Fontes:
- Instâncias:  emr:ListSupportedInstanceTypes (define o universo)
- Hardware:    ec2:DescribeInstanceTypes
- Ofertas/AZ:  ec2:DescribeInstanceTypeOfferings
- On-demand:   pricing:GetProducts (Price List API — endpoint em us-east-1)
- Spot:        ec2:DescribeSpotPriceHistory
- Interrupção: Spot Bid Advisor (S3 público)
- Release novo: RSS de release notes do EMR (docs.aws.amazon.com)
"""

from __future__ import annotations

import argparse
import logging
import sys

from botocore.exceptions import BotoCoreError, ClientError

from emr_instances.aws import build_clients
from emr_instances.collector import build_payload, collect_records, validate_coverage
from emr_instances.config import OUTPUT_FILE
from emr_instances.errors import EmrInstancesError
from emr_instances.sources.emr import latest_release_label
from emr_instances.sources.release_notes import latest_announced_release
from emr_instances.storage import write_output

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release-label",
        help="Release label do EMR (ex.: emr-7.13.0). "
        "Se omitido, usa o mais recente disponível.",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help=f"Arquivo JSON de saída (padrão: {OUTPUT_FILE}).",
    )
    args = parser.parse_args()

    try:
        emr, ec2, pricing = build_clients()
        release_label = args.release_label or latest_release_label(emr)
        records = collect_records(emr, ec2, pricing, release_label)
        validate_coverage(records)
        logger.info("Consultando o RSS de release notes do EMR...")
        announced = latest_announced_release()
        logger.info(f"  último release anunciado: {announced or 'indisponível'}")
        write_output(build_payload(release_label, records, announced), args.output)
    except EmrInstancesError as e:
        logger.error(f"{e}")
        sys.exit(1)
    except (ClientError, BotoCoreError) as e:
        logger.error(f"Erro ao chamar API AWS: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Erro inesperado: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
