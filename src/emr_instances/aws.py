"""Criação dos clients boto3 usados pela coleta."""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from emr_instances.config import PRICING_ENDPOINT_REGION, REGION

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client
    from mypy_boto3_emr import EMRClient
    from mypy_boto3_pricing import PricingClient


def build_clients() -> tuple[EMRClient, EC2Client, PricingClient]:
    """Cria os clients boto3 com retry adaptativo compartilhado."""
    retry_config = Config(retries={"max_attempts": 5, "mode": "adaptive"})
    emr = boto3.client("emr", region_name=REGION, config=retry_config)
    ec2 = boto3.client("ec2", region_name=REGION, config=retry_config)
    pricing = boto3.client(
        "pricing", region_name=PRICING_ENDPOINT_REGION, config=retry_config
    )
    return emr, ec2, pricing
