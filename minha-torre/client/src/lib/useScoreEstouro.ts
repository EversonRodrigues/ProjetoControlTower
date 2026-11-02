import { useCallback, useEffect, useState } from 'react';

/**
 * A probabilidade de estouro em 30 dias por projeto.
 *
 * Vem da rota GET /api/score-estouro, não de config/queries/: a tabela
 * gold.score_estouro_30d é escrita pelo modelo de ML e pode não existir.
 * Quando não existe, `disponivel` é false e a tela mostra "—" -- o app não
 * quebra e o build não quebra.
 */
export interface LinhaScore {
  projeto_id: string;
  prob_estouro_30d: number;
  ranking: number;
  faixa_risco: string;
  principais_fatores: string;
}

/** Por que o score não veio. A tela escreve coisas diferentes para cada um. */
export type MotivoDaAusencia = 'sem_tabela' | 'warehouse_frio' | 'erro';

interface RespostaScore {
  disponivel: boolean;
  motivo?: string;
  causa?: MotivoDaAusencia;
  linhas: LinhaScore[];
}

export interface Score {
  disponivel: boolean;
  causa?: MotivoDaAusencia;
  motivo?: string;
  carregando: boolean;
  /** projeto_id -> linha do score, para a tabela casar linha por linha. */
  porProjeto: Map<string, LinhaScore>;
  /** O KPI da tela: quantos projetos o modelo põe na faixa 'alto'. */
  altoRisco30d: number | null;
  recarregar: () => void;
}

/**
 * @param habilitado só busca o score depois que as queries da gold
 *   responderam. O warehouse da Free Edition dorme em 10 minutos, e numa
 *   visita com o warehouse frio esta rota desistia antes de ele subir --
 *   a tela dizia "modelo ainda não publicou o score" com a tabela lá,
 *   inteira. Esperar o warehouse esquentar elimina a corrida.
 */
export function useScoreEstouro(habilitado: boolean): Score {
  const [tentativa, setTentativa] = useState(0);
  // A resposta guarda de QUAL tentativa ela veio. Assim o "carregando" é
  // derivado (resposta mais velha que a tentativa atual = ainda buscando)
  // em vez de um setState dentro do efeito.
  const [resultado, setResultado] = useState<{ tentativa: number; resposta: RespostaScore } | null>(
    null,
  );

  const recarregar = useCallback(() => setTentativa((n) => n + 1), []);

  useEffect(() => {
    if (!habilitado) return;
    let vivo = true;
    fetch('/api/score-estouro')
      .then((r) => r.json() as Promise<RespostaScore>)
      .then((resposta) => {
        if (vivo) setResultado({ tentativa, resposta });
      })
      .catch(() => {
        // A rota já degrada sozinha; aqui só garantimos que a tela não trave.
        if (vivo) {
          setResultado({ tentativa, resposta: { disponivel: false, causa: 'erro', linhas: [] } });
        }
      });
    return () => {
      vivo = false;
    };
  }, [habilitado, tentativa]);

  const resposta = resultado?.tentativa === tentativa ? resultado.resposta : null;
  const linhas = resposta?.linhas ?? [];
  const disponivel = resposta?.disponivel === true;

  return {
    disponivel,
    causa: resposta?.causa,
    motivo: resposta?.motivo,
    // Enquanto espera o warehouse das outras queries, o card continua em
    // estado de carregando em vez de piscar um "—" que seria mentira.
    carregando: !habilitado || resposta === null,
    porProjeto: new Map(linhas.map((l) => [l.projeto_id, l])),
    altoRisco30d: disponivel ? linhas.filter((l) => l.faixa_risco === 'alto').length : null,
    recarregar,
  };
}
