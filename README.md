# Projeto Farol · Torre de Controle de Portfólio

**Uma plataforma de dados que responde, em segundos, a pergunta que a empresa levava semanas para responder: quais projetos estão atrasados, quanto esse atraso vai custar e o que fazer a respeito.**

Construído de ponta a ponta sobre Databricks Lakehouse: ingestão → modelagem em medalhão → métricas de gestão de projetos (EVM) → classificação de texto com IA → modelo de risco → aplicação web para quem não escreve SQL.

🔗 **Aplicação no ar:** https://minha-torre-7474652665238460.aws.databricksapps.com

---

## 1. O problema de negócio

A **Vértice Tecnologia** (empresa fictícia, dados sintéticos) desenvolve sistemas para grandes clientes de varejo, financeiro, saúde, logística e indústria:

| | |
|---|---|
| Projetos | **60** |
| Pessoas | **520** |
| Carteira | **R$ 305,2 milhões** |

O problema não era falta de dado — era dado espalhado. **Cada gerente controlava o seu projeto numa ferramenta diferente:** 20 em planilhas Excel, 25 no ClickUp e 15 no MS Project. Ninguém na empresa conseguia responder quais projetos estavam atrasados sem abrir 60 arquivos à mão.

O dono da empresa fez quatro perguntas. A Torre responde as quatro:

| Pergunta | Como é respondida |
|---|---|
| 1. Quais projetos estão atrasados, e de quais clientes? | Índices SPI/CPI por projeto, com cliente e segmento |
| 2. Quanto esse atraso vai me custar? | EAC, estouro previsto e margem projetada |
| 3. Tenho gente parada enquanto outro projeto pede gente? | Utilização por pessoa × causa declarada no status, com simulador de realocação |
| 4. O que vai dar errado no próximo mês? | Modelo de classificação com probabilidade de estouro em 30 dias |

---

## 2. O que a plataforma entrega

Resultados reais, extraídos da camada gold (fotografia de 16/10/2026):

| Indicador | Valor |
|---|---|
| Projetos em andamento | **41** |
| Em risco (atenção + crítico) | **17** |
| Críticos | **7** |
| **Estouro de orçamento previsto** | **R$ 6,47 milhões** |
| SPI / CPI da carteira | 0,92 / 0,97 |
| "Melancias" — gerente reportou verde, mas o índice diz atraso | **4** (PRJ-012, PRJ-028, PRJ-034, PRJ-042) |

E três achados que ninguém tinha visto antes:

- **Dois SREs sêniores parados há 12 semanas** (COL0017 e COL0018, utilização de 5,8% e 5,5%) — enquanto o PRJ-011 acumulava **57 dias de atraso declarado por falta de gente**, nas mesmas 12 semanas. O simulador põe preço nessa realocação: ~R$ 30 mil/mês de ociosidade que deixa de ser paga contra R$ 8 mil de mobilização.
- **Um fornecedor fora da curva:** a CodeForge entregou **332 das 349 entregas fora do prazo**, levando em média **1,41×** o prazo prometido. Os outros quatro fornecedores ficam em 0,98×.
- **4 projetos com farol verde e SPI abaixo de 0,9** — o indicador de gestão mais importante que a plataforma produz, porque é a diferença entre o que foi reportado e o que o dado mostra.

### Métricas implementadas (Earned Value Management)

| KPI | Fórmula |
|---|---|
| **SPI** (Schedule Performance Index) | Valor agregado ÷ valor planejado. Abaixo de 1 = atrasado |
| **CPI** (Cost Performance Index) | Valor agregado ÷ custo real. Abaixo de 1 = estourando |
| **EAC** (Estimate at Completion) | Orçamento ÷ CPI |
| Estouro previsto | EAC − orçamento, quando positivo |
| Margem projetada | (valor do contrato − EAC) ÷ valor do contrato |
| Atraso projetado | Duração baseline ÷ SPI − duração baseline |

Regras de corte: índice **< 0,9 = atenção**, **< 0,8 = crítico**.

---

## 3. Arquitetura

```
                     ┌──────────────── job vertice_farol (9 tarefas, orquestrado) ────────────────┐
                     │                                                                            │
  BrasilAPI ─────────▶ ingestão feriados ──┐                                                      │
                     │                     ├─▶ conferência ─▶ MEDALHÃO ──┬─▶ testes de qualidade  │
  Data lake S3 ──────▶ ingestão arquivos ──┘      bronze     (pipeline)   │        │              │
  (Excel/ClickUp/    │                                      silver → gold │        ▼              │
   MS Project/CSV)   │                                                    │   features → modelo   │
                     │                                                    │        → score        │
                     │                                                    ├─▶ status + IA         │
                     │                                                    └─▶ métrica governada   │
                     └────────────────────────────────────────────────────────────────────────────┘
                                                      │
                        ┌─────────────────────────────┼─────────────────────────────┐
                        ▼                             ▼                             ▼
                 Aplicação web              Dashboard AI/BI              Genie (perguntas
                 (React + TypeScript)         (executivo)                 em português)
```

### A camada de dados

| Camada | O que é | Tabelas |
|---|---|---|
| **Bronze** | O dado cru, exatamente como chegou, com toda a sujeira | 9 tabelas + feriados |
| **Silver** | Limpo, tipado, integrado e testado | `projetos`, `tarefas`, `status_semanal`, `custos`, `colaboradores`, `apontamentos`, `entregas_fornecedor` |
| **Gold** | Pronto para consumo, uma tabela por pergunta de negócio | `projeto_situacao_atual`, `fato_projeto_semana`, `utilizacao_pessoa_semana`, `status_estruturado`, `score_estouro_30d`, `mv_projetos` |

Volumes processados: **4.917 tarefas** (as três ferramentas unificadas), **30.883 apontamentos** de timesheet, **23.640 lançamentos de custo** (R$ 193,35 mi), **3.911 semanas** de histórico de projeto, **520 pessoas**.

### A integração das três ferramentas

O ponto mais difícil do projeto. Excel, ClickUp e MS Project descrevem a mesma coisa — uma tarefa — de três formas incompatíveis:

| | Excel | ClickUp | MS Project |
|---|---|---|---|
| Datas | texto `dd/MM/yyyy` **ou** número de série (`45321`) | timestamp em milissegundos | dentro de struct `Baseline` |
| % concluído | `'45%'`, `'10,5%'` ou `0.45` | dentro de um array `custom_fields` | campo `PercentComplete` |
| Horas | `'40h'` | custom field | `'PT40H0M0S'` (ISO 8601) |
| Hierarquia | planilha plana, com linha de TOTAL | `list_id` / `list_name` | `OutlineLevel` + `Summary` |

A solução: três *views* temporárias (uma por ferramenta) com **exatamente as mesmas colunas**, unificadas por `UNION ALL` em `silver.tarefas`. Um modelo só, e o resto da plataforma não precisa saber de onde a tarefa veio.

### A sujeira tratada (18 casos)

A limpeza é o conteúdo técnico do projeto, não um detalhe. Alguns exemplos e a decisão tomada:

| Sujeira | Decisão de engenharia |
|---|---|
| Vírgula decimal (`12345,67`) em 671 linhas de custo | `replace(',', '.')` antes do cast. **`try_cast` descartaria R$ 5,4 milhões em silêncio** — o tipo de bug que ninguém encontra |
| Estornos lançados como valor negativo | **Manter** (custo é líquido) e sinalizar com flag. Filtrar inflaria o custo real |
| Tarefas-resumo somando as horas das filhas (105 linhas) | `WHERE Summary = 0` — sem isso as horas contam em dobro |
| 51 status com texto vazio ou `"ver ata da reunião"` | **Não descartar.** Flag `status_vazio` — ausência de informação também é informação |
| Mesma pessoa cadastrada duas vezes (3 casos) | Deduplicar mantendo o cadastro canônico |
| Mesma consultoria com 4 grafias diferentes | Normalizar — sem isso a análise de fornecedor não existe |
| 11 percentuais acima de 100% | Limitar a 100 **com flag**, para não esconder o problema de origem |

**Como a limpeza é validada:** o custo total não pode mudar entre bronze e silver (R$ 193,35 mi antes, R$ 193,35 mi depois), e a soma de horas de cada planilha tem que bater com a linha de TOTAL que o gerente digitou. São testes automatizados, não conferência manual.

---

## 4. A aplicação

Uma aplicação web para quem não escreve SQL — porque um dashboard responde "o quê", mas não responde "e se".

**Tela 1 · Projetos em risco.** Quatro indicadores no topo (em risco, estouro previsto, carteira, alto risco em 30 dias) e a tabela dos 41 projetos em andamento, ordenada do pior para o melhor. Situação com cor semântica (crítico vermelho, atenção âmbar), probabilidade de estouro do modelo, e o farol do gerente ao lado do farol calculado — com 🍉 quando os dois discordam.

**Tela 2 · Simulador de realocação.** Escolha uma pessoa ociosa e um projeto em risco; a tela calcula horas liberadas no mês, ociosidade que deixa de ser paga, dias de cronograma recuperados, custo de mobilização e o saldo final em reais. **A conta inteira está aberta num `<details>`**, passo a passo, com a origem de cada número — incluindo o que a conta *não* diz (se a pessoa tem a competência, se o cliente aceita a troca). A decisão continua humana; a aplicação só põe o preço na mesa.

### Decisões de engenharia visíveis no código

- **Degradação em vez de quebra.** A tabela do modelo de ML pode não existir ainda. Se a leitura falhasse numa query comum, o *build* inteiro quebraria na geração de tipos. Em vez disso, o score é lido por uma rota dedicada que distingue três causas (`tabela ausente`, `warehouse frio`, `erro`) e escreve mensagens diferentes para cada uma — porque "o modelo ainda não rodou" e "o servidor está ligando" são problemas opostos, e mostrar o primeiro quando é o segundo é mentir para o usuário.
- **Nenhum número sem procedência.** Todo indicador na tela carrega unidade, período, comparação e **fonte** (`gold.projeto_situacao_atual · 16/10/2026`). Um "17" solto não é informação.
- **Conversão explícita de tipos.** O warehouse devolve todo número — e todo booleano — como *string* no JSON, enquanto os tipos gerados dizem `number` e `boolean`. O compilador não pega; só o runtime. `"false"` é *truthy* em JavaScript, e sem tratamento o ícone de melancia aparecia em todas as linhas da tabela. Há testes cobrindo exatamente isso.
- **Estados obrigatórios.** Carregando, vazio, erro e parcial — todos tratados. O *warehouse* da edição gratuita hiberna após 10 minutos, então a primeira visita do dia espera; em vez de retângulos cinza sem explicação, a tela diz com palavras o que está acontecendo.

---

## 5. IA e Machine Learning

**Classificação de texto (`gold.status_estruturado`).** Os gerentes escrevem os bloqueios em texto livre no status semanal. Duas funções de IA nativas do Databricks leem esse texto: `ai_classify` categoriza a causa e `ai_extract` puxa os dias de impacto que o gerente declarou. Resultado: **163 status estruturados** em seis categorias de causa.

Três decisões que fizeram isso ser viável:
- Cada chamada de IA leva ~5 segundos. Rodar nos 3.911 status levaria mais de 5 horas. **Rodamos só nos status com bloqueio dos últimos 90 dias** (163) e aplicamos regra determinística no resto — de horas para minutos.
- `ai_extract` sem schema devolve tudo como texto. Usamos a versão com **JSON schema tipado**, então `dias_impacto` chega como número.
- A carga é **incremental via `MERGE`**: um texto já classificado nunca é reprocessado.

**Modelo de risco (`gold.score_estouro_30d`).** Classificador que atribui a cada projeto uma probabilidade de estourar o orçamento nos próximos 30 dias, com faixa de risco e os principais fatores que explicam a previsão.

> **Nota de honestidade analítica:** na execução atual o modelo coloca 26 dos 41 projetos na faixa "alto", com probabilidade mínima de 0,988. Isso é um score saturado — provavelmente vazamento de variável ou alvo mal definido — e **está documentado como pendência de calibração**, não apresentado como resultado válido. A aplicação exibe a faixa que o modelo produz, sem inventar um limiar que o código não usa.

---

## 6. O Genie: perguntar em português — e como eu testo isso

Toda a engenharia acima não vale nada se o dono da empresa precisar de um analista
disponível para fazer uma pergunta. Por isso a plataforma publica um **Genie Agent**
(`Farol · Diretoria`): uma interface em linguagem natural sobre a camada gold, em que o
diretor pergunta em português e recebe o número **junto com o SQL que o produziu**.

```
"Quais projetos estão atrasados, e de quais clientes?"
"Quanto esse atraso vai me custar?"
"Tenho gente parada enquanto outro projeto pede gente?"
"Por que o PRJ-011 atrasou?"
"O que vai dar errado no próximo mês?"
```

O agente é **código**, não configuração de tela: `resources/farol.geniespace.json` é
gerado por `scripts/gerar_genie.py` com **ids determinísticos** (contador, não UUID), de
forma que regerar o arquivo produz exatamente os mesmos bytes — o diff mostra só a
mudança real, e o agente pode ser revisado em *pull request* como qualquer outro artefato.

### A parte que eu mais defendo: o benchmark

Publicar um Genie é fácil. **Saber se ele está respondendo certo é o problema de
engenharia de verdade** — e é o que quase ninguém faz.

`llm/genie-benchmark.json` tem **20 perguntas com a resposta correta conhecida**, versionadas
junto do código. Cada uma declara como deve ser verificada (`numero`, `conjunto`, `linhas`,
`distinto`, `contem`) e **por que a pergunta existe** — qual armadilha ela testa:

```json
{
  "pergunta": "Qual é o SPI e o CPI da carteira de projetos em andamento?",
  "como_verificar": "numero",
  "esperado": [0.92, 0.97],
  "tolerancia": 0.015,
  "porque": "razão de somas pela mv_projetos; AVG(spi) daria outro número"
}
```

```bash
python scripts/genie.py benchmark "Farol · Diretoria" llm/genie-benchmark.json --profile MEU_PERFIL
```

**O julgamento é por regra declarada, não por um juiz LLM.** Essa foi uma decisão
deliberada: usar um modelo como juiz colocaria variância no próprio instrumento de
medida. Quando a nota caísse, eu não saberia dizer se o Genie piorou ou se o juiz mudou
de ideia — e o ciclo de melhoria perderia o sinal. As respostas certas são números
conhecidos de um dataset com semente fixa, então uma regra dá um placar **auditável e
reproduzível**.

A verificação procura o valor esperado no texto da resposta **e** nas linhas do resultado
achatadas. Assim um número que o Genie arredondou na prosa ("R$ 6,5 mi") ainda é
encontrado no valor cru da linha — a nota mede **o SQL que ele escreveu**, que é o que a
instrução controla, e não a redação dele.

### O que o benchmark encontrou

Placar atual: **20/20**, com variação ocasional de 19/20 entre execuções (o modelo não é
determinístico — e o benchmark existe justamente para tornar isso visível em vez de
suposto).

O benchmark pagou por si na primeira rodada, pegando uma falha que eu não teria achado
olhando a tela. À pergunta *"quantos projetos estão críticos e quantos em atenção **hoje**?"*
o Genie respondia **10 e 11** em vez de 7 e 10. O SQL que ele gerou estava sintaticamente
perfeito e usava a métrica governada corretamente — ele só havia omitido
`WHERE status = 'em_andamento'`, e assim contava 3 projetos críticos **que já tinham sido
concluídos**.

A causa não estava no dado nem na métrica: estava na instrução, que dizia *"para 'em
andamento', filtre por status"* — uma condicional. O usuário escreveu "hoje", não "em
andamento". A correção foi tornar a regra um **padrão** em vez de uma condicional: as
palavras "hoje", "em risco", "crítico", "em atenção" e "melancia" já significam em
andamento, porque um projeto concluído não está atrasado hoje.

Uma linha de instrução, e a nota foi de 19/20 para 20/20. É o tipo de erro que um
dashboard nunca comete e um agente comete sempre — e a única razão de eu tê-lo
encontrado é que existe um teste.

---

## 7. Stack

| Camada | Tecnologia |
|---|---|
| Plataforma | Databricks Lakehouse · Unity Catalog |
| Transformação | Lakeflow Spark Declarative Pipelines (SQL declarativo, serverless) |
| Orquestração | Lakeflow Jobs — 9 tarefas com dependências, agendado |
| Infraestrutura como código | Databricks Asset Bundles (DABs) |
| IA | `ai_classify`, `ai_extract` (funções nativas de SQL) |
| ML | Python + MLflow |
| Aplicação | Databricks Apps · React 19 · TypeScript · Tailwind · Vite |
| Consumo | Dashboard AI/BI · Genie (linguagem natural) · Metric View governada |
| Qualidade | `CONSTRAINT ... EXPECT ... ON VIOLATION FAIL UPDATE` · Vitest · ESLint · ast-grep |

**Tudo versionado como código.** Não há nada configurado por clique: o job, o pipeline, o dashboard, o espaço de Genie e a aplicação são todos arquivos neste repositório, deployados por um comando.

---

## 8. Estrutura do repositório

```
├── databricks.yml              # o bundle: variáveis, targets (dev/prod), exclusões de sync
├── src/
│   ├── ingestao/               # bronze: BrasilAPI (feriados) + data lake S3 via boto3
│   ├── conferencia/            # valida a bronze antes de transformar
│   ├── silver/                 # 5 arquivos: projetos, tarefas, status+custos, pessoas, fornecedores
│   ├── gold/                   # 3 arquivos: situação atual, fato semanal, utilização
│   ├── ia/                     # ai_classify + ai_extract sobre o status semanal
│   ├── ml/                     # features → treino → score
│   ├── metricas/               # metric view governada (mv_projetos)
│   └── testes/                 # testes de qualidade pós-medalhão
├── resources/                  # job, pipeline, dashboard e Genie como código
├── minha-torre/                # a aplicação web (bundle próprio)
│   ├── config/queries/         # 3 queries SQL tipadas
│   ├── server/server.ts        # backend + a rota tolerante do score
│   └── client/src/             # React: telas, componentes, lib e testes
├── scripts/                    # geradores de dashboard/Genie, executor de SQL, concessão de acessos
└── llm/                        # os prompts que construíram cada etapa
```

---

## 9. Como rodar

### Pré-requisitos

- [Databricks CLI](https://docs.databricks.com/dev-tools/cli/) v0.240+ (`databricks -v`)
- Um workspace Databricks com Unity Catalog e um SQL warehouse
- Node.js 20+ (para a aplicação)
- Python 3.11+ com [uv](https://docs.astral.sh/uv/) (para os scripts auxiliares)

### Passo 1 — Autenticar

```bash
databricks auth login --host https://seu-workspace.cloud.databricks.com --profile MEU_PERFIL
databricks warehouses list --profile MEU_PERFIL   # anote o ID do warehouse
```

### Passo 2 — Configurar as credenciais do data lake

As chaves de acesso **nunca** entram no Git. Elas são declaradas como variáveis em `databricks.yml` e o valor mora num arquivo local, ignorado pelo versionamento:

```bash
mkdir -p .databricks/bundle/dev
cat > .databricks/bundle/dev/variable-overrides.json <<'JSON'
{
  "s3_access_key_id": "...",
  "s3_secret_access_key": "...",
  "warehouse_id": "..."
}
JSON
```

### Passo 3 — Criar o catálogo

`scripts/run_sql.py` executa um arquivo `.sql` statement por statement, via a API de
SQL Statements (e não pela CLI interativa, que achata a indentação e quebra o YAML das
metric views):

```bash
cat > /tmp/catalogo.sql <<'SQL'
CREATE CATALOG IF NOT EXISTS lakehouse_vertice;
CREATE SCHEMA  IF NOT EXISTS lakehouse_vertice.bronze;
CREATE SCHEMA  IF NOT EXISTS lakehouse_vertice.silver;
CREATE SCHEMA  IF NOT EXISTS lakehouse_vertice.gold;
CREATE VOLUME  IF NOT EXISTS lakehouse_vertice.bronze.raw;
SQL

python scripts/run_sql.py /tmp/catalogo.sql --profile MEU_PERFIL
```

### Passo 4 — Deployar a plataforma de dados

```bash
databricks bundle validate --profile MEU_PERFIL
databricks bundle deploy   --profile MEU_PERFIL
```

Isso cria o job, o pipeline, o dashboard e o espaço de Genie — todos a partir dos arquivos do repositório.

### Passo 5 — Rodar a esteira completa

```bash
databricks bundle run vertice_farol --profile MEU_PERFIL
```

Executa, em ordem de dependência: ingestão → conferência da bronze → medalhão (silver + gold) → testes de qualidade → IA no status → métrica governada → features → modelo → score.

> O espaço de Genie exige que as tabelas existam. Na primeira vez, a ordem é `deploy → run → deploy`.

### Passo 6 — Deployar a aplicação

```bash
cd minha-torre
databricks bundle deploy --profile MEU_PERFIL      # cria o app e o service principal
cd .. && bash scripts/conceder-acesso.sh MEU_PERFIL minha-torre   # concede leitura na silver e na gold
cd minha-torre && databricks apps deploy --profile MEU_PERFIL
```

A ordem importa: o `bundle deploy` cria o *service principal* da aplicação, que precisa dos acessos **antes** do `apps deploy` — senão o build falha ao gerar os tipos a partir do warehouse.

### Desenvolvimento local da aplicação

```bash
cd minha-torre
npm install
npm run dev          # http://localhost:8000
npm run typecheck    # TypeScript, cliente e servidor
npm run lint         # ESLint
npm run lint:ast-grep # regras do AppKit
npm run test         # Vitest — 23 testes
databricks apps validate --profile MEU_PERFIL   # tipos + lint + typecheck + build + testes
```

---

## 10. Qualidade

A plataforma não confia em si mesma por padrão. A validação acontece em quatro níveis:

| Nível | Como |
|---|---|
| **No pipeline** | `CONSTRAINT ... EXPECT (...) ON VIOLATION FAIL UPDATE` em cada tabela — chave preenchida, percentuais no intervalo válido, semana sempre numa sexta, estouro nunca negativo. Dado fora da regra **para a carga**, não entra silenciosamente |
| **Reconciliação** | O custo total tem que ser idêntico entre bronze e silver; as horas de cada planilha têm que bater com a linha de TOTAL digitada pelo gerente |
| **Tarefa dedicada no job** | `testes_de_qualidade` roda depois do medalhão e falha o job inteiro se algo não fecha |
| **Na aplicação** | 23 testes unitários (Vitest) sobre a aritmética do simulador e as conversões de tipo, mais typecheck, ESLint e ast-grep no pipeline de validação |
| **No Genie** | 20 perguntas de benchmark com resposta conhecida, julgadas por regra declarada (não por juiz LLM). Placar atual **20/20** |

### Notas de reprodutibilidade

- **A data de referência é fixa:** `DATE'2026-10-16'`, nunca `current_date()`. Com data dinâmica os números mudariam a cada execução e ninguém conseguiria reconciliar um resultado com o de outra pessoa.
- **Os dados são sintéticos** (semente fixa), gerados para conter a sujeira de propósito. Não há informação real de cliente, pessoa ou contrato neste repositório.
- **Nenhuma credencial versionada.** Todas as chaves são referências `${var.…}`; os valores ficam em arquivos locais ignorados pelo Git.

---

## 11. Pendências conhecidas

Documentar o que falta é parte do trabalho:

- **Calibrar `score_estouro_30d`** — modelo saturado (26 de 41 projetos em "alto risco"), provável vazamento de variável. A aplicação já exibe o resultado de forma honesta, mas o modelo precisa de revisão.
- **Tela "Perguntar"** — o Genie Agent está no ar e versionado (seção 6), mas ainda é consumido pela interface do Databricks e pela CLI. Falta embuti-lo como terceira aba da aplicação.
- **Variância do Genie** — o placar oscila entre 19/20 e 20/20 entre execuções, porque o modelo não é determinístico. O benchmark torna isso mensurável, mas estabilizar a pergunta que oscila exige mais instrução ou mais SQL de exemplo.
- **Formatação** — o projeto nunca passou integralmente pelo Prettier; apenas os arquivos tocados recentemente estão formatados.
- **Taxonomia de bloqueio** — as categorias vêm de `ai_classify` em linguagem natural. Consolidá-las num domínio fechado e versionado facilitaria a análise histórica.

---

<sub>Projeto técnico desenvolvido na Imersão Jornada de Dados. Dados sintéticos; a Vértice Tecnologia é uma empresa fictícia.</sub>
