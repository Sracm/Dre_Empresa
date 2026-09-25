import os
import sys

# Força codificação UTF-8 para evitar UnicodeEncodeError em terminais Windows (cp1252)
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import time
import subprocess
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "carga_completa_execucao.log")

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Limpa caracteres que não possam ser exibidos se reconfigure falhar
    msg_clean = str(msg).encode("utf-8", errors="replace").decode("utf-8")
    formatted = f"[{ts}] {msg_clean}"
    try:
        print(formatted, flush=True)
    except Exception:
        print(formatted.encode("ascii", errors="replace").decode("ascii"), flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(formatted + "\n")
    except Exception as e:
        pass

def git_push_final(motivo="auto: carga completa noturna DRE desde 2022"):
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_file = os.path.join(BASE_DIR, "data_sync_status.json")
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump({
                "ultima_sincronizacao": ts,
                "motivo": motivo,
                "status": "sucesso"
            }, f, indent=2, ensure_ascii=False)

        log("Adicionando arquivos no Git...")
        subprocess.run(["git", "add", "data_sync_status.json", "templates/index.html", "static/js/app.js", "static/css/style.css", "static/css/components.css", "static/css/responsive.css", "app.py", "etl_oracle.py"], cwd=BASE_DIR, check=False)
        commit_msg = f"{motivo} ({ts})"
        res_c = subprocess.run(["git", "commit", "-m", commit_msg], cwd=BASE_DIR, capture_output=True, text=True, check=False)
        log(f"[GIT COMMIT] {res_c.stdout or res_c.stderr}".strip())

        res_p = subprocess.run(["git", "push", "origin", "master"], cwd=BASE_DIR, capture_output=True, text=True, check=False)
        log(f"[GIT PUSH] {res_p.stdout or res_p.stderr}".strip())
        return True
    except Exception as e:
        log(f"[GIT ERROR] {e}")
        return False

def main():
    log("=======================================================")
    log("INICIANDO PROCESSO DE CARGA COMPLETA DRE (2022 A 2027)")
    log("=======================================================")

    etl_script = os.path.join(BASE_DIR, "etl_oracle.py")
    cmd = [sys.executable, "-u", etl_script, "--anos", "2022,2023,2024,2025,2026,2027"]

    log(f"Comando: {' '.join(cmd)}")
    t0 = time.time()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        cmd,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env
    )

    for line in iter(proc.stdout.readline, ''):
        if line:
            log(line.rstrip())

    proc.stdout.close()
    ret_code = proc.wait()
    duracao = (time.time() - t0) / 60.0

    if ret_code == 0:
        log(f"ETL concluído com SUCESSO em {duracao:.1f} minutos!")
        log("Sincronizando com o GitHub...")
        if git_push_final("auto: carga completa DRE 2022 a 2027 concluída"):
            log("Processo 100% finalizado e sincronizado no GitHub!")
        else:
            log("Aviso: Falha ao enviar para o GitHub.")
    else:
        log(f"ERRO: ETL encerrou com código {ret_code} após {duracao:.1f} minutos.")
        status_file = os.path.join(BASE_DIR, "data_sync_status.json")
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump({
                    "ultima_sincronizacao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "motivo": f"erro na carga completa DRE (código {ret_code})",
                    "status": "erro"
                }, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

if __name__ == "__main__":
    main()
