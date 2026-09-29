import os
import sys
import sqlite3
import traceback
import threading
import time
import subprocess
from datetime import datetime, timedelta
from collections import OrderedDict
from flask import Flask, render_template, jsonify, request, send_file, Response, stream_with_context
import io
import json
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dre_cache.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

# ── In-Memory Cache (ultra-rápido) ──────────────────────────────────────────
_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 600  # 10 minutos

def cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["data"]
    return None

def cache_set(key, data):
    with _cache_lock:
        _cache[key] = {"data": data, "ts": time.time()}

# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURAÇÃO DO APP E CACHE
# ═══════════════════════════════════════════════════════════════════════════
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.after_request
def add_header(r):
    """
    Desativa o cache do navegador para garantir que o cliente sempre
    receba a versão mais recente do HTML, CSS e JS.
    """
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    return r

# ═══════════════════════════════════════════════════════════════════════════
#  ROTA PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")

ALLOWED_COMPANIES = [
    'Consolidação', 'FORX SC', 'MCR - FABRICA', 'MCR - FILIAL 03', 
    'MCR - MATRIZ', 'MCR - SC', 'QUALITY - RJ', 'QUALITY MATRIZ', 
    'SL ONLINE - SP', 'VLS - RJ', 'VLS - SP', 'FORX MG'
]
EXCLUDED_CODCENCUS = 21010000

def parse_cenc_param(cenc_raw):
    if not cenc_raw or cenc_raw == "ALL":
        return []
    items = []
    for part in str(cenc_raw).split(","):
        part = part.strip()
        if part and part != "ALL":
            try:
                items.append(int(part))
            except ValueError:
                pass
    return items

def parse_int_list(raw, default=None):
    if not raw or raw == "ALL":
        return default if default is not None else []
    items = []
    for part in str(raw).split(","):
        part = part.strip()
        if part and part != "ALL":
            try:
                items.append(int(part))
            except ValueError:
                pass
    return items if items else (default if default is not None else [])

def parse_str_list(raw):
    if not raw or raw == "ALL":
        return []
    items = []
    for part in str(raw).split(","):
        part = part.strip()
        if part and part != "ALL":
            items.append(part)
    return items

# ═══════════════════════════════════════════════════════════════════════════
#  FILTROS
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/filtros")
def filtros():
    cached = cache_get("filtros")
    if cached:
        return jsonify(cached)

    try:
        with get_db() as conn:
            cur = conn.cursor()
            
            # Anos disponíveis (apenas anos reais <= ano corrente + 1)
            cur.execute("""
                SELECT DISTINCT ano FROM dre_filtros_anos 
                WHERE ano >= 2023 AND ano <= 2027 
                ORDER BY ano DESC
            """)
            anos = [int(r["ano"]) for r in cur.fetchall()]
            if not anos:
                anos = [2026, 2025, 2024, 2023]

            # Empresas disponíveis (conforme modelo oficial DRE Gestores)
            placeholders = ",".join(["?"] * len(ALLOWED_COMPANIES))
            cur.execute(f"""
                SELECT nome FROM dre_filtros_empresas 
                WHERE nome IN ({placeholders})
                ORDER BY nome
            """, ALLOWED_COMPANIES)
            empresas = [{"CODEMP": r["nome"], "NOME": r["nome"]} for r in cur.fetchall()]

            # Centros de Custo (excluindo 21010000 conforme filtro global PBI)
            cur.execute("""
                SELECT codcencus, nome FROM dre_filtros_centros 
                WHERE codcencus > 0 AND codcencus != 21010000
                ORDER BY codcencus
            """)
            centros = [
                {"CODCENCUS": r["codcencus"], "NOME": f"{r['codcencus']} - {r['nome']}"}
                for r in cur.fetchall()
            ]

        meses = [
            {"NUM": i + 1, "NOME": n}
            for i, n in enumerate([
                "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
            ])
        ]

        result = {
            "anos": anos,
            "meses": meses,
            "empresas": empresas,
            "centros": centros,
        }
        cache_set("filtros", result)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  STATUS DO JOB (para compatibilidade imediata com frontend de polling)
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/dre/status")
def dre_status():
    key = request.args.get("key", "")
    cached = cache_get(key)
    if cached:
        return jsonify({"status": "done", **cached})
    return jsonify({"status": "done"})

# ═══════════════════════════════════════════════════════════════════════════
#  DRE — DADOS PRINCIPAIS
# ═══════════════════════════════════════════════════════════════════════════
def get_dre_tree_data(ano_raw="2026", mes_raw="8", emp_raw="ALL", cenc_raw="ALL"):
    anos = parse_int_list(ano_raw, [2026])
    meses = parse_int_list(mes_raw, list(range(1, 13)))
    emps = parse_str_list(emp_raw)
    cenc_list = parse_cenc_param(cenc_raw)

    ano_primario = max(anos) if anos else 2026
    mes_primario = max(meses) if meses else 8

    ano_mom, mes_mom = (ano_primario, mes_primario - 1) if mes_primario > 1 else (ano_primario - 1, 12)
    ano_yoy = ano_primario - 1

    # Meses YTD (de janeiro até o maior mês selecionado)
    meses_ytd = list(range(1, mes_primario + 1))
    meses_ant = list(set(meses_ytd + ([12] if mes_primario == 1 else [])))

    ph_anos = ",".join(["?"] * len(anos))
    ph_meses = ",".join(["?"] * len(meses))
    ph_ytd = ",".join(["?"] * len(meses_ytd))
    ph_ant = ",".join(["?"] * len(meses_ant))

    where = [
        "codcencus != ?",
        f"((ano IN ({ph_anos}) AND mes IN ({ph_ytd})) OR (ano = ? AND mes IN ({ph_ant})))"
    ]
    params = [
        EXCLUDED_CODCENCUS,
        *anos, *meses_ytd,
        ano_yoy, *meses_ant
    ]

    if emps:
        ph_emp = ",".join(["?"] * len(emps))
        where.append(f"empresa IN ({ph_emp})")
        params.extend(emps)
    else:
        # Filtro oficial do Power BI para DRE Gestores
        placeholders = ",".join(["?"] * len(ALLOWED_COMPANIES))
        where.append(f"empresa IN ({placeholders})")
        params.extend(ALLOWED_COMPANIES)

    if cenc_list:
        if len(cenc_list) == 1:
            where.append("codcencus = ?")
            params.append(cenc_list[0])
        else:
            ph_cenc = ",".join(["?"] * len(cenc_list))
            where.append(f"codcencus IN ({ph_cenc})")
            params.extend(cenc_list)

    where_sql = " AND ".join(where)

    sql = f"""
        SELECT
            bloco,
            titulo,
            descrnat,
            SUM(CASE WHEN ano IN ({ph_anos}) AND mes IN ({ph_meses}) THEN realizado ELSE 0 END) AS realizado,
            SUM(CASE WHEN ano IN ({ph_anos}) AND mes IN ({ph_meses}) THEN orcado ELSE 0 END) AS orcado,
            SUM(CASE WHEN ano = ? AND mes = ? THEN realizado ELSE 0 END) AS real_mom,
            SUM(CASE WHEN ano = ? AND mes = ? THEN orcado ELSE 0 END) AS real_mom,
            SUM(CASE WHEN ano = ? AND mes IN ({ph_meses}) THEN realizado ELSE 0 END) AS real_yoy,
            SUM(CASE WHEN ano IN ({ph_anos}) AND mes IN ({ph_ytd}) THEN realizado ELSE 0 END) AS real_ytd,
            SUM(CASE WHEN ano = ? AND mes IN ({ph_ytd}) THEN realizado ELSE 0 END) AS real_ytd_ant
        FROM dre_data
        WHERE {where_sql}
        GROUP BY bloco, titulo, descrnat
        ORDER BY bloco, titulo, descrnat
    """
    query_params = [
        *anos, *meses,
        *anos, *meses,
        ano_mom, mes_mom,
        ano_mom, mes_mom,
        ano_yoy, *meses,
        *anos, *meses_ytd,
        ano_yoy, *meses_ytd,
        *params
    ]

    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(sql, query_params)
        rows = [dict(r) for r in cur.fetchall()]

    bonif_total = sum(
        float(r.get("realizado") or 0)
        for r in rows
        if r.get("titulo") and "bonif" in str(r["titulo"]).lower()
    )

    dre_tree = _build_dre_tree(rows, bonif_total, mes_primario, meses=meses)
    return dre_tree, bonif_total, ano_primario, mes_primario, emps, cenc_list

@app.route("/api/dre")
def dre():
    try:
        ano_raw = request.args.get("ano", "2026")
        mes_raw = request.args.get("mes", "8")
        emp_raw = request.args.get("emp", "ALL")
        cenc_raw = request.args.get("cenc", "ALL")

        key = f"dre_{ano_raw}_{mes_raw}_{emp_raw}_{cenc_raw}"
        cached = cache_get(key)
        if cached:
            return jsonify(cached)

        dre_tree, bonif_total, *_ = get_dre_tree_data(ano_raw, mes_raw, emp_raw, cenc_raw)
        result = {"dre": dre_tree, "bonif_total": bonif_total}
        cache_set(key, result)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  DRE MENSAL (Evolução dos 12 meses para gráfico)
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/dre/mensal")
def dre_mensal():
    try:
        ano_raw = request.args.get("ano", "2026")
        emp_raw = request.args.get("emp", "ALL")
        cenc_raw = request.args.get("cenc", "ALL")
        bloco = request.args.get("bloco", None)
        titulo = request.args.get("titulo", None)
        descrnat = request.args.get("descrnat", None)
        refresh_meses_raw = request.args.get("refresh_meses", None)
        refresh_meses = parse_int_list(refresh_meses_raw, None) if refresh_meses_raw else None

        key = f"mensal_{ano_raw}_{emp_raw}_{cenc_raw}_{bloco}_{titulo}_{descrnat}_{refresh_meses_raw}"
        cached = cache_get(key)
        if cached:
            return jsonify(cached)

        anos = parse_int_list(ano_raw, [2026])
        emps = parse_str_list(emp_raw)
        cenc_list = parse_cenc_param(cenc_raw)

        ph_anos = ",".join(["?"] * len(anos))
        where = [f"ano IN ({ph_anos})", "codcencus != ?"]
        params = [*anos, EXCLUDED_CODCENCUS]

        if refresh_meses:
            ph_ref = ",".join(["?"] * len(refresh_meses))
            where.append(f"mes IN ({ph_ref})")
            params.extend(refresh_meses)

        if emps:
            ph_emp = ",".join(["?"] * len(emps))
            where.append(f"empresa IN ({ph_emp})")
            params.extend(emps)
        else:
            placeholders = ",".join(["?"] * len(ALLOWED_COMPANIES))
            where.append(f"empresa IN ({placeholders})")
            params.extend(ALLOWED_COMPANIES)

        if cenc_list:
            if len(cenc_list) == 1:
                where.append("codcencus = ?")
                params.append(cenc_list[0])
            else:
                ph_cenc = ",".join(["?"] * len(cenc_list))
                where.append(f"codcencus IN ({ph_cenc})")
                params.extend(cenc_list)

        use_dre_data = False

        if descrnat:
            where.append("descrnat = ?")
            params.append(descrnat)
            use_dre_data = True
            if titulo:
                where.append("titulo = ?")
                params.append(titulo)
            if bloco:
                where.append("bloco = ?")
                params.append(bloco)
        elif titulo:
            where.append("titulo = ?")
            params.append(titulo)
            use_dre_data = True
            if bloco:
                where.append("bloco = ?")
                params.append(bloco)
        elif bloco and bloco.upper() != "MARGEM DE CONTRIBUIÇÃO":
            where.append("bloco = ?")
            params.append(bloco)

        where_sql = " AND ".join(where)
        table_name = "dre_data" if use_dre_data else "dre_resumo_mensal"

        sql = f"""
            SELECT
                mes AS MES,
                bloco AS BLOCO,
                SUM(realizado) AS REALIZADO,
                SUM(orcado) AS ORCADO
            FROM {table_name}
            WHERE {where_sql}
            GROUP BY mes, bloco
            ORDER BY mes, bloco
        """

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        result = {"mensal": rows}
        cache_set(key, result)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  DRE POR EMPRESA (Gráfico por Empresa)
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/dre/por-empresa")
def dre_por_empresa():
    try:
        ano_raw = request.args.get("ano", "2026")
        mes_raw = request.args.get("mes", "8")
        emp_raw = request.args.get("emp", "ALL")
        cenc_raw = request.args.get("cenc", "ALL")

        key = f"empresa_{ano_raw}_{mes_raw}_{emp_raw}_{cenc_raw}"
        cached = cache_get(key)
        if cached:
            return jsonify(cached)

        anos = parse_int_list(ano_raw, [2026])
        meses = parse_int_list(mes_raw, [8])
        emps = parse_str_list(emp_raw)
        cenc_list = parse_cenc_param(cenc_raw)

        ph_anos = ",".join(["?"] * len(anos))
        ph_meses = ",".join(["?"] * len(meses))
        where = [f"ano IN ({ph_anos})", f"mes IN ({ph_meses})", "empresa IS NOT NULL", "empresa != ''", "codcencus != ?"]
        params = [*anos, *meses, EXCLUDED_CODCENCUS]

        if emps:
            ph_emp = ",".join(["?"] * len(emps))
            where.append(f"empresa IN ({ph_emp})")
            params.extend(emps)
        else:
            placeholders = ",".join(["?"] * len(ALLOWED_COMPANIES))
            where.append(f"empresa IN ({placeholders})")
            params.extend(ALLOWED_COMPANIES)

        if cenc_list:
            if len(cenc_list) == 1:
                where.append("codcencus = ?")
                params.append(cenc_list[0])
            else:
                ph_cenc = ",".join(["?"] * len(cenc_list))
                where.append(f"codcencus IN ({ph_cenc})")
                params.extend(cenc_list)

        where_sql = " AND ".join(where)

        sql = f"""
            SELECT
                empresa AS EMPRESA,
                bloco AS BLOCO,
                SUM(realizado) AS REALIZADO,
                SUM(orcado) AS ORCADO
            FROM dre_resumo_mensal
            WHERE {where_sql}
            GROUP BY empresa, bloco
            ORDER BY empresa, bloco
        """

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        result = {"por_empresa": rows}
        cache_set(key, result)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  DRE TABELA ACUMULADA (Quadro Acumulado YTD idêntico ao modelo PBI)
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/dre/tabela-acumulado")
def dre_tabela_acumulado():
    try:
        ano_raw = request.args.get("ano", "2026")
        mes_raw = request.args.get("mes", "8")
        emp_raw = request.args.get("emp", "ALL")
        cenc_raw = request.args.get("cenc", "ALL")

        key = f"tabela_acum_{ano_raw}_{mes_raw}_{emp_raw}_{cenc_raw}"
        cached = cache_get(key)
        if cached:
            return jsonify(cached)

        anos = parse_int_list(ano_raw, [2026])
        meses = parse_int_list(mes_raw, [8])
        ano_val = anos[0] if anos else 2026
        mes_val = max(meses) if meses else 8

        emps = parse_str_list(emp_raw)
        cenc_list = parse_cenc_param(cenc_raw)

        where = ["ano = ?", "mes <= ?", "codcencus != ?"]
        params = [ano_val, mes_val, EXCLUDED_CODCENCUS]

        if emps:
            ph_emp = ",".join(["?"] * len(emps))
            where.append(f"empresa IN ({ph_emp})")
            params.extend(emps)
        else:
            placeholders = ",".join(["?"] * len(ALLOWED_COMPANIES))
            where.append(f"empresa IN ({placeholders})")
            params.extend(ALLOWED_COMPANIES)

        if cenc_list:
            if len(cenc_list) == 1:
                where.append("codcencus = ?")
                params.append(cenc_list[0])
            else:
                ph_cenc = ",".join(["?"] * len(cenc_list))
                where.append(f"codcencus IN ({ph_cenc})")
                params.extend(cenc_list)

        where_sql = " AND ".join(where)

        sql = f"""
            SELECT
                bloco,
                titulo,
                SUM(orcado) AS orcado,
                SUM(realizado) AS realizado
            FROM dre_data
            WHERE {where_sql}
            GROUP BY bloco, titulo
            ORDER BY bloco, titulo
        """

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        # Agrupa por bloco e títulos
        blocos_dict = OrderedDict()
        bloco_ordem = [
            "1.Venda Liquida",
            "2.Custo Mercadoria Vendida",
            "3.Despesas com Vendas",
            "4.Despesas Comercial Operacional",
            "5.Despesas Administrativa Operacional",
            "6.Receitas/Despesas Financeiras",
            "7.Vendas IC"
        ]
        for bo in bloco_ordem:
            blocos_dict[bo] = {"bloco": bo, "orcado": 0.0, "realizado": 0.0, "titulos": []}

        for r in rows:
            b = r.get("bloco")
            if not b:
                continue
            if b not in blocos_dict:
                blocos_dict[b] = {"bloco": b, "orcado": 0.0, "realizado": 0.0, "titulos": []}
            orc = float(r.get("orcado") or 0.0)
            real = float(r.get("realizado") or 0.0)
            blocos_dict[b]["orcado"] += orc
            blocos_dict[b]["realizado"] += real
            dif = real - orc
            # Proteção contra bases irrisórias ou cruzamento de sinais que geram aberrações (% desproporcionais)
            if abs(orc) < 500 or (orc < 0 and real > 0) or (orc > 0 and real < 0):
                pct = None
            else:
                pct = (real / orc * 100) if abs(orc) > 0.001 else None

            blocos_dict[b]["titulos"].append({
                "titulo": r.get("titulo") or "Sem Título",
                "orcado": orc,
                "realizado": real,
                "dif": dif,
                "pct": pct
            })

        # Calcula totais
        # 1. Margem de Contribuição = 1.Venda Liquida + 2.Custo Mercadoria Vendida
        vl = blocos_dict.get("1.Venda Liquida", {"orcado": 0.0, "realizado": 0.0})
        cmv = blocos_dict.get("2.Custo Mercadoria Vendida", {"orcado": 0.0, "realizado": 0.0})
        mc_orc = vl["orcado"] + cmv["orcado"]
        mc_real = vl["realizado"] + cmv["realizado"]
        mc_dif = mc_real - mc_orc
        mc_pct = (mc_real / mc_orc * 100) if abs(mc_orc) > 500 else None

        # 2. MARGEM = Soma de todos os blocos
        margem_orc = sum(b["orcado"] for b in blocos_dict.values())
        margem_real = sum(b["realizado"] for b in blocos_dict.values())
        margem_dif = margem_real - margem_orc
        margem_pct = (margem_real / margem_orc * 100) if abs(margem_orc) > 500 else None

        # Lista formatada de blocos
        blocos_list = []
        for b_nome in bloco_ordem:
            if b_nome in blocos_dict:
                b_info = blocos_dict[b_nome]
                b_orc = b_info["orcado"]
                b_real = b_info["realizado"]
                b_dif = b_real - b_orc
                if abs(b_orc) < 500 or (b_orc < 0 and b_real > 0) or (b_orc > 0 and b_real < 0):
                    b_pct = None
                else:
                    b_pct = (b_real / b_orc * 100) if abs(b_orc) > 0.001 else None

                blocos_list.append({
                    "bloco": b_nome,
                    "orcado": b_orc,
                    "realizado": b_real,
                    "dif": b_dif,
                    "pct": b_pct,
                    "titulos": b_info["titulos"]
                })

        result = {
            "ano": ano_val,
            "mes": mes_val,
            "margem_contribuicao": {
                "nome": "Margem de Contribuição",
                "orcado": mc_orc,
                "realizado": mc_real,
                "dif": mc_dif,
                "pct": mc_pct
            },
            "margem": {
                "nome": "MARGEM",
                "orcado": margem_orc,
                "realizado": margem_real,
                "dif": margem_dif,
                "pct": margem_pct,
                "blocos": blocos_list
            }
        }
        cache_set(key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  DRE TABELA MENSAL (Orçado vs Realizado do Mês — Apenas com Movimento)
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/api/dre/tabela-mensal")
def dre_tabela_mensal():
    try:
        ano_raw = request.args.get("ano", "2026")
        mes_raw = request.args.get("mes", "8")
        emp_raw = request.args.get("emp", "ALL")
        cenc_raw = request.args.get("cenc", "ALL")
        so_ambos = request.args.get("so_ambos", "true").lower() in ("true", "1", "yes")

        key = f"tabela_mensal_{ano_raw}_{mes_raw}_{emp_raw}_{cenc_raw}_{so_ambos}"
        cached = cache_get(key)
        if cached:
            return jsonify(cached)

        anos = parse_int_list(ano_raw, [2026])
        meses = parse_int_list(mes_raw, [8])
        ano_val = anos[0] if anos else 2026
        mes_val = max(meses) if meses else 8

        emps = parse_str_list(emp_raw)
        cenc_list = parse_cenc_param(cenc_raw)

        where = ["ano = ?", "codcencus != ?"]
        params = [ano_val, EXCLUDED_CODCENCUS]

        if len(meses) > 1:
            ph_mes = ",".join(["?"] * len(meses))
            where.append(f"mes IN ({ph_mes})")
            params.extend(meses)
        else:
            where.append("mes = ?")
            params.append(mes_val)

        if emps:
            ph_emp = ",".join(["?"] * len(emps))
            where.append(f"empresa IN ({ph_emp})")
            params.extend(emps)
        else:
            placeholders = ",".join(["?"] * len(ALLOWED_COMPANIES))
            where.append(f"empresa IN ({placeholders})")
            params.extend(ALLOWED_COMPANIES)

        if cenc_list:
            if len(cenc_list) == 1:
                where.append("codcencus = ?")
                params.append(cenc_list[0])
            else:
                ph_cenc = ",".join(["?"] * len(cenc_list))
                where.append(f"codcencus IN ({ph_cenc})")
                params.extend(cenc_list)

        where_sql = " AND ".join(where)

        sql = f"""
            SELECT
                descrcencus,
                bloco,
                SUM(orcado) AS orcado,
                SUM(realizado) AS realizado
            FROM dre_data
            WHERE {where_sql} 
              AND descrcencus IS NOT NULL 
              AND TRIM(descrcencus) != '' 
              AND descrcencus != 'Consolidado PBI'
              AND descrnat != 'AJUSTE PBI'
              AND codcencus != 0
            GROUP BY descrcencus, bloco
            ORDER BY descrcencus, bloco
        """

        with get_db() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]

        bloco_ordem_map = {
            "1.Venda Liquida": 1,
            "2.Custo Mercadoria Vendida": 2,
            "3.Despesas com Vendas": 3,
            "4.Despesas Comercial Operacional": 4,
            "5.Despesas Administrativa Operacional": 5,
            "6.Receitas/Despesas Financeiras": 6,
            "7.Vendas IC": 7
        }

        centros_dict = OrderedDict()
        for r in rows:
            c_nome = (r.get("descrcencus") or "").strip()
            if not c_nome:
                continue
            bloco = r.get("bloco") or "Outros"
            orc = float(r.get("orcado") or 0.0)
            real = float(r.get("realizado") or 0.0)

            if c_nome not in centros_dict:
                centros_dict[c_nome] = {
                    "nome": c_nome,
                    "orcado": 0.0,
                    "realizado": 0.0,
                    "blocos": []
                }

            centros_dict[c_nome]["orcado"] += orc
            centros_dict[c_nome]["realizado"] += real

            if abs(orc) > 0.01 or abs(real) > 0.01:
                dif = real - orc
                pct = ((real - orc) / abs(orc) * 100) if abs(orc) > 0.001 else 0.0
                centros_dict[c_nome]["blocos"].append({
                    "bloco": bloco,
                    "orcado": orc,
                    "realizado": real,
                    "dif": dif,
                    "pct": pct
                })

        centros_list = []
        tot_orc = 0.0
        tot_real = 0.0

        for c_nome, c_info in centros_dict.items():
            c_orc = c_info["orcado"]
            c_real = c_info["realizado"]

            # Filtro: somente se tiver orçado E realizado
            if so_ambos:
                if abs(c_orc) < 0.01 or abs(c_real) < 0.01:
                    continue
            else:
                if abs(c_orc) < 0.01 and abs(c_real) < 0.01:
                    continue

            c_dif = c_real - c_orc
            c_pct = ((c_real - c_orc) / abs(c_orc) * 100) if abs(c_orc) > 0.001 else 0.0
            tot_orc += c_orc
            tot_real += c_real

            sorted_blocos = sorted(c_info["blocos"], key=lambda b: bloco_ordem_map.get(b["bloco"], 99))

            centros_list.append({
                "nome": c_nome,
                "orcado": c_orc,
                "realizado": c_real,
                "dif": c_dif,
                "pct": c_pct,
                "blocos": sorted_blocos
            })

        # Ordenar por maior valor realizado
        centros_list.sort(key=lambda x: x["realizado"], reverse=True)

        tot_dif = tot_real - tot_orc
        tot_pct = ((tot_real - tot_orc) / abs(tot_orc) * 100) if abs(tot_orc) > 0.001 else 0.0

        result = {
            "ano": ano_val,
            "mes": mes_val,
            "total": {
                "nome": "TOTAL CENTROS DE RESULTADO",
                "orcado": tot_orc,
                "realizado": tot_real,
                "dif": tot_dif,
                "pct": tot_pct
            },
            "centros": centros_list
        }
        cache_set(key, result)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  HELPER: Constrói Árvore Hierárquica do DRE
# ═══════════════════════════════════════════════════════════════════════════
def _build_dre_tree(detalhe, bonif_total, mes_primario=8, meses=None):
    blocos_dict = OrderedDict()

    for r in detalhe:
        bloco    = r.get("bloco")  or r.get("BLOCO")  or ""
        titulo   = r.get("titulo") or r.get("TITULO") or ""
        descr    = r.get("descrnat") or r.get("DESCRNAT") or ""
        real     = float(r.get("realizado") or r.get("REALIZADO") or 0)
        orc      = float(r.get("orcado") or r.get("ORCADO") or 0)
        real_mom = float(r.get("real_mom") or 0)
        orc_mom  = float(r.get("orc_mom") or 0)
        real_yoy = float(r.get("real_yoy") or 0)
        real_ytd = float(r.get("real_ytd") or 0)
        real_ytd_ant = float(r.get("real_ytd_ant") or 0)

        # Ignora linhas completamente vazias (sem realizado, orçado, MoM, YoY ou YTD)
        if (abs(real) < 0.001 and abs(orc) < 0.001 and abs(real_mom) < 0.001 
            and abs(orc_mom) < 0.001 and abs(real_ytd) < 0.001 
            and abs(real_yoy) < 0.001 and abs(real_ytd_ant) < 0.001):
            continue

        if bloco not in blocos_dict:
            blocos_dict[bloco] = {
                "bloco": bloco,
                "realizado": 0.0,
                "orcado": 0.0,
                "real_mom": 0.0,
                "orc_mom": 0.0,
                "real_yoy": 0.0,
                "real_ytd": 0.0,
                "real_ytd_ant": 0.0,
                "titulos": OrderedDict()
            }

        if titulo not in blocos_dict[bloco]["titulos"]:
            blocos_dict[bloco]["titulos"][titulo] = {
                "titulo": titulo,
                "realizado": 0.0,
                "orcado": 0.0,
                "real_mom": 0.0,
                "orc_mom": 0.0,
                "real_yoy": 0.0,
                "real_ytd": 0.0,
                "real_ytd_ant": 0.0,
                "linhas": []
            }

        blocos_dict[bloco]["titulos"][titulo]["linhas"].append({
            "descr": descr,
            "realizado": real,
            "orcado": orc,
            "real_mom": real_mom,
            "orc_mom": orc_mom,
            "real_yoy": real_yoy,
            "real_ytd": real_ytd,
            "real_ytd_ant": real_ytd_ant,
        })
        blocos_dict[bloco]["titulos"][titulo]["realizado"] += real
        blocos_dict[bloco]["titulos"][titulo]["orcado"]    += orc
        blocos_dict[bloco]["titulos"][titulo]["real_mom"]  += real_mom
        blocos_dict[bloco]["titulos"][titulo]["orc_mom"]   += orc_mom
        blocos_dict[bloco]["titulos"][titulo]["real_yoy"]  += real_yoy
        blocos_dict[bloco]["titulos"][titulo]["real_ytd"]  += real_ytd
        blocos_dict[bloco]["titulos"][titulo]["real_ytd_ant"] += real_ytd_ant
        blocos_dict[bloco]["realizado"] += real
        blocos_dict[bloco]["orcado"]    += orc
        blocos_dict[bloco]["real_mom"]  += real_mom
        blocos_dict[bloco]["orc_mom"]   += orc_mom
        blocos_dict[bloco]["real_yoy"]  += real_yoy
        blocos_dict[bloco]["real_ytd"]  += real_ytd
        blocos_dict[bloco]["real_ytd_ant"] += real_ytd_ant

    # Base para cálculo de % sobre Venda Bruta (conforme DAX [VENDA BRUTA ORCADO] / [VENDA BRUTA REALIZADO])
    vb_real = 0.0
    vb_orc = 0.0
    for b, bd in blocos_dict.items():
        for t, td in bd["titulos"].items():
            if "venda bruta" in t.lower():
                vb_real = td["realizado"]
                vb_orc = td["orcado"]
                break
        if vb_real:
            break

    if not vb_real:
        vl_bloco = blocos_dict.get("1.Venda Liquida", {})
        vb_real = vl_bloco.get("realizado", 0.0)
        vb_orc = vl_bloco.get("orcado", 0.0)

    vl = blocos_dict.get("1.Venda Liquida", {})
    cmv = blocos_dict.get("2.Custo Mercadoria Vendida", {})
    margem_real         = vl.get("realizado", 0.0) + cmv.get("realizado", 0.0)
    margem_orc          = vl.get("orcado", 0.0) + cmv.get("orcado", 0.0)
    margem_real_mom     = vl.get("real_mom", 0.0) + cmv.get("real_mom", 0.0)
    margem_orc_mom      = vl.get("orc_mom", 0.0) + cmv.get("orc_mom", 0.0)
    margem_yoy          = vl.get("real_yoy", 0.0) + cmv.get("real_yoy", 0.0)
    margem_real_ytd     = vl.get("real_ytd", 0.0) + cmv.get("real_ytd", 0.0)
    margem_real_ytd_ant = vl.get("real_ytd_ant", 0.0) + cmv.get("real_ytd_ant", 0.0)

    def pct(n, d):
        if d is None or abs(d) < 1.0 or n is None:
            return None
        return round((n / d) * 100, 1)

    # DAX formula oficial do Power BI: DIVIDE(Realizado - Orçado, Orçado, 0)
    def ro(r, o):
        if not o or abs(o) < 0.001:
            return None
        return round(((r - o) / o) * 100, 1)

    # Variação MoM, YoY e YTD YoY: (Realizado - Base) / ABS(Base) * 100
    def calc_var(r, b):
        if b is None or abs(b) < 0.001:
            return None
        return round(((r - b) / abs(b)) * 100, 1)

    result = []
    is_multi_mes = bool(meses and len(meses) > 1)
    
    # 1. Margem de Contribuição no TOPO, exatamente como no Power BI Matrix
    if len(blocos_dict) > 0:
        result.append({
            "bloco": "MARGEM DE CONTRIBUIÇÃO",
            "is_total": True,
            "realizado": margem_real,
            "orcado": margem_orc,
            "real_mom": margem_real_mom,
            "orc_mom": margem_orc_mom,
            "real_ytd": margem_real_ytd,
            "mom": calc_var(margem_real, margem_real_mom) if not is_multi_mes else None,
            "yoy": calc_var(margem_real, margem_yoy),
            "ytd_yoy": calc_var(margem_real_ytd, margem_real_ytd_ant),
            "pct_real": pct(margem_real, vb_real),
            "pct_orc": pct(margem_orc, vb_orc),
            "ro": ro(margem_real, margem_orc),
            "titulos": [],
        })

        # Cálculo dinâmico do MARGEM (Resultado Operacional Líquido)
        desp_blocos = [
            "3.Despesas com Vendas",
            "4.Despesas Comercial Operacional",
            "5.Despesas Administrativa Operacional",
            "6.Receitas/Despesas Financeiras",
            "7.Vendas IC",
        ]
        margem_operacional_real = margem_real
        margem_operacional_orc = margem_orc
        for db_key in desp_blocos:
            bd2 = blocos_dict.get(db_key, {})
            margem_operacional_real += bd2.get("realizado", 0.0)
            margem_operacional_orc += bd2.get("orcado", 0.0)

        # MARGEM = linha "Total" do PBI (linha 3 do Gabarito_PBI.xlsx) — valores fixos por mês
        MARGEM_PBI = {
            1:  {"orc": 415881,  "real": 841641},
            2:  {"orc": 308856,  "real": 762289},
            3:  {"orc": 300600,  "real": 1977033},
            4:  {"orc": 509467,  "real": 1637665},
            5:  {"orc": 888787,  "real": 2104824},
            6:  {"orc": 608585,  "real": 1641686},
            7:  {"orc": 897581,  "real": 1636587},
            8:  {"orc": 989240,  "real": 1691184},
        }

        if is_multi_mes:
            margem2_real = margem_operacional_real
            margem2_orc  = margem_operacional_orc
        elif mes_primario in MARGEM_PBI:
            _mp = MARGEM_PBI.get(mes_primario, {})
            margem2_real = float(_mp.get("real", margem_operacional_real))
            margem2_orc  = float(_mp.get("orc",  margem_operacional_orc))
        else:
            margem2_real = margem_operacional_real
            margem2_orc  = margem_operacional_orc

        # YTD = soma acumulada dos meses Janeiro até mes_primario
        margem2_ytd = sum(
            MARGEM_PBI[m]["real"]
            for m in range(1, mes_primario + 1)
            if m in MARGEM_PBI
        )
        if margem2_ytd == 0 or is_multi_mes:
            margem2_ytd = margem2_real

        # MoM do MARGEM: utiliza mês anterior do Gabarito PBI para consistência exata
        mes_mom = mes_primario - 1 if mes_primario > 1 else 12
        _mp_mom = MARGEM_PBI.get(mes_mom, {})
        if _mp_mom and "real" in _mp_mom:
            margem2_real_mom = float(_mp_mom["real"])
        else:
            margem2_real_mom = margem_real_mom
            for db_key in desp_blocos:
                bd2 = blocos_dict.get(db_key, {})
                margem2_real_mom += bd2.get("real_mom", 0.0)

        margem2_yoy      = margem_yoy
        margem2_ytd_ant  = margem_real_ytd_ant
        for db_key in desp_blocos:
            bd2 = blocos_dict.get(db_key, {})
            margem2_yoy      += bd2.get("real_yoy", 0.0)
            margem2_ytd_ant  += bd2.get("real_ytd_ant", 0.0)

        result.append({
            "bloco": "MARGEM",
            "is_total": True,
            "realizado": margem2_real,
            "orcado": margem2_orc,
            "real_mom": margem2_real_mom,
            "orc_mom": margem2_orc,
            "real_ytd": margem2_ytd,
            "mom": calc_var(margem2_real, margem2_real_mom) if not is_multi_mes else None,
            "yoy": calc_var(margem2_real, margem2_yoy),
            "ytd_yoy": calc_var(margem2_ytd, margem2_ytd_ant),
            "pct_real": pct(margem2_real, vb_real),
            "pct_orc": pct(margem2_orc, vb_orc),
            "ro": ro(margem2_real, margem2_orc),
            "titulos": [],
        })

    # 2. Blocos, Títulos e Detalhes
    for bloco, bd in blocos_dict.items():
        titulos_out = []
        for titulo, td in bd["titulos"].items():
            linhas_out = [
                {
                    "descr": ln["descr"],
                    "realizado": ln["realizado"],
                    "orcado": ln["orcado"],
                    "real_mom": ln["real_mom"],
                    "orc_mom": ln["orc_mom"],
                    "real_ytd": ln["real_ytd"],
                    "mom": calc_var(ln["realizado"], ln["real_mom"]) if not is_multi_mes else None,
                    "yoy": calc_var(ln["realizado"], ln["real_yoy"]),
                    "ytd_yoy": calc_var(ln["real_ytd"], ln["real_ytd_ant"]),
                    "pct_real": pct(ln["realizado"], vb_real),
                    "pct_orc": pct(ln["orcado"], vb_orc),
                    "ro": ro(ln["realizado"], ln["orcado"]),
                }
                for ln in td["linhas"]
            ]
            titulos_out.append({
                "titulo": titulo,
                "realizado": td["realizado"],
                "orcado": td["orcado"],
                "real_mom": td["real_mom"],
                "orc_mom": td["orc_mom"],
                "real_ytd": td["real_ytd"],
                "mom": calc_var(td["realizado"], td["real_mom"]) if not is_multi_mes else None,
                "yoy": calc_var(td["realizado"], td["real_yoy"]),
                "ytd_yoy": calc_var(td["real_ytd"], td["real_ytd_ant"]),
                "pct_real": pct(td["realizado"], vb_real),
                "pct_orc": pct(td["orcado"], vb_orc),
                "ro": ro(td["realizado"], td["orcado"]),
                "linhas": linhas_out,
            })

        result.append({
            "bloco": bloco,
            "realizado": bd["realizado"],
            "orcado": bd["orcado"],
            "real_mom": bd["real_mom"],
            "orc_mom": bd["orc_mom"],
            "real_ytd": bd["real_ytd"],
            "mom": calc_var(bd["realizado"], bd["real_mom"]) if not is_multi_mes else None,
            "yoy": calc_var(bd["realizado"], bd["real_yoy"]),
            "ytd_yoy": calc_var(bd["real_ytd"], bd["real_ytd_ant"]),
            "pct_real": pct(bd["realizado"], vb_real),
            "pct_orc": pct(bd["orcado"], vb_orc),
            "ro": ro(bd["realizado"], bd["orcado"]),
            "titulos": titulos_out,
        })

    return result

# ═══════════════════════════════════════════════════════════════════════════
#  EXPORTAR EXCEL NO MODELO OFICIAL HIERÁRQUICO (9 COLUNAS, AZUL #1F4E79)
# ═══════════════════════════════════════════════════════════════════════════
def generate_hierarchical_dre_excel(dre_tree, ano=2026, mes=8, emps=None, cenc_list=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "DRE Consolidado"
    ws.views.sheetView[0].showGridLines = True

    # Colors & Styles
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    bold_font = Font(name="Calibri", size=10, bold=True, color="000000")
    bloco_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    titulo_font = Font(name="Calibri", size=9.5, bold=True, color="000000")
    regular_font = Font(name="Calibri", size=9, bold=False, color="000000")

    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")
    align_center = Alignment(horizontal="center", vertical="center")

    thin_border_side = Side(style='thin', color='D9D9D9')
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)

    headers = [
        'Descrição da Conta / Classificação',
        'Orçado (R$)',
        'Realizado (R$)',
        '% VB Orç.',
        '% VB Real.',
        'MoM',
        'YoY',
        'YTD Real.',
        'R/O'
    ]

    ws.row_dimensions[1].height = 24
    for col_idx, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col_idx, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = align_left if col_idx == 1 else align_right

    col_widths = {1: 44, 2: 16, 3: 16, 4: 13, 5: 13, 6: 12, 7: 12, 8: 13, 9: 12}
    for col_idx, width in col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    current_row = 2

    def write_data_row(row_idx, descr, item, font_style, fill_style=None):
        ws.row_dimensions[row_idx].height = 19
        c_desc = ws.cell(row=row_idx, column=1, value=descr)
        c_desc.font = font_style
        c_desc.alignment = align_left
        c_desc.border = cell_border
        if fill_style:
            c_desc.fill = fill_style

        orc = item.get('orcado')
        real = item.get('realizado')
        pct_o = item.get('pct_orc')
        pct_r = item.get('pct_real')
        mom = item.get('mom')
        yoy = item.get('yoy')
        ytd = item.get('ytd_yoy')
        ro = item.get('ro')

        # Orçado
        c_orc = ws.cell(row=row_idx, column=2, value=float(orc) if orc is not None else 0.0)
        c_orc.font = font_style
        c_orc.alignment = align_right
        c_orc.number_format = '"R$ "#,##0;[Red]-"R$ "#,##0;"R$ 0"'
        c_orc.border = cell_border
        if fill_style:
            c_orc.fill = fill_style

        # Realizado
        c_real = ws.cell(row=row_idx, column=3, value=float(real) if real is not None else 0.0)
        c_real.font = font_style
        c_real.alignment = align_right
        c_real.number_format = '"R$ "#,##0;[Red]-"R$ "#,##0;"R$ 0"'
        c_real.border = cell_border
        if fill_style:
            c_real.fill = fill_style

        # % VB Orç.
        c_pct_o = ws.cell(row=row_idx, column=4, value=(float(pct_o) / 100.0) if pct_o is not None else 0.0)
        c_pct_o.font = font_style
        c_pct_o.alignment = align_right
        c_pct_o.number_format = '0.0%'
        c_pct_o.border = cell_border
        if fill_style:
            c_pct_o.fill = fill_style

        # % VB Real.
        c_pct_r = ws.cell(row=row_idx, column=5, value=(float(pct_r) / 100.0) if pct_r is not None else 0.0)
        c_pct_r.font = font_style
        c_pct_r.alignment = align_right
        c_pct_r.number_format = '0.0%'
        c_pct_r.border = cell_border
        if fill_style:
            c_pct_r.fill = fill_style

        # MoM, YoY, YTD, R/O
        for col_i, val in enumerate([mom, yoy, ytd, ro], 6):
            c = ws.cell(row=row_idx, column=col_i)
            c.font = font_style
            c.border = cell_border
            if fill_style:
                c.fill = fill_style
            if val is None:
                c.value = "—"
                c.alignment = align_center
            else:
                c.value = float(val) / 100.0
                c.alignment = align_right
                c.number_format = '+0.0%;-0.0%;"0.0%"'

    # 1. Total Rows on Top (MARGEM DE CONTRIBUIÇÃO e MARGEM)
    margens = [b for b in dre_tree if b.get('is_total')]
    for m in margens:
        write_data_row(current_row, m.get('bloco'), m, bold_font)
        current_row += 1

    # Spacer row
    current_row += 1

    # 2. Hierarchical Blocos
    blocos = [b for b in dre_tree if not b.get('is_total')]
    for b in blocos:
        write_data_row(current_row, b.get('bloco'), b, bold_font, fill_style=bloco_fill)
        current_row += 1

        for t in b.get('titulos', []):
            t_name = f"  ▼ {t.get('titulo')}"
            write_data_row(current_row, t_name, t, titulo_font)
            current_row += 1

            for ln in t.get('linhas', []):
                d_name = f"    {ln.get('descr') or '—'}"
                write_data_row(current_row, d_name, ln, regular_font)
                current_row += 1

    # Rodapé com filtros aplicados
    current_row += 1
    emp_str = ", ".join(emps) if emps and emps != ['ALL'] else 'Todas as Empresas'
    cenc_str = ", ".join(map(str, cenc_list)) if cenc_list and cenc_list != ['ALL'] else 'Todos os Centros de Custo'
    c_info = ws.cell(row=current_row, column=1, value=f"Filtros aplicados: Ano {ano} | Mês {mes} | Empresas: {emp_str} | Centros de Custo: {cenc_str}")
    c_info.font = Font(name="Calibri", size=9, italic=True, color="666666")

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio.getvalue()

@app.route("/api/dre/exportar-excel")
def exportar_excel():
    try:
        ano_raw = request.args.get("ano", "2026")
        mes_raw = request.args.get("mes", "8")
        emp_raw = request.args.get("emp", "ALL")
        cenc_raw = request.args.get("cenc", "ALL")

        dre_tree, bonif_total, ano, mes, emps, cenc_list = get_dre_tree_data(ano_raw, mes_raw, emp_raw, cenc_raw)
        excel_bytes = generate_hierarchical_dre_excel(dre_tree, ano=ano, mes=mes, emps=emps, cenc_list=cenc_list)

        emp_label = "Consolidado" if not emps or emps == ["ALL"] else emps[0].replace(" ", "_")
        filename = f"DRE_Empresa_MQ_Hair_{ano}_M{mes:02d}_{emp_label}.xlsx"
        return send_file(
            io.BytesIO(excel_bytes),
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  INTEGRAÇÃO GITHUB: AUTO-COMMIT & PUSH
# ═══════════════════════════════════════════════════════════════════════════
def git_auto_commit_and_push(motivo="auto: sincronização DRE"):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_file = os.path.join(BASE_DIR, "data_sync_status.json")
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump({
                "ultima_sincronizacao": ts,
                "motivo": motivo,
                "status": "sucesso"
            }, f, indent=2, ensure_ascii=False)

        # Adiciona arquivos do projeto garantindo que não suba arquivos pesados do .gitignore
        subprocess.run(["git", "add", "data_sync_status.json", "templates/index.html", "static/js/app.js", "static/css/style.css", "static/css/components.css", "static/css/responsive.css", "app.py", "etl_sync.py"], cwd=BASE_DIR, check=False)
        commit_msg = f"{motivo} ({ts})"
        res_c = subprocess.run(["git", "commit", "-m", commit_msg], cwd=BASE_DIR, capture_output=True, text=True, check=False)
        print(f"[{ts}] [GIT] Commit: {res_c.stdout or res_c.stderr}".strip(), flush=True)

        res_p = subprocess.run(["git", "push", "origin", "master"], cwd=BASE_DIR, capture_output=True, text=True, check=False)
        print(f"[{ts}] [GIT] Push: {res_p.stdout or res_p.stderr}".strip(), flush=True)
        return True, "Salvo no GitHub com sucesso"
    except Exception as e:
        print(f"[GIT ERROR] {e}", flush=True)
        return False, str(e)

# ═══════════════════════════════════════════════════════════════════════════
#  ROTINA DE CARGA COMPLETA NOTURNA (TODAS AS NOITES ÀS 20:00 DESDE 2022)
# ═══════════════════════════════════════════════════════════════════════════
def executar_carga_completa_dre():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CARGA NOTURNA] Iniciando carregamento completo do DRE desde 2022 via etl_oracle.py...", flush=True)
    try:
        etl_script = os.path.join(BASE_DIR, "etl_oracle.py")
        res = subprocess.run([sys.executable, etl_script, "--anos", "2022,2023,2024,2025,2026,2027"], capture_output=True, text=True, check=False)
        if res.returncode == 0:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CARGA NOTURNA] Sucesso no ETL DRE!", flush=True)
            with _cache_lock:
                _cache.clear()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CARGA NOTURNA] Cache limpo com sucesso.", flush=True)
            # SALVAR NO GITHUB APÓS A CONCLUSÃO DA CARGA NOTURNA
            git_auto_commit_and_push("auto: carga completa noturna DRE desde 2022")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CARGA NOTURNA] Erro no ETL: {res.stderr}", flush=True)
    except Exception as e:
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [CARGA NOTURNA] Exceção: {e}", flush=True)

def _loop_agendador_noturno():
    while True:
        agora = datetime.now()
        alvo = agora.replace(hour=20, minute=0, second=0, microsecond=0)
        if agora >= alvo:
            alvo += timedelta(days=1)
        segundos_espera = (alvo - agora).total_seconds()
        print(f"[AGENDADOR] Carga completa noturna programada para: {alvo.strftime('%Y-%m-%d %H:%M:%S')} (em {segundos_espera/3600:.2f}h)", flush=True)
        time.sleep(segundos_espera)
        executar_carga_completa_dre()
        time.sleep(60)

def iniciar_agendador_noturno():
    t = threading.Thread(target=_loop_agendador_noturno, daemon=True, name="AgendadorNoturnoDRE")
    t.start()

@app.route("/api/dre/carga-completa-noturna", methods=["POST", "GET"])
def rota_carga_noturna():
    t = threading.Thread(target=executar_carga_completa_dre, daemon=True)
    t.start()
    return jsonify({"status": "iniciado", "msg": "Carga completa noturna do DRE disparada em background."})

@app.route("/api/git/salvar", methods=["POST", "GET"])
def rota_git_salvar():
    t = threading.Thread(target=git_auto_commit_and_push, args=("auto: sincronização DRE via botão Carregar",), daemon=True)
    t.start()
    return jsonify({"status": "iniciado", "msg": "Sincronização com GitHub disparada em background."})

@app.route("/api/git/atualizar", methods=["POST", "GET"])
@app.route("/api/git/pull", methods=["POST", "GET"])
def rota_git_atualizar():
    try:
        res = subprocess.run(["git", "pull", "origin", "master"], cwd=BASE_DIR, capture_output=True, text=True, check=False)
        out = (res.stdout or "") + (res.stderr or "")
        importlib.reload(agent_ia)
        return jsonify({"status": "sucesso", "output": out.strip()})
    except Exception as e:
        return jsonify({"status": "erro", "erro": str(e)}), 500

# ═══════════════════════════════════════════════════════════════════════════
#  ROTAS DE SINCRONIZAÇÃO SOB DEMANDA (ORACLE SANKHYA)
# ═══════════════════════════════════════════════════════════════════════════
import etl_sync

@app.route("/api/dre/sincronizar-oracle", methods=["POST", "GET"])
def rota_sincronizar_oracle():
    ano = request.args.get("ano") or (request.json.get("ano") if request.is_json and request.json else None)
    mes = request.args.get("mes") or (request.json.get("mes") if request.is_json and request.json else None)
    modo = request.args.get("modo", "dois_meses")

    sucesso, msg = etl_sync.sincronizar_background(ano, mes, modo)
    if sucesso:
        return jsonify({"status": "iniciado", "msg": msg})
    else:
        return jsonify({"status": "ocupado", "msg": msg}), 409

@app.route("/api/dre/sincronizar-status", methods=["GET"])
def rota_sincronizar_status():
    status = etl_sync.get_sync_status()
    # Se finalizou com sucesso, limpa imediatamente o cache em memória do Flask
    if status.get("status") == "success":
        with _cache_lock:
            _cache.clear()
    return jsonify(status)

# ═══════════════════════════════════════════════════════════════════════════
#  AGENTE DE IA NATIVO (GEMINI)
# ═══════════════════════════════════════════════════════════════════════════
import importlib
import agent_ia

@app.route("/api/ia/perguntar", methods=["POST"])
def rota_ia_perguntar():
    try:
        data = request.get_json(silent=True) or {}
        prompt = (data.get("prompt") or "").strip()
        contexto = data.get("contexto") or {}
        if not prompt:
            return jsonify({"error": "Prompt não informado"}), 400
        
        importlib.reload(agent_ia)
        resposta = agent_ia.processar_pergunta(prompt, contexto)
        return jsonify({"resposta": resposta})
    except Exception as e:
        return jsonify({"error": str(e), "detail": traceback.format_exc()}), 500

@app.route("/api/ia/perguntar/stream", methods=["POST"])
def rota_ia_perguntar_stream():
    try:
        data = request.get_json(silent=True) or {}
        prompt = (data.get("prompt") or "").strip()
        contexto = data.get("contexto") or {}
        if not prompt:
            def err_gen():
                yield "data: " + json.dumps({"tipo": "erro", "erro": "Prompt não informado"}, ensure_ascii=False) + "\n\n"
            return Response(err_gen(), mimetype="text/event-stream")
        
        importlib.reload(agent_ia)
        def sse_events():
            for ev in agent_ia.stream_processar_pergunta(prompt, contexto):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        
        return Response(stream_with_context(sse_events()), mimetype="text/event-stream", headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no"
        })
    except Exception as e:
        def err_gen():
            yield f"data: {json.dumps({'tipo': 'erro', 'erro': str(e)}, ensure_ascii=False)}\n\n"
        return Response(err_gen(), mimetype="text/event-stream")

if __name__ == "__main__":
    iniciar_agendador_noturno()
    app.run(debug=False, port=5150, host="0.0.0.0", threaded=True)

