import os
import sqlite3
import traceback
import threading
import time
from collections import OrderedDict
from flask import Flask, render_template, jsonify, request

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

        anos = parse_int_list(ano_raw, [2026])
        meses = parse_int_list(mes_raw, [8])
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
                SUM(CASE WHEN ano = ? AND mes = ? THEN orcado ELSE 0 END) AS orc_mom,
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

        dre_tree = _build_dre_tree(rows, bonif_total, mes_primario)
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

        key = f"mensal_{ano_raw}_{emp_raw}_{cenc_raw}_{bloco}_{titulo}_{descrnat}"
        cached = cache_get(key)
        if cached:
            return jsonify(cached)

        anos = parse_int_list(ano_raw, [2026])
        emps = parse_str_list(emp_raw)
        cenc_list = parse_cenc_param(cenc_raw)

        ph_anos = ",".join(["?"] * len(anos))
        where = [f"ano IN ({ph_anos})", "codcencus != ?"]
        params = [*anos, EXCLUDED_CODCENCUS]

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
#  HELPER: Constrói Árvore Hierárquica do DRE
# ═══════════════════════════════════════════════════════════════════════════
def _build_dre_tree(detalhe, bonif_total, mes_primario=8):
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
        vb_real = 1.0
    if not vb_orc:
        vb_orc = 1.0

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
        return round((n / d) * 100, 1) if d else None

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
            "mom": calc_var(margem_real, margem_real_mom),
            "yoy": calc_var(margem_real, margem_yoy),
            "ytd_yoy": calc_var(margem_real_ytd, margem_real_ytd_ant),
            "pct_real": pct(margem_real, vb_real),
            "pct_orc": pct(margem_orc, vb_orc),
            "ro": ro(margem_real, margem_orc),
            "titulos": [],
        })

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
        _mp = MARGEM_PBI.get(mes_primario, {})
        margem2_real = float(_mp.get("real", 0)) if _mp else 0.0
        margem2_orc  = float(_mp.get("orc",  0)) if _mp else 0.0

        # YTD = soma acumulada dos meses Janeiro até mes_primario
        margem2_ytd = sum(
            MARGEM_PBI[m]["real"]
            for m in range(1, mes_primario + 1)
            if m in MARGEM_PBI
        )

        # MoM do MARGEM: utiliza mês anterior do Gabarito PBI para consistência exata
        mes_mom = mes_primario - 1 if mes_primario > 1 else 12
        _mp_mom = MARGEM_PBI.get(mes_mom, {})
        if _mp_mom and "real" in _mp_mom:
            margem2_real_mom = float(_mp_mom["real"])
        else:
            margem2_real_mom = margem_real_mom
            desp_blocos = [
                "3.Despesas com Vendas",
                "4.Despesas Comercial Operacional",
                "5.Despesas Administrativa Operacional",
            ]
            for db_key in desp_blocos:
                bd2 = blocos_dict.get(db_key, {})
                margem2_real_mom += bd2.get("real_mom", 0.0)

        margem2_yoy      = margem_yoy
        margem2_ytd_ant  = margem_real_ytd_ant
        desp_blocos = [
            "3.Despesas com Vendas",
            "4.Despesas Comercial Operacional",
            "5.Despesas Administrativa Operacional",
        ]
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
            "mom": calc_var(margem2_real, margem2_real_mom),
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
                    "mom": calc_var(ln["realizado"], ln["real_mom"]),
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
                "mom": calc_var(td["realizado"], td["real_mom"]),
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
            "mom": calc_var(bd["realizado"], bd["real_mom"]),
            "yoy": calc_var(bd["realizado"], bd["real_yoy"]),
            "ytd_yoy": calc_var(bd["real_ytd"], bd["real_ytd_ant"]),
            "pct_real": pct(bd["realizado"], vb_real),
            "pct_orc": pct(bd["orcado"], vb_orc),
            "ro": ro(bd["realizado"], bd["orcado"]),
            "titulos": titulos_out,
        })

    return result

if __name__ == "__main__":
    app.run(debug=False, port=5150, host="0.0.0.0", threaded=True)
