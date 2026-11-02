-- Os projetos em andamento, do pior para o melhor.
--
-- Esta query serve as DUAS telas: é a tabela de "Projetos em risco" e é
-- também a lista de projetos destino do simulador (lá o cliente filtra só
-- atenção e crítico). Uma query, dois usos -- menos ida ao warehouse.
--
-- A causa do atraso vem da gold.status_estruturado, que é o status semanal
-- lido pela IA (ai_classify + ai_extract). Ela tem ~163 linhas: só os status
-- COM bloqueio dos últimos 90 dias.
--
-- Sobre falta_sre: a nossa status_estruturado não tem esse rótulo. Ela tem
-- categoria_bloqueio em linguagem natural e a flag DETERMINÍSTICA
-- falta_de_gente (regex no texto, sem IA). As duas juntas são o sinal de
-- "falta de SRE" -- no PRJ-011 dão as 12 semanas e os 57 dias de impacto que
-- o dono precisa ver. Por isso dias_falta_gente, e não dias_falta_sre.
WITH bloqueios AS (
    SELECT
        projeto_id,
        categoria_bloqueio,
        coalesce(dias_impacto, 0) AS dias_impacto,
        -- A causa "falta de gente" é a categoria da IA OU a flag do regex.
        (falta_de_gente OR categoria_bloqueio = 'falta de gente ou papel nao alocado') AS e_falta_de_gente
    FROM lakehouse_vertice.gold.status_estruturado
    WHERE data_status >= date_sub(DATE'2026-10-16', 90)
),
-- Quantas semanas e quantos dias cada causa custou, por projeto.
causas AS (
    SELECT
        projeto_id,
        categoria_bloqueio,
        count(*)          AS semanas,
        sum(dias_impacto) AS dias
    FROM bloqueios
    GROUP BY projeto_id, categoria_bloqueio
),
-- A causa que mais apareceu. row_number num CTE separado: janela dentro de
-- agregação quebra, e aqui já está agregado.
causa_principal AS (
    SELECT projeto_id, categoria_bloqueio AS causa_mais_frequente, semanas AS semanas_da_causa
    FROM (
        SELECT
            *,
            row_number() OVER (PARTITION BY projeto_id ORDER BY semanas DESC, dias DESC) AS ordem
        FROM causas
    )
    WHERE ordem = 1
),
-- Os dias de impacto declarados, separados em falta de gente × o resto.
impacto AS (
    SELECT
        projeto_id,
        -- As SEMANAS andam junto dos DIAS. Sem elas a tela mostrava "7
        -- semana(s)" (da causa mais frequente) ao lado de "57 d de falta de
        -- gente" -- dois numeros que nao conversam. No PRJ-011 o par certo e
        -- 12 semanas / 57 dias, e e esse que o dono conhece.
        count_if(e_falta_de_gente)                                       AS semanas_falta_gente,
        count_if(NOT e_falta_de_gente)                                   AS semanas_outras_causas,
        sum(CASE WHEN e_falta_de_gente     THEN dias_impacto ELSE 0 END) AS dias_falta_gente,
        sum(CASE WHEN NOT e_falta_de_gente THEN dias_impacto ELSE 0 END) AS dias_outras_causas
    FROM bloqueios
    GROUP BY projeto_id
)
SELECT
    p.projeto_id,
    p.nome_projeto,
    p.cliente,
    p.segmento,
    p.gerente_projeto,
    p.situacao,
    p.spi,
    p.cpi,
    p.indice_min,
    p.estouro_previsto,
    p.atraso_projetado_dias,
    p.margem_projetada,
    p.farol_do_gerente,
    p.farol_calculado,
    p.melancia,
    c.causa_mais_frequente,
    coalesce(c.semanas_da_causa, 0)      AS semanas_da_causa,
    coalesce(i.semanas_falta_gente, 0)   AS semanas_falta_gente,
    coalesce(i.dias_falta_gente, 0)      AS dias_falta_gente,
    coalesce(i.semanas_outras_causas, 0) AS semanas_outras_causas,
    coalesce(i.dias_outras_causas, 0)    AS dias_outras_causas
FROM lakehouse_vertice.gold.projeto_situacao_atual p
LEFT JOIN causa_principal c ON c.projeto_id = p.projeto_id
LEFT JOIN impacto         i ON i.projeto_id = p.projeto_id
WHERE p.status = 'em_andamento'
-- indice_min = least(spi, cpi): o pior dos dois índices manda na ordem.
ORDER BY p.indice_min ASC NULLS LAST
