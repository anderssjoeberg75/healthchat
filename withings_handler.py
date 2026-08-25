"""
Withings API Integration Handler for HealthChat.
Fetches weight, body fat %, muscle mass, bone mass, body water %, and BMI
from Withings Health Mate API (WBS API v2) and stores them in local SQLite database.
"""

import logging
import requests
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from garmin_db import GarminDatabase

logger = logging.getLogger("withings_handler")


class WithingsDataHandler:
    """Handler for Withings Health Mate API integration."""

    MEASURE_ENDPOINT = "https://wbsapi.withings.net/v2/measure"
    OAUTH_ENDPOINT = "https://wbsapi.withings.net/v2/oauth2"

    # Withings Measurement Types
    TYPE_WEIGHT = 1        # Weight (kg)
    TYPE_FAT_RATIO = 6     # Fat ratio (%)
    TYPE_HEART_RATE = 11   # Heart pulse (bpm)
    TYPE_MUSCLE_MASS = 76  # Muscle mass (kg)
    TYPE_HYDRATION = 77    # Hydration / Water (%)
    TYPE_BONE_MASS = 88    # Bone mass (kg)

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        refresh_token: Optional[str] = None,
        access_token: Optional[str] = None,
        db: Optional[GarminDatabase] = None
    ):
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.refresh_token = refresh_token or ""
        self.access_token = access_token or ""
        self.db = db or GarminDatabase()
        self.last_error: Optional[str] = None

    @staticmethod
    def get_auth_url(client_id: str, redirect_uri: str = "http://localhost:8000") -> str:
        """Build Withings OAuth2 authorization URL with encoded redirect_uri."""
        encoded_uri = urllib.parse.quote(redirect_uri.strip(), safe='')
        return (
            "https://account.withings.com/oauth2_user/authorize2"
            f"?response_type=code&client_id={client_id.strip()}"
            "&state=withings_state"
            "&scope=user.metrics,user.info,user.activity"
            f"&redirect_uri={encoded_uri}"
        )

    def exchange_code_for_token(
        self,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://localhost:8000"
    ) -> Dict[str, Any]:
        """Exchange authorization code for refresh_token and access_token."""
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        clean_code = code.strip()
        clean_uri = redirect_uri.strip()

        payload = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": clean_code,
            "redirect_uri": clean_uri
        }

        resp = requests.post(self.OAUTH_ENDPOINT, data=payload, timeout=15)
        data = resp.json()
        logger.info(f"Withings exchange_code_for_token response: {data}")

        if data.get("status") == 0 and "body" in data:
            body = data["body"]
            self.access_token = body.get("access_token", "")
            self.refresh_token = body.get("refresh_token", "")
            return {
                "success": True,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "userid": body.get("userid")
            }
        else:
            error_msg = data.get("error", f"Withings API status: {data.get('status')}")
            raise ValueError(f"{error_msg} (Status: {data.get('status')})")

    def refresh_access_token(self) -> Dict[str, Any]:
        """
        Refresh Withings OAuth2 Access Token using Refresh Token.
        """
        if not self.client_id or not self.client_secret or not self.refresh_token:
            return {"success": False, "error": "Missing Withings OAuth credentials (client_id, client_secret, refresh_token)"}

        payload = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        }

        try:
            resp = requests.post(self.OAUTH_ENDPOINT, data=payload, timeout=15)
            data = resp.json()
            if data.get("status") == 0 and "body" in data:
                body = data["body"]
                self.access_token = body.get("access_token", self.access_token)
                self.refresh_token = body.get("refresh_token", self.refresh_token)
                return {
                    "success": True,
                    "access_token": self.access_token,
                    "refresh_token": self.refresh_token,
                    "expires_in": body.get("expires_in")
                }
            else:
                error_msg = data.get("error", f"Withings API status code: {data.get('status')}")
                return {"success": False, "error": error_msg}
        except Exception as e:
            logger.error(f"Error refreshing Withings token: {e}")
            return {"success": False, "error": str(e)}

    def fetch_measurements(self, days: int = 365) -> List[Dict[str, Any]]:
        """
        Fetch body composition measurements from Withings Health Mate API.
        If days >= 3650, fetches full lifetime history (lastupdate=0).
        """
        self.last_error = None
        if not self.access_token and self.refresh_token:
            res = self.refresh_access_token()
            if not res.get("success"):
                logger.warning(f"Could not refresh Withings token: {res.get('error')}")

        if not self.access_token:
            return []

        if days >= 3650:
            lastupdate = 0
        else:
            lastupdate = int((datetime.now() - timedelta(days=days)).timestamp())

        payload = {
            "action": "getmeas",
            "category": 1,
            "lastupdate": lastupdate
        }
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

        try:
            resp = requests.post(self.MEASURE_ENDPOINT, data=payload, headers=headers, timeout=15)
            data = resp.json()

            # If token expired, attempt refresh once
            if data.get("status") in [401, 5011, 40101, 2555]:
                refresh_res = self.refresh_access_token()
                if refresh_res.get("success"):
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    resp = requests.post(self.MEASURE_ENDPOINT, data=payload, headers=headers, timeout=15)
                    data = resp.json()

            if data.get("status") == 0 and "body" in data:
                measuregrps = data["body"].get("measuregrps", [])
                logger.info(f"Fetched {len(measuregrps)} raw measuregrps from Withings API")
                return self.parse_measurements(measuregrps)
            else:
                logger.warning(f"Withings getmeas status {data.get('status')}: {data}")
                self.last_error = f"Withings API status {data.get('status')}"
                return []
        except Exception as e:
            logger.error(f"Error fetching Withings measurements: {e}")
            self.last_error = str(e)
            return []

    @classmethod
    def parse_measurements(cls, measuregrps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse raw Withings measuregrps into formatted daily dictionary logs.
        Withings values are scaled using value * 10^unit.
        """
        daily_records: Dict[str, Dict[str, Any]] = {}

        for grp in measuregrps:
            dt = datetime.fromtimestamp(grp.get("date", 0))
            date_str = dt.strftime("%Y-%m-%d")

            if date_str not in daily_records:
                daily_records[date_str] = {
                    "date": date_str,
                    "weight_kg": 0.0,
                    "fat_ratio_pct": 0.0,
                    "muscle_mass_kg": 0.0,
                    "bone_mass_kg": 0.0,
                    "water_pct": 0.0,
                    "bmi": 0.0,
                    "source": "withings",
                    "raw_json": grp
                }

            rec = daily_records[date_str]

            for m in grp.get("measures", []):
                m_type = m.get("type")
                raw_val = m.get("value", 0)
                unit = m.get("unit", 0)
                val = raw_val * (10 ** unit)

                if m_type == cls.TYPE_WEIGHT and val > 0:
                    rec["weight_kg"] = round(val, 2)
                elif m_type == cls.TYPE_FAT_RATIO and val > 0:
                    rec["fat_ratio_pct"] = round(val, 2)
                elif m_type == cls.TYPE_MUSCLE_MASS and val > 0:
                    rec["muscle_mass_kg"] = round(val, 2)
                elif m_type == cls.TYPE_BONE_MASS and val > 0:
                    rec["bone_mass_kg"] = round(val, 2)
                elif m_type == cls.TYPE_HYDRATION and val > 0:
                    rec["water_pct"] = round(val, 2)

        # Return all records that have at least weight or body fat data
        valid_records = [r for r in daily_records.values() if r.get("weight_kg", 0) > 0 or r.get("fat_ratio_pct", 0) > 0]
        return valid_records

    def sync_withings_data(self, days: int = 365, force_full: bool = False) -> Dict[str, Any]:
        """
        Fetch and save Withings body composition records to local SQLite DB.
        Single fast API request fetches measurements for the requested range.
        """
        sync_days = 3650 if force_full else max(30, days)
        logger.info(f"Starting Withings DB sync for last {sync_days} days (force_full={force_full})...")
        records = self.fetch_measurements(days=sync_days)
        if not records:
            return {
                "success": False,
                "count": 0,
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "message": self.last_error or "No measurements fetched from Withings"
            }

        saved_count = 0
        for rec in records:
            self.db.upsert_body_composition(
                date=rec["date"],
                weight_kg=rec.get("weight_kg", 0.0),
                fat_ratio_pct=rec.get("fat_ratio_pct", 0.0),
                muscle_mass_kg=rec.get("muscle_mass_kg", 0.0),
                bone_mass_kg=rec.get("bone_mass_kg", 0.0),
                water_pct=rec.get("water_pct", 0.0),
                bmi=rec.get("bmi", 0.0),
                source=rec.get("source", "withings"),
                raw_data=rec.get("raw_json")
            )
            saved_count += 1

        if hasattr(self, 'db') and self.db:
            self.db.set_metadata("last_withings_sync", datetime.now().strftime("%Y-%m-%d"))
            self.db.set_metadata("last_withings_sync_timestamp", datetime.now().isoformat())

        return {
            "success": True,
            "count": saved_count,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "records": records
        }

    def import_withings_export_file(self, filepath: str) -> Dict[str, Any]:
        """
        Import Withings exported history file (CSV or JSON).
        Returns counts of imported measurements.
        """
        import csv
        import json
        from pathlib import Path

        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        records_imported = 0
        if path.suffix.lower() == ".json":
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                measuregrps = data if isinstance(data, list) else data.get("measuregrps", [])
                parsed = self.parse_measurements(measuregrps)
                for rec in parsed:
                    self.db.upsert_body_composition(
                        date=rec["date"],
                        weight_kg=rec.get("weight_kg", 0.0),
                        fat_ratio_pct=rec.get("fat_ratio_pct", 0.0),
                        muscle_mass_kg=rec.get("muscle_mass_kg", 0.0),
                        bone_mass_kg=rec.get("bone_mass_kg", 0.0),
                        water_pct=rec.get("water_pct", 0.0),
                        bmi=rec.get("bmi", 0.0),
                        source="withings_export"
                    )
                    records_imported += 1
        else:
            # Parse CSV file
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Clean dictionary keys
                    clean_row = {k.strip().lower(): v.strip() for k, v in row.items() if k}
                    date_val = clean_row.get("date") or clean_row.get("datum") or clean_row.get("timestamp")
                    if not date_val:
                        continue

                    # Parse date string
                    try:
                        dt = datetime.strptime(date_val[:10], "%Y-%m-%d")
                        date_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        continue

                    def _flt(key_substr):
                        for k, v in clean_row.items():
                            if key_substr in k:
                                try:
                                    return float(v.replace(",", "."))
                                except ValueError:
                                    pass
                        return 0.0

                    weight = _flt("weight") or _flt("vikt")
                    fat = _flt("fat") or _flt("fett")
                    muscle = _flt("muscle") or _flt("muskel")
                    bone = _flt("bone") or _flt("ben")
                    water = _flt("water") or _flt("vätska") or _flt("hydration")

                    if weight > 0 or fat > 0:
                        self.db.upsert_body_composition(
                            date=date_str,
                            weight_kg=weight,
                            fat_ratio_pct=fat,
                            muscle_mass_kg=muscle,
                            bone_mass_kg=bone,
                            water_pct=water,
                            source="withings_csv"
                        )
                        records_imported += 1

        return {"count": records_imported}
