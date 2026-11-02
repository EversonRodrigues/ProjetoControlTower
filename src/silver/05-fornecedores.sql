-- =====================================================================
-- SILVER 05 · entregas_fornecedor
--
-- As entregas das consultorias contratadas: o que foi prometido e o que
-- chegou. É metade da resposta da quarta pergunta do dono ("o que vai
-- dar errado no próximo mês?"): entrega de consultoria atrasada hoje é
-- atraso de projeto no mês que vem.
--
-- Sujeira tratada aqui: 15 (a mesma consultoria com 4 grafias —
-- 'CodeForge Consultoria Ltda', 'Codeforge Consultoria',
-- 'CODEFORGE CONSULTORIA LTDA' e 'Code Forge Consultoria'). Sem
-- normalizar, a CodeForge aparece como quatro fornecedores diferentes e
-- ninguém percebe que todos os atrasos são do mesmo.
--
-- Atenção: data_entrega vazia NÃO é sujeira — é entrega em aberto.
-- O "hoje" do dataset é 16/10/2026: nunca current_date().
-- Conferência (seed 42): 5 entregas em atraso, todas da CodeForge;
-- prazo real ÷ prometido da CodeForge = 1,41.
-- =====================================================================

CREATE OR REFRESH MATERIALIZED VIEW entregas_fornecedor
(
  CONSTRAINT datas_do_pedido_preenchidas
    EXPECT (data_pedido IS NOT NULL AND data_prometida IS NOT NULL)
    ON VIOLATION FAIL UPDATE,

  -- Se sobrar alguma grafia de CodeForge fora do padrão, a conta de
  -- "quem atrasa" se parte em dois fornecedores.
  CONSTRAINT fornecedor_normalizado
    EXPECT (fornecedor NOT RLIKE '(?i)code ?forge' OR fornecedor = 'CodeForge Consultoria Ltda')
    ON VIOLATION FAIL UPDATE
)
COMMENT 'Entregas contratadas das consultorias: prometido x entregue, com o atraso em dias. Uma linha por entrega. Entrega sem data_entrega está em aberto (não é dado faltando). O nome do fornecedor está normalizado; fornecedor_como_veio guarda a grafia original.'
AS
WITH bruto AS (
  SELECT
      trim(entrega_id)                     AS entrega_id,
      trim(projeto_id)                     AS projeto_id,
      trim(fornecedor)                     AS fornecedor_como_veio,
      trim(item)                           AS item,
      nullif(trim(valor), '')              AS valor,
      nullif(trim(data_pedido), '')        AS data_pedido,
      nullif(trim(data_prometida), '')     AS data_prometida,
      nullif(trim(data_entrega), '')       AS data_entrega,
      nullif(trim(prazo_contratado_dias), '') AS prazo_contratado_dias,
      lower(trim(status))                  AS status
  FROM lakehouse_vertice.bronze.entregas_fornecedor
),
convertido AS (
  SELECT
      entrega_id,
      projeto_id,

      -- tira o espaço e a caixa antes de comparar: assim 'Code Forge',
      -- 'Codeforge' e 'CODEFORGE' caem todas no mesmo LIKE
      CASE
        WHEN replace(lower(fornecedor_como_veio), ' ', '') LIKE '%codeforge%'
          THEN 'CodeForge Consultoria Ltda'
        ELSE fornecedor_como_veio
      END                                               AS fornecedor,
      fornecedor_como_veio,

      item,
      CAST(replace(valor, ',', '.') AS DECIMAL(18,2))    AS valor,

      coalesce(try_to_date(data_pedido,    'yyyy-MM-dd'), try_to_date(data_pedido,    'dd/MM/yyyy')) AS data_pedido,
      coalesce(try_to_date(data_prometida, 'yyyy-MM-dd'), try_to_date(data_prometida, 'dd/MM/yyyy')) AS data_prometida,
      -- vazio aqui quer dizer "ainda não chegou"
      coalesce(try_to_date(data_entrega,   'yyyy-MM-dd'), try_to_date(data_entrega,   'dd/MM/yyyy')) AS data_entrega,

      CAST(prazo_contratado_dias AS INT)                AS prazo_contratado_dias,
      status
  FROM bruto
)
SELECT
    entrega_id,
    projeto_id,
    fornecedor,
    fornecedor_como_veio,
    item,
    valor,
    data_pedido,
    data_prometida,
    data_entrega,
    prazo_contratado_dias,
    status,

    -- quantos dias o fornecedor prometeu...
    datediff(data_prometida, data_pedido)               AS prazo_prometido_dias,
    -- ...e quantos ele levou de fato (NULL enquanto não entrega)
    datediff(data_entrega, data_pedido)                 AS prazo_real_dias,
    -- positivo = chegou depois do prometido
    datediff(data_entrega, data_prometida)              AS dias_de_atraso_na_entrega,

    data_entrega IS NULL                                AS em_aberto,
    -- atrasada = ainda não chegou e o prazo já passou. O "hoje" do
    -- dataset é fixo em 16/10/2026 para o número bater com o de todos.
    data_entrega IS NULL AND data_prometida < DATE'2026-10-16' AS em_atraso
FROM convertido;
