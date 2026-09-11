"""
Garmin Database Handler for HealthChat Desktop.
Provides MariaDB database storage with connection pooling, user isolation,
and client-side envelope encryption, as well as SQLite fallback for offline testing.
"""

import os
import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union

import pymysql
from dbutils.pooled_db import PooledDB
import crypto

logger = logging.getLogger("garmin_db")

DEFAULT_MARIADB_HOST = "192.168.101.106"
DEFAULT_MARIADB_PORT = 3306
DEFAULT_MARIADB_USER = "healthchat"
DEFAULT_MARIADB_DB = "healthchat"

_ALLOWED_TABLES: frozenset[str] = frozenset({
    "daily_summary",
    "sleep_data",
    "body_battery",
    "stress_data",
    "hrv_data",
    "activities",
    "body_composition",
    "calorie_burn",
    "users",
    "user_sessions",
    "sync_metadata"
})


# Template written to ~/.healthchat/db.env when no configuration exists yet.
# Every line is commented out and no credential is embedded: the operator fills
# it in. Never add a default password here - it would end up in version control
# and in every installation.
_DB_ENV_TEMPLATE = """\
# HealthChat MariaDB-konfiguration.
# Läses av load_db_env() i garmin_db.py. Filen ligger utanför git-repot.
# Avkommentera och fyll i värdena nedan, eller sätt motsvarande
# miljövariabler i systemd-enheten (EnvironmentFile).
#
# Filen ska ha rättigheterna 0600 (endast ägaren kan läsa den).

#MARIADB_HOST=
#MARIADB_PORT=3306
#MARIADB_USER=healthchat
#MARIADB_PASSWORD=
#MARIADB_DB=healthchat
"""


def _write_db_env_template(path: Path):
    """Write the credential-free db.env template with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the start so the file is never briefly world-readable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_DB_ENV_TEMPLATE)
    logger.info(f"Skapade konfigurationsmall utan lösenord: {path}")


def _warn_if_world_readable(path: Path):
    """Log a warning when a file holding credentials is readable by others."""
    try:
        mode = path.stat().st_mode
        if mode & 0o077:
            logger.warning(
                f"{path} är läsbar för andra användare (rättigheter {mode & 0o777:o}). "
                f"Kör: chmod 600 {path}"
            )
    except OSError:
        pass


def load_db_env():
    """Load key-value environment variables from ~/.healthchat/db.env or local .env into os.environ if missing.

    Values already present in os.environ always win, so a systemd EnvironmentFile
    or an explicitly exported variable cannot be overridden by a stray file in the
    user's home directory.
    """
    db_env_file = Path.home() / ".healthchat" / "db.env"
    local_env_file = Path.cwd() / ".env"

    if not db_env_file.exists() and not local_env_file.exists():
        try:
            _write_db_env_template(db_env_file)
        except Exception as e:
            logger.debug(f"Could not auto-create db.env: {e}")

    env_paths = [local_env_file, db_env_file]
    for p in env_paths:
        if p.is_file():
            _warn_if_world_readable(p)
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and v:
                                os.environ.setdefault(k, v)
            except Exception as e:
                logger.debug(f"Failed to load env file {p}: {e}")


def get_mariadb_connection(config: Optional[Dict[str, Any]] = None):
    """Create and return a raw pymysql connection to the MariaDB server."""
    load_db_env()
    cfg = config or {}
    host = cfg.get("host") or os.environ.get("MARIADB_HOST", DEFAULT_MARIADB_HOST)
    port = int(cfg.get("port") or os.environ.get("MARIADB_PORT", DEFAULT_MARIADB_PORT))
    user = cfg.get("user") or os.environ.get("MARIADB_USER", DEFAULT_MARIADB_USER)
    password = cfg.get("password") or os.environ.get("MARIADB_PASSWORD")
    database = cfg.get("database") or os.environ.get("MARIADB_DB", DEFAULT_MARIADB_DB)

    if not password:
        raise RuntimeError("MARIADB_PASSWORD saknas – sätt miljövariabel eller ~/.healthchat/db.env")

    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=False
    )


class GarminDatabase:
    """Database Manager for health and activity data supporting MariaDB and SQLite."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        mariadb_config: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
        dek: Optional[bytes] = None
    ):
        self.user_id = user_id
        self.dek = dek
        self.pool: Optional[PooledDB] = None
        self.is_mariadb = False

        load_db_env()
        if mariadb_config is None and db_path is None:
            password = os.environ.get("MARIADB_PASSWORD")
            if password or os.environ.get("MARIADB_HOST"):
                mariadb_config = {
                    "host": os.environ.get("MARIADB_HOST", DEFAULT_MARIADB_HOST),
                    "port": int(os.environ.get("MARIADB_PORT", DEFAULT_MARIADB_PORT)),
                    "user": os.environ.get("MARIADB_USER", DEFAULT_MARIADB_USER),
                    "password": password,
                    "database": os.environ.get("MARIADB_DB", DEFAULT_MARIADB_DB),
                }
        self.mariadb_config = mariadb_config

        if mariadb_config and mariadb_config.get("host"):
            try:
                self._init_mariadb_pool(mariadb_config)
                self.is_mariadb = True
                logger.info(f"Connected to MariaDB at {mariadb_config.get('host')}:{mariadb_config.get('port', 3306)}")
            except Exception as e:
                logger.warning(f"Failed to connect to MariaDB pool, falling back to SQLite: {e}")
                self.is_mariadb = False

        # SQLite fallback setup
        if db_path is None:
            config_dir = Path.home() / '.healthchat'
            config_dir.mkdir(parents=True, exist_ok=True)
            db_path = config_dir / 'healthdata.db'
            
        self.db_path = db_path
        self.init_sqlite_db()

    def _init_mariadb_pool(self, config: Dict[str, Any]):
        """Initialize connection pool for MariaDB with ping, timeouts, and optional TLS."""
        password = config.get("password") or os.environ.get("MARIADB_PASSWORD")
        if not password:
            raise RuntimeError("MARIADB_PASSWORD saknas – sätt miljövariabel eller ~/.healthchat/db.env")

        ssl_config = None
        require_tls = os.environ.get("MARIADB_REQUIRE_TLS", "0") == "1" or config.get("require_tls")
        ca_path = config.get("ssl_ca") or os.environ.get("MARIADB_SSL_CA") or str(Path.home() / ".healthchat" / "ca.pem")
        if os.path.exists(ca_path):
            ssl_config = {"ca": ca_path}
        elif require_tls:
            raise RuntimeError(f"MARIADB_REQUIRE_TLS=1 men SSL CA certifikat saknas på sökvägen: {ca_path}")

        connect_timeout = int(config.get("connect_timeout") or os.environ.get("MARIADB_CONNECT_TIMEOUT", 5))
        read_timeout = int(config.get("read_timeout") or os.environ.get("MARIADB_READ_TIMEOUT", 30))
        write_timeout = int(config.get("write_timeout") or os.environ.get("MARIADB_WRITE_TIMEOUT", 30))

        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=int(os.environ.get("MARIADB_MAX_CONNECTIONS", "10")),
            mincached=int(os.environ.get("MARIADB_MIN_CACHED", "2")),
            maxcached=int(os.environ.get("MARIADB_MAX_CACHED", "5")),
            blocking=True,
            ping=1,
            host=config.get("host", DEFAULT_MARIADB_HOST),
            port=int(config.get("port", DEFAULT_MARIADB_PORT)),
            user=config.get("user", DEFAULT_MARIADB_USER),
            password=password,
            database=config.get("database", DEFAULT_MARIADB_DB),
            charset="utf8mb4",
            autocommit=True,
            ssl=ssl_config,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            write_timeout=write_timeout,
        )

    def set_user_session(self, user_id: int, dek: bytes):
        """Set active user session for encrypted MariaDB operations."""
        self.user_id = user_id
        self.dek = dek
        logger.info(f"GarminDatabase: Active session set for user_id {user_id}")

    def get_connection(self):
        """Get a connection to SQLite (with WAL enabled)."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_mariadb_conn(self):
        """Get a connection from the MariaDB connection pool."""
        if not self.pool:
            raise RuntimeError("MariaDB connection pool is not initialized")
        return self.pool.connection()

    def init_sqlite_db(self):
        """Create SQLite database tables if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_summary (
                date TEXT PRIMARY KEY,
                total_steps INTEGER DEFAULT 0,
                total_calories INTEGER DEFAULT 0,
                active_calories INTEGER DEFAULT 0,
                resting_hr INTEGER DEFAULT 0,
                raw_json TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sleep_data (
                date TEXT PRIMARY KEY,
                total_sleep_hours REAL DEFAULT 0,
                deep_sleep_hours REAL DEFAULT 0,
                light_sleep_hours REAL DEFAULT 0,
                rem_sleep_hours REAL DEFAULT 0,
                awake_hours REAL DEFAULT 0,
                sleep_score INTEGER DEFAULT 0,
                raw_json TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS body_battery (
                date TEXT PRIMARY KEY,
                charged INTEGER DEFAULT 0,
                drained INTEGER DEFAULT 0,
                highest INTEGER DEFAULT 0,
                lowest INTEGER DEFAULT 0,
                current INTEGER DEFAULT 0
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS stress_data (
                date TEXT PRIMARY KEY,
                average INTEGER DEFAULT 0,
                max INTEGER DEFAULT 0,
                rest INTEGER DEFAULT 0,
                activity INTEGER DEFAULT 0,
                low_duration_min INTEGER DEFAULT 0,
                medium_duration_min INTEGER DEFAULT 0,
                high_duration_min INTEGER DEFAULT 0
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS hrv_data (
                date TEXT PRIMARY KEY,
                last_night_avg REAL DEFAULT 0,
                weekly_avg REAL DEFAULT 0,
                status TEXT DEFAULT ''
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                activity_id INTEGER PRIMARY KEY,
                activity_name TEXT,
                activity_type TEXT,
                start_time TEXT,
                date TEXT,
                distance_km REAL DEFAULT 0,
                duration_min REAL DEFAULT 0,
                calories INTEGER DEFAULT 0,
                avg_hr INTEGER DEFAULT 0,
                max_hr INTEGER DEFAULT 0,
                avg_pace_min_km REAL DEFAULT 0,
                source TEXT DEFAULT 'Garmin',
                raw_json TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS body_composition (
                date TEXT PRIMARY KEY,
                weight_kg REAL DEFAULT 0,
                fat_ratio_pct REAL DEFAULT 0,
                muscle_mass_kg REAL DEFAULT 0,
                bone_mass_kg REAL DEFAULT 0,
                water_pct REAL DEFAULT 0,
                bmi REAL DEFAULT 0,
                source TEXT DEFAULT 'withings',
                raw_json TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS calorie_burn (
                date TEXT PRIMARY KEY,
                total_burn INTEGER DEFAULT 0,
                resting_burn INTEGER DEFAULT 0,
                steps_burn INTEGER DEFAULT 0,
                workout_burn INTEGER DEFAULT 0,
                bmr_full INTEGER DEFAULT 0,
                steps INTEGER DEFAULT 0,
                weight_kg REAL DEFAULT 0,
                day_fraction REAL DEFAULT 1.0,
                bmr_source TEXT DEFAULT '',
                updated_at TEXT,
                raw_json TEXT
            )
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(activity_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_body_comp_date ON body_composition(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_calorie_burn_date ON calorie_burn(date)")
            
            conn.commit()

    @staticmethod
    def _normalize_date(date_input: Optional[str], strict: bool = False) -> str:
        if not date_input:
            if strict:
                raise ValueError("Datumsträng saknas i strict-läge.")
            return datetime.now().strftime('%Y-%m-%d')
        date_str = str(date_input).strip()
        if len(date_str) >= 10 and date_str[0:4].isdigit() and date_str[4] in ('-', '/') and date_str[7] in ('-', '/'):
            return date_str[:10].replace('/', '-')
        for fmt in (
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y",
            "%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y.%m.%d",
            "%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S", "%b %d, %Y",
            "%d %b %Y, %H:%M:%S", "%d %b %Y"
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
        logger.warning(f"Okänt datumformat: {date_str!r} – faller tillbaka på dagens datum")
        if strict:
            raise ValueError(f"Okänt datumformat: {date_str!r}")
        return datetime.now().strftime('%Y-%m-%d')

    # --- ENCRYPTED MARIADB HELPER METHODS ---

    def _mariadb_upsert_payload(self, table: str, date: str, payload: Dict[str, Any]):
        """Encrypt payload with DEK and save row to MariaDB with (user_id, date)."""
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Ogiltigt eller otillåtet tabellnamn: {table!r}")

        if not self.dek or self.user_id is None:
            logger.warning(f"Cannot write encrypted data to {table}: missing user session")
            return

        nonce, ciphertext = crypto.encrypt_payload(self.dek, payload)
        conn = self.get_mariadb_conn()
        try:
            with conn.cursor() as cur:
                sql = f"INSERT INTO `{table}` (user_id, date, encrypted_payload, nonce) VALUES (%s, %s, %s, %s) ON DUPLICATE KEY UPDATE encrypted_payload = VALUES(encrypted_payload), nonce = VALUES(nonce)"
                cur.execute(sql, (self.user_id, date, ciphertext, nonce))
        finally:
            conn.close()

    def _mariadb_get_history(self, table: str, days: int = 30) -> List[Dict]:
        """Fetch and decrypt history rows from MariaDB for the current user."""
        if table not in _ALLOWED_TABLES:
            raise ValueError(f"Ogiltigt eller otillåtet tabellnamn: {table!r}")

        if not self.dek or self.user_id is None:
            return []

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        conn = self.get_mariadb_conn()
        results = []
        try:
            with conn.cursor() as cur:
                sql = f"SELECT encrypted_payload, nonce FROM `{table}` WHERE user_id = %s AND date >= %s ORDER BY date ASC"
                cur.execute(sql, (self.user_id, start_date))
                rows = cur.fetchall()

            for ciphertext, nonce in rows:
                try:
                    data = crypto.decrypt_payload(self.dek, ciphertext, nonce)
                    results.append(data)
                except Exception as e:
                    logger.debug(f"Failed decrypting row from {table}: {e}")
        finally:
            conn.close()
        return results

    # --- UPSERT METHODS ---

    def upsert_daily_summary(self, date: str, steps: int = 0, calories: int = 0, active_calories: int = 0, resting_hr: int = 0, raw_data: Optional[Dict] = None):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "total_steps": steps,
            "total_calories": calories,
            "active_calories": active_calories,
            "resting_hr": resting_hr,
            "raw_json": json.dumps(raw_data) if raw_data else None
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("daily_summary", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO daily_summary (date, total_steps, total_calories, active_calories, resting_hr, raw_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_steps=excluded.total_steps,
                total_calories=excluded.total_calories,
                active_calories=excluded.active_calories,
                resting_hr=excluded.resting_hr,
                raw_json=excluded.raw_json
            """, (date, steps, calories, active_calories, resting_hr, json.dumps(raw_data) if raw_data else None))
            conn.commit()

    def upsert_sleep(self, date: str, total_hours: float, deep_hours: float = 0, light_hours: float = 0, rem_hours: float = 0, awake_hours: float = 0, score: int = 0, raw_data: Optional[Dict] = None):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "total_sleep_hours": total_hours,
            "deep_sleep_hours": deep_hours,
            "light_sleep_hours": light_hours,
            "rem_sleep_hours": rem_hours,
            "awake_hours": awake_hours,
            "sleep_score": score,
            "raw_json": json.dumps(raw_data) if raw_data else None
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("sleep_data", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO sleep_data (date, total_sleep_hours, deep_sleep_hours, light_sleep_hours, rem_sleep_hours, awake_hours, sleep_score, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_sleep_hours=excluded.total_sleep_hours,
                deep_sleep_hours=excluded.deep_sleep_hours,
                light_sleep_hours=excluded.light_sleep_hours,
                rem_sleep_hours=excluded.rem_sleep_hours,
                awake_hours=excluded.awake_hours,
                sleep_score=excluded.sleep_score,
                raw_json=excluded.raw_json
            """, (date, total_hours, deep_hours, light_hours, rem_hours, awake_hours, score, json.dumps(raw_data) if raw_data else None))
            conn.commit()

    def upsert_body_battery(self, date: str, charged: int, drained: int, highest: int, lowest: int, current: int):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "charged": charged,
            "drained": drained,
            "highest": highest,
            "lowest": lowest,
            "current": current
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("body_battery", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO body_battery (date, charged, drained, highest, lowest, current)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                charged=excluded.charged,
                drained=excluded.drained,
                highest=excluded.highest,
                lowest=excluded.lowest,
                current=excluded.current
            """, (date, charged, drained, highest, lowest, current))
            conn.commit()

    def upsert_stress(self, date: str, average: int, max_stress: int, rest: int, activity: int, low_min: int = 0, med_min: int = 0, high_min: int = 0):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "average": average,
            "max": max_stress,
            "rest": rest,
            "activity": activity,
            "low_duration_min": low_min,
            "medium_duration_min": med_min,
            "high_duration_min": high_min
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("stress_data", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO stress_data (date, average, max, rest, activity, low_duration_min, medium_duration_min, high_duration_min)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                average=excluded.average,
                max=excluded.max,
                rest=excluded.rest,
                activity=excluded.activity,
                low_duration_min=excluded.low_duration_min,
                medium_duration_min=excluded.medium_duration_min,
                high_duration_min=excluded.high_duration_min
            """, (date, average, max_stress, rest, activity, low_min, med_min, high_min))
            conn.commit()

    def upsert_hrv(self, date: str, last_night_avg: float, weekly_avg: float = 0, status: str = ""):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "last_night_avg": last_night_avg,
            "weekly_avg": weekly_avg,
            "status": status
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("hrv_data", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO hrv_data (date, last_night_avg, weekly_avg, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                last_night_avg=excluded.last_night_avg,
                weekly_avg=excluded.weekly_avg,
                status=excluded.status
            """, (date, last_night_avg, weekly_avg, status))
            conn.commit()

    def upsert_activity(self, activity: Dict) -> None:
        """Upsert activity record to database."""
        if hasattr(self, "_max_hr_cache"):
            self._max_hr_cache.clear()

        act_id = str(activity.get('activityId') or activity.get('id') or activity.get('activity_id') or '').strip()
        if not act_id:
            return
            
        act_name = activity.get('activityName') or 'Aktivitet'
        act_type_raw = activity.get('activityType') or 'Träning'
        if isinstance(act_type_raw, dict):
            act_type = act_type_raw.get('typeKey') or 'Träning'
        elif act_type_raw is not None:
            act_type = str(act_type_raw)
        else:
            act_type = 'Träning'
            
        start_time = activity.get('startTimeLocal') or activity.get('start_time') or ''
        date_str = self._normalize_date(start_time)
        
        if 'distance_km' in activity and activity['distance_km'] is not None:
            distance_km = float(activity.get('distance_km') or 0.0)
        else:
            distance_km = float(activity.get('distance') or 0.0) / 1000.0
            
        if 'duration_min' in activity and activity['duration_min'] is not None:
            duration_min = float(activity.get('duration_min') or 0.0)
        else:
            duration_min = float(activity.get('duration') or 0.0) / 60.0

        calories = int(float(activity.get('calories') or 0))
        avg_hr = int(float(activity.get('averageHR') or activity.get('avg_hr') or 0))
        max_hr = int(float(activity.get('maxHR') or activity.get('max_hr') or 0))
        
        if 'avg_pace_min_km' in activity and activity['avg_pace_min_km'] is not None:
            avg_pace_min_km = float(activity.get('avg_pace_min_km') or 0.0)
        else:
            avg_speed_ms = float(activity.get('averageSpeed') or 0.0)
            avg_pace_min_km = (1000 / (avg_speed_ms * 60)) if avg_speed_ms > 0 else 0.0
        
        source = str(activity.get('source') or 'Garmin')

        payload = {
            "activity_id": act_id,
            "activity_name": act_name,
            "activity_type": act_type,
            "start_time": start_time,
            "date": date_str,
            "distance_km": distance_km,
            "duration_min": duration_min,
            "calories": calories,
            "avg_hr": avg_hr,
            "max_hr": max_hr,
            "avg_pace_min_km": avg_pace_min_km,
            "source": source,
            "raw_json": json.dumps(activity)
        }

        if self.is_mariadb and self.user_id and self.dek:
            nonce, ciphertext = crypto.encrypt_payload(self.dek, payload)
            conn = self.get_mariadb_conn()
            try:
                with conn.cursor() as cur:
                    sql = "INSERT INTO activities (user_id, activity_id, date, encrypted_payload, nonce) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE date = VALUES(date), encrypted_payload = VALUES(encrypted_payload), nonce = VALUES(nonce)"
                    cur.execute(sql, (self.user_id, act_id, date_str, ciphertext, nonce))
            finally:
                conn.close()
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO activities (activity_id, activity_name, activity_type, start_time, date, distance_km, duration_min, calories, avg_hr, max_hr, avg_pace_min_km, source, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                activity_name=excluded.activity_name,
                activity_type=excluded.activity_type,
                start_time=excluded.start_time,
                date=excluded.date,
                distance_km=excluded.distance_km,
                duration_min=excluded.duration_min,
                calories=excluded.calories,
                avg_hr=excluded.avg_hr,
                max_hr=excluded.max_hr,
                avg_pace_min_km=excluded.avg_pace_min_km,
                source=excluded.source,
                raw_json=excluded.raw_json
            """, (act_id, act_name, act_type, start_time, date_str, distance_km, duration_min, calories, avg_hr, max_hr, avg_pace_min_km, source, json.dumps(activity)))
            conn.commit()

    def upsert_body_composition(
        self,
        date: str,
        weight_kg: float = 0.0,
        fat_ratio_pct: float = 0.0,
        muscle_mass_kg: float = 0.0,
        bone_mass_kg: float = 0.0,
        water_pct: float = 0.0,
        bmi: float = 0.0,
        source: str = 'withings',
        raw_data: Optional[Dict] = None
    ):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "weight_kg": weight_kg,
            "fat_ratio_pct": fat_ratio_pct,
            "muscle_mass_kg": muscle_mass_kg,
            "bone_mass_kg": bone_mass_kg,
            "water_pct": water_pct,
            "bmi": bmi,
            "source": source,
            "raw_json": json.dumps(raw_data) if raw_data else None
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("body_composition", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO body_composition (
                date, weight_kg, fat_ratio_pct, muscle_mass_kg, bone_mass_kg, water_pct, bmi, source, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                weight_kg=excluded.weight_kg,
                fat_ratio_pct=excluded.fat_ratio_pct,
                muscle_mass_kg=excluded.muscle_mass_kg,
                bone_mass_kg=excluded.bone_mass_kg,
                water_pct=excluded.water_pct,
                bmi=excluded.bmi,
                source=excluded.source,
                raw_json=excluded.raw_json
            """, (
                date, weight_kg, fat_ratio_pct, muscle_mass_kg, bone_mass_kg, water_pct, bmi, source,
                json.dumps(raw_data) if raw_data else None
            ))
            conn.commit()

    def upsert_calorie_burn(
        self,
        date: str,
        total_burn: int = 0,
        resting_burn: int = 0,
        steps_burn: int = 0,
        workout_burn: int = 0,
        bmr_full: int = 0,
        steps: int = 0,
        weight_kg: float = 0.0,
        day_fraction: float = 1.0,
        bmr_source: str = '',
        raw_data: Optional[Dict] = None,
    ):
        date = self._normalize_date(date)
        payload = {
            "date": date,
            "total_burn": int(total_burn),
            "resting_burn": int(resting_burn),
            "steps_burn": int(steps_burn),
            "workout_burn": int(workout_burn),
            "bmr_full": int(bmr_full),
            "steps": int(steps),
            "weight_kg": float(weight_kg or 0.0),
            "day_fraction": float(day_fraction or 0.0),
            "bmr_source": str(bmr_source or ''),
            "updated_at": datetime.now().isoformat(),
            "raw_json": json.dumps(raw_data) if raw_data else None,
        }
        if self.is_mariadb and self.user_id and self.dek:
            self._mariadb_upsert_payload("calorie_burn", date, payload)
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO calorie_burn (
                date, total_burn, resting_burn, steps_burn, workout_burn,
                bmr_full, steps, weight_kg, day_fraction, bmr_source, updated_at, raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_burn=excluded.total_burn,
                resting_burn=excluded.resting_burn,
                steps_burn=excluded.steps_burn,
                workout_burn=excluded.workout_burn,
                bmr_full=excluded.bmr_full,
                steps=excluded.steps,
                weight_kg=excluded.weight_kg,
                day_fraction=excluded.day_fraction,
                bmr_source=excluded.bmr_source,
                updated_at=excluded.updated_at,
                raw_json=excluded.raw_json
            """, (
                date, int(total_burn), int(resting_burn), int(steps_burn), int(workout_burn),
                int(bmr_full), int(steps), float(weight_kg or 0.0), float(day_fraction or 0.0),
                str(bmr_source or ''), datetime.now().isoformat(),
                json.dumps(raw_data) if raw_data else None,
            ))
            conn.commit()

    # --- QUERY METHODS ---

    def get_daily_summary_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("daily_summary", days)

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_summary WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_daily_summary(self, date: Optional[str] = None) -> Optional[Dict]:
        date = self._normalize_date(date)
        if self.is_mariadb and self.user_id and self.dek:
            conn = self.get_mariadb_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT encrypted_payload, nonce FROM daily_summary WHERE user_id = %s AND date = %s", (self.user_id, date))
                    row = cur.fetchone()
                if row:
                    return crypto.decrypt_payload(self.dek, row[0], row[1])
            finally:
                conn.close()
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM daily_summary WHERE date = ?", (date,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_sleep_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("sleep_data", days)

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sleep_data WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_body_battery_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("body_battery", days)

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM body_battery WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_stress_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("stress_data", days)

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM stress_data WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_hrv_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("hrv_data", days)

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM hrv_data WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def deduplicate_activities(activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not activities:
            return []

        # Pre-normalize numeric fields and group by date (duplicates only exist within the same date)
        normalized_list = []
        for act in activities:
            act_date = str(act.get("date") or act.get("start_time") or "")[:10]
            act_dist = float(act.get("distance_km") or 0.0)
            act_dur = float(act.get("duration_min") or 0.0)
            act_hr = float(act.get("avg_hr") or 0.0)
            act_src = str(act.get("source") or "Garmin").strip()
            normalized_list.append({
                "raw": dict(act),
                "date": act_date,
                "dist": act_dist,
                "dur": act_dur,
                "hr": act_hr,
                "src": act_src
            })

        unique_activities: List[Dict[str, Any]] = []
        unique_by_date: Dict[str, List[Dict[str, Any]]] = {}

        for norm in normalized_list:
            act_date = norm["date"]
            act_dist = norm["dist"]
            act_dur = norm["dur"]
            act_hr = norm["hr"]
            act_src = norm["src"]
            act_raw = norm["raw"]

            existing_candidates = unique_by_date.get(act_date, [])
            is_dup = False

            for existing_norm in existing_candidates:
                ex_dist = existing_norm["dist"]
                ex_dur = existing_norm["dur"]
                ex_hr = existing_norm["hr"]
                existing = existing_norm["raw"]

                dist_diff = abs(act_dist - ex_dist)
                dur_diff = abs(act_dur - ex_dur)
                hr_diff = abs(act_hr - ex_hr) if (act_hr > 0 and ex_hr > 0) else 999.0

                is_dist_match = (dist_diff <= max(0.15, ex_dist * 0.05)) if (act_dist > 0 or ex_dist > 0) else True
                is_hr_match = (hr_diff <= 4.0)
                is_dur_match = (dur_diff <= max(10.0, ex_dur * 0.25))

                if is_dist_match and (is_hr_match or is_dur_match or dist_diff <= 0.1):
                    is_dup = True
                    ex_src = str(existing.get("source") or "Garmin").strip()
                    if act_src.lower() not in ex_src.lower():
                        existing["source"] = f"{ex_src} / {act_src}"

                    if ex_dur > 300 and 0 < act_dur < 300:
                        existing["duration_min"] = act_dur
                        existing_norm["dur"] = act_dur
                    if (existing.get("calories") or 0) == 0 and (act_raw.get("calories") or 0) > 0:
                        existing["calories"] = act_raw.get("calories")
                    break

            if not is_dup:
                unique_activities.append(act_raw)
                if act_date not in unique_by_date:
                    unique_by_date[act_date] = []
                unique_by_date[act_date].append({
                    "raw": act_raw,
                    "dist": act_dist,
                    "dur": act_dur,
                    "hr": act_hr
                })

        return unique_activities

    def get_activities_history(self, days: int = 365, deduplicate: bool = True) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            conn = self.get_mariadb_conn()
            rows = []
            try:
                with conn.cursor() as cur:
                    if days <= 0 or days >= 3650:
                        sql = "SELECT encrypted_payload, nonce FROM activities WHERE user_id = %s ORDER BY date DESC"
                        cur.execute(sql, (self.user_id,))
                    else:
                        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                        sql = "SELECT encrypted_payload, nonce FROM activities WHERE user_id = %s AND date >= %s ORDER BY date DESC"
                        cur.execute(sql, (self.user_id, start_date))
                    fetched = cur.fetchall()
                for ciphertext, nonce in fetched:
                    try:
                        rows.append(crypto.decrypt_payload(self.dek, ciphertext, nonce))
                    except Exception:
                        pass
            finally:
                conn.close()
            if deduplicate:
                return self.deduplicate_activities(rows)
            return rows

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if days <= 0 or days >= 3650:
                cursor.execute("SELECT * FROM activities ORDER BY date DESC")
            else:
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                cursor.execute("SELECT * FROM activities WHERE date >= ? ORDER BY date DESC", (start_date,))
            rows = [dict(row) for row in cursor.fetchall()]
            if deduplicate:
                return self.deduplicate_activities(rows)
            return rows

    def get_max_recorded_hr(self, source: Optional[str] = None) -> int:
        """Find highest plausible max heart rate recorded across activities in database, optionally filtered by source."""
        if not hasattr(self, "_max_hr_cache"):
            self._max_hr_cache = {}

        cache_key = source.lower().strip() if source else "__all__"
        if cache_key in self._max_hr_cache:
            return self._max_hr_cache[cache_key]

        acts = self.get_activities_history(days=0, deduplicate=False)
        max_hrs = []
        for a in acts:
            if source:
                act_src = str(a.get("source") or "").strip().lower()
                if source.lower().strip() not in act_src:
                    continue
            val = a.get("max_hr") or a.get("maxHR") or a.get("max_heartrate")
            if val is not None:
                try:
                    num = int(float(val))
                    if 100 <= num <= 225:
                        max_hrs.append(num)
                except (ValueError, TypeError):
                    pass
        res = max(max_hrs) if max_hrs else 0
        self._max_hr_cache[cache_key] = res
        return res


    def get_latest_body_composition(self) -> Optional[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            conn = self.get_mariadb_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT encrypted_payload, nonce FROM body_composition WHERE user_id = %s ORDER BY date DESC LIMIT 1", (self.user_id,))
                    row = cur.fetchone()
                if row:
                    return crypto.decrypt_payload(self.dek, row[0], row[1])
            finally:
                conn.close()
            return None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM body_composition ORDER BY date DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_body_composition_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("body_composition", days)

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM body_composition WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_calorie_burn_history(self, days: int = 30) -> List[Dict]:
        if self.is_mariadb and self.user_id and self.dek:
            return self._mariadb_get_history("calorie_burn", days)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if days <= 0 or days >= 3650:
                cursor.execute("SELECT * FROM calorie_burn ORDER BY date ASC")
            else:
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                cursor.execute("SELECT * FROM calorie_burn WHERE date >= ? ORDER BY date ASC", (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_metadata(self, key: str, default: Optional[str] = None) -> Optional[str]:
        if self.is_mariadb and self.user_id:
            conn = self.get_mariadb_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT `value` FROM sync_metadata WHERE user_id = %s AND `key` = %s", (self.user_id, key))
                    row = cur.fetchone()
                    return row[0] if row else default
            finally:
                conn.close()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM sync_metadata WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

    def set_metadata(self, key: str, value: str):
        if self.is_mariadb and self.user_id:
            conn = self.get_mariadb_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO sync_metadata (user_id, `key`, `value`) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)", (self.user_id, key, value))
            finally:
                conn.close()
            return

        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO sync_metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            conn.commit()
