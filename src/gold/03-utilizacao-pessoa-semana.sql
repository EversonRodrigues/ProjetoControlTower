-- =====================================================================
-- GOLD 03 · utilizacao_pessoa_semana
--
-- A terceira pergunta do dono: "tenho gente parada enquanto outro
-- projeto pede gente?".
--
-- Grão: uma linha por PESSOA e por SEMANA (é o que o nome diz). As
-- horas dos vários projetos da semana somam, mas guardamos o
-- projeto_principal (o de mais horas naquela semana) — sem ele a
-- resposta "COL0017 e COL0018 estão com 5% de uso" fica sem o "no
-- PRJ-007", que é a metade útil da frase.
--
-- As duas janelas (o projeto principal e a média móvel de 12 semanas)
-- moram cada uma num CTE próprio: janela dentro de agregação quebra
-- no pipeline.
--
-- Conferência (seed 42): COL0017 e COL0018 são os SREs com menos de
-- 20% de uso em 12 semanas, no PRJ-007 (5,8% e 5,5%).
-- =====================================================================

CREATE OR REFRESH MATERIALIZED VIEW lakehouse_vertice.gold.utilizacao_pessoa_semana
(
  CONSTRAINT chave_preenchida
    EXPECT (colaborador_id IS NOT NULL AND semana IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- Horas disponíveis zeradas dividiriam por zero na utilização.
  CONSTRAINT horas_disponiveis_positivas
    EXPECT (horas_disponiveis > 0)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'Utilização semanal das 520 pessoas da Vértice: horas disponíveis x horas apontadas, o percentual de uso, a média móvel de 12 semanas, o custo das horas apontadas e o projeto em que a pessoa mais trabalhou na semana. Uma linha por colaborador e por sexta. Responde "tenho gente parada enquanto outro projeto pede gente?": pessoa_parada marca quem ficou abaixo de 20% de uso.'
AS
WITH por_pessoa_semana AS (
  SELECT
      colaborador_id,
      semana,
      sum(horas_disponiveis)     AS horas_disponiveis,
      sum(horas_apontadas)       AS horas_apontadas,
      count(DISTINCT projeto_id) AS projetos_na_semana
  FROM apontamentos
  GROUP BY colaborador_id, semana
),
projeto_ordenado AS (
  -- qual projeto levou mais horas dessa pessoa nessa semana
  SELECT
      colaborador_id,
      semana,
      projeto_id,
      row_number() OVER (PARTITION BY colaborador_id, semana
                         ORDER BY horas_apontadas DESC, projeto_id) AS ordem
  FROM apontamentos
),
projeto_principal AS (
  SELECT colaborador_id, semana, projeto_id AS projeto_principal
  FROM projeto_ordenado
  WHERE ordem = 1
),
com_cadastro AS (
  SELECT
      s.colaborador_id,
      s.semana,
      s.horas_disponiveis,
      s.horas_apontadas,
      s.projetos_na_semana,
      pp.projeto_principal,
      c.nome,
      c.papel,
      c.senioridade,
      c.ativo,
      CAST(c.custo_hora AS DOUBLE)                       AS custo_hora,
      s.horas_apontadas / nullif(s.horas_disponiveis, 0) AS pct_utilizacao
  FROM por_pessoa_semana s
  LEFT JOIN projeto_principal pp USING (colaborador_id, semana)
  JOIN colaboradores c USING (colaborador_id)
),
com_media_movel AS (
  SELECT
      j.*,
      avg(pct_utilizacao) OVER (
        PARTITION BY colaborador_id ORDER BY semana
        ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)       AS media_12s,
      count(*) OVER (
        PARTITION BY colaborador_id ORDER BY semana
        ROWS BETWEEN 11 PRECEDING AND CURRENT ROW)       AS semanas_na_janela
  FROM com_cadastro j
)
SELECT
    colaborador_id,
    nome,
    papel,
    senioridade,
    ativo,
    semana,
    projeto_principal,
    projetos_na_semana,
    horas_disponiveis,
    horas_apontadas,
    pct_utilizacao,
    -- a média de 12 semanas só vale quando há 12 semanas; antes disso
    -- ela mentiria para baixo no começo de cada carreira
    CASE WHEN semanas_na_janela = 12 THEN media_12s END   AS pct_utilizacao_12s,
    custo_hora * horas_apontadas                          AS custo_horas_apontadas,
    (pct_utilizacao < 0.20)                               AS pessoa_parada
FROM com_media_movel;
