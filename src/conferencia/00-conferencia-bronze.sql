-- =====================================================================
-- CONFERÊNCIA DA BRONZE
--
-- Antes de construir a silver, a pergunta mais barata do mundo:
-- a bronze chegou inteira?
--
-- As contagens abaixo são do seed 42 e não mudam. bronze.feriados fica
-- de fora de propósito: ela cresce a cada execução da ingestão da API.
--
-- São DOIS statements separados por ';' — e isso é intencional.
-- A sql_task do job corta o arquivo em todo ';' e roda um por um:
--   1) o relatório, que é a saída que você vê no run;
--   2) o freio, que derruba a tarefa se alguma tabela divergiu.
--
-- Caminho sempre completo: sql_task não tem catálogo padrão.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) O relatório: uma linha por tabela, esperado × obtido
-- ---------------------------------------------------------------------
WITH esperado AS (
  SELECT 'projetos'            AS tabela, 60    AS esperado UNION ALL
  SELECT 'status_semanal'               , 3911              UNION ALL
  SELECT 'excel_tarefas'                , 1663              UNION ALL
  SELECT 'clickup_tarefas'              , 2119              UNION ALL
  SELECT 'msproject_tarefas'            , 1260              UNION ALL
  SELECT 'colaboradores'                , 523               UNION ALL
  SELECT 'apontamentos'                 , 30883             UNION ALL
  SELECT 'custos'                       , 23640             UNION ALL
  SELECT 'entregas_fornecedor'          , 640
),
obtido AS (
  SELECT 'projetos'            AS tabela, count(*) AS obtido FROM lakehouse_vertice.bronze.projetos            UNION ALL
  SELECT 'status_semanal'               , count(*)           FROM lakehouse_vertice.bronze.status_semanal      UNION ALL
  SELECT 'excel_tarefas'                , count(*)           FROM lakehouse_vertice.bronze.excel_tarefas       UNION ALL
  SELECT 'clickup_tarefas'              , count(*)           FROM lakehouse_vertice.bronze.clickup_tarefas     UNION ALL
  SELECT 'msproject_tarefas'            , count(*)           FROM lakehouse_vertice.bronze.msproject_tarefas   UNION ALL
  SELECT 'colaboradores'                , count(*)           FROM lakehouse_vertice.bronze.colaboradores       UNION ALL
  SELECT 'apontamentos'                 , count(*)           FROM lakehouse_vertice.bronze.apontamentos        UNION ALL
  SELECT 'custos'                       , count(*)           FROM lakehouse_vertice.bronze.custos              UNION ALL
  SELECT 'entregas_fornecedor'          , count(*)           FROM lakehouse_vertice.bronze.entregas_fornecedor
)
SELECT
    e.tabela,
    e.esperado,
    o.obtido,
    o.obtido - e.esperado              AS diferenca,
    CASE WHEN o.obtido = e.esperado THEN 'ok' ELSE 'DIVERGIU' END AS situacao
FROM esperado e
JOIN obtido   o ON o.tabela = e.tabela
-- divergentes primeiro: quem está lendo o run vê o problema na primeira linha
ORDER BY CASE WHEN o.obtido = e.esperado THEN 1 ELSE 0 END, e.tabela;

-- ---------------------------------------------------------------------
-- 2) O freio: se alguma tabela divergiu, a tarefa falha aqui mesmo
--    e a silver nem começa.
-- ---------------------------------------------------------------------
WITH esperado AS (
  SELECT 'projetos'            AS tabela, 60    AS esperado UNION ALL
  SELECT 'status_semanal'               , 3911              UNION ALL
  SELECT 'excel_tarefas'                , 1663              UNION ALL
  SELECT 'clickup_tarefas'              , 2119              UNION ALL
  SELECT 'msproject_tarefas'            , 1260              UNION ALL
  SELECT 'colaboradores'                , 523               UNION ALL
  SELECT 'apontamentos'                 , 30883             UNION ALL
  SELECT 'custos'                       , 23640             UNION ALL
  SELECT 'entregas_fornecedor'          , 640
),
obtido AS (
  SELECT 'projetos'            AS tabela, count(*) AS obtido FROM lakehouse_vertice.bronze.projetos            UNION ALL
  SELECT 'status_semanal'               , count(*)           FROM lakehouse_vertice.bronze.status_semanal      UNION ALL
  SELECT 'excel_tarefas'                , count(*)           FROM lakehouse_vertice.bronze.excel_tarefas       UNION ALL
  SELECT 'clickup_tarefas'              , count(*)           FROM lakehouse_vertice.bronze.clickup_tarefas     UNION ALL
  SELECT 'msproject_tarefas'            , count(*)           FROM lakehouse_vertice.bronze.msproject_tarefas   UNION ALL
  SELECT 'colaboradores'                , count(*)           FROM lakehouse_vertice.bronze.colaboradores       UNION ALL
  SELECT 'apontamentos'                 , count(*)           FROM lakehouse_vertice.bronze.apontamentos        UNION ALL
  SELECT 'custos'                       , count(*)           FROM lakehouse_vertice.bronze.custos              UNION ALL
  SELECT 'entregas_fornecedor'          , count(*)           FROM lakehouse_vertice.bronze.entregas_fornecedor
),
divergentes AS (
  SELECT
      count(*) AS quantas,
      -- lista "tabela (esperado X, obtido Y)" só das que divergiram
      concat_ws(', ', collect_list(
        concat(e.tabela, ' (esperado ', CAST(e.esperado AS STRING),
               ', obtido ', CAST(o.obtido AS STRING), ')')
      )) AS detalhe
  FROM esperado e
  JOIN obtido   o ON o.tabela = e.tabela
  WHERE o.obtido <> e.esperado
)
SELECT
    CASE
      WHEN quantas > 0 THEN raise_error(
        concat('conferencia_bronze: ', CAST(quantas AS STRING),
               ' tabela(s) divergiram da contagem esperada do seed 42 -> ',
               detalhe,
               '. Olhe a saida da tarefa ingestao_data_lake: ela e quem recria as 9 tabelas.')
      )
      ELSE 'bronze conferida: as 9 tabelas bateram com o esperado'
    END AS resultado
FROM divergentes;
