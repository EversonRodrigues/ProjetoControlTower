Continue o bundle na raiz deste repositório. Crie o notebook
src/ml/02-modelo.py (# Databricks notebook source, widget catalog) e a
tarefa ml_modelo (notebook_task, depois de ml_features).

ARMADILHAS MEDIDAS NO FREE EDITION (siga todas):
- O serverless vem com MLflow 2.11, e registrar modelo no Unity Catalog
  falha com "s3:PutObject ... explicit deny". Primeira célula:
  %pip install -q -U "mlflow-skinny[databricks]>=2.21,<3"
  e dbutils.library.restartPython() na seguinte.
- XGBoost treina e não carrega de volta: use HistGradientBoosting do sklearn.
- DECIMAL vira Decimal no pandas e quebra o registro: .astype(float).
- mlflow.set_experiment não cria a pasta pai: WorkspaceClient().workspace
  .mkdirs("/Users/<eu>/vertice") antes.
- MLflow 2.x: log_model(..., artifact_path="modelo"), nunca name=.
- Toda célula de texto começa com "# MAGIC %md": sem ela o notebook quebra
  com SyntaxError na linha do texto.

O notebook, nesta ordem:
1. Lê ml.features_projeto_semana (24 features: todas as colunas do prompt 1
   menos segmento, farol_do_gerente, elegivel e os dois alvos). Teste = elegíveis com rótulo e semana >=
   2026-04-03. Treino = rotulados com semana <= 2026-03-06 e pct_prazo > 0,15
   (inclui projetos já abaixo de 0,9: eles ensinam como um projeto afunda).
2. BASELINES no teste, impressos antes de qualquer treino: regra de corte
   atual (0,5), folga até o corte (-indice_min), só o CPI, tendência
   (-d_indice_min_4s).
3. Modelo: HistGradientBoostingRegressor(random_state=42, max_depth=3,
   learning_rate=0.05, max_iter=300, min_samples_leaf=20) prevendo
   alvo_pior_indice_30d - indice_min. pior_previsto = indice_min + previsão.
   sigma = desvio do erro no teste. prob = P(pior < 0,9) com erro normal
   (math.erf). Compare com um HistGradientBoostingClassifier sim/não.
4. Métrica do dono: um estouro é o projeto que vinha 4 semanas com SPI e CPI
   >= 0,9, cruza para baixo e FICA abaixo por 2 semanas seguidas (pct_prazo
   > 0,15), a partir de 4 semanas depois do início do teste. Avisado =
   esteve no top 5 da semana (rank por prob) em alguma das 8 semanas
   anteriores. Imprima avisados/estouros, antecedência média em dias e o
   estouro previsto hoje (gold.projeto_situacao_atual) desses projetos.
5. Importância por permutação.
6. Testes com assert, ANTES de registrar: AUC >= 0,75; AUC < 0,98 (acima
   disso é vazamento); AUC >= a folga até o corte (senão, use a regra);
   avisados >= 70% dos estouros.
7. Retreine com TODOS os rotulados, registre em
   lakehouse_vertice.ml.modelo_estouro_30d com input_example, alias @prod.
8. Grave ml.modelo_metricas (uma linha: versão, auc, todas as réguas,
   sigma, estouros, avisados e quais, antecedência, estouro avisado,
   feature principal).

Rode e me mostre a saída:
  databricks bundle deploy --profile <perfil>
  databricks bundle run vertice_farol --only ml_modelo --profile <perfil>