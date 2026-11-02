#!/usr/bin/env python3
"""Gera resources/farol.geniespace.json (serialized_space versao 2).

  python scripts/gerar_genie.py

Regras da API que decidem o formato do arquivo:
  · question, sql e content sao ARRAYS de strings, nunca string
  · id e hex minusculo de 32 caracteres, unico entre as TRES listas
  · data_sources.tables ordenado por identifier, e
    example_question_sqls e text_instructions ordenados por id
  · text_instructions aceita NO MAXIMO UM item -- por isso a instrucao
    inteira (persona, guia de tabelas, formulas, dominios) vai num unico
    bloco, e nao em varios

Os ids sao DETERMINISTICOS (contador, nao uuid4): regerar o arquivo tem
que dar o mesmo JSON byte a byte, senao todo `bundle deploy` mexe no
espaco e o diff do Git e ruido. O prefixo separa as listas e o contador
no fim faz a ordem alfabetica do id ser a ordem de autoria, que e
exatamente o que a API exige.
"""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "resources" / "farol.geniespace.json"

CATALOGO = "lakehouse_vertice"


def ident(lista: int, n: int) -> str:
    """Id de 32 hex: 1 = perguntas de exemplo, 2 = SQLs, 3 = instrucao."""
    assert 1 <= lista <= 3 and 1 <= n <= 9999
    return f"{lista}{'0' * 27}{n:04d}"


# As 7 fontes. score_estouro_30d entra alem do que o prompt_04 lista: a
# tabela ja existe (o "o modelo vem na noite 3" do prompt esta
# desatualizado) e e a resposta real a 4a pergunta do dono.
TABELAS = sorted(
    [
        f"{CATALOGO}.gold.fato_projeto_semana",
        f"{CATALOGO}.gold.mv_projetos",
        f"{CATALOGO}.gold.projeto_situacao_atual",
        f"{CATALOGO}.gold.score_estouro_30d",
        f"{CATALOGO}.gold.status_estruturado",
        f"{CATALOGO}.gold.utilizacao_pessoa_semana",
        f"{CATALOGO}.silver.entregas_fornecedor",
    ]
)

# As perguntas de exemplo do espaco -- os "chips" que o usuario clica.
#
# Sao as MESMAS que a descricao do espaco manda experimentar
# (resources/genie.genie_space.yml): se a descricao sugere uma pergunta e o
# botao oferece outra, o usuario estranha na primeira tela.
#
# Todas foram verificadas contra o espaco no ar. Deliberadamente NAO entra aqui
# "e se eu realocar uma pessoa?": a conta em reais dessa simulacao vive no app
# (aba Simulador), nao no Genie -- ele recusa a pergunta, com razao, e uma
# sugestao que nao responde e a pior primeira impressao possivel.
PERGUNTAS_DO_DONO = [
    "Quais projetos estão em risco e quanto isso vai custar?",
    "Qual farol verde, na verdade, está vermelho?",
    "Tenho gente parada enquanto outro projeto pede gente?",
    "Por que o PRJ-011 atrasou?",
    "O que vai dar errado no próximo mês?",
]

INSTRUCAO = """\
QUEM PERGUNTA. O dono da Vértice Tecnologia e a diretoria. Eles não escrevem SQL.
Responda em português do Brasil, em frases curtas, citando projeto_id e cliente quando a
resposta for sobre projeto, e dinheiro em reais com vírgula decimal (R$ 6,47 mi). Se a
pergunta for ambígua, responda a leitura mais útil e diga qual leitura você usou.

O HOJE DO DADO É 16/10/2026 (sexta). NUNCA use current_date(): o número mudaria todo dia
e não bateria com o de ninguém. Escreva sempre DATE'2026-10-16'.
  - "últimos 90 dias" = data_status >= date_sub(DATE'2026-10-16', 90)
  - "12 semanas"      = semana BETWEEN date_sub(DATE'2026-10-16', 77) AND DATE'2026-10-16'
                        (as 11 sextas anteriores mais a de hoje)
  - "último mês / últimas 4 semanas" = 25/09, 02/10, 09/10 e 16/10 de 2026
  - "próximo mês"     = de 17/10/2026 a 16/11/2026

QUAL TABELA USAR.
  - TOTAL DE HOJE, em qualquer corte (cliente, segmento, tipo de projeto, ferramenta,
    gerente, status, situação, farol): gold.mv_projetos, com MEASURE(). É a métrica
    governada. Medidas disponíveis: projetos, carteira, orcamento, custo_real, ev, spi,
    cpi, eac, estouro_previsto, margem_projetada, projetos_em_risco, projetos_criticos,
    projetos_em_atencao, melancias, atraso_projetado_dias.

O FILTRO DE STATUS. As duas leituras existem e a pergunta decide qual usar.
  - PERGUNTA DE RISCO, PRAZO OU PREVISAO: filtre WHERE status = 'em_andamento'.
    As palavras "hoje", "em risco", "critico", "em atencao", "atrasado", "melancia",
    "estouro previsto", "SPI", "CPI" e "margem projetada" JA significam em andamento,
    mesmo que a pergunta nao diga: projeto concluido nao esta atrasado HOJE. Sem esse
    filtro, "quantos projetos estao criticos" devolve 10 em vez de 7, porque entram 3
    projetos que ja terminaram.
  - PERGUNTA SOBRE O QUE JA ACONTECEU (realizado, acumulado, historico, "ja lancado",
    "total da empresa", "quantos projetos existem"): NAO filtre, some os 60 projetos.
    O custo real total ja lancado e R$ 193,35 mi nos 60 projetos, e NAO os R$ 114,5 mi
    dos 41 em andamento. Dinheiro gasto em projeto entregue continua gasto.
  Em duvida, responda a leitura de risco (em andamento) e DIGA qual leitura usou.
  - RANKING, LISTA E DETALHE DE PROJETO: gold.projeto_situacao_atual, uma linha por
    projeto (60 linhas), já com o cadastro. Toda pergunta "quais projetos" ou "top N"
    vem daqui, nunca da mv_projetos.
  - SÉRIE SEMANAL E TENDÊNCIA: gold.fato_projeto_semana (projeto x sexta).
  - POR QUE O PROJETO ATRASOU: gold.status_estruturado.
  - GENTE PARADA: gold.utilizacao_pessoa_semana.
  - FORNECEDOR: silver.entregas_fornecedor.
  - O QUE VAI DAR ERRADO NO PRÓXIMO MÊS: gold.score_estouro_30d.

AS FÓRMULAS E AS REGRAS DE CORTE (manual da Vértice).
  SPI = EV / PV. Abaixo de 1 é atraso.
  CPI = EV / AC. Abaixo de 1 é estouro.
  EAC = orçamento / CPI. Estouro previsto = EAC - orçamento, só quando positivo.
  Margem projetada = (valor do contrato - EAC) / valor do contrato.
  Atraso projetado em dias = duração baseline / SPI - duração baseline.
  indice_min = o pior entre SPI e CPI, e é ele que manda.
  CORTE: SPI ou CPI abaixo de 0,9 é ATENÇÃO. Abaixo de 0,8 é CRÍTICO.
  SPI E CPI SÃO RAZÕES. Para o índice de um GRUPO use MEASURE(spi) e MEASURE(cpi) na
  mv_projetos. NUNCA AVG(spi) nem AVG(cpi): média de razão dá o número errado, porque um
  projeto de R$ 200 mil pesaria igual a um de R$ 20 mi.

PV, EV E AC NO FATO SÃO ACUMULADOS. Em gold.fato_projeto_semana as colunas ev_dinheiro,
pv_dinheiro e ac_dinheiro são o acumulado do projeto ATÉ aquela sexta. Pode somar os
PROJETOS dentro de uma mesma semana. NUNCA some semanas: isso contaria o mesmo dinheiro
várias vezes. Para a série do SPI da carteira: GROUP BY semana e
SUM(ev_dinheiro)/SUM(pv_dinheiro).

AS DUAS FONTES DE AVANÇO, e é importante não confundir. O status semanal é o que o
gerente DIZ (gold.fato_projeto_semana). O cronograma é o que as tarefas das três
ferramentas MOSTRAM (gold.projeto_situacao_atual). O SPI da carteira pelas tarefas é
0,92; pelo status semanal é 0,87. Quando a pergunta for sobre hoje, use as tarefas
(projeto_situacao_atual ou mv_projetos). Quando for sobre tendência, use o status
semanal, e diga que é o status.

FAROL E MELANCIA. farol_calculado é a conta: verde com SPI >= 0,95, amarelo >= 0,90,
vermelho abaixo. farol_do_gerente é o que o gerente reportou. MELANCIA é farol do gerente
VERDE com SPI abaixo de 0,9: verde por fora, atrasado por dentro. A coluna melancia é
BOOLEAN. Hoje são 4 melancias.

DOMÍNIOS EXATOS, use estes valores literais:
  status: 'em_andamento' ou 'concluido' (com underscore e SEM acento). Nunca escreva
    'em andamento' nem 'concluído'.
  situacao: 'ok', 'atencao', 'critico' (sem acento).
  farol_calculado e farol_do_gerente: 'verde', 'amarelo', 'vermelho'.
  segmento: 'varejo', 'financeiro', 'industria', 'saude', 'logistica'.
  ferramenta: 'excel', 'clickup', 'msproject'.
  faixa_risco: 'alto', 'medio', 'baixo'.
  categoria_bloqueio, os SETE valores possíveis e nada além deles:
    'falta de gente ou papel nao alocado', 'fornecedor atrasou entrega',
    'mudanca de escopo', 'falha tecnica de ambiente', 'aprovacao pendente do cliente',
    'dificuldade tecnica na solucao', 'outros'.

POR QUE O PROJETO X ATRASOU. Responda com gold.status_estruturado dos últimos 90 dias
filtrando projeto_id, e traga: a categoria_bloqueio mais frequente, em quantas semanas
ela apareceu, a soma de dias_impacto declarados e um ou dois corpo_bloqueio como citação.
ATENÇÃO: status_estruturado JÁ CONTÉM SOMENTE os status com bloqueio real dos últimos 90
dias (163 linhas). Não existe e não precisa excluir nenhuma categoria de "sem bloqueio"
ou "não reportado" -- esses valores não existem nesta tabela.
Junte sempre o SPI e o CPI de hoje do projeto (projeto_situacao_atual), para a resposta
ter o tamanho do problema, e não só a causa.
Quando a causa for FALTA DE GENTE, use a coluna BOOLEAN falta_de_gente, não a categoria:
a IA divide o mesmo bloqueio entre 'falha tecnica de ambiente' e 'falta de gente ou papel
nao alocado', e só o booleano pega as duas. No PRJ-011, falta_de_gente é verdadeiro nas 12
semanas, somando 57 dias de impacto declarado. Nesse caso complete a resposta com as
pessoas do papel que falta que estão OCIOSAS (gold.utilizacao_pessoa_semana, 12 semanas):
existem dois SREs com menos de 20% de uso, COL0017 e COL0018, alocados no PRJ-007.

GENTE PARADA. Pessoa parada = utilização abaixo de 20% nas 12 semanas, isto é
SUM(horas_apontadas) / SUM(horas_disponiveis) < 0,20 com GROUP BY colaborador_id em
gold.utilizacao_pessoa_semana. A coluna pct_utilizacao_12s existe, mas é NULL quando a
pessoa ainda não tem a janela de 12 semanas cheia: prefira recalcular com SUM/SUM, que
nunca devolve NULL em silêncio.
O GRÃO DESTA TABELA É PESSOA E SEMANA. NÃO existe grão por pessoa e projeto aqui: para
dizer em QUE projeto a pessoa está, use max_by(projeto_principal, horas_apontadas).
Traga sempre colaborador_id, nome, papel, o percentual e o projeto: "COL0017, SRE, 5,8%
de uso, no PRJ-007" é a resposta útil; "COL0017 está parado" não é.
A outra metade da pergunta é "enquanto outro projeto pede gente": cruze com
status_estruturado dos últimos 90 dias onde falta_de_gente é verdadeiro, para mostrar o
projeto que PEDE o papel ao lado da pessoa que está parada.

FORNECEDOR. Use silver.entregas_fornecedor. A medida de confiança é
AVG(prazo_real_dias / prazo_prometido_dias), a MÉDIA DAS RAZÕES por entrega -- acima de 1
o fornecedor costuma estourar o prazo. Percentual no prazo = entregas com
dias_de_atraso_na_entrega <= 0 sobre as que já foram entregues (em_aberto falso).
"Em atraso hoje" é a coluna em_atraso. Use sempre a coluna fornecedor, que está
normalizada: fornecedor_como_veio guarda as grafias originais, e a CodeForge chegou
escrita de 4 jeitos -- sem a normalização ela viraria quatro fornecedores, nenhum com
atraso visível. Medido hoje: 5 entregas em atraso, todas da CodeForge, cujo prazo real
sobre prometido é 1,41 e o percentual no prazo é 0%.

O QUE VAI DAR ERRADO NO PRÓXIMO MÊS. Três peças, nesta ordem:
  1. gold.score_estouro_30d, com data_referencia = DATE'2026-10-16'. ranking 1 é o mais
     arriscado; traga prob_estouro_30d, faixa_risco e principais_fatores, que já vêm em
     português. São os 41 projetos em andamento. Comece por aqui.
  2. As entregas de consultoria em atraso (silver.entregas_fornecedor, em_atraso
     verdadeiro) nos projetos envolvidos.
  3. O CHANGE FREEZE DE VAREJO, de 01/11/2026 a 10/01/2027: nenhuma mudança entra em
     produção no varejo nesse período. Ele atinge os projetos com segmento = 'varejo' e
     tipo_projeto de e-commerce ('Nova plataforma de e-commerce', 'Checkout e meios de
     pagamento', 'Marketplace de sellers', 'Integração omnichannel') cuja entrega cai
     dentro da janela (data_fim_baseline >= DATE'2026-11-01'). O change freeze não está
     em nenhuma coluna: é esta regra de calendário.

QUAIS CLIENTES. Quando a pergunta for "de quais clientes" ou "quais clientes", devolva
CADA CLIENTE UMA VEZ: SELECT DISTINCT cliente, ou GROUP BY cliente com a contagem de
projetos ao lado. Nunca repita o mesmo cliente uma vez por projeto. Hoje são 17 projetos
em risco distribuídos em 13 clientes, porque quatro clientes têm dois projetos cada.

RÉGUAS PARA VOCÊ SE CONFERIR (16/10/2026): 60 projetos, 41 em andamento e 19 concluídos.
7 críticos e 10 em atenção, 17 em risco. Carteira R$ 208,63 mi. Estouro previsto
R$ 6,47 mi. SPI da carteira 0,92 e CPI 0,97. 4 melancias: PRJ-012, PRJ-028, PRJ-034 e
PRJ-042. Custo real total R$ 193,35 mi. 163 status classificados nos últimos 90 dias. Se
o seu número ficar muito longe de um destes, revise o filtro de status e o de data antes
de responder.
"""

EXEMPLOS: list[tuple[str, str]] = [
    (
        "Quais projetos estão atrasados, e de quais clientes?",
        """\
SELECT
    projeto_id,
    nome_projeto,
    cliente,
    gerente_projeto,
    round(spi, 2)                  AS spi,
    round(cpi, 2)                  AS cpi,
    situacao,
    farol_do_gerente,
    farol_calculado,
    melancia,
    round(atraso_projetado_dias)   AS atraso_projetado_dias
FROM lakehouse_vertice.gold.projeto_situacao_atual
WHERE status = 'em_andamento'
  AND least(spi, cpi) < 0.9
ORDER BY least(spi, cpi)
""",
    ),
    (
        "Quanto esse atraso vai me custar?",
        """\
SELECT
    MEASURE(projetos)            AS projetos_em_andamento,
    MEASURE(carteira)            AS carteira,
    MEASURE(estouro_previsto)    AS estouro_previsto,
    MEASURE(margem_projetada)    AS margem_projetada,
    MEASURE(projetos_criticos)   AS criticos,
    MEASURE(projetos_em_atencao) AS em_atencao
FROM lakehouse_vertice.gold.mv_projetos
WHERE status = 'em_andamento'
GROUP BY ALL
""",
    ),
    (
        "Tenho gente parada enquanto outro projeto pede gente?",
        """\
WITH uso_12_semanas AS (
  SELECT
      colaborador_id,
      nome,
      papel,
      senioridade,
      max_by(projeto_principal, horas_apontadas)               AS projeto_principal,
      sum(horas_apontadas) / nullif(sum(horas_disponiveis), 0) AS pct_utilizacao_12s
  FROM lakehouse_vertice.gold.utilizacao_pessoa_semana
  WHERE semana BETWEEN date_sub(DATE'2026-10-16', 77) AND DATE'2026-10-16'
  GROUP BY colaborador_id, nome, papel, senioridade
),
projetos_que_pedem_gente AS (
  SELECT
      projeto_id,
      count(*)          AS semanas_pedindo_gente,
      sum(dias_impacto) AS dias_declarados
  FROM lakehouse_vertice.gold.status_estruturado
  WHERE data_status >= date_sub(DATE'2026-10-16', 90)
    AND falta_de_gente
  GROUP BY projeto_id
)
SELECT
    u.colaborador_id,
    u.nome,
    u.papel,
    u.senioridade,
    round(100 * u.pct_utilizacao_12s, 1) AS pct_uso_12s,
    u.projeto_principal                  AS parada_no_projeto,
    (SELECT count(*) FROM projetos_que_pedem_gente) AS projetos_pedindo_gente
FROM uso_12_semanas u
WHERE u.pct_utilizacao_12s < 0.20
ORDER BY u.pct_utilizacao_12s
""",
    ),
    (
        "O que vai dar errado no próximo mês?",
        """\
SELECT
    s.ranking,
    s.projeto_id,
    p.nome_projeto,
    p.cliente,
    p.segmento,
    round(s.prob_estouro_30d, 3) AS prob_estouro_30d,
    s.faixa_risco,
    s.principais_fatores,
    p.entregas_em_atraso,
    (p.segmento = 'varejo'
      AND p.tipo_projeto IN ('Nova plataforma de e-commerce',
                             'Checkout e meios de pagamento',
                             'Marketplace de sellers',
                             'Integração omnichannel')
      AND p.data_fim_baseline >= DATE'2026-11-01') AS exposto_ao_change_freeze
FROM lakehouse_vertice.gold.score_estouro_30d s
JOIN lakehouse_vertice.gold.projeto_situacao_atual p USING (projeto_id)
WHERE s.data_referencia = DATE'2026-10-16'
ORDER BY s.ranking
LIMIT 10
""",
    ),
    (
        "Por que o projeto PRJ-011 atrasou?",
        """\
SELECT
    e.projeto_id,
    e.categoria_bloqueio,
    count(*)                   AS semanas_com_esse_bloqueio,
    sum(e.dias_impacto)        AS dias_declarados,
    count_if(e.falta_de_gente) AS semanas_citando_falta_de_gente,
    max(e.corpo_bloqueio)      AS exemplo_do_texto
FROM lakehouse_vertice.gold.status_estruturado e
WHERE e.projeto_id = 'PRJ-011'
  AND e.data_status >= date_sub(DATE'2026-10-16', 90)
GROUP BY e.projeto_id, e.categoria_bloqueio
ORDER BY semanas_com_esse_bloqueio DESC
""",
    ),
    (
        "Qual fornecedor atrasa mais as entregas?",
        """\
SELECT
    fornecedor,
    count(DISTINCT fornecedor_como_veio)                   AS grafias_no_cadastro,
    count(*)                                               AS entregas,
    round(avg(prazo_real_dias
              / nullif(prazo_prometido_dias, 0)), 2)       AS prazo_real_sobre_prometido,
    round(100.0 * count_if(NOT em_aberto AND dias_de_atraso_na_entrega <= 0)
          / nullif(count_if(NOT em_aberto), 0), 0)         AS pct_no_prazo,
    count_if(em_atraso)                                    AS em_atraso_hoje
FROM lakehouse_vertice.silver.entregas_fornecedor
GROUP BY fornecedor
ORDER BY prazo_real_sobre_prometido DESC NULLS LAST
""",
    ),
]


def linhas(texto: str) -> list[str]:
    """Quebra em array de strings mantendo o \\n, como a API espera."""
    return [linha + "\n" for linha in texto.rstrip("\n").split("\n")]


def espaco() -> dict:
    return {
        "version": 2,
        "config": {
            "sample_questions": [
                {"id": ident(1, i), "question": [p]}
                for i, p in enumerate(PERGUNTAS_DO_DONO, 1)
            ]
        },
        "data_sources": {"tables": [{"identifier": t} for t in TABELAS]},
        "instructions": {
            "example_question_sqls": [
                {"id": ident(2, i), "question": [q], "sql": linhas(s)}
                for i, (q, s) in enumerate(EXEMPLOS, 1)
            ],
            # UM unico item: a API rejeita dois.
            "text_instructions": [{"id": ident(3, 1), "content": linhas(INSTRUCAO)}],
        },
    }


def main() -> int:
    e = espaco()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(e, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ids = (
        [q["id"] for q in e["config"]["sample_questions"]]
        + [x["id"] for x in e["instructions"]["example_question_sqls"]]
        + [x["id"] for x in e["instructions"]["text_instructions"]]
    )
    assert len(ids) == len(set(ids)), "id repetido entre as tres listas"
    assert all(len(i) == 32 and all(c in "0123456789abcdef" for c in i) for i in ids), ids
    for lista in ("example_question_sqls", "text_instructions"):
        seq = [x["id"] for x in e["instructions"][lista]]
        assert seq == sorted(seq), f"{lista} fora de ordem"
    assert [t["identifier"] for t in e["data_sources"]["tables"]] == TABELAS
    assert len(e["instructions"]["text_instructions"]) == 1, "a API aceita um unico bloco"

    print(f"gravado: {SAIDA.relative_to(RAIZ)}")
    print(f"  {len(TABELAS)} fontes, {len(PERGUNTAS_DO_DONO)} perguntas de exemplo, "
          f"{len(EXEMPLOS)} SQLs, 1 bloco de instrucao "
          f"({len(e['instructions']['text_instructions'][0]['content'])} linhas)")
    for t in TABELAS:
        print(f"    {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
