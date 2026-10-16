"""
etl_sync.py — Módulo de Sincronização Sob Demanda do DRE Empresa direto do Oracle (Sankhya).

Projetado para ser rápido, robusto e 100% multiplataforma (Windows e Linux).
Utiliza modo Thin do python-oracledb por padrão (dispensa instalação de Instant Client no servidor Linux).
"""
import os
from db import get_db_connection
import sys
import time
import threading
import datetime as dt
import json
import sqlite3
import oracledb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dre_cache.db")
STATUS_FILE = os.path.join(BASE_DIR, "data_sync_status.json")

ORACLE_USER = os.getenv("ORACLE_USER", "POWERBI")
ORACLE_PASS = os.getenv("ORACLE_PASS", "@Yzmpq100#")
ORACLE_DSN  = os.getenv("ORACLE_DSN",  "192.168.1.55/ORCL")

ALLOWED_COMPANIES = [
    'Consolidação', 'FORX SC', 'MCR - FABRICA', 'MCR - FILIAL 03',
    'MCR - MATRIZ', 'MCR - SC', 'QUALITY - RJ', 'QUALITY MATRIZ',
    'SL ONLINE - SP', 'VLS - RJ', 'VLS - SP', 'FORX MG'
]
EXCLUDED_CODCENCUS = 21010000
EXCLUDED_CODEMP    = 9

# Cortes de data para a view VMQ_DREQLIK no Oracle
_CORTES = [
    ("AND CAB.DTENTSAI>=TO_DATE('01/01/2024','DD/MM/YYYY')",
     "AND CAB.DTENTSAI>=:dt_ini AND CAB.DTENTSAI<:dt_fim"),
    ("AND fin.dtneg>=TO_DATE('01/01/2024','DD/MM/YYYY')",
     "AND fin.dtneg>=:dt_ini AND fin.dtneg<ADD_MONTHS(:dt_fim,1)"),
    ("AND FIN.DHBAIXA>=TO_DATE('01/01/2024','DD/MM/YYYY')",
     "AND FIN.DHBAIXA>=:dt_ini AND FIN.DHBAIXA<ADD_MONTHS(:dt_fim,1)"),
    ("WHERE DTNEG>=TO_DATE('01/01/2024','DD/MM/YYYY')",
     "WHERE DTNEG>=:dt_ini AND DTNEG<:dt_fim"),
    ("FROM AD_ORCAMENTO\r\nWHERE CODCENCUS NOT IN (21010000)",
     "FROM AD_ORCAMENTO\r\nWHERE CODCENCUS NOT IN (21010000) AND DTREF>=:dt_ini AND DTREF<:dt_fim"),
]

# Estado global da sincronização em background
_sync_lock = threading.Lock()
_sync_status = {
    "status": "idle",       # "idle", "running", "success", "error"
    "pct": 0,
    "msg": "Pronto para sincronizar",
    "detalhe": "",
    "linhas_afetadas": 0,
    "duracao_seg": 0,
    "erro": None,
    "inicio": None,
    "fim": None
}

def get_sync_status():
    with _sync_lock:
        return dict(_sync_status)

def _set_status(status, pct, msg, detalhe="", linhas=0, erro=None):
    with _sync_lock:
        _sync_status["status"] = status
        _sync_status["pct"] = pct
        _sync_status["msg"] = msg
        _sync_status["detalhe"] = detalhe
        if linhas:
            _sync_status["linhas_afetadas"] = linhas
        if erro:
            _sync_status["erro"] = str(erro)

def gravar_status_sync(motivo):
    """Registra em data_sync_status.json o horário da última sincronização concluída com sucesso."""
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "ultima_sincronizacao": ts,
            "motivo": motivo,
            "status": "sucesso"
        }, f, indent=2, ensure_ascii=False)
    return ts

def ler_status_sync():
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ultima_sincronizacao": None}

def trimestre(mes):
    return f"Q{((int(mes)-1)//3)+1}"

def semestre(mes):
    return "S1" if int(mes) <= 6 else "S2"

def conectar_oracle():
    """Conecta ao Oracle no modo Thin (ou Thick se configurado), compatível com Windows e Linux."""
    try:
        # Se instantclient estiver disponível no Windows, utiliza; se não, opera em Thin mode
        oracledb.init_oracle_client()
    except Exception:
        pass
    
    conn = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASS, dsn=ORACLE_DSN)
    cur = conn.cursor()
    cur.execute("ALTER SESSION SET CURRENT_SCHEMA = SANKHYA")
    return conn

def carregar_dimensoes(cur):
    """Carrega empresas, naturezas e CADDRE em poucos segundos."""
    cur.execute("SELECT CODEMP, RAZAOABREV FROM SANKHYA.VMQ_TSIEMP ORDER BY CODEMP")
    emp_map = {int(r[0]): str(r[1]) for r in cur.fetchall() if r[0] is not None}

    cur.execute("SELECT CODNAT, DESCRNAT FROM SANKHYA.TGFNAT")
    nat_map = {int(r[0]): str(r[1]).strip() for r in cur.fetchall() if r[0] is not None and r[1]}

    cur.arraysize = 10000
    cur.execute("SELECT BLOCO, TITULO, CODNAT, CODCENCUS, FATOR, REF FROM SANKHYA.VMQ_CADDRE")
    caddre = {}
    for bloco, titulo, codnat, codcencus, fator, ref in cur.fetchall():
        ref_val = ref or ''
        key = (int(codnat) if codnat else 0, int(codcencus) if codcencus else 0, ref_val)
        caddre[key] = {
            "bloco": bloco or "",
            "titulo": titulo or "",
            "fator": float(fator) if fator else 1.0,
            "ref": ref_val
        }
    return emp_map, caddre, nat_map

def extrair_mes(cur, view_texto_cortado, ano, mes):
    """Extrai um mês agregando por empresa, centro, natureza e ref com os filtros oficiais."""
    dt_ini = dt.datetime(ano, mes, 1)
    dt_fim = dt.datetime(ano, mes + 1, 1) if mes < 12 else dt.datetime(ano + 1, 1, 1)

    sql = f"""
        SELECT CODEMP,
               CODCENCUS,
               CODNAT,
               REF,
               SUM(VALOR)     AS REALIZADO,
               SUM(ORCAMENTO) AS ORCADO
          FROM ({view_texto_cortado}) d
         WHERE d.dtcomp >= :dt_ini AND d.dtcomp < :dt_fim
           AND d.codcencus != :cenc_excl
           AND d.codemp    != :emp_excl
         GROUP BY CODEMP, CODCENCUS, CODNAT, REF
    """
    cur.arraysize = 5000
    cur.execute(sql, dt_ini=dt_ini, dt_fim=dt_fim, cenc_excl=EXCLUDED_CODCENCUS, emp_excl=EXCLUDED_CODEMP)
    return cur.fetchall()

def salvar_mes_mariadb(conn, ano, mes, rows, emp_map, caddre, nat_map):
    """Mapeia e salva os registros de um mês em dre_data e dre_resumo_mensal no MariaDB."""
    permitidas = set(ALLOWED_COMPANIES)
    batch = []

    for codemp, codcencus, codnat, ref_raw, realizado, orcado in rows:
        emp_nome = emp_map.get(codemp, f"EMP-{codemp}")
        if emp_nome not in permitidas:
            continue
        
        ref_val = ref_raw or ''
        info = caddre.get((codnat, codcencus, ref_val)) or caddre.get((codnat, 0, ref_val))
        if info is None and ref_val != '':
            info = caddre.get((codnat, codcencus, '')) or caddre.get((codnat, 0, ''))
            
        if info is None:
            continue
            
        real = float(realizado or 0.0)
        orc  = float(orcado or 0.0)
        if abs(real) < 0.001 and abs(orc) < 0.001:
            continue
            
        fator = info["fator"]
        descr_natureza = nat_map.get(int(codnat), str(codnat)) if codnat else ""
        batch.append((
            ano, mes, trimestre(mes), semestre(mes),
            emp_nome, codcencus, "",
            info["bloco"], info["titulo"], descr_natureza,
            orc, real * fator, 0.0, 0.0  # orçado (AD_ORCAMENTO) já vem com sinal: NÃO aplica fator
        ))

    with conn.cursor() as cur:
        # Atualiza dre_data para o mês
        cur.execute("DELETE FROM dre_data WHERE ano = %s AND mes = %s", (ano, mes))
        if batch:
            cur.executemany("""
                INSERT INTO dre_data
                (ano,mes,trimestre,semestre,empresa,codcencus,descrcencus,
                 bloco,titulo,descrnat,orcado,realizado,vb_orcado,vb_realizado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, batch)

        # Atualiza dre_resumo_mensal para o mês
        cur.execute("DELETE FROM dre_resumo_mensal WHERE ano = %s AND mes = %s", (ano, mes))
        cur.execute("""
            INSERT INTO dre_resumo_mensal (ano, mes, empresa, codcencus, bloco, realizado, orcado)
            SELECT ano, mes, empresa, codcencus, bloco, SUM(realizado), SUM(orcado)
            FROM dre_data
            WHERE ano = %s AND mes = %s
            GROUP BY ano, mes, empresa, codcencus, bloco
        """, (ano, mes))

        # Garante ano nos filtros
        cur.execute("INSERT IGNORE INTO dre_filtros_anos (ano) VALUES (%s)", (ano,))
        conn.commit()
    return len(batch)

def _executar_sincronizacao(meses_para_sincronizar, motivo="sincronização DRE via botão Carregar"):
    """Executa a sincronização dos meses especificados no Oracle gravando no MariaDB."""
    t0 = time.time()
    total_linhas = 0
    _set_status("running", 5, "Conectando ao banco Oracle Sankhya...", f"Total de {len(meses_para_sincronizar)} mês(es) a sincronizar.")

    oc = None
    try:
        oc = conectar_oracle()
        cur = oc.cursor()

        _set_status("running", 15, "Carregando plano de contas e empresas...", "Lendo CADDRE e mapeamento de empresas.")
        emp_map, caddre, nat_map = carregar_dimensoes(cur)

        _set_status("running", 25, "Preparando consulta otimizada da view VMQ_DREQLIK...", "Injetando cortes temporais nos índices de data.")
        cur.execute("SELECT text FROM all_views WHERE owner = 'SANKHYA' AND view_name = 'VMQ_DREQLIK'")
        texto = cur.fetchone()[0]
        if hasattr(texto, "read"):
            texto = texto.read()
        texto_norm = texto.replace("\r\n", "\n").replace("\n", "\r\n")
        for orig, novo in _CORTES:
            texto_norm = texto_norm.replace(orig, novo)

        conn_db = get_db_connection()

        passo = 60 // len(meses_para_sincronizar)
        for idx, (ano_s, mes_s) in enumerate(meses_para_sincronizar):
            pct_atual = 25 + (idx * passo)
            _set_status("running", pct_atual, f"Extraindo dados do Oracle: {ano_s}/{mes_s:02d}...", "Consultando lançamentos analíticos e orçados.")
            
            rows = extrair_mes(cur, texto_norm, ano_s, mes_s)
            
            _set_status("running", pct_atual + (passo // 2), f"Gravando {ano_s}/{mes_s:02d} no MariaDB...", f"{len(rows)} linhas lidas do Oracle.")
            linhas_mes = salvar_mes_mariadb(conn_db, ano_s, mes_s, rows, emp_map, caddre, nat_map)
            total_linhas += linhas_mes

        conn_db.close()
        oc.close()

        gravar_status_sync(motivo)

        duracao = time.time() - t0
        _set_status("success", 100, "Sincronização com Oracle concluída!",
                    f"{total_linhas} lançamentos atualizados em {duracao:.1f}s.", linhas=total_linhas)
        with _sync_lock:
            _sync_status["duracao_seg"] = duracao
            _sync_status["fim"] = dt.datetime.now().isoformat()
        return True

    except Exception as e:
        duracao = time.time() - t0
        _set_status("error", 100, f"Erro ao sincronizar com Oracle: {e}", str(e), erro=e)
        if oc:
            try:
                oc.close()
            except Exception:
                pass
        return False

def _montar_meses(ano=None, mes=None, modo="dois_meses"):
    """Resolve ano/mês (padrão: data atual do servidor) e devolve a lista de (ano, mes) a sincronizar."""
    agora = dt.datetime.now()
    ano = int(ano) if ano else agora.year
    mes = int(mes) if mes else agora.month

    if modo == "dois_meses":
        mes_ant = mes - 1 if mes > 1 else 12
        ano_ant = ano if mes > 1 else ano - 1
        return [(ano_ant, mes_ant), (ano, mes)]
    return [(ano, mes)]

def _reservar_execucao(meses):
    """Marca a sincronização como 'running' de forma atômica. Retorna False se já houver uma em andamento."""
    with _sync_lock:
        if _sync_status["status"] == "running":
            return False
        _sync_status.update({
            "status": "running", "pct": 1, "msg": "Iniciando sincronização...",
            "detalhe": f"Total de {len(meses)} mês(es) a sincronizar.",
            "linhas_afetadas": 0, "duracao_seg": 0, "erro": None,
            "inicio": dt.datetime.now().isoformat(), "fim": None
        })
        return True

def sincronizar_background(ano=None, mes=None, modo="dois_meses"):
    """Dispara a sincronização em uma thread separada para não travar a requisição HTTP."""
    meses = _montar_meses(ano, mes, modo)
    if not _reservar_execucao(meses):
        return False, "Uma sincronização já está em andamento no momento."

    t = threading.Thread(target=_executar_sincronizacao, args=(meses,), daemon=True, name="OracleSyncThread")
    t.start()
    return True, f"Sincronização iniciada para {len(meses)} mês(es)."

def sincronizar_agora(ano=None, mes=None, modo="mes"):
    """Executa a sincronização na thread atual (usado pelo agendador diário)."""
    meses = _montar_meses(ano, mes, modo)
    if not _reservar_execucao(meses):
        return False, "Uma sincronização já está em andamento no momento."

    if _executar_sincronizacao(meses, motivo="auto: atualização diária do mês atual"):
        return True, get_sync_status()["detalhe"]
    return False, get_sync_status()["erro"] or "Erro desconhecido na sincronização."
