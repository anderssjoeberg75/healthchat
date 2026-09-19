"""
Whoop Integration Handler for HealthChat.
Supports Whoop Developer API v2 authentication (OAuth 2.0), background metric sync,
and profile retrieval (Recovery, Sleep, Cycles, Workouts, Body Measurements).
"""

import os
import sys
import time
import json
import logging
import secrets
import urllib.parse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List, Callable, Any

import requests
from garmin_db import GarminDatabase

logger = logging.getLogger("whoop_handler")

WHOOP_AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"
WHOOP_SCOPES = "read:recovery read:cycles read:workout read:sleep read:profile read:body_measurement offline"


def _uuid_to_int_id(uuid_str: str) -> int:
    """Convert UUID string or arbitrary ID into a positive 62-bit integer for MariaDB BIGINT."""
    if not uuid_str:
        return 0
    try:
        import uuid
        u = uuid.UUID(str(uuid_str))
        return int(u.int & 0x7FFFFFFFFFFFFFFF)
    except Exception:
        # Fallback to deterministic hash
        import hashlib
        h = hashlib.sha256(str(uuid_str).encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF


def _parse_iso_date(dt_str: Optional[str]) -> str:
    """Extract YYYY-MM-DD from an ISO 8601 string or fallback to today."""
    if not dt_str:
        return datetime.now().strftime("%Y-%m-%d")
    try:
        clean = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return str(dt_str)[:10]


class WhoopHandler:
    """Manages Whoop OAuth 2.0 authentication and sync with Whoop API v2."""

    def __init__(self, db: GarminDatabase, token_store_dir: Optional[Path] = None):
        self.db = db
        if token_store_dir is None:
            token_store_dir = Path.home() / ".healthchat"
        self.token_store_dir = Path(token_store_dir)
        self.token_store_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.token_store_dir / "whoop_tokens.json"

        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.expires_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self._authenticated = False
        self.current_state: Optional[str] = None

        self.load_stored_tokens()

    def load_stored_tokens(self) -> bool:
        """Load stored OAuth tokens from secret_store or fallback disk."""
        is_default_dir = (self.token_store_dir.resolve() == (Path.home() / ".healthchat").resolve())
        if is_default_dir:
            try:
                import secret_store
                at = secret_store.get_secret("whoop_access_token")
                rt = secret_store.get_secret("whoop_refresh_token")
                cs = secret_store.get_secret("whoop_client_secret")
                if at and rt:
                    self.access_token = at
                    self.refresh_token = rt
                    if cs:
                        self.client_secret = cs
                    self._authenticated = True
                    return True
            except Exception as ss_err:
                logger.debug(f"Could not load Whoop tokens from secret_store: {ss_err}")

        if self.token_file.exists():
            try:
                with open(self.token_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.access_token = data.get("access_token")
                    self.refresh_token = data.get("refresh_token")
                    self.expires_at = data.get("expires_at")
                    self.client_id = data.get("client_id")
                    self.client_secret = data.get("client_secret")
                    if self.access_token and self.refresh_token:
                        self._authenticated = True
                        logger.info("Whoop tokens loaded successfully from disk.")
                        if is_default_dir:
                            try:
                                import secret_store
                                secret_store.set_secret("whoop_access_token", self.access_token)
                                secret_store.set_secret("whoop_refresh_token", self.refresh_token)
                                if self.client_secret:
                                    secret_store.set_secret("whoop_client_secret", self.client_secret)
                            except Exception:
                                pass
                        return True
            except Exception as e:
                logger.error(f"Error loading stored Whoop tokens: {e}")
                self.last_error = str(e)
        return False

    def save_tokens(self, tokens: Dict[str, Any]) -> None:
        """Save OAuth tokens to secret_store and restricted disk file."""
        try:
            self.client_id = self.client_id or tokens.get("client_id")
            self.client_secret = self.client_secret or tokens.get("client_secret")
            self.access_token = tokens.get("access_token")
            self.refresh_token = tokens.get("refresh_token")
            if "expires_in" in tokens and "expires_at" not in tokens:
                tokens["expires_at"] = time.time() + float(tokens["expires_in"])
            self.expires_at = tokens.get("expires_at")

            is_default_dir = (self.token_store_dir.resolve() == (Path.home() / ".healthchat").resolve())
            if is_default_dir:
                try:
                    import secret_store
                    if self.access_token:
                        secret_store.set_secret("whoop_access_token", self.access_token)
                    if self.refresh_token:
                        secret_store.set_secret("whoop_refresh_token", self.refresh_token)
                    if self.client_secret:
                        secret_store.set_secret("whoop_client_secret", self.client_secret)
                except Exception as ss_err:
                    logger.debug(f"Could not save Whoop tokens to secret_store: {ss_err}")

            tokens["client_id"] = self.client_id
            tokens["client_secret"] = self.client_secret
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(self.token_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(tokens, f, indent=2)

            self._authenticated = True
            logger.info("Saved Whoop tokens.")
        except Exception as e:
            logger.error(f"Failed to save Whoop tokens: {e}")

    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_auth_url(self, client_id: str, redirect_uri: str, state: Optional[str] = None) -> str:
        """Generate Whoop OAuth 2.0 authorization URL."""
        self.client_id = client_id
        self.current_state = state or secrets.token_urlsafe(32)

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": WHOOP_SCOPES,
            "state": self.current_state,
        }
        return f"{WHOOP_AUTH_URL}?{urllib.parse.urlencode(params)}"

    def verify_state(self, received_state: str) -> bool:
        """Verify CSRF state token against current session state."""
        if not self.current_state or not received_state:
            return False
        return secrets.compare_digest(received_state.strip(), self.current_state.strip())

    def exchange_code_for_token(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> Dict[str, Any]:
        """Exchange authorization code for OAuth access & refresh tokens."""
        self.client_id = client_id
        self.client_secret = client_secret

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }

        try:
            res = requests.post(WHOOP_TOKEN_URL, headers=headers, data=data, timeout=(5, 30))
            if res.status_code == 200:
                tokens = res.json()
                self.save_tokens(tokens)
                return tokens
            else:
                err_msg = f"Whoop Token Exchange Failed ({res.status_code}): {res.text}"
                self.last_error = err_msg
                raise Exception(err_msg)
        except requests.exceptions.Timeout:
            err_msg = "Whoop token exchange timed out after 30 seconds"
            self.last_error = err_msg
            raise Exception(err_msg)
        except requests.exceptions.RequestException as req_err:
            err_msg = f"Whoop network error during token exchange: {req_err}"
            self.last_error = err_msg
            raise Exception(err_msg)

    def refresh_access_token(self) -> bool:
        """Refresh the access token using refresh_token if needed."""
        if not self.refresh_token or not self.client_id or not self.client_secret:
            logger.warning("Whoop: Missing credentials or refresh token for token refresh")
            return False

        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "scope": "offline",
        }
        try:
            res = requests.post(WHOOP_TOKEN_URL, headers=headers, data=data, timeout=(5, 30))
            if res.status_code == 200:
                tokens = res.json()
                self.save_tokens(tokens)
                logger.info("Whoop: Successfully refreshed access token")
                return True
            else:
                logger.warning(f"Whoop: Failed to refresh token ({res.status_code}): {res.text}")
                return False
        except Exception as e:
            logger.error(f"Whoop: Exception during token refresh: {e}")
            return False

    def _get_headers(self) -> Dict[str, str]:
        if self.expires_at and time.time() > self.expires_at - 300:
            success = self.refresh_access_token()
            if not success:
                raise RuntimeError("Whoop-anslutningen har gått ut – koppla om i inställningarna")

        if not self.access_token:
            raise RuntimeError("Whoop inte autentiserad – koppla om i inställningarna")
        return {"Authorization": f"Bearer {self.access_token}"}

    def _api_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Helper to make authenticated GET requests to Whoop v2 API."""
        url = f"{WHOOP_API_BASE}{endpoint}" if endpoint.startswith("/") else f"{WHOOP_API_BASE}/{endpoint}"
        headers = self._get_headers()
        res = requests.get(url, headers=headers, params=params, timeout=(5, 30))
        if res.status_code == 401:
            if self.refresh_access_token():
                headers = self._get_headers()
                res = requests.get(url, headers=headers, params=params, timeout=(5, 30))
        if res.status_code == 200:
            return res.json()
        logger.warning(f"Whoop API GET {endpoint} returned {res.status_code}: {res.text}")
        return None

    def fetch_user_profile(self) -> Dict[str, Any]:
        """Fetch Whoop profile and body measurements."""
        res: Dict[str, Any] = {}
        if not self.is_authenticated():
            return res
        try:
            # 1. Basic profile
            prof = self._api_get("/user/profile/basic")
            if prof:
                if prof.get("first_name") or prof.get("last_name"):
                    res["name"] = f"{prof.get('first_name', '')} {prof.get('last_name', '')}".strip()
                if prof.get("email"):
                    res["email"] = prof.get("email")

            # 2. Body measurement
            body = self._api_get("/user/measurement/body")
            if body:
                if body.get("height_meter"):
                    res["height_cm"] = round(float(body["height_meter"]) * 100.0, 1)
                if body.get("weight_kilogram"):
                    res["weight_kg"] = round(float(body["weight_kilogram"]), 1)
                if body.get("max_heart_rate"):
                    res["max_hr"] = int(body["max_heart_rate"])
        except Exception as e:
            logger.warning(f"Error fetching Whoop profile: {e}")
        return res

    def sync_whoop_history(
        self,
        days: int = 30,
        force_full: bool = False,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_complete: Optional[Callable[[int, Optional[str]], None]] = None,
    ) -> None:
        """Fetch Whoop metrics for past days and insert into database."""
        def _sync_worker():
            total_items = 0
            err_msg: Optional[str] = None
            try:
                sync_days = days
                if not force_full and hasattr(self, "db") and self.db:
                    last_sync = self.db.get_metadata("last_whoop_sync")
                    if last_sync:
                        try:
                            last_date = datetime.strptime(last_sync, "%Y-%m-%d").date()
                            diff_days = (datetime.now().date() - last_date).days + 2
                            if diff_days > 0:
                                sync_days = min(days, diff_days)
                        except Exception as e:
                            logger.debug(f"Error parsing last Whoop sync date '{last_sync}': {e}")

                logger.info(f"Starting Whoop sync for past {sync_days} days...")
                start_dt = datetime.now(timezone.utc) - timedelta(days=sync_days)
                start_iso = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")

                def _report(step: int, text: str):
                    if on_progress:
                        try:
                            on_progress(step, 5, text)
                        except Exception:
                            pass

                # Step 1: Body measurements
                _report(1, "Hämtar Whoop kroppsmått & profil...")
                try:
                    body = self._api_get("/user/measurement/body")
                    if body and hasattr(self, "db") and self.db:
                        w_kg = float(body.get("weight_kilogram") or 0.0)
                        h_m = float(body.get("height_meter") or 0.0)
                        bmi = round(w_kg / (h_m ** 2), 1) if (w_kg > 0 and h_m > 0) else 0.0
                        if w_kg > 0:
                            today_str = datetime.now().strftime("%Y-%m-%d")
                            self.db.upsert_body_composition(
                                today_str,
                                weight_kg=w_kg,
                                bmi=bmi,
                                source="Whoop",
                                raw_data=body,
                            )
                            total_items += 1
                except Exception as e:
                    logger.warning(f"Could not sync Whoop body measurements: {e}")

                # Step 2: Sleep
                _report(2, "Hämtar Whoop sömn...")
                next_token: Optional[str] = None
                while True:
                    params: Dict[str, Any] = {"start": start_iso, "limit": 25}
                    if next_token:
                        params["nextToken"] = next_token
                    data = self._api_get("/activity/sleep", params=params)
                    if not data or not data.get("records"):
                        break
                    for rec in data.get("records", []):
                        score_obj = rec.get("score") or {}
                        stages = score_obj.get("stage_summary") or {}
                        
                        rem_ms = stages.get("rem_sleep_duration_milli") or 0
                        deep_ms = stages.get("slow_wave_sleep_duration_milli") or 0
                        light_ms = stages.get("light_sleep_duration_milli") or 0
                        in_bed_ms = stages.get("total_in_bed_time_milli") or 0
                        asleep_ms = rem_ms + deep_ms + light_ms
                        awake_ms = max(0, in_bed_ms - asleep_ms)

                        perf = score_obj.get("sleep_performance_percentage") or 0
                        date_str = _parse_iso_date(rec.get("end") or rec.get("start"))

                        if hasattr(self, "db") and self.db:
                            self.db.upsert_sleep(
                                date=date_str,
                                total_hours=round(asleep_ms / 3600000.0, 2),
                                deep_hours=round(deep_ms / 3600000.0, 2),
                                light_hours=round(light_ms / 3600000.0, 2),
                                rem_hours=round(rem_ms / 3600000.0, 2),
                                awake_hours=round(awake_ms / 3600000.0, 2),
                                score=int(perf),
                                raw_data=rec,
                            )
                            total_items += 1

                    next_token = data.get("next_token")
                    if not next_token:
                        break

                # Step 3: Recovery & HRV
                _report(3, "Hämtar Whoop återhämtning & HRV...")
                next_token = None
                while True:
                    params = {"start": start_iso, "limit": 25}
                    if next_token:
                        params["nextToken"] = next_token
                    data = self._api_get("/recovery", params=params)
                    if not data or not data.get("records"):
                        break
                    for rec in data.get("records", []):
                        score_obj = rec.get("score") or {}
                        rec_score = int(score_obj.get("recovery_score") or 0)
                        hrv_val = float(score_obj.get("hrv_rmssd_milli") or 0.0)
                        rhr_val = int(score_obj.get("resting_heart_rate") or 0)
                        date_str = _parse_iso_date(rec.get("created_at"))

                        if hasattr(self, "db") and self.db:
                            if hrv_val > 0:
                                self.db.upsert_hrv(date=date_str, last_night_avg=hrv_val, weekly_avg=0, status="Whoop Recovery")
                            if rec_score > 0:
                                self.db.upsert_body_battery(
                                    date=date_str,
                                    charged=rec_score,
                                    drained=0,
                                    highest=rec_score,
                                    lowest=0,
                                    current=rec_score,
                                )
                            if rhr_val > 0:
                                self.db.upsert_daily_summary(date=date_str, resting_hr=rhr_val)
                            total_items += 1

                    next_token = data.get("next_token")
                    if not next_token:
                        break

                # Step 4: Cycles (Daily Strain & Energy)
                _report(4, "Hämtar Whoop dagsbelastning...")
                next_token = None
                while True:
                    params = {"start": start_iso, "limit": 25}
                    if next_token:
                        params["nextToken"] = next_token
                    data = self._api_get("/cycle", params=params)
                    if not data or not data.get("records"):
                        break
                    for rec in data.get("records", []):
                        score_obj = rec.get("score") or {}
                        kj = float(score_obj.get("kilojoule") or 0.0)
                        kcal = int(round(kj * 0.239006))
                        avg_hr = int(score_obj.get("average_heart_rate") or 0)
                        date_str = _parse_iso_date(rec.get("start"))

                        if hasattr(self, "db") and self.db:
                            self.db.upsert_daily_summary(
                                date=date_str,
                                calories=kcal,
                                resting_hr=avg_hr if avg_hr else 0,
                                raw_data=rec,
                            )
                            total_items += 1

                    next_token = data.get("next_token")
                    if not next_token:
                        break

                # Step 5: Workouts
                _report(5, "Hämtar Whoop träningspass...")
                next_token = None
                while True:
                    params = {"start": start_iso, "limit": 25}
                    if next_token:
                        params["nextToken"] = next_token
                    data = self._api_get("/activity/workout", params=params)
                    if not data or not data.get("records"):
                        break
                    for rec in data.get("records", []):
                        score_obj = rec.get("score") or {}
                        sport_name = str(rec.get("sport_name") or "Träning").replace("_", " ").title()
                        start_time = rec.get("start") or ""
                        end_time = rec.get("end") or ""
                        
                        duration_min = 0.0
                        if start_time and end_time:
                            try:
                                s_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                                e_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                                duration_min = max(0.0, (e_dt - s_dt).total_seconds() / 60.0)
                            except Exception:
                                duration_min = 0.0

                        kj = float(score_obj.get("kilojoule") or 0.0)
                        kcal = int(round(kj * 0.239006))
                        avg_hr = int(score_obj.get("average_heart_rate") or 0)
                        max_hr = int(score_obj.get("max_heart_rate") or 0)
                        dist_m = float(score_obj.get("distance_meter") or 0.0)
                        dist_km = round(dist_m / 1000.0, 2)

                        int_id = _uuid_to_int_id(rec.get("id") or start_time)

                        if hasattr(self, "db") and self.db and int_id:
                            self.db.upsert_activity({
                                "activityId": int_id,
                                "activityName": f"Whoop {sport_name}",
                                "activityType": sport_name,
                                "startTimeLocal": start_time,
                                "distance_km": dist_km,
                                "duration_min": duration_min,
                                "calories": kcal,
                                "averageHR": avg_hr,
                                "maxHR": max_hr,
                                "source": "Whoop",
                                "raw_json": json.dumps(rec),
                            })
                            total_items += 1

                    next_token = data.get("next_token")
                    if not next_token:
                        break

                if hasattr(self, "db") and self.db:
                    self.db.set_metadata("last_whoop_sync", datetime.now().strftime("%Y-%m-%d"))
                    self.db.set_metadata("last_whoop_sync_timestamp", datetime.now().isoformat())

                logger.info(f"Whoop sync completed successfully ({total_items} items)!")
            except Exception as e:
                logger.error(f"Error during Whoop sync: {e}")
                err_msg = str(e)
                self.last_error = err_msg

            if on_complete:
                try:
                    on_complete(total_items, err_msg)
                except Exception as cb_err:
                    logger.error(f"Error in Whoop on_complete callback: {cb_err}")

        import threading
        t = threading.Thread(target=_sync_worker, daemon=True)
        t.start()
