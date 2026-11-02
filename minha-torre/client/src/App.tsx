import { createBrowserRouter, NavLink, Outlet, RouterProvider } from 'react-router';
import { TooltipProvider } from '@databricks/appkit-ui/react';
import { ProjetosEmRisco } from './components/ProjetosEmRisco';
import { Simulador } from './components/Simulador';
import { FOTOGRAFIA } from './lib/formatters';

/**
 * Projeto Farol · a Torre da Vértice.
 *
 * Duas telas: a lista do que está em risco e o simulador de realocação.
 * A terceira ("Perguntar", o Genie) entra no próximo prompt -- é só mais um
 * item em TELAS e uma rota aqui embaixo.
 */
const TELAS = [
  { para: '/', rotulo: 'Projetos em risco', fim: true },
  { para: '/simulador', rotulo: 'Simulador', fim: false },
];

const classeDaAba = ({ isActive }: { isActive: boolean }) =>
  `px-4 py-3 -mb-px border-b-2 text-sm font-medium transition-colors whitespace-nowrap ${
    isActive
      ? 'border-primary text-foreground'
      : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
  }`;

function Moldura() {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      <header className="border-b">
        <div className="px-4 md:px-6 pt-3">
          <h1 className="text-lg font-semibold text-foreground">Projeto Farol</h1>
          <p className="text-xs text-muted-foreground">
            Vértice Tecnologia · fotografia de {FOTOGRAFIA} · lakehouse_vertice.gold
          </p>
        </div>

        {/*
          As abas ficam numa LINHA PRÓPRIA, embaixo do título, e não no canto
          superior direito: lá elas ficavam escondidas atrás do toast de
          "warehouse warming up" e ninguém achava o Simulador. Duas (em breve
          três) abas cabem em qualquer tela, então não há menu sanduíche.
        */}
        <nav className="px-4 md:px-6 mt-2 flex gap-1 overflow-x-auto border-b-0">
          {TELAS.map((tela) => (
            <NavLink key={tela.para} to={tela.para} end={tela.fim} className={classeDaAba}>
              {tela.rotulo}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="flex-1 p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}

const rotas = createBrowserRouter([
  {
    element: <Moldura />,
    children: [
      { path: '/', element: <ProjetosEmRisco /> },
      { path: '/simulador', element: <Simulador /> },
    ],
  },
]);

export default function App() {
  // O ResourceStatusProvider e o indicador do warehouse já são montados em
  // main.tsx. Montá-los aqui de novo colocava DOIS toasts na tela.
  return (
    <TooltipProvider>
      <RouterProvider router={rotas} />
    </TooltipProvider>
  );
}
