"""
Migrate HealthChat data from local SQLite database to remote MariaDB server
with client-side envelope encryption (AES-256-GCM + Argon2id).
Target user: anders@andrix.se
"""

import os
import shutil
import sqlite3
import pymysql
import json
import logging
from pathlib import Path
from typing import Optional

import auth
import crypto

import sys
import getpass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("migrate")

DEFAULT_SQLITE_PATH = Path.home() / ".healthchat" / "healthdata.db"
MARIADB_HOST = os.environ.get("MARIADB_HOST", "192.168.101.106")
MARIADB_PORT = int(os.environ.get("MARIADB_PORT", 3306))
MARIADB_USER = os.environ.get("MARIADB_USER", "healthchat")
MARIADB_DB = os.environ.get("MARIADB_DB", "healthchat")


def migrate_to_encrypted_mariadb(
    sqlite_path: Optional[Path] = None,
    email: Optional[str] = None,
    password: Optional[str] = None,
    db_password: Optional[str] = None
):
    if not email:
        email = input("Ange target e-post för kontot: ").strip()
    if not password:
        password = getpass.getpass("Ange kontolösenord: ").strip()
    if not db_password:
        db_password = os.environ.get("MARIADB_PASSWORD") or getpass.getpass("Ange MariaDB databaslösenord: ").strip()
    if sqlite_path is None:
        sqlite_path = DEFAULT_SQLITE_PATH
    else:
        sqlite_path = Path(sqlite_path)

    if not sqlite_path.exists():
        logger.error(f"SQLite database not found at {sqlite_path}")
        return False

    # 1. Backup SQLite database
    backup_path = sqlite_path.with_suffix(".db.backup")
    logger.info(f"Creating backup of SQLite database to {backup_path}...")
    shutil.copy2(sqlite_path, backup_path)
    logger.info("Backup created successfully.")

    # 2. Connect to MariaDB
    logger.info(f"Connecting to MariaDB at {MARIADB_HOST}:{MARIADB_PORT} ({MARIADB_DB})...")
    m_conn = pymysql.connect(
        host=MARIADB_HOST,
        port=MARIADB_PORT,
        user=MARIADB_USER,
        password=db_password,
        database=MARIADB_DB,
        charset="utf8mb4",
        autocommit=False
    )

    try:
        # 3. Authenticate or register user
        session = None
        try:
            logger.info(f"Checking if account '{auth.mask_email(email)}' exists...")
            session = auth.authenticate_user(m_conn, email, password)
            logger.info(f"Authenticated existing account '{auth.mask_email(email)}' (user_id: {session.user_id}).")
        except ValueError:
            logger.info(f"Account for '{auth.mask_email(email)}' does not exist yet. Registering new account...")
            user_id, rec_key, session = auth.register_user(m_conn, email, password)
            logger.info(f"Registered user (id: {user_id}). Recovery key generated.")
            print("\n" + "!" * 50)
            print(f"ÅTERSTÄLLNINGSNYCKEL FÖR {email}:")
            print(f"  {rec_key}")
            print("SPARA DENNA NYCKEL PÅ ETT SÄKERT STÄLLE (t.ex. lösenordshanterare).")
            print("!" * 50 + "\n")

        user_id = session.user_id
        dek = session.dek

        # 4. Open SQLite database
        s_conn = sqlite3.connect(sqlite_path)
        s_conn.row_factory = sqlite3.Row
        s_cur = s_conn.cursor()
        m_cur = m_conn.cursor()

        tables = [
            "daily_summary",
            "sleep_data",
            "body_battery",
            "stress_data",
            "hrv_data",
            "activities",
            "body_composition",
            "calorie_burn",
            "sync_metadata"
        ]

        allowed_tables = set(tables)
        migration_summary = {}

        for table in tables:
            if table not in allowed_tables:
                raise ValueError(f"Untrusted table name: {table}")

            s_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not s_cur.fetchone():
                logger.info(f"Skipping table {table} (not in SQLite)")
                continue

            s_cur.execute(f"SELECT * FROM `{table}`")
            rows = s_cur.fetchall()
            if not rows:
                migration_summary[table] = 0
                continue

            batch_data = []

            if table == "activities":
                sql = "INSERT INTO activities (user_id, activity_id, date, encrypted_payload, nonce) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE date = VALUES(date), encrypted_payload = VALUES(encrypted_payload), nonce = VALUES(nonce)"
                for r in rows:
                    act_dict = dict(r)
                    act_id = act_dict.get("activity_id")
                    date_val = str(act_dict.get("date") or act_dict.get("start_time") or "")[:10]
                    nonce, ciphertext = crypto.encrypt_payload(dek, act_dict)
                    batch_data.append((user_id, act_id, date_val, ciphertext, nonce))
            elif table == "sync_metadata":
                sql = "INSERT INTO sync_metadata (user_id, `key`, `value`) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)"
                for r in rows:
                    batch_data.append((user_id, r["key"], r["value"]))
            else:
                sql = f"INSERT INTO `{table}` (user_id, date, encrypted_payload, nonce) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE encrypted_payload = VALUES(encrypted_payload), nonce = VALUES(nonce)"
                for r in rows:
                    row_dict = dict(r)
                    date_val = str(row_dict.get("date", ""))[:10]
                    nonce, ciphertext = crypto.encrypt_payload(dek, row_dict)
                    batch_data.append((user_id, date_val, ciphertext, nonce))

            m_cur.executemany(sql, batch_data)
            m_conn.commit()
            migration_summary[table] = len(batch_data)
            logger.info(f"Table {table}: Migrated and encrypted {len(batch_data)} rows.")

        s_conn.close()

        # Save remember me session to OS keyring
        auth.save_remembered_session(email, dek)

        print("\n" + "="*50)
        print(f"MIGRATION COMPLETED SUCCESSFULLY FOR {email}")
        print("="*50)
        for t, count in migration_summary.items():
            print(f"  • {t:<20}: {count:>5} rader krypterade")
        print("="*50)
        print("Data har krypterats med AES-256-GCM och sparats i MariaDB.")
        print(f"Lokal säkerhetskopia finns på: {backup_path}")
        print("="*50 + "\n")
        return True

    except Exception as e:
        m_conn.rollback()
        logger.error(f"Migration error: {e}", exc_info=True)
        return False
    finally:
        m_conn.close()


if __name__ == "__main__":
    migrate_to_encrypted_mariadb()
