import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def run():
    db_url = os.getenv("NEON_DB_URL")
    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, protocol_text FROM ai_protocols WHERE is_active = TRUE;")
            rows = cur.fetchall()
            print(f"Trovati {len(rows)} protocolli attivi:")
            for row in rows:
                print(f"ID: {row[0]}, Testo: {row[1]}")
                
            print("Azzeramento di TUTTA la memoria viziata del Supervisore (Clean Slate)...")
            cur.execute("UPDATE ai_protocols SET is_active = FALSE;")
            conn.commit()
            print("Fatto. Memoria resettata.")
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    run()
