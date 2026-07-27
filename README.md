# aws-emr-instances-sa-east-1

Coleta diariamente as instâncias EMR suportadas em **São Paulo (`sa-east-1`)**
com preço **on-demand** e **spot**, salva o resultado em JSON e avisa via
**Pushover** quando surgem instâncias novas ou um **release novo do EMR**.

## Como funciona

- `emr-collect` — gera `instances_sa-east-1.json` a partir de:
  - `emr:ListSupportedInstanceTypes` (lista de instâncias, release mais recente)
  - `pricing:GetProducts` (preço on-demand + network performance — Price List API, endpoint `us-east-1`)
  - `ec2:DescribeSpotPriceHistory` (spot, menor preço entre as AZs)
  - Spot Bid Advisor (S3 público) (frequência de interrupção + economia esperada)
  - [RSS de release notes do EMR](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/amazon-emr-release-notes.rss) (último release anunciado pela AWS)
- `emr-notify` — compara o JSON novo com o anterior e notifica via
  Pushover em toda execução (serve de heartbeat).
- [`.github/workflows/daily.yml`](.github/workflows/daily.yml) — roda tudo via
  cron diário (09:00 UTC), publica o JSON na branch órfã **`data`** e dispara a
  notificação.

### Estrutura do pacote

Os dois comandos são console scripts declarados no [`pyproject.toml`](pyproject.toml),
apontando para o pacote em [`src/emr_instances/`](src/emr_instances/):

```
src/emr_instances/
├── config.py                    config compartilhada (região, arquivos, limites)
├── errors.py                    exceções de domínio; só o cli/ vira código de saída
├── models.py                    TypedDicts do domínio, serializados direto pro JSON
├── aws.py                       clients boto3 com retry adaptativo
├── storage.py                   leitura/escrita dos snapshots JSON
├── collector.py                 junta as fontes, valida cobertura, monta o payload
├── sources/                     uma fonte de dados externa por módulo
│   ├── emr.py                   ListSupportedInstanceTypes / ListReleaseLabels
│   ├── pricing.py               Price List API + parse de network_gbps
│   ├── spot.py                  DescribeSpotPriceHistory + Spot Bid Advisor
│   └── release_notes.py         RSS de release notes
├── notify/
│   ├── diff.py                  instâncias novas e mudanças de release
│   ├── message.py               monta título, corpo e link da notificação
│   └── pushover.py              envio (só biblioteca padrão)
└── cli/
    ├── collect.py               entrypoint do emr-collect
    └── notify.py                entrypoint do emr-notify
```

Os testes em [`tests/`](tests/) espelham essa estrutura.

O endpoint de cada serviço externo mora no módulo que fala com ele (o RSS em
`sources/release_notes.py`, o Spot Advisor em `sources/spot.py`, a API do
Pushover em `notify/pushover.py`) — `config.py` guarda só o que é transversal.

As camadas internas levantam as exceções de [`errors.py`](src/emr_instances/errors.py)
(`CoverageError`, `StorageError`, `NotificationError`); apenas os entrypoints em
`cli/` as traduzem em `exit(1)`. Isso mantém os módulos reutilizáveis e testáveis
sem precisar capturar `SystemExit`.

### Aviso de release novo

O EMR é monitorado por duas fontes independentes, que costumam mudar em datas
diferentes:

| Origem | Campo comparado | Quando dispara |
| --- | --- | --- |
| `Anunciado pela AWS` | `latest_announced_release.version` | no dia do anúncio no RSS |
| `Disponível em sa-east-1` | `release_label` | quando o release chega na região |

Quando qualquer uma muda (ex.: `7.13.0` → `7.14.0`), a notificação vem com o
título **"EMR sa-east-1 — release novo"** e o link das release notes clicável
(ex.: `https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-7130-release.html`).

Só entram releases do **EMR on EC2 padrão** — o RSS também anuncia linhas
especiais como `emr-spark-8.0.0`, que são ignoradas. Um alerta só é emitido
quando o valor existe nos **dois** snapshots e é diferente, de modo que a
primeira execução e uma indisponibilidade do RSS não viram falso alarme.

O JSON gerado **não** fica na branch de código — ele vive apenas na branch `data`.

### Estrutura do JSON

No envelope:
- `region`, `generated_at`, `instance_count`
- `release_label` — release usado na coleta, o mais recente disponível em `sa-east-1` (ex: `"emr-7.13.0"`)
- `latest_announced_release` — último release anunciado no RSS: `{"version": "7.13.0", "url": ..., "published_at": ...}`, ou `null` se o feed estiver indisponível

Cada instância contém:
- `instance_type` — ex: `m5.large`
- `vcpu`, `memory_gb`, `architecture` — especificações
- `network_performance` — ex: `"Up to 10 Gigabit"`, `"25 Gigabit"`, `"Moderate"` (importante para shuffles em MapReduce)
- `network_gbps` — valor numérico em Gbps extraído de `network_performance` (ex: `10.0`), ou `null` para valores qualitativos (`"Moderate"`, `"High"`); facilita ordenar/comparar por rede
- `on_demand_usd_hour` — preço on-demand (USD/hora)
- `spot` — `{"usd_hour": ..., "az": ...}` (menor preço entre as AZs)
- `spot_interruption` — `{"savings_percent": ..., "interruption_rate": ...}` (do Spot Bid Advisor, onde `interruption_rate` é 1-5: <5%, 5-10%, 10-15%, 15-20%, >20%)

## Rodar localmente

```bash
uv sync                   # instala o pacote (editable) e as dependências
uv run emr-collect        # gera instances_sa-east-1.json
uv run emr-collect --help # opções: --release-label, --output
```

Requer credenciais AWS com permissão de leitura para EMR, Pricing e EC2 spot.

Para testar a notificação, com `PUSHOVER_TOKEN` e `PUSHOVER_USER` no ambiente:

```bash
uv run emr-notify --new instances_sa-east-1.json --old previous.json
```

### Testes e type checking

```bash
uv sync --dev             # inclui pytest, mypy, ruff e os stubs do boto3
uv run pytest             # executa testes
uv run mypy .             # verifica tipos
uv run ruff check .       # lint
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

2. **Configurar credenciais localmente** (para rodar `emr-collect` localmente):
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
   - A coleta diária roda por agendamento (cron) ou por esse disparo manual —
     **não** por `push`. Um push para `master` aciona apenas o CI (lint/mypy/testes).
   - ⚠️ Em repositórios novos, o workflow só aparece na aba Actions depois do
     primeiro push do arquivo — se não aparecer, faça um push e recarregue a página.

6. **Confirmar sucesso**:
   - Verifique que a branch **`data`** foi criada com o arquivo `instances_sa-east-1.json`.
   - A notificação no Pushover chega em toda execução; ela destaca instâncias
     novas e releases novos do EMR quando houver.

## Secrets necessários (GitHub Actions)

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `PUSHOVER_TOKEN`, `PUSHOVER_USER`.
