import { Card, CardContent, CardHeader, CardTitle } from '@databricks/appkit-ui/react';
import { Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * O appkit-ui não traz card de KPI pronto -- este é composto de Card*.
 *
 * Regra: número nenhum vai para a tela sem unidade, período e fonte. Um "17"
 * solto não é informação; "17 de 41 em andamento · fotografia de 16/10/2026 ·
 * gold.projeto_situacao_atual" é.
 *
 * O estado de carregando NÃO é um retângulo cinza. O warehouse da Free
 * Edition dorme em 10 minutos, e a primeira visita do dia passa um bom tempo
 * esperando -- quatro barras cinza sem explicação parecem um app quebrado.
 * Aqui ele diz, com letra, o que está acontecendo.
 */
export function Kpi({
  titulo,
  valor,
  detalhe,
  fonte,
  acao,
  carregando = false,
  textoDeEspera = 'carregando…',
  tom = 'neutro',
}: {
  titulo: string;
  valor: ReactNode;
  detalhe?: string;
  fonte: string;
  /** Botão opcional de recuperação, para quando o número não pôde ser lido. */
  acao?: ReactNode;
  carregando?: boolean;
  textoDeEspera?: string;
  tom?: 'neutro' | 'alerta' | 'critico';
}) {
  const corDoValor =
    tom === 'critico' ? 'text-destructive' : tom === 'alerta' ? 'text-warning' : 'text-foreground';

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{titulo}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-1">
        {carregando ? (
          <div className="flex h-9 items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            <span>{textoDeEspera}</span>
          </div>
        ) : (
          <div className={`text-3xl font-semibold tabular-nums ${corDoValor}`}>{valor}</div>
        )}
        {detalhe && <p className="text-sm text-muted-foreground">{detalhe}</p>}
        <p className="text-xs text-muted-foreground/80">{fonte}</p>
        {!carregando && acao}
      </CardContent>
    </Card>
  );
}
