#!/usr/bin/env python3
"""Gera resources/dashboard-portfolio.lvdash.json (AI/BI, GRID_V1).

  python scripts/gerar_dashboard.py                            # gera o JSON
  python scripts/gerar_dashboard.py --conferir --profile X      # roda cada query

O formato do .lvdash.json nao foi adivinhado: foi lido de dashboards que
ja funcionam neste workspace (`databricks lakeview get`). Dai vem as
regras que quebram o parser se violadas:
  · queryLines e um array de strings concatenado verbatim, entao TODA
    linha termina em \\n
  · query.fields[].name tem que ser IDENTICO ao encodings.*.fieldName
  · a versao do spec depende do tipo: counter e table 2, bar/line/
    scatter 3
  · toda pagina precisa de pageType e layoutVersion

As tabelas da gold vao com o NOME PURO: o dataset_catalog/dataset_schema
do resources/dashboard.dashboard.yml resolve o caminho. O que vem da
silver vai com o nome completo, porque o schema padrao ali e a gold.
"""
import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "resources" / "dashboard-portfolio.lvdash.json"
HOJE = "DATE'2026-10-16'"

# As cores da Jornada de Dados...
AZUL, CIANO = "#0059DB", "#22C2F4"
FUNDO_ESCURO = "#14141A"
# ...e a semantica do farol, que nao pode depender da ordem da paleta.
CRITICO, ATENCAO, OK = "#FF5F46", "#F6C344", "#22C2F4"

CORES_DA_SITUACAO = [
    {"value": "critico", "color": CRITICO},
    {"value": "atencao", "color": ATENCAO},
    {"value": "ok", "color": OK},
]

# As tabelas da gold que aparecem com nome puro. O --conferir prefixa
# estas para rodar fora do dashboard.
GOLD = (
    "mv_projetos",
    "projeto_situacao_atual",
    "fato_projeto_semana",
    "utilizacao_pessoa_semana",
    "status_estruturado",
    "score_estouro_30d",
)


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #
def sql(*linhas: str) -> list[str]:
    """Garante o \\n no fim de cada linha: sem ele uma linha engole a seguinte."""
    return [linha + "\n" for linha in linhas]


def campo(nome: str, expressao: str) -> dict:
    return {"name": nome, "expression": expressao}


def coluna(nome: str) -> dict:
    """Campo de coluna crua (widget desagregado)."""
    return campo(nome, f"`{nome}`")


def soma(nome: str) -> dict:
    """Campo agregado: o name casa com o fieldName do encoding."""
    return campo(f"sum({nome})", f"SUM(`{nome}`)")


def consulta(dataset: str, campos: list[dict], desagregado: bool) -> list[dict]:
    return [
        {
            "name": "main_query",
            "query": {
                "datasetName": dataset,
                "fields": campos,
                "disaggregated": desagregado,
            },
        }
    ]


def pos(x: int, y: int, largura: int, altura: int) -> dict:
    return {"x": x, "y": y, "width": largura, "height": altura}


def texto(nome: str, markdown: str, posicao: dict) -> dict:
    """Widget de texto: usa multilineTextboxSpec e NAO tem 'spec'."""
    return {
        "widget": {"name": nome, "multilineTextboxSpec": {"lines": [markdown]}},
        "position": posicao,
    }


def contador(nome, dataset, col, titulo, formato, posicao) -> dict:
    return {
        "widget": {
            "name": nome,
            "queries": consulta(dataset, [coluna(col)], True),
            "spec": {
                "version": 2,
                "widgetType": "counter",
                "encodings": {"value": {"fieldName": col, "displayName": titulo, "format": formato}},
                "frame": {"showTitle": True, "title": titulo},
            },
        },
        "position": posicao,
    }


def barra(nome, dataset, categoria, medida, titulo, posicao, cor=None,
          mapeamento=None, rotulo_medida=None, formato=None, horizontal=True) -> dict:
    campos = [coluna(categoria), soma(medida)]
    if cor:
        campos.insert(1, coluna(cor))
    eixo_cat = {"fieldName": categoria, "scale": {"type": "categorical"}}
    eixo_num = {
        "fieldName": f"sum({medida})",
        "scale": {"type": "quantitative"},
        "displayName": rotulo_medida or medida,
    }
    if formato:
        eixo_num["format"] = formato
    encodings = {"x": eixo_num, "y": eixo_cat} if horizontal else {"x": eixo_cat, "y": eixo_num}
    if cor:
        enc_cor = {"fieldName": cor, "displayName": cor, "scale": {"type": "categorical"}}
        if mapeamento:
            enc_cor["scale"]["mappings"] = mapeamento
        encodings["color"] = enc_cor
    return {
        "widget": {
            "name": nome,
            "queries": consulta(dataset, campos, False),
            "spec": {
                "version": 3,
                "widgetType": "bar",
                "encodings": encodings,
                "frame": {"showTitle": True, "title": titulo},
            },
        },
        "position": posicao,
    }


def dispersao(nome, dataset, eixo_x, eixo_y, cor, tamanho, titulo, posicao) -> dict:
    return {
        "widget": {
            "name": nome,
            "queries": consulta(
                dataset,
                [coluna(eixo_x), coluna(eixo_y), coluna(cor), coluna(tamanho), coluna("projeto_id")],
                True,
            ),
            "spec": {
                "version": 3,
                "widgetType": "scatter",
                "encodings": {
                    "x": {"fieldName": eixo_x, "scale": {"type": "quantitative"}, "displayName": "SPI"},
                    "y": {"fieldName": eixo_y, "scale": {"type": "quantitative"}, "displayName": "CPI"},
                    "color": {
                        "fieldName": cor,
                        "displayName": "Situação",
                        "scale": {"type": "categorical", "mappings": CORES_DA_SITUACAO},
                    },
                    "size": {"fieldName": tamanho, "scale": {"type": "quantitative"}, "displayName": "Contrato"},
                },
                "frame": {"showTitle": True, "title": titulo},
            },
        },
        "position": posicao,
    }


def linha_do_tempo(nome, dataset, eixo_x, series, titulo, posicao) -> dict:
    campos = [coluna(eixo_x)] + [coluna(c) for c, _ in series]
    return {
        "widget": {
            "name": nome,
            "queries": consulta(dataset, campos, True),
            "spec": {
                "version": 3,
                "widgetType": "line",
                "encodings": {
                    "x": {"fieldName": eixo_x, "scale": {"type": "temporal"}, "displayName": "Semana"},
                    "y": {
                        "scale": {"type": "quantitative"},
                        "fields": [{"fieldName": c, "displayName": r} for c, r in series],
                    },
                },
                "frame": {"showTitle": True, "title": titulo},
            },
        },
        "position": posicao,
    }


def tabela(nome, dataset, colunas, titulo, posicao) -> dict:
    return {
        "widget": {
            "name": nome,
            "queries": consulta(dataset, [coluna(c) for c, _ in colunas], True),
            "spec": {
                "version": 2,
                "widgetType": "table",
                "encodings": {
                    "columns": [
                        {"fieldName": c, "displayName": r, "booleanValues": ["false", "true"]}
                        for c, r in colunas
                    ]
                },
                "frame": {"showTitle": True, "title": titulo},
            },
        },
        "position": posicao,
    }


def pagina(nome: str, titulo: str, widgets: list[dict]) -> dict:
    return {
        "name": nome,
        "displayName": titulo,
        "pageType": "PAGE_TYPE_CANVAS",
        "layoutVersion": "GRID_V1",
        "layout": widgets,
    }


MOEDA = {"type": "number-currency", "currencyCode": "BRL", "abbreviation": "compact",
         "decimalPlaces": {"type": "max", "places": 2}}
INDICE = {"type": "number-plain", "decimalPlaces": {"type": "exact", "places": 2}}
INTEIRO = {"type": "number-plain", "decimalPlaces": {"type": "exact", "places": 0}}


# --------------------------------------------------------------------- #
# os datasets
# --------------------------------------------------------------------- #
DATASETS: dict[str, tuple[str, list[str]]] = {
    # ---------------- Portfólio ----------------
    "ds_kpi_portfolio": (
        "KPIs do portfólio (mv_projetos)",
        sql(
            "SELECT",
            "    MEASURE(carteira)            AS carteira,",
            "    MEASURE(spi)                 AS spi,",
            "    MEASURE(cpi)                 AS cpi,",
            "    MEASURE(estouro_previsto)    AS estouro_previsto,",
            "    MEASURE(projetos_em_risco)   AS projetos_em_risco,",
            "    MEASURE(projetos_criticos)   AS projetos_criticos,",
            "    MEASURE(melancias)           AS melancias",
            "FROM mv_projetos",
            "WHERE status = 'em_andamento'",
            "GROUP BY ALL",
        ),
    ),
    "ds_estouro_por_projeto": (
        "Estouro previsto por projeto",
        sql(
            "SELECT",
            "    projeto_id,",
            "    nome_projeto,",
            "    cliente,",
            "    situacao,",
            "    estouro_previsto",
            "FROM projeto_situacao_atual",
            "WHERE status = 'em_andamento'",
            "  AND estouro_previsto > 0",
            "ORDER BY estouro_previsto DESC",
            "LIMIT 20",
        ),
    ),
    "ds_spi_cpi": (
        "SPI x CPI dos projetos em andamento",
        sql(
            "SELECT",
            "    projeto_id,",
            "    nome_projeto,",
            "    cliente,",
            "    situacao,",
            "    spi,",
            "    cpi,",
            "    valor_contrato",
            "FROM projeto_situacao_atual",
            "WHERE status = 'em_andamento'",
            "  AND spi IS NOT NULL",
            "  AND cpi IS NOT NULL",
        ),
    ),
    "ds_carteira_semanal": (
        "SPI e CPI semanais da carteira (status do gerente)",
        sql(
            "-- EV, PV e AC sao ACUMULADOS por projeto em cada sexta: somar os",
            "-- projetos dentro da mesma semana esta certo, somar semanas nao.",
            "-- Esta query nunca soma semanas (GROUP BY semana).",
            "SELECT",
            "    semana,",
            "    sum(ev_dinheiro) / nullif(sum(pv_dinheiro), 0) AS spi_carteira,",
            "    sum(ev_dinheiro) / nullif(sum(ac_dinheiro), 0) AS cpi_carteira,",
            "    count(*)                                       AS projetos_na_semana",
            "FROM fato_projeto_semana",
            f"WHERE semana <= {HOJE}",
            "GROUP BY semana",
            "ORDER BY semana",
        ),
    ),
    "ds_em_andamento": (
        "Projetos em andamento: o farol do gerente ao lado do farol pela conta",
        sql(
            "SELECT",
            "    p.projeto_id,",
            "    p.nome_projeto,",
            "    p.cliente,",
            "    p.gerente_projeto,",
            "    p.farol_do_gerente,",
            "    p.farol_calculado,",
            "    p.melancia,",
            "    round(p.spi, 2)                  AS spi,",
            "    round(p.cpi, 2)                  AS cpi,",
            "    p.situacao,",
            "    p.pct_concluido,",
            "    p.estouro_previsto,",
            "    round(p.atraso_projetado_dias)   AS atraso_projetado_dias,",
            "    s.ranking,",
            "    s.faixa_risco",
            "FROM projeto_situacao_atual p",
            "LEFT JOIN score_estouro_30d s",
            "       ON s.projeto_id = p.projeto_id",
            f"      AND s.data_referencia = {HOJE}",
            "WHERE p.status = 'em_andamento'",
            "ORDER BY least(p.spi, p.cpi)",
        ),
    ),
    # ---------------- Pessoas ----------------
    # A silver entra com NOME COMPLETO aqui pela mesma regra da
    # entregas_fornecedor: o custo_hora nao existe na gold (so o
    # custo_horas_apontadas, que e o custo do que foi TRABALHADO -- o
    # oposto do que esta pergunta quer).
    "ds_hora_parada": (
        "Top 15 por custo da hora parada (12 semanas)",
        sql(
            "SELECT",
            "    u.nome,",
            "    u.papel,",
            "    u.senioridade,",
            "    max_by(u.projeto_principal, u.horas_apontadas)               AS projeto_principal,",
            "    sum(u.horas_disponiveis)                                     AS horas_disponiveis,",
            "    sum(u.horas_apontadas)                                       AS horas_apontadas,",
            "    sum(u.horas_disponiveis - u.horas_apontadas)                 AS horas_paradas,",
            "    round(100 * sum(u.horas_apontadas)",
            "          / nullif(sum(u.horas_disponiveis), 0), 1)              AS pct_uso_12s,",
            "    CAST(c.custo_hora AS DOUBLE)",
            "      * sum(u.horas_disponiveis - u.horas_apontadas)             AS custo_hora_parada",
            "FROM utilizacao_pessoa_semana u",
            "JOIN lakehouse_vertice.silver.colaboradores c USING (colaborador_id)",
            f"WHERE u.semana BETWEEN date_sub({HOJE}, 77) AND {HOJE}",
            "GROUP BY u.colaborador_id, u.nome, u.papel, u.senioridade, c.custo_hora",
            "ORDER BY custo_hora_parada DESC",
            "LIMIT 15",
        ),
    ),
    "ds_utilizacao_pessoa_projeto": (
        "Utilização por pessoa e projeto (12 semanas)",
        sql(
            "-- O grao pessoa x projeto NAO existe na gold (utilizacao_pessoa_semana",
            "-- e pessoa x semana, com apenas o projeto_principal), por isso as",
            "-- horas vem da silver.apontamentos.",
            "WITH capacidade_da_pessoa AS (",
            "  SELECT",
            "      colaborador_id,",
            "      sum(horas_disponiveis) AS horas_disponiveis_12s",
            "  FROM utilizacao_pessoa_semana",
            f"  WHERE semana BETWEEN date_sub({HOJE}, 77) AND {HOJE}",
            "  GROUP BY colaborador_id",
            "),",
            "horas_no_projeto AS (",
            "  SELECT",
            "      colaborador_id,",
            "      projeto_id,",
            "      sum(horas_apontadas) AS horas_apontadas_12s",
            "  FROM lakehouse_vertice.silver.apontamentos",
            f"  WHERE semana BETWEEN date_sub({HOJE}, 77) AND {HOJE}",
            "  GROUP BY colaborador_id, projeto_id",
            ")",
            "SELECT",
            "    c.nome,",
            "    c.papel,",
            "    c.senioridade,",
            "    h.projeto_id,",
            "    h.horas_apontadas_12s,",
            "    p.horas_disponiveis_12s,",
            "    round(100 * h.horas_apontadas_12s",
            "          / nullif(p.horas_disponiveis_12s, 0), 1) AS pct_da_capacidade",
            "FROM horas_no_projeto h",
            "JOIN capacidade_da_pessoa p USING (colaborador_id)",
            "JOIN lakehouse_vertice.silver.colaboradores c USING (colaborador_id)",
            "WHERE h.horas_apontadas_12s > 0",
            "ORDER BY pct_da_capacidade",
        ),
    ),
    "ds_bloqueios": (
        "Causas de bloqueio por projeto (últimos 90 dias)",
        sql(
            "WITH por_projeto_e_causa AS (",
            "  SELECT",
            "      projeto_id,",
            "      categoria_bloqueio,",
            "      count(*)                 AS status_com_bloqueio,",
            "      sum(dias_impacto)        AS dias_declarados,",
            "      count_if(falta_de_gente) AS citam_falta_de_gente",
            "  FROM status_estruturado",
            f"  WHERE data_status >= date_sub({HOJE}, 90)",
            "  GROUP BY projeto_id, categoria_bloqueio",
            "),",
            "mais_bloqueados AS (",
            "  SELECT projeto_id",
            "  FROM por_projeto_e_causa",
            "  GROUP BY projeto_id",
            "  ORDER BY sum(status_com_bloqueio) DESC",
            "  LIMIT 12",
            ")",
            "SELECT b.*",
            "FROM por_projeto_e_causa b",
            "JOIN mais_bloqueados m USING (projeto_id)",
            "ORDER BY b.projeto_id, b.categoria_bloqueio",
        ),
    ),
    # ---------------- Fornecedores (as duas sobre a silver) ----------------
    "ds_fornecedores": (
        "Confiança por fornecedor",
        sql(
            "SELECT",
            "    fornecedor,",
            "    count(DISTINCT fornecedor_como_veio)                   AS grafias_no_cadastro,",
            "    count(*)                                               AS entregas,",
            "    count_if(em_aberto)                                    AS em_aberto,",
            "    round(avg(prazo_real_dias",
            "              / nullif(prazo_prometido_dias, 0)), 2)       AS prazo_real_sobre_prometido,",
            "    round(100.0 * count_if(NOT em_aberto AND dias_de_atraso_na_entrega <= 0)",
            "          / nullif(count_if(NOT em_aberto), 0), 0)         AS pct_no_prazo,",
            "    count_if(em_atraso)                                    AS em_atraso_hoje",
            "FROM lakehouse_vertice.silver.entregas_fornecedor",
            "GROUP BY fornecedor",
            "ORDER BY prazo_real_sobre_prometido DESC NULLS LAST",
        ),
    ),
    "ds_entregas_em_atraso": (
        "Entregas em atraso hoje",
        sql(
            "SELECT",
            "    entrega_id,",
            "    projeto_id,",
            "    fornecedor,",
            "    fornecedor_como_veio,",
            "    item,",
            "    valor,",
            "    data_prometida,",
            "    prazo_prometido_dias,",
            f"    datediff({HOJE}, data_prometida) AS dias_de_atraso_hoje",
            "FROM lakehouse_vertice.silver.entregas_fornecedor",
            "WHERE em_atraso",
            "ORDER BY dias_de_atraso_hoje DESC",
        ),
    ),
}


# --------------------------------------------------------------------- #
# as páginas
# --------------------------------------------------------------------- #
def pagina_portfolio() -> dict:
    kpis = [
        ("kpi_carteira", "carteira", "Carteira", MOEDA, pos(0, 2, 3, 3)),
        ("kpi_estouro", "estouro_previsto", "Estouro previsto", MOEDA, pos(3, 2, 3, 3)),
        ("kpi_spi", "spi", "SPI de hoje (pelas tarefas)", INDICE, pos(6, 2, 3, 3)),
        ("kpi_cpi", "cpi", "CPI de hoje", INDICE, pos(9, 2, 3, 3)),
        ("kpi_em_risco", "projetos_em_risco", "Projetos em risco", INTEIRO, pos(0, 5, 4, 3)),
        ("kpi_criticos", "projetos_criticos", "Críticos", INTEIRO, pos(4, 5, 4, 3)),
        ("kpi_melancias", "melancias", "Melancias", INTEIRO, pos(8, 5, 4, 3)),
    ]
    return pagina(
        "portfolio",
        "Portfólio",
        [
            texto("t_portfolio", "# Projeto Farol · Portfólio", pos(0, 0, 12, 1)),
            texto(
                "t_portfolio_sub",
                "Fotografia de **16/10/2026**. Os KPIs vêm da métrica governada "
                "`gold.mv_projetos` — a mesma conta que o Genie usa.",
                pos(0, 1, 12, 1),
            ),
            *[contador(n, "ds_kpi_portfolio", c, t, f, p) for n, c, t, f, p in kpis],
            barra(
                "bar_estouro",
                "ds_estouro_por_projeto",
                "projeto_id",
                "estouro_previsto",
                "Estouro previsto por projeto",
                pos(0, 8, 6, 6),
                cor="situacao",
                mapeamento=CORES_DA_SITUACAO,
                rotulo_medida="Estouro previsto (R$)",
                formato=MOEDA,
            ),
            dispersao(
                "scatter_spi_cpi",
                "ds_spi_cpi",
                "spi",
                "cpi",
                "situacao",
                "valor_contrato",
                "SPI × CPI — o quadrante de baixo à esquerda é atraso com estouro",
                pos(6, 8, 6, 6),
            ),
            linha_do_tempo(
                "line_carteira",
                "ds_carteira_semanal",
                "semana",
                [("spi_carteira", "SPI"), ("cpi_carteira", "CPI")],
                "SPI e CPI semanais da carteira, pelo status do gerente (1,00 = no prazo)",
                pos(0, 14, 12, 6),
            ),
            texto(
                "t_duas_fontes",
                "**Por que a linha termina em 0,87 e o KPI diz 0,92?** São duas fontes: a linha é o "
                "**status semanal** que o gerente escreve, o KPI é o **cronograma de tarefas** das três "
                "ferramentas. Quando as duas discordam, alguém precisa abrir o projeto — é o que a coluna "
                "`melancia` e o score de estouro apontam.",
                pos(0, 20, 12, 2),
            ),
            tabela(
                "tab_em_andamento",
                "ds_em_andamento",
                [
                    ("projeto_id", "Projeto"),
                    ("cliente", "Cliente"),
                    ("gerente_projeto", "Gerente"),
                    ("farol_do_gerente", "Farol do gerente"),
                    ("farol_calculado", "Farol pela conta"),
                    ("melancia", "Melancia"),
                    ("spi", "SPI"),
                    ("cpi", "CPI"),
                    ("situacao", "Situação"),
                    ("pct_concluido", "% concluído"),
                    ("estouro_previsto", "Estouro previsto"),
                    ("atraso_projetado_dias", "Atraso (dias)"),
                    ("ranking", "Risco 30d"),
                    ("faixa_risco", "Faixa"),
                ],
                "Os 41 projetos em andamento",
                pos(0, 22, 12, 8),
            ),
        ],
    )


def pagina_pessoas() -> dict:
    return pagina(
        "pessoas",
        "Pessoas",
        [
            texto("t_pessoas", "# Pessoas · quem está parado e por quê", pos(0, 0, 12, 1)),
            texto(
                "t_pessoas_sub",
                "Janela de **12 semanas** (24/07 a 16/10/2026). A hora parada é "
                "`(horas disponíveis − horas apontadas) × custo/hora`.",
                pos(0, 1, 12, 1),
            ),
            barra(
                "bar_hora_parada",
                "ds_hora_parada",
                "nome",
                "custo_hora_parada",
                "Top 15 por custo da hora parada em 12 semanas",
                pos(0, 2, 12, 7),
                cor="papel",
                rotulo_medida="Custo da hora parada (R$)",
                formato=MOEDA,
            ),
            tabela(
                "tab_pessoa_projeto",
                "ds_utilizacao_pessoa_projeto",
                [
                    ("nome", "Pessoa"),
                    ("papel", "Papel"),
                    ("senioridade", "Senioridade"),
                    ("projeto_id", "Projeto"),
                    ("horas_apontadas_12s", "Horas apontadas"),
                    ("horas_disponiveis_12s", "Capacidade"),
                    ("pct_da_capacidade", "% da capacidade"),
                ],
                "Utilização por pessoa e projeto",
                pos(0, 9, 12, 7),
            ),
            barra(
                "bar_bloqueios",
                "ds_bloqueios",
                "projeto_id",
                "status_com_bloqueio",
                "Causas de bloqueio por projeto (últimos 90 dias, pela IA)",
                pos(0, 16, 12, 6),
                cor="categoria_bloqueio",
                rotulo_medida="Semanas com bloqueio",
                horizontal=False,
            ),
        ],
    )


def pagina_fornecedores() -> dict:
    return pagina(
        "fornecedores",
        "Fornecedores",
        [
            texto("t_fornec", "# Fornecedores · quem cumpre o prazo", pos(0, 0, 12, 1)),
            texto(
                "t_fornec_sub",
                "A coluna **grafias no cadastro** é a prova de que a limpeza aconteceu: a CodeForge "
                "chegou escrita de 4 jeitos e, sem normalizar, apareceria como quatro fornecedores "
                "diferentes — nenhum deles com atraso visível.",
                pos(0, 1, 12, 2),
            ),
            tabela(
                "tab_fornecedores",
                "ds_fornecedores",
                [
                    ("fornecedor", "Fornecedor"),
                    ("grafias_no_cadastro", "Grafias no cadastro"),
                    ("entregas", "Entregas"),
                    ("em_aberto", "Em aberto"),
                    ("prazo_real_sobre_prometido", "Prazo real ÷ prometido"),
                    ("pct_no_prazo", "% no prazo"),
                    ("em_atraso_hoje", "Em atraso hoje"),
                ],
                "Confiança por fornecedor",
                pos(0, 3, 12, 6),
            ),
            tabela(
                "tab_entregas_atraso",
                "ds_entregas_em_atraso",
                [
                    ("entrega_id", "Entrega"),
                    ("projeto_id", "Projeto"),
                    ("fornecedor", "Fornecedor"),
                    ("item", "Item"),
                    ("valor", "Valor"),
                    ("data_prometida", "Prometida para"),
                    ("dias_de_atraso_hoje", "Dias de atraso"),
                ],
                "Entregas em atraso hoje",
                pos(0, 9, 12, 5),
            ),
        ],
    )


TEMA = {
    "canvasBackgroundColor": {"light": "#F5F7FB", "dark": FUNDO_ESCURO},
    "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#1C1C26"},
    "widgetBorderColor": {"light": "#E6EAF2", "dark": "#2A2A36"},
    "fontColor": {"light": FUNDO_ESCURO, "dark": "#E8ECF4"},
    "selectionColor": {"light": AZUL, "dark": CIANO},
    "visualizationColors": [AZUL, CIANO, ATENCAO, CRITICO, "#6C5CE7", "#00B894", "#8A94A6"],
}


def montar() -> dict:
    return {
        "datasets": [
            {"name": nome, "displayName": titulo, "queryLines": linhas}
            for nome, (titulo, linhas) in DATASETS.items()
        ],
        "pages": [pagina_portfolio(), pagina_pessoas(), pagina_fornecedores()],
        "uiSettings": {"theme": TEMA},
    }


# --------------------------------------------------------------------- #
# conferência: roda cada query ANTES do deploy
# --------------------------------------------------------------------- #
def qualificar(texto_sql: str) -> str:
    """Faz na mao o que o dataset_catalog/dataset_schema faz no deploy."""
    for tabela_gold in GOLD:
        texto_sql = re.sub(
            rf"\b(FROM|JOIN)\s+{tabela_gold}\b",
            rf"\1 lakehouse_vertice.gold.{tabela_gold}",
            texto_sql,
        )
    return texto_sql


def conferir(profile: str) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from run_sql import executar, warehouse_padrao

    warehouse = warehouse_padrao(profile)
    print(f"conferindo {len(DATASETS)} queries no warehouse {warehouse}\n")
    print(f"{'dataset':<32} {'linhas':>8}  situacao")
    print("-" * 60)
    falhas = 0
    for nome, (_, linhas) in DATASETS.items():
        consulta_sql = qualificar("".join(linhas))
        contagem = f"SELECT count(*) AS linhas FROM (\n{consulta_sql}\n)"
        try:
            r = executar(contagem, warehouse, profile)
            if r["status"]["state"] != "SUCCEEDED":
                raise RuntimeError(r["status"].get("error", {}).get("message", "falhou"))
            n = r["result"]["data_array"][0][0]
            print(f"{nome:<32} {n:>8}  ok")
        except Exception as erro:  # noqa: BLE001
            falhas += 1
            print(f"{nome:<32} {'-':>8}  FALHOU: {str(erro)[:70]}")
    print()
    print("todas as queries rodaram" if not falhas else f"{falhas} query(ies) falharam")
    return 1 if falhas else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--conferir", action="store_true", help="roda cada query em vez de gerar o JSON")
    ap.add_argument("--profile", help="profile do ~/.databrickscfg (obrigatório com --conferir)")
    args = ap.parse_args()

    if args.conferir:
        if not args.profile:
            sys.exit("--conferir precisa de --profile")
        return conferir(args.profile)

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(montar(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    painel = montar()
    print(f"gravado: {SAIDA.relative_to(RAIZ)}")
    print(f"  {len(painel['datasets'])} datasets")
    for p in painel["pages"]:
        print(f"  pagina {p['displayName']:<14} {len(p['layout'])} widgets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
