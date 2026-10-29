# aws-emr-instances-sa-east-1

Catálogo diário das instâncias EMR suportadas em **São Paulo (`sa-east-1`)**:
para cada uma das 465, o **hardware completo** (vCPU, cores, memória, disco,
banda de EBS e de rede com baseline e pico, clock, GPU, AZs), o **preço**
on-demand, a **taxa do EMR**, o **spot por AZ com estatísticas** de 30 dias e a
taxa de interrupção, a **memória alocável pelo YARN** e **campos derivados**
(razões e custo por unidade) prontos para filtrar. Salva tudo em JSON.

O JSON é rico o bastante para responder "esta carga cabe nesta máquina e quanto
ela custa de verdade?" e não só "quanto custa o EC2". Ver
[Estrutura do JSON](#estrutura-do-json) para o formato,
[Consultando com jq](#consultando-com-jq) para exemplos e
[Fora de escopo](#fora-de-escopo) para o que ficou de fora.

## Como funciona

- `emr-collect` — gera `instances_sa-east-1.json` a partir de:
  - `emr:ListSupportedInstanceTypes` (lista de instâncias, release mais recente)
  - `ec2:DescribeInstanceTypes` (catálogo de hardware: vCPU, memória, disco, EBS, rede, clock, GPU)
  - `ec2:DescribeInstanceTypeOfferings` (em quais AZs cada tipo é ofertado)
  - `pricing:GetProducts` (preço on-demand + nome do processador, categoria de família e fator de normalização — Price List API, endpoint `us-east-1`)
  - `pricing:GetProducts` no serviço `ElasticMapReduce` (taxa do EMR por instância-hora)
  - `ec2:DescribeSpotPriceHistory` (30 dias por AZ: preço vigente e estatísticas ponderadas pelo tempo)
  - Spot Bid Advisor (S3 público) (frequência de interrupção + economia esperada)
  - Página [Task configuration](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-hadoop-task-config.html) da documentação do EMR, em Markdown (padrões de YARN por tipo)
- [`.github/workflows/daily.yml`](.github/workflows/daily.yml) — roda tudo via
  cron diário (09:00 UTC) e publica o JSON na branch órfã **`data`**.

A coleta falha (código de saída 1, workflow vermelho e o e-mail de falha que o
GitHub já manda) quando uma fonte essencial some: mais de 5% das instâncias sem
preço on-demand, spot, taxa do EMR, hardware, oferta por AZ ou detalhe de disco,
ou mais de 25% sem padrões de YARN ou sem taxa de interrupção (dados públicos de
fora das APIs; a folga cobre tipos que eles ainda não listam). Nesse caso nada é
publicado e a branch `data` continua com o último JSON bom.

### Estrutura do pacote

O comando é um console script declarado no [`pyproject.toml`](pyproject.toml),
apontando para o pacote em [`src/emr_instances/`](src/emr_instances/):

```
src/emr_instances/
├── config.py                    config compartilhada (região, arquivos, limites)
├── errors.py                    exceções de domínio; só o cli/ vira código de saída
├── models.py                    TypedDicts do domínio, serializados direto pro JSON
├── derived.py                   bloco `derived`: razões e custo por unidade
├── aws.py                       clients boto3 com retry adaptativo
├── storage.py                   escrita do JSON gerado
├── collector.py                 junta as fontes, valida cobertura, monta o payload
├── sources/                     uma fonte de dados externa por módulo
│   ├── emr.py                   ListSupportedInstanceTypes / ListReleaseLabels
│   ├── ec2.py                   DescribeInstanceTypes / DescribeInstanceTypeOfferings
│   ├── pricing.py               Price List API (preço EC2, 3 campos de catálogo, taxa do EMR)
│   ├── spot.py                  DescribeSpotPriceHistory (por AZ, com estatísticas) + Spot Bid Advisor
│   └── yarn.py                  padrões de YARN, lidos da documentação do EMR
└── cli/
    └── collect.py               entrypoint do emr-collect
```

Os testes em [`tests/`](tests/) espelham essa estrutura.

O endpoint de cada serviço externo mora no módulo que fala com ele (o Spot Advisor em
`sources/spot.py`, a documentação de YARN em `sources/yarn.py`) e `config.py`
guarda só o que é transversal.

As camadas internas levantam as exceções de [`errors.py`](src/emr_instances/errors.py)
(`CoverageError`, `StorageError`); apenas os entrypoints em
`cli/` as traduzem em `exit(1)`. Isso mantém os módulos reutilizáveis e testáveis
sem precisar capturar `SystemExit`.

O JSON gerado **não** fica na branch de código — ele vive apenas na branch `data`.

### Estrutura do JSON

No envelope:
- `region`, `generated_at`, `instance_count`
- `release_label` — release usado na coleta, o mais recente disponível em `sa-east-1` (ex: `"emr-7.13.0"`)
- `schema_version`: versão do formato (atual: `3`)

Cada instância tem `instance_type` no topo e quatro blocos: `static` nunca muda
para um dado tipo de instância (pode ser congelado, versionado e usado como
constante), `pricing` muda todo dia e vem datado, `emr_yarn` depende do release
do EMR e `derived` é calculado a partir dos outros três.

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
    "emr_fee_usd_hour": 0.4,
    "spot": { "usd_hour": 1.1793, "az": "sa-east-1c" },
    "spot_by_az": [
      { "az": "sa-east-1c", "current_usd_hour": 1.1793, "window_days": 30,
        "min_usd_hour": 1.1, "mean_usd_hour": 1.2, "median_usd_hour": 1.19,
        "p95_usd_hour": 1.3, "max_usd_hour": 1.4, "stddev_usd_hour": 0.06,
        "price_changes": 12 }
    ],
    "spot_interruption": { "savings_percent": 46, "interruption_rate": 4 }
  },
  "emr_yarn": {
    "nodemanager_memory_mb": 114688,
    "scheduler_max_allocation_mb": 114688,
    "scheduler_min_allocation_mb": 1
  },
  "derived": {
    "memory_gb_per_vcpu": 8.0, "yarn_memory_gb": 112.0,
    "yarn_memory_gb_per_vcpu": 7.0, "yarn_memory_share_of_hardware": 0.875,
    "total_on_demand_usd_hour": 2.2616, "total_spot_usd_hour": 1.5793,
    "total_spot_p95_usd_hour": 1.7, "spot_discount_percent": 36.7,
    "total_spot_usd_per_yarn_gb_hour": 0.014101
  }
}
```

Os números de `emr_fee_usd_hour`, `spot_by_az`, `emr_yarn` e `derived` acima são
ilustrativos, para mostrar o formato. O `derived` real tem mais campos, listados
em [Campos derivados](#campos-derivados).

Alguns campos merecem explicação:

- **`memory_gb_emr` e `memory_gb_hardware` são valores diferentes de propósito.**
  O EMR reporta menos memória que o hardware em 352 dos 465 tipos (razão ~0.953);
  um é o que a máquina tem, o outro é o que o EMR enxerga. **Nenhum dos dois é a
  memória alocável pelo YARN**, que tem um corte bem maior e vem no bloco
  `emr_yarn` (nos tipos lidos da documentação, o YARN aloca entre 47% e 96% da
  memória do hardware).
- **`baseline` e `maximum` (em `ebs` e `network`) são a diferença entre pico e
  sustentado**, que é o que decide o comportamento de um job Spark longo: 159
  tipos fazem burst de EBS e 228 de rede. As `flex` são o caso extremo —
  `c7i-flex.xlarge` vai de 625 a 10000 Mbps de EBS, 16x. Quando o crédito acaba,
  o job cai para o baseline. O booleano `burstable` é derivado (`maximum >
  baseline`) para o consumidor não precisar comparar.
- **`interruption_rate`** é 1-5, do Spot Bid Advisor: <5%, 5-10%, 10-15%, 15-20%, >20%.
- **`emr_fee_usd_hour`** é a taxa que o EMR cobra por instância-hora **além** do
  EC2. Ela varia por tipo e não é um percentual fixo do EC2 (em x86 grandes chega
  a um valor fixo). Fica `null` se a Price List não devolver um preço único para o
  tipo. O custo real de rodar é EC2 mais essa taxa.
- **`spot` é o menor preço vigente entre as AZs; `spot_by_az` traz cada AZ** com a
  distribuição dos últimos 30 dias. No empate do preço vigente (comum: um sexto
  dos tipos empata entre AZs), `spot` fica com a AZ de menor `p95`, a mais
  estável, e depois com a de menor nome. As estatísticas são **ponderadas pelo tempo
  em que cada preço esteve em vigor**, porque o histórico da AWS não é uma
  amostragem regular. `price_changes` conta as vezes em que o preço mudou de
  valor na janela: a AWS repete o mesmo preço em registros sucessivos (umas
  quatro vezes por dia), e esses registros não contam. `stddev` sobre `mean`
  mede quanto o preço oscila, e `p95` é o preço que só é superado em 5% do tempo.
- **`emr_yarn`** vem da coluna de valor padrão da página Task configuration, que
  segue o release mais recente do EMR. Um cluster que sobrescreve `yarn-site` (ou
  usa `maximizeResourceAllocation`) tem outro valor efetivo. É `null` para tipo
  que a página não lista.
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

#### Campos derivados

O bloco `derived` não traz dado novo: é razão ou soma de campos dos outros blocos,
calculada na coleta para que quem consome filtre e ordene sem refazer a conta.
Qualquer entrada ausente deixa `null` só os campos que dependem dela.

| Campo | Cálculo |
| --- | --- |
| `memory_gb_per_vcpu`, `memory_gb_emr_per_vcpu` | memória do hardware (ou do EMR) / vCPU |
| `yarn_memory_gb`, `yarn_memory_gb_per_vcpu` | `nodemanager_memory_mb` / 1024 (e / vCPU) |
| `yarn_memory_share_of_hardware` | memória do YARN / memória do hardware |
| `local_disk_gb_per_vcpu` | disco local / vCPU (`0` em instância EBS-only) |
| `ebs_baseline_mbps_per_vcpu`, `network_baseline_gbps_per_vcpu` | banda sustentada / vCPU |
| `total_on_demand_usd_hour` | EC2 on-demand + taxa do EMR |
| `total_spot_usd_hour`, `total_spot_p95_usd_hour` | spot vigente (ou P95 da AZ mais barata) + taxa do EMR |
| `spot_discount_percent` | desconto do spot sobre o on-demand, só da parte do EC2 |
| `spot_volatility_cv` | desvio / média do spot na AZ mais barata agora |
| `total_*_usd_per_vcpu_hour`, `total_*_usd_per_yarn_gb_hour` | custo total / vCPU (ou GB de YARN), em spot e on-demand |
| `total_spot_usd_per_normalization_unit_hour` | custo total em spot / fator de normalização |

Os custos `total_*` ficam `null` quando falta a taxa do EMR, em vez de sair só com
o EC2: um total que ignora a taxa pareceria barato e distorceria o ranking. Para
spot, a taxa somada é a de on-demand, na premissa de que o EMR não a desconta;
confira na fatura.

#### Consultando com jq

O arquivo é grande demais para caber inteiro numa janela de contexto, então a
consulta é por filtro. Exemplos (a branch `data` guarda o arquivo):

```bash
# as 10 instâncias mais baratas por GB de YARN em spot, com pelo menos 4 GB por vCPU
jq '[.instances[]
     | select(.derived.yarn_memory_gb_per_vcpu >= 4 and .derived.total_spot_usd_per_yarn_gb_hour != null)
     | {t: .instance_type, usd_gb: .derived.total_spot_usd_per_yarn_gb_hour}]
    | sort_by(.usd_gb) | .[:10]' instances_sa-east-1.json

# Graviton com NVMe local e baixa interrupção (faixa 1 ou 2)
jq '[.instances[]
     | select(.static.architecture == "arm64"
              and .static.storage.nvme == "required"
              and .pricing.spot_interruption.interruption_rate <= 2)
     | .instance_type]' instances_sa-east-1.json
```

#### Versões do schema

| Versão | Formato |
| --- | --- |
| 1 | registro plano de 9 campos, sem `schema_version` |
| 2 | `static` / `pricing`, catálogo completo de hardware |
| 3 | acrescenta `pricing.emr_fee_usd_hour`, `pricing.spot_by_az`, `emr_yarn` e `derived` |

`instance_type` fica no topo do registro em todas as versões, para quem consome
o JSON achar a chave do registro sem procurar.

## Rodar localmente

```bash
uv sync                   # instala o pacote (editable) e as dependências
uv run emr-collect        # gera instances_sa-east-1.json
uv run emr-collect --help # opções: --release-label, --output
```

Requer credenciais AWS com permissão de leitura para EMR, Pricing e EC2 (spot e
catálogo de instâncias) — a policy completa está em [Deploy inicial](#deploy-inicial-do-zero).

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

3. **Cadastrar 2 secrets no GitHub**:
   - Vá a **Settings → Secrets and variables → Actions**.
   - Adicione:
     - `AWS_ACCESS_KEY_ID`
     - `AWS_SECRET_ACCESS_KEY`

4. **Disparar o workflow pela primeira vez**:
   - Vá a **Actions → EMR instances (sa-east-1) → Run workflow → Run workflow**.
   - A coleta diária roda por agendamento (cron) ou por esse disparo manual —
     **não** por `push`. Um push para `master` aciona apenas o CI (lint/mypy/testes).
   - ⚠️ Em repositórios novos, o workflow só aparece na aba Actions depois do
     primeiro push do arquivo — se não aparecer, faça um push e recarregue a página.

5. **Confirmar sucesso**:
   - Verifique que a branch **`data`** foi criada com o arquivo `instances_sa-east-1.json`.

## Secrets necessários (GitHub Actions)

`AWS_ACCESS_KEY_ID` e `AWS_SECRET_ACCESS_KEY`.

## Fora de escopo

**Medições do seu job.** Duração, custo por execução e variância de cada candidata
no seu benchmark pertencem a um arquivo à parte (por exemplo `measurements.json`),
unido a este por `instance_type`. O catálogo descreve a máquina; as medições dizem
como ela se comporta na sua carga.

**Outros itens possíveis**, ainda não coletados: taxas de Savings Plans, preço de
referência de EBS e de transferência entre AZs, e as cotas de vCPU da sua conta.
