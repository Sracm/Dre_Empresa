#!/usr/bin/env bash
set -euo pipefail

# Sempre roda a partir da pasta do projeto
cd "$(dirname "$(readlink -f "$0")")"

VENV_DIR="venv"
[ -d ".venv" ] && [ ! -d "venv" ] && VENV_DIR=".venv"

# Cria o ambiente virtual se ainda não existir
if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Criando ambiente virtual em $VENV_DIR..."
    python3 -m venv "$VENV_DIR" || {
        echo "Erro ao criar o venv. Instale com: sudo apt install python3-venv" >&2
        exit 1
    }
fi

source "$VENV_DIR/bin/activate"

# Instala/atualiza dependências apenas quando o requirements.txt mudar
STAMP="$VENV_DIR/.requirements.stamp"
if [ -f requirements.txt ] && { [ ! -f "$STAMP" ] || [ requirements.txt -nt "$STAMP" ]; }; then
    echo "Instalando dependências..."
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    touch "$STAMP"
fi

echo "Iniciando a aplicação..."
exec python app.py "$@"
