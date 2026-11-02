Leia o CLAUDE.md da raiz e aulas/aula-04-produtos-de-dados-ia/prd/CLAUDE.md.
Use as skills databricks-apps e databricks-app-design. A gold já existe. O score do modelo (gold.score_estouro_30d)
pode NÃO existir: nenhuma query de config/queries pode depender dele.

1. Confira `databricks apps list --profile ControlTower` (limite de 3 apps no
   Free Edition) e crie o app numa pasta minha-torre/ na raiz deste
   repositório, só com o plugin analytics (o Genie entra no prompt 2):
   databricks apps init --name minha-torre \
     --features analytics \
     --set analytics.sql-warehouse.id=d7331012-899b-4b1d-b5bc-90752af4c322 \
     --run none --profile ControlTower
   O app é um bundle próprio, dentro da pasta do bundle vertice. Acrescente
   ao databricks.yml da RAIZ (o do vertice) sync: { exclude: ["minha-torre/**"] },
   senão o deploy do vertice sobe o node_modules do app inteiro.

2. config/queries (apague os exemplos do template):
   - kpis.sql: projetos em andamento, em risco (atenção + crítico),
     críticos, melancias, estouro previsto e carteira
     (projeto_situacao_atual). Nada do score aqui.
   - projetos_risco.sql: projetos em andamento do pior para o melhor, com
     SPI, CPI, estouro, atraso projetado, farol do gerente × calculado,
     melancia, a causa mais frequente no status_estruturado dos últimos 90
     dias e os dias de impacto por falta_sre e por rotatividade.
   - pessoas_ociosas.sql: pessoas com utilização < 20% nas últimas 12
     semanas (utilizacao_pessoa_semana), com horas paradas e custo ocioso
     MÉDIOS por semana e custo_hora.
   A probabilidade por projeto (gold.score_estouro_30d) vem de uma rota
   GET /api/score-estouro no servidor que responde {disponivel, linhas}:
   se a tabela não existir, a tela mostra "—" em vez de quebrar o build.
   O KPI "alto risco em 30 dias" (faixa_risco = 'alto') sai dessa rota.

3. Telas (português, R$, índices com 2 casas, Number() em tudo que vem do
   warehouse):
   - Projetos em risco: 4 KPIs (em risco, estouro previsto, carteira, alto
     risco em 30 dias) + tabela (situação com cor: crítico vermelho, atenção
     âmbar; farol do gerente com 🍉 quando é melancia; coluna P(estouro)).
   - Simulador: escolher uma pessoa ociosa e um projeto destino (só atenção
     ou crítico; para SRE, ordene pelos dias de falta_sre); mostrar horas no
     mês (× 4 semanas), ociosidade que deixa de ser paga, dias de cronograma
     recuperados (dias de impacto da causa nos últimos 90 dias ÷ 90 × 30),
     mobilização = horas de onboarding (editável, 40) × custo_hora, e saldo.
     Explique a conta num <details>.
   Menu com as duas telas (a terceira, Perguntar, entra no prompt 2).
   Sem cache no createApp. Título "Projeto Farol".

4. npm run typecheck, npm run lint, databricks apps validate.
   Depois: databricks bundle deploy --profile ControlTower (cria o app e o
   service principal). Crie scripts/conceder-acesso.sh (lê o
   service_principal_client_id com apps get e dá USE CATALOG em
   lakehouse_vertice e USE SCHEMA + SELECT na gold e na silver), rode e
   faça databricks apps deploy --profile ControlTower. Me mostre a URL.