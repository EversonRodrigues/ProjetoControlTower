-- Confere a mv_projetos contra as réguas do seed 42 (16/10/2026).
-- Esperado: 41 projetos · 208,63 mi · 0,92 · 0,97 · 6,47 mi · 7 · 10 · 17 · 4
SELECT
    MEASURE(projetos)                  AS projetos,
    round(MEASURE(carteira)/1e6, 2)    AS carteira_mi,
    round(MEASURE(spi), 4)             AS spi,
    round(MEASURE(cpi), 4)             AS cpi,
    round(MEASURE(estouro_previsto)/1e6, 2) AS estouro_mi,
    MEASURE(projetos_criticos)         AS criticos,
    MEASURE(projetos_em_atencao)       AS em_atencao,
    MEASURE(projetos_em_risco)         AS em_risco,
    MEASURE(melancias)                 AS melancias,
    round(MEASURE(margem_projetada), 4) AS margem
FROM lakehouse_vertice.gold.mv_projetos
WHERE status = 'em_andamento'
GROUP BY ALL;
