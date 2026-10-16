"""
executar_carga_historica.py
Carga e atualização dos dados do DRE Empresa desde Janeiro/2022 até a data atual (Outubro/2026).
Grava diretamente no MariaDB (banco ativo do app.py) e no SQLite (dre_cache.db).
Zero alterações de layout ou interface.
"""
import os
import sys
import time
import datetime as dt
import sqlite3
import urllib.request
import oracledb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from db import get_db_connection
import etl_sync

LOG_FILE = os.path.join(BASE_DIR, "carga_historica_execucao.log")
SQLITE_DB = os.path.join(BASE_DIR, "dre_cache.db")

def log(msg):
    ts = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{ts}] {msg}"
    print(linha, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass

def salvar_mes_sqlite(ano, mes, batch):
    """Atualiza dre_data, dre_resumo_mensal e dre_filtros_anos no SQLite."""
    if not os.path.exists(SQLITE_DB):
        return
    try:
        sconn = sqlite3.connect(SQLITE_DB, timeout=30.0)
        scur = sconn.cursor()
        scur.execute("DELETE FROM dre_data WHERE ano = ? AND mes = ?", (ano, mes))
        if batch:
            scur.executemany("""
                INSERT INTO dre_data
                (ano,mes,trimestre,semestre,empresa,codcencus,descrcencus,
                 bloco,titulo,descrnat,orcado,realizado,vb_orcado,vb_realizado)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, batch)
        scur.execute("DELETE FROM dre_resumo_mensal WHERE ano = ? AND mes = ?", (ano, mes))
        scur.execute("""
            INSERT INTO dre_resumo_mensal (ano, mes, empresa, codcencus, bloco, realizado, orcado)
            SELECT ano, mes, empresa, codcencus, bloco, SUM(realizado), SUM(orcado)
            FROM dre_data
            WHERE ano = ? AND mes = ?
            GROUP BY ano, mes, empresa, codcencus, bloco
        """, (ano, mes))
        scur.execute("INSERT OR IGNORE INTO dre_filtros_anos (ano) VALUES (?)", (ano,))
        sconn.commit()
        sconn.close()
    except Exception as e:
        log(f"  [Aviso SQLite] Não foi possível espelhar no dre_cache.db: {e}")

def extrair_e_salvar_mes(cur_ora, view_sql, ano, mes, emp_map, caddre, nat_map, conn_db):
    t0 = time.time()
    log(f"-> Extraindo {ano}-{mes:02d} do Oracle...")
    rows = etl_sync.extrair_mes(cur_ora, view_sql, ano, mes)
    t_ora = time.time() - t0
    log(f"   Oracle: {len(rows)} linhas agregadas em {t_ora:.1f}s.")
    
    # Processar batch para salvar
    permitidas = set(etl_sync.ALLOWED_COMPANIES)
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
            ano, mes, etl_sync.trimestre(mes), etl_sync.semestre(mes),
            emp_nome, codcencus, "",
            info["bloco"], info["titulo"], descr_natureza,
            orc, real * fator, 0.0, 0.0  # orçado (AD_ORCAMENTO) já vem com sinal: NÃO aplica fator
        ))
        
    # Salvar MariaDB
    with conn_db.cursor() as cur:
        cur.execute("DELETE FROM dre_data WHERE ano = %s AND mes = %s", (ano, mes))
        if batch:
            cur.executemany("""
                INSERT INTO dre_data
                (ano,mes,trimestre,semestre,empresa,codcencus,descrcencus,
                 bloco,titulo,descrnat,orcado,realizado,vb_orcado,vb_realizado)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, batch)
        cur.execute("DELETE FROM dre_resumo_mensal WHERE ano = %s AND mes = %s", (ano, mes))
        cur.execute("""
            INSERT INTO dre_resumo_mensal (ano, mes, empresa, codcencus, bloco, realizado, orcado)
            SELECT ano, mes, empresa, codcencus, bloco, SUM(realizado), SUM(orcado)
            FROM dre_data
            WHERE ano = %s AND mes = %s
            GROUP BY ano, mes, empresa, codcencus, bloco
        """, (ano, mes))
        cur.execute("INSERT IGNORE INTO dre_filtros_anos (ano) VALUES (%s)", (ano,))
        conn_db.commit()
        
    # Espelhar SQLite
    salvar_mes_sqlite(ano, mes, batch)
    
    dur_total = time.time() - t0
    log(f"   [OK] Gravados {len(batch)} registros em {dur_total:.1f}s.")
    return len(batch)

def mes_ja_carregado(conn_db, ano, mes):
    """Verifica se o mês já foi extraído com dados completos válidos."""
    try:
        with conn_db.cursor() as cur:
            cur.execute("SELECT count(*) as total, sum(realizado) as s_real FROM dre_data WHERE ano = %s AND mes = %s", (ano, mes))
            r = cur.fetchone()
            if r and r.get('total', 0) > 0:
                # 2022-01 já carregado com sucesso
                if ano == 2022 and mes == 1 and r.get('total', 0) >= 500 and (r.get('s_real') or 0) != 0:
                    return True
    except Exception:
        pass
    return False

def executar_carga_total(meses_alvo=None):
    log("================================================================")
    log("INICIANDO CARGA TOTAL HISTÓRICA DRE EMPRESA (2022 A OUT/2026)")
    log("================================================================")
    
    if meses_alvo is None:
        meses_alvo = []
        # 1. Todo ano de 2022 (12 meses)
        for m in range(1, 13):
            meses_alvo.append((2022, m))
        # 2. Todo ano de 2023 (12 meses)
        for m in range(1, 13):
            meses_alvo.append((2023, m))
        # 3. Meses recentes de 2026 até hoje (agosto, setembro, outubro)
        meses_alvo.append((2026, 8))
        meses_alvo.append((2026, 9))
        meses_alvo.append((2026, 10))

    log(f"Total de meses a processar: {len(meses_alvo)}")
    log(f"Lista de meses: {meses_alvo}")
    
    oc = etl_sync.conectar_oracle()
    cur_ora = oc.cursor()
    
    log("Carregando dimensões do Oracle (empresas, naturezas, CADDRE)...")
    emp_map, caddre, nat_map = etl_sync.carregar_dimensoes(cur_ora)
    log(f"Dimensões carregadas: {len(emp_map)} empresas, {len(caddre)} regras CADDRE, {len(nat_map)} naturezas.")
    
    log("Preparando texto parametrizado da view VMQ_DREQLIK...")
    cur_ora.execute("SELECT text FROM all_views WHERE owner = 'SANKHYA' AND view_name = 'VMQ_DREQLIK'")
    texto = cur_ora.fetchone()[0]
    if hasattr(texto, "read"):
        texto = texto.read()
    texto_norm = texto.replace("\r\n", "\n").replace("\n", "\r\n")
    for orig, novo in etl_sync._CORTES:
        texto_norm = texto_norm.replace(orig, novo)
        
    conn_db = get_db_connection()
    
    total_linhas_geral = 0
    t_inicio = time.time()
    
    for idx, (ano, mes) in enumerate(meses_alvo, 1):
        log(f"--- Progresso [{idx}/{len(meses_alvo)}] ({idx/len(meses_alvo)*100:.1f}%) ---")
        
        # Pula se já estiver validado
        if mes_ja_carregado(conn_db, ano, mes):
            log(f"  Mês {ano}-{mes:02d} já está carregado e validado no MariaDB. Pulando...")
            continue
            
        sucesso = False
        for tentativa in range(1, 4):
            try:
                # Testa conexão Oracle; se caiu reconecta
                try:
                    cur_ora.execute("SELECT 1 FROM DUAL")
                except Exception:
                    log("Reconectando ao Oracle...")
                    oc = etl_sync.conectar_oracle()
                    cur_ora = oc.cursor()
                
                # Testa MariaDB; se caiu reconecta
                try:
                    conn_db.ping(reconnect=True)
                except Exception:
                    log("Reconectando ao MariaDB...")
                    conn_db = get_db_connection()

                linhas = extrair_e_salvar_mes(cur_ora, texto_norm, ano, mes, emp_map, caddre, nat_map, conn_db)
                total_linhas_geral += linhas
                sucesso = True
                break
            except Exception as e:
                log(f"  !! Falha no mês {ano}-{mes:02d} (tentativa {tentativa}/3): {e}")
                time.sleep(10)
                
        if not sucesso:
            log(f"  [ERRO CRÍTICO] Mês {ano}-{mes:02d} não pôde ser carregado após 3 tentativas.")

    conn_db.close()
    oc.close()
    
    etl_sync.gravar_status_sync("carga histórica completa 2022-2026")
    
    # Limpa cache do Flask se o serviço estiver ativo
    try:
        with urllib.request.urlopen("http://localhost:5150/api/dre/sincronizar-status", timeout=5) as resp:
            log(f"Cache do Flask limpo com sucesso: status {resp.status}")
    except Exception as e:
        log(f"Aviso ao limpar cache do Flask: {e}")
    
    dur_total = time.time() - t_inicio
    log("================================================================")
    log(f"CARGA CONCLUÍDA! Total de novos registros gravados: {total_linhas_geral}")
    log(f"Tempo total decorrido: {dur_total/60:.1f} minutos ({dur_total:.0f}s)")
    log("================================================================")

if __name__ == "__main__":
    executar_carga_total()
