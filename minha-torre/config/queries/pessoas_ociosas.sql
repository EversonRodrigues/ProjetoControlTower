-- Quem está parado: utilização abaixo de 20% nas últimas 12 semanas.
--
-- A janela são as 12 sextas até 16/10/2026: a de hoje mais as 11 anteriores,
-- ou seja 7 x 11 = 77 dias para trás. (Com 84 dias entrariam 13 sextas e a
-- média já não bateria com a pct_utilizacao_12s da gold, que é
-- ROWS BETWEEN 11 PRECEDING AND CURRENT ROW.)
-- A gold já traz essa coluna pronta, mas ela é NULL quando a pessoa não tem
-- exatamente 12 semanas na janela -- então a média é recalculada aqui, para
-- não perder quem entrou no meio do período.
--
-- ATENÇÃO: pct_utilizacao é FRAÇÃO (0..1), não percentual. O corte é 0.20.
--
-- As horas paradas e o custo ocioso são MÉDIAS POR SEMANA: é o que o
-- simulador multiplica por 4 para chegar ao mês.
WITH janela AS (
    SELECT
        colaborador_id,
        nome,
        papel,
        senioridade,
        -- O projeto da semana mais recente. Agrupar POR projeto_principal
        -- duplicaria a pessoa, uma linha por projeto que ela passou.
        max_by(projeto_principal, semana)            AS projeto_principal,
        avg(horas_disponiveis - horas_apontadas)     AS horas_paradas_semana,
        avg(pct_utilizacao)                          AS pct_utilizacao_12s,
        count(*)                                     AS semanas_na_janela
    FROM lakehouse_vertice.gold.utilizacao_pessoa_semana
    WHERE semana >= date_sub(DATE'2026-10-16', 7 * 11)
      AND semana <= DATE'2026-10-16'
      AND ativo
    GROUP BY colaborador_id, nome, papel, senioridade
)
SELECT
    j.colaborador_id,
    j.nome,
    j.papel,
    j.senioridade,
    j.projeto_principal,
    j.semanas_na_janela,
    j.pct_utilizacao_12s,
    j.horas_paradas_semana,
    -- custo_hora é DECIMAL(18,2) na silver: o CAST evita que o warehouse
    -- devolva a conta como string e o Number() do cliente tenha surpresa.
    CAST(c.custo_hora AS DOUBLE)                              AS custo_hora,
    j.horas_paradas_semana * CAST(c.custo_hora AS DOUBLE)     AS custo_ocioso_semana
FROM janela j
JOIN lakehouse_vertice.silver.colaboradores c USING (colaborador_id)
WHERE j.pct_utilizacao_12s < 0.20
ORDER BY custo_ocioso_semana DESC
