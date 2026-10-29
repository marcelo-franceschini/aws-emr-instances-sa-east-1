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

# Janela do histórico de preço spot usada nas estatísticas por AZ. A API guarda
# até 90 dias; 30 cobre o ciclo mensal sem puxar o histórico inteiro.
SPOT_HISTORY_DAYS = 30

# Mesmo limite para os joins de catálogo (hardware do EC2, ofertas por AZ), que
# na prática cobrem 100% do universo do EMR. A folga existe para o dia em que o
# EMR anunciar suporte a um tipo antes de ele aparecer nas outras APIs — o que
# não pode passar batido é a fonte inteira cair.
MAX_MISSING_CATALOG_RATIO = 0.05
