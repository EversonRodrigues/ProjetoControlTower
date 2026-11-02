import { useMemo, useState } from 'react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Empty,
  EmptyDescription,
  EmptyTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { Loader2 } from 'lucide-react';
import {
  FOTOGRAFIA,
  formatarDias,
  formatarFracaoComoPercent,
  formatarHoras,
  formatarIndice,
  formatarReais,
  formatarReaisComCentavos,
  paraNumero,
} from '../lib/formatters';
import {
  HORAS_ONBOARDING_PADRAO,
  HORIZONTE_EM_DIAS,
  JANELA_DO_STATUS_EM_DIAS,
  SEMANAS_NO_MES,
  calcularRealocacao,
} from '../lib/realocacao';

function Resultado({
  titulo,
  valor,
  explicacao,
  tom = 'neutro',
}: {
  titulo: string;
  valor: string;
  explicacao: string;
  tom?: 'neutro' | 'bom' | 'ruim';
}) {
  const cor = tom === 'bom' ? 'text-success' : tom === 'ruim' ? 'text-destructive' : 'text-foreground';
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{titulo}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        <div className={`text-2xl font-semibold tabular-nums ${cor}`}>{valor}</div>
        <p className="text-xs text-muted-foreground">{explicacao}</p>
      </CardContent>
    </Card>
  );
}

export function Simulador() {
  const semParametros = useMemo(() => ({}), []);
  const pessoas = useAnalyticsQuery('pessoas_ociosas', semParametros);
  const projetos = useAnalyticsQuery('projetos_risco', semParametros);

  const [colaboradorId, setColaboradorId] = useState<string>('');
  const [projetoId, setProjetoId] = useState<string>('');
  const [horasOnboarding, setHorasOnboarding] = useState<string>(String(HORAS_ONBOARDING_PADRAO));

  const listaDePessoas = pessoas.data ?? [];
  const pessoa = listaDePessoas.find((p) => p.colaborador_id === colaboradorId);

  /**
   * Só projetos em atenção ou crítico: realocar gente para um projeto que
   * está ok não recupera cronograma nenhum.
   *
   * Para SRE a ordem é pelos dias que a falta de gente já custou -- é onde a
   * pessoa que falta é exatamente a pessoa que está parada. Para os outros
   * papéis vale a ordem que a query já traz (o pior índice primeiro).
   */
  const destinos = useMemo(() => {
    const emRisco = (projetos.data ?? []).filter((p) => p.situacao === 'atencao' || p.situacao === 'critico');
    if (pessoa?.papel.includes('sre')) {
      return [...emRisco].sort((a, b) => paraNumero(b.dias_falta_gente) - paraNumero(a.dias_falta_gente));
    }
    return emRisco;
  }, [projetos.data, pessoa]);

  const projeto = destinos.find((p) => p.projeto_id === projetoId);

  // As cinco contas. Tudo derivado no cliente -- nenhuma query nova.
  // A aritmetica mora em lib/realocacao.ts, onde o teste a alcanca.
  const conta = useMemo(
    () =>
      pessoa && projeto
        ? calcularRealocacao(pessoa.horas_paradas_semana, pessoa.custo_hora, projeto.dias_falta_gente, horasOnboarding)
        : null,
    [pessoa, projeto, horasOnboarding]
  );

  const carregando = pessoas.loading || projetos.loading;
  const erro = pessoas.error ?? projetos.error;

  const statusWarehouse = pessoas.warehouseStatus ?? projetos.warehouseStatus;
  const aquecendo = statusWarehouse !== null && statusWarehouse.state !== 'RUNNING';

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-foreground">Simulador de realocação</h2>
        <p className="text-sm text-muted-foreground">
          Tenho gente parada enquanto outro projeto pede gente? Escolha a pessoa e o destino e veja a conta em reais.
          Base: últimas 12 semanas até {FOTOGRAFIA}.
        </p>
      </div>

      {aquecendo && (
        <Alert>
          <AlertTitle>Ligando o warehouse</AlertTitle>
          <AlertDescription>
            O SQL warehouse está {statusWarehouse.state.toLowerCase()} e as listas aparecem sozinhas quando ele subir.
            Ele dorme depois de 10 minutos parado, então a primeira visita costuma esperar um ou dois minutos.
          </AlertDescription>
        </Alert>
      )}

      {erro && (
        <Alert variant="destructive">
          <AlertTitle>Não foi possível ler a gold</AlertTitle>
          <AlertDescription>{erro}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>A realocação</CardTitle>
        </CardHeader>
        <CardContent>
          {carregando ? (
            <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              <span>{aquecendo ? 'ligando o warehouse…' : 'lendo quem está parado…'}</span>
            </div>
          ) : listaDePessoas.length === 0 ? (
            <Empty>
              <EmptyTitle>Ninguém com utilização abaixo de 20%</EmptyTitle>
              <EmptyDescription>
                Nas últimas 12 semanas não há pessoa parada na gold.utilizacao_pessoa_semana. Sem gente ociosa não há
                realocação a simular.
              </EmptyDescription>
            </Empty>
          ) : (
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="pessoa">Pessoa parada</Label>
                <Select value={colaboradorId} onValueChange={setColaboradorId}>
                  <SelectTrigger id="pessoa">
                    <SelectValue placeholder="escolha quem está ocioso" />
                  </SelectTrigger>
                  <SelectContent>
                    {listaDePessoas.map((p) => (
                      <SelectItem key={p.colaborador_id} value={p.colaborador_id}>
                        {p.nome} · {p.papel} {p.senioridade} · {formatarFracaoComoPercent(p.pct_utilizacao_12s)} de uso
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {pessoa && (
                  <p className="text-xs text-muted-foreground">
                    hoje no {pessoa.projeto_principal} · {formatarHoras(pessoa.horas_paradas_semana, 1)} paradas por
                    semana · {formatarReais(pessoa.custo_ocioso_semana)} por semana ·{' '}
                    {formatarReaisComCentavos(pessoa.custo_hora)}/h
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="projeto">Projeto destino</Label>
                <Select value={projetoId} onValueChange={setProjetoId}>
                  <SelectTrigger id="projeto">
                    <SelectValue placeholder="só atenção ou crítico" />
                  </SelectTrigger>
                  <SelectContent>
                    {destinos.map((p) => (
                      <SelectItem key={p.projeto_id} value={p.projeto_id}>
                        {p.projeto_id} · {p.situacao} · SPI {formatarIndice(p.spi)} · {formatarDias(p.dias_falta_gente)}{' '}
                        de falta de gente
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {pessoa?.papel.includes('sre') && (
                  <p className="text-xs text-muted-foreground">
                    A pessoa é SRE: a lista está ordenada pelos dias que a falta de gente já custou.
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="onboarding">Horas de onboarding</Label>
                <Input
                  id="onboarding"
                  type="number"
                  min={0}
                  step={8}
                  value={horasOnboarding}
                  onChange={(e) => setHorasOnboarding(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  o que a pessoa gasta para entrar no projeto. Padrão: {HORAS_ONBOARDING_PADRAO} h.
                </p>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {!carregando && listaDePessoas.length > 0 && !conta && (
        <Empty>
          <EmptyTitle>Escolha a pessoa e o projeto destino</EmptyTitle>
          <EmptyDescription>
            Com os dois escolhidos a tela mostra as horas no mês, a ociosidade que deixa de ser paga, os dias de
            cronograma recuperados, a mobilização e o saldo.
          </EmptyDescription>
        </Empty>
      )}

      {conta && pessoa && projeto && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
            <Resultado
              titulo="Horas no mês"
              valor={formatarHoras(conta.horasNoMes)}
              explicacao={`${formatarHoras(pessoa.horas_paradas_semana, 1)} paradas por semana x ${SEMANAS_NO_MES} semanas`}
            />
            <Resultado
              titulo="Ociosidade que deixa de ser paga"
              valor={formatarReais(conta.ociosidadeEvitada)}
              explicacao={`${formatarHoras(conta.horasNoMes, 1)} x ${formatarReaisComCentavos(conta.custoHora)}/h`}
              tom="bom"
            />
            <Resultado
              titulo="Dias de cronograma recuperados"
              valor={formatarDias(conta.diasRecuperados, 1)}
              explicacao={`${formatarDias(projeto.dias_falta_gente)} de impacto em ${JANELA_DO_STATUS_EM_DIAS} dias, projetados em ${HORIZONTE_EM_DIAS}`}
              tom="bom"
            />
            <Resultado
              titulo="Mobilização"
              valor={formatarReais(conta.mobilizacao)}
              explicacao={`${formatarHoras(horasOnboarding)} de onboarding x ${formatarReaisComCentavos(conta.custoHora)}/h`}
              tom="ruim"
            />
            <Resultado
              titulo="Saldo"
              valor={formatarReais(conta.saldo)}
              explicacao="ociosidade evitada menos mobilização"
              tom={conta.saldo >= 0 ? 'bom' : 'ruim'}
            />
          </div>

          <Card>
            <CardContent className="pt-6">
              <details className="text-sm">
                <summary className="cursor-pointer font-medium text-foreground">Como essa conta é feita</summary>
                <div className="mt-4 space-y-3 text-muted-foreground">
                  <p>
                    Mover {pessoa.nome} ({pessoa.colaborador_id}, {pessoa.papel} {pessoa.senioridade}) do{' '}
                    {pessoa.projeto_principal} para o {projeto.projeto_id} — {projeto.nome_projeto}.
                  </p>
                  <ol className="list-decimal space-y-2 pl-5">
                    <li>
                      <strong>Horas no mês.</strong> A gold.utilizacao_pessoa_semana diz quantas horas estavam
                      disponíveis e quantas foram apontadas em cada sexta. A diferença são as horas paradas:{' '}
                      {formatarHoras(pessoa.horas_paradas_semana, 1)} por semana, na média das 12 semanas até{' '}
                      {FOTOGRAFIA}. Vezes {SEMANAS_NO_MES} semanas dá {formatarHoras(conta.horasNoMes)} no mês.
                    </li>
                    <li>
                      <strong>Ociosidade que deixa de ser paga.</strong> Essas horas já são pagas hoje e não produzem
                      nada. {formatarHoras(conta.horasNoMes, 1)} x {formatarReaisComCentavos(conta.custoHora)}/h
                      (custo_hora da silver.colaboradores) = {formatarReais(conta.ociosidadeEvitada)}.
                    </li>
                    <li>
                      <strong>Dias de cronograma recuperados.</strong> Os gerentes declaram no status semanal quantos
                      dias cada bloqueio custou, e a IA extrai esse número (gold.status_estruturado). No{' '}
                      {projeto.projeto_id} a falta de gente soma {formatarDias(projeto.dias_falta_gente)} nos últimos{' '}
                      {JANELA_DO_STATUS_EM_DIAS} dias. Tirar a causa não devolve o passado: devolve o ritmo daqui para a
                      frente. Por isso o número é a média diária desse impacto ({formatarDias(projeto.dias_falta_gente)}{' '}
                      ÷ {JANELA_DO_STATUS_EM_DIAS}) projetada nos próximos {HORIZONTE_EM_DIAS} dias ={' '}
                      {formatarDias(conta.diasRecuperados, 1)}.
                    </li>
                    <li>
                      <strong>Mobilização.</strong> Entrar num projeto novo custa horas que também são pagas:{' '}
                      {formatarHoras(horasOnboarding)} x {formatarReaisComCentavos(conta.custoHora)}/h ={' '}
                      {formatarReais(conta.mobilizacao)}. O campo é editável porque 40 h é um palpite razoável, não um
                      número da base.
                    </li>
                    <li>
                      <strong>Saldo.</strong> {formatarReais(conta.ociosidadeEvitada)} −{' '}
                      {formatarReais(conta.mobilizacao)} = {formatarReais(conta.saldo)} no primeiro mês.
                    </li>
                  </ol>
                  <p>
                    O que a conta <em>não</em> diz: se a pessoa tem a competência que o projeto pede, se o cliente
                    aceita a troca e se o {pessoa.projeto_principal} precisa dela de volta. A decisão continua sendo
                    humana — a Torre só põe o preço na mesa.
                  </p>
                </div>
              </details>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
