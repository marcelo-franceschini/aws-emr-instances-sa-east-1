# aws-emr-instances-sa-east-1

Coleta diariamente as instâncias EMR suportadas em **São Paulo (`sa-east-1`)**
com preço **on-demand** e **spot**, salva o resultado em JSON e avisa via
**Pushover** quando surgem instâncias novas.

## Como funciona

- [`main.py`](main.py) — gera `instances_sa-east-1.json` a partir de:
  - `emr:ListSupportedInstanceTypes` (lista de instâncias, release mais recente)
  - `pricing:GetProducts` (preço on-demand — Price List API, endpoint `us-east-1`)
  - `ec2:DescribeSpotPriceHistory` (spot, menor preço entre as AZs)
- [`notify.py`](notify.py) — compara o JSON novo com o anterior e, se houver
  instâncias novas, notifica a quantidade via Pushover.
- [`.github/workflows/daily.yml`](.github/workflows/daily.yml) — roda tudo via
  cron diário (09:00 UTC), publica o JSON na branch órfã **`data`** e dispara a
  notificação.

O JSON gerado **não** fica na branch de código — ele vive apenas na branch `data`.

## Rodar localmente

```bash
uv run main.py            # gera instances_sa-east-1.json
```

Requer credenciais AWS com permissão de leitura para EMR, Pricing e EC2 spot.

## Secrets necessários (GitHub Actions)

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `PUSHOVER_TOKEN`, `PUSHOVER_USER`.
