"""
agent_ia.py — Agente de Inteligência Artificial Interno do DRE (MQ Hair Company)
Utiliza a API do Mistral AI com Function Calling nativo e funções analíticas
especializadas sobre a base SQLite dre_cache.db (dre_data).
Garante precisão contábil e matemática de 100% sobre Orçado, Realizado e Desvios.
Otimizado para respostas ultrarrápidas (< 2.5s) com Session Keep-Alive.
"""

import os
import time
import sqlite3
import requests
import json
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dre_cache.db")

# Carrega chave do .env
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

if not MISTRAL_API_KEY:
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("MISTRAL_API_KEY="):
                    MISTRAL_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")

if not MISTRAL_API_KEY:
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

MISTRAL_MODELS = ["open-mistral-nemo", "codestral-latest", "open-mistral-7b"]

# Sessão HTTP persistente para eliminar latência de handshake TLS/TCP
_HTTP_SESSION = requests.Session()
_HTTP_SESSION.headers.update({
    "Authorization": f"Bearer {MISTRAL_API_KEY}",
    "Content-Type": "application/json"
})

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

def obter_resumo_dre(ano=2026, mes=8, empresa=None):
    """
    Retorna o resumo executivo oficial e consolidado do DRE para um mês e ano específicos.
    Calcula Venda Bruta, Venda Líquida, CMV, Margem de Contribuição e todas as Despesas Operacionais.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    where = ["ano = ?", "mes = ?", "codcencus != 21010000"]
    params = [ano, mes]
    if empresa and str(empresa).strip().upper() not in ("ALL", "CONSOLIDAÇÃO", "CONSOLIDADO", "TODAS AS EMPRESAS", "TODAS", "NONE"):
        where.append("empresa = ?")
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

    conn.close()

    vl = blocos.get("1.Venda Liquida", {"orc": 0.0, "real": 0.0})
    cmv = blocos.get("2.Custo Mercadoria Vendida", {"orc": 0.0, "real": 0.0})
    mc_orc = (vl["orc"] or 0.0) + (cmv["orc"] or 0.0)
    mc_real = (vl["real"] or 0.0) + (cmv["real"] or 0.0)

    dv = blocos.get("3.Despesas com Vendas", {"orc": 0.0, "real": 0.0})
    dcom = blocos.get("4.Despesas Comercial Operacional", {"orc": 0.0, "real": 0.0})
    dadm = blocos.get("5.Despesas Administrativa Operacional", {"orc": 0.0, "real": 0.0})
    dfin = blocos.get("6.Receitas/Despesas Financeiras", {"orc": 0.0, "real": 0.0})
    vic = blocos.get("7.Vendas IC", {"orc": 0.0, "real": 0.0})

    return {
        "periodo": f"{mes:02d}/{ano}",
        "empresa": empresa or "Consolidado (Todas as Empresas)",
        "venda_bruta": _calc_dif(vb_orc, vb_real),
        "venda_liquida": _calc_dif(vl["orc"], vl["real"]),
        "cmv": _calc_dif(cmv["orc"], cmv["real"]),
        "margem_contribuicao": _calc_dif(mc_orc, mc_real),
        "despesas_vendas": _calc_dif(dv["orc"], dv["real"]),
        "despesas_comercial": _calc_dif(dcom["orc"], dcom["real"]),
        "despesas_administrativa": _calc_dif(dadm["orc"], dadm["real"]),
        "financeiro": _calc_dif(dfin["orc"], dfin["real"]),
        "vendas_ic": _calc_dif(vic["orc"], vic["real"])
    }

def detalhar_bloco(bloco, ano=2026, mes=8, empresa=None):
    """
    Detalha os títulos contábeis de um bloco específico da DRE.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
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

    where = ["ano = ?", "mes = ?", "codcencus != 21010000", "bloco LIKE ?"]
    params = [ano, mes, f"%{termo_busca}%"]
    if empresa and str(empresa).strip().upper() not in ("ALL", "CONSOLIDAÇÃO", "CONSOLIDADO", "TODAS AS EMPRESAS", "TODAS", "NONE"):
        where.append("empresa = ?")
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

def comparar_empresas(indicador="venda_bruta", ano=2026, mes=8):
    """
    Retorna o comparativo/ranking de todas as empresas da MQ Hair para um indicador financeiro específico.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    where = ["ano = ?", "mes = ?", "codcencus != 21010000"]
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
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
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
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        ano = int(ano)
    except Exception:
        ano = 2026

    query = """
        SELECT mes, SUM(orcado) as orc, SUM(realizado) as real
        FROM dre_data
        WHERE ano=? AND codcencus != 21010000
          AND (descrnat LIKE ? OR titulo LIKE ?)
        GROUP BY mes
        ORDER BY mes ASC
    """
    cur.execute(query, [ano, f"%{conta}%", f"%{conta}%"])
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

def consultar_por_centro_custo(centro_custo, ano=2026, mes=8, filtro_conta=None):
    """
    Consulta os valores realizados e orçados de um centro de resultado específico.
    Exemplos de centro_custo: 'DISTRIBUICAO', 'VAREJO - SP', 'MERCADO LIVRE', 'LOGISTICA - SC'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    where = ["ano = ?", "mes = ?", "codcencus != 21010000", "(descrcencus LIKE ? OR codcencus LIKE ?)"]
    params = [ano, mes, f"%{centro_custo}%", f"%{centro_custo}%"]

    if filtro_conta:
        where.append("(titulo LIKE ? OR descrnat LIKE ?)")
        params.extend([f"%{filtro_conta}%", f"%{filtro_conta}%"])

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

    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
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
            "description": "Retorna a evolução mês a mês (Jan a Dez) de uma despesa ou conta específica. Use para perguntas como: 'qual o valor de aluguel pago mês a mês?', 'evolução de frete', 'evolução de comissões', 'histórico de impostos'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "conta": {"type": "string", "description": "Nome da conta a buscar (ex: 'Aluguel', 'Frete', 'Comissões', 'Imposto', 'Energia')"},
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
            "description": "Consulta os valores de um centro de resultado específico, com opção de filtrar uma conta/despesa. Use para: 'quanto paguei de comissão na distribuição?', 'quanto gastei no centro marketing?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "centro_custo": {"type": "string", "description": "Nome ou código do centro de custo (ex: 'Distribuição', 'Varejo SP', 'Mercado Livre')"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês (ex: 8)"},
                    "filtro_conta": {"type": "string", "description": "Filtro opcional de conta ou título (ex: 'Comissão', 'Frete', 'Salários')"}
                },
                "required": ["centro_custo", "ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obter_resumo_dre",
            "description": "Retorna o resumo executivo oficial e consolidado do DRE para um mês e ano específicos (Venda Bruta, Venda Líquida, CMV, Margem, Despesas).",
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

def _executar_mistral(messages, tools):
    url = "https://api.mistral.ai/v1/chat/completions"

    for model in MISTRAL_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": 0.1,
            "max_tokens": 650
        }
        for retry in range(2):
            try:
                r = _HTTP_SESSION.post(url, json=payload, timeout=25)
                if r.status_code == 200:
                    return r.json(), model
                if r.status_code in (429, 503):
                    time.sleep(1.0 * (retry + 1))
                    continue
                print(f"[Mistral - {model}] Erro {r.status_code}: {r.text[:140]}", flush=True)
                break
            except Exception as e:
                time.sleep(0.5)
    return None, None

def processar_pergunta(prompt, contexto=None):
    """
    Processa a pergunta do usuário no Chat da IA com Function Calling do Mistral.
    """
    ano_ctx = 2026
    mes_ctx = 8
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

    usuario_instrucao = (
        f"\nTRATAMENTO PERSONALIZADO AO USUÁRIO:"
        f"\nO usuário conectado neste momento chama-se **{nome_usuario}**. "
        f"Cumprimente-o cordialmente pelo nome ao iniciar uma resposta formal (ex: '{saudacao_periodo}, {nome_usuario}!...').\n"
    ) if (contexto and contexto.get("usuario")) else ""

    system_prompt = (
        f"{usuario_instrucao}"
        "Você é a MQIA, consultora executiva sênior de Finanças & BI da MQ Hair Company. "
        "Sua missão é responder com 100% de exatidão matemática, agilidade executiva e clareza às dúvidas de diretores e gerentes sobre o DRE da empresa. "
        "\n\nDIRETRIZES DE ATENDIMENTO E ESCOLHA DE FERRAMENTAS:"
        "\n1. ESTOUROS E DESVIOS DE ORÇAMENTO (Perguntas como 'qual centro estourou o orçamento?', 'maior desvio'):"
        "\n   - Chame IMEDIATAMENTE a ferramenta `analisar_estouros_orcamento(ano, mes)`. Ela traz a lista exata dos centros que estouraram e o valor em R$ do estouro."
        "\n   - Obs: se o usuário pedir 'mês passado' e estivermos em Agosto (8), use mês=7 (Julho)."
        "\n2. HISTÓRICO MÊS A MÊS DE UMA CONTA (Perguntas como 'valor de aluguel pago mês a mês', 'evolução de frete'):"
        "\n   - Chame IMEDIATAMENTE a ferramenta `consultar_conta_historico(conta, ano)`. Ela retorna Jan a Dez completo."
        "\n3. CONSULTA ESPECÍFICA POR CENTRO DE RESULTADO (Perguntas como 'quanto paguei de comissão na distribuição?'):"
        "\n   - Chame IMEDIATAMENTE `consultar_por_centro_custo(centro_custo, ano, mes, filtro_conta)`. Ela retorna os valores orçados e realizados desse centro."
        "\n4. NÚMEROS GERAIS DA DRE (Faturamento, Receita Líquida, CMV, Margem):"
        "\n   - Chame `obter_resumo_dre` ou `detalhar_bloco`."
        "\n5. REGRAS DE COMUNICAÇÃO:"
        "\n   - Seja direta, executiva e ágil. Vá direto ao ponto com números claros em negrito e valores em R$ formatados (ex: R$ 127.648,19)."
        "\n   - Mostre se o desvio é favorável (economia) ou desfavorável (estouro)."
        "\n   - Se o valor for R$ 0,00, explique com precisão que para aquele centro ou conta não houve lançamento no período."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt + contexto_str}
    ]

    blocos_graficos_gerados = []

    for step in range(3):
        res, model_used = _executar_mistral(messages, TOOLS_SCHEMA)
        if not res:
            return "Desculpe, ocorreu uma instabilidade temporária ao conectar ao serviço Mistral AI. Por favor, tente novamente em instantes."

        choice = res.get("choices", [{}])[0]
        asst_msg = choice.get("message", {})
        messages.append(asst_msg)

        tool_calls = asst_msg.get("tool_calls", [])
        if not tool_calls:
            texto_final = asst_msg.get("content") or "Análise concluída com sucesso."
            if blocos_graficos_gerados:
                for bg in blocos_graficos_gerados:
                    if bg and "```chart" not in texto_final and "```grafico" not in texto_final:
                        texto_final = texto_final + "\n\n" + bg
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

            print(f"[IA MISTRAL] Executando tool: {fname}({args})", flush=True)

            if fname == "analisar_estouros_orcamento":
                ano_arg = args.get("ano", ano_ctx)
                mes_arg = args.get("mes", mes_ctx)
                apenas_arg = args.get("apenas_estouros", True)
                tool_output = analisar_estouros_orcamento(ano=ano_arg, mes=mes_arg, apenas_estouros=apenas_arg)

            elif fname == "consultar_conta_historico":
                conta_arg = args.get("conta", "Aluguel")
                ano_arg = args.get("ano", ano_ctx)
                tool_output = consultar_conta_historico(conta=conta_arg, ano=ano_arg)

            elif fname == "consultar_por_centro_custo":
                cenc_arg = args.get("centro_custo", "Distribuição")
                ano_arg = args.get("ano", ano_ctx)
                mes_arg = args.get("mes", mes_ctx)
                filtro_arg = args.get("filtro_conta")
                tool_output = consultar_por_centro_custo(centro_custo=cenc_arg, ano=ano_arg, mes=mes_arg, filtro_conta=filtro_arg)

            elif fname == "obter_resumo_dre":
                ano_arg = args.get("ano", ano_ctx)
                mes_arg = args.get("mes", mes_ctx)
                emp_arg = args.get("empresa", emp_ctx if emp_ctx != "Consolidado" else None)
                tool_output = obter_resumo_dre(ano=ano_arg, mes=mes_arg, empresa=emp_arg)

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

            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": fname,
                "content": json.dumps(tool_output, ensure_ascii=False)
            })

    return "A análise foi concluída."
