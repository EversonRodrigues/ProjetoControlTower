# Databricks notebook source
# MAGIC %md
# MAGIC # Noite 4 · 3 de 3 · O score que o dono lê na segunda-feira
# MAGIC
# MAGIC O `02-modelo.py` provou que o modelo ganha das quatro réguas bobas e o registrou como
# MAGIC `@prod`. Este notebook é o **uso** dele: pega os **41 projetos em andamento** na sexta de
# MAGIC **16/10/2026** e devolve uma tabela de seis colunas que responde a quarta pergunta do dono —
# MAGIC *"o que vai dar errado no próximo mês?"* — numa linha por projeto.
# MAGIC
# MAGIC ## As três coisas que esta tabela tem e um `ORDER BY prob` não teria
# MAGIC
# MAGIC 1. **A fotografia de hoje manda.** O modelo prevê a partir do `indice_min` do *status semanal*.
# MAGIC    Quem já está abaixo de 0,9 no **cronograma de hoje** (`gold.projeto_situacao_atual`) não
# MAGIC    precisa de previsão nenhuma: recebe `prob = 1,0` na mão. Prever o que já aconteceu é o erro
# MAGIC    mais fácil de cometer num score.
# MAGIC 2. **Um ranking que não empata.** Vinte e um projetos terminam com `prob = 1,0`: dezessete
# MAGIC    pelo override (já estão abaixo do corte) e mais quatro porque o modelo prevê uma queda tão
# MAGIC    grande que a probabilidade satura. O desempate é o índice de hoje: quem está mais fundo
# MAGIC    aparece mais em cima. Sem ele, metade da tabela ficaria em ordem arbitrária.
# MAGIC 3. **O porquê, em português.** `principais_fatores` traz os 2 ou 3 sinais mais graves, com
# MAGIC    número em vírgula decimal. É a coluna que o gerente lê antes da probabilidade.
# MAGIC
# MAGIC ## Armadilhas desta etapa, todas medidas
# MAGIC
# MAGIC | Armadilha | O que fazemos |
# MAGIC |---|---|
# MAGIC | `mlflow.pyfunc.spark_udf` morre no serverless com `InvalidVersion` | `mlflow.sklearn.load_model` e `predict` em pandas: são 41 linhas |
# MAGIC | Sem `set_registry_uri("databricks-uc")` o `models:/cat.schema.nome@prod` não resolve | setado antes do load |
# MAGIC | `least()` do Spark **ignora** NULL | nunca contamos com ele para propagar um valor faltante |
# MAGIC | Janela nomeada com frame próprio dá `PARSE_SYNTAX_ERROR` | a janela vai inteira, inline, em cada função |
# MAGIC | `DECIMAL` do Spark chega como `Decimal` no pandas | `.astype(float)` nas 24 features |
# MAGIC | `overwriteSchema` apaga o COMMENT das colunas | os comentários são reaplicados **depois** da escrita |
# MAGIC
# MAGIC O "hoje" do dataset é **16/10/2026**. Nunca `current_date()`.

# COMMAND ----------

# MAGIC %pip install -q -U "mlflow-skinny[databricks]>=2.21,<3"

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 0 · Preparo
# MAGIC
# MAGIC As duas células acima são a mesma armadilha do `02-modelo.py`, e pelo mesmo motivo: o MLflow
# MAGIC 2.11 que vem no serverless não fala com o Unity Catalog. Lá ele não **registrava**; aqui ele
# MAGIC não **carrega** `models:/...@prod`. Elas precisam estar sozinhas, e nesta ordem.

# COMMAND ----------

import math

import numpy as np
import pandas as pd
import mlflow

dbutils.widgets.text("catalog", "lakehouse_vertice")
CATALOGO = dbutils.widgets.get("catalog")

HOJE = "2026-10-16"       # o "hoje" do dataset, sempre literal
INICIO_4_STATUS = "2026-09-25"   # as ultimas 4 sextas: 25/09, 02/10, 09/10 e 16/10
CORTE = 0.9               # a regra da Vertice: SPI ou CPI abaixo de 0,9 e atencao
N_EM_ANDAMENTO = 41       # o contrato do seed 42: 41 em andamento, 19 concluidos
MAX_FATORES = 3
SEM_SINAL = "sem sinal de piora"

MODELO = f"{CATALOGO}.ml.modelo_estouro_30d"
TABELA = f"{CATALOGO}.gold.score_estouro_30d"

print("catalogo:", CATALOGO)
print("modelo  :", f"models:/{MODELO}@prod")
print("destino :", TABELA)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 1 · O modelo `@prod` e o `sigma`
# MAGIC
# MAGIC O caminho é o **alias**, não a versão: `models:/...@prod`. É o que faz o retreino da semana que
# MAGIC vem entrar aqui sem ninguém editar este notebook — e é por isso que o `02-modelo.py` confere o
# MAGIC alias com um `assert` antes de terminar.
# MAGIC
# MAGIC O `sigma` **não** se recalcula aqui. Ele é o desvio do erro do modelo **no teste**, medido no
# MAGIC notebook anterior e guardado em `ml.modelo_metricas`. Recalculá-lo no dado de hoje seria medir o
# MAGIC erro sem ter o gabarito: as próximas 4 semanas ainda não aconteceram.

# COMMAND ----------

# Sem isto o "models:/catalogo.schema.nome@prod" cai no registry velho,
# que nao conhece nome de tres partes nem alias.
mlflow.set_registry_uri("databricks-uc")

modelo = mlflow.sklearn.load_model(f"models:/{MODELO}@prod")

# As features vem do PROPRIO modelo, na ordem em que ele foi treinado.
# Reconstruir a lista a partir da tabela funcionaria hoje e quebraria no
# dia em que alguem reordenasse uma coluna do 01-features.
FEATURES = list(modelo.feature_names_in_)
assert len(FEATURES) == 24, f"esperava 24 features, o modelo pede {len(FEATURES)}: {FEATURES}"

m = spark.sql(
    f"""
    SELECT versao, sigma, auc
    FROM {CATALOGO}.ml.modelo_metricas
    ORDER BY treinado_em DESC
    LIMIT 1
    """
).collect()[0]

VERSAO = m["versao"]
SIGMA = float(m["sigma"])
assert SIGMA > 0, f"sigma {SIGMA}: sem dispersao nao existe probabilidade"

print(f"modelo   versao {VERSAO}  (AUC {m['auc']:.4f})")
print(f"sigma    {SIGMA:.4f}")
print(f"features {len(FEATURES)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 2 · A moldura de pontuação
# MAGIC
# MAGIC Uma consulta, cinco fontes, 41 linhas. Cada fonte está aqui por um motivo diferente:
# MAGIC
# MAGIC | Fonte | O que traz | Por que não dá para dispensar |
# MAGIC |---|---|---|
# MAGIC | `ml.features_projeto_semana` (semana = 16/10) | as 24 features e o `indice_min` | é a entrada do modelo, e o `indice_min` **de onde a previsão parte** |
# MAGIC | `gold.projeto_situacao_atual` | `spi`, `cpi` e o índice **de hoje** | é a fotografia das tarefas; é ela que define quem já estourou |
# MAGIC | `gold.fato_projeto_semana` | `cpi_ultimas_4s` e `spi_ultimas_4s` | **não existem** na tabela de features: são calculados aqui |
# MAGIC | `gold.status_estruturado` | falta de gente, escopo, consultoria, change freeze, rotatividade | é o texto do gerente virado contagem |
# MAGIC | `silver.colaboradores` + `silver.apontamentos` | saídas do time nas últimas 12 semanas | rotatividade que o gerente **não** escreveu no status |
# MAGIC
# MAGIC ### As duas contas que merecem explicação
# MAGIC
# MAGIC **`cpi_ultimas_4s`** não é o CPI acumulado: é o CPI **só do último mês**, a razão entre o que foi
# MAGIC *entregue* e o que foi *gasto* nas últimas 4 semanas — `(EV − EV de 4 semanas atrás) ÷ (AC − AC de
# MAGIC 4 semanas atrás)`. Um projeto com CPI acumulado 0,98 e `cpi_ultimas_4s` 0,70 está quebrando
# MAGIC **agora**, e o acumulado leva meses para contar isso. Mesma ideia no `spi_ultimas_4s`, trocando
# MAGIC AC por PV.
# MAGIC
# MAGIC **"os últimos 4 status"** são as últimas 4 **sextas** (25/09, 02/10, 09/10 e 16/10), não as
# MAGIC últimas 4 linhas que a IA classificou. A diferença é grande: pela segunda leitura, um bloqueio de
# MAGIC julho contaria como "um dos últimos 4" e o sinal de escopo saltaria de 2 para 8 projetos. Para um
# MAGIC score de 30 dias à frente, sinal tem que ser limitado no tempo.

# COMMAND ----------

SQL_MOLDURA = f"""
WITH features_da_semana AS (
  -- A entrada do modelo: as 24 features medidas AS OF 16/10/2026.
  -- Sao exatamente os 41 em andamento: so eles ainda reportam status.
  -- O SELECT * preserva os nomes que o modelo espera em feature_names_in_.
  SELECT *
  FROM {CATALOGO}.ml.features_projeto_semana
  WHERE semana = DATE'{HOJE}'
),
foto_de_hoje AS (
  -- A FOTOGRAFIA: o avanco vem das tarefas das tres ferramentas, nao do
  -- status. E a fonte que decide quem JA estourou.
  SELECT
      projeto_id,
      nome_projeto,
      cliente,
      gerente_projeto,
      spi                     AS spi_hoje,
      cpi                     AS cpi_hoje,
      least(spi, cpi)         AS indice_hoje,
      situacao,
      estouro_previsto
  FROM {CATALOGO}.gold.projeto_situacao_atual
  WHERE status = 'em_andamento'
),
indices_do_mes AS (
  -- CPI e SPI DO ULTIMO MES, que nao estao na tabela de features.
  -- A janela vai inteira dentro de cada funcao: o Spark recusa estender
  -- uma janela nomeada com frame proprio. E o filtro de semana mora no
  -- JOIN de baixo, nao aqui: o lag(4) precisa das 4 semanas anteriores
  -- para existir.
  SELECT
      projeto_id,
      semana,
      (ev_dinheiro - lag(ev_dinheiro, 4) OVER (PARTITION BY projeto_id ORDER BY semana))
        / nullif(ac_dinheiro - lag(ac_dinheiro, 4) OVER (PARTITION BY projeto_id ORDER BY semana), 0)
                                                           AS cpi_ultimas_4s,
      (ev_dinheiro - lag(ev_dinheiro, 4) OVER (PARTITION BY projeto_id ORDER BY semana))
        / nullif(pv_dinheiro - lag(pv_dinheiro, 4) OVER (PARTITION BY projeto_id ORDER BY semana), 0)
                                                           AS spi_ultimas_4s
  FROM {CATALOGO}.gold.fato_projeto_semana
),
sinais_do_status AS (
  -- "2 em 4" = o mesmo bloqueio apareceu em duas das quatro ultimas
  -- sextas. Bloqueio isolado e ruido; repetido, e causa.
  SELECT
      projeto_id,
      count(*)                                                      AS status_com_bloqueio,
      count_if(falta_de_gente)                                      AS n_falta_de_gente,
      count_if(lower(corpo_bloqueio) RLIKE 'congelamento|janela de mudan|freeze|black friday')
                                                                    AS n_change_freeze,
      count_if(categoria_bloqueio = 'mudanca de escopo')             AS n_escopo,
      count_if(categoria_bloqueio = 'fornecedor atrasou entrega')    AS n_consultoria,
      -- "Saida de 3 desenvolvedores no mes" vem COM acento: sem o
      -- sa[ii]da este sinal achava 1 projeto em vez de 2.
      count_if(lower(corpo_bloqueio) RLIKE 'rotativ|sa[ií]da|saiu|demiss|desligad')
                                                                    AS n_rotatividade_citada
  FROM {CATALOGO}.gold.status_estruturado
  WHERE data_status >= DATE'{INICIO_4_STATUS}'
  GROUP BY projeto_id
),
saidas_do_time AS (
  -- Rotatividade que o gerente NAO escreveu: quem foi desligado nas
  -- ultimas 12 semanas e apontou hora neste projeto no mesmo periodo.
  SELECT
      a.projeto_id,
      count(DISTINCT c.colaborador_id) AS saidas_12s
  FROM {CATALOGO}.silver.colaboradores c
  JOIN {CATALOGO}.silver.apontamentos  a USING (colaborador_id)
  WHERE c.data_desligamento BETWEEN date_sub(DATE'{HOJE}', 84) AND DATE'{HOJE}'
    AND a.semana >= date_sub(DATE'{HOJE}', 84)
  GROUP BY a.projeto_id
)
SELECT
    f.*,

    h.nome_projeto,
    h.cliente,
    h.gerente_projeto,
    h.spi_hoje,
    h.cpi_hoje,
    h.indice_hoje,
    h.situacao,
    h.estouro_previsto,

    m.cpi_ultimas_4s,
    m.spi_ultimas_4s,

    coalesce(s.status_com_bloqueio, 0)    AS status_com_bloqueio,
    coalesce(s.n_falta_de_gente, 0)       AS n_falta_de_gente,
    coalesce(s.n_change_freeze, 0)        AS n_change_freeze,
    coalesce(s.n_escopo, 0)               AS n_escopo,
    coalesce(s.n_consultoria, 0)          AS n_consultoria,
    coalesce(s.n_rotatividade_citada, 0)  AS n_rotatividade_citada,
    coalesce(t.saidas_12s, 0)             AS saidas_12s
FROM features_da_semana f
JOIN      foto_de_hoje     h USING (projeto_id)
LEFT JOIN indices_do_mes   m ON m.projeto_id = f.projeto_id AND m.semana = f.semana
LEFT JOIN sinais_do_status s USING (projeto_id)
LEFT JOIN saidas_do_time   t USING (projeto_id)
"""

pdf = spark.sql(SQL_MOLDURA).toPandas()

# DECIMAL do Spark chega como Decimal no pandas e o sklearn recusa dtype
# object. Mesmo .astype(float) do 02-modelo.
pdf[FEATURES] = pdf[FEATURES].astype(float)
for c in ["indice_hoje", "spi_hoje", "cpi_hoje", "cpi_ultimas_4s", "spi_ultimas_4s"]:
    pdf[c] = pdf[c].astype(float)

print(f"projetos na moldura        {len(pdf)}")
print(f"indice_min preenchido      {int(pdf['indice_min'].notna().sum())}")
print(f"indice de hoje preenchido  {int(pdf['indice_hoje'].notna().sum())}")

assert len(pdf) == N_EM_ANDAMENTO, (
    f"{len(pdf)} projetos na moldura, esperava {N_EM_ANDAMENTO}: ou o ml_features nao rodou, "
    "ou algum projeto parou de reportar status"
)
# O least() do Spark IGNORA NULL: um indice nulo nao viraria NULL, viraria
# o outro indice e passaria batido. Conferimos na mao.
assert pdf["indice_min"].notna().all(), "indice_min nulo: a previsao sairia NaN"
assert pdf["indice_hoje"].notna().all(), "indice de hoje nulo: o override nao decidiria nada"

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 3 · Previsão, `pior_previsto` e a probabilidade
# MAGIC
# MAGIC Três linhas de conta e uma regra de negócio:
# MAGIC
# MAGIC 1. O modelo prevê a **queda** (`alvo − indice_min`), não o nível — é o que o `02-modelo.py`
# MAGIC    treinou, justamente para não copiar a entrada.
# MAGIC 2. `pior_previsto = indice_min + queda`. O `indice_min` é o **da linha de features**, o do status
# MAGIC    semanal: é desse ponto que a previsão parte.
# MAGIC 3. `prob = P(pior_previsto < 0,9)`, pela normal com desvio `sigma`, via `math.erf`.
# MAGIC
# MAGIC **E o override.** Quem está abaixo de 0,9 na **fotografia de hoje** recebe `prob = 1,0`. Não é
# MAGIC ajuste cosmético: a previsão parte do status semanal, que é o que o gerente *diz*. Quando as
# MAGIC tarefas já mostram o projeto abaixo do corte, não há nada para prever — aconteceu. Prever um fato
# MAGIC é o jeito mais elegante de errar um score.

# COMMAND ----------

queda_prevista = modelo.predict(pdf[FEATURES])
pior_previsto = pdf["indice_min"].values + queda_prevista

# math.erf e escalar: vetorizamos, igual ao 02-modelo.
erf = np.vectorize(math.erf)
prob_modelo = 0.5 * (1 + erf((CORTE - pior_previsto) / (SIGMA * math.sqrt(2))))

pdf["queda_prevista"] = queda_prevista
pdf["pior_previsto"] = pior_previsto
pdf["prob_modelo"] = prob_modelo

# O OVERRIDE: a fotografia de hoje manda.
pdf["ja_abaixo"] = pdf["indice_hoje"] < CORTE
pdf["prob_estouro_30d"] = np.where(pdf["ja_abaixo"], 1.0, pdf["prob_modelo"])

# A gold ja carrega essa mesma regra na coluna situacao. Se as duas
# discordarem, uma esta errada, e e melhor saber agora.
assert (pdf["ja_abaixo"] == pdf["situacao"].isin(["atencao", "critico"])).all(), (
    "ja_abaixo nao casa com a coluna situacao da gold"
)

print(f"ja abaixo do corte hoje  {int(pdf['ja_abaixo'].sum())} de {len(pdf)}  -> prob 1,0")
print(f"pior_previsto            {pior_previsto.min():.3f} .. {pior_previsto.max():.3f}")
print(f"prob (sem override)      {prob_modelo.min():.4f} .. {prob_modelo.max():.4f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 4 · `ranking` e `faixa_risco`
# MAGIC
# MAGIC O ranking é por probabilidade decrescente, e o desempate é o **índice de hoje crescente**: entre
# MAGIC dois projetos com a mesma probabilidade, quem está mais fundo aparece primeiro. Isso é o que
# MAGIC organiza os 17 projetos que receberam 1,0 — sem o desempate eles ficariam em ordem arbitrária, e
# MAGIC ordem arbitrária é exatamente o que ninguém vai conferir.
# MAGIC
# MAGIC O terceiro critério é o `projeto_id`. Não é elegante, é **determinístico**: ele é único por
# MAGIC linha, então o `ranking` é único por construção — o `assert` lá embaixo nunca cai por empate, só
# MAGIC por bug de verdade. E a mesma execução duas vezes dá a mesma tabela.
# MAGIC
# MAGIC `faixa_risco`: **alto** com `prob >= 0,5`, **medio** com `>= 0,2`, **baixo** abaixo disso.

# COMMAND ----------

pdf = pdf.sort_values(
    ["prob_estouro_30d", "indice_hoje", "projeto_id"],
    ascending=[False, True, True],
).reset_index(drop=True)

pdf["ranking"] = np.arange(1, len(pdf) + 1, dtype=int)


def faixa_de_risco(p):
    if p >= 0.50:
        return "alto"
    if p >= 0.20:
        return "medio"
    return "baixo"


pdf["faixa_risco"] = pdf["prob_estouro_30d"].map(faixa_de_risco)

print(pdf["faixa_risco"].value_counts().reindex(["alto", "medio", "baixo"], fill_value=0).to_string())
# Com um sigma pequeno a faixa medio e uma lamina. Mostramos a largura
# dela em vez de deixar a plateia achar que e bug.
print(
    f"\na faixa medio corresponde a um pior_previsto entre "
    f"{CORTE:.3f} e {CORTE + 0.8416 * SIGMA:.3f}  (sigma {SIGMA:.4f})"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 5 · Os motivos, em português
# MAGIC
# MAGIC `prob = 0,97` não faz ninguém levantar da cadeira. "*as fontes não batem: o status semanal dá
# MAGIC 0,87 e o cronograma de hoje 0,93*" faz.
# MAGIC
# MAGIC São **13 sinais**, e a lista no código está escrita **na ordem da gravidade**: o primeiro que
# MAGIC dispara é o mais grave, e levamos os três primeiros. Não há comparador nem `sort` — a ordem da
# MAGIC lista *é* a regra, e dá para discuti-la lendo o código de cima para baixo.
# MAGIC
# MAGIC Quatro princípios ordenam a lista:
# MAGIC
# MAGIC 1. **Fato antes de previsão.** O que já aconteceu vem antes do que pode acontecer.
# MAGIC 2. **Magnitude antes de direção.** "entregou R$ 0,78 por R$ 1" diz quanto; "CPI caindo" só diz
# MAGIC    para que lado.
# MAGIC 3. **Índice antes de causa.** O índice é o problema; a causa é a conversa seguinte.
# MAGIC 4. **Sinal raro antes de sinal comum.** Um sinal que dispara em 5 de 41 projetos informa mais que
# MAGIC    um que dispara em 18.
# MAGIC
# MAGIC | # | Sinal | A frase | Por que nessa posição |
# MAGIC |---|---|---|---|
# MAGIC | 1 | índice de hoje < 0,9 | já abaixo do corte: menor índice de hoje 0,84 | não é risco, é fato — e é quem força `prob = 1,0`. Sempre primeiro |
# MAGIC | 2 | status < 0,9 **e** hoje ≥ 0,9 | as fontes não batem: o status semanal dá 0,87 e o cronograma de hoje 0,93 | duas fontes discordando é o único sinal que exige **alguém olhar o projeto na mão** |
# MAGIC | 3 | folga < 0,05 | folga de só 0,031 até o corte de 0,9 | é literalmente a distância que o modelo prevê. O mais acionável |
# MAGIC | 4 | `cpi_ultimas_4s < 0,85` | cada R$ 1 gasto no último mês entregou R$ 0,78 | magnitude, em dinheiro, e raro (5 de 41) |
# MAGIC | 5 | `spi_ultimas_4s < 0,85` | no último mês o projeto andou 72% do previsto no cronograma | mesma força, sem o dinheiro |
# MAGIC | 6 | `d_cpi_4s <= -0,005` | CPI caiu 0,012 nas últimas 4 semanas | direção sem magnitude. O piso de 0,005 existe porque sem ele 12 dos 18 projetos diziam "CPI caiu 0,000" |
# MAGIC | 7 | entrega de fornecedor atrasada | 2 entregas de fornecedor em atraso nesta semana | causa externa com culpado nomeado: dá uma ligação a fazer |
# MAGIC | 8 | falta de gente em 2+ | falta de gente citada em 3 dos últimos 4 status | palavra do próprio gerente, repetida |
# MAGIC | 9 | change freeze em 2+ | change freeze citado em 2 dos últimos 4 status | causa de calendário: ninguém resolve, só se planeja |
# MAGIC | 10 | escopo em 2+ | escopo crescendo: mudança de escopo em 2 dos últimos 4 status | causa com conversa de cliente atrás |
# MAGIC | 11 | consultoria em 2+ | consultoria atrasando em 2 dos últimos 4 status | sobrepõe o 7, que é medido e não classificado: vem depois dele |
# MAGIC | 12 | saídas em 12 semanas ou citada | rotatividade: 2 saídas do time nas últimas 12 semanas | causa de ação lenta: explica o passado melhor que o próximo mês |
# MAGIC | 13 | ociosidade ≥ 25% | ociosidade de 31% no time nas últimas 4 semanas | o mais fraco: é sintoma, e time ocioso às vezes é CPI **bom** |
# MAGIC
# MAGIC Nenhum sinal: **"sem sinal de piora"** — e a coluna nunca fica vazia, que é um dos `assert`.
# MAGIC
# MAGIC Um aviso honesto: neste dataset o **change freeze não dispara em ninguém**. Os textos de
# MAGIC congelamento vão de 07/11/2025 a 16/01/2026, fora da janela de 90 dias da IA. A regra fica no
# MAGIC código porque em novembro ela volta a disparar — e porque um sinal que some em silêncio é pior
# MAGIC que um sinal que você sabe estar quieto. A célula abaixo imprime esse zero.

# COMMAND ----------

def br(x, casas=2):
    """O numero como o gerente brasileiro le: 1.234,56 em vez de 1,234.56.

    Formata no padrao americano, estaciona a virgula de milhar no @, troca
    o ponto decimal por virgula e devolve o @ como ponto: os dois
    separadores numa passada, sem regex e sem locale (que no serverless vem
    indefinido e daria resposta errada em silencio, nao erro).
    """
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    return f"{x:,.{casas}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def pct_br(x, casas=0):
    """Fracao -> percentual brasileiro: 0,3125 -> 31%."""
    return f"{br(x * 100, casas)}%"


def plural(n, singular, plural_):
    return f"{n} {singular if n == 1 else plural_}"


def frase_rotatividade(r):
    partes = []
    if r.saidas_12s >= 1:
        partes.append(
            f"{plural(int(r.saidas_12s), 'saída', 'saídas')} do time nas últimas 12 semanas"
        )
    if r.n_rotatividade_citada >= 1:
        partes.append("citada no status")
    return "rotatividade: " + " e ".join(partes)


# A LISTA ESTA NA ORDEM DA GRAVIDADE. Quem dispara primeiro e o mais
# grave; levamos os 3 primeiros. Nenhum sort, de proposito: mexer na
# gravidade e mexer na ordem destas linhas.
#
# NaN faz toda comparacao devolver False, que e o comportamento certo:
# sinal sem dado medido nao dispara.
SINAIS = [
    dict(
        nome="ja abaixo do corte",
        quando=lambda r: r.indice_hoje < CORTE,
        frase=lambda r: f"já abaixo do corte: menor índice de hoje {br(r.indice_hoje)}",
    ),
    dict(
        nome="fontes nao batem",
        quando=lambda r: r.indice_min < CORTE and r.indice_hoje >= CORTE,
        frase=lambda r: (
            f"as fontes não batem: o status semanal dá {br(r.indice_min)} "
            f"e o cronograma de hoje {br(r.indice_hoje)}"
        ),
    ),
    dict(
        nome="folga curta",
        quando=lambda r: CORTE <= r.indice_hoje < CORTE + 0.05,
        frase=lambda r: f"folga de só {br(r.indice_hoje - CORTE, 3)} até o corte de 0,9",
    ),
    dict(
        nome="cpi do mes",
        quando=lambda r: r.cpi_ultimas_4s < 0.85,
        frase=lambda r: f"cada R$ 1 gasto no último mês entregou R$ {br(r.cpi_ultimas_4s)}",
    ),
    dict(
        nome="spi do mes",
        quando=lambda r: r.spi_ultimas_4s < 0.85,
        frase=lambda r: (
            f"no último mês o projeto andou {pct_br(r.spi_ultimas_4s)} do previsto no cronograma"
        ),
    ),
    dict(
        # O piso de 0,005 nao e decoracao: com "d_cpi_4s < 0" puro, 18 dos
        # 41 projetos disparavam e 12 deles por uma queda menor que 0,005,
        # que a frase imprime como "CPI caiu 0,000". Isso e uma afirmacao
        # vazia ocupando uma das 3 vagas de principais_fatores. Com o piso
        # sobram 6 projetos, e a frase passa a dizer alguma coisa.
        nome="cpi caindo",
        quando=lambda r: r.d_cpi_4s <= -0.005,
        frase=lambda r: f"CPI caiu {br(abs(r.d_cpi_4s), 3)} nas últimas 4 semanas",
    ),
    dict(
        nome="fornecedor atrasado",
        quando=lambda r: r.entregas_em_atraso_na_semana >= 1,
        frase=lambda r: (
            f"{plural(int(r.entregas_em_atraso_na_semana), 'entrega', 'entregas')} "
            "de fornecedor em atraso nesta semana"
        ),
    ),
    dict(
        nome="falta de gente",
        quando=lambda r: r.n_falta_de_gente >= 2,
        frase=lambda r: f"falta de gente citada em {int(r.n_falta_de_gente)} dos últimos 4 status",
    ),
    dict(
        nome="change freeze",
        quando=lambda r: r.n_change_freeze >= 2,
        frase=lambda r: f"change freeze citado em {int(r.n_change_freeze)} dos últimos 4 status",
    ),
    dict(
        nome="escopo crescendo",
        quando=lambda r: r.n_escopo >= 2,
        frase=lambda r: (
            f"escopo crescendo: mudança de escopo em {int(r.n_escopo)} dos últimos 4 status"
        ),
    ),
    dict(
        nome="consultoria atrasando",
        quando=lambda r: r.n_consultoria >= 2,
        frase=lambda r: f"consultoria atrasando em {int(r.n_consultoria)} dos últimos 4 status",
    ),
    dict(
        nome="rotatividade",
        quando=lambda r: r.saidas_12s >= 1 or r.n_rotatividade_citada >= 1,
        frase=frase_rotatividade,
    ),
    dict(
        nome="ociosidade",
        quando=lambda r: r.utilizacao_media_4s <= 0.75,
        frase=lambda r: (
            f"ociosidade de {pct_br(1 - r.utilizacao_media_4s)} no time nas últimas 4 semanas"
        ),
    ),
]

# COMMAND ----------

def montar_fatores(r):
    frases = [s["frase"](r) for s in SINAIS if s["quando"](r)]
    return "; ".join(frases[:MAX_FATORES]) if frases else SEM_SINAL


pdf["principais_fatores"] = pdf.apply(montar_fatores, axis=1)
pdf["n_sinais"] = pdf.apply(lambda r: sum(1 for s in SINAIS if s["quando"](r)), axis=1)

# Quantos projetos cada regra pegou. E aqui que se ve a regra morta.
print("sinal                          projetos")
for s in SINAIS:
    n = int(pdf.apply(s["quando"], axis=1).sum())
    marca = "   <- nenhum projeto neste dataset" if n == 0 else ""
    print(f"{s['nome']:<30} {n:>3}{marca}")
print(f"\n{'sem sinal de piora':<30} {int((pdf['n_sinais'] == 0).sum()):>3}")
print(f"{'sinais por projeto (media)':<30} {pdf['n_sinais'].mean():>6.1f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 6 · Os testes, **antes** de gravar
# MAGIC
# MAGIC A noite 4 lê desta tabela, e o dashboard também. Se um destes cair, o notebook morre aqui e a
# MAGIC tabela antiga continua de pé — bem melhor do que um `score_estouro_30d` com 40 linhas e ninguém
# MAGIC percebendo que um projeto sumiu.

# COMMAND ----------

assert len(pdf) == N_EM_ANDAMENTO, f"{len(pdf)} linhas, esperava {N_EM_ANDAMENTO}"
assert pdf["projeto_id"].is_unique, "projeto repetido: e uma linha por projeto em andamento"
assert pdf["prob_estouro_30d"].notna().all(), "probabilidade nula"
assert pdf["prob_estouro_30d"].between(0, 1).all(), (
    f"probabilidade fora de [0, 1]: {pdf['prob_estouro_30d'].min()} .. "
    f"{pdf['prob_estouro_30d'].max()}"
)
assert pdf["ranking"].is_unique, "ranking repetido: o desempate por projeto_id falhou"
assert sorted(pdf["ranking"]) == list(range(1, len(pdf) + 1)), "ranking com buraco"
assert pdf["faixa_risco"].isin(["alto", "medio", "baixo"]).all(), "faixa de risco fora do dominio"
assert pdf["principais_fatores"].notna().all(), "motivo nulo"
assert (pdf["principais_fatores"].str.strip() != "").all(), "motivo vazio"

print("os testes passaram:")
print(f"  {len(pdf)} linhas, uma por projeto em andamento")
print(f"  prob entre {pdf['prob_estouro_30d'].min():.4f} e {pdf['prob_estouro_30d'].max():.4f}")
print(f"  ranking 1..{len(pdf)}, sem repeticao e sem buraco")
print(
    f"  nenhum motivo vazio "
    f"({int((pdf['principais_fatores'] == SEM_SINAL).sum())} com 'sem sinal de piora')"
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 7 · `gold.score_estouro_30d`
# MAGIC
# MAGIC **Seis colunas, nem uma a mais.** `pior_previsto`, `queda_prevista`, `spi_ultimas_4s` e as
# MAGIC contagens de status ficaram no caminho de propósito: elas são o *raciocínio*, e o raciocínio já
# MAGIC está em `principais_fatores`, em português. Quem precisar do número cru abre este notebook ou a
# MAGIC tabela de features.
# MAGIC
# MAGIC A `data_referencia` entra em SQL (`DATE'2026-10-16'`), não em pandas: data saindo de pandas por
# MAGIC Arrow para `DateType` é briga que não precisa existir. O `selectExpr` também fixa os seis tipos
# MAGIC de uma vez, na ordem do contrato.
# MAGIC
# MAGIC E os `COMMENT` vêm **depois** da escrita, sempre: `overwriteSchema` apaga o comentário de cada
# MAGIC coluna, e é o Genie que lê esses comentários.

# COMMAND ----------

COLUNAS = {
    "projeto_id": "o projeto pontuado (PRJ-xxx); so entram os que estao em andamento",
    "data_referencia": "a sexta de referencia do score (o hoje do dataset: 16/10/2026)",
    "prob_estouro_30d": (
        "probabilidade de o projeto cruzar o corte de 0,9 nas proximas 4 semanas, pelo modelo "
        "ml.modelo_estouro_30d@prod: P(pior indice previsto abaixo de 0,9) com erro normal. "
        "Quem ja esta abaixo de 0,9 no cronograma de hoje recebe 1,0 na mao: nesse caso nao e "
        "previsao, e fato"
    ),
    "ranking": (
        "1 = o projeto mais arriscado. Ordena por probabilidade decrescente, desempata pelo menor "
        "indice de hoje (quem esta mais fundo vem antes) e, por fim, pelo projeto_id, para o "
        "ranking ser unico e a mesma execucao dar sempre a mesma ordem"
    ),
    "faixa_risco": "alto com probabilidade de 0,5 ou mais; medio de 0,2 a 0,5; baixo abaixo de 0,2",
    "principais_fatores": (
        "os 2 ou 3 sinais mais graves do projeto, em portugues e com numero em virgula decimal, "
        "separados por ponto e virgula e na ordem da gravidade (ja abaixo do corte sempre "
        'primeiro). Quando nenhum sinal dispara, traz "sem sinal de piora"'
    ),
}

COMENTARIO_DA_TABELA = (
    "O score de estouro em 30 dias dos projetos em andamento da Vertice, na semana de referencia "
    "16/10/2026: uma linha por projeto com a probabilidade de cruzar o corte de 0,9 nas proximas "
    "4 semanas, o ranking (1 = mais arriscado), a faixa de risco e, em portugues, os 2 ou 3 sinais "
    "mais graves que explicam o numero. A probabilidade vem do modelo ml.modelo_estouro_30d@prod "
    "(regressor da queda do indice mais erro normal, com o sigma de ml.modelo_metricas); quem ja "
    "esta abaixo de 0,9 na fotografia de hoje (gold.projeto_situacao_atual) recebe 1,0. E a "
    "resposta a quarta pergunta do dono: o que vai dar errado no proximo mes."
)

saida = spark.createDataFrame(
    pdf[["projeto_id", "prob_estouro_30d", "ranking", "faixa_risco", "principais_fatores"]]
).selectExpr(
    "CAST(projeto_id         AS STRING) AS projeto_id",
    f"DATE'{HOJE}'                      AS data_referencia",
    "CAST(prob_estouro_30d   AS DOUBLE) AS prob_estouro_30d",
    "CAST(ranking            AS INT)    AS ranking",
    "CAST(faixa_risco        AS STRING) AS faixa_risco",
    "CAST(principais_fatores AS STRING) AS principais_fatores",
)

saida.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(TABELA)

# Os COMMENT vem DEPOIS da escrita: o overwriteSchema apaga os antigos.
spark.sql(f"COMMENT ON TABLE {TABELA} IS '{COMENTARIO_DA_TABELA}'")
for coluna, texto in COLUNAS.items():
    spark.sql(f"ALTER TABLE {TABELA} ALTER COLUMN {coluna} COMMENT '{texto}'")

esquema = spark.table(TABELA).schema
print("gravada:", TABELA)
for c in esquema:
    print(f"  {c.name:<20} {c.dataType.simpleString():<7} {c.metadata.get('comment', '')[:55]}")

assert [c.name for c in esquema] == list(COLUNAS), [c.name for c in esquema]
assert [c.dataType.simpleString() for c in esquema] == [
    "string",
    "date",
    "double",
    "int",
    "string",
    "string",
], [c.dataType.simpleString() for c in esquema]
assert all(c.metadata.get("comment") for c in esquema), "coluna sem COMMENT: o Genie le daqui"

# COMMAND ----------

# MAGIC %md
# MAGIC ## O top 25, do jeito que o dono vai ler
# MAGIC
# MAGIC Com o cliente e o estouro previsto de hoje ao lado — é o que transforma "ranking 3" numa decisão.

# COMMAND ----------

top = (
    pdf.head(25)[
        [
            "ranking",
            "projeto_id",
            "cliente",
            "prob_estouro_30d",
            "faixa_risco",
            "spi_hoje",
            "cpi_hoje",
            "pior_previsto",
            "estouro_previsto",
            "principais_fatores",
        ]
    ]
).copy()

print(
    f"{'#':>2}  {'projeto':<8} {'cliente':<22} {'prob':>6} {'faixa':<6} "
    f"{'spi':>5} {'cpi':>5} {'pior':>5} {'estouro':>9}  motivos"
)
for _, r in top.iterrows():
    estouro = f"R$ {br(r.estouro_previsto / 1e6)} mi" if r.estouro_previsto > 0 else "-"
    print(
        f"{int(r.ranking):>2}  {r.projeto_id:<8} {str(r.cliente)[:22]:<22} "
        f"{br(r.prob_estouro_30d, 3):>6} {r.faixa_risco:<6} "
        f"{br(r.spi_hoje):>5} {br(r.cpi_hoje):>5} {br(r.pior_previsto):>5} {estouro:>9}  "
        f"{r.principais_fatores}"
    )

# COMMAND ----------

display(spark.table(TABELA).orderBy("ranking"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## O que a Torre entrega agora
# MAGIC
# MAGIC As quatro perguntas do dono, respondidas: `projeto_situacao_atual` diz quem está atrasado e
# MAGIC quanto custa, `utilizacao_pessoa_semana` diz quem está parado, `status_estruturado` diz por quê —
# MAGIC e esta tabela diz **o que vai dar errado no próximo mês**, com nome, ordem e motivo.
# MAGIC
# MAGIC Duas honestidades para fechar:
# MAGIC
# MAGIC - **A tabela é de uma semana só.** Ela é sobrescrita toda segunda. Quem quiser medir se o score
# MAGIC   acertou olha `ml.modelo_metricas`, que é onde a régua honesta mora.
# MAGIC - **O campo operacional é o `ranking`, não a faixa.** Com um `sigma` pequeno a probabilidade
# MAGIC   satura: ela é quase sempre 0 ou 1. Isso não é defeito, é a pergunta — "cruza 0,9 ou não?" é
# MAGIC   pergunta de limiar, e pergunta de limiar tem resposta afiada. Quem dá a nuance é a ordem do
# MAGIC   ranking e a coluna `principais_fatores`.
