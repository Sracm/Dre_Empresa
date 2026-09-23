import os
import sys
import time
import shutil
import sqlite3
import oracledb
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "dre_cache.db")
BACKUP_PATH = os.path.join(BASE_DIR, "dre_cache.db.bak_antes_2022")

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

SQL_FATIA = """
    SELECT
        CODEMP,
        CODCENCUS,
        CODNAT,
        REF,
        SUM(VALOR)     AS REALIZADO,
        SUM(ORCAMENTO) AS ORCADO
    FROM SANKHYA.VMQ_DREQLIK
    WHERE DTCOMP >= TO_DATE(:d1, 'YYYY-MM-DD')
      AND DTCOMP <  TO_DATE(:d2, 'YYYY-MM-DD')
      AND CODCENCUS != :cenc_excl
      AND CODEMP    != :emp_excl
    GROUP BY CODEMP, CODCENCUS, CODNAT, REF
"""

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def trimestre(mes):
    return f"Q{((int(mes)-1)//3)+1}"

def semestre(mes):
    return "S1" if int(mes) <= 6 else "S2"

def carregar_apoio(conn):
    cur = conn.cursor()
    new_db = os.path.join(BASE_DIR, "dre_cache.new.db")
    if os.path.exists(new_db):
        try:
            nconn = sqlite3.connect(new_db)
            ncur = nconn.cursor()
            emp_map = {int(r[0]): r[1] for r in ncur.execute("SELECT codemp, nome FROM emp_map").fetchall()}
            caddre = {
                (int(r[0]), int(r[1]), r[5] or ''): {
                    "bloco": r[2], "titulo": r[3], "fator": float(r[4]), "ref": r[5] or ''
                }
                for r in ncur.execute("SELECT codnat, codcencus, bloco, titulo, fator, ref FROM caddre").fetchall()
            }
            nconn.close()
            if emp_map and caddre:
                log(f"Apoio lido com sucesso de {os.path.basename(new_db)}: {len(emp_map)} empresas, {len(caddre)} regras CADDRE.")
                return emp_map, caddre
        except Exception as e:
            log(f"Aviso ao ler {new_db}: {e}. Consultando Oracle...")

    # Fallback consultando Oracle direto
    oc = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASS, dsn=ORACLE_DSN)
    ocur = oc.cursor()
    ocur.execute("SELECT CODEMP, RAZAOABREV FROM SANKHYA.VMQ_TSIEMP ORDER BY CODEMP")
    emp_map = {int(r[0]): str(r[1]) for r in ocur.fetchall() if r[0] is not None}
    
    ocur.execute("SELECT BLOCO, TITULO, CODNAT, CODCENCUS, FATOR, REF FROM SANKHYA.VMQ_CADDRE")
    caddre = {}
    for bloco, titulo, codnat, codcencus, fator, ref in ocur.fetchall():
        ref_val = ref or ''
        key = (int(codnat) if codnat else 0, int(codcencus) if codcencus else 0, ref_val)
        caddre[key] = {
            "bloco": bloco or "",
            "titulo": titulo or "",
            "fator": float(fator) if fator else 1.0,
            "ref": ref_val
        }
    oc.close()
    return emp_map, caddre

def extrair_mes(ano, mes, emp_map, caddre, conn):
    d1 = f"{ano:04d}-{mes:02d}-01"
    d2 = f"{ano:04d}-{mes+1:02d}-01" if mes < 12 else f"{ano+1:04d}-01-01"
    
    log(f"Iniciando extração do mês {ano}-{mes:02d} ({d1} a {d2})...")
    t0 = time.time()
    
    oc = oracledb.connect(user=ORACLE_USER, password=ORACLE_PASS, dsn=ORACLE_DSN)
    cur = oc.cursor()
    cur.arraysize = 5000
    cur.execute(SQL_FATIA, d1=d1, d2=d2, cenc_excl=EXCLUDED_CODCENCUS, emp_excl=EXCLUDED_CODEMP)
    rows = cur.fetchall()
    oc.close()
    
    dur_oracle = time.time() - t0
    log(f"  Oracle retornou {len(rows)} linhas agregadas em {dur_oracle:.1f}s.")
    
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
        batch.append((
            ano, mes, trimestre(mes), semestre(mes),
            emp_nome, codcencus, "",
            info["bloco"], info["titulo"], str(codnat),
            orc * fator, real * fator, 0.0, 0.0
        ))
        
    log(f"  Inserindo {len(batch)} registros em dre_data...")
    # Remove registros antigos desse mês específico para evitar duplicações
    conn.execute("DELETE FROM dre_data WHERE ano = ? AND mes = ?", (ano, mes))
    conn.executemany("""
        INSERT INTO dre_data
        (ano,mes,trimestre,semestre,empresa,codcencus,descrcencus,
         bloco,titulo,descrnat,orcado,realizado,vb_orcado,vb_realizado)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, batch)
    
    # Atualiza dre_resumo_mensal para esse mês
    conn.execute("DELETE FROM dre_resumo_mensal WHERE ano = ? AND mes = ?", (ano, mes))
    conn.execute("""
        INSERT INTO dre_resumo_mensal (ano, mes, empresa, codcencus, bloco, realizado, orcado)
        SELECT ano, mes, empresa, codcencus, bloco, SUM(realizado), SUM(orcado)
        FROM dre_data
        WHERE ano = ? AND mes = ?
        GROUP BY ano, mes, empresa, codcencus, bloco
    """, (ano, mes))
    
    # Garante ano na lista de filtros
    conn.execute("INSERT OR IGNORE INTO dre_filtros_anos (ano) VALUES (?)", (ano,))
    conn.commit()
    log(f"  [OK] Mês {ano}-{mes:02d} gravado com sucesso! Total no mês: {len(batch)} linhas. Tempo total: {time.time()-t0:.1f}s.")

def main():
    ano = 2022
    log(f"=== INICIANDO EXTRAÇÃO DE {ano} PARA O DRE EMPRESA ===")
    
    if not os.path.exists(BACKUP_PATH) and os.path.exists(DB_PATH):
        log(f"Criando backup de segurança em {os.path.basename(BACKUP_PATH)}...")
        shutil.copy2(DB_PATH, BACKUP_PATH)
        log("Backup criado com sucesso.")
        
    oracledb.init_oracle_client()
    conn = sqlite3.connect(DB_PATH, timeout=60.0)
    
    log("Carregando empresas e CADDRE...")
    emp_map, caddre = carregar_apoio(conn)
    log(f"Apoio carregado: {len(emp_map)} empresas, {len(caddre)} regras CADDRE.")
    
    # Verifica quais meses já estão carregados para não re-extrair à toa
    c = conn.cursor()
    meses_existentes = set(r[0] for r in c.execute("SELECT DISTINCT mes FROM dre_data WHERE ano = ?", (ano,)).fetchall())
    log(f"Meses de {ano} já existentes no banco: {sorted(meses_existentes) if meses_existentes else 'Nenhum'}")
    
    for mes in range(1, 13):
        if mes in meses_existentes:
            log(f"Mês {ano}-{mes:02d} já existe no banco. Pulando...")
            continue
        try:
            extrair_mes(ano, mes, emp_map, caddre, conn)
        except Exception as e:
            log(f"ERRO no mês {ano}-{mes:02d}: {e}")
            import traceback
            traceback.print_exc()
            log("Pausando 10s antes do próximo mês...")
            time.sleep(10)
            
    conn.close()
    log(f"=== EXTRAÇÃO DE {ano} CONCLUÍDA ===")

if __name__ == "__main__":
    main()
