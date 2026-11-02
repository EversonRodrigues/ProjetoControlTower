# Databricks notebook source
# MAGIC %md
# MAGIC # Noite 4 · 1 de 2 · As features do modelo de estouro
# MAGIC
# MAGIC **A quarta pergunta do dono: "o que vai dar errado no próximo mês?"**
# MAGIC
# MAGIC A noite 3 respondeu o presente (quem está atrasado, quanto custa). Esta tabela é o que permite
# MAGIC responder o futuro: uma linha por **projeto e por sexta**, com o que se sabia **naquela sexta** e,
# MAGIC ao lado, o que aconteceu nas **4 sextas seguintes** (o alvo).
# MAGIC
# MAGIC ## As duas regras que fazem esta tabela valer alguma coisa
# MAGIC
# MAGIC 1. **Nenhuma feature pode olhar para o futuro.** Tudo é medido *as of* a sexta da linha. É fácil
# MAGIC    errar: `silver.tarefas` só tem o % de **hoje**, então usá-lo numa sexta de 2025 injetaria 2026
# MAGIC    na linha e o modelo acertaria quase tudo — de mentira.
# MAGIC 2. **A grade é densa.** Conferimos: as 98 datas de status são todas sexta e nenhum projeto tem
# MAGIC    buraco na série. Por isso `ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING` é mesmo "os próximos 30
# MAGIC    dias" — `ROWS` conta **linhas**, e aqui linha = semana.
# MAGIC
# MAGIC O "hoje" do dataset é **16/10/2026**. Nunca `current_date()`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 1 · O schema `ml`
# MAGIC
# MAGIC `bronze`, `silver` e `gold` já existem desde a noite 1. O `ml` é desta noite — e um pipeline
# MAGIC declarativo não cria schema, que é uma das razões desta etapa ser um notebook e não mais um
# MAGIC arquivo do medalhão.

# COMMAND ----------

dbutils.widgets.text("catalog", "lakehouse_vertice")
CATALOGO = dbutils.widgets.get("catalog")

spark.sql(
    f"CREATE SCHEMA IF NOT EXISTS {CATALOGO}.ml "
    "COMMENT 'Features, modelos e metricas do modelo de estouro (noite 4).'"
)
print("schema ml pronto em", CATALOGO)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 2 · A tabela de features
# MAGIC
# MAGIC **31 colunas = 2 chaves + 24 features + 5 que não entram no modelo.**
# MAGIC
# MAGIC As 5 de fora: `segmento` e `farol_do_gerente` viajam só para fatiar o relatório, `elegivel` faz o
# MAGIC corte do teste e os dois `alvo_*` são a resposta.
# MAGIC
# MAGIC **`elegivel`** é quem *pode* estourar: projeto que naquela sexta ainda estava **acima** do corte
# MAGIC (`indice_min >= 0,9`) e já tinha andado o bastante para o SPI significar algo (`pct_prazo > 0,15`).
# MAGIC O treino de propósito **não** filtra por isso: projeto já afundado ensina como se afunda.

# COMMAND ----------

# O Spark nao aceita estender uma janela nomeada com um frame proprio
# (OVER (w ROWS BETWEEN ...) da PARSE_SYNTAX_ERROR): com uma janela
# nomeada so se pode escrever OVER w, sem frame. Entao a janela vai em
# cada funcao, por uma variavel, para o SQL continuar legivel.
W = "PARTITION BY b.projeto_id ORDER BY b.semana"

SQL = f"""
CREATE OR REPLACE TABLE {CATALOGO}.ml.features_projeto_semana
COMMENT 'Uma linha por projeto e por sexta com as 24 features do modelo de estouro, medidas as of aquela sexta (nada olha para o futuro), mais os dois alvos: o pior indice_min das 4 sextas seguintes (os proximos 30 dias) e a versao sim/nao dele. A coluna elegivel marca quem naquela semana ainda estava acima do corte de 0,9 e podia estourar. Alimenta src/ml/02-modelo.py.'
AS
WITH base AS (
  SELECT
      f.projeto_id,
      f.semana,
      p.segmento,
      f.farol_do_gerente,
      f.spi,
      f.cpi,
      least(f.spi, f.cpi)                                    AS indice_min,
      f.pct_prazo,
      f.pct_concluido / 100.0                                AS pct_concluido,
      f.ac_dinheiro,
      f.orcamento_custo,
      f.valor_contrato,
      f.duracao_baseline_dias,
      f.pessoas_na_semana,
      f.pct_utilizacao,
      f.horas_apontadas,
      datediff(f.semana, p.data_inicio)       / 7.0          AS semanas_desde_inicio,
      datediff(p.data_fim_baseline, f.semana) / 7.0          AS semanas_restantes_baseline,
      f.duracao_baseline_dias                 / 7.0          AS duracao_baseline_semanas
  FROM {CATALOGO}.gold.fato_projeto_semana f
  JOIN {CATALOGO}.silver.projetos p USING (projeto_id)
),
custo_da_semana AS (
  -- Custo lancado EM cada semana, separando consultoria. O LEFT JOIN a
  -- partir da grade mantem como zero a semana sem lancamento.
  SELECT
      b.projeto_id,
      b.semana,
      CAST(coalesce(sum(c.valor), 0) AS DOUBLE)              AS custo_semana,
      CAST(coalesce(sum(CASE WHEN c.categoria = 'consultoria' THEN c.valor END), 0) AS DOUBLE)
                                                             AS custo_consultoria_semana
  FROM base b
  LEFT JOIN {CATALOGO}.silver.custos c
         ON c.projeto_id = b.projeto_id
        AND c.semana     = b.semana
  GROUP BY b.projeto_id, b.semana
),
atraso_fornecedor AS (
  -- as-of: entregas que JA estavam atrasadas naquela sexta. A silver
  -- calcula em_atraso contra 16/10/2026, o que aqui seria futuro.
  SELECT
      b.projeto_id,
      b.semana,
      count(e.entrega_id)                                    AS entregas_em_atraso_na_semana
  FROM base b
  LEFT JOIN {CATALOGO}.silver.entregas_fornecedor e
         ON e.projeto_id     = b.projeto_id
        AND e.data_prometida < b.semana
        AND (e.data_entrega IS NULL OR e.data_entrega > b.semana)
  GROUP BY b.projeto_id, b.semana
),
com_janelas AS (
  SELECT
      b.*,
      cs.custo_semana,
      cs.custo_consultoria_semana,
      af.entregas_em_atraso_na_semana,

      -- Deltas: sempre lag, NUNCA lead. Um lead aqui seria vazamento.
      b.spi           - lag(b.spi, 4)           OVER ({W})       AS d_spi_4s,
      b.cpi           - lag(b.cpi, 4)           OVER ({W})       AS d_cpi_4s,
      b.indice_min    - lag(b.indice_min, 4)    OVER ({W})       AS d_indice_min_4s,
      b.indice_min    - lag(b.indice_min, 8)    OVER ({W})       AS d_indice_min_8s,
      b.pct_concluido - lag(b.pct_concluido, 4) OVER ({W})       AS d_pct_concluido_4s,

      stddev_samp(b.indice_min) OVER ({W} ROWS BETWEEN 7 PRECEDING AND CURRENT ROW)
                                                             AS vol_indice_min_8s,
      avg(b.pct_utilizacao)     OVER ({W} ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
                                                             AS utilizacao_media_4s,
      sum(b.horas_apontadas)    OVER ({W} ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
                                                             AS horas_apontadas_4s,

      b.ac_dinheiro - lag(b.ac_dinheiro, 4) OVER ({W})           AS custo_dos_ultimos_4s,
      sum(cs.custo_semana)             OVER ({W} ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
                                                             AS custo_12s,
      sum(cs.custo_consultoria_semana) OVER ({W} ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)
                                                             AS consultoria_12s,

      -- O ALVO: o pior indice_min das 4 sextas SEGUINTES.
      -- Comeca em 1 FOLLOWING: incluir a propria semana poria o alvo
      -- dentro da feature indice_min e o AUC iria a ~1 de mentira.
      -- So vale quando existem as 4 semanas; as 4 ultimas de cada
      -- projeto ficam sem rotulo, e e por isso que o passo 4 do modelo
      -- le o estouro de hoje em gold.projeto_situacao_atual.
      CASE WHEN count(*) OVER ({W} ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING) = 4
           THEN min(b.indice_min) OVER ({W} ROWS BETWEEN 1 FOLLOWING AND 4 FOLLOWING)
      END                                                    AS alvo_pior_indice_30d
  FROM base b
  JOIN custo_da_semana   cs USING (projeto_id, semana)
  JOIN atraso_fornecedor af USING (projeto_id, semana)
)
SELECT
    -- as 2 chaves
    projeto_id,
    semana,

    -- as 24 features
    spi,
    cpi,
    indice_min,
    pct_prazo,
    pct_concluido,
    pct_concluido - pct_prazo                                AS folga_prazo,
    d_spi_4s,
    d_cpi_4s,
    d_indice_min_4s,
    d_indice_min_8s,
    d_pct_concluido_4s,
    vol_indice_min_8s,
    semanas_desde_inicio,
    semanas_restantes_baseline,
    duracao_baseline_semanas,
    ln(valor_contrato)                                       AS log_valor_contrato,
    ln(orcamento_custo)                                      AS log_orcamento_custo,
    ac_dinheiro / nullif(orcamento_custo, 0)                 AS custo_sobre_orcamento,
    custo_dos_ultimos_4s / nullif(orcamento_custo, 0)        AS burn_custo_4s,
    consultoria_12s / nullif(custo_12s, 0)                   AS pct_custo_consultoria_12s,
    utilizacao_media_4s,
    horas_apontadas_4s,
    CAST(pessoas_na_semana AS DOUBLE)                        AS pessoas_na_semana,
    CAST(entregas_em_atraso_na_semana AS DOUBLE)             AS entregas_em_atraso_na_semana,

    -- as 5 que nao entram no modelo
    segmento,
    farol_do_gerente,
    (    pct_prazo > 0.15
     AND pct_prazo <= 1.0
     AND spi IS NOT NULL
     AND cpi IS NOT NULL
     AND indice_min >= 0.9)                                  AS elegivel,
    alvo_pior_indice_30d,
    CASE WHEN alvo_pior_indice_30d IS NOT NULL
         THEN CAST(alvo_pior_indice_30d < 0.9 AS INT) END    AS alvo_estourou_30d
FROM com_janelas
"""

spark.sql(SQL)
print("gravada:", f"{CATALOGO}.ml.features_projeto_semana")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 3 · Conferência
# MAGIC
# MAGIC Estes `assert` existem para o `ml_modelo` falhar **aqui**, alto e claro, em vez de morrer lá na
# MAGIC frente com uma mensagem do sklearn que não diz nada.

# COMMAND ----------

from pyspark.sql import functions as F

df = spark.table(f"{CATALOGO}.ml.features_projeto_semana")

CHAVES = ["projeto_id", "semana"]
NAO_FEATURE = [
    "segmento",
    "farol_do_gerente",
    "elegivel",
    "alvo_pior_indice_30d",
    "alvo_estourou_30d",
]
FEATURES = [c for c in df.columns if c not in CHAVES + NAO_FEATURE]

print(f"colunas: {len(df.columns)}  features: {len(FEATURES)}")
assert len(df.columns) == 31, df.columns
assert len(FEATURES) == 24, FEATURES

FIM_TREINO = "2026-03-06"
INICIO_TESTE = "2026-04-03"

rotulado = F.col("alvo_pior_indice_30d").isNotNull()

m = df.select(
    F.count("*").alias("linhas"),
    F.count("alvo_pior_indice_30d").alias("rotulados"),
    F.sum(F.col("elegivel").cast("int")).alias("elegiveis"),
    F.sum(
        F.when(rotulado & (F.col("semana") <= FIM_TREINO) & (F.col("pct_prazo") > 0.15), 1)
        .otherwise(0)
    ).alias("treino"),
    F.sum(
        F.when(rotulado & F.col("elegivel") & (F.col("semana") >= INICIO_TESTE), 1).otherwise(0)
    ).alias("teste"),
    F.min("semana").alias("primeira_semana"),
    F.max("semana").alias("ultima_semana"),
).collect()[0]

for k in ["linhas", "rotulados", "elegiveis", "treino", "teste"]:
    print(f"{k:>12}  {m[k]}")
print(f"     semanas  {m['primeira_semana']} .. {m['ultima_semana']}")

assert m["linhas"] == 3911, m["linhas"]
assert m["treino"] > 500, f"treino pequeno demais: {m['treino']}"
assert m["teste"] > 200, f"teste pequeno demais: {m['teste']}"

# A taxa de positivos no teste: 0% ou 100% nao tem o que aprender.
taxa = (
    df.filter(rotulado & F.col("elegivel") & (F.col("semana") >= INICIO_TESTE))
    .agg(F.avg("alvo_estourou_30d"))
    .collect()[0][0]
)
print(f"taxa de estouro no teste: {taxa:.1%}")
assert 0.02 < taxa < 0.60, f"taxa de positivos irreal: {taxa}"

# COMMAND ----------

# MAGIC %md
# MAGIC Com a tabela conferida, `src/ml/02-modelo.py` treina, mede contra quatro réguas simples e só
# MAGIC registra o modelo se ele for melhor que todas elas.
