-- =====================================================================
-- GOLD 01 · fato_projeto_semana
--
-- O HISTÓRICO do portfólio: uma linha por projeto e por sexta.
--
-- Por que o avanço vem do status do gerente, e não das tarefas?
-- Porque Excel, ClickUp e MS Project guardam só o % de HOJE. Quem tem
-- memória semanal é o status que o gerente escreve toda sexta. A
-- fotografia de hoje é a outra tabela (projeto_situacao_atual).
--
-- Conferido na silver antes de escrever este arquivo:
--   · as 98 datas de status são TODAS sexta (dayofweek = 6)
--   · nenhum projeto tem buraco na série semanal
-- É isso que deixa o modelo da noite 4 dizer "4 semanas à frente" com
-- ROWS ... FOLLOWING e saber que são 30 dias de verdade.
--
-- O custo acumulado sai de um "as-of join" (custos.semana <= a sexta da
-- linha) e não de uma janela: função de janela dentro de agregação
-- quebra no pipeline, e assim o problema nem existe.
--
-- O "hoje" do dataset é 16/10/2026. Nunca current_date().
-- Conferência (seed 42): 3.911 linhas, as mesmas do status_semanal.
-- =====================================================================

CREATE OR REFRESH MATERIALIZED VIEW lakehouse_vertice.gold.fato_projeto_semana
(
  CONSTRAINT chave_preenchida
    EXPECT (projeto_id IS NOT NULL AND semana IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- O % vem do status já limpo na silver; fora de 0..100 a conta de SPI mente.
  CONSTRAINT pct_entre_0_e_100
    EXPECT (pct_concluido BETWEEN 0 AND 100)
    ON VIOLATION FAIL UPDATE,

  -- O prazo decorrido é uma fração: o clip em 1 é o que segura o SPI de
  -- projeto que já passou do baseline.
  CONSTRAINT pct_prazo_e_fracao
    EXPECT (pct_prazo BETWEEN 0 AND 1)
    ON VIOLATION FAIL UPDATE,

  -- A semana da Vértice fecha na sexta. Se um dia chegar um status de
  -- quarta, o alvo de 30 dias do modelo passa a contar linhas erradas:
  -- melhor o pipeline parar aqui do que o modelo mentir depois.
  CONSTRAINT semana_e_sexta
    EXPECT (dayofweek(semana) = 6)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'O histórico do portfólio da Vértice, semana a semana (toda sexta). Uma linha por projeto e por semana. O avanço vem do status que o gerente reporta (as três ferramentas só guardam o % de hoje) e o custo é o acumulado até aquela sexta. Traz SPI, CPI, EAC, estouro previsto, margem projetada, atraso projetado, o farol calculado e a flag melancia de cada semana: é a série histórica que o modelo de estouro da noite 4 aprende.'
AS
WITH grade AS (
  -- A grade é o próprio status semanal: é ele que define quais sextas
  -- cada projeto viveu (projeto concluído para de reportar).
  SELECT
      projeto_id,
      data_status                AS semana,
      pct_concluido,
      farol,
      gerente,
      status_vazio
  FROM status_semanal
),
cadastro AS (
  SELECT
      g.projeto_id,
      g.semana,
      g.pct_concluido,
      g.farol,
      g.gerente,
      g.status_vazio,
      p.status                                               AS status_projeto,
      CAST(p.valor_contrato   AS DOUBLE)                     AS valor_contrato,
      CAST(p.orcamento_custo  AS DOUBLE)                     AS orcamento_custo,
      p.data_inicio,
      p.data_fim_baseline,
      datediff(p.data_fim_baseline, p.data_inicio)           AS duracao_baseline_dias,

      -- PV: a fração do prazo baseline já decorrida NAQUELA sexta.
      -- greatest(...,0) para semana anterior ao início; least(...,1)
      -- para quem já passou do fim baseline.
      least(greatest(
        datediff(g.semana, p.data_inicio)
          / nullif(datediff(p.data_fim_baseline, p.data_inicio), 0)
      , 0), 1)                                               AS pct_prazo
  FROM grade g
  JOIN projetos p USING (projeto_id)
),
custo_acumulado AS (
  -- "as-of join": tudo o que foi gasto ATÉ aquela sexta (inclusive).
  -- Sem janela, logo sem a armadilha de janela-dentro-de-agregação.
  SELECT
      g.projeto_id,
      g.semana,
      CAST(coalesce(sum(c.valor), 0) AS DOUBLE) AS ac_dinheiro
  FROM grade g
  LEFT JOIN custos c
         ON c.projeto_id = g.projeto_id
        AND c.semana    <= g.semana
  GROUP BY g.projeto_id, g.semana
),
timesheet AS (
  SELECT
      projeto_id,
      semana,
      sum(horas_disponiveis)         AS horas_disponiveis,
      sum(horas_apontadas)           AS horas_apontadas,
      count(DISTINCT colaborador_id) AS pessoas_na_semana
  FROM apontamentos
  GROUP BY projeto_id, semana
),
indices AS (
  SELECT
      c.*,
      a.ac_dinheiro,
      t.horas_disponiveis,
      t.horas_apontadas,
      t.pessoas_na_semana,

      -- EV e PV em dinheiro, para o CPI e para quem quiser auditar a conta
      c.orcamento_custo * c.pct_concluido / 100.0  AS ev_dinheiro,
      c.orcamento_custo * c.pct_prazo              AS pv_dinheiro,

      -- SPI = EV / PV. Com os dois em fração, o orçamento se cancela.
      (c.pct_concluido / 100.0) / nullif(c.pct_prazo, 0)                       AS spi,

      -- CPI = EV / AC, agora em dinheiro (o custo real é dinheiro).
      (c.orcamento_custo * c.pct_concluido / 100.0) / nullif(a.ac_dinheiro, 0) AS cpi
  FROM cadastro c
  JOIN custo_acumulado a USING (projeto_id, semana)
  LEFT JOIN timesheet   t USING (projeto_id, semana)
)
SELECT
    projeto_id,
    semana,
    status_projeto,

    pct_concluido,
    pct_prazo,
    ev_dinheiro,
    pv_dinheiro,
    ac_dinheiro,

    spi,
    cpi,
    -- o índice que manda é o pior dos dois: atraso OU estouro já é problema
    least(spi, cpi)                                          AS indice_min,

    orcamento_custo / nullif(cpi, 0)                         AS eac,

    -- estouro só conta quando é positivo (manual da Vértice)
    greatest(orcamento_custo / nullif(cpi, 0) - orcamento_custo, 0) AS estouro_previsto,

    (valor_contrato - orcamento_custo / nullif(cpi, 0))
      / nullif(valor_contrato, 0)                            AS margem_projetada,

    duracao_baseline_dias / nullif(spi, 0) - duracao_baseline_dias AS atraso_projetado_dias,

    -- O farol que o gerente reportou...
    farol                                                    AS farol_do_gerente,
    -- ...e o que a conta diz (regra do manual: 0,95 e 0,90)
    CASE
      WHEN spi >= 0.95 THEN 'verde'
      WHEN spi >= 0.90 THEN 'amarelo'
      ELSE 'vermelho'
    END                                                      AS farol_calculado,

    -- Melancia: verde por fora, atrasado por dentro.
    (farol = 'verde' AND spi < 0.9)                          AS melancia,

    -- Regra de corte da Vértice: SPI OU CPI < 0,9 é atenção; < 0,8 é crítico.
    CASE
      WHEN least(spi, cpi) < 0.8 THEN 'critico'
      WHEN least(spi, cpi) < 0.9 THEN 'atencao'
      ELSE 'ok'
    END                                                      AS situacao,

    horas_disponiveis,
    horas_apontadas,
    horas_apontadas / nullif(horas_disponiveis, 0)           AS pct_utilizacao,
    pessoas_na_semana,

    status_vazio,
    gerente,
    valor_contrato,
    orcamento_custo,
    duracao_baseline_dias
FROM indices;
