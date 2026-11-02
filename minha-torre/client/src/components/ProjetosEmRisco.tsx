import { useMemo } from 'react';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Empty,
  EmptyDescription,
  EmptyTitle,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  useAnalyticsQuery,
} from '@databricks/appkit-ui/react';
import { Button } from '@databricks/appkit-ui/react';
import { Kpi } from './Kpi';
import { useScoreEstouro } from '../lib/useScoreEstouro';
import {
  FOTOGRAFIA,
  SEM_DADO,
  formatarDias,
  formatarFracaoComoPercent,
  formatarIndice,
  formatarReais,
  formatarReaisCurto,
  paraBooleano,
  paraNumero,
} from '../lib/formatters';

/** crítico vermelho, atenção âmbar -- sempre por token, nunca por hex. */
function Situacao({ situacao }: { situacao: string }) {
  if (situacao === 'critico') return <Badge variant="destructive">crítico</Badge>;
  if (situacao === 'atencao')
    return (
      <Badge variant="outline" className="border-transparent bg-warning text-warning-foreground">
        atenção
      </Badge>
    );
  return <Badge variant="outline">ok</Badge>;
}

/**
 * O farol do gerente ao lado do farol pelo número. Quando o gerente diz
 * verde e o SPI está abaixo de 0,9, é melancia: verde por fora, vermelha por
 * dentro. A melancia é o ponto da tela -- é a mentira ficando visível.
 */
function Farol({ doGerente, calculado, melancia }: { doGerente: string; calculado: string; melancia: boolean }) {
  return (
    <span className="whitespace-nowrap">
      {melancia && <span title="melancia: farol verde com SPI abaixo de 0,9">🍉 </span>}
      <span className={melancia ? 'text-destructive font-medium' : undefined}>{doGerente}</span>
      <span className="text-muted-foreground"> / {calculado}</span>
    </span>
  );
}

/**
 * "12 semana(s) · 57 d". Semana e dia juntos, porque um sem o outro nao
 * responde "quanto esse atraso custou": 57 dias em 12 semanas e um projeto
 * sangrando toda sexta; 57 dias em 1 semana e um evento isolado.
 */
function formatarImpacto(semanas: number | string, dias: number | string) {
  const s = paraNumero(semanas);
  if (s === 0) return 'nenhuma semana';
  return `${s} semana(s) · ${formatarDias(dias)}`;
}

export function ProjetosEmRisco() {
  const semParametros = useMemo(() => ({}), []);
  const kpis = useAnalyticsQuery('kpis', semParametros);
  const projetos = useAnalyticsQuery('projetos_risco', semParametros);

  const resumo = kpis.data?.[0];
  const linhas = projetos.data ?? [];

  const statusWarehouse = kpis.warehouseStatus ?? projetos.warehouseStatus;
  const aquecendo = statusWarehouse !== null && statusWarehouse.state !== 'RUNNING';

  // O score só é buscado DEPOIS que a gold respondeu. Com o warehouse frio
  // a rota do score desistia antes de ele subir e o card mentia dizendo que
  // o modelo não tinha rodado. Esperar o warehouse esquentar resolve.
  const goldRespondeu = !kpis.loading && kpis.error === null;
  const score = useScoreEstouro(goldRespondeu);

  const esperandoWarehouse = aquecendo ? 'ligando o warehouse…' : 'carregando…';

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-foreground">Projetos em risco</h2>
        <p className="text-sm text-muted-foreground">
          SPI ou CPI abaixo de 0,9 é atenção; abaixo de 0,8 é crítico. Fotografia de {FOTOGRAFIA}.
        </p>
      </div>

      {aquecendo && (
        <Alert>
          <AlertTitle>Ligando o warehouse</AlertTitle>
          <AlertDescription>
            O SQL warehouse está {statusWarehouse.state.toLowerCase()} e os números aparecem sozinhos quando ele subir.
            Ele dorme depois de 10 minutos parado, então a primeira visita costuma esperar um ou dois minutos.
          </AlertDescription>
        </Alert>
      )}

      {/* ---------------- Os quatro números ---------------- */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          titulo="Projetos em risco"
          carregando={kpis.loading}
          textoDeEspera={esperandoWarehouse}
          valor={
            resumo ? (
              <>
                {paraNumero(resumo.em_risco)}
                <span className="text-lg font-normal text-muted-foreground"> de {paraNumero(resumo.em_andamento)}</span>
              </>
            ) : (
              SEM_DADO
            )
          }
          detalhe={
            resumo ? `${paraNumero(resumo.criticos)} críticos · ${paraNumero(resumo.melancias)} melancias` : undefined
          }
          fonte={`projetos em andamento · gold.projeto_situacao_atual · ${FOTOGRAFIA}`}
          tom="alerta"
        />
        <Kpi
          titulo="Estouro previsto"
          carregando={kpis.loading}
          textoDeEspera={esperandoWarehouse}
          valor={resumo ? formatarReaisCurto(resumo.estouro_previsto) : SEM_DADO}
          detalhe="EAC menos orçamento, só onde é positivo"
          fonte={`projetos em andamento · gold.projeto_situacao_atual · ${FOTOGRAFIA}`}
          tom="critico"
        />
        <Kpi
          titulo="Carteira"
          carregando={kpis.loading}
          textoDeEspera={esperandoWarehouse}
          valor={resumo ? formatarReaisCurto(resumo.carteira) : SEM_DADO}
          detalhe="valor de contrato dos 60 projetos"
          fonte={`gold.projeto_situacao_atual · ${FOTOGRAFIA}`}
        />
        <Kpi
          titulo="Alto risco em 30 dias"
          carregando={score.carregando}
          textoDeEspera={esperandoWarehouse}
          valor={score.altoRisco30d ?? SEM_DADO}
          /*
            O numero e a contagem de faixa_risco = 'alto' do modelo -- NAO um
            corte de probabilidade. O texto dizia "0,50 ou mais", limiar que o
            codigo nao usa e que o dado nao confirma (a faixa 'alto' deste
            score comeca em 0,988). Descrever a faixa, e nao inventar o corte.
          */
          detalhe={
            score.carregando || score.disponivel
              ? `faixa 'alto' do modelo${resumo ? ` · de ${paraNumero(resumo.em_andamento)} em andamento` : ''}`
              : score.causa === 'sem_tabela'
                ? 'o modelo ainda não publicou o score'
                : 'não foi possível ler o score agora'
          }
          fonte={
            !score.carregando && !score.disponivel && score.causa === 'sem_tabela'
              ? 'gold.score_estouro_30d ausente'
              : `gold.score_estouro_30d · ${FOTOGRAFIA}`
          }
          acao={
            !score.carregando && !score.disponivel && score.causa !== 'sem_tabela' ? (
              <Button variant="outline" size="sm" className="mt-1" onClick={score.recarregar}>
                tentar de novo
              </Button>
            ) : undefined
          }
          tom="critico"
        />
      </div>

      {/* ---------------- A tabela ---------------- */}
      <Card>
        <CardHeader>
          <CardTitle>Do pior para o melhor</CardTitle>
          <p className="text-sm text-muted-foreground">
            Ordenado pelo pior dos dois índices (SPI ou CPI). A causa vem do status semanal lido pela IA, nos últimos 90
            dias.
          </p>
        </CardHeader>
        <CardContent>
          {projetos.error ? (
            <Alert variant="destructive">
              <AlertTitle>Não foi possível ler a gold</AlertTitle>
              <AlertDescription>{projetos.error}</AlertDescription>
            </Alert>
          ) : projetos.loading ? (
            <div className="space-y-2">
              {['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map((linha) => (
                <Skeleton key={linha} className="h-8 w-full" />
              ))}
            </div>
          ) : linhas.length === 0 ? (
            <Empty>
              <EmptyTitle>Nenhum projeto em andamento</EmptyTitle>
              <EmptyDescription>
                Rode o job vertice_farol para reconstruir a gold e recarregue a página.
              </EmptyDescription>
            </Empty>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Projeto</TableHead>
                  <TableHead>Cliente</TableHead>
                  <TableHead>Situação</TableHead>
                  <TableHead className="text-right">SPI</TableHead>
                  <TableHead className="text-right">CPI</TableHead>
                  <TableHead className="text-right">P(est.)</TableHead>
                  <TableHead className="text-right">Estouro</TableHead>
                  <TableHead className="text-right">Atraso</TableHead>
                  <TableHead>Farol ger. / calc.</TableHead>
                  <TableHead>Causa no status (90 d)</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {linhas.map((linha) => {
                  const doScore = score.porProjeto.get(linha.projeto_id);
                  return (
                    <TableRow key={linha.projeto_id}>
                      <TableCell className="font-medium whitespace-nowrap">
                        {linha.projeto_id}
                        <span className="block text-xs text-muted-foreground">{linha.nome_projeto}</span>
                      </TableCell>
                      <TableCell className="text-sm">
                        {linha.cliente}
                        <span className="block text-xs text-muted-foreground">{linha.segmento}</span>
                      </TableCell>
                      <TableCell>
                        <Situacao situacao={linha.situacao} />
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{formatarIndice(linha.spi)}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatarIndice(linha.cpi)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {doScore ? formatarFracaoComoPercent(doScore.prob_estouro_30d, 0) : SEM_DADO}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {paraNumero(linha.estouro_previsto) > 0 ? formatarReais(linha.estouro_previsto) : SEM_DADO}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatarDias(linha.atraso_projetado_dias)}
                      </TableCell>
                      <TableCell className="text-sm">
                        <Farol
                          doGerente={linha.farol_do_gerente}
                          calculado={linha.farol_calculado}
                          melancia={paraBooleano(linha.melancia)}
                        />
                      </TableCell>
                      <TableCell className="whitespace-normal break-words">
                        {linha.causa_mais_frequente ? (
                          <>
                            {linha.causa_mais_frequente}
                            <span className="block text-xs text-muted-foreground">
                              a mais frequente, em {paraNumero(linha.semanas_da_causa)} semana(s)
                            </span>
                            {/*
                              Semanas e dias andam SEMPRE no mesmo par. Antes a
                              linha de cima dizia "7 semana(s)" (da causa mais
                              frequente) e a de baixo "57 d de falta de gente":
                              dois numeros verdadeiros que, juntos, mentiam.
                            */}
                            <span className="block text-xs text-muted-foreground">
                              impacto declarado: {formatarImpacto(linha.semanas_falta_gente, linha.dias_falta_gente)} de
                              falta de gente · {formatarImpacto(linha.semanas_outras_causas, linha.dias_outras_causas)}{' '}
                              de outras causas
                            </span>
                          </>
                        ) : (
                          <span className="text-muted-foreground">sem bloqueio reportado</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
