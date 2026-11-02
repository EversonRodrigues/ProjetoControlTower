import { describe, expect, it } from 'vitest';
import {
  formatarDias,
  formatarFracaoComoPercent,
  formatarIndice,
  formatarReaisCurto,
  paraBooleano,
  paraNumero,
} from './formatters';

/**
 * O que está testado aqui não é formatação por vaidade: é a conversão que
 * salvou a tela. O warehouse devolve TODO valor como string no JSON, e os
 * tipos gerados dizem `number`/`boolean` -- o compilador não pega, só o
 * runtime. Cada caso abaixo foi um bug real.
 *
 * O locale é pt-BR, então os separadores são vírgula decimal e ponto de
 * milhar. Os testes comparam dígito por dígito de propósito: se alguém trocar
 * o locale, a mentira aparece aqui e não na frente do dono.
 */
describe('paraNumero', () => {
  it('converte a string que o warehouse manda', () => {
    expect(paraNumero('0.92')).toBe(0.92);
  });

  it('null e undefined viram zero, não NaN', () => {
    expect(paraNumero(null)).toBe(0);
    expect(paraNumero(undefined)).toBe(0);
  });
});

describe('paraBooleano', () => {
  it('"false" do JSON é falso -- sem isto a melancia aparecia em toda linha', () => {
    expect(paraBooleano('false')).toBe(false);
  });

  it('aceita o booleano e a string "true"', () => {
    expect(paraBooleano(true)).toBe(true);
    expect(paraBooleano('true')).toBe(true);
  });

  it('ausência não é verdade', () => {
    expect(paraBooleano(null)).toBe(false);
    expect(paraBooleano(undefined)).toBe(false);
  });
});

describe('formatarIndice', () => {
  it('SPI e CPI sempre com 2 casas, como manda a convenção da Vértice', () => {
    expect(formatarIndice('0.92')).toBe('0,92');
    expect(formatarIndice(1)).toBe('1,00');
  });
});

describe('formatarFracaoComoPercent', () => {
  it('pct_utilizacao é FRAÇÃO: 0,0577 é 5,8% de uso, não 0,06%', () => {
    expect(formatarFracaoComoPercent('0.05770833333333334')).toBe('5,8%');
  });

  it('aceita zero casa para a coluna P(est.) da tabela', () => {
    expect(formatarFracaoComoPercent(0.988, 0)).toBe('99%');
  });
});

describe('formatarReaisCurto', () => {
  it('a escala que o dono usa: R$ 6,5 mi de estouro previsto', () => {
    expect(formatarReaisCurto('6465127.242262782')).toBe('R$ 6,5 mi');
  });

  it('a carteira dos 60 projetos', () => {
    expect(formatarReaisCurto(305214000)).toBe('R$ 305,2 mi');
  });

  it('abaixo de mil não inventa sufixo', () => {
    expect(formatarReaisCurto(0)).toContain('0');
  });
});

describe('formatarDias', () => {
  it('os 57 dias de impacto declarado do PRJ-011', () => {
    expect(formatarDias('57.0')).toBe('57 d');
  });

  it('com uma casa, para os dias recuperados do simulador', () => {
    expect(formatarDias(19, 1)).toBe('19,0 d');
  });
});
