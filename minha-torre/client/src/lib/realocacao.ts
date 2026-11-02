import { paraNumero } from './formatters';

/**
 * As contas do simulador de realocação, fora do componente.
 *
 * Por que uma função pura e não um useMemo no Simulador: isto é a única
 * aritmética do app que o dono vai levar para uma reunião. Aqui ela é
 * testável sem navegador e sem warehouse -- client/src/lib/realocacao.test.ts
 * trava os números do caso real (COL0017 -> PRJ-011).
 */

/** Onboarding padrão: uma semana de 40 h para a pessoa entrar no projeto. */
export const HORAS_ONBOARDING_PADRAO = 40;

/** 4 semanas no mês, janela de 90 dias do status projetada em 30. */
export const SEMANAS_NO_MES = 4;
export const JANELA_DO_STATUS_EM_DIAS = 90;
export const HORIZONTE_EM_DIAS = 30;

export interface Realocacao {
  custoHora: number;
  horasNoMes: number;
  ociosidadeEvitada: number;
  diasRecuperados: number;
  mobilizacao: number;
  saldo: number;
}

/** Todo numero do warehouse pode chegar como string -- ou nao chegar. */
type ValorDoWarehouse = number | string | null | undefined;

/**
 * Tudo que entra aqui vem do warehouse (ou de um <input>), então tudo pode
 * chegar como string. `paraNumero` em cada um -- ver o comentário em
 * formatters.ts.
 *
 * @param horasParadasSemana média das 12 semanas, da gold.utilizacao_pessoa_semana
 * @param custoHora          silver.colaboradores.custo_hora
 * @param diasFaltaGente     dias de impacto declarado nos últimos 90 dias
 * @param horasOnboarding    editável na tela; 40 h é palpite, não dado
 */
export function calcularRealocacao(
  horasParadasSemana: ValorDoWarehouse,
  custoHora: ValorDoWarehouse,
  diasFaltaGente: ValorDoWarehouse,
  horasOnboarding: ValorDoWarehouse
): Realocacao {
  const custo = paraNumero(custoHora);
  const horasNoMes = paraNumero(horasParadasSemana) * SEMANAS_NO_MES;
  const ociosidadeEvitada = horasNoMes * custo;
  // Tirar a causa não devolve o passado: devolve o ritmo daqui para a frente.
  // Daí a média diária do impacto projetada no horizonte, e não o total.
  const diasRecuperados = (paraNumero(diasFaltaGente) / JANELA_DO_STATUS_EM_DIAS) * HORIZONTE_EM_DIAS;
  const mobilizacao = paraNumero(horasOnboarding) * custo;
  return {
    custoHora: custo,
    horasNoMes,
    ociosidadeEvitada,
    diasRecuperados,
    mobilizacao,
    saldo: ociosidadeEvitada - mobilizacao,
  };
}
