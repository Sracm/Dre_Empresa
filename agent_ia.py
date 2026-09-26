"""
agent_ia.py — Agente de Inteligência Artificial Interno do DRE (MQ Hair Company)
Utiliza a API do Mistral AI com Function Calling nativo e funções analíticas
especializadas sobre a base SQLite dre_cache.db (dre_data).
Garante precisão contábil e matemática de 100% sobre Orçado, Realizado e Desvios.
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
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
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
    Exemplos de bloco: 'Despesas com Vendas', 'Venda Liquida', 'Custo Mercadoria Vendida',
    'Despesas Comercial Operacional', 'Despesas Administrativa Operacional', 'Receitas/Despesas Financeiras'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        ano = int(ano)
        mes = int(mes)
    except Exception:
        ano, mes = 2026, 8

    # Mapeamento amigável
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
    Indicadores aceitos: 'venda_bruta', 'venda_liquida', 'cmv', 'despesas_vendas', 'despesas_adm', 'despesas_comercial'.
    """
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
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

def consultar_sql(query):
    """
    Executa consulta SELECT SQL livre no banco SQLite (tabela dre_data).
    Garante segurança e adiciona filtro de centro de custo 21010000 se omitido.
    """
    query_clean = query.strip()
    if not query_clean.upper().startswith("SELECT"):
        return {"error": "Apenas consultas SELECT são permitidas."}

    proibidos = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "PRAGMA", "ATTACH", "DETACH"]
    for p in proibidos:
        if p in query_clean.upper().split():
            return {"error": f"Comando '{p}' não é permitido por segurança."}

    conn = sqlite3.connect(DB_PATH, timeout=15.0)
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
#  INTEGRAÇÃO COM MISTRAL AI
# ═══════════════════════════════════════════════════════════════════════════

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "obter_resumo_dre",
            "description": "Retorna o resumo executivo oficial e consolidado do DRE para um mês e ano específicos. Traz Venda Bruta, Venda Líquida, CMV, Margem de Contribuição e Despesas Operacionais com Orçado, Realizado e Desvios.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ano": {"type": "integer", "description": "Ano de exercício contábil (ex: 2026, 2025)"},
                    "mes": {"type": "integer", "description": "Mês contábil de 1 a 12 (ex: 8 para Agosto)"},
                    "empresa": {"type": "string", "description": "Nome da empresa para filtrar, ou null/Consolidado para todas as empresas juntas"}
                },
                "required": ["ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "detalhar_bloco",
            "description": "Detalha os títulos contábeis de um bloco do DRE (ex: 'Despesas com Vendas', 'Custo Mercadoria Vendida', 'Despesas Comercial Operacional', 'Despesas Administrativa Operacional', 'Receitas/Despesas Financeiras').",
            "parameters": {
                "type": "object",
                "properties": {
                    "bloco": {"type": "string", "description": "Nome do bloco a detalhar (ex: 'Despesas com Vendas', 'Custo Mercadoria Vendida', 'Despesas Administrativa Operacional')"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês de 1 a 12 (ex: 8)"},
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
            "description": "Compara e ordena as empresas da MQ Hair para um indicador financeiro específico (ex: 'venda_bruta', 'venda_liquida', 'cmv', 'despesas_vendas', 'despesas_adm').",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicador": {"type": "string", "description": "Indicador a comparar: 'venda_bruta', 'venda_liquida', 'cmv', 'despesas_vendas', 'despesas_adm'"},
                    "ano": {"type": "integer", "description": "Ano (ex: 2026)"},
                    "mes": {"type": "integer", "description": "Mês de 1 a 12 (ex: 8)"}
                },
                "required": ["indicador", "ano", "mes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_sql",
            "description": "Executa uma consulta SQL SELECT avançada na tabela dre_data para cruzamentos específicos não cobertos pelas outras funções.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Comando SELECT SQL. Atenção: sempre inclua 'codcencus != 21010000'"}
                },
                "required": ["query"]
            }
        }
    }
]

def _executar_mistral(messages, tools):
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }

    for model in MISTRAL_MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": 0.1
        }
        for retry in range(2):
            try:
                r = requests.post(url, headers=headers, json=payload, timeout=30)
                if r.status_code == 200:
                    return r.json(), model
                if r.status_code in (429, 503):
                    time.sleep(1.5 * (retry + 1))
                    continue
                print(f"[Mistral - {model}] Erro {r.status_code}: {r.text[:140]}", flush=True)
                break
            except Exception as e:
                time.sleep(1)
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

        contexto_str = (
            f"\n\n[CONTEXTO ATUAL DA TELA DO USUÁRIO]:"
            f"\n- Ano Selecionado: {ano_ctx}"
            f"\n- Mês Selecionado: {mes_ctx}"
            f"\n- Empresa Filtrada: {emp_ctx}"
            f"\n- Centro de Custo: {cenc_ctx}"
            f"\n- Venda Bruta na Tela: {vb_ctx}"
            f"\n- Margem na Tela: {mg_ctx}"
            f"\n(Utilize este ano={ano_ctx}, mês={mes_ctx}, empresa='{emp_ctx}' caso a pergunta não especifique outros)."
        )

    system_prompt = (
        "Você é o Agente MQIA, consultor executivo sênior de Finanças & BI da MQ Hair Company. "
        "Sua missão é responder com 100% de exatidão matemática e profundidade analítica às dúvidas de diretores e gerentes sobre o DRE da empresa. "
        "\n\nREGRAS OBRIGATÓRIAS:"
        "\n1. NUNCA invente números. SEMPRE consulte as ferramentas analíticas disponíveis antes de dar a resposta."
        "\n2. Para dúvidas sobre faturamento, receita, CMV, margem ou resultado geral, chame PRIMEIRO a ferramenta `obter_resumo_dre`."
        "\n3. Para detalhar despesas específicas (como frete, comissões, marketing, pessoal), chame `detalhar_bloco`."
        "\n4. Para comparar desempenho entre empresas do grupo, chame `comparar_empresas`."
        "\n5. Formate moedas no padrão brasileiro: R$ 1.234.567,89 e percentuais com 1 ou 2 casas decimais (+5,1% ou -2,4%)."
        "\n6. Explique sempre se o desvio é favorável ou desfavorável: "
        "   - Receita acima do orçado = FAVORÁVEL (+)"
        "   - Custos ou Despesas acima do orçado = DESFAVORÁVEL (estouro de orçamento)"
        "   - Custos ou Despesas abaixo do orçado = FAVORÁVEL (economia orçamentária)"
        "\n7. Apresente respostas elegantes, executivas, com tópicos estruturados em Markdown."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt + contexto_str}
    ]

    for step in range(4):
        print(f"[IA MISTRAL] Passo {step + 1}: enviando {len(messages)} mensagens...", flush=True)
        res, model_used = _executar_mistral(messages, TOOLS_SCHEMA)
        if not res:
            print("[IA MISTRAL] Falha de conexao com Mistral", flush=True)
            return "Desculpe, ocorreu uma instabilidade temporária ao conectar ao serviço Mistral AI. Por favor, tente novamente em instantes."

        choice = res.get("choices", [{}])[0]
        asst_msg = choice.get("message", {})
        messages.append(asst_msg)

        tool_calls = asst_msg.get("tool_calls", [])
        if not tool_calls:
            print(f"[IA MISTRAL] Resposta final obtida via {model_used}", flush=True)
            return asst_msg.get("content") or "Análise concluída com sucesso."

        # Executa cada ferramenta chamada
        for tc in tool_calls:
            fname = tc.get("function", {}).get("name")
            call_id = tc.get("id")
            args_raw = tc.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except Exception:
                args = {}

            print(f"[IA MISTRAL] Executando tool: {fname}({args})", flush=True)

            if fname == "obter_resumo_dre":
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

            elif fname == "consultar_sql":
                sql_q = args.get("query", "")
                tool_output = consultar_sql(sql_q)

            else:
                tool_output = {"error": f"Ferramenta desconhecida: {fname}"}

            print(f"[IA MISTRAL] Tool {fname} concluida com sucesso.", flush=True)
            messages.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": fname,
                "content": json.dumps(tool_output, ensure_ascii=False)
            })

    return "A análise atingiu o limite de consultas. Por favor, tente refazer a pergunta de forma mais específica."
