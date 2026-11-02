# Databricks notebook source
# MAGIC %md
# MAGIC # Noite 4 · 2 de 2 · O modelo de estouro em 30 dias
# MAGIC
# MAGIC **"O que vai dar errado no próximo mês?"** — a quarta pergunta do dono, e a única que a noite 3
# MAGIC não conseguia responder.
# MAGIC
# MAGIC O modelo prevê, para cada projeto que **hoje está acima do corte**, qual vai ser o **pior
# MAGIC `indice_min` das próximas 4 semanas** — e daí a probabilidade de ele cruzar 0,9.
# MAGIC
# MAGIC ## O que faz este notebook ser honesto
# MAGIC
# MAGIC Antes de treinar qualquer coisa, ele mede **quatro réguas bobas** (a regra de corte atual, a folga
# MAGIC até o corte, o CPI sozinho e a tendência de 4 semanas). Se o modelo não ganhar da melhor delas, o
# MAGIC `assert` derruba o notebook e **o modelo não é registrado** — porque aí a resposta certa para o
# MAGIC dono é "use a regra, ela é mais simples".
# MAGIC
# MAGIC ## Armadilhas do Free Edition, todas medidas
# MAGIC
# MAGIC | Armadilha | O que fazemos |
# MAGIC |---|---|
# MAGIC | O serverless vem com MLflow 2.11 e registrar em UC morre com `s3:PutObject explicit deny` | `%pip install mlflow-skinny>=2.21,<3` na 1ª célula |
# MAGIC | XGBoost treina e não carrega de volta | `HistGradientBoosting` do sklearn |
# MAGIC | `DECIMAL` vira `Decimal` no pandas e quebra o registro | `.astype(float)` |
# MAGIC | `mlflow.set_experiment` não cria a pasta pai | `workspace.mkdirs(...)` antes |
# MAGIC | MLflow 2.x | `log_model(..., artifact_path="modelo")`, nunca `name=` |
# MAGIC | Sem `set_registry_uri("databricks-uc")` o modelo vai para o registry velho | setado junto do experimento |
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
# MAGIC As duas células acima são uma só armadilha: o `%pip` troca o MLflow que vem no serverless (2.11,
# MAGIC que não registra em Unity Catalog) e o `restartPython()` é o que faz o novo valer. Elas precisam
# MAGIC estar **sozinhas**, e nesta ordem.

# COMMAND ----------

import math

import numpy as np
import pandas as pd
import mlflow
from databricks.sdk import WorkspaceClient
from mlflow.tracking import MlflowClient
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import roc_auc_score

dbutils.widgets.text("catalog", "lakehouse_vertice")
CATALOGO = dbutils.widgets.get("catalog")

HOJE = pd.Timestamp("2026-10-16")
FIM_TREINO = pd.Timestamp("2026-03-06")
INICIO_TESTE = pd.Timestamp("2026-04-03")
CORTE = 0.9
SEED = 42
TOP_N = 5            # o dono olha 5 projetos por semana
JANELA_AVISO = 8     # e aceita um aviso dado até 8 semanas antes
MODELO = f"{CATALOGO}.ml.modelo_estouro_30d"

# mlflow.set_experiment NAO cria a pasta pai: sem este mkdirs o
# set_experiment falha com NOT_FOUND Parent directory does not exist.
w = WorkspaceClient()
EU = w.current_user.me().user_name
PASTA = f"/Users/{EU}/vertice"
w.workspace.mkdirs(PASTA)

# Sem isto o modelo vai para o workspace registry (depreciado) e o
# alias @prod nunca aparece no Unity Catalog.
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(f"{PASTA}/modelo_estouro_30d")

print("experimento:", f"{PASTA}/modelo_estouro_30d")
print("modelo     :", MODELO)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 1 · Ler as features e cortar treino × teste
# MAGIC
# MAGIC **Treino:** rotulados até **06/03/2026** com `pct_prazo > 0,15`. Não filtra `elegivel` de
# MAGIC propósito — projeto já abaixo de 0,9 ensina como um projeto afunda.
# MAGIC
# MAGIC **Teste:** elegíveis com rótulo, de **03/04/2026** em diante.
# MAGIC
# MAGIC Entre os dois há um **vão de 4 semanas** (13, 20 e 27/03). Não é folga: 4 semanas é exatamente a
# MAGIC janela do alvo, então nenhum rótulo de treino enxerga uma semana de teste. Sem esse vão, o modelo
# MAGIC "aprenderia" o período em que é avaliado.

# COMMAND ----------

df = spark.table(f"{CATALOGO}.ml.features_projeto_semana").toPandas()

CHAVES = ["projeto_id", "semana"]
NAO_FEATURE = [
    "segmento",
    "farol_do_gerente",
    "elegivel",
    "alvo_pior_indice_30d",
    "alvo_estourou_30d",
]
FEATURES = [c for c in df.columns if c not in CHAVES + NAO_FEATURE]
assert len(FEATURES) == 24, f"esperava 24 features, achei {len(FEATURES)}: {FEATURES}"

# DECIMAL do Spark chega como Decimal no pandas: o sklearn aceita, mas o
# input_example do log_model quebra o registro no Unity Catalog.
NUMERICAS = FEATURES + ["alvo_pior_indice_30d", "alvo_estourou_30d"]
df[NUMERICAS] = df[NUMERICAS].astype(float)
df["semana"] = pd.to_datetime(df["semana"])
df = df.sort_values(["projeto_id", "semana"]).reset_index(drop=True)

# O alvo do regressor e uma DIFERENCA (alvo - indice_min), entao a linha
# so e utilizavel se o ponto de partida tambem for conhecido. Sao 4 linhas
# em 3.911 com indice_min nulo (SPI e CPI nulos na mesma semana): o
# min() da janela as ignora e o alvo sai preenchido, mas a subtracao sai
# NaN e o sklearn recusa com "Input y contains NaN" -- no retreino final,
# que e o unico lugar que nao filtrava por elegivel.
rotulado = df["alvo_pior_indice_30d"].notna() & df["indice_min"].notna()
treino = df[rotulado & (df["semana"] <= FIM_TREINO) & (df["pct_prazo"] > 0.15)].copy()
teste = df[rotulado & df["elegivel"] & (df["semana"] >= INICIO_TESTE)].copy()

print(f"features           {len(FEATURES)}")
print(f"linhas             {len(df)}")
print(f"rotuladas          {int(rotulado.sum())}")
print(f"treino             {len(treino)}  ({treino.semana.min().date()} .. {treino.semana.max().date()})")
print(f"teste              {len(teste)}  ({teste.semana.min().date()} .. {teste.semana.max().date()})")
print(f"estouros no teste  {int(teste.alvo_estourou_30d.sum())} de {len(teste)} ({teste.alvo_estourou_30d.mean():.1%})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 2 · As quatro réguas, **antes** de treinar
# MAGIC
# MAGIC Esta é a parte que costuma faltar num projeto de ML: saber contra o que se está competindo. Se a
# MAGIC folga até o corte (uma subtração) já acerta tanto quanto o modelo, o modelo não deveria existir.
# MAGIC
# MAGIC A **regra de corte atual** vale 0,5 por construção: ela só marca quem já está abaixo de 0,9, e no
# MAGIC teste **ninguém** está (é o que `elegivel` quer dizer). Ou seja: hoje a Vértice não tem como
# MAGIC separar quem vai estourar de quem não vai. É o chão.

# COMMAND ----------

y_teste = teste["alvo_estourou_30d"].values

baselines = {
    "regra de corte atual (0,5)": 0.5,
    "folga ate o corte (-indice_min)": roc_auc_score(y_teste, -teste["indice_min"]),
    "so o CPI (-cpi)": roc_auc_score(y_teste, -teste["cpi"]),
    "tendencia (-d_indice_min_4s)": roc_auc_score(y_teste, -teste["d_indice_min_4s"].fillna(0)),
}

for nome, valor in baselines.items():
    print(f"AUC {valor:.4f}  {nome}")

AUC_FOLGA = baselines["folga ate o corte (-indice_min)"]
MELHOR_BASELINE = max(baselines, key=baselines.get)
print(f"\nmelhor regua: {MELHOR_BASELINE} (AUC {baselines[MELHOR_BASELINE]:.4f})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 3 · O modelo
# MAGIC
# MAGIC Prevê **`alvo_pior_indice_30d − indice_min`**, a *queda* — não o nível. Prever a queda é o que
# MAGIC impede a trapaça mais óbvia: `indice_min` é feature, então prever o nível seria quase copiar a
# MAGIC entrada.
# MAGIC
# MAGIC Depois: `pior_previsto = indice_min + queda_prevista`, `sigma` é o desvio do erro no teste, e a
# MAGIC probabilidade de cruzar o corte sai da normal — `P(pior < 0,9)` com `math.erf`.
# MAGIC
# MAGIC O regressor é a entrega, não o classificador: ele devolve um **número que o gerente lê** ("seu
# MAGIC pior índice nas próximas 4 semanas deve ser 0,86"), e não só uma probabilidade.

# COMMAND ----------

def queda(d):
    return (d["alvo_pior_indice_30d"] - d["indice_min"]).values


X_treino, X_teste = treino[FEATURES], teste[FEATURES]
y_treino_queda, y_teste_queda = queda(treino), queda(teste)

reg = HistGradientBoostingRegressor(
    random_state=SEED, max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=20
)
reg.fit(X_treino, y_treino_queda)

queda_prevista = reg.predict(X_teste)
pior_previsto = teste["indice_min"].values + queda_prevista
sigma = float(np.std(y_teste_queda - queda_prevista))

# P(pior < 0,9) com erro normal. math.erf e escalar: vetorizamos.
erf = np.vectorize(math.erf)
prob = 0.5 * (1 + erf((CORTE - pior_previsto) / (sigma * math.sqrt(2))))

teste["pior_previsto"] = pior_previsto
teste["prob"] = prob

AUC = roc_auc_score(y_teste, prob)

# O classificador sim/nao, para comparar
clf = HistGradientBoostingClassifier(
    random_state=SEED, max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=20
)
clf.fit(X_treino, treino["alvo_estourou_30d"].values)
AUC_CLF = roc_auc_score(y_teste, clf.predict_proba(X_teste)[:, 1])

print(f"sigma do erro          {sigma:.4f}")
print(f"AUC do regressor       {AUC:.4f}   <- o modelo que vai para producao")
print(f"AUC do classificador   {AUC_CLF:.4f}")
print(f"melhor regua            {baselines[MELHOR_BASELINE]:.4f}  ({MELHOR_BASELINE})")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 4 · A métrica do dono
# MAGIC
# MAGIC AUC não é a pergunta do dono. A pergunta é: **"dos projetos que estouraram, de quantos você me
# MAGIC avisou antes?"**
# MAGIC
# MAGIC **Estouro** é definido do jeito dele, e é exigente de propósito:
# MAGIC o projeto vinha **4 semanas** com SPI *e* CPI ≥ 0,9, **cruza para baixo** e **fica abaixo por 2
# MAGIC semanas seguidas** (com `pct_prazo > 0,15`), contando de **4 semanas depois do início do teste**
# MAGIC (01/05/2026). Uma queda de uma semana só não é estouro: é ruído.
# MAGIC
# MAGIC **Avisado** é o projeto que apareceu no **top 5 da semana** (ranqueado por `prob`) em alguma das
# MAGIC **8 semanas anteriores** ao estouro.

# COMMAND ----------

INICIO_METRICA = INICIO_TESTE + pd.Timedelta(weeks=4)

# A definicao de estouro so olha para tras e para 1 semana a frente (o
# "fica abaixo"), sobre a serie completa de cada projeto.
serie = df[df["spi"].notna() & df["cpi"].notna()].copy()
g = serie.groupby("projeto_id", sort=False)

acima = ((serie["spi"] >= CORTE) & (serie["cpi"] >= CORTE)).astype(float)
serie["vinha_acima_4s"] = (
    acima.groupby(serie["projeto_id"], sort=False)
    .transform(lambda s: s.shift(1).rolling(4).min())
    .eq(1.0)
)
abaixo = serie["indice_min"] < CORTE
serie["fica_abaixo_2s"] = abaixo & abaixo.groupby(serie["projeto_id"], sort=False).shift(-1).fillna(False)

serie["estouro"] = (
    serie["vinha_acima_4s"]
    & serie["fica_abaixo_2s"]
    & (serie["pct_prazo"] > 0.15)
    & (serie["semana"] >= INICIO_METRICA)
)

estouros = serie[serie["estouro"]][["projeto_id", "semana", "indice_min"]].copy()

# O top 5 de cada semana do teste, por probabilidade
top = (
    teste.sort_values(["semana", "prob"], ascending=[True, False])
    .groupby("semana", sort=False)
    .head(TOP_N)[["projeto_id", "semana", "prob"]]
)

linhas = []
for _, e in estouros.iterrows():
    janela = top[
        (top["projeto_id"] == e["projeto_id"])
        & (top["semana"] <= e["semana"] - pd.Timedelta(weeks=1))
        & (top["semana"] >= e["semana"] - pd.Timedelta(weeks=JANELA_AVISO))
    ]
    avisado = len(janela) > 0
    linhas.append(
        {
            "projeto_id": e["projeto_id"],
            "semana_do_estouro": e["semana"],
            "avisado": avisado,
            "primeiro_aviso": janela["semana"].min() if avisado else pd.NaT,
            "antecedencia_dias": (e["semana"] - janela["semana"].min()).days if avisado else np.nan,
        }
    )

placar = pd.DataFrame(linhas)
N_ESTOUROS = len(placar)
N_AVISADOS = int(placar["avisado"].sum()) if N_ESTOUROS else 0
ANTECEDENCIA = float(placar["antecedencia_dias"].mean()) if N_AVISADOS else 0.0
AVISADOS = sorted(placar[placar["avisado"]]["projeto_id"].unique()) if N_ESTOUROS else []

print(f"estouros (de {INICIO_METRICA.date()} em diante)  {N_ESTOUROS}")
print(f"avisados                                  {N_AVISADOS}"
      f"  ({(N_AVISADOS / N_ESTOUROS if N_ESTOUROS else 0):.0%})")
print(f"antecedencia media                        {ANTECEDENCIA:.0f} dias")
print(f"projetos avisados                         {', '.join(AVISADOS) if AVISADOS else '-'}")
print()
print(placar.to_string(index=False) if N_ESTOUROS else "nenhum estouro no periodo")

# COMMAND ----------

# MAGIC %md
# MAGIC E a frase que o dono realmente ouve: **quanto dinheiro** estava nesses projetos avisados, pelo
# MAGIC estouro previsto de hoje (`gold.projeto_situacao_atual`).

# COMMAND ----------

if AVISADOS:
    lista = "', '".join(AVISADOS)
    ESTOURO_AVISADO = float(
        spark.sql(
            f"""
            SELECT coalesce(sum(estouro_previsto), 0) AS total
            FROM {CATALOGO}.gold.projeto_situacao_atual
            WHERE projeto_id IN ('{lista}')
            """
        ).collect()[0]["total"]
    )
else:
    ESTOURO_AVISADO = 0.0

print(f"estouro previsto hoje nos projetos avisados: R$ {ESTOURO_AVISADO/1e6:.2f} mi")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 5 · Importância por permutação
# MAGIC
# MAGIC Embaralha uma feature de cada vez e mede o quanto o erro piora. Também é o detector de vazamento
# MAGIC mais rápido que existe: se **uma** feature carrega quase toda a importância, desconfie dela.

# COMMAND ----------

imp = permutation_importance(
    reg, X_teste, y_teste_queda, n_repeats=10, random_state=SEED,
    scoring="neg_mean_absolute_error",
)
importancia = (
    pd.DataFrame({"feature": FEATURES, "importancia": imp.importances_mean, "desvio": imp.importances_std})
    .sort_values("importancia", ascending=False)
    .reset_index(drop=True)
)
FEATURE_PRINCIPAL = importancia.iloc[0]["feature"]
peso_da_principal = importancia.iloc[0]["importancia"] / importancia["importancia"].clip(lower=0).sum()

print(importancia.head(12).to_string(index=False))
print(f"\nfeature principal: {FEATURE_PRINCIPAL} ({peso_da_principal:.0%} da importancia total)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 6 · Os testes, **antes** de registrar
# MAGIC
# MAGIC Se um destes cair, o notebook morre aqui e **nada é registrado** — que é o comportamento certo.
# MAGIC Os números são o contrato; quem muda são as features.

# COMMAND ----------

assert AUC >= 0.75, f"AUC {AUC:.4f} < 0,75: o modelo nao serve. Troque features, nao o limite."
assert AUC < 0.98, (
    f"AUC {AUC:.4f} >= 0,98: isso e vazamento, nao talento. "
    f"Olhe a feature principal ({FEATURE_PRINCIPAL}) antes de qualquer outra coisa."
)
assert AUC >= AUC_FOLGA, (
    f"AUC {AUC:.4f} < a folga ate o corte ({AUC_FOLGA:.4f}): "
    "uma subtracao acerta mais que o modelo. Use a regra."
)
assert N_ESTOUROS > 0, "nenhum estouro no periodo: a definicao ou a grade esta errada, nao o modelo"
assert N_AVISADOS >= 0.70 * N_ESTOUROS, (
    f"avisados {N_AVISADOS} de {N_ESTOUROS} ({N_AVISADOS/N_ESTOUROS:.0%}) < 70%"
)

print("os 4 testes passaram:")
print(f"  AUC {AUC:.4f} >= 0,75")
print(f"  AUC {AUC:.4f} <  0,98")
print(f"  AUC {AUC:.4f} >= folga ate o corte ({AUC_FOLGA:.4f})")
print(f"  avisados {N_AVISADOS}/{N_ESTOUROS} = {N_AVISADOS/N_ESTOUROS:.0%} >= 70%")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 7 · Retreinar com tudo e registrar
# MAGIC
# MAGIC O modelo avaliado acima foi treinado só até 06/03 — era o jeito de medir sem trapaça. O que vai
# MAGIC para produção é retreinado com **todos os rotulados**: para prever segunda-feira, jogar fora as
# MAGIC últimas 30 semanas seria desperdício.

# COMMAND ----------

todos = df[rotulado]
X_todos, y_todos = todos[FEATURES], queda(todos)

reg_final = clone(reg).fit(X_todos, y_todos)
print(f"retreinado com {len(todos)} linhas (contra {len(treino)} do teste)")

with mlflow.start_run(run_name="estouro_30d") as run:
    mlflow.log_params(
        {
            "features": len(FEATURES),
            "linhas_treino_final": len(todos),
            "fim_treino_avaliacao": FIM_TREINO.date(),
            "inicio_teste": INICIO_TESTE.date(),
            "corte": CORTE,
            "top_n": TOP_N,
            "janela_aviso_semanas": JANELA_AVISO,
            **reg.get_params(),
        }
    )
    mlflow.log_metrics(
        {
            "auc": AUC,
            "auc_classificador": AUC_CLF,
            "auc_regra_de_corte": baselines["regra de corte atual (0,5)"],
            "auc_folga_ate_o_corte": AUC_FOLGA,
            "auc_so_cpi": baselines["so o CPI (-cpi)"],
            "auc_tendencia": baselines["tendencia (-d_indice_min_4s)"],
            "sigma": sigma,
            "estouros": N_ESTOUROS,
            "avisados": N_AVISADOS,
            "antecedencia_media_dias": ANTECEDENCIA,
            "estouro_avisado_reais": ESTOURO_AVISADO,
        }
    )
    # MLflow 2.x: artifact_path, NUNCA name=
    info = mlflow.sklearn.log_model(
        reg_final,
        artifact_path="modelo",
        input_example=X_todos.head(3),
        registered_model_name=MODELO,
    )

VERSAO = info.registered_model_version
cliente = MlflowClient(registry_uri="databricks-uc")
cliente.set_registered_model_alias(MODELO, "prod", VERSAO)

# Ler o alias de volta. O set_registered_model_alias nao levanta erro se
# nao pegar, e o alias nao aparece em `databricks model-versions get`
# (so em `registered-models get --include-aliases`): sem esta conferencia,
# um @prod ausente passaria batido e quem fosse carregar
# models:/...@prod na segunda-feira e que descobriria.
apontado = cliente.get_model_version_by_alias(MODELO, "prod").version
assert str(apontado) == str(VERSAO), f"@prod aponta para {apontado}, nao para {VERSAO}"
print(f"registrado: {MODELO} versao {VERSAO}, alias @prod conferido")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Passo 8 · `ml.modelo_metricas`
# MAGIC
# MAGIC Uma linha: o modelo, as quatro réguas que ele teve de bater e o que isso significa em dinheiro.
# MAGIC É a tabela que o dashboard e o Genie leem para dizer *por que* confiar no número.

# COMMAND ----------

metricas = pd.DataFrame(
    [
        {
            "versao": str(VERSAO),
            "auc": AUC,
            "auc_classificador": AUC_CLF,
            "auc_regra_de_corte": float(baselines["regra de corte atual (0,5)"]),
            "auc_folga_ate_o_corte": float(AUC_FOLGA),
            "auc_so_cpi": float(baselines["so o CPI (-cpi)"]),
            "auc_tendencia": float(baselines["tendencia (-d_indice_min_4s)"]),
            "sigma": sigma,
            "estouros": N_ESTOUROS,
            "avisados": N_AVISADOS,
            "projetos_avisados": ", ".join(AVISADOS),
            "antecedencia_media_dias": ANTECEDENCIA,
            "estouro_avisado_reais": ESTOURO_AVISADO,
            "feature_principal": str(FEATURE_PRINCIPAL),
            "linhas_treino": len(todos),
            "linhas_teste": len(teste),
            "treinado_em": pd.Timestamp.now(),
        }
    ]
)

(
    spark.createDataFrame(metricas)
    .write.mode("overwrite")
    .option("overwriteSchema", "true")
    .saveAsTable(f"{CATALOGO}.ml.modelo_metricas")
)

spark.sql(
    f"""COMMENT ON TABLE {CATALOGO}.ml.modelo_metricas IS
    'Uma linha com o retrato do modelo de estouro em producao: a versao registrada, o AUC, as quatro reguas simples que ele teve de bater (regra de corte, folga ate o corte, CPI sozinho e tendencia), o sigma do erro, quantos estouros aconteceram e de quantos o modelo avisou antes, com quantos dias de antecedencia, quanto dinheiro estava nesses projetos e qual feature mais pesa. E a tabela que explica por que confiar no score.'"""
)

print(metricas.T.to_string(header=False))

# COMMAND ----------

# MAGIC %md
# MAGIC ## O que o dono faz na segunda
# MAGIC
# MAGIC Abre o dashboard, olha os **5 projetos com maior probabilidade** de cruzar o corte nas próximas 4
# MAGIC semanas e pergunta para cada um: *o que está travado aqui?* — e a resposta já está em
# MAGIC `gold.status_estruturado`, escrita pelo próprio gerente e classificada pela IA.
# MAGIC
# MAGIC O modelo não substitui o SPI; ele compra tempo. A régua honesta está em `ml.modelo_metricas`:
# MAGIC quando a folga até o corte voltar a empatar com o modelo, o modelo pode ser aposentado sem
# MAGIC cerimônia.
