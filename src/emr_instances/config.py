"""Configuração compartilhada por mais de um módulo do projeto.

Endpoint de terceiro fica no módulo que fala com aquele serviço; aqui entra só
o que é transversal ou que se pode querer ajustar (região, arquivos, limites).
"""

from __future__ import annotations

REGION = "sa-east-1"
PRICING_ENDPOINT_REGION = "us-east-1"

OUTPUT_FILE = "instances_sa-east-1.json"
PREVIOUS_FILE = "previous.json"

MAX_MISSING_PRICE_RATIO = 0.05  # 5% de preços faltando é limite de alerta/erro
