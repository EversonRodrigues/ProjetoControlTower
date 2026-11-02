-- =====================================================================
-- SILVER 04 · colaboradores e apontamentos
--
-- As 520 pessoas da Vértice e o timesheet semanal delas. Daqui sai a
-- resposta da terceira pergunta do dono: "tenho gente parada enquanto
-- outro projeto pede gente?".
--
-- Sujeira tratada aqui: 16 (COL0102, COL0257 e COL0433 aparecem duas
-- vezes — o cadastro bom é o que tem papel em minúsculas; a cópia veio
-- com nome e papel em CAIXA ALTA).
-- Conferência (seed 42): 523 linhas na bronze -> 520 colaboradores.
-- =====================================================================


-- ---------------------------------------------------------------------
-- colaboradores · 523 linhas, 520 pessoas
-- ---------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW colaboradores
(
  -- Se a deduplicação falhar, o custo da pessoa entra duas vezes no CPI.
  CONSTRAINT custo_hora_preenchido
    EXPECT (custo_hora IS NOT NULL)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'Cadastro das 520 pessoas da Vértice: papel, senioridade, custo/hora, admissão e desligamento. Uma linha por colaborador (as 3 duplicidades da bronze foram resolvidas mantendo o cadastro com papel em minúsculas).'
AS
WITH bruto AS (
  SELECT
      trim(colaborador_id)                  AS colaborador_id,
      trim(nome)                            AS nome,
      trim(papel)                           AS papel,
      lower(trim(senioridade))              AS senioridade,
      nullif(trim(custo_hora), '')          AS custo_hora,
      nullif(trim(data_admissao), '')       AS data_admissao,
      nullif(trim(data_desligamento), '')   AS data_desligamento
  FROM lakehouse_vertice.bronze.colaboradores
),
escolhido AS (
  -- A cópia duplicada veio em CAIXA ALTA. "papel igual ao papel em
  -- minúsculas" é o jeito mais direto de dizer "este é o cadastro bom".
  SELECT
      *,
      row_number() OVER (
        PARTITION BY colaborador_id
        ORDER BY CASE WHEN papel = lower(papel) THEN 0 ELSE 1 END
      ) AS ordem
  FROM bruto
)
SELECT
    colaborador_id,
    nome,
    lower(papel)                                        AS papel,
    senioridade,
    CAST(replace(custo_hora, ',', '.') AS DECIMAL(18,2)) AS custo_hora,
    coalesce(
      try_to_date(data_admissao, 'yyyy-MM-dd'),
      try_to_date(data_admissao, 'dd/MM/yyyy')
    )                                                   AS data_admissao,
    -- vazio aqui é bom sinal: a pessoa continua na empresa
    coalesce(
      try_to_date(data_desligamento, 'yyyy-MM-dd'),
      try_to_date(data_desligamento, 'dd/MM/yyyy')
    )                                                   AS data_desligamento,
    data_desligamento IS NULL                           AS ativo
FROM escolhido
WHERE ordem = 1;


-- ---------------------------------------------------------------------
-- apontamentos · 30.883 linhas de timesheet semanal
-- ---------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW apontamentos
(
  CONSTRAINT semana_preenchida
    EXPECT (semana IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- Horas disponíveis zeradas dividiriam por zero na utilização.
  CONSTRAINT horas_disponiveis_positivas
    EXPECT (horas_disponiveis > 0)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'Timesheet semanal: horas disponíveis x horas apontadas por pessoa e por projeto. Uma linha por colaborador, projeto e semana. A coluna semana aponta para a sexta, igual ao status_semanal e aos custos, para os três casarem na gold.'
AS
WITH bruto AS (
  SELECT
      trim(colaborador_id)                 AS colaborador_id,
      trim(projeto_id)                     AS projeto_id,
      nullif(trim(semana_inicio), '')      AS semana_inicio,
      nullif(trim(horas_disponiveis), '')  AS horas_disponiveis,
      nullif(trim(horas_apontadas), '')    AS horas_apontadas
  FROM lakehouse_vertice.bronze.apontamentos
),
datado AS (
  SELECT
      colaborador_id,
      projeto_id,
      coalesce(
        try_to_date(semana_inicio, 'yyyy-MM-dd'),
        try_to_date(semana_inicio, 'dd/MM/yyyy')
      )                                                 AS semana_inicio,
      CAST(replace(horas_disponiveis, ',', '.') AS DOUBLE) AS horas_disponiveis,
      CAST(replace(horas_apontadas,   ',', '.') AS DOUBLE) AS horas_apontadas
  FROM bruto
)
SELECT
    colaborador_id,
    projeto_id,
    semana_inicio,
    -- a semana começa na segunda e fecha na sexta: + 4 dias
    date_add(semana_inicio, 4)                          AS semana,
    horas_disponiveis,
    horas_apontadas
FROM datado;
