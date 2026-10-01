import os
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    return pymysql.connect(
        host=os.getenv("MARIADB_HOST", "192.168.1.22"),
        user=os.getenv("MARIADB_USER", "antonio"),
        password=os.getenv("MARIADB_PASSWORD", "yzmpq100"),
        port=int(os.getenv("MARIADB_PORT", 3306)),
        database=os.getenv("MARIADB_DB", "dre_empresa"),
        cursorclass=pymysql.cursors.DictCursor
    )
