-- =====================================================================
-- STATUS COM IA · gold.status_estruturado
--
-- O texto que o gerente escreve toda sexta virando dado: a CATEGORIA do
-- bloqueio (ai_classify) e os DIAS DE IMPACTO que ele declarou
-- (ai_extract). É a metade qualitativa da 4ª pergunta do dono — a que
-- explica POR QUE o projeto está atrasado.
--
-- Por que só um punhado de textos passa pela IA:
-- ai_classify + ai_extract custam ~5 s por texto. Rodar nos 3.911 status
-- levaria horas e não diria nada novo. Então a IA só lê os status dos
-- ÚLTIMOS 90 DIAS que têm BLOQUEIO DE VERDADE: 163 textos (medido).
--
-- Como se sabe que um status "tem bloqueio"? O texto é estruturado:
--   "... Entregas da semana: X; Y. Bloqueios: <corpo>"
-- e o corpo vem "nenhum", "nada relevante" ou o bloqueio real. Nos 90
-- dias são 605 status com texto: 229 sem seção de bloqueios, 213 com a
-- seção vazia e 163 com bloqueio real. Procurar a palavra "atraso" ou
-- "falta" no texto inteiro pegaria 605 — quase todos — porque essas
-- palavras aparecem nas entregas também.
--
-- MERGE incremental: status já classificado não volta para o modelo.
-- Reexecutar o job não repaga a IA.
--
-- São QUATRO statements separados por ';': cria, classifica, marca
-- a falta de gente (sem IA) e relata.
-- Não existe `;` dentro de nenhum literal aqui, de propósito: a
-- sql_task corta o arquivo em todo ';'.
--
-- O "hoje" do dataset é 16/10/2026. Nunca current_date().
-- Conferência (seed 42): 163 status classificados; no PRJ-011 a causa
-- dos últimos 90 dias é falta de SRE, 12 semanas, 57 dias de impacto.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1) A tabela. IF NOT EXISTS porque o MERGE abaixo é quem a alimenta,
--    e porque recriá-la jogaria fora a IA já paga.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lakehouse_vertice.gold.status_estruturado (
  projeto_id          STRING  COMMENT 'o projeto do status',
  data_status         DATE    COMMENT 'a sexta do status',
  corpo_bloqueio      STRING  COMMENT 'o trecho depois de "Bloqueios:", que é o que a IA leu',
  categoria_bloqueio  STRING  COMMENT 'a causa, classificada pela IA (ai_classify)',
  dias_impacto        DOUBLE  COMMENT 'os dias de atraso que o gerente declarou no texto (ai_extract)',
  falta_de_gente      BOOLEAN COMMENT 'o texto diz que falta uma pessoa/papel (regra deterministica, sem IA)',
  classificado_em     TIMESTAMP COMMENT 'quando a IA leu este texto'
)
COMMENT 'O texto livre do status semanal virado dado: a categoria do bloqueio (ai_classify) e os dias de impacto declarados (ai_extract, schema tipado versão 2.0). Uma linha por projeto e por sexta, só para os status dos últimos 90 dias que têm bloqueio real (163 no seed 42). Alimentada por MERGE incremental: um status já classificado não volta para o modelo, então reexecutar o job não repaga a IA.';

-- ---------------------------------------------------------------------
-- 2) A IA, só no que falta classificar.
--    O NOT EXISTS é o que torna a tarefa barata na segunda execução.
-- ---------------------------------------------------------------------
MERGE INTO lakehouse_vertice.gold.status_estruturado AS alvo
USING (
  WITH com_corpo AS (
    SELECT
        s.projeto_id,
        s.data_status,
        -- tudo o que vem depois de "Bloqueios:" é o bloqueio declarado
        trim(regexp_extract(s.texto_status, '(?i)bloqueios:\s*(.*)$', 1)) AS corpo_bloqueio
    FROM lakehouse_vertice.silver.status_semanal s
    WHERE s.data_status >= date_sub(DATE'2026-10-16', 90)
      AND NOT s.status_vazio
  ),
  candidatos AS (
    SELECT c.projeto_id, c.data_status, c.corpo_bloqueio
    FROM com_corpo c
    WHERE c.corpo_bloqueio <> ''
      -- "nenhum" e "nada relevante" são ausência de bloqueio escrita por extenso
      AND NOT lower(c.corpo_bloqueio) RLIKE '^(nenhum|nada relevante|n/a|sem bloqueios)'
      AND NOT EXISTS (
        SELECT 1 FROM lakehouse_vertice.gold.status_estruturado e
        WHERE e.projeto_id = c.projeto_id AND e.data_status = c.data_status
      )
  )
  SELECT
      projeto_id,
      data_status,
      corpo_bloqueio,
      -- Os rótulos são longos de propósito. Com 'falta de pessoas' e
      -- 'ambiente e infraestrutura' lado a lado, um texto como "ambiente
      -- de homologação fora do ar, SEM RESPONSÁVEL DE INFRAESTRUTURA"
      -- caía em infraestrutura: o modelo lia o SINTOMA (o ambiente) em
      -- vez da CAUSA (não há SRE alocado). No PRJ-011, 9 das 12 semanas
      -- iam para o rótulo errado, e a resposta ao dono deixava de ser
      -- "falta de SRE" — que é o que as 12 semanas dizem, uma por uma.
      -- O rótulo agora nomeia a causa, e o de ambiente diz explicitamente
      -- que é falha técnica. (Rótulo de ai_classify: máximo 50 caracteres.)
      ai_classify(corpo_bloqueio, ARRAY(
        'falta de gente ou papel nao alocado',
        'fornecedor atrasou entrega',
        'mudanca de escopo',
        'falha tecnica de ambiente',
        'aprovacao pendente do cliente',
        'dificuldade tecnica na solucao',
        'outros'))                                            AS categoria_bloqueio,
      -- ai_extract SEM schema devolve tudo como texto. A versão 2.0 com
      -- JSON schema tipado é o que faz dias_impacto chegar como número.
      ai_extract(
        corpo_bloqueio,
        '{"dias_impacto":{"type":"number","description":"quantos dias de atraso o texto declara"}}',
        map('version', '2.0')
      ):response:dias_impacto::DOUBLE                          AS dias_impacto,
      -- A FLAG DETERMINISTICA, sem IA. Os textos do PRJ-011 citam o
      -- sintoma e a causa na mesma frase ("ambiente fora do ar, SEM
      -- RESPONSAVEL de infraestrutura"), e o ai_classify se divide: 7
      -- semanas em ambiente, 5 em falta de gente. Nenhum rotulo resolve
      -- isso sozinho, e apagar o rotulo de ambiente seria forcar a
      -- resposta. Esta regra responde a pergunta do dono sem depender da
      -- IA: o texto cita falta de PESSOA? E auditavel linha por linha.
      lower(corpo_bloqueio) RLIKE
        'sem sre|sem responsavel|sem respons|aguardando alguem|aguardando algu|sem gente|nao alocad|nenhuma pessoa|ninguem para|sem dev|sem arquiteto|pedimos sre|ocioso esperando|falta de'
                                                               AS falta_de_gente,
      current_timestamp()                                      AS classificado_em
  FROM candidatos
) AS novo
ON  alvo.projeto_id  = novo.projeto_id
AND alvo.data_status = novo.data_status
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *;

-- ---------------------------------------------------------------------
-- 3) A flag de falta de gente é deterministica, então recalculá-la em
--    toda execução é de graça — e mantém as linhas antigas corretas
--    quando a regra muda, sem chamar a IA de novo.
-- ---------------------------------------------------------------------
UPDATE lakehouse_vertice.gold.status_estruturado
SET falta_de_gente = lower(corpo_bloqueio) RLIKE
  'sem sre|sem responsavel|sem respons|aguardando alguem|aguardando algu|sem gente|nao alocad|nenhuma pessoa|ninguem para|sem dev|sem arquiteto|pedimos sre|ocioso esperando|falta de';

-- ---------------------------------------------------------------------
-- 4) O relatório: o que a IA achou, por categoria.
-- ---------------------------------------------------------------------
SELECT
    categoria_bloqueio,
    count(*)                        AS status,
    count(DISTINCT projeto_id)      AS projetos,
    round(sum(dias_impacto), 0)     AS dias_declarados,
    count_if(falta_de_gente)        AS citam_falta_de_gente
FROM lakehouse_vertice.gold.status_estruturado
GROUP BY categoria_bloqueio
ORDER BY status DESC;
