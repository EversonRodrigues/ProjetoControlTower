-- =====================================================================
-- MÉTRICAS GOVERNADAS · gold.mv_projetos
--
-- A mesma conta para todo mundo: o dashboard, o Genie, o SQL editor e
-- quem abrir um alerta leem daqui. É a metric view do Unity Catalog:
-- ela não guarda número agregado, guarda a FÓRMULA, e quem consulta
-- escolhe o corte.
--
-- Por que ela existe, em uma frase: SPI e CPI são RAZÕES. A média dos
-- SPIs dos 41 projetos não é o SPI da carteira -- um projeto de
-- R$ 200 mil pesaria igual a um de R$ 20 mi. A metric view guarda o
-- numerador e o denominador separados e só divide DEPOIS de somar, em
-- qualquer recorte. É o que uma view comum com AVG(spi) erraria em
-- silêncio.
--
-- ATENÇÃO AO SPI: o SPI da carteira é
--   SUM(horas_agregadas) / SUM(horas_de_prazo_decorrido)  = 0,92
-- e NÃO SUM(ev_dinheiro)/SUM(pv_dinheiro), que dá 0,87. A diferença é
-- que o pv_dinheiro usa o prazo no nível do PROJETO, enquanto o SPI da
-- tabela é ponderado POR TAREFA -- a mesma distinção que fez a conta de
-- 7 críticos e 10 em atenção fechar. Só o CPI usa ev_dinheiro.
--
-- DUAS ARMADILHAS MEDIDAS NESTE WORKSPACE:
--  1. Pelo `aitools tools query` o YAML perde a indentação e a criação
--     falha com METRIC_VIEW_INVALID_VIEW_DEFINITION. Rode este arquivo
--     por `python scripts/run_sql.py` ou pela sql_task do job.
--  2. A sql_task corta o arquivo em TODO ponto-e-vírgula, inclusive
--     dentro do $$ ... $$. Por isso não existe nenhum ponto-e-vírgula
--     dentro do bloco abaixo, nem em comentário, nem em texto: o único
--     do arquivo é o que fecha a statement, depois do $$ final.
--
-- Metric view não nasce no pipeline declarativo (ele não cria
-- `CREATE VIEW ... WITH METRICS`), por isso o arquivo mora em
-- src/metricas/ e não em src/gold/, que é varrido pelo glob do pipeline.
--
-- O "hoje" do dataset é 16/10/2026, e projeto_situacao_atual já é a
-- fotografia desse dia: aqui não há filtro de data nenhum.
--
-- Conferência (seed 42), com WHERE status = 'em_andamento':
--   41 projetos · carteira R$ 208,63 mi · SPI 0,92 · CPI 0,97 ·
--   estouro previsto R$ 6,47 mi · 7 críticos · 10 em atenção ·
--   17 em risco · 4 melancias.
-- =====================================================================

CREATE OR REPLACE VIEW lakehouse_vertice.gold.mv_projetos
WITH METRICS
LANGUAGE YAML
AS $$
version: 0.1

source: lakehouse_vertice.gold.projeto_situacao_atual

dimensions:
  - name: projeto_id
    expr: projeto_id
  - name: nome_projeto
    expr: nome_projeto
  - name: cliente
    expr: cliente
  - name: segmento
    expr: segmento
  - name: tipo_projeto
    expr: tipo_projeto
  - name: ferramenta
    expr: ferramenta
  - name: gerente
    expr: gerente_projeto
  - name: status
    expr: status
  - name: situacao
    expr: situacao
  - name: farol
    expr: farol_calculado
  - name: farol_do_gerente
    expr: farol_do_gerente

measures:
  - name: projetos
    expr: COUNT(1)
  - name: carteira
    expr: SUM(valor_contrato)
  - name: orcamento
    expr: SUM(orcamento_custo)
  - name: custo_real
    expr: SUM(custo_real)
  - name: ev
    expr: SUM(ev_dinheiro)
  - name: spi
    expr: SUM(horas_agregadas) / SUM(horas_de_prazo_decorrido)
  - name: cpi
    expr: SUM(ev_dinheiro) / SUM(custo_real)
  - name: eac
    expr: SUM(eac)
  - name: estouro_previsto
    expr: SUM(estouro_previsto)
  - name: margem_projetada
    expr: (SUM(valor_contrato) - SUM(eac)) / SUM(valor_contrato)
  - name: projetos_em_risco
    expr: COUNT_IF(situacao IN ('atencao', 'critico'))
  - name: projetos_criticos
    expr: COUNT_IF(situacao = 'critico')
  - name: projetos_em_atencao
    expr: COUNT_IF(situacao = 'atencao')
  - name: melancias
    expr: COUNT_IF(melancia)
  - name: atraso_projetado_dias
    expr: SUM(atraso_projetado_dias)
$$;
