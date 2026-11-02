-- =====================================================================
-- TESTES DE QUALIDADE DA GOLD
--
-- A conferência da bronze perguntava "o dado chegou inteiro?".
-- Esta pergunta é outra: "a CONTA está certa?".
--
-- Cada linha é um número do seed 42 que não muda (CLAUDE.md §7). Se um
-- deles divergir, alguma fórmula da gold mudou de sentido e o relatório
-- do dono passa a mentir — então a tarefa falha e a noite para aqui.
--
-- Cada régua abaixo foi medida contra o dado real antes de entrar:
--   · SPI das tarefas = Σ(horas × % concluído) ÷ Σ(horas × % do prazo
--     decorrido DA TAREFA). Medir o prazo no nível do projeto derruba o
--     SPI da carteira para 0,87 e dobra a conta de projetos em atenção.
--   · estouro previsto = greatest(EAC − orçamento, 0) POR PROJETO, só
--     depois somado. Somar com sinal dá um número bem menor.
--   · CodeForge 1,41 é a MÉDIA DAS RAZÕES por entrega, não a razão das
--     somas (que dá 1,34).
--
-- Tolerância: contagem é igualdade exata. O CLAUDE.md publica SPI e CPI
-- da carteira com DUAS casas (0,92 e 0,97), então a tolerância deles é
-- 0,01 — a precisão em que o número foi publicado. O CPI medido é
-- 0,9650, que é 0,97 nessas duas casas; com tolerância 0,005 o teste
-- reprovaria um número certo. Já 0,87 (o SPI com o prazo medido no
-- nível do projeto) erra por 0,05 e continua sendo pego.
--
-- São DOIS statements separados por ';', como na conferência da bronze:
--   1) o relatório, que é a saída que você lê no run;
--   2) o freio, que derruba a tarefa se algum teste falhou.
-- O bloco de medidas aparece nos dois: a sql_task roda um statement por
-- vez e um CTE não atravessa o ';'.
--
-- Caminho sempre completo: sql_task não tem catálogo padrão.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) O relatório: uma linha por régua, esperado × obtido
-- ---------------------------------------------------------------------
WITH t AS (
  SELECT
      count(*)                                                        AS tarefas,
      count_if(ferramenta = 'excel')                                  AS tarefas_excel,
      count_if(ferramenta = 'clickup')                                AS tarefas_clickup,
      count_if(ferramenta = 'msproject')                              AS tarefas_msproject
  FROM lakehouse_vertice.silver.tarefas
),
s AS (
  SELECT
      count_if(status = 'em_andamento')                               AS em_andamento,
      count_if(status = 'concluido')                                  AS concluidos,
      count_if(status = 'em_andamento' AND situacao = 'critico')       AS criticos,
      count_if(status = 'em_andamento' AND situacao = 'atencao')       AS atencao,
      count_if(status = 'em_andamento' AND melancia)                   AS melancias,
      count_if(status = 'em_andamento' AND spi IS NULL)                AS spi_nulo,
      count(*)                                                        AS linhas_situacao,
      sum(CASE WHEN status = 'em_andamento' THEN estouro_previsto END) / 1e6 AS estouro_mi,
      sum(CASE WHEN status = 'em_andamento' THEN horas_agregadas END)
        / sum(CASE WHEN status = 'em_andamento' THEN horas_de_prazo_decorrido END) AS spi_carteira,
      sum(CASE WHEN status = 'em_andamento' THEN ev_dinheiro END)
        / sum(CASE WHEN status = 'em_andamento' THEN custo_real END)  AS cpi_carteira,
      concat_ws(',', sort_array(collect_list(
        CASE WHEN status = 'em_andamento' AND melancia THEN projeto_id END))) AS lista_melancias
  FROM lakehouse_vertice.gold.projeto_situacao_atual
),
f AS (SELECT count(*) AS linhas_fato FROM lakehouse_vertice.gold.fato_projeto_semana),
c AS (SELECT sum(valor) / 1e6 AS custo_mi FROM lakehouse_vertice.silver.custos),
e AS (
  SELECT
      count_if(em_atraso)                                             AS entregas_atraso,
      count_if(em_atraso AND fornecedor = 'CodeForge Consultoria Ltda') AS entregas_atraso_codeforge,
      avg(CASE WHEN fornecedor = 'CodeForge Consultoria Ltda'
               THEN prazo_real_dias / prazo_prometido_dias END)        AS codeforge_razao
  FROM lakehouse_vertice.silver.entregas_fornecedor
),
u AS (
  SELECT count(*) AS sres_parados FROM (
    SELECT colaborador_id
    FROM lakehouse_vertice.gold.utilizacao_pessoa_semana
    WHERE papel = 'sre' AND semana > date_sub(DATE'2026-10-16', 84)
    GROUP BY colaborador_id
    HAVING avg(pct_utilizacao) < 0.20)
),
-- teste | esperado | obtido | tolerancia (0 = igualdade exata)
medidas AS (
  SELECT 'silver.tarefas'                  AS teste, 4917.0   AS esperado, CAST(t.tarefas            AS DOUBLE) AS obtido, 0.0    AS tolerancia FROM t UNION ALL
  SELECT 'silver.tarefas excel'                   , 1643.0            , CAST(t.tarefas_excel      AS DOUBLE)           , 0.0               FROM t UNION ALL
  SELECT 'silver.tarefas clickup'                 , 2119.0            , CAST(t.tarefas_clickup    AS DOUBLE)           , 0.0               FROM t UNION ALL
  SELECT 'silver.tarefas msproject'               , 1155.0            , CAST(t.tarefas_msproject  AS DOUBLE)           , 0.0               FROM t UNION ALL
  SELECT 'projetos em andamento'                  ,   41.0            , CAST(s.em_andamento       AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'projetos concluidos'                    ,   19.0            , CAST(s.concluidos         AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'gold.fato_projeto_semana linhas'        , 3911.0            , CAST(f.linhas_fato        AS DOUBLE)           , 0.0               FROM f UNION ALL
  SELECT 'gold.projeto_situacao_atual linhas'     ,   60.0            , CAST(s.linhas_situacao    AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'projetos criticos'                      ,    7.0            , CAST(s.criticos           AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'projetos em atencao'                    ,   10.0            , CAST(s.atencao            AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'melancias'                              ,    4.0            , CAST(s.melancias          AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'melancias sao PRJ-012/028/034/042'      ,    1.0            ,
         CAST(CASE WHEN s.lista_melancias = 'PRJ-012,PRJ-028,PRJ-034,PRJ-042' THEN 1 ELSE 0 END AS DOUBLE)            , 0.0               FROM s UNION ALL
  SELECT 'SPI nulo em projeto em andamento'       ,    0.0            , CAST(s.spi_nulo           AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'custo real total (R$ mi)'               ,  193.35           , c.custo_mi                                     , 0.01              FROM c UNION ALL
  SELECT 'estouro previsto (R$ mi)'               ,    6.47           , s.estouro_mi                                   , 0.01              FROM s UNION ALL
  SELECT 'SPI da carteira'                        ,    0.92           , s.spi_carteira                                 , 0.01              FROM s UNION ALL
  SELECT 'CPI da carteira'                        ,    0.97           , s.cpi_carteira                                 , 0.01              FROM s UNION ALL
  SELECT 'entregas em atraso'                     ,    5.0            , CAST(e.entregas_atraso    AS DOUBLE)           , 0.0               FROM e UNION ALL
  SELECT 'entregas em atraso da CodeForge'        ,    5.0            , CAST(e.entregas_atraso_codeforge AS DOUBLE)    , 0.0               FROM e UNION ALL
  SELECT 'CodeForge prazo real / prometido'       ,    1.41           , e.codeforge_razao                              , 0.005             FROM e UNION ALL
  SELECT 'SREs com menos de 20% de uso (12 sem.)' ,    2.0            , CAST(u.sres_parados       AS DOUBLE)           , 0.0               FROM u
),
avaliado AS (
  SELECT teste, esperado, obtido, tolerancia,
         abs(coalesce(obtido, -1) - esperado) <= tolerancia AS passou
  FROM medidas
)
SELECT
    teste,
    round(esperado, 4)                               AS esperado,
    round(obtido,   4)                               AS obtido,
    round(obtido - esperado, 4)                      AS diferenca,
    CASE WHEN passou THEN 'ok' ELSE 'FALHOU' END     AS situacao
FROM avaliado
-- quem falhou primeiro: o problema aparece na primeira linha do run
ORDER BY passou, teste;

-- ---------------------------------------------------------------------
-- 2) O freio: se alguma régua falhou, a tarefa morre aqui e o modelo
--    da noite 4 não treina em cima de uma gold errada.
-- ---------------------------------------------------------------------
WITH t AS (
  SELECT
      count(*)                                                        AS tarefas,
      count_if(ferramenta = 'excel')                                  AS tarefas_excel,
      count_if(ferramenta = 'clickup')                                AS tarefas_clickup,
      count_if(ferramenta = 'msproject')                              AS tarefas_msproject
  FROM lakehouse_vertice.silver.tarefas
),
s AS (
  SELECT
      count_if(status = 'em_andamento')                               AS em_andamento,
      count_if(status = 'concluido')                                  AS concluidos,
      count_if(status = 'em_andamento' AND situacao = 'critico')       AS criticos,
      count_if(status = 'em_andamento' AND situacao = 'atencao')       AS atencao,
      count_if(status = 'em_andamento' AND melancia)                   AS melancias,
      count_if(status = 'em_andamento' AND spi IS NULL)                AS spi_nulo,
      count(*)                                                        AS linhas_situacao,
      sum(CASE WHEN status = 'em_andamento' THEN estouro_previsto END) / 1e6 AS estouro_mi,
      sum(CASE WHEN status = 'em_andamento' THEN horas_agregadas END)
        / sum(CASE WHEN status = 'em_andamento' THEN horas_de_prazo_decorrido END) AS spi_carteira,
      sum(CASE WHEN status = 'em_andamento' THEN ev_dinheiro END)
        / sum(CASE WHEN status = 'em_andamento' THEN custo_real END)  AS cpi_carteira,
      concat_ws(',', sort_array(collect_list(
        CASE WHEN status = 'em_andamento' AND melancia THEN projeto_id END))) AS lista_melancias
  FROM lakehouse_vertice.gold.projeto_situacao_atual
),
f AS (SELECT count(*) AS linhas_fato FROM lakehouse_vertice.gold.fato_projeto_semana),
c AS (SELECT sum(valor) / 1e6 AS custo_mi FROM lakehouse_vertice.silver.custos),
e AS (
  SELECT
      count_if(em_atraso)                                             AS entregas_atraso,
      count_if(em_atraso AND fornecedor = 'CodeForge Consultoria Ltda') AS entregas_atraso_codeforge,
      avg(CASE WHEN fornecedor = 'CodeForge Consultoria Ltda'
               THEN prazo_real_dias / prazo_prometido_dias END)        AS codeforge_razao
  FROM lakehouse_vertice.silver.entregas_fornecedor
),
u AS (
  SELECT count(*) AS sres_parados FROM (
    SELECT colaborador_id
    FROM lakehouse_vertice.gold.utilizacao_pessoa_semana
    WHERE papel = 'sre' AND semana > date_sub(DATE'2026-10-16', 84)
    GROUP BY colaborador_id
    HAVING avg(pct_utilizacao) < 0.20)
),
-- teste | esperado | obtido | tolerancia (0 = igualdade exata)
medidas AS (
  SELECT 'silver.tarefas'                  AS teste, 4917.0   AS esperado, CAST(t.tarefas            AS DOUBLE) AS obtido, 0.0    AS tolerancia FROM t UNION ALL
  SELECT 'silver.tarefas excel'                   , 1643.0            , CAST(t.tarefas_excel      AS DOUBLE)           , 0.0               FROM t UNION ALL
  SELECT 'silver.tarefas clickup'                 , 2119.0            , CAST(t.tarefas_clickup    AS DOUBLE)           , 0.0               FROM t UNION ALL
  SELECT 'silver.tarefas msproject'               , 1155.0            , CAST(t.tarefas_msproject  AS DOUBLE)           , 0.0               FROM t UNION ALL
  SELECT 'projetos em andamento'                  ,   41.0            , CAST(s.em_andamento       AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'projetos concluidos'                    ,   19.0            , CAST(s.concluidos         AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'gold.fato_projeto_semana linhas'        , 3911.0            , CAST(f.linhas_fato        AS DOUBLE)           , 0.0               FROM f UNION ALL
  SELECT 'gold.projeto_situacao_atual linhas'     ,   60.0            , CAST(s.linhas_situacao    AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'projetos criticos'                      ,    7.0            , CAST(s.criticos           AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'projetos em atencao'                    ,   10.0            , CAST(s.atencao            AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'melancias'                              ,    4.0            , CAST(s.melancias          AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'melancias sao PRJ-012/028/034/042'      ,    1.0            ,
         CAST(CASE WHEN s.lista_melancias = 'PRJ-012,PRJ-028,PRJ-034,PRJ-042' THEN 1 ELSE 0 END AS DOUBLE)            , 0.0               FROM s UNION ALL
  SELECT 'SPI nulo em projeto em andamento'       ,    0.0            , CAST(s.spi_nulo           AS DOUBLE)           , 0.0               FROM s UNION ALL
  SELECT 'custo real total (R$ mi)'               ,  193.35           , c.custo_mi                                     , 0.01              FROM c UNION ALL
  SELECT 'estouro previsto (R$ mi)'               ,    6.47           , s.estouro_mi                                   , 0.01              FROM s UNION ALL
  SELECT 'SPI da carteira'                        ,    0.92           , s.spi_carteira                                 , 0.01              FROM s UNION ALL
  SELECT 'CPI da carteira'                        ,    0.97           , s.cpi_carteira                                 , 0.01              FROM s UNION ALL
  SELECT 'entregas em atraso'                     ,    5.0            , CAST(e.entregas_atraso    AS DOUBLE)           , 0.0               FROM e UNION ALL
  SELECT 'entregas em atraso da CodeForge'        ,    5.0            , CAST(e.entregas_atraso_codeforge AS DOUBLE)    , 0.0               FROM e UNION ALL
  SELECT 'CodeForge prazo real / prometido'       ,    1.41           , e.codeforge_razao                              , 0.005             FROM e UNION ALL
  SELECT 'SREs com menos de 20% de uso (12 sem.)' ,    2.0            , CAST(u.sres_parados       AS DOUBLE)           , 0.0               FROM u
),
avaliado AS (
  SELECT teste, esperado, obtido, tolerancia,
         abs(coalesce(obtido, -1) - esperado) <= tolerancia AS passou
  FROM medidas
)
, falhas AS (
  SELECT
      count(*) AS quantas,
      concat_ws(' | ', collect_list(
        concat(teste, ' (esperado ', CAST(round(esperado, 4) AS STRING),
               ', obtido ', CAST(round(coalesce(obtido, -1), 4) AS STRING), ')')
      )) AS detalhe
  FROM avaliado
  WHERE NOT passou
)
SELECT
    CASE
      WHEN quantas > 0 THEN raise_error(
        concat('testes_de_qualidade: ', CAST(quantas AS STRING),
               ' regua(s) do seed 42 divergiram -> ', detalhe,
               '. A conta da gold mudou de sentido: olhe src/gold/ antes de seguir.')
      )
      ELSE concat('gold conferida: as ', CAST((SELECT count(*) FROM avaliado) AS STRING),
                  ' reguas do seed 42 bateram')
    END AS resultado
FROM falhas;
