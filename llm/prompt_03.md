Continue o bundle na raiz deste repositório. Crie o notebook
src/ml/03-score.py (mesma primeira célula de %pip do 02-modelo) e a tarefa
ml_score (notebook_task, depois de ml_modelo).

1. Carregue o modelo com mlflow.sklearn.load_model("models:/lakehouse_vertice
   .ml.modelo_estouro_30d@prod") — NÃO use spark_udf: no serverless ele
   quebra com InvalidVersion. O sigma vem de ml.modelo_metricas.
2. Pontue os projetos em andamento na semana 2026-10-16 de
   ml.features_projeto_semana, com join em gold.projeto_situacao_atual:
   pior_previsto = indice_min + previsão; prob = P(pior < 0,9) com erro
   normal; quem tem least(spi, cpi) < 0,9 NA FOTOGRAFIA DE HOJE → 1,0.
3. ranking por prob desc (desempate: índice de hoje asc); faixa_risco alto
   se >= 0,5, medio se >= 0,2, senão baixo.
4. principais_fatores: os 2 ou 3 sinais mais graves em português, com
   números no padrão brasileiro (vírgula decimal). Sinais: já abaixo do
   corte (sempre primeiro), status semanal abaixo do corte e cronograma
   acima (as fontes não batem), folga < 0,05 até o corte, CPI caindo nas
   últimas semanas, cpi_ultimas_4s < 0,85 ("cada R$ 1 gasto no último mês
   entregou R$ X"), spi_ultimas_4s < 0,85, falta de SRE em 2+ dos últimos 4
   status, change freeze em 2+, rotatividade (saídas em 12 semanas ou citada
   no status), escopo crescendo em 2+, consultoria atrasando em 2+,
   ociosidade >= 25%. Sem sinal: "sem sinal de piora".
5. Grave lakehouse_vertice.gold.score_estouro_30d com EXATAMENTE as colunas
   projeto_id STRING, data_referencia DATE, prob_estouro_30d DOUBLE,
   ranking INT, faixa_risco STRING, principais_fatores STRING (overwrite).
   COMMENT na tabela e nas colunas: a noite 4 lê daqui.
6. Testes com assert: uma linha por projeto em andamento, prob entre 0 e 1,
   ranking único, nenhum motivo vazio.

Rode o job inteiro e me mostre o top 25:
  databricks bundle deploy --profile ControlTower
  databricks bundle run vertice_farol --profile ControlTower