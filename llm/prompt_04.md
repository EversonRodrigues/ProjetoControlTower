Continue o bundle na raiz deste repositório. O pipeline, a IA e
as métricas estão prontos. Agora as duas portas para quem não escreve SQL.

1. Dashboard como código
   - scripts/gerar_dashboard.py gera resources/dashboard-portfolio.lvdash.json
     (AI/BI, GRID_V1, queries da gold com nome de tabela PURO, sem catálogo
     nem schema; a silver.entregas_fornecedor vai com o nome completo
     lakehouse_vertice.silver.entregas_fornecedor). Três páginas:
     Portfólio: KPIs da mv_projetos com MEASURE() (carteira, SPI, CPI, estouro
       previsto, projetos em risco, críticos, melancias); barra de estouro
       previsto por projeto colorida por situação (crítico #FF5F46, atenção
       #F6C344, ok #22C2F4); dispersão SPI × CPI; linha de SPI e CPI semanais
       da carteira (SUM(ev)/SUM(pv) por semana no fato_projeto_semana); tabela dos projetos em andamento com o farol
       do gerente ao lado do farol pelo número.
     Pessoas: top 15 pessoas por custo da hora parada (12 semanas), tabela de
       utilização por pessoa e projeto, e barras de causas de bloqueio por
       projeto (status_estruturado, últimos 90 dias).
     Fornecedores: tabela por fornecedor (grafias no cadastro, entregas,
       prazo real ÷ prometido, % no prazo, em atraso hoje) e tabela das
       entregas em atraso hoje, as duas sobre silver.entregas_fornecedor.
     Tema nas cores da Jornada: #0059DB, #22C2F4, fundo #14141A no escuro.
   - resources/dashboard.dashboard.yml: recurso dashboard_portfolio, display
     name "Projeto Farol · Portfólio", dataset_catalog ${var.catalog},
     dataset_schema gold, warehouse ${var.warehouse_id}.
   Antes do deploy, rode cada query do dashboard (prefixando
   lakehouse_vertice.gold. nas tabelas gold) e me mostre a contagem de linhas de cada uma.

2. Genie Agent como código
   - scripts/gerar_genie.py gera resources/farol.geniespace.json
     (serialized_space versão 2; ids de 32 caracteres hex, únicos e em ordem):
     tabelas gold.fato_projeto_semana, gold.projeto_situacao_atual,
     gold.status_estruturado, gold.utilizacao_pessoa_semana e
     silver.entregas_fornecedor, e a metric view gold.mv_projetos; as 4 perguntas do dono como perguntas de
     exemplo; instruções de texto com: quem pergunta (o dono e a diretoria); HOJE =
     2026-10-16 e o que é "últimos 90 dias / 12 semanas / próximo mês"; as
     fórmulas e as regras de corte; mv_projetos para totais de hoje e
     projeto_situacao_atual para ranking; PV/EV/AC acumulados no fato (nunca
     somar semanas); farol e melancia; "por que o projeto X atrasou" responde
     com status_estruturado dos últimos 90 dias (sem sem_bloqueio e
     nao_reportado), mais o SPI e SREs ociosos se a causa for falta_sre;
     gente parada = utilização < 20% em 12 semanas; fornecedor = prazo real ÷
     prometido na silver.entregas_fornecedor; "o que vai dar errado no
     próximo mês" junta as entregas de consultoria em atraso e o change
     freeze de varejo (01/11/2026 a 10/01/2027) nos projetos de e-commerce
     (o modelo de previsão vem na noite 3); "quais clientes" devolve cada
     cliente uma vez. E um exemplo de SQL para
     cada uma das 4 perguntas do dono.
   - resources/genie.genie_space.yml: recurso genie_farol, título
     "Farol · Diretoria".

Rode e me mostre a saída:
  databricks bundle deploy --profile ControlTower
  databricks bundle summary --profile ControlTower
  python3 scripts/genie.py perguntar "Farol · Diretoria" "Tenho gente parada enquanto outro projeto pede gente?" --profile ControlTower
  python3 scripts/genie.py benchmark "Farol · Diretoria" aulas/aula-03-modelagem-claude-code/claude-code/prd/genie-benchmark.json --profile ControlTower
Se o benchmark der menos de 16/20, mostre os erros e ajuste a INSTRUÇÃO
(não a pergunta), gere o JSON, faça deploy e rode de novo.