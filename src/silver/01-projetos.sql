-- =====================================================================
-- SILVER 01 · projetos
--
-- O cadastro do PMO. É também o DE-PARA da integração: é esta tabela
-- que diz qual ferramenta cada projeto usa e qual é o código do projeto
-- dentro dessa ferramenta. Sem ela, as tarefas das três ferramentas não
-- sabem a que projeto pertencem.
--
-- Sujeiras tratadas aqui:
--   1) data_inicio vem em dois formatos (24 das 60 linhas em dd/MM/yyyy)
--   2) a ferramenta está escrita de 8 jeitos diferentes
--   3) codigo_ferramenta vazio em 2 linhas -> NULL (vazio não é código)
-- =====================================================================

CREATE OR REFRESH MATERIALIZED VIEW projetos
(
  -- Projeto sem data de início não entra em nenhum cálculo de prazo.
  CONSTRAINT data_inicio_preenchida
    EXPECT (data_inicio IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- A ferramenta tem que cair num dos três valores canônicos, senão a
  -- integração de tarefas não sabe de onde ler o avanço do projeto.
  CONSTRAINT ferramenta_conhecida
    EXPECT (ferramenta IN ('excel', 'clickup', 'msproject'))
    ON VIOLATION FAIL UPDATE
)
COMMENT 'Cadastro limpo dos projetos do PMO da Vértice. Uma linha por projeto. É o de-para entre o projeto e o seu código dentro de cada ferramenta (Excel, ClickUp, MS Project).'
AS
WITH bruto AS (
  SELECT
      trim(projeto_id)        AS projeto_id,
      trim(nome_projeto)      AS nome_projeto,
      trim(cliente)           AS cliente,
      trim(segmento)          AS segmento,
      trim(tipo_projeto)      AS tipo_projeto,
      trim(ferramenta)        AS ferramenta_como_veio,
      trim(codigo_ferramenta) AS codigo_ferramenta,
      valor_contrato,
      orcamento_custo,
      data_inicio,
      data_fim_baseline,
      trim(status)            AS status,
      trim(gerente_projeto)   AS gerente_projeto
  FROM lakehouse_vertice.bronze.projetos
)
SELECT
    projeto_id,
    nome_projeto,
    cliente,
    segmento,
    tipo_projeto,

    -- 'Excel', 'EXCEL', 'planilha', 'Click Up', 'clickup', 'MS Project',
    -- 'msproject', 'Project'... oito grafias, três valores.
    -- Tiramos o espaço antes de comparar para 'Click Up' casar com 'clickup'.
    CASE
      WHEN lower(ferramenta_como_veio) LIKE '%excel%'                        THEN 'excel'
      WHEN lower(ferramenta_como_veio) LIKE '%planilha%'                     THEN 'excel'
      WHEN replace(lower(ferramenta_como_veio), ' ', '') LIKE '%clickup%'    THEN 'clickup'
      WHEN replace(lower(ferramenta_como_veio), ' ', '') LIKE '%msproject%'  THEN 'msproject'
      WHEN replace(lower(ferramenta_como_veio), ' ', '') LIKE '%project%'    THEN 'msproject'
      ELSE NULL
    END                                                        AS ferramenta,

    -- guardamos o texto original: é a prova de que a limpeza aconteceu
    ferramenta_como_veio,

    -- '' não é código, é ausência de código
    nullif(codigo_ferramenta, '')                              AS codigo_ferramenta,

    -- dinheiro: vírgula decimal viraria erro no CAST, então troca antes
    CAST(replace(nullif(valor_contrato,  ''), ',', '.') AS DECIMAL(18,2)) AS valor_contrato,
    CAST(replace(nullif(orcamento_custo, ''), ',', '.') AS DECIMAL(18,2)) AS orcamento_custo,

    -- try_to_date devolve NULL quando o formato não casa, então o
    -- coalesce escolhe o formato certo linha por linha.
    coalesce(
      try_to_date(data_inicio, 'yyyy-MM-dd'),
      try_to_date(data_inicio, 'dd/MM/yyyy')
    )                                                          AS data_inicio,
    coalesce(
      try_to_date(data_fim_baseline, 'yyyy-MM-dd'),
      try_to_date(data_fim_baseline, 'dd/MM/yyyy')
    )                                                          AS data_fim_baseline,

    lower(status)                                              AS status,
    gerente_projeto
FROM bruto;
