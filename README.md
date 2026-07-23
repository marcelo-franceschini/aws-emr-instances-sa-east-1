# aws-emr-instances-sa-east-1

Coleta diariamente as instâncias EMR suportadas em **São Paulo (`sa-east-1`)**
com preço **on-demand** e **spot**, salva o resultado em JSON e avisa via
**Pushover** quando surgem instâncias novas.

## Como funciona

- [`main.py`](main.py) — gera `instances_sa-east-1.json` a partir de:
  - `emr:ListSupportedInstanceTypes` (lista de instâncias, release mais recente)
  - `pricing:GetProducts` (preço on-demand + network performance — Price List API, endpoint `us-east-1`)
  - `ec2:DescribeSpotPriceHistory` (spot, menor preço entre as AZs)
  - Spot Bid Advisor (S3 público) (frequência de interrupção + economia esperada)
- [`notify.py`](notify.py) — compara o JSON novo com o anterior e, se houver
  instâncias novas, notifica a quantidade via Pushover.
- [`.github/workflows/daily.yml`](.github/workflows/daily.yml) — roda tudo via
  cron diário (09:00 UTC), publica o JSON na branch órfã **`data`** e dispara a
  notificação.

O JSON gerado **não** fica na branch de código — ele vive apenas na branch `data`.

### Estrutura do JSON

Cada instância contém:
- `instance_type` — ex: `m5.large`
- `vcpu`, `memory_gb`, `architecture` — especificações
- `network_performance` — ex: `"Up to 10 Gigabit"`, `"25 Gigabit"`, `"Moderate"` (importante para shuffles em MapReduce)
- `on_demand_usd_hour` — preço on-demand (USD/hora)
- `spot` — `{"usd_hour": ..., "az": ...}` (menor preço entre as AZs)
- `spot_interruption` — `{"savings_percent": ..., "interruption_rate": ...}` (do Spot Bid Advisor, onde `interruption_rate` é 1-5: <5%, 5-10%, 10-15%, 15-20%, >20%)

## Rodar localmente

```bash
uv run main.py            # gera instances_sa-east-1.json
```

Requer credenciais AWS com permissão de leitura para EMR, Pricing e EC2 spot.

### Testes e type checking

```bash
uv run pytest             # executa testes
uv run mypy .             # verifica tipos
```

## Deploy inicial (do zero)

Para replicar este projeto do zero em sua própria conta AWS:

1. **Criar usuário IAM dedicado** (sem acesso ao console):
   - Nome: `aws-emr-instances-sa-east-1`
   - Criar uma policy **customer-managed** com as 4 permissões mínimas:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Effect": "Allow",
           "Action": [
             "elasticmapreduce:ListSupportedInstanceTypes",
             "elasticmapreduce:ListReleaseLabels",
             "pricing:GetProducts",
             "ec2:DescribeSpotPriceHistory"
           ],
           "Resource": "*"
         }
       ]
     }
     ```
   - Gerar **access key** (ID + Secret).

2. **Configurar credenciais localmente** (para rodar `main.py` localmente):
   ```bash
   aws configure --profile sa-east-1
   # Coloque Access Key ID e Secret
   # Região: sa-east-1
   export AWS_PROFILE=sa-east-1
   ```

3. **Criar app no Pushover**:
   - Acesse https://pushover.net/apps e crie uma aplicação.
   - Copie o **PUSHOVER_TOKEN** (começa com `a`).
   - Confirme a **PUSHOVER_USER** key pessoal (começa com `u`).
   - ⚠️ Cuidado: não trocar os dois.

4. **Cadastrar 4 secrets no GitHub**:
   - Vá a **Settings → Secrets and variables → Actions**.
   - Adicione:
     - `AWS_ACCESS_KEY_ID`
     - `AWS_SECRET_ACCESS_KEY`
     - `PUSHOVER_TOKEN`
     - `PUSHOVER_USER`

5. **Disparar o workflow pela primeira vez**:
   - Vá a **Actions → EMR instances (sa-east-1) → Run workflow → Run workflow**.
   - Ou faça um push para `master` (o workflow é acionado pelo `push`).
   - ⚠️ Em repositórios novos, o primeiro push às vezes não registra o workflow na aba Actions — faça um segundo push ou disparo manual.

6. **Confirmar sucesso**:
   - Verifique que a branch **`data`** foi criada com o arquivo `instances_sa-east-1.json`.
   - Se houver instâncias novas, receberá notificação no Pushover.

## Secrets necessários (GitHub Actions)

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `PUSHOVER_TOKEN`, `PUSHOVER_USER`.
