"""Constantes de configuração compartilhadas pela coleta e pela notificação."""

from __future__ import annotations

REGION = "sa-east-1"
PRICING_ENDPOINT_REGION = "us-east-1"

OUTPUT_FILE = "instances_sa-east-1.json"
PREVIOUS_FILE = "previous.json"

MAX_MISSING_PRICE_RATIO = 0.05  # 5% de preços faltando é limite de alerta/erro

RELEASE_NOTES_RSS = (
    "https://docs.aws.amazon.com/emr/latest/ReleaseGuide/amazon-emr-release-notes.rss"
)
RELEASE_NOTES_BASE = "https://docs.aws.amazon.com/emr/latest/ReleaseGuide"
SPOT_ADVISOR_URL = "https://spot-bid-advisor.s3.amazonaws.com/spot-advisor-data.json"

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
