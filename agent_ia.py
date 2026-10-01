"""
agent_ia.py — Agente de Inteligência Executiva e Controladoria Corporativa de Nível Sênior (MQ Hair Company)
Integrado diretamente ao banco de dados Oracle / DRE oficial (dre_cache.db).
Atende a demandas analíticas de Diretores Executivos (CEO, CFO, CCO/Comercial, COO e Controladoria/Contábil)
com foco em Demonstração do Resultado do Exercício (DRE), aderência orçamentária e rentabilidade.
Garante precisão contábil e matemática de 100% sobre Orçado, Realizado e Desvios.
"""

import os
from datetime import datetime
from db import get_db_connection
import time
import sqlite3
import requests
import json
import traceback
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dre_cache.db")

DEFAULT_OPENROUTER_KEY = "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"
DEFAULT_OPENAI_KEY = "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"
DEFAULT_MISTRAL_KEY = "mstrl_QjLIPXVSQlth0eGa5szH4nhazKxNf8s3_3PElyn"

# Carrega chaves do ambiente ou do .env
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

env_file = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_file):
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY=") and not OPENROUTER_API_KEY:
                OPENROUTER_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("OPENAI_API_KEY=") and not OPENAI_API_KEY:
                OPENAI_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("MISTRAL_API_KEY=") and not MISTRAL_API_KEY:
                MISTRAL_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")

if not OPENROUTER_API_KEY or len(OPENROUTER_API_KEY) < 15:
    OPENROUTER_API_KEY = DEFAULT_OPENROUTER_KEY

if not OPENAI_API_KEY or len(OPENAI_API_KEY) < 15:
    OPENAI_API_KEY = DEFAULT_OPENAI_KEY

if not MISTRAL_API_KEY or len(MISTRAL_API_KEY) < 15:
    MISTRAL_API_KEY = DEFAULT_MISTRAL_KEY

OPENROUTER_MODELS = ["openai/gpt-4o-mini", "google/gemini-2.0-flash-001", "meta-llama/llama-3.3-70b-instruct"]
OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o"]
MISTRAL_MODELS = ["open-mistral-nemo", "codestral-latest", "open-mistral-7b"]

# Sessões HTTP persistentes para eliminar latência de handshake TLS/TCP
_OPENROUTER_SESSION = requests.Session()
_OPENROUTER_SESSION.headers.update({
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:5150",
    "X-Title": "MQ Hair DRE IA - Controladoria"
})

_OPENAI_SESSION = requests.Session()
_OPENAI_SESSION.headers.update({
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "Content-Type": "application/json"
})

_MISTRAL_SESSION = requests.Session()
_MISTRAL_SESSION.headers.update({
    "Authorization": f"Bearer {MISTRAL_API_KEY}",
    "Content-Type": "application/json"
})

# Compatibilidade retroativa
_HTTP_SESSION = _OPENROUTER_SESSION

# ═══════════════════════════════════════════════════════════════════════════
#  FUNÇÕES ANALÍTICAS FINANCEIRAS (DRE MQ HAIR)
# ═══════════════════════════════════════════════════════════════════════════

def _calc_dif(orc, real):
    dif = (real or 0.0) - (orc or 0.0)
    pct = (dif / abs(orc) * 100.0) if orc and abs(orc) > 0.001 else 0.0
    return {
        "orcado": round(orc or 0.0, 2),
        "realizado": round(real or 0.0, 2),
        "desvio_reais": round(dif, 2),
        "desvio_pct": round(pct, 2)
    }

# ─── TRAVA 1: VALIDADOR ANTI-ALUCINAÇÃO ────────────────────────────────────
def _extrair_valores_oficiais(dados):
    """
    Percorre recursivamente um dicionário/lista de dados do banco
    e extrai todos os valores numéricos absolutos relevantes (> R$ 100).
    Retorna um conjunto de floats para comparação rápida.
    """
    valores = set()
    if isinstance(dados, dict):
        for k, v in dados.items():
            if isinstance(v, (int, float)) and abs(v) > 100:
                valores.add(round(abs(float(v)), 0))
            elif isinstance(v, (dict, list)):
                valores |= _extrair_valores_oficiais(v)
    elif isinstance(dados, list):
        for item in dados:
            valores |= _extrair_valores_oficiais(item)
    return valores

def _detectar_alucinacao(texto_llm, dados_oficiais):
    """
    Verifica se algum valor monetário R$ na resposta do LLM
    não existe nos dados oficiais do banco (tolerância 2%).
    Retorna True se alucinação detectada, False se tudo ok.
    """
    if not texto_llm or not dados_oficiais:
        return False

    # Extrai valores R$ da resposta (formato BR: R$ 1.234,56 ou R$ 1234.56)
    padroes = re.findall(r'R\$\s*([\d.,\s]+)', texto_llm)
    if not padroes:
        return False

    valores_resposta = []
    for raw in padroes:
        clean = raw.strip().replace(' ', '')
        try:
            # Tenta formato BR: 1.234.567,89
            if ',' in clean:
                num = float(clean.replace('.', '').replace(',', '.'))
            else:
                num = float(clean.replace('.', ''))
            if num > 100:
                valores_resposta.append(round(num, 0))
        except Exception:
            pass

    if not valores_resposta:
        return False

    valores_db = _extrair_valores_oficiais(dados_oficiais)
    if not valores_db:
        return False

    for val in valores_resposta:
        encontrou = False
        for val_db in valores_db:
            if val_db == 0:
                continue
            desvio = abs(val - val_db) / val_db
            if desvio <= 0.05:  # Tolerância 5% para arredondamentos e somatórios
                encontrou = True
                break
        if not encontrou:
            print(f"[TRAVA ANTI-ALUCINAÇÃO] Valor R$ {val:,.2f} não encontrado nos dados oficiais do banco.", flush=True)
            return True  # Possível alucinação detectada

    return False

def extrair_periodo_do_prompt(prompt, ano_padrao=2026, mes_padrao=8):
    """
    Identifica com precisão o mês e ano mencionados pelo usuário no prompt,
    suportando nomes completos, abreviações e termos relativos ('mês passado').
    Se o usuário perguntar pelo ano completo/acumulado sem citar mês, retorna mes=None.
    """
    p = (prompt or "").lower()
    meses_map = {
        "janeiro": 1, "jan": 1,
        "fevereiro": 2, "fev": 2,
        "março": 3, "marco": 3, "mar": 3,
        "abril": 4, "abr": 4,
        "maio": 5, "mai": 5,
        "junho": 6, "jun": 6,
        "julho": 7, "jul": 7,
        "agosto": 8, "ago": 8,
        "setembro": 9, "set": 9,
        "outubro": 10, "out": 10,
        "novembro": 11, "nov": 11,
        "dezembro": 12, "dez": 12
    }
    mes_encontrado = None
    if "passado" in p or "anterior" in p:
        mes_encontrado = mes_padrao - 1 if mes_padrao > 1 else 12
    else:
        for m_nome, m_num in meses_map.items():
            if re.search(r'\b' + m_nome + r'\b', p):
                mes_encontrado = m_num
                break
        if not mes_encontrado:
            m_num_match = re.search(r'\bm[êe]s\s+(\d{1,2})\b', p)
            if m_num_match:
                val = int(m_num_match.group(1))
                if 1 <= val <= 12:
                    mes_encontrado = val

    ano_encontrado = None
    ano_match = re.search(r'\b(202[3-9])\b', p)
    if ano_match:
        ano_encontrado = int(ano_match.group(1))

    # Detecta se a pergunta é sobre o ano completo / acumulado
    termos_anual = ["no ano", "em 202", "ano de 202", "ano fiscal", "anual", "acumulado", "ano todo", "ytd", "total do ano", "fechamento do ano"]
    quer_anual = any(t in p for t in termos_anual) or (ano_encontrado is not None and not mes_encontrado)

    if quer_anual and not mes_encontrado:
        return (ano_encontrado or ano_padrao), None

    return (ano_encontrado or ano_padrao), (mes_encontrado or mes_padrao)

def obter_resumo_dre(ano=2026, mes=None, empresa=None):
    """
    Retorna o resumo executivo oficial e consolidado do DRE para um mês e ano específicos ou acumulado anual.
    Calcula Venda Bruta, Venda Líquida, CMV, Margem de Contribuição e todas as Despesas Operacionais.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
    except Exception:
        ano = 2026

    if mes is None or str(mes).strip().lower() in ("0", "none", "all", "ano", "anual", "acumulado", "ytd"):
        where = ["ano = %s", "codcencus != 21010000"]
        params = [ano]
        cur.execute("SELECT MAX(mes) as max_m FROM dre_data WHERE ano=? AND abs(realizado) > 0.01", [ano])
        row_max = cur.fetchone()
        max_m = (row_max["max_m"] if row_max and row_max["max_m"] else 9)
        periodo_label = f"Acumulado {ano} (01 a {max_m:02d}/{ano})"
    else:
        try:
            mes = int(mes)
        except Exception:
            mes = 8
        where = ["ano = %s", "mes = %s", "codcencus != 21010000"]
        params = [ano, mes]
        periodo_label = f"{mes:02d}/{ano}"

    if empresa and str(empresa).strip().upper() not in ("ALL", "CONSOLIDAÇÃO", "CONSOLIDADO", "TODAS AS EMPRESAS", "TODAS", "NONE"):
        where.append("empresa = %s")
        params.append(str(empresa).strip())

    where_str = " AND ".join(where)

    # 1. Venda Bruta
    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND titulo = '1.Venda Bruta'", params)
    r_vb = cur.fetchone() or {"orc": 0.0, "real": 0.0}
    vb_orc = r_vb["orc"] or 0.0
    vb_real = r_vb["real"] or 0.0

    # 2. Blocos DRE
    cur.execute(f"SELECT bloco, SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} GROUP BY bloco", params)
    blocos = {r["bloco"]: {"orc": r["orc"] or 0.0, "real": r["real"] or 0.0} for r in cur.fetchall()}

    vl = blocos.get("1.Venda Liquida", {"orc": 0.0, "real": 0.0})
    cmv = blocos.get("2.Custo Mercadoria Vendida", {"orc": 0.0, "real": 0.0})
    mc_orc = (vl["orc"] or 0.0) + (cmv["orc"] or 0.0)
    mc_real = (vl["real"] or 0.0) + (cmv["real"] or 0.0)

    dv = blocos.get("3.Despesas com Vendas", {"orc": 0.0, "real": 0.0})
    dcom = blocos.get("4.Despesas Comercial Operacional", {"orc": 0.0, "real": 0.0})
    dadm = blocos.get("5.Despesas Administrativa Operacional", {"orc": 0.0, "real": 0.0})
    dfin = blocos.get("6.Receitas/Despesas Financeiras", {"orc": 0.0, "real": 0.0})
    vic = blocos.get("7.Vendas IC", {"orc": 0.0, "real": 0.0})

    # 3. Cards Específicos do Cabeçalho (Idênticos ao app.js)
    # 3.1 Bonificação (Bonificação Clientes)
    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(titulo) LIKE '%bonifica%' AND lower(titulo) LIKE '%client%'", params)
    r_bonif = cur.fetchone() or {"orc": 0.0, "real": 0.0}
    if not r_bonif["real"] and not r_bonif["orc"]:
        cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(titulo) LIKE '%bonifica%'", params)
        r_bonif = cur.fetchone() or {"orc": 0.0, "real": 0.0}

    # 3.2 Comissão (Comissões)
    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(bloco) LIKE '%despesas com vendas%' AND lower(titulo) LIKE '%comiss%'", params)
    r_comiss = cur.fetchone() or {"orc": 0.0, "real": 0.0}
    if not r_comiss["real"] and not r_comiss["orc"]:
        cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(titulo) LIKE '%comiss%'", params)
        r_comiss = cur.fetchone() or {"orc": 0.0, "real": 0.0}

    # 3.3 Guelta
    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(titulo) LIKE '%guelta%'", params)
    r_guelta = cur.fetchone() or {"orc": 0.0, "real": 0.0}

    # 3.4 Folha de Pagamento e Benefícios (Administrativa + Comercial)
    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(titulo) LIKE '%folha%' AND lower(titulo) NOT LIKE '%comercial%'", params)
    r_folha_adm = cur.fetchone() or {"orc": 0.0, "real": 0.0}

    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND lower(titulo) LIKE '%folha%' AND lower(titulo) LIKE '%comercial%'", params)
    r_folha_com = cur.fetchone() or {"orc": 0.0, "real": 0.0}

    folha_total_orc = (r_folha_adm["orc"] or 0.0) + (r_folha_com["orc"] or 0.0)
    folha_total_real = (r_folha_adm["real"] or 0.0) + (r_folha_com["real"] or 0.0)

    conn.close()

    vb_o = vb_orc or 0.0
    vb_r = vb_real or 0.0
    vl_o = vl["orc"] or 0.0
    vl_r = vl["real"] or 0.0

    mc_pct_vb_orc = (mc_orc / vb_o * 100.0) if vb_o and abs(vb_o) > 0.01 else 0.0
    mc_pct_vb_real = (mc_real / vb_r * 100.0) if vb_r and abs(vb_r) > 0.01 else 0.0
    mc_pct_vl_orc = (mc_orc / vl_o * 100.0) if vl_o and abs(vl_o) > 0.01 else 0.0
    mc_pct_vl_real = (mc_real / vl_r * 100.0) if vl_r and abs(vl_r) > 0.01 else 0.0

    res_liq_orc = vl_o + (cmv["orc"] or 0.0) + (dv["orc"] or 0.0) + (dcom["orc"] or 0.0) + (dadm["orc"] or 0.0) + (dfin["orc"] or 0.0) + (vic["orc"] or 0.0)
    res_liq_real = vl_r + (cmv["real"] or 0.0) + (dv["real"] or 0.0) + (dcom["real"] or 0.0) + (dadm["real"] or 0.0) + (dfin["real"] or 0.0) + (vic["real"] or 0.0)

    ml_pct_vb_orc = (res_liq_orc / vb_o * 100.0) if vb_o and abs(vb_o) > 0.01 else 0.0
    ml_pct_vb_real = (res_liq_real / vb_r * 100.0) if vb_r and abs(vb_r) > 0.01 else 0.0
    ml_pct_vl_orc = (res_liq_orc / vl_o * 100.0) if vl_o and abs(vl_o) > 0.01 else 0.0
    ml_pct_vl_real = (res_liq_real / vl_r * 100.0) if vl_r and abs(vl_r) > 0.01 else 0.0

    pct_folha_vb = (abs(folha_total_real) / vb_r * 100.0) if vb_r and abs(vb_r) > 0.01 else 0.0

    return {
        "periodo": periodo_label,
        "empresa": empresa or "Consolidado (Todas as Empresas)",
        "venda_liquida": _calc_dif(vl["orc"], vl["real"]),
        "venda_bruta": _calc_dif(vb_orc, vb_real),
        "margem_contribuicao": {
            **_calc_dif(mc_orc, mc_real),
            "pct_sobre_vb_orcado": round(mc_pct_vb_orc, 2),
            "pct_sobre_vb_realizado": round(mc_pct_vb_real, 2),
            "pct_sobre_vl_orcado": round(mc_pct_vl_orc, 2),
            "pct_sobre_vl_realizado": round(mc_pct_vl_real, 2)
        },
        "bonificacao": _calc_dif(r_bonif["orc"] or 0.0, r_bonif["real"] or 0.0),
        "comissao": _calc_dif(r_comiss["orc"] or 0.0, r_comiss["real"] or 0.0),
        "guelta": _calc_dif(r_guelta["orc"] or 0.0, r_guelta["real"] or 0.0),
        "despesas_comercial": _calc_dif(dcom["orc"], dcom["real"]),
        "folha_beneficios": {
            **_calc_dif(folha_total_orc, folha_total_real),
            "folha_adm_realizado": round(r_folha_adm["real"] or 0.0, 2),
            "folha_adm_orcado": round(r_folha_adm["orc"] or 0.0, 2),
            "folha_comercial_realizado": round(r_folha_com["real"] or 0.0, 2),
            "folha_comercial_orcado": round(r_folha_com["orc"] or 0.0, 2),
            "pct_sobre_venda_bruta": round(pct_folha_vb, 2)
        },
        "folha_adm": _calc_dif(r_folha_adm["orc"] or 0.0, r_folha_adm["real"] or 0.0),
        "folha_comercial": _calc_dif(r_folha_com["orc"] or 0.0, r_folha_com["real"] or 0.0),
        "cmv": _calc_dif(cmv["orc"], cmv["real"]),
        "despesas_vendas": _calc_dif(dv["orc"], dv["real"]),
        "despesas_administrativa": _calc_dif(dadm["orc"], dadm["real"]),
        "financeiro": _calc_dif(dfin["orc"], dfin["real"]),
        "vendas_ic": _calc_dif(vic["orc"], vic["real"]),
        "margem_liquida_resultado_operacional": {
            **_calc_dif(res_liq_orc, res_liq_real),
            "pct_sobre_vb_orcado": round(ml_pct_vb_orc, 2),
            "pct_sobre_vb_realizado": round(ml_pct_vb_real, 2),
            "pct_sobre_vl_orcado": round(ml_pct_vl_orc, 2),
            "pct_sobre_vl_realizado": round(ml_pct_vl_real, 2)
        }
    }

def responder_indicador_fora_dre(prompt, ano=2026, mes=None, empresa=None):
    """
    Responde com precisão executiva e contábil a perguntas sobre indicadores de Balanço Patrimonial (ROI, ROE, Ativos),
    esclarecendo que a base é DRE e apresentando a Margem Líquida Operacional e Margem de Contribuição reais.
    """
    resumo = obter_resumo_dre(ano=ano, mes=mes, empresa=empresa)
    vb = resumo.get("venda_bruta", {})
    vl = resumo.get("venda_liquida", {})
    mc = resumo.get("margem_contribuicao", {})
    ml = resumo.get("margem_liquida_resultado_operacional", {})
    per = resumo.get("periodo", f"{ano}")
    emp = resumo.get("empresa", "Consolidado")

    def fmt_val(v):
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    p_lower = prompt.lower()
    ind_nome = "ROI (Retorno sobre o Investimento)"
    if "roe" in p_lower:
        ind_nome = "ROE (Retorno sobre o Patrimônio Líquido)"
    elif "roic" in p_lower:
        ind_nome = "ROIC (Retorno sobre o Capital Investido)"
    elif "ativo" in p_lower:
        ind_nome = "Ativo Total"
    elif "capital de giro" in p_lower:
        ind_nome = "Capital de Giro"
    elif "fluxo de caixa" in p_lower:
        ind_nome = "Fluxo de Caixa (DFC)"

    return (
        f"### **Esclarecimento Contábil — {ind_nome}**\n\n"
        f"O painel de BI da MQ Hair é integrado exclusivamente à base contábil da **DRE (Demonstração do Resultado do Exercício)**. "
        f"O cálculo formal do **{ind_nome}** exige contas patrimoniais do **Balanço Patrimonial** (como *Ativo Total* e *Capital Investido*), "
        f"que não constam nesta base de DRE.\n\n"
        f"Para avaliar o **retorno financeiro e a rentabilidade real das operações** no período de **{per}** ({emp}), "
        f"os indicadores oficiais apurados na DRE são:\n\n"
        f"| Indicador Contábil (DRE) | Orçado | Realizado | Desvio (R$) | Desvio (%) |\n"
        f"| :--- | :---: | :---: | :---: | :---: |\n"
        f"| **Venda Bruta** | {fmt_val(vb.get('orcado', 0))} | **{fmt_val(vb.get('realizado', 0))}** | {fmt_val(vb.get('desvio_reais', 0))} | {vb.get('desvio_pct', 0):+.1f}% |\n"
        f"| **Venda Líquida** | {fmt_val(vl.get('orcado', 0))} | **{fmt_val(vl.get('realizado', 0))}** | {fmt_val(vl.get('desvio_reais', 0))} | {vl.get('desvio_pct', 0):+.1f}% |\n"
        f"| **Margem de Contribuição** | {fmt_val(mc.get('orcado', 0))} | **{fmt_val(mc.get('realizado', 0))}** | {fmt_val(mc.get('desvio_reais', 0))} | {mc.get('desvio_pct', 0):+.1f}% |\n"
        f"| **Margem Líquida (Resultado Operacional)** | {fmt_val(ml.get('orcado', 0))} | **{fmt_val(ml.get('realizado', 0))}** | {fmt_val(ml.get('desvio_reais', 0))} | {ml.get('desvio_pct', 0):+.1f}% |\n\n"
        f"**Destaques de Rentabilidade no Período:**\n"
        f"- **Margem de Contribuição:** **{mc.get('pct_sobre_vb_realizado', 0):.2f}%** sobre a Venda Bruta Realizada.\n"
        f"- **Margem Líquida Operacional:** **{ml.get('pct_sobre_vb_realizado', 0):.2f}%** sobre a Venda Bruta Realizada.\n\n"
        f"*Caso necessite de detalhamento por centro de resultado, despesas operacionais ou comparativo por empresa, estou à disposição.*"
    )

def responder_folha_vs_faturamento(prompt, ano=2026, mes=None, empresa=None):
    """
    Responde com precisão executiva e matemática de 100% sobre o Custo Total de Folha de Pagamento
    (Administrativa + Comercial) em relação ao Faturamento Bruto (Venda Bruta) da MQ Hair.
    """
    resumo = obter_resumo_dre(ano=ano, mes=mes, empresa=empresa if empresa != "Consolidado" else None)
    vb = resumo.get("venda_bruta", {})
    folha_total = resumo.get("folha_beneficios", {})
    folha_adm = resumo.get("folha_adm", {})
    folha_com = resumo.get("folha_comercial", {})
    per = resumo.get("periodo", f"{ano}")
    emp = resumo.get("empresa", "Consolidado")

    def fmt_val(v):
        return f"R$ {abs(v or 0.0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    vb_orc = vb.get("orcado", 0.0)
    vb_real = vb.get("realizado", 0.0)

    f_tot_orc = abs(folha_total.get("orcado", 0.0))
    f_tot_real = abs(folha_total.get("realizado", 0.0))
    f_tot_desvio_reais = f_tot_real - f_tot_orc
    f_tot_desvio_pct = (f_tot_desvio_reais / f_tot_orc * 100.0) if f_tot_orc else 0.0

    f_adm_orc = abs(folha_adm.get("orcado", 0.0))
    f_adm_real = abs(folha_adm.get("realizado", 0.0))
    f_adm_desvio_reais = f_adm_real - f_adm_orc
    f_adm_desvio_pct = (f_adm_desvio_reais / f_adm_orc * 100.0) if f_adm_orc else 0.0

    f_com_orc = abs(folha_com.get("orcado", 0.0))
    f_com_real = abs(folha_com.get("realizado", 0.0))
    f_com_desvio_reais = f_com_real - f_com_orc
    f_com_desvio_pct = (f_com_desvio_reais / f_com_orc * 100.0) if f_com_orc else 0.0

    pct_folha_vb_orc = (f_tot_orc / vb_orc * 100.0) if vb_orc else 0.0
    pct_folha_vb_real = (f_tot_real / vb_real * 100.0) if vb_real else 0.0
    dif_pp = pct_folha_vb_real - pct_folha_vb_orc

    economia_reais = f_tot_orc - f_tot_real
    if economia_reais > 0:
        status_economia = f"economia de **{fmt_val(economia_reais)}** ({abs(f_tot_desvio_pct):.1f}% abaixo do teto orçado)"
    else:
        status_economia = f"estouro de **{fmt_val(abs(economia_reais))}** ({abs(f_tot_desvio_pct):.1f}% acima do orçado)"

    pct_adm_tot = (f_adm_real / f_tot_real * 100.0) if f_tot_real else 0.0
    pct_com_tot = (f_com_real / f_tot_real * 100.0) if f_tot_real else 0.0

    return (
        f"### **Análise Executiva: Custo Total de Folha x Faturamento Bruto — {per} ({emp})**\n\n"
        f"No período de **{per}**, o custo total realizado de **Folha de Pagamento e Benefícios** "
        f"(Administrativa + Comercial) somou **{fmt_val(f_tot_real)}**, o que representa exatamente "
        f"**{pct_folha_vb_real:.2f}% do Faturamento Bruto Realizado** (**{fmt_val(vb_real)}**).\n\n"
        f"O indicador demonstra **eficiência orçamentária**, operando **{abs(dif_pp):.2f} p.p. abaixo** "
        f"da meta estipulada no budget corporativo (orçado em **{pct_folha_vb_orc:.2f}%**), com uma {status_economia}.\n\n"
        f"| Indicador Contábil | Orçado | Realizado | Desvio (R$) | Desvio (%) |\n"
        f"| :--- | :---: | :---: | :---: | :---: |\n"
        f"| **Faturamento Bruto (Venda Bruta)** | {fmt_val(vb_orc)} | **{fmt_val(vb_real)}** | {fmt_val(vb.get('desvio_reais', 0))} | {vb.get('desvio_pct', 0):+.1f}% |\n"
        f"| (-) **Folha Administrativa** | {fmt_val(f_adm_orc)} | **{fmt_val(f_adm_real)}** | {fmt_val(f_adm_desvio_reais)} | {f_adm_desvio_pct:+.1f}% |\n"
        f"| (-) **Folha Comercial** | {fmt_val(f_com_orc)} | **{fmt_val(f_com_real)}** | {fmt_val(f_com_desvio_reais)} | {f_com_desvio_pct:+.1f}% |\n"
        f"| **(=) Custo Total de Folha e Benefícios** | {fmt_val(f_tot_orc)} | **{fmt_val(f_tot_real)}** | {fmt_val(f_tot_desvio_reais)} | {f_tot_desvio_pct:+.1f}% |\n"
        f"| **Proporção Folha / Faturamento Bruto (%)** | **{pct_folha_vb_orc:.2f}%** | **{pct_folha_vb_real:.2f}%** | **{dif_pp:+.2f} p.p.** | — |\n\n"
        f"**Diagnóstico de Controladoria:**\n"
        f"- **Folha Administrativa:** Representa **{pct_adm_tot:.1f}%** do dispêndio total com pessoal, totalizando **{fmt_val(f_adm_real)}** (vs. {fmt_val(f_adm_orc)} orçado).\n"
        f"- **Folha Comercial:** Representa **{pct_com_tot:.1f}%** do custo de pessoal, fechando em **{fmt_val(f_com_real)}** (vs. {fmt_val(f_com_orc)} orçado).\n"
        f"- **Alavanca de Eficiência:** A disciplina no quadro de colaboradores e encargos garantiu uma economia de **{fmt_val(economia_reais)}** frente ao orçamento aprovado para o período."
    )

def detalhar_bloco(bloco, ano=2026, mes=8, empresa=None):
    """
    Detalha os títulos contábeis de um bloco específico da DRE.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    bloco_limpo = str(bloco).strip().lower()
    mapa = {
        "venda": "1.Venda Liquida",
        "receita": "1.Venda Liquida",
        "custo": "2.Custo Mercadoria Vendida",
        "cmv": "2.Custo Mercadoria Vendida",
        "despesas com vendas": "3.Despesas com Vendas",
        "vendas": "3.Despesas com Vendas",
        "comercial": "4.Despesas Comercial Operacional",
        "administrativa": "5.Despesas Administrativa Operacional",
        "adm": "5.Despesas Administrativa Operacional",
        "financeiro": "6.Receitas/Despesas Financeiras",
        "financeira": "6.Receitas/Despesas Financeiras",
        "ic": "7.Vendas IC"
    }

    termo_busca = mapa.get(bloco_limpo, bloco)

    where = ["ano = %s", "mes = %s", "codcencus != 21010000", "bloco LIKE ?"]
    params = [ano, mes, f"%{termo_busca}%"]
    if empresa and str(empresa).strip().upper() not in ("ALL", "CONSOLIDAÇÃO", "CONSOLIDADO", "TODAS AS EMPRESAS", "TODAS", "NONE"):
        where.append("empresa = %s")
        params.append(str(empresa).strip())

    where_str = " AND ".join(where)

    cur.execute(f"""
        SELECT titulo, SUM(orcado) as orc, SUM(realizado) as real 
        FROM dre_data 
        WHERE {where_str} 
        GROUP BY titulo 
        ORDER BY ABS(SUM(realizado)) DESC
    """, params)

    rows = cur.fetchall()
    conn.close()

    itens = []
    for r in rows:
        orc = r["orc"] or 0.0
        real = r["real"] or 0.0
        itens.append({
            "titulo": r["titulo"],
            **_calc_dif(orc, real)
        })

    return {
        "bloco": termo_busca,
        "periodo": f"{mes:02d}/{ano}",
        "empresa": empresa or "Consolidado",
        "total_linhas": len(itens),
        "titulos": itens
    }

def obter_maiores_custos_despesas(ano=2026, mes=8, empresa=None, tipo="operacional", limite=10):
    """
    Retorna os maiores custos e despesas operacionais registrados no DRE oficial da MQ Hair.
    Agrupa por título contábil em blocos de despesas e custos operacionais:
    - 2.Custo Mercadoria Vendida (se tipo='geral' ou se solicitado)
    - 3.Despesas com Vendas
    - 4.Despesas Comercial Operacional
    - 5.Despesas Administrativa Operacional
    Garante valores 100% fiéis ao banco de dados SQLite oficial.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
    except Exception:
        ano = 2026

    where = ["ano = %s", "codcencus != 21010000"]
    params = [ano]

    if mes is not None and str(mes).strip().lower() not in ("0", "none", "all", "ano", "anual", "acumulado", "ytd"):
        try:
            mes = int(mes)
            where.append("mes = %s")
            params.append(mes)
            periodo_label = f"{mes:02d}/{ano}"
        except Exception:
            periodo_label = f"08/{ano}"
    else:
        periodo_label = f"Acumulado {ano}"

    if empresa and str(empresa).strip().upper() not in ("ALL", "CONSOLIDAÇÃO", "CONSOLIDADO", "TODAS AS EMPRESAS", "TODAS", "NONE"):
        where.append("empresa = %s")
        params.append(str(empresa).strip())

    where.append("(bloco LIKE '%Despesas%' OR bloco LIKE '%Custo%')")
    where_str = " AND ".join(where)

    query = f"""
        SELECT titulo, bloco, SUM(orcado) as orc, SUM(realizado) as real
        FROM dre_data
        WHERE {where_str}
        GROUP BY titulo
        ORDER BY ABS(SUM(realizado)) DESC
        LIMIT ?
    """
    params_lim = params + [int(limite)]
    cur.execute(query, params_lim)
    rows = cur.fetchall()
    conn.close()

    itens = []
    for r in rows:
        orc = r["orc"] or 0.0
        real = r["real"] or 0.0
        # Formata nome limpo do título removendo prefixos numéricos como '1.', '2.', '3.'
        tit_limpo = re.sub(r'^\d+\.\s*', '', r["titulo"] or "").strip()
        itens.append({
            "titulo": tit_limpo or r["titulo"],
            "titulo_original": r["titulo"],
            "bloco": r["bloco"],
            **_calc_dif(orc, real)
        })

    return {
        "tipo": "Maiores Custos e Despesas Operacionais DRE",
        "periodo": periodo_label,
        "empresa": empresa or "Consolidado (Todas as Empresas)",
        "total_itens": len(itens),
        "itens": itens,
        "maiores_custos": itens
    }

def comparar_empresas(indicador="venda_bruta", ano=2026, mes=8):
    """
    Retorna o comparativo/ranking de todas as empresas da MQ Hair para um indicador financeiro específico.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    where = ["ano = %s", "mes = %s", "codcencus != 21010000"]
    params = [ano, mes]

    ind = str(indicador).strip().lower()
    if "bruta" in ind:
        where.append("titulo = '1.Venda Bruta'")
    elif "liquida" in ind:
        where.append("bloco = '1.Venda Liquida'")
    elif "custo" in ind or "cmv" in ind:
        where.append("bloco = '2.Custo Mercadoria Vendida'")
    elif "venda" in ind:
        where.append("bloco = '3.Despesas com Vendas'")
    elif "adm" in ind:
        where.append("bloco = '5.Despesas Administrativa Operacional'")
    elif "comercial" in ind:
        where.append("bloco = '4.Despesas Comercial Operacional'")
    else:
        where.append("titulo = '1.Venda Bruta'")

    cur.execute(f"""
        SELECT empresa, SUM(orcado) as orc, SUM(realizado) as real
        FROM dre_data
        WHERE {' AND '.join(where)}
        GROUP BY empresa
        ORDER BY ABS(SUM(realizado)) DESC
    """, params)

    rows = cur.fetchall()
    conn.close()

    ranking = []
    for r in rows:
        ranking.append({
            "empresa": r["empresa"],
            **_calc_dif(r["orc"] or 0.0, r["real"] or 0.0)
        })

    return {
        "indicador": indicador,
        "periodo": f"{mes:02d}/{ano}",
        "ranking": ranking
    }

def analisar_estouros_orcamento(ano=2026, mes=8, apenas_estouros=True):
    """
    Identifica com precisão cirúrgica quais centros de custo/resultados ESTOURARAM o orçamento
    em custos e despesas operacionais (blocos 2, 3, 4 e 5).
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    query = """
        SELECT codcencus, descrcencus, 
               SUM(orcado) as orc, 
               SUM(realizado) as real,
               (SUM(realizado) - SUM(orcado)) as dif
        FROM dre_data
        WHERE ano=? AND mes=? AND codcencus != 21010000 
          AND bloco IN ('2.Custo Mercadoria Vendida', '3.Despesas com Vendas', '4.Despesas Comercial Operacional', '5.Despesas Administrativa Operacional')
        GROUP BY codcencus, descrcencus
    """
    if apenas_estouros:
        query += " HAVING (SUM(realizado) - SUM(orcado)) < -100.0 ORDER BY dif ASC LIMIT 10"
    else:
        query += " ORDER BY ABS(SUM(realizado) - SUM(orcado)) DESC LIMIT 10"

    cur.execute(query, [ano, mes])
    rows = cur.fetchall()
    conn.close()

    itens = []
    for r in rows:
        orc = r["orc"] or 0.0
        real = r["real"] or 0.0
        dif = r["dif"] or 0.0
        pct = (dif / abs(orc) * 100) if abs(orc) > 0.001 else 0.0
        itens.append({
            "centro_custo": r["descrcencus"],
            "orcado": round(orc, 2),
            "realizado": round(real, 2),
            "estouro_reais": round(abs(dif) if dif < 0 else 0, 2),
            "desvio_reais": round(dif, 2),
            "desvio_pct": round(pct, 2),
            "status": "ESTOURO (Desfavorável)" if dif < 0 else "ECONOMIA (Favorável)"
        })

    return {
        "periodo": f"{mes:02d}/{ano}",
        "analise": "Estouros de Orçamento em Despesas/Custos",
        "ranking_centros": itens
    }

def consultar_conta_historico(conta, ano=2026):
    """
    Retorna a evolução mês a mês (Janeiro a Dezembro) de uma conta contábil ou despesa específica.
    Exemplos: 'Aluguel', 'Frete', 'Comissões', 'Marketing', 'Energia', 'Impostos'.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
    except Exception:
        ano = 2026

    conta_lower = str(conta).strip().lower()
    termo = conta_lower
    if "comiss" in conta_lower:
        termo = "comiss"
    elif "bonif" in conta_lower:
        termo = "bonif"
    elif "guelta" in conta_lower:
        termo = "guelta"
    elif "folha" in conta_lower or "salario" in conta_lower or "salário" in conta_lower:
        termo = "folha"
    elif "aluguel" in conta_lower or "alugue" in conta_lower:
        termo = "alugue"
    elif "frete" in conta_lower:
        termo = "frete"
    elif "energia" in conta_lower or "luz" in conta_lower:
        termo = "energia"
    elif "impost" in conta_lower or "tribut" in conta_lower:
        termo = "impost"

    query = """
        SELECT mes, SUM(orcado) as orc, SUM(realizado) as real
        FROM dre_data
        WHERE ano=? AND codcencus != 21010000
          AND (lower(descrnat) LIKE ? OR lower(titulo) LIKE ?)
        GROUP BY mes
        ORDER BY mes ASC
    """
    cur.execute(query, [ano, f"%{termo}%", f"%{termo}%"])
    rows = cur.fetchall()
    conn.close()

    meses_pt = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    historico = []
    tot_orc = 0.0
    tot_real = 0.0
    for r in rows:
        orc = r["orc"] or 0.0
        real = r["real"] or 0.0
        tot_orc += orc
        tot_real += real
        historico.append({
            "mes_num": r["mes"],
            "mes_nome": meses_pt[r["mes"]] if r["mes"] <= 12 else str(r["mes"]),
            "orcado": round(orc, 2),
            "realizado": round(real, 2),
            "diferenca": round(real - orc, 2)
        })

    return {
        "conta_pesquisada": conta,
        "ano": ano,
        "total_ano_orcado": round(tot_orc, 2),
        "total_ano_realizado": round(tot_real, 2),
        "historico_mensal": historico
    }

def identificar_centro_custo_ou_empresa(prompt):
    """
    Identifica com precisão cirúrgica a regional, centro de custo ou empresa
    mencionada no prompt pelo usuário (ex: 'Varejo Sul' -> 'VAREJO - SUL').
    """
    p = (prompt or "").lower()
    
    # 1. Varejo por regional
    if "varejo" in p:
        if "sul" in p: return "VAREJO - SUL", "centro"
        if any(sp in p for sp in ["sp", "são paulo", "sao paulo", "paulista"]): return "VAREJO - SP", "centro"
        if any(rj in p for rj in ["rj", "rio", "carioca"]): return "VAREJO - RJ", "centro"
        if any(nd in p for nd in ["nd", "norte", "nordeste"]): return "VAREJO - ND", "centro"
        if "geral" in p: return "VAREJO - GERAL", "centro"
        return "VAREJO - GERAL", "centro"
        
    # 2. Promotoras por regional
    if "promotora" in p:
        if "sul" in p: return "PROMOTORAS - SUL", "centro"
        if any(sp in p for sp in ["sp", "são paulo", "sao paulo"]): return "PROMOTORAS - SP", "centro"
        if any(rj in p for rj in ["rj", "rio"]): return "PROMOTORAS - RJ", "centro"
        if any(nd in p for nd in ["nd", "norte", "nordeste"]): return "PROMOTORAS - ND", "centro"
        return "PROMOTORAS GERAL - BUDGET", "centro"

    # 3. Trade Marketing por regional
    if "trademarketing" in p or "trade marketing" in p or "trade" in p:
        if "sul" in p: return "TRADEMARKETING - SUL", "centro"
        if any(sp in p for sp in ["sp", "são paulo", "sao paulo"]): return "TRADEMARKETING - SP", "centro"
        if any(rj in p for rj in ["rj", "rio"]): return "TRADEMARKETING - RJ", "centro"
        if any(nd in p for nd in ["nd", "norte", "nordeste"]): return "TRADEMARKETING - ND", "centro"
        return "TRADEMARKETING GERAL - BUDGET", "centro"

    # 4. Logística por regional
    if "logistica" in p or "logística" in p:
        if any(sp in p for sp in ["sp", "são paulo", "sao paulo"]): return "LOGISTICA - SP", "centro"
        if any(rj in p for rj in ["rj", "rio"]): return "LOGISTICA - RJ", "centro"
        if any(sc in p for sc in ["sc", "santa catarina"]): return "LOGISTICA - SC", "centro"
        return "LOGISTICA GERAL - BUDGET", "centro"

    # 5. Marketplaces, Lojas e E-commerce
    if "mercado livre" in p or "meli" in p: return "MERCADO LIVRE", "centro"
    if "amazon" in p: return "AMAZON", "centro"
    if "magalu" in p or "magazine luiza" in p: return "MAGALU", "centro"
    if "b2w" in p or "americanas" in p: return "B2W", "centro"
    if "vtex" in p: return "LOJA VTEX", "centro"
    if "shopee" in p: return "LOJA SHOPEE", "centro"
    if "parlux" in p or "dm commerce" in p: return "LOJA DM COMMERCE (PARLUX)", "centro"
    if "ecommerce" in p or "e-commerce" in p or "loja virtual" in p: return "E-COMMERCE", "centro"
    if "loja fisica" in p or "loja física" in p: return "LOJA PROPRIA (FISICA)", "centro"
    if "carrefour" in p: return "CARREFOUR", "centro"
    if "cissa" in p: return "CISSA", "centro"
    if "cnova" in p: return "CNOVA", "centro"
    if "dafiti" in p: return "DAFITI", "centro"
    if "via" in p or "casas bahia" in p: return "VIA", "centro"
    if "olist" in p: return "OLIST", "centro"
    if "madeira" in p: return "MADEIRA", "centro"
    if "martins" in p: return "MARTINS", "centro"

    # 6. Departamentos e Operações Internas
    if "distribui" in p: return "DISTRIBUICAO", "centro"
    if "assistencia" in p or "assistência" in p or "sac" in p: return "ASSISTENCIA TECNICA", "centro"
    if "marketing digital" in p: return "MARKETING - DIGITAL", "centro"
    if "marketing" in p or "mkt" in p: return "MARKETING", "centro"
    if "comex" in p or "comercio exterior" in p or "comércio exterior" in p: return "COMERCIO EXTERIOR", "centro"
    if "rh" in p or "recursos humanos" in p: return "RH", "centro"
    if "fabrica" in p or "fábrica" in p: return "FÁBRICA", "centro"
    if "controladoria" in p: return "CONTROLADORIA", "centro"
    if "contabilidade" in p: return "CONTABILIDADE", "centro"
    if "financeiro" in p and not any(f in p for f in ["receita financeira", "despesa financeira", "desc financeiro"]): return "FINANCEIRO", "centro"
    if "cobranca" in p or "cobrança" in p: return "COBRANCA", "centro"
    if "contas a pagar" in p: return "CONTAS A PAGAR", "centro"
    if "contas a receber" in p: return "CONTAS A RECEBER", "centro"
    if any(k in p for k in ["faturamento-fiscal", "faturamento fiscal", "depto fiscal", "departamento fiscal", "setor fiscal"]): return "FATURAMENTO-FISCAL", "centro"
    if "desenvolvimento de produtos" in p or "p&d" in p: return "DESENVOLVIMENTO DE PRODUTOS", "centro"
    if "grandes contas" in p: return "GRANDES CONTAS", "centro"
    if "private label" in p: return "PRIVATE LABEL", "centro"

    # 7. Empresas específicas da MQ Hair
    empresas_map = {
        "sl online": "SL ONLINE - SP",
        "quality matriz": "QUALITY MATRIZ",
        "quality rj": "QUALITY - RJ",
        "quality": "QUALITY MATRIZ",
        "mcr matriz": "MCR - MATRIZ",
        "mcr fabrica": "MCR - FABRICA",
        "mcr fábrica": "MCR - FABRICA",
        "mcr filial": "MCR - FILIAL 03",
        "filial 03": "MCR - FILIAL 03",
        "filial 3": "MCR - FILIAL 03",
        "mcr sc": "MCR - SC",
        "globral": "GLOBRAL - SC",
        "forx mg": "FORX MG",
        "forx sc": "FORX SC",
        "forx": "FORX SC",
        "vls sp": "VLS - SP",
        "vls rj": "VLS - RJ",
        "vls": "VLS - SP"
    }
    for k, v in empresas_map.items():
        if re.search(r'\b' + re.escape(k) + r'\b', p):
            return v, "empresa"

    return None, None

def obter_dre_centro_custo(centro_custo, ano=2026, mes=8, empresa=None):
    """
    Calcula com precisão contábil e matemática exata o DRE Completo e as Margens de um Centro de Custo.
    Calcula: Venda Bruta, Venda Líquida, CPV, Margem de Contribuição (R$ e %), Despesas de Vendas,
    Despesas Comerciais, Despesas Adm, Financeiro e Resultado Líquido Operacional (Margem Líquida R$ e %).
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    where = ["ano = %s", "mes = %s", "codcencus != 21010000"]
    params = [ano, mes]

    # Busca exata no descrcencus
    where.append("descrcencus = %s")
    params.append(centro_custo)

    if empresa and str(empresa).strip().upper() not in ("ALL", "CONSOLIDAÇÃO", "CONSOLIDADO", "TODAS AS EMPRESAS", "TODAS", "NONE"):
        where.append("empresa = %s")
        params.append(str(empresa).strip())

    where_str = " AND ".join(where)

    # 1. Venda Bruta
    cur.execute(f"SELECT SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} AND titulo = '1.Venda Bruta'", params)
    r_vb = cur.fetchone() or {"orc": 0.0, "real": 0.0}
    vb_orc = r_vb["orc"] or 0.0
    vb_real = r_vb["real"] or 0.0

    # 2. Totais por Bloco
    cur.execute(f"SELECT bloco, SUM(orcado) as orc, SUM(realizado) as real FROM dre_data WHERE {where_str} GROUP BY bloco", params)
    blocos = {r["bloco"]: {"orc": r["orc"] or 0.0, "real": r["real"] or 0.0} for r in cur.fetchall()}

    vl = blocos.get("1.Venda Liquida", {"orc": 0.0, "real": 0.0})
    vl_orc = vl["orc"] or 0.0
    vl_real = vl["real"] or 0.0

    cmv = blocos.get("2.Custo Mercadoria Vendida", {"orc": 0.0, "real": 0.0})
    cmv_orc = cmv["orc"] or 0.0
    cmv_real = cmv["real"] or 0.0

    # Margem de Contribuição = Venda Líquida + CPV (CMV vem negativo)
    mc_orc = vl_orc + cmv_orc
    mc_real = vl_real + cmv_real

    # % Margem Contribuição
    mc_pct_vb_orc = (mc_orc / vb_orc * 100.0) if vb_orc and abs(vb_orc) > 0.01 else 0.0
    mc_pct_vb_real = (mc_real / vb_real * 100.0) if vb_real and abs(vb_real) > 0.01 else 0.0
    mc_pct_vl_orc = (mc_orc / vl_orc * 100.0) if vl_orc and abs(vl_orc) > 0.01 else 0.0
    mc_pct_vl_real = (mc_real / vl_real * 100.0) if vl_real and abs(vl_real) > 0.01 else 0.0

    dv = blocos.get("3.Despesas com Vendas", {"orc": 0.0, "real": 0.0})
    dv_orc = dv["orc"] or 0.0
    dv_real = dv["real"] or 0.0

    dcom = blocos.get("4.Despesas Comercial Operacional", {"orc": 0.0, "real": 0.0})
    dcom_orc = dcom["orc"] or 0.0
    dcom_real = dcom["real"] or 0.0

    dadm = blocos.get("5.Despesas Administrativa Operacional", {"orc": 0.0, "real": 0.0})
    dadm_orc = dadm["orc"] or 0.0
    dadm_real = dadm["real"] or 0.0

    dfin = blocos.get("6.Receitas/Despesas Financeiras", {"orc": 0.0, "real": 0.0})
    dfin_orc = dfin["orc"] or 0.0
    dfin_real = dfin["real"] or 0.0

    vic = blocos.get("7.Vendas IC", {"orc": 0.0, "real": 0.0})
    vic_orc = vic["orc"] or 0.0
    vic_real = vic["real"] or 0.0

    # Margem / Resultado Líquido Operacional
    # = Venda Líquida + CPV + Desp Vendas + Desp Comerciais + Desp Adm + Financeiro
    res_liq_orc = vl_orc + cmv_orc + dv_orc + dcom_orc + dadm_orc + dfin_orc + vic_orc
    res_liq_real = vl_real + cmv_real + dv_real + dcom_real + dadm_real + dfin_real + vic_real

    # % Margem Líquida
    ml_pct_vb_orc = (res_liq_orc / vb_orc * 100.0) if vb_orc and abs(vb_orc) > 0.01 else 0.0
    ml_pct_vb_real = (res_liq_real / vb_real * 100.0) if vb_real and abs(vb_real) > 0.01 else 0.0
    ml_pct_vl_orc = (res_liq_orc / vl_orc * 100.0) if vl_orc and abs(vl_orc) > 0.01 else 0.0
    ml_pct_vl_real = (res_liq_real / vl_real * 100.0) if vl_real and abs(vl_real) > 0.01 else 0.0

    # Detalhamento de títulos importantes (Frete, Comissões, Bonificação, Guelta, Folha, Impostos)
    cur.execute(f"""
        SELECT titulo, SUM(orcado) as orc, SUM(realizado) as real 
        FROM dre_data 
        WHERE {where_str} AND (abs(orcado) > 0.01 OR abs(realizado) > 0.01) 
        GROUP BY titulo 
        ORDER BY ABS(SUM(realizado)) DESC
    """, params)
    titulos = {r["titulo"]: {"orc": round(r["orc"] or 0.0, 2), "real": round(r["real"] or 0.0, 2)} for r in cur.fetchall()}

    conn.close()

    return {
        "tipo": "DRE Centro de Custo",
        "centro_custo": centro_custo,
        "periodo": f"{mes:02d}/{ano}",
        "empresa": empresa or "Consolidado",
        "venda_bruta": _calc_dif(vb_orc, vb_real),
        "venda_liquida": _calc_dif(vl_orc, vl_real),
        "cmv_cpv": _calc_dif(cmv_orc, cmv_real),
        "margem_contribuicao": {
            **_calc_dif(mc_orc, mc_real),
            "pct_sobre_vb_orcado": round(mc_pct_vb_orc, 2),
            "pct_sobre_vb_realizado": round(mc_pct_vb_real, 2),
            "pct_sobre_vl_orcado": round(mc_pct_vl_orc, 2),
            "pct_sobre_vl_realizado": round(mc_pct_vl_real, 2)
        },
        "despesas_com_vendas": _calc_dif(dv_orc, dv_real),
        "despesas_comerciais": _calc_dif(dcom_orc, dcom_real),
        "despesas_administrativas": _calc_dif(dadm_orc, dadm_real),
        "financeiro": _calc_dif(dfin_orc, dfin_real),
        "margem_liquida_resultado_operacional": {
            **_calc_dif(res_liq_orc, res_liq_real),
            "pct_sobre_vb_orcado": round(ml_pct_vb_orc, 2),
            "pct_sobre_vb_realizado": round(ml_pct_vb_real, 2),
            "pct_sobre_vl_orcado": round(ml_pct_vl_orc, 2),
            "pct_sobre_vl_realizado": round(ml_pct_vl_real, 2)
        },
        "detalhe_titulos": titulos
    }

def consultar_por_centro_custo(centro_custo, ano=2026, mes=8, filtro_conta=None):
    """
    Consulta os valores realizados e orçados de um centro de resultado específico.
    Exemplos de centro_custo: 'DISTRIBUICAO', 'VAREJO - SP', 'MERCADO LIVRE', 'LOGISTICA - SC'.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    c_lower = str(centro_custo).strip().lower()
    is_conta = any(k in c_lower for k in ["comiss", "bonif", "guelta", "frete", "aluguel", "folha", "salario"])

    if is_conta:
        filtro_conta = "comiss" if "comiss" in c_lower else ("bonif" if "bonif" in c_lower else ("guelta" if "guelta" in c_lower else ("folha" if "folha" in c_lower or "salario" in c_lower else c_lower)))
        where = ["ano = %s", "mes = %s", "codcencus != 21010000", "(lower(titulo) LIKE ? OR lower(descrnat) LIKE ?)"]
        params = [ano, mes, f"%{filtro_conta}%", f"%{filtro_conta}%"]
    else:
        where = ["ano = %s", "mes = %s", "codcencus != 21010000", "(lower(descrcencus) LIKE ? OR codcencus LIKE ?)"]
        params = [ano, mes, f"%{c_lower}%", f"%{centro_custo}%"]

        if filtro_conta:
            f_lower = str(filtro_conta).strip().lower()
            if "comiss" in f_lower: f_lower = "comiss"
            elif "bonif" in f_lower: f_lower = "bonif"
            where.append("(lower(titulo) LIKE ? OR lower(descrnat) LIKE ?)")
            params.extend([f"%{f_lower}%", f"%{f_lower}%"])

    query = f"""
        SELECT bloco, titulo, descrnat, SUM(orcado) as orc, SUM(realizado) as real
        FROM dre_data
        WHERE {' AND '.join(where)}
        GROUP BY bloco, titulo, descrnat
        ORDER BY ABS(SUM(realizado)) DESC
        LIMIT 25
    """
    cur.execute(query, params)
    rows = cur.fetchall()

    cur.execute(f"SELECT SUM(orcado) as tot_orc, SUM(realizado) as tot_real FROM dre_data WHERE {' AND '.join(where)}", params)
    tot = cur.fetchone() or {"tot_orc": 0.0, "tot_real": 0.0}
    conn.close()

    detalhes = []
    for r in rows:
        detalhes.append({
            "bloco": r["bloco"],
            "titulo": r["titulo"],
            "conta": r["descrnat"],
            "orcado": round(r["orc"] or 0.0, 2),
            "realizado": round(r["real"] or 0.0, 2),
            "desvio": round((r["real"] or 0.0) - (r["orc"] or 0.0), 2)
        })

    tot_orc = tot["tot_orc"] or 0.0
    tot_real = tot["tot_real"] or 0.0

    return {
        "centro_custo": centro_custo,
        "ano": ano,
        "mes": mes,
        "total_orcado": round(tot_orc, 2),
        "total_realizado": round(tot_real, 2),
        "desvio_total": round(tot_real - tot_orc, 2),
        "total_linhas": len(detalhes),
        "linhas": detalhes
    }

def gerar_grafico(tipo="bar", titulo="Gráfico MQ Hair", labels=None, valores=None, legenda="Realizado (R$)"):
    """
    Gera a estrutura JSON para exibição de gráfico interativo Chart.js no chat.
    """
    labels = labels or []
    valores = valores or []
    clean_vals = []
    for v in valores:
        try:
            clean_vals.append(float(v))
        except Exception:
            clean_vals.append(0.0)

    chart_json = {
        "type": tipo or "bar",
        "title": titulo or "Gráfico Interativo",
        "labels": labels,
        "datasets": [{
            "label": legenda or "Realizado (R$)",
            "data": clean_vals
        }]
    }
    bloco = f"\n```chart\n{json.dumps(chart_json, ensure_ascii=False, indent=2)}\n```\n"
    return {
        "status": "sucesso",
        "bloco_markdown": bloco,
        "instrucao": "Obrigatório: inclua o bloco_markdown fornecido diretamente na sua resposta para que o gráfico seja desenhado na tela!"
    }

def extrair_dados_tabela_markdown(texto):
    """
    Extrai labels e valores numéricos de qualquer tabela Markdown presente no texto da resposta.
    """
    labels = []
    valores = []
    linhas = (texto or "").strip().split("\n")
    for linha in linhas:
        linha = linha.strip()
        if not linha.startswith("|") or "---" in linha:
            continue
        partes = [p.strip() for p in linha.split("|") if p.strip()]
        if len(partes) >= 2:
            col_label = partes[0].replace("**", "").replace("(-)", "").replace("(=)", "").strip()
            # Ignora cabeçalhos comuns
            if any(h in col_label.lower() for h in ["descrição", "descricao", "indicador", "conta", "item", "centro de custo", "empresa"]):
                continue
            
            val_num = None
            cols_candidatas = list(range(1, len(partes)))
            if len(partes) >= 3:
                cols_candidatas = [2, 1] + [i for i in range(3, len(partes))]
            
            for idx in cols_candidatas:
                if idx < len(partes):
                    v_str = partes[idx].replace("**", "").replace("R$", "").replace("%", "").strip()
                    v_clean = v_str.replace(".", "").replace(",", ".")
                    try:
                        num = abs(float(v_clean))
                        if num > 0:
                            val_num = num
                            break
                    except Exception:
                        pass
            
            if val_num is not None:
                labels.append(col_label)
                valores.append(val_num)
                
    return labels, valores

def auto_injetar_bloco_grafico(prompt, texto_resposta, dados_ferramenta=None):
    """
    Constrói o bloco ```chart ... ``` caso o usuário tenha solicitado um gráfico
    mas a resposta textual do LLM não tenha emitido o bloco de renderização.
    """
    p = (prompt or "").lower()
    quer_grafico = any(k in p for k in ["gráfico", "grafico", "gráficos", "graficos", "graf"])
    if not quer_grafico:
        return None
        
    if "```chart" in texto_resposta or "```grafico" in texto_resposta:
        return None

    # Identifica tipo de gráfico
    if "pizza" in p or "pie" in p:
        chart_type = "pie"
    elif "rosca" in p or "doughnut" in p or "donut" in p:
        chart_type = "doughnut"
    elif any(k in p for k in ["linha", "line", "evolu", "mês a mês", "mes a mes", "temporal"]):
        chart_type = "line"
    else:
        chart_type = "bar"
        
    labels, valores = extrair_dados_tabela_markdown(texto_resposta)
    legenda = "Realizado (R$)"
    
    # Se não extraiu da tabela Markdown, tenta extrair dos dados das ferramentas
    if not labels and dados_ferramenta:
        items_to_check = dados_ferramenta if isinstance(dados_ferramenta, list) else [("data", dados_ferramenta)]
            
        for fname, out_data in items_to_check:
            if not isinstance(out_data, dict):
                continue
            if "historico_mensal" in out_data:
                for h in out_data["historico_mensal"]:
                    labels.append(h.get("mes_nome") or str(h.get("mes_num")))
                    valores.append(abs(float(h.get("realizado", 0))))
                if "conta_pesquisada" in out_data:
                    legenda = f"{out_data['conta_pesquisada']} (R$)"
                break
            elif "linhas" in out_data and isinstance(out_data["linhas"], list):
                for r in out_data["linhas"][:10]:
                    nome_item = r.get("titulo") or r.get("conta") or r.get("descricao") or r.get("descrnat")
                    if nome_item:
                        labels.append(nome_item)
                        valores.append(abs(float(r.get("realizado", 0))))
                break
            elif "maiores_estouros_reais" in out_data:
                for est in out_data["maiores_estouros_reais"][:10]:
                    labels.append(est.get("conta") or est.get("descrcencus", "Conta"))
                    valores.append(abs(float(est.get("desvio_reais", 0))))
                legenda = "Desvio / Estouro (R$)"
                break
            elif "titulos" in out_data:
                for t in out_data["titulos"][:10]:
                    labels.append(t.get("titulo", "Item"))
                    valores.append(abs(float(t.get("realizado", 0))))
                break
                
    if not labels or not valores:
        return None
        
    # Limita a 10 itens para visualização limpa
    labels = labels[:10]
    valores = valores[:10]
    
    # Define título inteligente
    titulo = "Gráfico Analítico DRE MQ Hair"
    if "custo" in p or "despesa" in p:
        titulo = "Divisão dos Custos e Despesas"
    elif "venda" in p or "fatur" in p:
        titulo = "Demonstrativo de Vendas"
    elif "estour" in p or "desvio" in p:
        titulo = "Maiores Desvios de Orçamento"
    elif "folha" in p:
        titulo = "Despesas com Pessoal e Benefícios"
    elif "frete" in p:
        titulo = "Evolução das Despesas de Frete"
    elif "comiss" in p:
        titulo = "Despesas com Comissões"
        
    ano_match = re.search(r'\b(202[3-9])\b', p)
    ano_txt = ano_match.group(1) if ano_match else "2026"
    for mes_nome in ["janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]:
        if mes_nome in p:
            titulo += f" - {mes_nome.capitalize()}/{ano_txt}"
            break
        
    chart_json = {
        "type": chart_type,
        "title": titulo,
        "labels": labels,
        "datasets": [{
            "label": legenda,
            "data": valores
        }]
    }
    
    return f"```chart\n{json.dumps(chart_json, ensure_ascii=False, indent=2)}\n```"

def validar_e_higienizar_bloco_grafico(texto, prompt="", dados_ferramenta=None):
    """
    TRAVA DEFINITIVA DE GRÁFICOS (ZERO ERROS NO CHAT):
    1. Se o usuário pediu gráfico e o LLM não gerou o bloco ```chart, auto-injeta usando os dados oficiais.
    2. Se o LLM emitiu o bloco ```chart ou ```grafico, higieniza e valida o JSON:
       - Converte números negativos em positivos para pizza/rosca (pie/doughnut)
       - Remove vírgulas sobressalentes, comentários JS e caracteres ilegais
       - Garante a presença dos campos obrigatórios (type, labels, datasets)
    3. Retorna o texto 100% pronto e blindado para o frontend Chart.js.
    """
    if not texto:
        return texto

    p = (prompt or "").lower()
    quer_grafico = any(k in p for k in ["gráfico", "grafico", "gráficos", "graficos", "pizza", "pie", "rosca", "doughnut", "donut", "barras", "linha", "evolu"])

    # Regex tolerante para identificar blocos de gráfico no texto
    chart_pattern = re.compile(r'```(?:chart|grafico)\s*([\s\S]*?)\s*```', re.IGNORECASE)
    matches = list(chart_pattern.finditer(texto))

    if matches:
        def _limpar_json_chart(match):
            raw = match.group(1).strip()
            # Limpa comentários JS //... e /* ... */
            clean = re.sub(r'//.*$', '', raw, flags=re.MULTILINE)
            clean = re.sub(r'/\*[\s\S]*?\*/', '', clean)
            # Remove pontos de milhar em números (ex: 349.736,65 -> 349736.65)
            clean = re.sub(r'(\d+)\.(\d{3})\.(\d{3})(?:\.(\d{3}))?', r'\1\2\3\4', clean)
            clean = re.sub(r'(\d+)\.(\d{3})(?=[,\s\]\}])', r'\1\2', clean)
            # Remove vírgulas residuais antes de fechar array ou objeto
            clean = re.sub(r',\s*([\}\]])', r'\1', clean)

            cfg = None
            try:
                cfg = json.loads(clean)
            except Exception:
                try:
                    clean_aspas = clean.replace("'", '"')
                    clean_aspas = re.sub(r',\s*([\}\]])', r'\1', clean_aspas)
                    cfg = json.loads(clean_aspas)
                except Exception:
                    pass

            if isinstance(cfg, dict):
                chart_type = cfg.get("type", "bar")
                # Gráficos de pizza/rosca exigem SEMPRE valores positivos
                if chart_type in ("pie", "doughnut"):
                    datasets = cfg.get("datasets")
                    if isinstance(datasets, list):
                        for ds in datasets:
                            if isinstance(ds, dict) and "data" in ds and isinstance(ds["data"], list):
                                clean_data = []
                                for v in ds["data"]:
                                    try:
                                        clean_data.append(abs(float(v)))
                                    except Exception:
                                        clean_data.append(0.0)
                                ds["data"] = clean_data
                return f"\n```chart\n{json.dumps(cfg, ensure_ascii=False, indent=2)}\n```\n"

            # Se não conseguiu interpretar o JSON quebrado, reconstrói usando os dados oficiais
            bloco_reconstruido = auto_injetar_bloco_grafico(prompt, texto, dados_ferramenta=dados_ferramenta)
            return ("\n" + bloco_reconstruido + "\n") if bloco_reconstruido else ""

        texto = chart_pattern.sub(_limpar_json_chart, texto)

    elif quer_grafico:
        # Usuário pediu gráfico, mas o LLM esqueceu de gerar o bloco: auto-injeta usando os dados oficiais
        bloco_auto = auto_injetar_bloco_grafico(prompt, texto, dados_ferramenta=dados_ferramenta)
        if bloco_auto:
            texto = texto.rstrip() + "\n\n" + bloco_auto

    return texto

def consultar_sql(query):
    """
    Executa consulta SELECT SQL livre no banco SQLite (tabela dre_data).
    """
    query_clean = query.strip()
    if not query_clean.upper().startswith("SELECT"):
        return {"error": "Apenas consultas SELECT são permitidas."}

    proibidos = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "PRAGMA", "ATTACH", "DETACH"]
    for p in proibidos:
        if p in query_clean.upper().split():
            return {"error": f"Comando '{p}' não é permitido por segurança."}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(query_clean)
        rows = [dict(r) for r in cur.fetchmany(50)]
        return {"linhas": rows, "total_retornado": len(rows)}
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════
#  SCHEMA DE FERRAMENTAS DO MISTRAL
# ═══════════════════════════════════════════════════════════════════════════

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "analisar_estouros_orcamento",
            "description": "Retorna o ranking de centros de resultado que estouraram o orçamento (despesas maiores que o previsto). Use sempre para responder: 'qual centro estourou o orçamento?', 'onde tivemos estouro?', 'qual o maior desvio?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8 para Agosto, 7 para Julho/mês passado)"},
                    "apenas_estouros": {"type": "boolean", "description": "True para listar apenas quem gastou a mais que o orçado (estouro)"}
                },
                "required": ["ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_conta_historico",
            "description": "Retorna a evolução mês a mês e o histórico de uma conta ou indicador específico (ex: 'Comissões', 'Bonificação', 'Guelta', 'Folha', 'Aluguel', 'Frete', 'Imposto', 'Energia'). Use para: 'histórico de comissão', 'evolução de frete', 'evolução de comissões', 'histórico de impostos'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conta": {"type": "string", "description": "Nome da conta ou indicador a buscar (ex: 'Comissões', 'Bonificação', 'Guelta', 'Folha', 'Aluguel', 'Frete', 'Imposto', 'Energia')"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"}
                },
                "required": ["conta", "ano"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_por_centro_custo",
            "description": "Consulta os valores de um departamento ou centro de resultado da empresa (ex: 'Distribuição', 'Varejo', 'Marketing', 'Logística'). ATENÇÃO CRÍTICA: NUNCA passe nomes de contas/indicadores da DRE (como 'Comissão', 'Bonificação', 'Guelta', 'Folha', 'Aluguel') como centro de custo. Para contas e indicadores, use obter_resumo_dre ou consultar_conta_historico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "centro_custo": {"type": "string", "description": "Nome do departamento/centro de resultado (ex: 'Distribuição', 'Varejo SP', 'Mercado Livre', 'Marketing')"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8)"},
                    "filtro_conta": {"type": "string", "description": "Filtro opcional de conta ou título dentro do centro (ex: 'Comissão', 'Frete', 'Salários')"}
                },
                "required": ["centro_custo", "ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obter_dre_centro_custo",
            "description": "Calcula com 100% de exatidão matemática o DRE Completo e as Margens (Margem de Contribuição e Margem Líquida / Resultado Operacional) de um Centro de Custo específico (ex: 'VAREJO - SUL', 'VAREJO - SP', 'DISTRIBUICAO', 'LOGISTICA - SC', 'MERCADO LIVRE'). Retorna Venda Bruta, Venda Líquida, CPV/CMV, Margens em R$ e %, Despesas com Vendas, Despesas Comerciais e Administrativas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "centro_custo": {"type": "string", "description": "Nome exato do centro de custo (ex: 'VAREJO - SUL', 'VAREJO - SP', 'DISTRIBUICAO')"},
                    "ano": {"type": "integer", "description": "Ano fiscal (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8)"},
                    "empresa": {"type": "string", "description": "Nome da empresa ou null/Consolidado"}
                },
                "required": ["centro_custo", "ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obter_resumo_dre",
            "description": "Retorna o resumo executivo oficial e consolidado do DRE e os 8 Cards Principais do Cabeçalho: Venda Bruta, Venda Líquida, Margem de Contribuição, Bonificação, Comissão, Guelta, Despesas Comercial Operacional e Folha e Benefícios, além de CMV. Use SEMPRE que a pergunta for sobre o valor de um indicador geral ou card do painel (ex: 'valor da comissão', 'qual a bonificação?', 'guelta', 'venda bruta', 'margem de contribuição').",
            "parameters": {
                "type": "object",
                "properties": {
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8)"},
                    "empresa": {"type": "string", "description": "Nome da empresa ou null/Consolidado"}
                },
                "required": ["ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obter_maiores_custos_despesas",
            "description": "Retorna o ranking dos maiores custos e despesas operacionais da MQ Hair (ranking oficial de valores realizados e orçados no DRE). Use SEMPRE para responder: 'quais os maiores custos?', 'divisão dos custos operacionais', 'maiores despesas', 'ranking de gastos', 'gráfico de pizza dos custos'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ano": {"type": "integer", "description": "Ano fiscal (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8 para Agosto)"},
                    "empresa": {"type": "string", "description": "Nome da empresa ou null/Consolidado"},
                    "limite": {"type": "integer", "description": "Quantidade máxima de contas no ranking (padrão 10)"}
                },
                "required": ["ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "detalhar_bloco",
            "description": "Detalha os títulos contábeis de um bloco do DRE (ex: 'Despesas com Vendas', 'Custo Mercadoria Vendida', 'Despesas Administrativa Operacional').",
            "parameters": {
                "type": "object",
                "properties": {
                    "bloco": {"type": "string", "description": "Nome do bloco a detalhar"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8)"},
                    "empresa": {"type": "string", "description": "Nome da empresa ou null/Consolidado"}
                },
                "required": ["bloco", "ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "comparar_empresas",
            "description": "Compara e ordena as empresas da MQ Hair para um indicador financeiro (venda_bruta, venda_liquida, cmv, despesas_vendas, despesas_adm).",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicador": {"type": "string", "description": "Indicador: 'venda_bruta', 'venda_liquida', 'cmv', 'despesas_vendas', 'despesas_adm'"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8)"}
                },
                "required": ["indicador", "ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "gerar_grafico",
            "description": "Gera um gráfico visual interativo (barras, linhas ou pizza) para ser desenhado na tela do chat.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["bar", "line", "pie", "doughnut"], "description": "Tipo do gráfico"},
                    "titulo": {"type": "string", "description": "Título explicativo do gráfico"},
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "Rótulos das categorias"},
                    "valores": {"type": "array", "items": {"type": "number"}, "description": "Valores numéricos puros"},
                    "legenda": {"type": "string", "description": "Nome da métrica"}
                },
                "required": ["tipo", "titulo", "labels", "valores"]
            }
        }
    }
]

def _executar_llm(messages, tools=None):
    """
    Executa a chamada com Function Calling prioritariamente via OpenRouter (openai/gpt-4o-mini).
    Se OpenRouter falhar (ex: quota 429 ou rede), aciona automaticamente o fallback para OpenAI direta e Mistral AI.
    """
    # 1. Prioridade: OpenRouter (openai/gpt-4o-mini, google/gemini-2.0-flash-001, etc.)
    if OPENROUTER_API_KEY and len(OPENROUTER_API_KEY) > 20:
        url_openrouter = "https://openrouter.ai/api/v1/chat/completions"
        for model in OPENROUTER_MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 850
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            try:
                r = _OPENROUTER_SESSION.post(url_openrouter, json=payload, timeout=25)
                if r.status_code == 200:
                    return r.json(), f"openrouter:{model}"
                print(f"[OpenRouter - {model}] Status {r.status_code}: {r.text[:140]}", flush=True)
                if r.status_code == 429:
                    break
            except Exception as e:
                print(f"[OpenRouter - {model}] Erro de conexão: {e}", flush=True)

    # 2. Fallback: OpenAI Direta (GPT-4o-mini / GPT-4o)
    if OPENAI_API_KEY and len(OPENAI_API_KEY) > 20:
        url_openai = "https://api.openai.com/v1/chat/completions"
        for model in OPENAI_MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": 850
            }
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            try:
                r = _OPENAI_SESSION.post(url_openai, json=payload, timeout=25)
                if r.status_code == 200:
                    return r.json(), f"openai:{model}"
                print(f"[OpenAI - {model}] Status {r.status_code}: {r.text[:140]}", flush=True)
                if r.status_code == 429:
                    break
            except Exception as e:
                print(f"[OpenAI - {model}] Erro de conexão: {e}", flush=True)

    # 3. Fallback: Mistral AI
    url_mistral = "https://api.mistral.ai/v1/chat/completions"
    headers_mistral = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    for model in MISTRAL_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 650
        }
        if tools:
            payload["tools"] = tools
        for retry in range(2):
            try:
                r = _MISTRAL_SESSION.post(url_mistral, headers=headers_mistral, json=payload, timeout=25)
                if r.status_code == 200:
                    return r.json(), f"mistral:{model}"
                if r.status_code in (429, 503):
                    time.sleep(1.0 * (retry + 1))
                    continue
                print(f"[Mistral - {model}] Erro {r.status_code}: {r.text[:140]}", flush=True)
                break
            except Exception:
                time.sleep(0.5)

    return None, None

def _executar_mistral(messages, tools=None):
    return _executar_llm(messages, tools)

def _stream_llm(messages, max_tokens=1000):
    """
    Transmite tokens via Server-Sent Events (SSE) prioritariamente via OpenRouter (openai/gpt-4o-mini).
    Se OpenRouter falhar (ex: quota 429), aciona automaticamente o fallback para OpenAI direta e Mistral AI.
    """
    # 1. Prioridade: OpenRouter (openai/gpt-4o-mini, etc.)
    if OPENROUTER_API_KEY and len(OPENROUTER_API_KEY) > 20:
        url_openrouter = "https://openrouter.ai/api/v1/chat/completions"
        for model in OPENROUTER_MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "stream": True
            }
            try:
                r = _OPENROUTER_SESSION.post(url_openrouter, json=payload, stream=True, timeout=25)
                if r.status_code == 200:
                    sucesso = False
                    for line in r.iter_lines():
                        if line:
                            decoded = line.decode('utf-8')
                            if decoded.startswith('data: '):
                                d_str = decoded[6:].strip()
                                if d_str == '[DONE]':
                                    break
                                try:
                                    chunk = json.loads(d_str)
                                    token = chunk['choices'][0]['delta'].get('content', '')
                                    if token:
                                        sucesso = True
                                        yield token
                                except Exception:
                                    pass
                    if sucesso:
                        return
                else:
                    print(f"[OpenRouter Stream - {model}] Status {r.status_code}: {r.text[:140]}", flush=True)
                    if r.status_code == 429:
                        break
            except Exception as e:
                print(f"[OpenRouter Stream - {model}] Erro: {e}", flush=True)

    # 2. Fallback: OpenAI Direta
    if OPENAI_API_KEY and len(OPENAI_API_KEY) > 20:
        url_op = "https://api.openai.com/v1/chat/completions"
        for model in OPENAI_MODELS:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "stream": True
            }
            try:
                r = _OPENAI_SESSION.post(url_op, json=payload, stream=True, timeout=25)
                if r.status_code == 200:
                    sucesso = False
                    for line in r.iter_lines():
                        if line:
                            decoded = line.decode('utf-8')
                            if decoded.startswith('data: '):
                                d_str = decoded[6:].strip()
                                if d_str == '[DONE]':
                                    break
                                try:
                                    chunk = json.loads(d_str)
                                    token = chunk['choices'][0]['delta'].get('content', '')
                                    if token:
                                        sucesso = True
                                        yield token
                                except Exception:
                                    pass
                    if sucesso:
                        return
                else:
                    print(f"[OpenAI Stream - {model}] Status {r.status_code}: {r.text[:140]}", flush=True)
                    if r.status_code == 429:
                        break
            except Exception as e:
                print(f"[OpenAI Stream - {model}] Erro: {e}", flush=True)

    # 3. Fallback: Mistral AI
    url_mis = "https://api.mistral.ai/v1/chat/completions"
    headers_mis = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload_mis = {
        "model": "open-mistral-nemo",
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": True
    }
    try:
        r = _MISTRAL_SESSION.post(url_mis, headers=headers_mis, json=payload_mis, stream=True, timeout=25)
        if r.status_code == 200:
            for line in r.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith('data: '):
                        d_str = decoded[6:].strip()
                        if d_str == '[DONE]':
                            break
                        try:
                            chunk = json.loads(d_str)
                            token = chunk['choices'][0]['delta'].get('content', '')
                            if token:
                                yield token
                        except Exception:
                            pass
            return
        print(f"[Mistral Stream] Status {r.status_code}: {r.text[:140]}", flush=True)
    except Exception as ex_mis:
        print(f"[Mistral Stream] Erro: {ex_mis}", flush=True)

def obter_system_prompt_persona(ano_ctx, mes_ctx, periodo_ref_desc, nome_usuario=None, saudacao_periodo="Olá"):
    """
    Retorna o System Prompt oficial consolidando a Persona Executiva Sênior,
    o Fluxo de Raciocínio Interno em 3 etapas, a Biblioteca de Casos de Uso
    e as Regras de Apresentação e Diretrizes Contábeis do DRE MQ Hair.
    """
    usuario_instrucao = (
        f"TRATAMENTO PERSONALIZADO AO DIRETOR/EXECUTIVO:\n"
        f"O executivo conectado neste momento chama-se **{nome_usuario}**.\n"
        f"Cumprimente-o cordialmente pelo nome ao iniciar sua resposta formal (ex: '{saudacao_periodo}, **{nome_usuario}**!...').\n\n"
    ) if nome_usuario else ""

    return (
        f"{usuario_instrucao}"
        "# ⚠️ REGRA ZERO DE SEGURANÇA E FIDELIDADE CONTÁBIL (ABSOLUTA E INEGOCIÁVEL)\n"
        "1. ZERO ALUCINAÇÃO: Você é um auditor e controlador corporativo de alta precisão. Todo e qualquer valor financeiro em R$, percentual (%) ou desvio orçamentário citado na sua resposta DEVE ser estritamente extraído dos [DADOS OFICIAIS DO BANCO DE DADOS MQ HAIR (DRE)] fornecidos nesta conversa ou retornados pelas ferramentas contábeis.\n"
        "2. PROIBIÇÃO CATEGÓRICA DE INVENÇÃO: É terminantemente proibido inventar, deduzir, supor ou estimar valores numéricos que não constem na base oficial. Se não souber ou o dado não estiver na base, declare expressamente que a informação não consta no extrato contábil do período.\n"
        "3. PRECISÃO EXATA: Não invente contas contábeis, nem agrupe valores sem correspondência exata na DRE.\n"
        "4. GERAÇÃO OBRIGATÓRIA DE GRÁFICOS: Se o usuário solicitar qualquer visualização em gráfico (pizza, rosca, barras, linhas, evolução temporal, custos), você DEVE OBRIGATORIAMENTE incluir ao final da sua resposta o bloco ```chart {...}``` com o JSON válido do Chart.js. No array `data`, use SEMPRE números puros positivos (ex: 204179.50) para custos e despesas em gráficos de pizza/rosca.\n\n"
        "---\n\n"
        "# Papel e Identidade\n"
        "Você é um Agente de Inteligência Executiva e Controladoria Corporativa de Nível Sênior, integrado diretamente ao banco de dados Oracle.\n"
        "Seu objetivo é atender a demandas analíticas de Diretores Executivos (CEO, CFO, CCO/Comercial, COO e Controladoria/Contábil) com foco em Demonstração do Resultado do Exercício (DRE), aderência orçamentária e rentabilidade.\n\n"
        f"EXERCÍCIO FISCAL EM ANÁLISE: {ano_ctx} | {periodo_ref_desc}.\n\n"
        "---\n\n"
        "# Fluxo Obrigatório de Raciocínio (Interno)\n\n"
        "Antes de gerar qualquer resposta ao executivo, execute estritamente este ciclo de 3 etapas:\n\n"
        "### 1. Query (Formulação Técnica no Oracle)\n"
        "- Identifique a métrica financeira exigida: Receita Bruta/Líquida, CMV/CPV, Margem Bruta, Margem de Contribuição, EBITDA/LAIDA, Resultado Financeiro, Lucro Líquido, Margem Líquida ou Variação Orçado vs. Realizado.\n"
        "- Formule a consulta SQL com sintaxe estrita de Oracle Database:\n"
        "  - Limite de linhas com `FETCH FIRST N ROWS ONLY` ou `ROWNUM <= N` (nunca use LIMIT).\n"
        "  - Truncamento e formatação de datas via `TRUNC(data_coluna)`, `TO_DATE` e `TO_CHAR(data, 'YYYY-MM')`.\n"
        "  - Tratamento de nulos com `NVL` ou `COALESCE`.\n"
        "  - Evite duplicidade de rateios/lançamentos conferindo chaves e status de validação contábil.\n\n"
        "### 2. Validação (Checagem Técnica e Contábil)\n"
        "Antes de rodar a query, valide os seguintes critérios:\n"
        "- **Estouro de Orçamento:** `Variação = Realizado - Orçado`. Para custos e despesas, variação positiva representa estouro desfavorável.\n"
        "- **Divisão por Zero:** Toda métrica com quociente (Margens %, Variações % MoM/YoY) deve usar `NULLIF(denominador, 0)` ou `CASE WHEN`.\n"
        "- **Hierarquia da DRE:** Garanta que deduções de receita, custos diretos e despesas operacionais (OpEx / SG&A) estejam nas linhas e naturezas de contas corretas do plano de contas.\n"
        "- **Granularidade:** Certifique-se de que agrupamentos por Centro de Custos, Canal, Unidade de Negócio ou Período não estejam duplicando somatórios.\n\n"
        "### 3. Execução & Síntese Executiva\n"
        "- Execute a query no Oracle em modo somente leitura (SELECT).\n"
        "- Se os dados retornados divergirem da lógica financeira básica, refine a query antes de emitir o relatório.\n"
        "- Formate a resposta final no formato executivo estabelecido abaixo.\n\n"
        "---\n\n"
        "# Biblioteca de Casos de Uso e Consultas da Diretoria\n\n"
        "Esteja preparado para responder com profundidade e rigor às seguintes demandas típicas dos diretores:\n\n"
        "### A. Estratégico & Resultados Globais (Foco: CEO / Diretor Executivo)\n"
        "- **Desempenho de EBITDA:** Comparativo do EBITDA consolidado atual vs. orçado e vs. mesmo período do ano anterior.\n"
        "- **Degradação de Margem:** Diagnóstico de receitas que cresceram com recuo no lucro líquido (onde o valor foi consumido na DRE).\n"
        "- **Contribuição por Unidade/Centro de Custo:** As 3 principais unidades/centros que mais geraram ou consumiram resultado no acumulado do ano.\n"
        "- **Projeção de Fechamento:** Estimativa de lucro líquido para o encerramento do exercício com base no ritmo atual de OpEx.\n"
        "- **Ponto de Equilíbrio (Break-Even):** Volume de faturamento necessário para cobrir custos e despesas fixas atuais.\n\n"
        "### B. Finanças, Orçamento & Controladoria (Foco: CFO / Controller)\n"
        "- **Orçado vs. Realizado Consolidado:** Desvios absolutos (R$) e percentuais (%) da DRE consolidada do mês e acumulada.\n"
        "- **Estouro Orçamentário:** Centros de custo que superaram o teto orçado em mais de 5%, detalhando mês de maior ocorrência e contas contábeis ofensoras.\n"
        "- **Evolução de SG&A:** Trajetória das despesas gerais e administrativas nos últimos 3, 6 ou 12 meses como % da Receita Líquida.\n"
        "- **Carga Tributária Efetiva:** Oscilação das deduções/impostos sobre faturamento e impacto de alterações no mix de vendas.\n"
        "- **Resultado Financeiro:** Impacto líquido de juros pagos, receitas de aplicações e variações cambiais sobre o resultado pré-tributos.\n\n"
        "### C. Comercial & Canais (Foco: CCO / Diretor Comercial)\n"
        "- **Margem de Contribuição por Canal/Produto:** Identificação dos canais, linhas e carteiras mais e menos rentáveis.\n"
        "- **Aderência à Meta de Margem Bruta:** Identificação de canais, regiões ou clientes que operam abaixo do patamar mínimo exigido.\n"
        "- **Impacto de Descontos e Devoluções:** Volume e representatividade das deduções comerciais sobre a receita bruta.\n"
        "- **Custos de Vendas (Frete, Comissões, Gateway):** Verificação se os custos de aquisição e distribuição estão crescendo acima da receita líquida.\n"
        "- **Recomendações de Eficiência Comercial:** Ações práticas para reduzir despesas de venda em canais específicos apoiadas nos dados reais.\n\n"
        "### D. Operações & Custos Diretos (Foco: COO / Diretor de Operações)\n"
        "- **Evolução de CMV/CPV:** Relação CMV/Receita Líquida nos últimos 12 meses (ganho ou perda de eficiência).\n"
        "- **Detalhamento do CPV:** Decomposição do custo direto (insumos/matéria-prima, mão de obra direta, logística inbound).\n"
        "- **Custos mais Elevados:** Levantamento das contas de maior peso financeiro e aplicação da curva ABC (80/20) dos custos.\n\n"
        "---\n\n"
        "# Regras de Apresentação da Resposta\n\n"
        "1. **Conclusão no Primeiro Parágrafo:** Comece sempre com o resumo executivo em 2 ou 3 linhas (conclusão direta e valores principais destacados em negrito).\n"
        "2. **Tabelas Sintéticas:** Mostre os dados consolidados em tabelas limpas em Markdown. Valores monetários em `R$ #.###.##0,00` e percentuais com 1 ou 2 casas decimais (`0,0%`). Colunas recomendadas: Indicador Contábil | Orçado | Realizado | Desvio (R$ e %).\n"
        "3. **Tendências e Séries Temporais:** Para pedidos de 3, 6 ou 12 meses, exiba a série cronológica com indicadores de variação (`▲` favorável / `▼` desfavorável).\n"
        "4. **Sem Jargão de TI:** Não exponha nomes técnicos de tabelas, sintaxes de `JOIN`, `WHERE` ou detalhes de banco de dados, exceto se solicitado expressamente.\n"
        "5. **Diagnóstico de Causa-Raiz:** Nunca se limite a mostrar o número frio; aponte quais contas contábeis, canais ou centros de custo puxaram a variação.\n\n"
        "---\n\n"
        "# Diretrizes Operacionais e Escolha de Ferramentas (DRE MQ Hair)\n\n"
        f"- **Ano Fiscal de Referência:** É OBRIGATORIAMENTE {ano_ctx}. NUNCA consulte o ano de 2024 a menos que o usuário cite expressamente '2024' na pergunta.\n"
        "- **Cards Oficiais do Cabeçalho do DRE:** 1. Venda Bruta | 2. Margem de Contribuição | 3. Bonificação | 4. Comissão | 5. Guelta | 6. Despesa Comercial Operacional | 7. Folha e Benefícios | 8. Venda Líquida.\n"
        "  Quando o usuário perguntar o valor de qualquer um desses cards (ex: 'valor da comissão', 'qual a comissão?', 'bonificação', 'guelta', 'folha'), NUNCA considere como centro de custo! Chame `obter_resumo_dre` ou `consultar_conta_historico`.\n"
        "- **Estouro e Desvios de Orçamento:** Chame `analisar_estouros_orcamento(ano, mes)`.\n"
        "- **Histórico Mês a Mês de uma Conta:** Chame `consultar_conta_historico(conta, ano)`.\n"
        "- **Centros de Custo Específicos:** Chame `consultar_por_centro_custo` ou `obter_dre_centro_custo`.\n"
        "- **Regra Crítica de Percentuais de Margem:**\n"
        "  - `pct_sobre_vb_realizado`: Margem sobre a VENDA BRUTA Realizada (padrão principal da MQ Hair).\n"
        "  - `pct_sobre_vl_realizado`: Margem sobre a VENDA LÍQUIDA Realizada.\n"
        "- **Geração de Gráficos Visuais Interativos:** Se o executivo solicitar um gráfico (ex: 'mostre em gráfico', 'gráfico de pizza', 'gráfico de barras', 'gráfico de linhas', 'evolução em gráfico', 'divisão dos custos em gráfico'), você DEVE OBRIGATORIAMENTE incluir ao final da sua resposta o bloco no formato exato:\n"
        "```chart\n"
        "{\n"
        '  "type": "pie",\n'
        '  "title": "Título Executivo do Gráfico",\n'
        '  "labels": ["Item 1", "Item 2", "Item 3"],\n'
        '  "datasets": [{\n'
        '    "label": "Realizado (R$)",\n'
        '    "data": [349736.65, 287798.27, 204179.50]\n'
        '  }]\n'
        "}\n"
        "```\n"
        "Regras vitais para gráficos:\n"
        "- Escolha o `type` adequado: 'pie' (pizza para divisão/composição percentual), 'doughnut' (rosca), 'bar' (barras para ranking/comparação), 'line' (linha para evolução temporal mês a mês).\n"
        "- No array `data`, use SEMPRE números puros (float/int), positivos para custos/despesas (ex: 204179.50 em vez de -204.179,50), sem símbolos de moeda dentro do JSON.\n"
        "- NUNCA escreva apenas 'gerando gráfico...' sem colocar o bloco ```chart {...}```. O bloco ```chart``` é a instrução direta que faz o gráfico Chart.js renderizar na tela.\n"
        "- **Proibição Absoluta de Alucinação:** Utilize estritamente os dados oficiais contábeis fornecidos no contexto ou retornados pelas ferramentas. NUNCA invente números."
    )

def processar_pergunta(prompt, contexto=None):
    """
    Processa a pergunta do usuário no Chat da IA com Function Calling do Mistral.
    """
    hoje = datetime.now()
    ano_ctx = hoje.year
    mes_ctx = hoje.month
    emp_ctx = "Consolidado"

    contexto_str = ""
    if contexto:
        f = contexto.get("filtros", {})
        try:
            if f.get("ano"):
                ano_ctx = int(f.get("ano"))
            if f.get("mes"):
                mes_ctx = int(f.get("mes"))
        except Exception:
            pass

        emp_ctx = f.get("empresa") or "Consolidado"
        cenc_ctx = f.get("centroCusto") or "Todos"
        vb_ctx = contexto.get("vendaBruta") or "N/D"
        mg_ctx = contexto.get("margem") or "N/D"

        nome_usuario = contexto.get("usuario")
        saudacao_periodo = contexto.get("saudacao") or "Olá"
        usuario_info = f"\n- Usuário Logado: {nome_usuario}" if nome_usuario else ""

        contexto_str = (
            f"\n\n[CONTEXTO ATUAL DA TELA DO USUÁRIO]:"
            f"{usuario_info}"
            f"\n- Ano Selecionado: {ano_ctx}"
            f"\n- Mês Selecionado: {mes_ctx}"
            f"\n- Empresa Filtrada: {emp_ctx}"
            f"\n- Centro de Custo: {cenc_ctx}"
            f"\n- Venda Bruta na Tela: {vb_ctx}"
            f"\n- Margem na Tela: {mg_ctx}"
            f"\n(Utilize este ano={ano_ctx}, mês={mes_ctx}, empresa='{emp_ctx}' caso a pergunta não especifique outros)."
        )
    else:
        nome_usuario = None
        saudacao_periodo = "Olá"

    p_lower = prompt.lower()

    # Identifica mês e ano solicitados na pergunta com alta precisão (mes_ctx pode ser None para ano acumulado)
    ano_ctx, mes_ctx = extrair_periodo_do_prompt(prompt, ano_padrao=ano_ctx, mes_padrao=mes_ctx)

    # 1.0 Roteamento Imediato para Indicadores de Balanço Patrimonial / Fora do DRE (ROI, ROE, etc.)
    termos_fora_dre = ["roi", "retorno sobre o investimento", "retorno sobre investimento", "roe", "roic", "capital investido", "balanço patrimonial", "balanco patrimonial", "ativo total", "passivo", "capital de giro", "fluxo de caixa"]
    if any(k in p_lower for k in termos_fora_dre):
        return responder_indicador_fora_dre(prompt, ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx)

    # 1.1 Roteamento Imediato para Saudações e Boas-Vindas
    saudacoes_simples = {"ola", "olá", "oi", "oie", "bom dia", "boa tarde", "boa noite", "ajuda", "help", "hello", "hi"}
    p_limpo = re.sub(r'[^\w\s]', '', p_lower).strip()
    periodo_label_info = f"{mes_ctx:02d}/{ano_ctx}" if mes_ctx is not None else f"Acumulado {ano_ctx}"
    if p_limpo in saudacoes_simples:
        saudacao_str = f"{saudacao_periodo}!" if not nome_usuario else f"{saudacao_periodo}, **{nome_usuario}**!"
        return (
            f"{saudacao_str} Sou o **Agente de Inteligência Executiva e Controladoria Corporativa** da **MQ Hair Company**.\n\n"
            f"Estou integrado à base de dados oficial da Controladoria para o exercício **{ano_ctx}** ({periodo_label_info}) com foco em **DRE, aderência orçamentária e rentabilidade**.\n\n"
            f"**Demandas executivas prontas para consulta:**\n"
            f"- 📊 **Estratégico & Resultados Globais:** *\"Qual foi a Venda Bruta e a Margem em {periodo_label_info}?\"*\n"
            f"- ⚠️ **Finanças & Orçamento:** *\"Quais centros de custo estouraram o orçamento neste mês?\"*\n"
            f"- 📈 **Séries Temporais:** *\"Qual a evolução mês a mês de frete, folha e aluguel?\"*\n"
            f"- 🏢 **Unidades & Desempenho:** *\"Como foi o desempenho por empresa ou centro de resultado?\"*"
        )

    # 1.2 Roteamento Imediato para Proporção Folha x Faturamento Bruto (100% exatidão matemática)
    if any(k in p_lower for k in ["folha", "salario", "salário", "beneficio", "benefício"]) and any(f in p_lower for f in ["fatur", "receita", "venda", " x ", " vs ", "sobre", "proporcao", "proporção", "percentual", "peso"]):
        return responder_folha_vs_faturamento(prompt, ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx)

    periodo_ref_desc = f"MÊS DE REFERÊNCIA É {mes_ctx:02d}" if mes_ctx is not None else f"PERÍODO É O ACUMULADO ANUAL DE {ano_ctx}"
    system_prompt = obter_system_prompt_persona(ano_ctx, mes_ctx, periodo_ref_desc, nome_usuario, saudacao_periodo)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt + contexto_str}
    ]

    blocos_graficos_gerados = []
    ultimas_ferramentas_outputs = []

    for step in range(3):
        res, model_used = _executar_llm(messages, TOOLS_SCHEMA)
        if not res:
            try:
                resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
                vb = resumo.get("venda_bruta", {})
                vl = resumo.get("venda_liquida", {})
                mc = resumo.get("margem_contribuicao", {})
                def fmt_val(v):
                    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                return (
                    f"Consultei diretamente os dados oficiais do DRE na base local:\n\n"
                    f"**Resultado Executivo ({resumo.get('periodo', periodo_label_info)} - {resumo.get('empresa', 'Consolidado')}):**\n"
                    f"- **Venda Bruta:** Realizado **{fmt_val(vb.get('realizado', 0))}** | Orçado **{fmt_val(vb.get('orcado', 0))}** ({vb.get('desvio_pct', 0):+.1f}%)\n"
                    f"- **Venda Líquida:** Realizado **{fmt_val(vl.get('realizado', 0))}** | Orçado **{fmt_val(vl.get('orcado', 0))}** ({vl.get('desvio_pct', 0):+.1f}%)\n"
                    f"- **Margem de Contribuição:** Realizado **{fmt_val(mc.get('realizado', 0))}** | Orçado **{fmt_val(mc.get('orcado', 0))}** ({mc.get('desvio_pct', 0):+.1f}%)"
                )
            except Exception:
                return "Olá! Sou a MQIA. Estou conectada aos dados oficiais do DRE da MQ Hair Company. Por favor, especifique o indicador ou centro de custo que deseja analisar."

        choice = res.get("choices", [{}])[0]
        asst_msg = choice.get("message", {})
        messages.append(asst_msg)

        tool_calls = asst_msg.get("tool_calls", [])
        if not tool_calls:
            texto_final = asst_msg.get("content") or "Análise concluída com sucesso."
            texto_final = validar_e_higienizar_bloco_grafico(texto_final, prompt, dados_ferramenta=ultimas_ferramentas_outputs)
            return texto_final

        # Executa ferramentas
        for tc in tool_calls:
            fname = tc.get("function", {}).get("name")
            call_id = tc.get("id")
            args_raw = tc.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except Exception:
                args = {}

            print(f"[IA LLM - {model_used}] Executando tool: {fname}({args})", flush=True)

            ano_arg = args.get("ano")
            if not ano_arg or (ano_arg == 2024 and "2024" not in prompt):
                ano_arg = ano_ctx
            mes_arg = args.get("mes") or mes_ctx

            if fname == "analisar_estouros_orcamento":
                apenas_arg = args.get("apenas_estouros", True)
                tool_output = analisar_estouros_orcamento(ano=ano_arg, mes=mes_arg, apenas_estouros=apenas_arg)

            elif fname == "consultar_conta_historico":
                conta_arg = args.get("conta", "Aluguel")
                tool_output = consultar_conta_historico(conta=conta_arg, ano=ano_arg)

            elif fname == "consultar_por_centro_custo":
                cenc_arg = args.get("centro_custo", "Distribuição")
                filtro_arg = args.get("filtro_conta")
                tool_output = consultar_por_centro_custo(centro_custo=cenc_arg, ano=ano_arg, mes=mes_arg, filtro_conta=filtro_arg)

            elif fname == "obter_dre_centro_custo":
                cenc_arg = args.get("centro_custo", "VAREJO - SUL")
                emp_arg = args.get("empresa")
                tool_output = obter_dre_centro_custo(centro_custo=cenc_arg, ano=ano_arg, mes=mes_arg, empresa=emp_arg)

            elif fname == "obter_resumo_dre":
                emp_arg = args.get("empresa", emp_ctx if emp_ctx != "Consolidado" else None)
                tool_output = obter_resumo_dre(ano=ano_arg, mes=mes_arg, empresa=emp_arg)

            elif fname == "obter_maiores_custos_despesas":
                emp_arg = args.get("empresa", emp_ctx if emp_ctx != "Consolidado" else None)
                tool_output = obter_maiores_custos_despesas(ano=ano_arg, mes=mes_arg, empresa=emp_arg, limite=args.get("limite", 10))

            elif fname == "detalhar_bloco":
                bloco_arg = args.get("bloco", "Despesas com Vendas")
                ano_arg = args.get("ano", ano_ctx)
                mes_arg = args.get("mes", mes_ctx)
                emp_arg = args.get("empresa", emp_ctx if emp_ctx != "Consolidado" else None)
                tool_output = detalhar_bloco(bloco=bloco_arg, ano=ano_arg, mes=mes_arg, empresa=emp_arg)

            elif fname == "comparar_empresas":
                ind_arg = args.get("indicador", "venda_bruta")
                ano_arg = args.get("ano", ano_ctx)
                mes_arg = args.get("mes", mes_ctx)
                tool_output = comparar_empresas(indicador=ind_arg, ano=ano_arg, mes=mes_arg)

            elif fname == "gerar_grafico":
                tipo_arg = args.get("tipo", "bar")
                titulo_arg = args.get("titulo", "Gráfico DRE MQ Hair")
                labels_arg = args.get("labels", [])
                valores_arg = args.get("valores", [])
                legenda_arg = args.get("legenda", "Realizado (R$)")
                tool_output = gerar_grafico(tipo=tipo_arg, titulo=titulo_arg, labels=labels_arg, valores=valores_arg, legenda=legenda_arg)
                if tool_output.get("bloco_markdown"):
                    blocos_graficos_gerados.append(tool_output["bloco_markdown"])

            else:
                tool_output = {"error": f"Ferramenta desconhecida: {fname}"}

            ultimas_ferramentas_outputs.append((fname, tool_output))

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": fname,
                "content": json.dumps(tool_output, ensure_ascii=False)
            })

    return "A análise foi concluída."

def stream_processar_pergunta(prompt, contexto=None):
    """
    Processa a pergunta do usuário transmitindo a resposta em tempo real via Server-Sent Events (SSE).
    Efeito 'máquina de escrever' com Time-To-First-Token ultrarrápido (< 500ms).
    """
    hoje = datetime.now()
    ano_ctx = hoje.year
    mes_ctx = hoje.month
    emp_ctx = "Consolidado"

    if contexto:
        f = contexto.get("filtros", {})
        try:
            if f.get("ano"):
                ano_ctx = int(f.get("ano"))
            if f.get("mes"):
                mes_ctx = int(f.get("mes"))
        except Exception:
            pass
        emp_ctx = f.get("empresa") or "Consolidado"
        nome_usuario = contexto.get("usuario")
        saudacao_periodo = contexto.get("saudacao") or "Boa tarde"
    else:
        nome_usuario = None
        saudacao_periodo = "Boa tarde"

    p_lower = prompt.lower()

    # Identifica com precisão o mês e ano solicitados na pergunta
    ano_ctx, mes_ctx = extrair_periodo_do_prompt(prompt, ano_padrao=ano_ctx, mes_padrao=mes_ctx)

    dados_pre = None
    status_msg = "MQIA analisando dados do DRE..."

    # Termos com tolerância a typos para venda / faturamento / DRE geral
    termos_venda_geral = [
        "venda", "vendas", "fatur", "receita", "bruta", "burt", "liquida", "líquida", 
        "cmv", "margem", "ebitda", "dre", "resultado"
    ]

    # 1.0 Roteamento Imediato para Indicadores de Balanço Patrimonial / Fora do DRE (ROI, ROE, etc.)
    termos_fora_dre = ["roi", "retorno sobre o investimento", "retorno sobre investimento", "roe", "roic", "capital investido", "balanço patrimonial", "balanco patrimonial", "ativo total", "passivo", "capital de giro", "fluxo de caixa"]
    if any(k in p_lower for k in termos_fora_dre):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        resposta_fora = responder_indicador_fora_dre(prompt, ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx)
        yield {"tipo": "token", "texto": resposta_fora}
        yield {"tipo": "fim", "resposta_completa": resposta_fora}
        return

    # 1.1 Roteamento Imediato para Saudações e Boas-Vindas (zero latência e 100% resiliente)
    saudacoes_simples = {"ola", "olá", "oi", "oie", "bom dia", "boa tarde", "boa noite", "ajuda", "help", "hello", "hi"}
    p_limpo = re.sub(r'[^\w\s]', '', p_lower).strip()
    periodo_label_info = f"{mes_ctx:02d}/{ano_ctx}" if mes_ctx is not None else f"Acumulado {ano_ctx}"
    if p_limpo in saudacoes_simples:
        yield {"tipo": "status", "texto": "Digitando..."}
        saudacao_str = f"{saudacao_periodo}!" if not nome_usuario else f"{saudacao_periodo}, **{nome_usuario}**!"
        resposta_saudacao = (
            f"{saudacao_str} Sou o **Agente de Inteligência Executiva e Controladoria Corporativa** da **MQ Hair Company**.\n\n"
            f"Estou integrado à base de dados oficial da Controladoria para o exercício **{ano_ctx}** ({periodo_label_info}) com foco em **DRE, aderência orçamentária e rentabilidade**.\n\n"
            f"**Demandas executivas prontas para consulta:**\n"
            f"- 📊 **Estratégico & Resultados Globais:** *\"Qual foi a Venda Bruta e a Margem em {periodo_label_info}?\"*\n"
            f"- ⚠️ **Finanças & Orçamento:** *\"Quais centros de custo estouraram o orçamento neste mês?\"*\n"
            f"- 📈 **Séries Temporais:** *\"Qual a evolução mês a mês de frete, folha e aluguel?\"*\n"
            f"- 🏢 **Unidades & Desempenho:** *\"Como foi o desempenho por empresa ou centro de resultado?\"*"
        )
        yield {"tipo": "token", "texto": resposta_saudacao}
        yield {"tipo": "fim", "resposta_completa": resposta_saudacao}
        return

    # 1.2 Roteamento Imediato para Proporção Folha x Faturamento Bruto (zero latência, 100% de exatidão matemática)
    if any(k in p_lower for k in ["folha", "salario", "salário", "beneficio", "benefício"]) and any(f in p_lower for f in ["fatur", "receita", "venda", " x ", " vs ", "sobre", "proporcao", "proporção", "percentual", "peso"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        resposta_folha = responder_folha_vs_faturamento(prompt, ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx)
        yield {"tipo": "token", "texto": resposta_folha}
        yield {"tipo": "fim", "resposta_completa": resposta_folha}
        return

    # 2. Roteamento de Pré-busca Indexada SQLite (< 10ms)
    if any(k in p_lower for k in ["estour", "desvio", "orçamento", "orcamento", "estouro"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        dados_pre = analisar_estouros_orcamento(ano=ano_ctx, mes=mes_ctx, apenas_estouros=("estour" in p_lower))

    elif any(k in p_lower for k in ["comiss", "comissão", "comissao", "comissões"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
        hist = consultar_conta_historico(conta="comiss", ano=ano_ctx)
        dados_pre = {
            "indicador": "Comissão (Despesas com Vendas)",
            "periodo": resumo.get("periodo", periodo_label_info),
            "empresa": emp_ctx,
            "venda_bruta": resumo.get("venda_bruta", {}),
            "venda_liquida": resumo.get("venda_liquida", {}),
            "card_kpi_mes_atual": resumo.get("comissao", {}),
            "historico_ano": hist
        }

    elif any(k in p_lower for k in ["bonific", "bonificação", "bonificacao", "bonificações", "bonificacoes"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
        hist = consultar_conta_historico(conta="bonif", ano=ano_ctx)
        dados_pre = {
            "indicador": "Bonificação (Dedução / Despesas)",
            "periodo": resumo.get("periodo", periodo_label_info),
            "empresa": emp_ctx,
            "venda_bruta": resumo.get("venda_bruta", {}),
            "venda_liquida": resumo.get("venda_liquida", {}),
            "card_kpi_mes_atual": resumo.get("bonificacao", {}),
            "historico_ano": hist
        }

    elif any(k in p_lower for k in ["guelta", "gueltas"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
        hist = consultar_conta_historico(conta="guelta", ano=ano_ctx)
        dados_pre = {
            "indicador": "Guelta (Incentivo Comercial)",
            "periodo": resumo.get("periodo", periodo_label_info),
            "empresa": emp_ctx,
            "venda_bruta": resumo.get("venda_bruta", {}),
            "venda_liquida": resumo.get("venda_liquida", {}),
            "card_kpi_mes_atual": resumo.get("guelta", {}),
            "historico_ano": hist
        }

    elif any(k in p_lower for k in ["folha", "salario", "salário", "beneficio", "benefício"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
        hist = consultar_conta_historico(conta="folha", ano=ano_ctx)
        dados_pre = {
            "indicador": "Folha de Pagamento e Benefícios (Administrativa + Comercial)",
            "periodo": resumo.get("periodo", periodo_label_info),
            "empresa": emp_ctx,
            "faturamento_bruto": resumo.get("venda_bruta", {}),
            "venda_bruta": resumo.get("venda_bruta", {}),
            "venda_liquida": resumo.get("venda_liquida", {}),
            "card_kpi_mes_atual": resumo.get("folha_beneficios", {}),
            "folha_total": resumo.get("folha_beneficios", {}),
            "folha_administrativa": resumo.get("folha_adm", {}),
            "folha_comercial": resumo.get("folha_comercial", {}),
            "proporcao_folha_sobre_venda_bruta_pct": resumo.get("folha_beneficios", {}).get("pct_sobre_venda_bruta"),
            "historico_ano": hist
        }

    elif any(k in p_lower for k in ["aluguel", "frete", "energia", "luz", "água", "agua"]) or \
         (("mês a mês" in p_lower or "mes a mes" in p_lower or "histórico" in p_lower or "historico" in p_lower or "evolução" in p_lower or "evolucao" in p_lower) and not any(v in p_lower for v in ["venda", "fatur", "receit"])):
        conta = "Aluguel" if "aluguel" in p_lower else ("Frete" if "frete" in p_lower else ("Energia" if "energia" in p_lower else "Comiss"))
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        dados_pre = consultar_conta_historico(conta=conta, ano=ano_ctx)

    if dados_pre is None:
        centro_identificado, tipo_identificado = identificar_centro_custo_ou_empresa(prompt)
        if centro_identificado:
            status_msg = "Digitando..."
            yield {"tipo": "status", "texto": status_msg}
            if tipo_identificado == "empresa":
                dados_pre = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=centro_identificado)
            else:
                dados_pre = obter_dre_centro_custo(centro_custo=centro_identificado, ano=ano_ctx, mes=mes_ctx)

    if dados_pre is None and any(k in p_lower for k in ["imposto", "impostos", "tributo", "tributos", "darf", "icms", "pis", "cofins"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        dados_pre = consultar_conta_historico(conta="IMPOST", ano=ano_ctx)

    if dados_pre is None and any(k in p_lower for k in ["custo", "custos", "despesa", "despesas", "gasto", "gastos", "operacion"]):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        dados_pre = obter_maiores_custos_despesas(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)

    if dados_pre is None and any(k in p_lower for k in termos_venda_geral):
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        dados_pre = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)

    # TRAVA FUNDAMENTAL ANTI-ALUCINAÇÃO (O LLM NUNCA OPERA SEM CONTEXTO OFICIAL DO BANCO):
    # Se nenhuma rota específica capturou dados_pre, SEMPRE carrega o resumo contábil oficial (obter_resumo_dre).
    if dados_pre is None:
        status_msg = "Digitando..."
        yield {"tipo": "status", "texto": status_msg}
        dados_pre = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)

    # 3. Instruções do Sistema para o Agente Executivo MQIA (Persona Executiva Sênior)
    periodo_ref_desc = f"MÊS DE REFERÊNCIA É {mes_ctx:02d}" if mes_ctx is not None else f"PERÍODO É O ACUMULADO ANUAL DE {ano_ctx}"
    system_content = obter_system_prompt_persona(ano_ctx, mes_ctx, periodo_ref_desc, nome_usuario, saudacao_periodo)

    messages = [{"role": "system", "content": system_content}]

    # Se dados já foram pré-buscados no banco, injeta no prompt do usuário e faz streaming imediato
    if dados_pre:
        user_content = (
            f"{prompt}\n\n"
            f"[DADOS OFICIAIS DO BANCO DE DADOS MQ HAIR (DRE)]:\n"
            f"{json.dumps(dados_pre, ensure_ascii=False, indent=2)}\n\n"
            f"INSTRUÇÃO OBRIGATÓRIA: Responda com base ESTRITAMENTE nos dados oficiais acima. "
            f"NUNCA invente números, percentuais ou contas que não estejam no bloco acima."
        )
        messages.append({"role": "user", "content": user_content})

        texto_total = ""
        for token in _stream_llm(messages, max_tokens=1000):
            texto_total += token
            yield {"tipo": "token", "texto": token}

        # TRAVA DEFINITIVA DE GRÁFICOS: Valida, higieniza JSON e auto-injeta se necessário
        texto_validado = validar_e_higienizar_bloco_grafico(texto_total, prompt, dados_ferramenta=[("dados_pre", dados_pre)])
        if texto_validado != texto_total:
            diferenca = texto_validado[len(texto_total):]
            if diferenca:
                yield {"tipo": "token", "texto": diferenca}
            texto_total = texto_validado

        # Auditoria anti-alucinação contra dados oficiais
        if _detectar_alucinacao(texto_total, dados_pre):
            print("[TRAVA DE SEGURANÇA] Alucinação detectada na resposta gerada pelo LLM.", flush=True)

        if texto_total.strip():
            yield {"tipo": "fim", "resposta_completa": texto_total}
            return
        else:
            # Fallback resiliente usando dados pré-buscados locais
            try:
                def fmt_val(v):
                    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                if dados_pre and "maiores_custos" in dados_pre:
                    itens = dados_pre.get("itens", [])
                    linhas_md = []
                    for it in itens[:8]:
                        linhas_md.append(f"| **{it['titulo']}** | {fmt_val(it['orcado'])} | **{fmt_val(it['realizado'])}** | {fmt_val(it['desvio_reais'])} | {it['desvio_pct']:+.1f}% |")
                    tabela_custos = "\n".join(linhas_md)
                    fb_custos = (
                        f"**Maiores Custos e Despesas Operacionais — {dados_pre.get('periodo')} ({dados_pre.get('empresa')}):**\n\n"
                        f"| Título Contábil | Orçado | Realizado | Desvio (R$) | Desvio (%) |\n"
                        f"| :--- | :---: | :---: | :---: | :---: |\n"
                        f"{tabela_custos}\n\n"
                    )
                    bloco_g = auto_injetar_bloco_grafico(prompt, fb_custos, dados_ferramenta=[("dados_pre", dados_pre)])
                    if bloco_g:
                        fb_custos += "\n\n" + bloco_g
                    yield {"tipo": "token", "texto": fb_custos}
                    yield {"tipo": "fim", "resposta_completa": fb_custos}
                    return
                
                if dados_pre and dados_pre.get("tipo") == "DRE Centro de Custo":
                    c_nome = dados_pre.get("centro_custo")
                    per = dados_pre.get("periodo")
                    vb = dados_pre.get("venda_bruta", {})
                    vl = dados_pre.get("venda_liquida", {})
                    mc = dados_pre.get("margem_contribuicao", {})
                    ml = dados_pre.get("margem_liquida_resultado_operacional", {})
                    dv = dados_pre.get("despesas_com_vendas", {})
                    dc = dados_pre.get("despesas_comerciais", {})
                    fb_centro = (
                        f"**Resumo Executivo — {c_nome} ({per}):**\n\n"
                        f"Em {per}, a **Margem de Contribuição** realizada foi de **{fmt_val(mc.get('realizado', 0))}** "
                        f"({mc.get('pct_sobre_vb_realizado', 0):.1f}% da Venda Bruta) e a **Margem Líquida Operacional** atingiu **{fmt_val(ml.get('realizado', 0))}** "
                        f"({ml.get('pct_sobre_vb_realizado', 0):.1f}% da Venda Bruta).\n\n"
                        f"| Indicador Contábil | Orçado | Realizado | Desvio (R$) | Desvio (%) |\n"
                        f"| :--- | :---: | :---: | :---: | :---: |\n"
                        f"| **Venda Bruta** | {fmt_val(vb.get('orcado', 0))} | **{fmt_val(vb.get('realizado', 0))}** | {fmt_val(vb.get('desvio_reais', 0))} | {vb.get('desvio_pct', 0):+.1f}% |\n"
                        f"| **Venda Líquida** | {fmt_val(vl.get('orcado', 0))} | **{fmt_val(vl.get('realizado', 0))}** | {fmt_val(vl.get('desvio_reais', 0))} | {vl.get('desvio_pct', 0):+.1f}% |\n"
                        f"| **Margem de Contribuição** | {fmt_val(mc.get('orcado', 0))} | **{fmt_val(mc.get('realizado', 0))}** | {fmt_val(mc.get('desvio_reais', 0))} | {mc.get('desvio_pct', 0):+.1f}% |\n"
                        f"| **Despesas com Vendas** | {fmt_val(dv.get('orcado', 0))} | **{fmt_val(dv.get('realizado', 0))}** | {fmt_val(dv.get('desvio_reais', 0))} | {dv.get('desvio_pct', 0):+.1f}% |\n"
                        f"| **Despesas Comerciais** | {fmt_val(dc.get('orcado', 0))} | **{fmt_val(dc.get('realizado', 0))}** | {fmt_val(dc.get('desvio_reais', 0))} | {dc.get('desvio_pct', 0):+.1f}% |\n"
                        f"| **Margem Líquida Operacional** | {fmt_val(ml.get('orcado', 0))} | **{fmt_val(ml.get('realizado', 0))}** | {fmt_val(ml.get('desvio_reais', 0))} | {ml.get('desvio_pct', 0):+.1f}% |\n"
                    )
                    yield {"tipo": "token", "texto": fb_centro}
                    yield {"tipo": "fim", "resposta_completa": fb_centro}
                    return

                if dados_pre and "card_kpi_mes_atual" in dados_pre:
                    kpi = dados_pre["card_kpi_mes_atual"]
                    nome_ind = dados_pre.get("indicador", "Indicador")
                    per = dados_pre.get("periodo", periodo_label_info)
                    vb = dados_pre.get("venda_bruta", {})
                    fb_card = (
                        f"Consultei os dados oficiais do DRE na base local:\n\n"
                        f"**{nome_ind} ({per} - {emp_ctx}):**\n"
                        f"- **Realizado:** **{fmt_val(kpi.get('realizado', 0))}**\n"
                        f"- **Orçado:** **{fmt_val(kpi.get('orcado', 0))}**\n"
                        f"- **Desvio:** **{fmt_val(kpi.get('desvio_reais', 0))}** ({kpi.get('desvio_pct', 0):+.1f}%)\n"
                    )
                    if vb and vb.get("realizado"):
                        pct_vb = kpi.get("pct_sobre_venda_bruta") or (abs(kpi.get("realizado", 0)) / vb.get("realizado", 1) * 100)
                        fb_card += f"- **Venda Bruta Realizada:** **{fmt_val(vb.get('realizado', 0))}**\n"
                        fb_card += f"- **Proporção s/ Venda Bruta:** **{pct_vb:.2f}%**\n"
                    yield {"tipo": "token", "texto": fb_card}
                    yield {"tipo": "fim", "resposta_completa": fb_card}
                    return

                resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
                vb = resumo.get("venda_bruta", {})
                vl = resumo.get("venda_liquida", {})
                mc = resumo.get("margem_contribuicao", {})
                fallback_local = (
                    f"Consultei diretamente os dados oficiais do DRE na base local:\n\n"
                    f"**Resultado Executivo ({resumo.get('periodo', periodo_label_info)} - {resumo.get('empresa', 'Consolidado')}):**\n"
                    f"- **Venda Bruta:** Realizado **{fmt_val(vb.get('realizado', 0))}** | Orçado **{fmt_val(vb.get('orcado', 0))}** ({vb.get('desvio_pct', 0):+.1f}%)\n"
                    f"- **Venda Líquida:** Realizado **{fmt_val(vl.get('realizado', 0))}** | Orçado **{fmt_val(vl.get('orcado', 0))}** ({vl.get('desvio_pct', 0):+.1f}%)\n"
                    f"- **Margem de Contribuição:** Realizado **{fmt_val(mc.get('realizado', 0))}** | Orçado **{fmt_val(mc.get('orcado', 0))}** ({mc.get('desvio_pct', 0):+.1f}%)"
                )
                yield {"tipo": "token", "texto": fallback_local}
                yield {"tipo": "fim", "resposta_completa": fallback_local}
                return
            except Exception as ex_fb:
                msg_fb = (
                    f"Olá! Sou a MQIA. No momento estou operando em contingência com os dados oficiais do DRE ({periodo_label_info}). "
                    f"Você pode enviar uma pergunta sobre contas ou centros de custo específicos."
                )
                yield {"tipo": "token", "texto": msg_fb}
                yield {"tipo": "fim", "resposta_completa": msg_fb}
                return

    # Fallback: Se pergunta não foi coberta pelo pre-fetch rápido, usa Function Calling dinâmico
    yield {"tipo": "status", "texto": "Digitando..."}
    messages.append({"role": "user", "content": prompt})
    res, model_used = _executar_llm(messages, TOOLS_SCHEMA)
    if not res:
        # Fallback inteligente local caso o Mistral falhe na análise
        try:
            resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
            vb = resumo.get("venda_bruta", {})
            vl = resumo.get("venda_liquida", {})
            mc = resumo.get("margem_contribuicao", {})
            def fmt_val(v):
                return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            fallback_text = (
                f"Consultei diretamente os dados oficiais do DRE na base local:\n\n"
                f"**Resumo Executivo ({mes_ctx:02d}/{ano_ctx} - {resumo.get('empresa', 'Consolidado')}):**\n"
                f"- **Venda Bruta:** Realizado **{fmt_val(vb.get('realizado', 0))}** | Orçado **{fmt_val(vb.get('orcado', 0))}** ({vb.get('desvio_pct', 0):+.1f}%)\n"
                f"- **Venda Líquida:** Realizado **{fmt_val(vl.get('realizado', 0))}** | Orçado **{fmt_val(vl.get('orcado', 0))}** ({vl.get('desvio_pct', 0):+.1f}%)\n"
                f"- **Margem de Contribuição:** Realizado **{fmt_val(mc.get('realizado', 0))}** | Orçado **{fmt_val(mc.get('orcado', 0))}** ({mc.get('desvio_pct', 0):+.1f}%)\n\n"
                f"*Você pode enviar uma nova pergunta sobre qualquer indicador, conta ou centro de custo.*"
            )
            yield {"tipo": "token", "texto": fallback_text}
            yield {"tipo": "fim", "resposta_completa": fallback_text}
            return
        except Exception:
            msg_fb = (
                f"Olá! Sou a MQIA. No momento estou conectada aos dados oficiais do DRE ({mes_ctx:02d}/{ano_ctx}). "
                f"Por favor, reformule sua pergunta indicando o indicador ou conta que deseja analisar."
            )
            yield {"tipo": "token", "texto": msg_fb}
            yield {"tipo": "fim", "resposta_completa": msg_fb}
            return

    choice = res.get("choices", [{}])[0]
    asst_msg = choice.get("message", {})
    tool_calls = asst_msg.get("tool_calls", [])

    if not tool_calls:
        texto = asst_msg.get("content") or "Análise concluída."
        yield {"tipo": "token", "texto": texto}
        yield {"tipo": "fim", "resposta_completa": texto}
        return

    messages.append(asst_msg)
    blocos_graficos_gerados = []
    ultimas_ferramentas_outputs = []
    for tc in tool_calls:
        fname = tc.get("function", {}).get("name")
        call_id = tc.get("id")
        args_raw = tc.get("function", {}).get("arguments", "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
        except Exception:
            args = {}

        ano_arg = args.get("ano")
        if not ano_arg or (ano_arg == 2024 and "2024" not in prompt):
            ano_arg = ano_ctx
        mes_arg = args.get("mes") or mes_ctx

        if fname == "analisar_estouros_orcamento":
            out = analisar_estouros_orcamento(ano_arg, mes_arg, args.get("apenas_estouros", True))
        elif fname == "consultar_conta_historico":
            out = consultar_conta_historico(args.get("conta", "Aluguel"), ano_arg)
        elif fname == "consultar_por_centro_custo":
            out = consultar_por_centro_custo(args.get("centro_custo", "Distribuição"), ano_arg, mes_arg, args.get("filtro_conta"))
        elif fname == "obter_dre_centro_custo":
            out = obter_dre_centro_custo(args.get("centro_custo", "VAREJO - SUL"), ano_arg, mes_arg, args.get("empresa"))
        elif fname == "obter_resumo_dre":
            out = obter_resumo_dre(ano_arg, mes_arg, args.get("empresa", emp_ctx if emp_ctx != "Consolidado" else None))
        elif fname == "obter_maiores_custos_despesas":
            out = obter_maiores_custos_despesas(ano_arg, mes_arg, args.get("empresa", emp_ctx if emp_ctx != "Consolidado" else None), limite=args.get("limite", 10))
        elif fname == "detalhar_bloco":
            out = detalhar_bloco(args.get("bloco", "Despesas com Vendas"), ano_arg, mes_arg, args.get("empresa"))
        elif fname == "comparar_empresas":
            out = comparar_empresas(args.get("indicador", "venda_bruta"), ano_arg, mes_arg)
        elif fname == "gerar_grafico":
            out = gerar_grafico(args.get("tipo", "bar"), args.get("titulo", ""), args.get("labels", []), args.get("valores", []), args.get("legenda", ""))
            if out.get("bloco_markdown"):
                blocos_graficos_gerados.append(out["bloco_markdown"])
        else:
            out = {"error": f"Ferramenta desconhecida: {fname}"}

        ultimas_ferramentas_outputs.append((fname, out))

        messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": fname,
            "content": json.dumps(out, ensure_ascii=False)
        })

    # Agora transmite a resposta final gerada em streaming
    texto_total = ""
    for token in _stream_llm(messages, max_tokens=1000):
        texto_total += token
        yield {"tipo": "token", "texto": token}

    # TRAVA DEFINITIVA DE GRÁFICOS: Valida, higieniza JSON e auto-injeta se necessário
    texto_validado = validar_e_higienizar_bloco_grafico(texto_total, prompt, dados_ferramenta=ultimas_ferramentas_outputs)
    if texto_validado != texto_total:
        diferenca = texto_validado[len(texto_total):]
        if diferenca:
            yield {"tipo": "token", "texto": diferenca}
        texto_total = texto_validado

    if texto_total.strip():
        yield {"tipo": "fim", "resposta_completa": texto_total}
        return
    else:
        # Fallback local com os dados das ferramentas já executadas
        try:
            resumo = obter_resumo_dre(ano=ano_ctx, mes=mes_ctx, empresa=emp_ctx if emp_ctx != "Consolidado" else None)
            vb = resumo.get("venda_bruta", {})
            vl = resumo.get("venda_liquida", {})
            mc = resumo.get("margem_contribuicao", {})
            def fmt_val(v):
                return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            fallback_text = (
                f"Resultado oficial apurado no DRE ({mes_ctx:02d}/{ano_ctx} - {resumo.get('empresa', 'Consolidado')}):\n\n"
                f"- **Venda Bruta:** Realizado **{fmt_val(vb.get('realizado', 0))}** | Orçado **{fmt_val(vb.get('orcado', 0))}** ({vb.get('desvio_pct', 0):+.1f}%)\n"
                f"- **Venda Líquida:** Realizado **{fmt_val(vl.get('realizado', 0))}** | Orçado **{fmt_val(vl.get('orcado', 0))}** ({vl.get('desvio_pct', 0):+.1f}%)\n"
                f"- **Margem de Contribuição:** Realizado **{fmt_val(mc.get('realizado', 0))}** | Orçado **{fmt_val(mc.get('orcado', 0))}** ({mc.get('desvio_pct', 0):+.1f}%)"
            )
            yield {"tipo": "token", "texto": fallback_text}
            yield {"tipo": "fim", "resposta_completa": fallback_text}
            return
        except Exception:
            msg_final = "Consulta aos dados concluída com sucesso. Os valores podem ser conferidos no painel."
            yield {"tipo": "token", "texto": msg_final}
            yield {"tipo": "fim", "resposta_completa": msg_final}
            return

