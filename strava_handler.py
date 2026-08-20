"""
Strava Integration Handler for HealthChat Desktop.
Supports Strava Web API authentication (OAuth 2.0 / Token Refresh),
background activity sync, and offline Strava export archive file import (CSV/ZIP/JSON).
"""

import os
import sys
import json
import csv
import zipfile
import logging
import urllib.parse
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any

import requests
from garmin_db import GarminDatabase

logger = logging.getLogger("strava_handler")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

class StravaHandler:
    """Manages Strava API authentication, activity fetching, and export file parsing."""

    def __init__(self, db: GarminDatabase, token_store_dir: Optional[Path] = None):
        self.db = db
        if token_store_dir is None:
            token_store_dir = Path.home() / ".healthchat"
        self.token_store_dir = Path(token_store_dir)
        self.token_store_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.token_store_dir / "strava_tokens.json"
        
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: Optional[int] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self._authenticated = False
        self.last_error: Optional[str] = None
        
        self.load_stored_tokens()

    def load_stored_tokens(self) -> bool:
        """Load stored OAuth tokens from disk if available."""
        if self.token_file.exists():
            try:
                with open(self.token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                    self.expires_at = data.get("expires_at")
                    self.client_id = data.get("client_id")
                    self.client_secret = data.get("client_secret")
                    if self.access_token or self.refresh_token:
                        self._authenticated = True
                        logger.info("Strava tokens loaded successfully from disk.")
                        return True
            except Exception as e:
                logger.error(f"Error loading stored Strava tokens: {e}")
                self.last_error = str(e)
        return False

    def save_tokens(self, tokens: Dict):
        """Save OAuth tokens to disk."""
        try:
            tokens["client_id"] = self.client_id or tokens.get("client_id")
            tokens["client_secret"] = self.client_secret or tokens.get("client_secret")
            with open(self.token_file, "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)
            self.access_token = tokens.get("access_token")
            self.refresh_token = tokens.get("refresh_token")
            self.expires_at = tokens.get("expires_at")
            self._authenticated = True
            logger.info("Saved Strava tokens to disk.")
        except Exception as e:
            logger.error(f"Failed to save Strava tokens: {e}")
            self.last_error = str(e)

    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_auth_url(self, client_id: str, redirect_uri: str = "http://localhost:8081/") -> str:
        """Generate Strava OAuth 2.0 authorization URL."""
        self.client_id = client_id
        scope = "read,activity:read_all"
        params = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "approval_prompt": "auto",
            "scope": scope
        }
        return f"{STRAVA_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def exchange_code_for_token(self, code: str, client_id: str, client_secret: str, redirect_uri: str = "http://localhost:8081/") -> Dict:
        """Exchange authorization code for OAuth access and refresh tokens."""
        clean_cid = str(client_id).strip().strip('"').strip("'")
        clean_secret = str(client_secret).strip().strip('"').strip("'")
        clean_code = str(code).strip().strip('"').strip("'")

        self.client_id = clean_cid
        self.client_secret = clean_secret
        
        data = {
            "client_id": clean_cid,
            "client_secret": clean_secret,
            "code": clean_code,
            "grant_type": "authorization_code"
        }
        
        res = requests.post(STRAVA_TOKEN_URL, data=data)
        if res.status_code == 200:
            tokens = res.json()
            self.save_tokens(tokens)
            return tokens
        else:
            try:
                err_json = res.json()
                if res.status_code in (400, 401) and ("Application" in str(err_json) or "code" in str(err_json)):
                    err_msg = "Ogiltigt Client ID eller Client Secret. Vänligen kontrollera dina uppgifter på strava.com/settings/api och se till att du kopierat hela Client ID och Client Secret utan extra tecken."
                else:
                    err_msg = f"Strava-fel ({res.status_code}): {err_json.get('message', res.text)}"
            except Exception:
                err_msg = f"Strava Token Exchange Failed ({res.status_code}): {res.text}"
            self.last_error = err_msg
            raise Exception(err_msg)

    def refresh_access_token(self) -> bool:
        """Refresh the access token using refresh_token if needed."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            return False
            
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }
        try:
            res = requests.post(STRAVA_TOKEN_URL, data=data)
            if res.status_code == 200:
                tokens = res.json()
                self.save_tokens(tokens)
                logger.info("Strava access token refreshed successfully.")
                return True
            else:
                logger.error(f"Strava token refresh failed ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.error(f"Error refreshing Strava token: {e}")
            return False

    def _get_headers(self) -> Dict[str, str]:
        # Check if expired and refresh if possible
        if self.expires_at and time.time() > self.expires_at - 300:
            self.refresh_access_token()
            
        if not self.access_token:
            raise Exception("Strava not authenticated")
        return {"Authorization": f"Bearer {self.access_token}"}

    def fetch_activities(self, days: int = 30) -> List[Dict[str, Any]]:
        """Fetch activities from Strava API for the past `days`."""
        if not self._authenticated:
            raise Exception("Strava not authenticated")
            
        headers = self._get_headers()
        after_ts = int((datetime.now() - timedelta(days=days)).timestamp())
        
        all_activities = []
        page = 1
        per_page = 200
        
        while True:
            url = f"{STRAVA_API_BASE}/athlete/activities?after={after_ts}&page={page}&per_page={per_page}"
            res = requests.get(url, headers=headers)
            if res.status_code == 401:
                # Try refreshing token once
                if self.refresh_access_token():
                    headers = self._get_headers()
                    res = requests.get(url, headers=headers)
            
            if res.status_code != 200:
                logger.error(f"Failed to fetch Strava activities ({res.status_code}): {res.text}")
                break
                
            items = res.json()
            if not isinstance(items, list) or len(items) == 0:
                break
                
            all_activities.extend(items)
            if len(items) < per_page:
                break
            page += 1
            
        return all_activities

    def sync_strava_history(
        self, 
        days: int = 3650, 
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_complete: Optional[Callable[..., None]] = None
    ):
        """Fetch Strava activities for past days and insert into local SQLite database."""
        def _sync_worker():
            try:
                logger.info(f"Starting Strava DB sync for past {days} days...")
                if on_progress:
                    try:
                        on_progress(0, 1, "Hämtar Strava-pass...")
                    except Exception:
                        pass

                activities = self.fetch_activities(days=days)
                total = len(activities)
                
                logger.info(f"Fetched {total} Strava activities.")
                
                for idx, act in enumerate(activities):
                    if on_progress:
                        try:
                            on_progress(idx + 1, max(total, 1), f"Synkar Strava pass {idx + 1}/{total}...")
                        except Exception:
                            pass
                            
                    act_id = act.get("id")
                    act_name = act.get("name", "Strava Activity")
                    act_type = act.get("sport_type") or act.get("type", "Run")
                    start_time = act.get("start_date_local", "")
                    
                    distance_m = act.get("distance", 0) or 0
                    duration_sec = act.get("elapsed_time") or act.get("moving_time", 0) or 0
                    
                    calories = act.get("calories", 0)
                    if not calories and act.get("kilojoules"):
                        calories = int(act.get("kilojoules", 0) * 0.239006)
                    else:
                        calories = int(calories or 0)

                    avg_hr = int(act.get("average_heartrate", 0) or 0)
                    max_hr = int(act.get("max_heartrate", 0) or 0)
                    avg_speed = act.get("average_speed", 0) or 0  # m/s

                    self.db.upsert_activity({
                        "activityId": act_id,
                        "activityName": act_name,
                        "activityType": act_type,
                        "startTimeLocal": start_time,
                        "distance": distance_m,
                        "duration": duration_sec,
                        "calories": calories,
                        "averageHR": avg_hr,
                        "maxHR": max_hr,
                        "averageSpeed": avg_speed,
                        "source": "Strava",
                        "raw_json": act
                    })

                logger.info(f"Strava DB sync completed successfully ({total} activities)!")
                if on_complete:
                    try:
                        import inspect
                        sig = inspect.signature(on_complete)
                        if len(sig.parameters) >= 2:
                            on_complete(total, None)
                        elif len(sig.parameters) == 1:
                            on_complete(total)
                        else:
                            on_complete()
                    except Exception as cb_err:
                        logger.error(f"Error in Strava on_complete callback: {cb_err}")
            except Exception as sync_err:
                logger.error(f"Error during Strava DB sync: {sync_err}")
                self.last_error = str(sync_err)
                if on_complete:
                    try:
                        import inspect
                        sig = inspect.signature(on_complete)
                        if len(sig.parameters) >= 2:
                            on_complete(0, str(sync_err))
                        elif len(sig.parameters) == 1:
                            on_complete(0)
                        else:
                            on_complete()
                    except Exception:
                        pass

        import threading
        t = threading.Thread(target=_sync_worker, daemon=True)
        t.start()

    def import_strava_export_file(self, filepath: str) -> Dict[str, int]:
        """Import data from a Strava export file (CSV, ZIP archive, GPX, FIT, or JSON)."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        imported_records = {"activities": 0}
        
        # Handle ZIP archive containing activities.csv or GPX/FIT files
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path, 'r') as zip_ref:
                csv_files = [f for f in zip_ref.namelist() if f.endswith("activities.csv")]
                if csv_files:
                    with zip_ref.open(csv_files[0]) as csv_file:
                        content = csv_file.read().decode('utf-8-sig', errors='replace')
                        count = self._parse_strava_csv(content)
                        imported_records["activities"] += count
                else:
                    logger.warning("No activities.csv found inside Strava ZIP export.")

        # Handle direct CSV file
        elif path.suffix.lower() == ".csv":
            with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
                content = f.read()
                count = self._parse_strava_csv(content)
                imported_records["activities"] += count

        # Handle JSON archive
        elif path.suffix.lower() == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if "id" in item or "name" in item or "start_date" in item:
                        act_id = item.get("id", hash(item.get("start_date", str(time.time()))))
                        act_name = item.get("name", "Strava Pass")
                        act_type = item.get("sport_type") or item.get("type", "Run")
                        start_time = item.get("start_date_local", item.get("start_date", ""))
                        dist_m = item.get("distance", 0) or 0
                        dur_sec = item.get("elapsed_time") or item.get("moving_time", 0) or 0
                        cal = item.get("calories", 0) or 0
                        
                        self.db.upsert_activity({
                            "activityId": act_id,
                            "activityName": act_name,
                            "activityType": act_type,
                            "startTimeLocal": start_time,
                            "distance": dist_m,
                            "duration": dur_sec,
                            "calories": cal,
                            "averageHR": item.get("average_heartrate", 0) or 0,
                            "maxHR": item.get("max_heartrate", 0) or 0,
                            "averageSpeed": item.get("average_speed", 0) or 0,
                            "source": "Strava",
                            "raw_json": item
                        })
                        imported_records["activities"] += 1

        return imported_records

    def _parse_strava_csv(self, csv_content: str) -> int:
        """Parse Strava activities.csv content and insert records into database."""
        lines = csv_content.splitlines()
        if not lines:
            return 0

        reader = csv.DictReader(lines)
        count = 0
        for row in reader:
            if not row:
                continue

            norm_row = {str(k).strip().lower(): (str(v).strip() if v is not None else "") for k, v in row.items() if k}
            
            def get_val(*possible_keys):
                for pk in possible_keys:
                    pk_clean = pk.strip().lower()
                    if pk_clean in norm_row and norm_row[pk_clean]:
                        return norm_row[pk_clean]
                return None

            act_id = get_val("activity id", "aktivitets-id", "id för aktivitet", "id")
            act_date = get_val("activity date", "aktivitetsdatum", "datum för aktivitet", "date", "datum", "start_date")
            act_name = get_val("activity name", "aktivitetsnamn", "namn på aktivitet", "title", "namn", "name") or "Strava Pass"
            act_type = get_val("activity type", "aktivitetstyp", "typ av aktivitet", "type", "typ", "sport_type") or "Run"
            
            if not act_date and not act_id:
                continue
                
            if not act_id:
                act_id = abs(hash(f"{act_date}_{act_name}_{count}"))

            dist_str = (get_val("distance", "sträcka", "distans") or "0").replace(",", ".").replace(" ", "")
            try:
                dist_val = float(dist_str)
            except ValueError:
                dist_val = 0.0

            if dist_val > 100:
                dist_m = dist_val
            else:
                dist_m = dist_val * 1000.0

            dur_str = get_val("elapsed time", "moving time", "förfluten tid", "rörlig tid", "tid") or "0"
            dur_sec = self._parse_duration_seconds(dur_str)

            cal_str = (get_val("calories", "kalorier", "energi") or "0").replace(",", ".").replace(" ", "")
            try:
                calories = int(float(cal_str))
            except ValueError:
                calories = 0

            avg_hr_str = (get_val("average heart rate", "average hr", "medelpuls", "genomsnittlig puls") or "0").replace(",", ".").replace(" ", "")
            max_hr_str = (get_val("max heart rate", "max hr", "maxpuls", "maximal puls") or "0").replace(",", ".").replace(" ", "")
            try:
                avg_hr = int(float(avg_hr_str))
            except ValueError:
                avg_hr = 0
            try:
                max_hr = int(float(max_hr_str))
            except ValueError:
                max_hr = 0

            formatted_date = self._format_strava_date(act_date)

            self.db.upsert_activity({
                "activityId": act_id,
                "activityName": act_name,
                "activityType": act_type,
                "startTimeLocal": formatted_date,
                "distance": dist_m,
                "duration": dur_sec,
                "calories": calories,
                "averageHR": avg_hr,
                "maxHR": max_hr,
                "source": "Strava",
                "raw_json": dict(row)
            })
            count += 1
            
        return count

    @staticmethod
    def _parse_duration_seconds(dur_str: str) -> float:
        dur_str = str(dur_str).strip()
        if not dur_str:
            return 0.0
        if ":" in dur_str:
            parts = dur_str.split(":")
            try:
                if len(parts) == 3:
                    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                elif len(parts) == 2:
                    return float(parts[0]) * 60 + float(parts[1])
            except ValueError:
                return 0.0
        try:
            return float(dur_str.replace(",", "."))
        except ValueError:
            return 0.0

    @staticmethod
    def _format_strava_date(date_str: Optional[str]) -> str:
        if not date_str:
            return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        date_str = str(date_str).strip()

        # If already ISO YYYY-MM-DD...
        if len(date_str) >= 10 and date_str[:4].isdigit() and date_str[4] in ('-', '/') and date_str[7] in ('-', '/'):
            clean_iso = date_str[:10].replace('/', '-')
            rest = date_str[10:].replace('Z', '').strip()
            return f"{clean_iso}T{rest}" if rest else f"{clean_iso}T00:00:00"

        # Swedish month replacements
        swe_months = {
            "jan.": "Jan", "feb.": "Feb", "mar.": "Mar", "apr.": "Apr",
            "maj": "May", "jun.": "Jun", "jul.": "Jul", "aug.": "Aug",
            "sep.": "Sep", "okt.": "Oct", "nov.": "Nov", "dec.": "Dec",
            "okt": "Oct", "maj.": "May", "jan": "Jan", "feb": "Feb",
            "mar": "Mar", "apr": "Apr", "jun": "Jun", "jul": "Jul",
            "aug": "Aug", "sep": "Sep", "nov": "Nov", "dec": "Dec"
        }
        import re
        for swe, eng in swe_months.items():
            if re.search(re.escape(swe), date_str, re.IGNORECASE):
                date_str = re.sub(re.escape(swe), eng, date_str, flags=re.IGNORECASE)
                break

        for fmt in (
            "%b %d, %Y, %I:%M:%S %p",
            "%b %d, %Y, %H:%M:%S",
            "%b %d, %Y",
            "%d %b %Y, %H:%M:%S",
            "%d %b %Y %H:%M:%S",
            "%d %b %Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
            "%m/%d/%Y %H:%M:%S",
            "%d.%m.%Y %H:%M:%S",
            "%d.%m.%Y",
        ):
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                pass
        return date_str
