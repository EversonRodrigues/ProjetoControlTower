-- =====================================================================
-- SILVER 02 · tarefas · AS TRÊS FERRAMENTAS VIRAM UMA
--
-- Este é o coração da Torre. Cada gerente controla o projeto na
-- ferramenta que prefere: 20 em planilhas Excel, 25 no ClickUp e 15 no
-- MS Project. Três formatos, três jeitos de escrever data, três jeitos
-- de escrever porcentagem. A silver.tarefas é o modelo ÚNICO onde as
-- três caem com as MESMAS colunas.
--
-- A receita é sempre a mesma: uma CREATE TEMPORARY VIEW por ferramenta,
-- todas com as 13 mesmas colunas, e um UNION ALL na materialized view.
-- Quem liga a tarefa ao projeto é o de-para da silver.projetos
-- (ferramenta + codigo_ferramenta).
--
-- Sujeiras tratadas aqui (seção 3 do CLAUDE.md):
--    4) data do Excel em texto dd/MM/yyyy OU em número de série
--    5) % do Excel em '45%', '10,5%' ou 0.45 (11 linhas acima de 100)
--    6) linha de TOTAL no fim de cada planilha (20 linhas)
--    7) horas do Excel como '40h'
--    8) datas do ClickUp em milissegundos; % e baseline em custom_fields
--    9) status do ClickUp escrito de 12 jeitos
--   10) tarefas-resumo do MS Project somando as horas das de baixo (105)
--   11) a fase do MS Project não está na tarefa, está na tarefa-resumo
--   12) horas do MS Project como 'PT40H0M0S'
--
-- Conferência (seed 42): 4.917 tarefas = 1.643 Excel + 2.119 ClickUp
-- + 1.155 MS Project.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1) EXCEL · 20 planilhas, tudo texto
-- ---------------------------------------------------------------------
CREATE TEMPORARY VIEW tarefas_excel AS
WITH bruto AS (
  SELECT
      e.arquivo,
      CAST(e.id AS STRING)            AS id_na_ferramenta,
      nullif(trim(e.fase), '')        AS fase,
      trim(e.tarefa)                  AS tarefa,
      nullif(trim(e.responsavel), '') AS responsavel,
      nullif(trim(e.inicio_previsto),  '') AS inicio_previsto,
      nullif(trim(e.termino_previsto), '') AS termino_previsto,
      nullif(trim(e.inicio_real),      '') AS inicio_real,
      nullif(trim(e.termino_real),     '') AS termino_real,
      nullif(trim(e.pct_concluido),    '') AS pct_concluido,
      nullif(trim(e.horas_previstas),  '') AS horas_previstas,
      -- o de-para: o "código da ferramenta" do Excel é o nome do arquivo
      p.projeto_id AS projeto_id_do_depara
  FROM lakehouse_vertice.bronze.excel_tarefas e
  LEFT JOIN projetos p
         ON p.ferramenta = 'excel'
        AND p.codigo_ferramenta = e.arquivo
  -- a última linha de cada planilha é o TOTAL, não é tarefa
  WHERE trim(e.tarefa) <> 'TOTAL'
)
SELECT
    -- Quando o de-para não casa (código vazio no cadastro, ou o arquivo
    -- chegou sem acento: 'Core bancario' x 'Core bancário'), o próprio
    -- nome do arquivo carrega o PRJ-xxx. É o plano B.
    coalesce(
      projeto_id_do_depara,
      nullif(regexp_extract(arquivo, 'PRJ-[0-9]{3}', 0), '')
    )                                                   AS projeto_id,
    'excel'                                             AS ferramenta,
    id_na_ferramenta,
    fase,
    tarefa,
    responsavel,

    -- Data com '/' é dd/MM/yyyy escrito à mão; sem '/' é o número de
    -- série do Excel, que conta os dias desde 30/12/1899.
    CASE WHEN contains(inicio_previsto, '/')
         THEN try_to_date(inicio_previsto, 'dd/MM/yyyy')
         ELSE date_add(DATE'1899-12-30', CAST(inicio_previsto AS INT))
    END                                                 AS inicio_baseline,
    CASE WHEN contains(termino_previsto, '/')
         THEN try_to_date(termino_previsto, 'dd/MM/yyyy')
         ELSE date_add(DATE'1899-12-30', CAST(termino_previsto AS INT))
    END                                                 AS fim_baseline,
    CASE WHEN contains(inicio_real, '/')
         THEN try_to_date(inicio_real, 'dd/MM/yyyy')
         ELSE date_add(DATE'1899-12-30', CAST(inicio_real AS INT))
    END                                                 AS inicio_real,
    CASE WHEN contains(termino_real, '/')
         THEN try_to_date(termino_real, 'dd/MM/yyyy')
         ELSE date_add(DATE'1899-12-30', CAST(termino_real AS INT))
    END                                                 AS fim_real,

    -- '45%' e '10,5%' já estão na escala 0-100: tira o '%' e troca a
    -- vírgula. '0.45' é fração: multiplica por 100.
    CASE WHEN contains(pct_concluido, '%')
         THEN CAST(replace(replace(pct_concluido, '%', ''), ',', '.') AS DOUBLE)
         ELSE CAST(replace(pct_concluido, ',', '.') AS DOUBLE) * 100
    END                                                 AS pct_como_veio,

    -- '40h' -> 40
    CAST(replace(replace(horas_previstas, 'h', ''), ',', '.') AS DOUBLE) AS horas,

    -- A planilha não tem coluna de status: quem quer saber o andamento
    -- olha o pct_concluido. NULL aqui é a verdade, não é dado faltando.
    CAST(NULL AS STRING)                                AS status_na_ferramenta
FROM bruto;


-- ---------------------------------------------------------------------
-- 2) CLICKUP · 25 listas, datas em milissegundos, metade do dado dentro
--    de custom_fields (uma lista de structs name/type/value)
-- ---------------------------------------------------------------------
CREATE TEMPORARY VIEW tarefas_clickup AS
WITH bruto AS (
  SELECT
      c.id                            AS id_na_ferramenta,
      trim(c.name)                    AS tarefa,
      c.assignees,
      c.custom_fields,
      c.start_date,
      c.date_done,
      c.time_estimate,
      c.status.status                 AS status_na_ferramenta,
      -- o de-para principal é o list_id; se o cadastro veio sem código,
      -- o nome da lista salva
      coalesce(por_id.projeto_id, por_nome.projeto_id) AS projeto_id
  FROM lakehouse_vertice.bronze.clickup_tarefas c
  LEFT JOIN projetos por_id
         ON por_id.ferramenta = 'clickup'
        AND por_id.codigo_ferramenta = c.list_id
  LEFT JOIN projetos por_nome
         ON por_nome.ferramenta = 'clickup'
        AND por_nome.nome_projeto = c.list_name
),
campos AS (
  SELECT
      *,
      -- filter(...)[0].value é o jeito de ler um custom field pelo nome
      filter(custom_fields, f -> f.name = 'Progresso (%)')[0].value   AS cf_pct,
      filter(custom_fields, f -> f.name = 'Início baseline')[0].value AS cf_inicio_baseline,
      filter(custom_fields, f -> f.name = 'Fim baseline')[0].value    AS cf_fim_baseline,
      filter(custom_fields, f -> f.name = 'Fase')[0].value            AS cf_fase
  FROM bruto
)
SELECT
    projeto_id,
    'clickup'                                           AS ferramenta,
    id_na_ferramenta,
    nullif(trim(cf_fase), '')                           AS fase,
    tarefa,
    assignees[0].username                               AS responsavel,

    -- O baseline do ClickUp vem em MILISSEGUNDOS, igual ao start_date e
    -- ao date_done abaixo -- e nao como texto de data. Com try_to_date as
    -- 2.119 tarefas das 25 listas ficavam com baseline NULL em silencio, o
    -- SPI das tarefas saia NULL em 25 dos 60 projetos e o least(spi, cpi)
    -- escondia o buraco (least ignora NULL). O coalesce aceita as duas
    -- formas: milissegundos primeiro, texto depois, caso a fonte mude.
    coalesce(
      to_date(timestamp_millis(try_cast(nullif(trim(cf_inicio_baseline), '') AS BIGINT))),
      try_to_date(nullif(trim(cf_inicio_baseline), ''), 'yyyy-MM-dd'),
      try_to_date(nullif(trim(cf_inicio_baseline), ''), 'dd/MM/yyyy')
    )                                                   AS inicio_baseline,
    coalesce(
      to_date(timestamp_millis(try_cast(nullif(trim(cf_fim_baseline), '') AS BIGINT))),
      try_to_date(nullif(trim(cf_fim_baseline), ''), 'yyyy-MM-dd'),
      try_to_date(nullif(trim(cf_fim_baseline), ''), 'dd/MM/yyyy')
    )                                                   AS fim_baseline,

    -- o ClickUp guarda data como milissegundos desde 1970
    to_date(timestamp_millis(CAST(nullif(trim(start_date), '') AS BIGINT))) AS inicio_real,
    to_date(timestamp_millis(CAST(nullif(trim(date_done),  '') AS BIGINT))) AS fim_real,

    CAST(replace(nullif(trim(cf_pct), ''), ',', '.') AS DOUBLE)  AS pct_como_veio,

    -- time_estimate vem em milissegundos: 3.600.000 ms = 1 hora
    time_estimate / 3600000.0                           AS horas,

    -- 12 grafias ('Complete', 'done', 'FINALIZADO', 'to do', 'backlog',
    -- 'em progresso'...) para três estados.
    CASE
      WHEN lower(status_na_ferramenta) RLIKE 'complet|done|finaliz|conclu|closed|entregue' THEN 'concluida'
      WHEN lower(status_na_ferramenta) RLIKE 'to ?do|todo|open|aberto|backlog|pendente|não iniciad|nao iniciad' THEN 'a_fazer'
      ELSE 'em_andamento'
    END                                                 AS status_na_ferramenta
FROM campos;


-- ---------------------------------------------------------------------
-- 3) MS PROJECT · 15 XML. Duas armadilhas: as tarefas-resumo somam as
--    horas das tarefas de baixo (contariam duas vezes), e a fase não
--    está na tarefa — está na tarefa-resumo acima dela.
-- ---------------------------------------------------------------------
CREATE TEMPORARY VIEW tarefas_msproject AS
WITH com_fase AS (
  -- A janela roda ANTES do filtro, de propósito: são justamente as
  -- linhas Summary = 1 que carregam o nome da fase. Se filtrássemos
  -- primeiro, a fase sumiria junto.
  SELECT
      m.*,
      last_value(CASE WHEN m.OutlineLevel = 1 THEN m.Name END, true)
        OVER (PARTITION BY m.arquivo ORDER BY m.UID)    AS fase
  FROM lakehouse_vertice.bronze.msproject_tarefas m
)
SELECT
    p.projeto_id,
    'msproject'                                         AS ferramenta,
    CAST(t.UID AS STRING)                               AS id_na_ferramenta,
    nullif(trim(t.fase), '')                            AS fase,
    trim(t.Name)                                        AS tarefa,
    -- o XML exportado não traz o recurso na tarefa
    CAST(NULL AS STRING)                                AS responsavel,
    CAST(t.Baseline.Start  AS DATE)                     AS inicio_baseline,
    CAST(t.Baseline.Finish AS DATE)                     AS fim_baseline,
    CAST(t.ActualStart     AS DATE)                     AS inicio_real,
    CAST(t.ActualFinish    AS DATE)                     AS fim_real,
    CAST(t.PercentComplete AS DOUBLE)                   AS pct_como_veio,

    -- 'PT40H0M0S' = 40 horas. Somamos os minutos para não zerar uma
    -- tarefa de meia hora (o EXPECT de horas > 0 é FAIL UPDATE).
    coalesce(CAST(nullif(regexp_extract(t.Work, 'PT([0-9]+)H', 1), '') AS DOUBLE), 0)
      + coalesce(CAST(nullif(regexp_extract(t.Work, 'H([0-9]+)M', 1), '') AS DOUBLE), 0) / 60.0
                                                        AS horas,
    -- o MS Project também não tem status textual: o andamento é o %
    CAST(NULL AS STRING)                                AS status_na_ferramenta
FROM com_fase t
LEFT JOIN projetos p
       ON p.ferramenta = 'msproject'
      AND p.codigo_ferramenta = t.arquivo
-- fora as 105 tarefas-resumo: as horas delas são a soma das de baixo
WHERE t.Summary = 0;


-- ---------------------------------------------------------------------
-- 4) A TABELA ÚNICA
-- ---------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW tarefas
(
  -- Tarefa sem projeto é tarefa invisível no portfólio: é o pior erro
  -- possível aqui, então para o pipeline.
  CONSTRAINT achou_o_projeto
    EXPECT (projeto_id IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- Depois do least(), 11 linhas acima de 100 viraram 100. Se alguma
  -- escapar da escala, a conta de SPI sai errada.
  CONSTRAINT pct_entre_0_e_100
    EXPECT (pct_concluido BETWEEN 0 AND 100)
    ON VIOLATION FAIL UPDATE,

  -- Hora é o peso de toda a agregação de avanço: sem hora, a tarefa
  -- não pesa nada e o SPI mente.
  CONSTRAINT horas_positivas
    EXPECT (horas > 0)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'As tarefas dos 60 projetos num modelo único, vindas das três ferramentas (Excel, ClickUp e MS Project). Uma linha por tarefa. É aqui que a integração acontece: pct_concluido e horas já estão na mesma escala, qualquer que seja a origem.'
AS
WITH tres_ferramentas AS (
  SELECT * FROM tarefas_excel
  UNION ALL
  SELECT * FROM tarefas_clickup
  UNION ALL
  SELECT * FROM tarefas_msproject
)
SELECT
    -- chave estável e legível: projeto + ferramenta + id de origem
    concat_ws('-', projeto_id, ferramenta, id_na_ferramenta) AS tarefa_id,
    projeto_id,
    ferramenta,
    id_na_ferramenta,
    fase,
    tarefa,
    responsavel,
    inicio_baseline,
    fim_baseline,
    inicio_real,
    fim_real,
    pct_como_veio,
    -- o teto é 100: ninguém entrega 120% de uma tarefa
    least(pct_como_veio, 100)                           AS pct_concluido,
    -- ...mas registramos quem veio errado, para o gerente saber
    pct_como_veio > 100                                 AS pct_veio_acima_de_100,
    horas,
    status_na_ferramenta
FROM tres_ferramentas;
