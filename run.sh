#!/bin/bash

echo "Iniciando a aplicação..."

# Ativa o ambiente virtual se ele existir
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Aviso: Ambiente virtual não encontrado. Rodando com o python global do sistema."
fi

# Executa o arquivo principal
python3 app.py
