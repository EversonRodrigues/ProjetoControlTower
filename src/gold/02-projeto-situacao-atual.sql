-- =====================================================================
-- GOLD 02 · projeto_situacao_atual
--
-- A FOTOGRAFIA DE HOJE (16/10/2026): uma linha por projeto, 60 linhas.
--
-- Aqui o avanço vem das TAREFAS das três ferramentas, não do status do
-- gerente. É a diferença de propósito entre as duas tabelas gold:
--   · fato_projeto_semana = a série histórica (status de cada sexta)
--   · projeto_situacao_atual = onde cada projeto está agora (tarefas)
--
-- Esta tabela já traz o cadastro (cliente, segmento, tipo, ferramenta,
-- gerente, contrato e prazo) de propósito: é o que o Genie lê e é o que
-- dispensa uma dim_projeto.
--
-- SPI das tarefas, ponderado por horas (manual da Vértice):
--   Σ(horas × % concluído) ÷ Σ(horas × % do prazo baseline decorrido)
-- Com o prazo lido no nível do projeto, o Σ(horas) se cancela e sobra
-- o % ponderado ÷ o prazo decorrido.
--
-- Responde as perguntas 1 e 2 do dono: quais projetos estão atrasados,
-- de quais clientes, e quanto esse atraso vai custar.
--
-- Conferência (seed 42): 60 linhas; dos 41 em andamento, 7 críticos e
-- 10 em atenção, R$ 6,47 mi de estouro previsto e 4 melancias.
-- =====================================================================

CREATE OR REFRESH MATERIALIZED VIEW lakehouse_vertice.gold.projeto_situacao_atual
(
  CONSTRAINT projeto_preenchido
    EXPECT (projeto_id IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- Sem horas não há como ponderar o avanço: o SPI sairia nulo em silêncio.
  CONSTRAINT tem_horas_de_baseline
    EXPECT (horas_baseline > 0)
    ON VIOLATION FAIL UPDATE,

  -- O SPI das tarefas saiu NULL em 25 dos 60 projetos enquanto o baseline
  -- do ClickUp nao era lido (milissegundos lidos como texto). O least()
  -- ignora NULL, entao o buraco passava despercebido e o projeto era
  -- julgado so pelo CPI. Esta regra nao deixa isso voltar.
  CONSTRAINT spi_calculado_para_quem_esta_em_andamento
    EXPECT (status <> 'em_andamento' OR spi IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  CONSTRAINT situacao_conhecida
    EXPECT (situacao IN ('ok', 'atencao', 'critico'))
    ON VIOLATION FAIL UPDATE,

  -- Estouro é "só quando positivo": negativo aqui é erro de conta.
  CONSTRAINT estouro_nao_negativo
    EXPECT (estouro_previsto >= 0)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'A fotografia de hoje (16/10/2026) dos 60 projetos da Vértice: o cadastro completo (cliente, segmento, tipo de projeto, ferramenta, gerente, valor de contrato e prazo baseline) mais SPI, CPI, EAC, estouro previsto, margem projetada, atraso projetado em dias, o farol calculado, o farol do gerente e a flag melancia. Uma linha por projeto. O avanço vem das tarefas das três ferramentas (Excel, ClickUp e MS Project), não do status semanal.'
AS
WITH tarefa_com_prazo AS (
  -- O prazo decorrido de CADA tarefa, que e o PV do manual da Vertice:
  -- "Sigma horas x % do prazo baseline decorrido". Medir o prazo no nivel
  -- do projeto em vez da tarefa derruba o SPI da carteira de 0,93 para
  -- 0,87 e dobra a conta de projetos em atencao: tarefa que ainda nao
  -- comecou no baseline nao deve pesar no denominador.
  SELECT
      t.projeto_id,
      t.horas,
      t.pct_concluido,
      t.fim_baseline,
      coalesce(
        least(greatest(
          datediff(DATE'2026-10-16', t.inicio_baseline)
            / nullif(datediff(t.fim_baseline, t.inicio_baseline), 0)
        , 0), 1),
        -- rede de seguranca: tarefa sem baseline cai no prazo do projeto
        least(greatest(
          datediff(DATE'2026-10-16', p.data_inicio)
            / nullif(datediff(p.data_fim_baseline, p.data_inicio), 0)
        , 0), 1)
      )                                        AS pct_prazo_da_tarefa
  FROM tarefas t
  JOIN projetos p USING (projeto_id)
),
avanco AS (
  -- Agregação pura das tarefas. Nenhuma janela aqui de propósito.
  SELECT
      projeto_id,
      count(*)                                 AS qtd_tarefas,
      sum(horas)                               AS horas_baseline,
      sum(horas * pct_concluido / 100.0)       AS horas_agregadas,
      sum(horas * pct_prazo_da_tarefa)         AS horas_de_prazo_decorrido,
      sum(CASE WHEN pct_concluido >= 100 THEN 1 ELSE 0 END) AS tarefas_concluidas,
      -- tarefa cujo fim baseline já passou e que não terminou
      sum(CASE WHEN fim_baseline < DATE'2026-10-16'
                AND pct_concluido < 100 THEN 1 ELSE 0 END)  AS tarefas_vencidas
  FROM tarefa_com_prazo
  GROUP BY projeto_id
),
custo_real AS (
  SELECT
      projeto_id,
      CAST(sum(valor) AS DOUBLE) AS custo_real
  FROM custos
  WHERE data <= DATE'2026-10-16'
  GROUP BY projeto_id
),
status_ordenado AS (
  -- A janela mora num CTE só dela: dentro de uma agregação ela quebraria
  -- o pipeline.
  SELECT
      projeto_id,
      data_status,
      farol,
      pct_concluido AS pct_do_gerente,
      texto_status,
      row_number() OVER (PARTITION BY projeto_id ORDER BY data_status DESC) AS ordem
  FROM status_semanal
),
ultimo_status AS (
  SELECT projeto_id, data_status, farol, pct_do_gerente, texto_status
  FROM status_ordenado
  WHERE ordem = 1
),
fornecedor AS (
  SELECT
      projeto_id,
      count(*)                                   AS entregas,
      sum(CASE WHEN em_atraso THEN 1 ELSE 0 END) AS entregas_em_atraso
  FROM entregas_fornecedor
  GROUP BY projeto_id
),
base AS (
  SELECT
      p.projeto_id,
      p.nome_projeto,
      p.cliente,
      p.segmento,
      p.tipo_projeto,
      p.ferramenta,
      p.gerente_projeto,
      p.status,
      p.data_inicio,
      p.data_fim_baseline,
      datediff(p.data_fim_baseline, p.data_inicio) AS duracao_baseline_dias,
      CAST(p.valor_contrato  AS DOUBLE)            AS valor_contrato,
      CAST(p.orcamento_custo AS DOUBLE)            AS orcamento_custo,

      a.qtd_tarefas,
      a.horas_baseline,
      a.horas_agregadas,
      a.horas_de_prazo_decorrido,
      a.tarefas_concluidas,
      a.tarefas_vencidas,
      a.horas_agregadas / nullif(a.horas_baseline, 0) AS pct_concluido_ponderado,

      coalesce(c.custo_real, 0)                    AS custo_real,

      u.farol                                      AS farol_do_gerente,
      u.data_status                                AS data_ultimo_status,
      u.pct_do_gerente,
      u.texto_status                               AS ultimo_texto_status,

      coalesce(f.entregas, 0)                      AS entregas,
      coalesce(f.entregas_em_atraso, 0)            AS entregas_em_atraso,

      -- o mesmo pct_prazo do fato, só que medido em 16/10/2026
      least(greatest(
        datediff(DATE'2026-10-16', p.data_inicio)
          / nullif(datediff(p.data_fim_baseline, p.data_inicio), 0)
      , 0), 1)                                     AS pct_prazo
  FROM projetos p
  JOIN avanco        a USING (projeto_id)
  LEFT JOIN custo_real    c USING (projeto_id)
  LEFT JOIN ultimo_status u USING (projeto_id)
  LEFT JOIN fornecedor    f USING (projeto_id)
),
indices AS (
  SELECT
      b.*,
      -- SPI = Sigma(horas x % concluido) / Sigma(horas x % do prazo decorrido)
      horas_agregadas / nullif(horas_de_prazo_decorrido, 0)             AS spi,
      orcamento_custo * pct_concluido_ponderado / nullif(custo_real, 0) AS cpi
  FROM base b
)
SELECT
    projeto_id,
    nome_projeto,
    cliente,
    segmento,
    tipo_projeto,
    ferramenta,
    gerente_projeto,
    status,
    data_inicio,
    data_fim_baseline,
    duracao_baseline_dias,
    valor_contrato,
    orcamento_custo,

    qtd_tarefas,
    tarefas_concluidas,
    tarefas_vencidas,
    horas_baseline,
    horas_agregadas,
    horas_de_prazo_decorrido,
    round(pct_concluido_ponderado * 100, 1)                  AS pct_concluido,
    pct_prazo,
    custo_real,

    orcamento_custo * pct_concluido_ponderado                AS ev_dinheiro,
    orcamento_custo * pct_prazo                              AS pv_dinheiro,

    spi,
    cpi,
    least(spi, cpi)                                          AS indice_min,

    orcamento_custo / nullif(cpi, 0)                         AS eac,
    greatest(orcamento_custo / nullif(cpi, 0) - orcamento_custo, 0) AS estouro_previsto,
    (valor_contrato - orcamento_custo / nullif(cpi, 0))
      / nullif(valor_contrato, 0)                            AS margem_projetada,
    duracao_baseline_dias / nullif(spi, 0) - duracao_baseline_dias AS atraso_projetado_dias,

    CASE
      WHEN spi >= 0.95 THEN 'verde'
      WHEN spi >= 0.90 THEN 'amarelo'
      ELSE 'vermelho'
    END                                                      AS farol_calculado,
    farol_do_gerente,
    data_ultimo_status,
    pct_do_gerente,
    ultimo_texto_status,
    (farol_do_gerente = 'verde' AND spi < 0.9)               AS melancia,

    CASE
      WHEN least(spi, cpi) < 0.8 THEN 'critico'
      WHEN least(spi, cpi) < 0.9 THEN 'atencao'
      ELSE 'ok'
    END                                                      AS situacao,

    entregas,
    entregas_em_atraso
FROM indices;
