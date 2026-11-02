import { describe, expect, it } from 'vitest';
import {
  HORAS_ONBOARDING_PADRAO,
  HORIZONTE_EM_DIAS,
  JANELA_DO_STATUS_EM_DIAS,
  SEMANAS_NO_MES,
  calcularRealocacao,
} from './realocacao';

/**
 * O caso real da Vértice, o mesmo que a aula mostra ao vivo:
 * COL0017 (Karina Ferraz, sre senior, parada no PRJ-007) -> PRJ-011.
 *
 * Os números vêm das queries, conferidos no warehouse:
 *   gold.utilizacao_pessoa_semana -> 37,69166... h paradas por semana (média de 12)
 *   silver.colaboradores          -> custo_hora 199,80
 *   gold.status_estruturado       -> 57 dias de falta de gente em 12 semanas
 */
const COL0017 = {
  horas_paradas_semana: 37.69166666666667,
  custo_hora: 199.8,
};
const PRJ_011 = { dias_falta_gente: 57 };

describe('calcularRealocacao · COL0017 -> PRJ-011', () => {
  const conta = calcularRealocacao(
    COL0017.horas_paradas_semana,
    COL0017.custo_hora,
    PRJ_011.dias_falta_gente,
    HORAS_ONBOARDING_PADRAO
  );

  it('multiplica as horas paradas por 4 semanas', () => {
    expect(conta.horasNoMes).toBeCloseTo(150.77, 2);
  });

  it('põe preço na ociosidade com o custo_hora da silver', () => {
    // 150,766666... h x R$ 199,80
    expect(conta.ociosidadeEvitada).toBeCloseTo(30123.18, 2);
  });

  it('projeta o impacto de 90 dias no horizonte de 30', () => {
    // 57 / 90 x 30 = 19 dias
    expect(conta.diasRecuperados).toBeCloseTo(19, 10);
  });

  it('cobra as 40 h de onboarding ao mesmo custo_hora', () => {
    expect(conta.mobilizacao).toBeCloseTo(7992, 2);
  });

  it('o saldo é a ociosidade evitada menos a mobilização', () => {
    expect(conta.saldo).toBeCloseTo(conta.ociosidadeEvitada - conta.mobilizacao, 10);
    expect(conta.saldo).toBeGreaterThan(0);
  });
});

describe('calcularRealocacao · bordas', () => {
  it('aceita string em tudo, porque o warehouse manda número como string', () => {
    const comString = calcularRealocacao('37.69166666666667', '199.80', '57', '40');
    const comNumero = calcularRealocacao(37.69166666666667, 199.8, 57, 40);
    expect(comString).toEqual(comNumero);
  });

  it('projeto sem impacto de falta de gente não recupera dia nenhum', () => {
    expect(calcularRealocacao(10, 100, 0, 40).diasRecuperados).toBe(0);
  });

  it('onboarding alto pode virar o saldo negativo -- e a tela precisa poder mostrar isso', () => {
    const conta = calcularRealocacao(1, 200, 57, 400);
    expect(conta.saldo).toBeLessThan(0);
  });

  it('null/undefined viram zero em vez de NaN', () => {
    const conta = calcularRealocacao(null, undefined, 0, 0);
    expect(conta.horasNoMes).toBe(0);
    expect(Number.isNaN(conta.saldo)).toBe(false);
  });

  it('as constantes da conta são as que o <details> explica na tela', () => {
    expect([SEMANAS_NO_MES, JANELA_DO_STATUS_EM_DIAS, HORIZONTE_EM_DIAS]).toEqual([4, 90, 30]);
  });
});
