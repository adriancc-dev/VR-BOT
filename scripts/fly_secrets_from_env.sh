#!/usr/bin/env bash
# Importa los secrets de Fly.io desde tu archivo .env
# Uso: desde la raíz del proyecto, con fly autenticado en la cuenta NUEVA:
#   bash scripts/fly_secrets_from_env.sh
#
# Requisitos: fly auth login (cuenta nueva), fly launch --no-deploy (o app ya creada)

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "❌ No se encuentra .env en la raíz del proyecto."
  exit 1
fi

echo "📋 Importando variables de .env como secrets en Fly.io..."
# Quitar comentarios y líneas vacías; fly secrets import lee NAME=VALUE por línea
grep -v '^[[:space:]]*#' .env | grep -v '^[[:space:]]*$' | grep '=' | fly secrets import

echo "✅ Secrets importados. Comprueba con: fly secrets list"
echo "   Despliega con: fly deploy"
