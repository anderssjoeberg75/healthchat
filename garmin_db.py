"""
Garmin Database Handler for HealthChat Desktop.
Provides local SQLite storage for daily summaries, sleep, body battery,
stress, HRV, and workout activities.
"""

import sqlite3
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger("garmin_db")

class GarminDatabase:
    """SQLite Database Manager for Garmin health and activity data."""
    
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            config_dir = Path.home() / '.healthchat'
            config_dir.mkdir(parents=True, exist_ok=True)
            db_path = config_dir / 'healthdata.db'
            
        self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Get a connection to the SQLite database with WAL enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def init_db(self):
        """Create database tables if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Daily Summary Table
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

            # Sleep Data Table
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

            # Body Battery Table
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

            # Stress Data Table
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

            # HRV Data Table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS hrv_data (
                date TEXT PRIMARY KEY,
                last_night_avg REAL DEFAULT 0,
                weekly_avg REAL DEFAULT 0,
                status TEXT DEFAULT ''
            )
            """)

            # Activities Table
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
            try:
                cursor.execute("ALTER TABLE activities ADD COLUMN source TEXT DEFAULT 'Garmin'")
            except sqlite3.OperationalError:
                pass

            # Body Composition Table (Withings / Garmin)
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

            # Create Indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(activity_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_body_comp_date ON body_composition(date)")
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    # --- UPSERT METHODS ---

    def upsert_daily_summary(self, date: str, steps: int = 0, calories: int = 0, active_calories: int = 0, resting_hr: int = 0, raw_data: Optional[Dict] = None):
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

    @staticmethod
    def _normalize_date(date_input: Optional[str]) -> str:
        if not date_input:
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
        return datetime.now().strftime('%Y-%m-%d')

    def upsert_activity(self, activity: Dict):
        act_id = activity.get('activityId')
        if act_id is None or act_id == '':
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

    # --- QUERY METHODS FOR CHARTS & LLM CONTEXT ---

    def get_daily_summary_history(self, days: int = 30) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM daily_summary WHERE date >= ? ORDER BY date ASC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_sleep_history(self, days: int = 30) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM sleep_data WHERE date >= ? ORDER BY date ASC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_body_battery_history(self, days: int = 30) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM body_battery WHERE date >= ? ORDER BY date ASC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_stress_history(self, days: int = 30) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM stress_data WHERE date >= ? ORDER BY date ASC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    def get_hrv_history(self, days: int = 30) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM hrv_data WHERE date >= ? ORDER BY date ASC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def deduplicate_activities(activities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge duplicate activities recorded on the same date with matching distance/duration 
        across different platforms (e.g. Garmin and Strava).
        """
        if not activities:
            return []

        unique_activities: List[Dict[str, Any]] = []

        for act in activities:
            act_date = str(act.get("date") or act.get("start_time") or "")[:10]
            act_dist = float(act.get("distance_km") or 0.0)
            act_dur = float(act.get("duration_min") or 0.0)
            act_src = str(act.get("source") or "Garmin").strip()

            is_dup = False
            for existing in unique_activities:
                ex_date = str(existing.get("date") or existing.get("start_time") or "")[:10]
                ex_dist = float(existing.get("distance_km") or 0.0)
                ex_dur = float(existing.get("duration_min") or 0.0)

                if act_date and act_date == ex_date:
                    dist_diff = abs(act_dist - ex_dist)
                    dur_diff = abs(act_dur - ex_dur)
                    if (dist_diff < 0.3 and dur_diff < 3.0) or (act_dist == 0 and ex_dist == 0 and dur_diff < 3.0):
                        is_dup = True
                        ex_src = str(existing.get("source") or "Garmin").strip()
                        if act_src.lower() not in ex_src.lower():
                            existing["source"] = f"{ex_src} / {act_src}"
                        break

            if not is_dup:
                unique_activities.append(dict(act))

        return unique_activities

    def get_activities_history(self, days: int = 365, deduplicate: bool = True) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if days <= 0 or days >= 3650:
                cursor.execute("SELECT * FROM activities ORDER BY date DESC")
            else:
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                cursor.execute("""
                SELECT * FROM activities WHERE date >= ? ORDER BY date DESC
                """, (start_date,))
            rows = [dict(row) for row in cursor.fetchall()]
            if deduplicate:
                return self.deduplicate_activities(rows)
            return rows

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

    def get_latest_body_composition(self) -> Optional[Dict]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM body_composition ORDER BY date DESC LIMIT 1
            """)
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_body_composition_history(self, days: int = 30) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT * FROM body_composition WHERE date >= ? ORDER BY date ASC
            """, (start_date,))
            return [dict(row) for row in cursor.fetchall()]
