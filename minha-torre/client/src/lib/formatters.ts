/**
 * O warehouse devolve TODO número como string no JSON. Number() em tudo que
 * vem da query, sempre -- sem isso `0.92.toFixed(2)` virou `"0.92".toFixed`
 * e a tela quebra em runtime, não na compilação.
 */
export const paraNumero = (valor: number | string | null | undefined): number =>
  valor === null || valor === undefined ? 0 : Number(valor);

/**
 * BOOLEAN também chega como string: o JSON do warehouse manda "false", e
 * `"false"` é truthy em JavaScript -- sem isto a melancia aparecia em TODAS
 * as linhas da tabela. O tipo gerado diz `boolean`; o runtime discorda.
 */
export const paraBooleano = (valor: boolean | string | null | undefined): boolean =>
  valor === true || valor === 'true';

/** R$ 1.234.567 -- sem centavos, que ninguém lê num KPI de milhões. */
export const formatarReais = (valor: number | string | null | undefined): string =>
  paraNumero(valor).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    maximumFractionDigits: 0,
  });

/**
 * R$ 199,80 -- com centavos. Usado no custo/hora: arredondar para R$ 200
 * fazia a conta do simulador parecer errada na tela (40 h x R$ 200 = R$
 * 8.000, e o card mostrava R$ 7.992).
 */
export const formatarReaisComCentavos = (valor: number | string | null | undefined): string =>
  paraNumero(valor).toLocaleString('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

/** R$ 6,5 mi -- a escala que o dono usa quando fala da carteira. */
export const formatarReaisCurto = (valor: number | string | null | undefined): string => {
  const n = paraNumero(valor);
  if (Math.abs(n) >= 1_000_000) return `R$ ${(n / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mi`;
  if (Math.abs(n) >= 1_000) return `R$ ${(n / 1_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`;
  return formatarReais(n);
};

/** SPI e CPI com 2 casas, como manda a convenção da Vértice. */
export const formatarIndice = (valor: number | string | null | undefined): string =>
  paraNumero(valor).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** pct_utilizacao e margem chegam como FRAÇÃO (0..1), não como percentual. */
export const formatarFracaoComoPercent = (
  valor: number | string | null | undefined,
  casas = 1,
): string =>
  `${(paraNumero(valor) * 100).toLocaleString('pt-BR', {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  })}%`;

export const formatarDias = (valor: number | string | null | undefined, casas = 0): string =>
  `${paraNumero(valor).toLocaleString('pt-BR', {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  })} d`;

export const formatarHoras = (valor: number | string | null | undefined, casas = 0): string =>
  `${paraNumero(valor).toLocaleString('pt-BR', {
    minimumFractionDigits: casas,
    maximumFractionDigits: casas,
  })} h`;

/** O que a tela mostra quando o número não existe. */
export const SEM_DADO = '—';

/** A data do dado. A gold é a fotografia de 16/10/2026, não de hoje. */
export const FOTOGRAFIA = '16/10/2026';
