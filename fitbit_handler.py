"""
Fitbit Integration Handler for HealthChat Desktop.
Supports Fitbit Web API authentication (OAuth 2.0 / Token), background metric sync,
and offline Fitbit export archive file import (CSV/JSON).
"""

import os
import sys
import time
import json
import logging
import secrets
import base64
import hashlib
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Callable, Any


import requests
from garmin_db import GarminDatabase

logger = logging.getLogger("fitbit_handler")

FITBIT_AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"
FITBIT_API_BASE = "https://api.fitbit.com/1/user/-"

class FitbitHandler:
    """Manages Fitbit API authentication, data fetching, and export file parsing."""

    def __init__(self, db: GarminDatabase, token_store_dir: Optional[Path] = None):
        self.db = db
        if token_store_dir is None:
            token_store_dir = Path.home() / ".healthchat"
        self.token_store_dir = Path(token_store_dir)
        self.token_store_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.token_store_dir / "fitbit_tokens.json"
        
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.expires_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self._authenticated = False
        self.current_state: Optional[str] = None
        self.code_verifier: Optional[str] = None
        
        self.load_stored_tokens()

    def load_stored_tokens(self) -> bool:
        """Load stored OAuth tokens from disk if available."""
        if self.token_file.exists():
            try:
                with open(self.token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                    self.client_id = data.get("client_id")
                    self.client_secret = data.get("client_secret")
                    self.expires_at = data.get("expires_at")
                    if self.access_token or self.refresh_token:
                        self._authenticated = True
                        logger.info("Fitbit tokens loaded successfully from disk.")
                        return True
            except Exception as e:
                logger.error(f"Error loading stored Fitbit tokens: {e}")
                self.last_error = str(e)
        return False

    def save_tokens(self, tokens: Dict) -> None:
        """Save OAuth tokens to disk."""
        try:
            tokens["client_id"] = self.client_id or tokens.get("client_id")
            tokens["client_secret"] = self.client_secret or tokens.get("client_secret")
            if "expires_in" in tokens and "expires_at" not in tokens:
                tokens["expires_at"] = time.time() + float(tokens["expires_in"])
            with open(self.token_file, "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)
            self.access_token = tokens.get("access_token")
            self.refresh_token = tokens.get("refresh_token")
            self.expires_at = tokens.get("expires_at")
            self._authenticated = True
            logger.info("Saved Fitbit tokens to disk.")
        except Exception as e:
            logger.error(f"Failed to save Fitbit tokens: {e}")

    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_auth_url(self, client_id: str, redirect_uri: str = "http://127.0.0.1:8080/", state: Optional[str] = None) -> str:
        """Generate Fitbit OAuth 2.0 authorization URL with dynamic state and PKCE (S256)."""
        self.client_id = client_id
        self.current_state = state or secrets.token_urlsafe(32)
        
        # PKCE S256 generation
        self.code_verifier = secrets.token_urlsafe(64)
        hashed = hashlib.sha256(self.code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(hashed).decode("ascii").rstrip("=")

        scope = "activity heartrate location nutrition profile settings sleep weight"
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "expires_in": "31536000",
            "state": self.current_state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256"
        }
        return f"{FITBIT_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def verify_state(self, received_state: str) -> bool:
        """Verify CSRF state token against current session state."""
        if not self.current_state or not received_state:
            return False
        return secrets.compare_digest(received_state.strip(), self.current_state.strip())

    def exchange_code_for_token(self, code: str, client_id: str, client_secret: str, redirect_uri: str = "http://127.0.0.1:8080/") -> Dict:
        """Exchange authorization code for OAuth access tokens with PKCE verifier."""
        self.client_id = client_id
        self.client_secret = client_secret
        
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }
        if self.code_verifier:
            data["code_verifier"] = self.code_verifier
        
        try:
            res = requests.post(FITBIT_TOKEN_URL, headers=headers, data=data, timeout=(5, 30))
            if res.status_code == 200:
                tokens = res.json()
                self.save_tokens(tokens)
                return tokens
            else:
                err_msg = f"Fitbit Token Exchange Failed ({res.status_code}): {res.text}"
                self.last_error = err_msg
                raise Exception(err_msg)
        except requests.exceptions.Timeout:
            err_msg = "Fitbit token exchange timed out after 30 seconds"
            self.last_error = err_msg
            raise Exception(err_msg)
        except requests.exceptions.RequestException as req_err:
            err_msg = f"Fitbit network error during token exchange: {req_err}"
            self.last_error = err_msg
            raise Exception(err_msg)

    def refresh_access_token(self) -> bool:
        """Refresh the access token using refresh_token if needed."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            logger.warning("Fitbit: Missing credentials or refresh token for token refresh")
            return False

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token
        }
        try:
            res = requests.post(FITBIT_TOKEN_URL, headers=headers, data=data, timeout=(5, 30))
            if res.status_code == 200:
                tokens = res.json()
                self.save_tokens(tokens)
                logger.info("Fitbit: Successfully refreshed access token")
                return True
            else:
                logger.warning(f"Fitbit: Failed to refresh token ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.error(f"Fitbit: Exception during token refresh: {e}")
            return False

    def _get_headers(self) -> Dict[str, str]:
        # Check if expired and refresh if possible (5 min buffer)
        if self.expires_at and time.time() > self.expires_at - 300:
            self.refresh_access_token()

        if not self.access_token:
            raise Exception("Fitbit not authenticated")
        return {"Authorization": f"Bearer {self.access_token}"}

    def fetch_user_profile(self) -> Dict[str, Any]:
        """Fetch Fitbit profile data (gender, height, weight, age, resting_hr)."""
        res = {}
        if not self.is_authenticated():
            return res
        try:
            import requests
            url = "https://api.fitbit.com/1/user/-/profile.json"
            resp = requests.get(url, headers=self._get_headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("user", {})
                if data.get("gender"):
                    gen = str(data.get("gender")).lower()
                    res["sex"] = "female" if "female" in gen or gen == "f" else "male"
                if data.get("height"):
                    res["height_cm"] = float(data.get("height"))
                if data.get("weight"):
                    res["weight_kg"] = round(float(data.get("weight")), 1)
                if data.get("age"):
                    res["age"] = float(data.get("age"))
                elif data.get("dateOfBirth"):
                    try:
                        from datetime import datetime
                        byear = int(str(data.get("dateOfBirth")).split("-")[0])
                        res["age"] = float(datetime.now().year - byear)
                    except Exception:
                        pass
                if data.get("averageDailySteps"):
                    pass
                if data.get("restingHeartRate"):
                    res["resting_hr"] = float(data.get("restingHeartRate"))
        except Exception as e:
            logger.warning(f"Error fetching Fitbit profile: {e}")
        return res


    def sync_fitbit_history(
        self, 
        days: int = 30, 
        force_full: bool = False,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_complete: Optional[Callable[[], None]] = None
    ):
        """Fetch Fitbit metrics for past days and insert into local SQLite database."""
        def _sync_worker():
            try:
                sync_days = days
                if not force_full and hasattr(self, 'db') and self.db:
                    last_sync = self.db.get_metadata("last_fitbit_sync")
                    if last_sync:
                        try:
                            last_date = datetime.strptime(last_sync, "%Y-%m-%d").date()
                            diff_days = (datetime.now().date() - last_date).days + 2
                            if diff_days > 0:
                                sync_days = min(days, diff_days)
                        except Exception as e:
                            logger.debug(f"Error parsing last Fitbit sync date '{last_sync}': {e}")

                logger.info(f"Starting Fitbit DB sync for past {sync_days} days (force_full={force_full})...")
                if on_progress:
                    try:
                        on_progress(0, sync_days, "Hämtar Fitbit-data...")
                    except Exception:
                        pass

                for i in range(sync_days):
                    d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                    if on_progress:
                        try:
                            on_progress(i + 1, sync_days, f"Synkar Fitbit {d}...")
                        except Exception:
                            pass

                    # Fetch & store Sleep
                    if self._authenticated:
                        try:
                            url = f"{FITBIT_API_BASE}/sleep/date/{d}.json"
                            res = requests.get(url, headers=self._get_headers(), timeout=(5, 30))
                            if res.status_code == 401:
                                # Attempt refresh and retry once
                                if self.refresh_access_token():
                                    res = requests.get(url, headers=self._get_headers(), timeout=(5, 30))

                            if res.status_code == 200:
                                sleep_data = res.json()
                                summary = sleep_data.get("summary", {})
                                total_sec = summary.get("totalMinutesAsleep", 0) * 60
                                if total_sec > 0:
                                    stages = summary.get("stages", {})
                                    self.db.upsert_sleep(
                                        date=d,
                                        total_hours=total_sec / 3600.0,
                                        deep_hours=(stages.get("deep", 0) * 60) / 3600.0,
                                        light_hours=(stages.get("light", 0) * 60) / 3600.0,
                                        rem_hours=(stages.get("rem", 0) * 60) / 3600.0,
                                        awake_hours=(stages.get("wake", 0) * 60) / 3600.0,
                                        score=0,
                                        raw_data=sleep_data
                                    )
                        except requests.exceptions.Timeout:
                            logger.warning(f"Fitbit sleep request timed out for {d}")
                            self.last_error = f"Timeout vid hämtning av Fitbit-sömn för {d}"
                        except requests.exceptions.RequestException as req_err:
                            logger.warning(f"Fitbit network error for {d}: {req_err}")
                            self.last_error = str(req_err)
                        except Exception as e:
                            logger.debug(f"Fitbit sleep fetch failed for {d}: {e}")

                if hasattr(self, 'db') and self.db:
                    self.db.set_metadata("last_fitbit_sync", datetime.now().strftime("%Y-%m-%d"))
                    self.db.set_metadata("last_fitbit_sync_timestamp", datetime.now().isoformat())

                logger.info("Fitbit DB sync completed successfully!")
                if on_complete:
                    try:
                        on_complete()
                    except Exception as cb_err:
                        logger.error(f"Error in Fitbit on_complete callback: {cb_err}")
            except Exception as sync_err:
                logger.error(f"Error during Fitbit DB sync: {sync_err}")

        import threading
        t = threading.Thread(target=_sync_worker, daemon=True)
        t.start()

    def import_fitbit_export_file(self, filepath: str) -> Dict[str, int]:
        """Import data from a Fitbit export file (CSV or JSON archive)."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        imported_records = {"sleep": 0, "activities": 0}
        
        if path.suffix.lower() == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            if isinstance(data, list):
                for item in data:
                    # Check for sleep JSON entry
                    if "dateOfSleep" in item:
                        d = item.get("dateOfSleep")
                        total_sec = (item.get("minutesAsleep", 0) or 0) * 60
                        levels = item.get("levels", {}).get("summary", {})
                        self.db.upsert_sleep(
                            date=d,
                            total_hours=total_sec / 3600.0,
                            deep_hours=((levels.get("deep", {}).get("minutes", 0) or 0) * 60) / 3600.0,
                            light_hours=((levels.get("light", {}).get("minutes", 0) or 0) * 60) / 3600.0,
                            rem_hours=((levels.get("rem", {}).get("minutes", 0) or 0) * 60) / 3600.0,
                            awake_hours=((levels.get("wake", {}).get("minutes", 0) or 0) * 60) / 3600.0,
                            score=item.get("efficiency", 0) or 0,
                            raw_data=item
                        )
                        imported_records["sleep"] += 1
                        
                    # Check for activity JSON entry
                    elif "activityName" in item or "logId" in item:
                        d_str = item.get("startTime", item.get("date", ""))
                        if d_str:
                            d = d_str.split("T")[0]
                            dist_km = (item.get("distance", 0) or 0)
                            if item.get("distanceUnit") == "Miles":
                                dist_km *= 1.60934
                            self.db.upsert_activity({
                                "activityId": item.get("logId", hash(d_str)),
                                "activityName": item.get("activityName", "Fitbit Pass"),
                                "startTimeLocal": d_str,
                                "duration": item.get("duration", 0) / 1000.0 if item.get("duration") else 0,
                                "distance": dist_km * 1000.0,
                                "calories": item.get("calories", 0) or 0,
                                "averageHR": item.get("averageHeartRate", 0) or 0,
                                "maxHR": 0
                            })
                            imported_records["activities"] += 1

        return imported_records
