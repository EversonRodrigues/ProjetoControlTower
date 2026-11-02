-- Os quatro números do topo da tela "Projetos em risco".
--
-- Uma linha só: a fotografia da carteira em 16/10/2026. O "hoje" do dataset
-- é fixo de propósito -- com current_date() o número mudaria todo dia e não
-- bateria com o de ninguém. A gold.projeto_situacao_atual JÁ é essa
-- fotografia, por isso aqui não há filtro de data nenhum.
--
-- O KPI "alto risco em 30 dias" NÃO está aqui: ele vem do modelo
-- (gold.score_estouro_30d), que pode não existir no workspace do aluno. Uma
-- query de config/queries/ apontando para tabela inexistente quebraria o
-- build no typegen, então o score é lido pela rota GET /api/score-estouro.
SELECT
    count_if(status = 'em_andamento')                                      AS em_andamento,
    count_if(status = 'em_andamento' AND situacao IN ('atencao', 'critico')) AS em_risco,
    count_if(status = 'em_andamento' AND situacao = 'critico')              AS criticos,
    count_if(status = 'em_andamento' AND melancia)                         AS melancias,
    -- Estouro só de quem está em andamento: o que já terminou não estoura mais.
    sum(CASE WHEN status = 'em_andamento' THEN estouro_previsto END)       AS estouro_previsto,
    -- Carteira é a empresa inteira, os 60 projetos.
    sum(valor_contrato)                                                    AS carteira
FROM lakehouse_vertice.gold.projeto_situacao_atual
