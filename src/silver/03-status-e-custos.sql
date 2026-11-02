-- =====================================================================
-- SILVER 03 · status_semanal e custos
--
-- Duas tabelas que vêm do mundo real e por isso vêm tortas:
--   · status_semanal é o que o gerente escreve toda sexta. O farol vem
--     'Verde', 'VERDE', 'verde'; e 51 textos estão vazios ou dizem
--     'ver ata da reunião'. Esse texto é o que a IA da noite 3 vai ler,
--     então NADA é descartado: o vazio ganha uma flag.
--   · custos é o dinheiro. 671 lançamentos vêm com vírgula decimal
--     ('12345,67'). Se usássemos try_cast, esses 671 virariam NULL em
--     silêncio e R$ 5,4 mi desapareceriam do relatório. O replace vem
--     ANTES do CAST, e o CAST é duro de propósito: se um valor novo vier
--     torto, o pipeline falha e alguém olha.
--
-- Sujeiras tratadas aqui: 13 (vírgula decimal), 14 (estorno negativo),
-- 17 (farol em caixas diferentes) e 18 (status vazio).
-- Conferência (seed 42): custo real total = R$ 193,35 mi.
-- =====================================================================


-- ---------------------------------------------------------------------
-- status_semanal · 3.911 linhas, uma por projeto e por sexta
-- ---------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW status_semanal
(
  -- O farol do gerente é metade da história do projeto (a outra metade
  -- é o SPI calculado). Se ele vier fora dos três valores, a conta de
  -- "melancia" (verde por fora, atrasado por dentro) não fecha.
  CONSTRAINT farol_conhecido
    EXPECT (farol IN ('verde', 'amarelo', 'vermelho'))
    ON VIOLATION FAIL UPDATE,

  CONSTRAINT data_status_preenchida
    EXPECT (data_status IS NOT NULL)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'O status que cada gerente reporta toda sexta: farol, % concluído e o texto livre com os bloqueios. Uma linha por projeto e por semana. É daqui que sai o histórico de avanço do portfólio (as ferramentas só guardam o % de hoje).'
AS
WITH bruto AS (
  SELECT
      trim(projeto_id)                 AS projeto_id,
      nullif(trim(data_status), '')    AS data_status,
      nullif(trim(gerente), '')        AS gerente,
      lower(trim(farol))               AS farol,
      nullif(trim(pct_concluido), '')  AS pct_concluido,
      trim(texto_status)               AS texto_status
  FROM lakehouse_vertice.bronze.status_semanal
)
SELECT
    projeto_id,

    -- o mesmo coalesce de dois formatos usado em projetos
    coalesce(
      try_to_date(data_status, 'yyyy-MM-dd'),
      try_to_date(data_status, 'dd/MM/yyyy')
    )                                                   AS data_status,

    gerente,
    farol,

    -- o % vem como texto; passa por DOUBLE antes do INT para aguentar
    -- um '45.0' sem quebrar
    CAST(CAST(replace(pct_concluido, ',', '.') AS DOUBLE) AS INT) AS pct_concluido,

    texto_status,

    -- Status sem conteúdo não é lixo: é o sinal de que naquela semana
    -- ninguém reportou nada. A IA pula essas; o relatório as conta.
    lower(texto_status) IN ('', 'n/a', 'ver ata da reunião')      AS status_vazio
FROM bruto;


-- ---------------------------------------------------------------------
-- custos · 23.640 lançamentos de custo real
-- ---------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW custos
(
  -- Um valor que não virou número é dinheiro perdido no caminho.
  CONSTRAINT valor_convertido
    EXPECT (valor IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  CONSTRAINT data_preenchida
    EXPECT (data IS NOT NULL)
    ON VIOLATION FAIL UPDATE
)
COMMENT 'Lançamentos de custo real dos projetos (pessoal, consultoria, cloud, licenças e despesas). Uma linha por lançamento. Os estornos ficam como valor negativo e sinalizados em estorno: o custo da Vértice é líquido. A coluna semana aponta para a sexta da semana do lançamento.'
AS
WITH bruto AS (
  SELECT
      trim(lancamento_id)        AS lancamento_id,
      trim(projeto_id)           AS projeto_id,
      nullif(trim(data), '')     AS data_texto,
      lower(trim(categoria))     AS categoria,
      trim(descricao)            AS descricao,
      nullif(trim(valor), '')    AS valor_texto,
      trim(centro_custo)         AS centro_custo
  FROM lakehouse_vertice.bronze.custos
),
convertido AS (
  SELECT
      lancamento_id,
      projeto_id,
      coalesce(
        try_to_date(data_texto, 'yyyy-MM-dd'),
        try_to_date(data_texto, 'dd/MM/yyyy')
      )                                                 AS data,
      categoria,
      descricao,
      -- O replace vem ANTES do CAST. E é CAST, não try_cast: 671
      -- vírgulas decimais viram ponto e entram na conta; qualquer outra
      -- sujeira nova derruba o pipeline em vez de sumir com o dinheiro.
      CAST(replace(valor_texto, ',', '.') AS DECIMAL(18,2)) AS valor,
      centro_custo
  FROM bruto
)
SELECT
    lancamento_id,
    projeto_id,
    data,
    -- date_trunc('WEEK') cai na segunda; + 4 dias é a sexta, o dia em
    -- que a Vértice fecha a semana (igual ao status_semanal).
    date_add(CAST(date_trunc('WEEK', data) AS DATE), 4) AS semana,
    categoria,
    descricao,
    valor,
    -- estorno não é erro de digitação: é devolução de custo
    valor < 0                                           AS estorno,
    centro_custo
FROM convertido;
