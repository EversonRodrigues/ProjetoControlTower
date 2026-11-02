#!/usr/bin/env bash
#
# Dá ao app minha-torre acesso de leitura ao lakehouse_vertice.
#
# POR QUE ISTO EXISTE: o app é um USUÁRIO do Unity Catalog -- o
# `bundle deploy` cria um service principal para ele, e esse SP nasce sem
# acesso a nada. O `permission: CAN_USE` do databricks.yml dá acesso ao
# WAREHOUSE, não ao CATÁLOGO. Sem os GRANTs abaixo o build do app falha no
# typegen com INSUFFICIENT_PERMISSIONS e a tela nasce vazia.
#
# QUANDO RODAR: depois do `databricks bundle deploy` (que cria o SP) e antes
# do `databricks apps deploy` (que roda o build lá dentro).
#
# Uso:
#   bash scripts/conceder-acesso.sh [perfil] [nome-do-app]
set -euo pipefail

PERFIL="${1:-ControlTower}"
APP="${2:-minha-torre}"
CATALOGO="lakehouse_vertice"
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Lendo o service principal do app '$APP' (perfil $PERFIL)..."
SP="$(databricks apps get "$APP" --profile "$PERFIL" -o json \
      | python -c 'import json,sys; print(json.load(sys.stdin)["service_principal_client_id"])')"

if [ -z "$SP" ]; then
  echo "ERRO: não achei o service_principal_client_id. O app já foi criado com 'databricks bundle deploy'?" >&2
  exit 1
fi
echo "Service principal: $SP"

SQL="$(mktemp -t conceder-acesso-XXXXXX.sql)"
trap 'rm -f "$SQL"' EXIT

# O SP é identificado pelo client id, com crase. Só leitura: o app não
# escreve nada na gold nem na silver.
cat > "$SQL" <<SQL
GRANT USE CATALOG ON CATALOG ${CATALOGO} TO \`${SP}\`;
GRANT USE SCHEMA ON SCHEMA ${CATALOGO}.gold TO \`${SP}\`;
GRANT SELECT ON SCHEMA ${CATALOGO}.gold TO \`${SP}\`;
-- A silver entra porque o simulador lê o custo/hora em silver.colaboradores.
GRANT USE SCHEMA ON SCHEMA ${CATALOGO}.silver TO \`${SP}\`;
GRANT SELECT ON SCHEMA ${CATALOGO}.silver TO \`${SP}\`;
SQL

# Reusa o run_sql.py da noite 3: ele já trata o split por ';', o polling da
# statement e o encoding cp1252 do Windows.
python "$RAIZ/scripts/run_sql.py" "$SQL" --profile "$PERFIL" --quiet

echo
echo "Pronto. O app '$APP' lê ${CATALOGO}.gold e ${CATALOGO}.silver."
echo "Agora: cd minha-torre && databricks apps deploy --profile $PERFIL"
