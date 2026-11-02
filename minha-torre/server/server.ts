import { analytics, createApp, getExecutionContext, server } from '@databricks/appkit';
import { z } from 'zod';

/**
 * Projeto Farol · a Torre da Vértice para quem não escreve SQL.
 *
 * A leitura da gold é toda por config/queries/*.sql (plugin analytics).
 * A única exceção é o score do modelo, e ela é deliberada -- veja abaixo.
 *
 * Sem `cache` no createApp de propósito: o dono precisa ver o número que
 * está na gold agora, não o de alguns minutos atrás.
 */

/** O "hoje" do dataset da Vértice. Nunca current_date(). */
const HOJE = "DATE'2026-10-16'";

const SCORE_SQL = `
  SELECT projeto_id, prob_estouro_30d, ranking, faixa_risco, principais_fatores
  FROM lakehouse_vertice.gold.score_estouro_30d
  WHERE data_referencia = ${HOJE}
  ORDER BY ranking
`;

/**
 * O contrato do score é fixo (projeto_id, data_referencia, prob_estouro_30d,
 * ranking, faixa_risco, principais_fatores). O warehouse devolve TODO número
 * como string no JSON_ARRAY, então aqui é coerce, não number.
 */
const LinhaScore = z.object({
  projeto_id: z.string(),
  prob_estouro_30d: z.coerce.number(),
  ranking: z.coerce.number(),
  faixa_risco: z.string(),
  principais_fatores: z.string().nullable().default(''),
});

type LinhaScore = z.infer<typeof LinhaScore>;

/**
 * Por que o score não veio. A tela escreve coisas diferentes para cada
 * causa: "o modelo ainda não rodou" e "o warehouse está subindo" são
 * problemas opostos, e mostrar o primeiro quando é o segundo é mentir.
 */
type Causa = 'sem_tabela' | 'warehouse_frio' | 'erro';

function classificar(mensagem: string): Causa {
  const m = mensagem.toUpperCase();
  if (m.includes('TABLE_OR_VIEW_NOT_FOUND') || m.includes('DOES NOT EXIST')) return 'sem_tabela';
  if (m.includes('PENDING') || m.includes('RUNNING') || m.includes('WAREHOUSE')) return 'warehouse_frio';
  return 'erro';
}

/** Converte o result.data_array (array de arrays) em objetos. */
function montarLinhas(colunas: string[], dados: (string | null)[][]): LinhaScore[] {
  const linhas: LinhaScore[] = [];
  for (const valores of dados) {
    const bruto: Record<string, string | null> = {};
    colunas.forEach((coluna, i) => {
      bruto[coluna] = valores[i] ?? null;
    });
    const analisado = LinhaScore.safeParse(bruto);
    if (analisado.success) linhas.push(analisado.data);
  }
  return linhas;
}

await createApp({
  plugins: [analytics({}), server()],

  onPluginsReady(appkit) {
    appkit.server.extend((app) => {
      /**
       * GET /api/score-estouro -> { disponivel, linhas }
       *
       * POR QUE ISTO NÃO É UM ARQUIVO EM config/queries/:
       * gold.score_estouro_30d é escrita pelo modelo de ML, que no
       * repositório do aluno pode não ter rodado. Uma query em
       * config/queries/ apontando para tabela inexistente QUEBRA O BUILD no
       * typegen (`--wait` descreve cada query no warehouse). Lida aqui, a
       * ausência da tabela vira `disponivel: false` e a tela mostra "—".
       *
       * É a única rota de SELECT do app, e existe só por causa disso.
       */
      app.get('/api/score-estouro', async (_req, res) => {
        try {
          const { client } = getExecutionContext();
          const warehouseId = process.env.DATABRICKS_WAREHOUSE_ID;
          if (!warehouseId) {
            res.json({
              disponivel: false,
              causa: 'erro',
              motivo: 'warehouse não configurado',
              linhas: [],
            });
            return;
          }

          let resposta = await client.statementExecution.executeStatement({
            warehouse_id: warehouseId,
            statement: SCORE_SQL,
            wait_timeout: '30s',
            on_wait_timeout: 'CONTINUE',
            disposition: 'INLINE',
            format: 'JSON_ARRAY',
          });

          // Warehouse frio: a statement fica PENDING. Espera limitada -- o
          // proxy do Databricks Apps corta a requisição em 120 s, então o
          // teto aqui é 30 s de wait_timeout + 35 x 2 s = 100 s.
          for (let i = 0; i < 35 && resposta.status?.state && ['PENDING', 'RUNNING'].includes(resposta.status.state); i += 1) {
            await new Promise((pronto) => setTimeout(pronto, 2000));
            resposta = await client.statementExecution.getStatement({
              statement_id: resposta.statement_id ?? '',
            });
          }

          if (resposta.status?.state !== 'SUCCEEDED') {
            // Tabela ausente cai aqui (TABLE_OR_VIEW_NOT_FOUND), e também
            // falta de permissão ou warehouse que não subiu. Em todos os
            // casos a tela degrada em vez de quebrar.
            const mensagem = resposta.status?.error?.message ?? `statement ${resposta.status?.state}`;
            console.warn('[score-estouro] indisponível:', mensagem);
            res.json({
              disponivel: false,
              causa: classificar(mensagem),
              motivo: mensagem,
              linhas: [],
            });
            return;
          }

          const colunas = (resposta.manifest?.schema?.columns ?? []).map((c) => c.name ?? '');
          const dados = (resposta.result?.data_array ?? []) as (string | null)[][];
          res.json({ disponivel: true, linhas: montarLinhas(colunas, dados) });
        } catch (erro) {
          const mensagem = erro instanceof Error ? erro.message : String(erro);
          console.warn('[score-estouro] indisponível:', mensagem);
          res.json({ disponivel: false, causa: classificar(mensagem), motivo: mensagem, linhas: [] });
        }
      });
    });
  },
}).catch(console.error);
