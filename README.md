# aws-emr-instances-sa-east-1

Catálogo diário das instâncias EMR suportadas em **São Paulo (`sa-east-1`)**:
para cada uma das 465, o **hardware completo** (vCPU, cores, memória, disco,
banda de EBS e de rede com baseline e pico, clock, GPU, AZs) e o **preço**
on-demand e spot com taxa de interrupção. Salva tudo em JSON e avisa via
**Pushover** quando surgem instâncias novas ou um **release novo do EMR**.

O JSON é rico o bastante para responder "esta carga cabe nesta máquina?" e não
só "quanto custa" — ver [Estrutura do JSON](#estrutura-do-json) para o formato e
[Fora de escopo](#fora-de-escopo) para a peça que falta.

## Como funciona

- `emr-collect` — gera `instances_sa-east-1.json` a partir de:
  - `emr:ListSupportedInstanceTypes` (lista de instâncias, release mais recente)
  - `ec2:DescribeInstanceTypes` (catálogo de hardware: vCPU, memória, disco, EBS, rede, clock, GPU)
  - `ec2:DescribeInstanceTypeOfferings` (em quais AZs cada tipo é ofertado)
  - `pricing:GetProducts` (preço on-demand + nome do processador, categoria de família e fator de normalização — Price List API, endpoint `us-east-1`)
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
│   ├── ec2.py                   DescribeInstanceTypes / DescribeInstanceTypeOfferings
│   ├── pricing.py               Price List API (preço + 3 campos de catálogo)
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
- `schema_version` — versão do formato (atual: `2`)
- `latest_announced_release` — último release anunciado no RSS: `{"version": "7.13.0", "url": ..., "published_at": ...}`, ou `null` se o feed estiver indisponível

Cada instância tem `instance_type` no topo e dois blocos separados **por
mutabilidade**: `static` nunca muda para um dado tipo de instância (pode ser
congelado, versionado e usado como constante) e `pricing` muda todo dia e vem
datado.

```json
{
  "instance_type": "r8gd.4xlarge",
  "static": {
    "vcpu": 16, "cores": 16, "threads_per_core": 1,
    "memory_gb_emr": 122.0, "memory_gb_hardware": 128.0,
    "architecture": "arm64",
    "processor_manufacturer": "AWS", "processor_name": "AWS Graviton4 Processor",
    "clock_ghz_sustained": 2.8,
    "family_category": "Memory optimized", "family_id_emr": "HI_MEM_CURRENT_GEN",
    "current_generation": true, "bare_metal": false, "hypervisor": "nitro",
    "burstable_performance": false, "normalization_factor": 32,
    "supports_spot": true,
    "availability_zones": ["sa-east-1a", "sa-east-1b", "sa-east-1c"],
    "storage": { "ebs_only": false, "total_gb": 950, "nvme": "required",
                 "disks": [{ "count": 1, "size_gb": 950, "type": "ssd" }] },
    "ebs": { "baseline_mbps": 5000, "maximum_mbps": 10000,
             "baseline_iops": 20000, "maximum_iops": 40000,
             "burstable": true, "optimized_by_default": true, "nvme": "required" },
    "network": { "baseline_gbps": 7.5, "peak_gbps": 15.0, "burstable": true,
                 "max_interfaces": 8, "ena": "required", "efa": false },
    "gpu": null
  },
  "pricing": {
    "as_of": "2026-07-27T12:15:33+00:00",
    "on_demand_usd_hour": 1.8616,
    "spot": { "usd_hour": 1.1793, "az": "sa-east-1c" },
    "spot_interruption": { "savings_percent": 46, "interruption_rate": 4 }
  }
}
```

Alguns campos merecem explicação:

- **`memory_gb_emr` e `memory_gb_hardware` são valores diferentes de propósito.**
  O EMR reporta menos memória que o hardware em 352 dos 465 tipos (razão ~0.953);
  um é o que a máquina tem, o outro é o que o EMR enxerga. **Nenhum dos dois é a
  memória alocável pelo YARN**, que tem um corte bem maior — veja
  [Fora de escopo](#fora-de-escopo).
- **`baseline` e `maximum` (em `ebs` e `network`) são a diferença entre pico e
  sustentado**, que é o que decide o comportamento de um job Spark longo: 159
  tipos fazem burst de EBS e 228 de rede. As `flex` são o caso extremo —
  `c7i-flex.xlarge` vai de 625 a 10000 Mbps de EBS, 16x. Quando o crédito acaba,
  o job cai para o baseline. O booleano `burstable` é derivado (`maximum >
  baseline`) para o consumidor não precisar comparar.
- **`interruption_rate`** é 1-5, do Spot Bid Advisor: <5%, 5-10%, 10-15%, 15-20%, >20%.
- **`nvme` e `ena`** são `"required"`, `"supported"` ou `"unsupported"`.
- Campo ausente vem como `null` e **o bloco nunca some** — `storage` existe
  mesmo em instância EBS-only (com `ebs_only: true` e `disks: []`), e `gpu` é
  `null` nas 439 sem GPU. Quem consome nunca precisa checar se a chave existe.

O universo é sempre o que o `ListSupportedInstanceTypes` devolve: há 22 tipos
ofertados em `sa-east-1` (`m6in.*`, `m6idn.*`, `r7gd.*`) que o `emr-7.13.0` não
suporta e que por isso não entram no JSON.

Onde duas fontes têm o mesmo dado, a precedência é: **hardware** vem do
`DescribeInstanceTypes` (é numérico e estruturado; a Price List só tem string —
o campo `storage` dela chega a ter 93 formatos diferentes), **nome comercial do
processador e categoria de família** vêm da Price List (o EC2 só informa o
fabricante, `"AWS"`), e **o universo e o suporte do EMR** vêm sempre do EMR.

#### Versões do schema

| Versão | Formato |
| --- | --- |
| 1 | registro plano de 9 campos, sem `schema_version` |
| 2 | `static` / `pricing`, catálogo completo de hardware |

`instance_type` fica no topo do registro nas duas versões — é o que o diff da
notificação compara, e é o que garante que a troca de schema não vire um alerta
falso de "465 instâncias novas" no primeiro run após o deploy.

## Rodar localmente

```bash
uv sync                   # instala o pacote (editable) e as dependências
uv run emr-collect        # gera instances_sa-east-1.json
uv run emr-collect --help # opções: --release-label, --output
```

Requer credenciais AWS com permissão de leitura para EMR, Pricing e EC2 (spot e
catálogo de instâncias) — a policy completa está em [Deploy inicial](#deploy-inicial-do-zero).

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
   - Criar uma policy **customer-managed** com as 6 permissões mínimas:
     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Sid": "EmrList",
           "Effect": "Allow",
           "Action": [
             "elasticmapreduce:ListSupportedInstanceTypes",
             "elasticmapreduce:ListReleaseLabels"
           ],
           "Resource": "*"
         },
         {
           "Sid": "Pricing",
           "Effect": "Allow",
           "Action": [
             "pricing:GetProducts",
             "ec2:DescribeSpotPriceHistory"
           ],
           "Resource": "*"
         },
         {
           "Sid": "Ec2InstanceCatalog",
           "Effect": "Allow",
           "Action": [
             "ec2:DescribeInstanceTypes",
             "ec2:DescribeInstanceTypeOfferings"
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

## Fora de escopo

**A memória alocável pelo YARN por tipo de instância**
(`yarn.nodemanager.resource.memory-mb`) não vem de API nenhuma — está nas páginas
de *Task configuration* da documentação do EMR, uma por release. É a constante
que falta para sair de "specs da máquina" e chegar em "quantos executores
cabem": nem `memory_gb_hardware` nem `memory_gb_emr` substituem ela, porque o
corte do YARN é bem maior que a diferença entre os dois. Vale uma tarefa
própria, provavelmente com scraping da doc por release.
