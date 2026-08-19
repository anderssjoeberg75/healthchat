"""
Garmin Connect data handler for retrieving and formatting user fitness data.
"""

import garth
from garth.exc import GarthHTTPError
from garminconnect import Garmin
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import logging

from garmin_db import GarminDatabase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GarminDataHandler:
    """Handles Garmin Connect authentication and data retrieval."""
    
    def __init__(self, email: str, password: str, token_store_path: Optional[str] = None):
        """
        Initialize Garmin Connect handler.
        
        Args:
            email: Garmin Connect email
            password: Garmin Connect password
            token_store_path: Directory to store tokens (default: ~/.garmin_tokens)
        """
        self.email = email
        self.password = password
        self.client: Optional[Garmin] = None
        self._authenticated = False
        
        # Initialize Local SQLite Database
        self.db = GarminDatabase()
        
        # Token store directory - garth will create oauth1_token.json and oauth2_token.json files
        if token_store_path is None:
            self.token_store = Path.home() / ".garmin_tokens"
        else:
            self.token_store = Path(token_store_path)
        
        self.token_store.mkdir(parents=True, exist_ok=True)
        self.client_state = None

    def sync_garmin_history(
        self, 
        days: int = 30, 
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        on_complete: Optional[Callable[[], None]] = None
    ):
        """Fetch health metrics and activities for recent days and store in local SQLite database (runs in background)."""
        if not self._authenticated:
            return
            
        def _sync_worker():
            try:
                logger.info(f"Starting background Garmin DB sync for last {days} days...")
                if on_progress:
                    try:
                        on_progress(0, days, "Hämtar träningspass...")
                    except Exception:
                        pass

                # 1. Sync activities (fetch up to 2000 workouts for full history)
                act_limit = 2000 if days >= 365 else max(100, days * 2)
                activities = self.get_activities(limit=act_limit)
                for act in activities:
                    self.db.upsert_activity(act)
                    
                # 2. Sync daily metrics for each day
                from datetime import datetime, timedelta
                for i in range(days):
                    d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
                    if on_progress:
                        try:
                            on_progress(i + 1, days, f"Synkar {d}...")
                        except Exception:
                            pass

                    try:
                        # Sleep
                        sleep = self.client.get_sleep_data(d)
                        if sleep and "dailySleepDTO" in sleep:
                            sd = sleep["dailySleepDTO"]
                            self.db.upsert_sleep(
                                date=d,
                                total_hours=(sd.get("sleepTimeSeconds", 0) or 0) / 3600.0,
                                deep_hours=(sd.get("deepSleepSeconds", 0) or 0) / 3600.0,
                                light_hours=(sd.get("lightSleepSeconds", 0) or 0) / 3600.0,
                                rem_hours=(sd.get("remSleepSeconds", 0) or 0) / 3600.0,
                                awake_hours=(sd.get("awakeSleepSeconds", 0) or 0) / 3600.0,
                                score=sd.get("sleepQualityScore", 0) or 0,
                                raw_data=sleep
                            )
                    except Exception as e:
                        logger.debug(f"Sync sleep failed for {d}: {e}")
                        
                    try:
                        # Body Battery
                        bb = self.client.get_body_battery(d)
                        if bb:
                            bb_metrics = self.extract_bb_metrics(bb, d)
                            if bb_metrics:
                                self.db.upsert_body_battery(
                                    date=d,
                                    charged=bb_metrics.get("charged", 0) or 0,
                                    drained=bb_metrics.get("drained", 0) or 0,
                                    highest=bb_metrics.get("highest", 0) or 0,
                                    lowest=bb_metrics.get("lowest", 0) or 0,
                                    current=bb_metrics.get("current", 0) or 0
                                )
                    except Exception as e:
                        logger.debug(f"Sync Body Battery failed for {d}: {e}")
                        
                    try:
                        # Stress
                        st = self.client.get_stress_data(d)
                        if st and isinstance(st, dict):
                            self.db.upsert_stress(
                                date=d,
                                average=st.get("avgStressLevel", st.get("averageStressLevel", 0)) or 0,
                                max_stress=st.get("maxStressLevel", 0) or 0,
                                rest=st.get("restStressDuration", st.get("restStressLevel", 0)) or 0,
                                activity=st.get("activityStressDuration", st.get("activityStressLevel", 0)) or 0,
                                low_min=(st.get("lowStressDuration", 0) or 0) // 60,
                                med_min=(st.get("mediumStressDuration", 0) or 0) // 60,
                                high_min=(st.get("highStressDuration", 0) or 0) // 60
                            )
                    except Exception as e:
                        logger.debug(f"Sync stress failed for {d}: {e}")
                        
                    try:
                        # HRV
                        hrv = self.client.get_hrv_data(d)
                        if hrv and isinstance(hrv, dict):
                            summary = hrv.get("hrvSummary", {})
                            self.db.upsert_hrv(
                                date=d,
                                last_night_avg=summary.get("lastNightAvg", hrv.get("lastNightAvg", 0)) or 0,
                                weekly_avg=summary.get("weeklyAvg", hrv.get("weeklyAvg", 0)) or 0,
                                status=summary.get("status", "") or ""
                            )
                    except Exception as e:
                        logger.debug(f"Sync HRV failed for {d}: {e}")
                        
                logger.info("Garmin DB background sync completed successfully!")
                if on_complete:
                    try:
                        on_complete()
                    except Exception as cb_err:
                        logger.error(f"Error in on_complete callback: {cb_err}")
            except Exception as sync_err:
                logger.error(f"Error during Garmin DB sync: {sync_err}")
                
        import threading
        t = threading.Thread(target=_sync_worker, daemon=True)
        t.start()
        
    def authenticate(self, mfa_callback: Optional[Callable[[], str]] = None) -> Dict:
        """
        Authenticate with Garmin Connect.
        
        Args:
            mfa_callback: Optional function that returns MFA code when called
        
        Returns:
            Dictionary with authentication status:
            - {'success': True} if successful
            - {'mfa_required': True} if MFA code needed
            - {'error': 'message'} on failure
        """
        try:
            logger.info("Authenticating with Garmin Connect...")
            
            # Try to resume existing session first
            try:
                oauth1_path = self.token_store / "oauth1_token.json"
                oauth2_path = self.token_store / "oauth2_token.json"
                
                logger.info(f"Token store directory: {self.token_store}")
                logger.info(f"OAuth1 token path: {oauth1_path}")
                logger.info(f"OAuth2 token path: {oauth2_path}")
                logger.info(f"OAuth1 token exists: {oauth1_path.exists()}")
                logger.info(f"OAuth2 token exists: {oauth2_path.exists()}")
                
                if oauth1_path.exists():
                    logger.info(f"OAuth1 token file size: {oauth1_path.stat().st_size} bytes")
                if oauth2_path.exists():
                    logger.info(f"OAuth2 token file size: {oauth2_path.stat().st_size} bytes")
                
                if not oauth1_path.exists() or not oauth2_path.exists():
                    logger.info("Token files not found, will do fresh login")
                    raise FileNotFoundError("Token files not found")

                # Check if the refresh token has expired — if so, skip resume
                # and force a fresh login (garth.resume succeeds even with dead tokens,
                # but subsequent API calls silently return empty results).
                try:
                    import json as _json
                    with open(oauth2_path) as _f:
                        _tok = _json.load(_f)
                    _refresh_exp = _tok.get('refresh_token_expires_at', 0)
                    if datetime.fromtimestamp(_refresh_exp) < datetime.now():
                        logger.info("Refresh token has expired — clearing tokens and forcing fresh login")
                        oauth1_path.unlink(missing_ok=True)
                        oauth2_path.unlink(missing_ok=True)
                        raise FileNotFoundError("Refresh token expired")
                    logger.info(f"Refresh token valid until {datetime.fromtimestamp(_refresh_exp)}")
                except FileNotFoundError:
                    raise
                except Exception as _e:
                    logger.warning(f"Could not check token expiry: {_e}")

                logger.info(f"Calling garth.resume() with path: {str(self.token_store)}")
                try:
                    garth.resume(str(self.token_store))
                    logger.info("âœ… garth.resume() succeeded!")
                    # garth uses a mobile iPhone User-Agent for SSO auth, but Garmin's
                    # Connect API returns empty lists for mobile UAs on activity endpoints.
                    # Switch to a standard requests UA so data APIs return real results.
                    garth.client.sess.headers.update({'User-Agent': 'python-requests/2.32.3'})
                except Exception as resume_ex:
                    logger.error(f"âŒ garth.resume() failed: {type(resume_ex).__name__}: {resume_ex}")
                    
                    # Try manual token loading
                    logger.info("Attempting manual token load...")
                    import json
                    import os
                    
                    token_dir = str(self.token_store)
                    oauth1_path = os.path.join(token_dir, "oauth1_token.json")
                    oauth2_path = os.path.join(token_dir, "oauth2_token.json")
                    
                    if os.path.exists(oauth1_path) and os.path.exists(oauth2_path):
                        try:
                            # Load OAuth1 token
                            with open(oauth1_path, 'r') as f:
                                oauth1_data = json.load(f)
                            logger.info("âœ… Loaded OAuth1 token manually")
                            
                            # Load OAuth2 token
                            with open(oauth2_path, 'r') as f:
                                oauth2_data = json.load(f)
                            logger.info("âœ… Loaded OAuth2 token manually")
                            
                            # Set tokens in garth client
                            from garth.http import OAuth1Token, OAuth2Token
                            garth.client.oauth1_token = OAuth1Token(**oauth1_data)
                            garth.client.oauth2_token = OAuth2Token(**oauth2_data)
                            logger.info("âœ… Manually loaded tokens into garth.client")
                            logger.info("✅ Manually loaded tokens into garth.client")
                            
                        except Exception as manual_load_error:
                            logger.error(f"Failed to manually load tokens: {manual_load_error}")
                            raise
                    else:
                        raise
                
                logger.info("Creating Garmin client and logging in with saved tokens...")
                self.client = Garmin(self.email, self.password)
                self.client.login(str(self.token_store))
                if hasattr(self.client, 'garth') and hasattr(self.client.garth, 'sess'):
                    self.client.garth.sess.headers.update({'User-Agent': 'python-requests/2.32.3'})
                logger.info("Garmin client initialized and logged in via tokens")
                
                self.client.display_name = self._resolve_display_name()
                
                self._authenticated = True
                logger.info("Successfully resumed existing Garmin session")
                return {'success': True}
                        
            except Exception as resume_error:
                logger.info(f"❌ Could not resume session: {type(resume_error).__name__}: {resume_error}")
                logger.info("Will attempt fresh login...")
            
            # Attempt fresh login
            # Use threading so the GUI can show an MFA prompt while garth waits
            try:
                import threading
                
                logger.info("Attempting fresh Garmin login...")
                
                # MFA coordination: garth's prompt_mfa callback blocks until code arrives
                mfa_event = threading.Event()       # set when MFA code is ready
                mfa_result = [None]                  # holds the MFA code
                mfa_needed = [False]                 # set if MFA was requested
                login_done = threading.Event()        # set when login thread finishes
                login_error = [None]                  # holds any login exception
                login_success = [False]               # set if login completed cleanly

                def _prompt_mfa():
                    """Called by garth when MFA code is needed (runs inside login thread)."""
                    mfa_needed[0] = True
                    logger.info("garth is requesting MFA code...")
                    mfa_event.wait(timeout=300)  # wait up to 5 min for user
                    code = mfa_result[0] or ''
                    logger.info(f"Returning MFA code to garth (length={len(code)})")
                    return code

                def _do_login():
                    try:
                        if mfa_callback:
                            # Caller provided their own MFA retrieval function
                            garth.login(self.email, self.password,
                                        prompt_mfa=mfa_callback)
                        else:
                            garth.login(self.email, self.password,
                                        prompt_mfa=_prompt_mfa)
                        login_success[0] = True
                    except Exception as ex:
                        login_error[0] = ex
                    finally:
                        login_done.set()

                login_thread = threading.Thread(target=_do_login, daemon=True)
                login_thread.start()

                # Wait briefly to see if MFA is triggered or login completes quickly
                login_done.wait(timeout=3)

                if not login_done.is_set() and mfa_needed[0]:
                    # Login is paused waiting for MFA code
                    self.client_state = {
                        'mfa_event': mfa_event,
                        'mfa_result': mfa_result,
                        'login_done': login_done,
                        'login_error': login_error,
                        'login_success': login_success,
                        'login_thread': login_thread,
                    }
                    logger.info("MFA required - waiting for code from UI")
                    return {'mfa_required': True}

                # Login completed (or failed) without needing MFA
                login_thread.join(timeout=30)

                if login_error[0]:
                    raise login_error[0]

                if not login_success[0]:
                    raise RuntimeError("Login did not complete successfully")

                # Save tokens
                try:
                    garth.save(str(self.token_store))
                    logger.info(f"âœ… Tokens saved to {self.token_store}")
                except Exception as save_err:
                    logger.warning(f"Could not save tokens: {save_err}")

                garth.client.sess.headers.update({'User-Agent': 'python-requests/2.32.3'})
                self.client = Garmin()
                self.client.garth = garth.client
                self._authenticated = True

                self.client.display_name = self._resolve_display_name()
                logger.info("Successfully authenticated with Garmin Connect")
                return {'success': True}

            except GarthHTTPError as e:
                logger.error(f"Garmin login failed: {e}")
                return {'error': f'Login failed: {str(e)}'}
                    
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            return {'error': f'Authentication error: {str(e)}'}
    
    def submit_mfa(self, mfa_code: str) -> Dict:
        """
        Submit MFA code after initial authentication indicated MFA required.
        
        Args:
            mfa_code: 6-digit MFA code from user's authenticator
            
        Returns:
            Dictionary with status:
            - {'success': True} on success
            - {'error': 'message'} on failure
        """
        if not self.client_state:
            return {'error': 'Must authenticate first before submitting MFA'}
        
        try:
            logger.info("Submitting MFA code to Garmin...")
            
            # The login thread is paused inside garth waiting for the MFA code.
            # Signal it with the code and wait for it to finish.
            state = self.client_state
            mfa_result = state['mfa_result']
            mfa_event  = state['mfa_event']
            login_done = state['login_done']
            login_error = state['login_error']
            login_success = state['login_success']
            
            # Deliver the code to the waiting _prompt_mfa() callback
            mfa_result[0] = mfa_code
            mfa_event.set()
            
            # Wait for garth to complete authentication
            logger.info("Waiting for garth to complete login after MFA...")
            login_done.wait(timeout=60)
            
            if login_error[0]:
                raise login_error[0]
            
            if not login_success[0]:
                raise RuntimeError("Login did not complete after MFA submission")
            
            # Save tokens
            try:
                garth.save(str(self.token_store))
                logger.info(f"âœ… Tokens saved to {self.token_store}")
            except Exception as save_err:
                logger.warning(f"Could not save tokens (will re-auth next time): {save_err}")
            
            garth.client.sess.headers.update({'User-Agent': 'python-requests/2.32.3'})
            self.client = Garmin()
            self.client.garth = garth.client
            self._authenticated = True
            self.client_state = None
            
            self.client.display_name = self._resolve_display_name()
            logger.info("Successfully authenticated with MFA")
            return {'success': True}
            
        except Exception as e:
            logger.error(f"MFA submission failed: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {'error': f'MFA submission failed: {str(e)}'}
    
    def _ensure_authenticated(self):
        """Ensure client is authenticated before making requests."""
        if not self._authenticated or self.client is None:
            raise RuntimeError("Not authenticated. Call authenticate() first.")
    
    def _resolve_display_name(self) -> str:
        """
        Fetch the Garmin Connect display name (username slug) from the social profile.
        garth.client.username returns the SSO login email, which is NOT what the
        usersummary/userprofile APIs expect in their URL paths.
        Falls back to email prefix if the API call fails.
        """
        try:
            profile = garth.client.connectapi('/userprofile-service/socialProfile')
            display_name = profile.get('displayName') or profile.get('userName', '')
            # Prefer displayName (slug like 'rodtrent'), not userName (email)
            if '@' in display_name:
                # userName came back as email — use email prefix instead
                display_name = display_name.split('@')[0]
            logger.info(f"Display name from social profile: {display_name!r}")
            return display_name
        except Exception as e:
            logger.warning(f"Could not fetch social profile for display name: {e}")
            return self.email.split('@')[0]

    def _ensure_display_name(self):
        """
        Ensure display_name is set for API calls that require it.
        """
        if not hasattr(self.client, 'display_name') or not self.client.display_name or '@' in (self.client.display_name or ''):
            self.client.display_name = self._resolve_display_name()
            logger.debug(f"Display name resolved: {self.client.display_name!r}")
    
    def get_user_summary(self) -> Dict:
        """
        Get user profile summary.
        
        Returns:
            Dictionary containing user profile information
        """
        self._ensure_authenticated()
        self._ensure_display_name()
        try:
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")
            return self.client.get_user_summary(today)
        except Exception as e:
            logger.error(f"Error fetching user summary: {e}")
            return {}
    
    def get_activities(self, limit: int = 10, start: int = 0) -> List[Dict]:
        """
        Get recent activities with pagination support.
        
        Args:
            limit: Number of activities to retrieve (max recommended: 100)
            start: Starting index for pagination (0 = most recent)
            
        Returns:
            List of activity dictionaries
            
        Note:
            - Garmin API can return up to 100 activities per request
            - For more than 100, use multiple requests with different start values
            - Activities are ordered newest to oldest
        """
        self._ensure_authenticated()
        try:
            logger.info(f"Calling get_activities: start={start}, limit={limit}, display_name={getattr(self.client, 'display_name', None)!r}")
            activities = self.client.get_activities(start, limit)
            logger.info(f"get_activities returned: {len(activities) if activities else 0} items, type={type(activities).__name__}")
            return activities if activities else []
        except Exception as e:
            logger.error(f"Error fetching activities: {e}")
            return []
    
    def get_activities_by_date(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Get activities within a date range.
        
        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            
        Returns:
            List of activity dictionaries within the date range
            
        Note:
            This fetches activities in batches and filters by date.
            May require multiple API calls for large date ranges.
        """
        self._ensure_authenticated()
        try:
            from datetime import datetime
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            
            all_activities = []
            batch_size = 50
            current_start = 0
            
            # Keep fetching until we get activities outside our date range
            while True:
                activities = self.get_activities(limit=batch_size, start=current_start)
                
                if not activities:
                    break
                
                for activity in activities:
                    # Parse activity date
                    start_time_str = activity.get("startTimeLocal", "")
                    if start_time_str:
                        activity_dt = datetime.strptime(start_time_str[:10], "%Y-%m-%d")
                        
                        # If activity is within range, add it
                        if start_dt <= activity_dt <= end_dt:
                            all_activities.append(activity)
                        # If we've gone past the start date, we're done
                        elif activity_dt < start_dt:
                            return all_activities
                
                # Move to next batch
                current_start += batch_size
                
                # Safety limit: don't fetch more than 500 activities
                if current_start >= 500:
                    logger.warning("Reached safety limit of 500 activities")
                    break
            
            return all_activities
            
        except Exception as e:
            logger.error(f"Error fetching activities by date: {e}")
            return []
    
    def get_activity_details(self, activity_id: int) -> Dict:
        """
        Get detailed data for a specific activity.
        
        For strength training activities, this includes:
        - Individual exercises performed
        - Sets and reps for each exercise
        - Weight/resistance used
        - Rest times between sets
        - Exercise order and structure
        
        Args:
            activity_id: The Garmin activity ID
            
        Returns:
            Detailed activity dictionary with all available data
        """
        self._ensure_authenticated()
        try:
            details = self.client.get_activity_details(activity_id)
            return details if details else {}
        except Exception as e:
            logger.error(f"Error fetching activity details for {activity_id}: {e}")
            return {}
    
    def get_strength_training_details(self, activity_id: int) -> Dict:
        """
        Parse and structure strength training specific data from an activity.
        
        Returns detailed information about:
        - Each exercise performed (name, category)
        - Sets, reps, and weight for each exercise
        - Rest times between sets
        - Volume metrics (total sets, reps, weight lifted)
        - Workout duration and calories
        
        Args:
            activity_id: The Garmin activity ID
            
        Returns:
            Dictionary with structured strength training data:
            {
                'activity_id': int,
                'activity_name': str,
                'date': str,
                'duration_minutes': int,
                'calories': int,
                'exercises': [
                    {
                        'name': str,
                        'category': str,
                        'sets': [
                            {
                                'set_number': int,
                                'reps': int,
                                'weight': float,
                                'weight_unit': str,
                                'duration_seconds': int
                            }
                        ],
                        'rest_times': [int],  # seconds
                        'total_reps': int,
                        'total_volume': float
                    }
                ],
                'metrics': {
                    'total_exercises': int,
                    'total_sets': int,
                    'total_reps': int,
                    'total_volume': float,
                    'average_rest_time': float
                }
            }
            
            Returns {'error': str} if not a strength training activity or data unavailable
        """
        self._ensure_authenticated()
        
        try:
            # Get detailed activity data
            details = self.get_activity_details(activity_id)
            
            if not details:
                return {'error': 'Could not fetch activity details'}
            
            # Check if this is a strength training activity
            activity_type = details.get('activityType', {}).get('typeKey', '')
            if 'strength' not in activity_type.lower():
                return {
                    'error': f'Not a strength training activity (type: {activity_type})',
                    'activity_type': activity_type
                }
            
            # Extract basic activity info
            activity_name = details.get('activityName', 'Strength Training')
            start_time = details.get('startTimeLocal', '')
            duration_seconds = details.get('duration', 0)
            calories = details.get('calories', 0)
            
            # Parse exercise sets data
            exercises = []
            total_sets = 0
            total_reps = 0
            total_volume = 0
            all_rest_times = []
            
            # The structure varies by Garmin device and how workout was recorded
            # Try multiple possible data locations
            exercise_sets = details.get('exerciseSets', []) or details.get('sets', [])
            
            for exercise_data in exercise_sets:
                exercise_name = exercise_data.get('exerciseName') or exercise_data.get('category', 'Unknown Exercise')
                category = exercise_data.get('category', '')
                
                exercise_info = {
                    'name': exercise_name,
                    'category': category,
                    'sets': [],
                    'rest_times': [],
                    'total_reps': 0,
                    'total_volume': 0
                }
                
                # Parse individual sets
                set_number = 0
                sets_data = exercise_data.get('sets', [])
                
                for set_data in sets_data:
                    set_type = set_data.get('setType', '')
                    
                    if set_type == 'ACTIVE' or set_type == 'active':
                        set_number += 1
                        reps = set_data.get('repetitions', 0) or set_data.get('reps', 0)
                        weight = set_data.get('weight', 0)
                        weight_unit = set_data.get('weightDisplayUnit', 'lb')
                        duration = set_data.get('duration', 0)
                        
                        set_info = {
                            'set_number': set_number,
                            'reps': reps,
                            'weight': weight,
                            'weight_unit': weight_unit,
                            'duration_seconds': duration
                        }
                        
                        exercise_info['sets'].append(set_info)
                        exercise_info['total_reps'] += reps
                        
                        if weight and reps:
                            set_volume = weight * reps
                            exercise_info['total_volume'] += set_volume
                        
                        total_sets += 1
                        total_reps += reps
                    
                    elif set_type == 'REST' or set_type == 'rest':
                        rest_duration = set_data.get('duration', 0)
                        if rest_duration > 0:
                            exercise_info['rest_times'].append(rest_duration)
                            all_rest_times.append(rest_duration)
                
                # Only add exercise if it has sets
                if exercise_info['sets']:
                    total_volume += exercise_info['total_volume']
                    exercises.append(exercise_info)
            
            # Calculate average rest time
            avg_rest_time = sum(all_rest_times) / len(all_rest_times) if all_rest_times else 0
            
            return {
                'activity_id': activity_id,
                'activity_name': activity_name,
                'date': start_time[:10] if start_time else '',
                'start_time': start_time,
                'duration_minutes': duration_seconds // 60,
                'duration_seconds': duration_seconds,
                'calories': calories,
                'exercises': exercises,
                'metrics': {
                    'total_exercises': len(exercises),
                    'total_sets': total_sets,
                    'total_reps': total_reps,
                    'total_volume': round(total_volume, 1),
                    'average_rest_time': round(avg_rest_time, 1)
                }
            }
            
        except Exception as e:
            logger.error(f"Error parsing strength training details: {e}")
            return {'error': f'Error parsing strength training data: {str(e)}'}
    
    def find_strength_training_activities(self, limit: int = 20) -> List[Dict]:
        """
        Find recent strength training activities.
        
        Args:
            limit: Number of recent activities to search through
            
        Returns:
            List of strength training activities with basic info
        """
        self._ensure_authenticated()
        
        try:
            activities = self.get_activities(limit=limit)
            strength_activities = []
            
            for activity in activities:
                activity_type = activity.get('activityType', {}).get('typeKey', '')
                if 'strength' in activity_type.lower() or 'training' in activity_type.lower():
                    strength_activities.append({
                        'activity_id': activity.get('activityId'),
                        'name': activity.get('activityName', 'Strength Training'),
                        'date': activity.get('startTimeLocal', '')[:10],
                        'duration_minutes': activity.get('duration', 0) // 60,
                        'calories': activity.get('calories', 0)
                    })
            
            return strength_activities
            
        except Exception as e:
            logger.error(f"Error finding strength training activities: {e}")
            return []
    
    def format_strength_training_for_display(self, strength_data: Dict) -> str:
        """
        Format strength training data into a readable string for AI context or display.
        
        Args:
            strength_data: Dictionary from get_strength_training_details()
            
        Returns:
            Formatted string with exercise details, sets, reps, weights
        """
        if 'error' in strength_data:
            return f"Error: {strength_data['error']}"
        
        output = []
        output.append(f"**{strength_data['activity_name']}**")
        output.append(f"Date: {strength_data['date']}")
        output.append(f"Duration: {strength_data['duration_minutes']} minutes")
        output.append(f"Calories: {strength_data['calories']}")
        output.append("")
        
        # List exercises
        exercises = strength_data.get('exercises', [])
        if exercises:
            output.append("**Exercises Performed:**")
            output.append("")
            
            for i, exercise in enumerate(exercises, 1):
                output.append(f"{i}. **{exercise['name']}**")
                
                # Show sets
                for set_info in exercise['sets']:
                    weight_str = ""
                    if set_info['weight'] > 0:
                        weight_str = f" @ {set_info['weight']} {set_info['weight_unit']}"
                    
                    output.append(f"   Set {set_info['set_number']}: {set_info['reps']} reps{weight_str}")
                
                # Show rest times if available
                if exercise['rest_times']:
                    avg_rest = sum(exercise['rest_times']) / len(exercise['rest_times'])
                    output.append(f"   Rest: {avg_rest:.0f}s average")
                
                # Show exercise totals
                if exercise['total_volume'] > 0:
                    output.append(f"   Total: {exercise['total_reps']} reps, {exercise['total_volume']:.1f} lbs volume")
                else:
                    output.append(f"   Total: {exercise['total_reps']} reps")
                
                output.append("")
        
        # Show workout summary
        metrics = strength_data.get('metrics', {})
        output.append("**Workout Summary:**")
        output.append(f"- Total Exercises: {metrics.get('total_exercises', 0)}")
        output.append(f"- Total Sets: {metrics.get('total_sets', 0)}")
        output.append(f"- Total Reps: {metrics.get('total_reps', 0)}")
        
        if metrics.get('total_volume', 0) > 0:
            output.append(f"- Total Volume: {metrics.get('total_volume', 0):,.1f} lbs")
        
        if metrics.get('average_rest_time', 0) > 0:
            output.append(f"- Average Rest: {metrics.get('average_rest_time', 0):.0f}s")
        
        return "\n".join(output)
    
    def get_steps_data(self, date: Optional[str] = None) -> Dict:
        """
        Get steps data for a specific date.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing steps data
        """
        self._ensure_authenticated()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_steps_data(date)
        except Exception as e:
            logger.error(f"Error fetching steps data: {e}")
            return {}
    
    def get_heart_rate_data(self, date: Optional[str] = None) -> Dict:
        """
        Get heart rate data for a specific date.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing heart rate data
        """
        self._ensure_authenticated()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_heart_rates(date)
        except Exception as e:
            logger.error(f"Error fetching heart rate data: {e}")
            return {}
    
    def get_sleep_data(self, date: Optional[str] = None) -> Dict:
        """
        Get sleep data for a specific date (or fall back to recent days if empty).
        """
        self._ensure_authenticated()
        from datetime import datetime, timedelta
        dates_to_try = [date] if date else [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        
        for d in dates_to_try:
            try:
                data = self.client.get_sleep_data(d)
                if data and (data.get("dailySleepDTO") or data.get("sleepTimeSeconds")):
                    data["_retrieved_date"] = d
                    return data
            except Exception as e:
                logger.debug(f"Sleep data for {d} not available: {e}")
        return {}

    def get_body_composition(self, date: Optional[str] = None) -> Dict:
        """
        Get body composition data.
        """
        self._ensure_authenticated()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_body_composition(date)
        except Exception as e:
            logger.error(f"Error fetching body composition: {e}")
            return {}

    @staticmethod
    def extract_bb_metrics(data, date_str: str) -> Dict:
        """Robustly extract Body Battery values from various Garmin Connect API response schemas."""
        if not data:
            return {}
        
        entry = data[0] if isinstance(data, list) and len(data) > 0 else (data if isinstance(data, dict) else {})
        if not isinstance(entry, dict):
            return {}
        
        charged = entry.get('charged') or entry.get('bodyBatteryChargedValue') or 0
        drained = entry.get('drained') or entry.get('bodyBatteryDrainedValue') or 0
        highest = entry.get('highest') or entry.get('bodyBatteryHighestValue') or 0
        lowest = entry.get('lowest') or entry.get('bodyBatteryLowestValue') or 0
        current = entry.get('current') or entry.get('mostRecentValue') or entry.get('bodyBatteryMostRecentValue') or 0

        # Check bodyBatteryStatList if present
        stat_list = entry.get('bodyBatteryStatList') or entry.get('statList')
        if isinstance(stat_list, list) and len(stat_list) > 0:
            stat = stat_list[0]
            if isinstance(stat, dict):
                if not charged: charged = stat.get('charged') or stat.get('bodyBatteryChargedValue', 0)
                if not drained: drained = stat.get('drained') or stat.get('bodyBatteryDrainedValue', 0)
                if not highest: highest = stat.get('highest') or stat.get('bodyBatteryHighestValue', 0)
                if not lowest: lowest = stat.get('lowest') or stat.get('bodyBatteryLowestValue', 0)
                if not current: current = stat.get('current') or stat.get('mostRecentValue', 0)

        # Check time series values array (bodyBatteryValuesArray) if min/max not present
        val_array = entry.get('bodyBatteryValuesArray') or entry.get('values') or []
        if isinstance(val_array, list) and len(val_array) > 0:
            valid_vals = []
            for item in val_array:
                if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], (int, float)):
                    valid_vals.append(item[1])
                elif isinstance(item, (int, float)):
                    valid_vals.append(item)
                elif isinstance(item, dict) and 'value' in item:
                    valid_vals.append(item['value'])
            
            if valid_vals:
                if not highest:
                    highest = max(valid_vals)
                if not lowest:
                    lowest = min(valid_vals)
                if not current:
                    current = valid_vals[-1]

        return {
            'date': entry.get('date', date_str),
            'charged': charged,
            'drained': drained,
            'highest': highest,
            'lowest': lowest,
            'current': current
        }

    def get_body_battery(self, date: Optional[str] = None) -> Dict:
        """
        Get Body Battery data (energy levels throughout the day), with recent day fallback.
        """
        self._ensure_authenticated()
        self._ensure_display_name()
        from datetime import datetime, timedelta
        dates_to_try = [date] if date else [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        for d in dates_to_try:
            try:
                data = self.client.get_body_battery(d)
                if data:
                    res = self.extract_bb_metrics(data, d)
                    if res.get('charged') or res.get('highest') or res.get('current') or res.get('drained'):
                        return res
            except Exception as e:
                logger.debug(f"Body Battery for {d} not available: {e}")
        return {}

    def get_stress_data(self, date: Optional[str] = None) -> Dict:
        """
        Get stress level data for the day (with recent day fallback).
        """
        self._ensure_authenticated()
        self._ensure_display_name()
        from datetime import datetime, timedelta
        dates_to_try = [date] if date else [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        for d in dates_to_try:
            try:
                data = self.client.get_stress_data(d)
                if data and isinstance(data, dict):
                    avg = data.get('avgStressLevel') or data.get('averageStressLevel') or 0
                    max_st = data.get('maxStressLevel') or 0
                    if avg > 0 or max_st > 0:
                        return {
                            'date': data.get('calendarDate', d),
                            'average': avg,
                            'max': max_st,
                            'rest': data.get('restStressDuration', data.get('restStressLevel', 0)),
                            'activity': data.get('activityStressDuration', data.get('activityStressLevel', 0)),
                            'low_duration': data.get('lowStressDuration', 0),
                            'medium_duration': data.get('mediumStressDuration', 0),
                            'high_duration': data.get('highStressDuration', 0)
                        }
            except Exception as e:
                logger.debug(f"Stress data for {d} not available: {e}")
        return {}
    
    def get_respiration_data(self, date: Optional[str] = None) -> Dict:
        """
        Get respiration rate data (breaths per minute).
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing respiration rates
        """
        self._ensure_authenticated()
        self._ensure_display_name()  # Ensure display_name is set
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            data = self.client.get_respiration_data(date)
            if data:
                return {
                    'date': date,
                    'waking_avg': data.get('avgWakingRespirationValue', 0),
                    'sleeping_avg': data.get('avgSleepRespirationValue', 0),
                    'highest': data.get('highestRespirationValue', 0),
                    'lowest': data.get('lowestRespirationValue', 0)
                }
            return {}
        except AttributeError:
            logger.debug("Respiration API not available")
            return {}
        except Exception as e:
            logger.debug(f"Respiration data not available: {e}")
            return {}
    
    def get_hydration_data(self, date: Optional[str] = None) -> Dict:
        """
        Get hydration/water intake data.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing hydration data in milliliters
        """
        self._ensure_authenticated()
        self._ensure_display_name()  # Ensure display_name is set
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_hydration_data(date) or {}
        except AttributeError:
            logger.debug("Hydration API not available")
            return {}
        except Exception as e:
            logger.debug(f"Hydration data not available: {e}")
            return {}
    
    def get_floors_data(self, date: Optional[str] = None) -> Dict:
        """
        Get floors climbed data.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing floors climbed
        """
        self._ensure_authenticated()
        self._ensure_display_name()  # Ensure display_name is set
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            # Floors are usually in the daily summary
            steps_data = self.client.get_steps_data(date)
            if steps_data:
                return {
                    'date': date,
                    'floors_ascended': steps_data.get('floorsAscended', 0),
                    'floors_descended': steps_data.get('floorsDescended', 0),
                    'floors_ascended_goal': steps_data.get('floorsAscendedGoal', 0)
                }
            return {}
        except Exception as e:
            logger.debug(f"Floors data not available: {e}")
            return {}
    
    def get_intensity_minutes(self, date: Optional[str] = None) -> Dict:
        """
        Get intensity minutes (moderate and vigorous activity).
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing intensity minutes
        """
        self._ensure_authenticated()
        self._ensure_display_name()  # Ensure display_name is set
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            # Try to get from heart rate data which sometimes includes intensity
            hr_data = self.client.get_heart_rates(date)
            if hr_data and isinstance(hr_data, dict):
                return {
                    'date': date,
                    'moderate': hr_data.get('moderateIntensityMinutes', 0),
                    'vigorous': hr_data.get('vigorousIntensityMinutes', 0),
                    'weekly_moderate': hr_data.get('weeklyModerateIntensityMinutes', 0),
                    'weekly_vigorous': hr_data.get('weeklyVigorousIntensityMinutes', 0),
                    'weekly_goal': hr_data.get('intensityMinutesGoal', 150)
                }
            return {}
        except Exception as e:
            logger.debug(f"Intensity minutes not available: {e}")
            return {}
    
    def get_calories_data(self, date: Optional[str] = None) -> Dict:
        """
        Get calories data (consumed, burned, net).
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing calorie data
        """
        self._ensure_authenticated()
        self._ensure_display_name()  # Ensure display_name is set
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            # Get from user summary which has calorie data
            summary = self.get_user_summary()
            if summary:
                return {
                    'date': date,
                    'total_burned': summary.get('totalKilocalories', 0),
                    'active_burned': summary.get('activeKilocalories', 0),
                    'bmr': summary.get('bmrKilocalories', 0),
                    'consumed': summary.get('consumedCalories', 0),
                    'net': summary.get('netCalorieGoal', 0)
                }
            return {}
        except Exception as e:
            logger.debug(f"Calorie data not available: {e}")
            return {}
    
    def get_nutrition_summary(self, date: Optional[str] = None) -> Dict:
        """
        Get detailed nutrition summary including macros and food logging.
        This is Garmin's newer nutrition feature.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing nutrition data (calories, protein, carbs, fat, etc.)
        """
        self._ensure_authenticated()
        self._ensure_display_name()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        nutrition_data = {}
        
        # Try Method 1: Dedicated nutrition API endpoint
        try:
            # Some Garmin devices support a nutrition summary endpoint
            data = self.client.get_nutrition_summary(date)
            if data:
                nutrition_data.update({
                    'date': date,
                    'calories_consumed': data.get('totalCalories', data.get('consumedCalories', 0)),
                    'protein_g': data.get('totalProtein', 0),
                    'carbs_g': data.get('totalCarbs', 0),
                    'fat_g': data.get('totalFat', 0),
                    'fiber_g': data.get('totalFiber', 0),
                    'sugar_g': data.get('totalSugar', 0),
                    'sodium_mg': data.get('totalSodium', 0),
                    'water_ml': data.get('totalWater', 0)
                })
                logger.debug("Nutrition data loaded from get_nutrition_summary")
                return nutrition_data
        except AttributeError:
            logger.debug("get_nutrition_summary method not available")
        except Exception as e:
            logger.debug(f"get_nutrition_summary failed: {e}")
        
        # Try Method 2: Daily summary which sometimes includes nutrition
        try:
            summary = self.client.get_user_summary(date)
            if summary and 'consumedCalories' in summary:
                nutrition_data.update({
                    'date': date,
                    'calories_consumed': summary.get('consumedCalories', 0),
                    'calories_goal': summary.get('netCalorieGoal', 0)
                })
                logger.debug("Basic nutrition data from user summary")
        except Exception as e:
            logger.debug(f"User summary nutrition failed: {e}")
        
        # Try Method 3: Stats endpoint
        try:
            stats = self.client.get_stats(date)
            if stats:
                if 'consumedCalories' in stats:
                    nutrition_data['calories_consumed'] = stats.get('consumedCalories', 0)
                if 'netCalorieGoal' in stats:
                    nutrition_data['calories_goal'] = stats.get('netCalorieGoal', 0)
                logger.debug("Nutrition data from stats endpoint")
        except Exception as e:
            logger.debug(f"Stats endpoint nutrition failed: {e}")
        
        return nutrition_data if nutrition_data else {}
    
    def get_food_log(self, date: Optional[str] = None) -> List[Dict]:
        """
        Get detailed food log entries for a specific date.
        This retrieves individual meals/snacks logged in Garmin.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            List of food entries with nutrition details
        """
        self._ensure_authenticated()
        self._ensure_display_name()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        try:
            # Try to get food log - this may be a newer API endpoint
            food_log = self.client.get_food_log(date)
            if food_log and isinstance(food_log, list):
                return food_log
            return []
        except AttributeError:
            logger.debug("get_food_log method not available in this version")
            return []
        except Exception as e:
            logger.debug(f"Food log not available: {e}")
            return []
    
    def get_spo2_data(self, date: Optional[str] = None) -> Dict:
        """
        Get blood oxygen (SpO2/Pulse Ox) data.
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing SpO2 percentages
        """
        self._ensure_authenticated()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_spo2_data(date) or {}
        except AttributeError:
            logger.debug("SpO2 API not available")
            return {}
        except Exception as e:
            logger.debug(f"SpO2 data not available: {e}")
            return {}
    
    def get_max_metrics(self) -> Dict:
        """
        Get max performance metrics (VO2 Max, lactate threshold, etc).
        
        Returns:
            Dictionary containing max performance metrics
        """
        self._ensure_authenticated()
        try:
            return self.client.get_max_metrics() or {}
        except AttributeError:
            logger.debug("Max metrics API not available")
            return {}
        except Exception as e:
            logger.debug(f"Max metrics not available: {e}")
            return {}
    
    def get_training_status(self) -> Dict:
        """
        Get training status and recommendations.
        
        Returns:
            Dictionary containing training load, status, and recommendations
        """
        self._ensure_authenticated()
        try:
            return self.client.get_training_status() or {}
        except AttributeError:
            logger.debug("Training status API not available")
            return {}
        except Exception as e:
            logger.debug(f"Training status not available: {e}")
            return {}
    
    def get_training_readiness(self, date: Optional[str] = None) -> Dict:
        """
        Get training readiness score (combines multiple metrics).
        
        Args:
            date: Date in YYYY-MM-DD format (defaults to today)
            
        Returns:
            Dictionary containing training readiness score and factors
        """
        self._ensure_authenticated()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_training_readiness(date) or {}
        except AttributeError:
            logger.debug("Training readiness API not available")
            return {}
        except Exception as e:
            logger.debug(f"Training readiness not available: {e}")
            return {}
    
    def get_hrv_data(self, date: Optional[str] = None) -> Dict:
        """
        Get Heart Rate Variability (HRV) data (with recent day fallback).
        """
        self._ensure_authenticated()
        from datetime import datetime, timedelta
        dates_to_try = [date] if date else [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
        
        for d in dates_to_try:
            try:
                data = self.client.get_hrv_data(d)
                if data and (data.get("hrvSummary") or data.get("hrvReadings") or data.get("lastNightAvg")):
                    data["_retrieved_date"] = d
                    return data
            except Exception as e:
                logger.debug(f"HRV data for {d} not available: {e}")
        return {}
    
    def get_all_day_stress(self, date: Optional[str] = None) -> List[Dict]:
        """
        Get all-day stress measurements (every few minutes).
        """
        self._ensure_authenticated()
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        try:
            return self.client.get_all_day_stress(date) or []
        except AttributeError:
            logger.debug("All-day stress API not available")
            return []
        except Exception as e:
            logger.debug(f"All-day stress not available: {e}")
            return []

    
    def format_data_for_context(self, data_type: str = "summary", activity_limit: int = 5) -> str:
        """
        Format Garmin data into a readable string for LLM context.
        """
        self._ensure_authenticated()
        
        context_parts = []
        today = datetime.now().strftime("%Y-%m-%d")
        
        if data_type in ["summary", "all", "comprehensive"]:
            # Get user summary
            summary = self.get_user_summary()
            if summary:
                context_parts.append(f"=== Daily Summary (Date: {today}) ===")
                if "totalSteps" in summary:
                    context_parts.append(f"Steps: {summary.get('totalSteps', 'N/A')}")
                if "totalKilocalories" in summary:
                    context_parts.append(f"Calories: {summary.get('totalKilocalories', 'N/A')}")
                if "activeKilocalories" in summary:
                    context_parts.append(f"Active Calories: {summary.get('activeKilocalories', 'N/A')}")
                if "restingHeartRate" in summary:
                    context_parts.append(f"Resting Heart Rate (RHR): {summary.get('restingHeartRate', 'N/A')} bpm")
                if "maxHeartRate" in summary:
                    context_parts.append(f"Max Heart Rate Today: {summary.get('maxHeartRate', 'N/A')} bpm")
                context_parts.append("")
        
        if data_type in ["activities", "all", "comprehensive"]:
            # Get recent activities with configurable limit
            activities = self.get_activities(activity_limit)
            if activities:
                context_parts.append(f"=== Recent Activities (Last {len(activities)}) ===")
                for i, activity in enumerate(activities, 1):
                    act_name = activity.get("activityName", "Unknown")
                    act_type = activity.get("activityType", {}).get("typeKey", "Unknown")
                    distance = activity.get("distance", 0) / 1000 if activity.get("distance") else 0  # Convert to km
                    duration = activity.get("duration", 0) / 60 if activity.get("duration") else 0  # Convert to minutes
                    calories = activity.get("calories", "N/A")
                    start_time = activity.get("startTimeLocal", "N/A")
                    avg_hr = activity.get("averageHR")
                    max_hr = activity.get("maxHR")
                    
                    context_parts.append(f"{i}. {act_name} ({act_type})")
                    context_parts.append(f"   Date: {start_time}")
                    if distance > 0:
                        context_parts.append(f"   Distance: {distance:.2f} km")
                    context_parts.append(f"   Duration: {duration:.1f} minutes")
                    if distance > 0 and duration > 0:
                        is_cycling = any(k in act_type.lower() or k in act_name.lower() for k in ['cyc', 'ride', 'biking', 'bike', 'cykel'])
                        if is_cycling:
                            speed_kmh = distance / (duration / 60)
                            context_parts.append(f"   Avg Speed: {speed_kmh:.1f} km/h")
                        else:
                            pace_sec = (duration * 60) / distance
                            pace_min = int(pace_sec // 60)
                            pace_rem_sec = int(pace_sec % 60)
                            context_parts.append(f"   Pace: {pace_min}:{pace_rem_sec:02d} /km")
                    if avg_hr:
                        context_parts.append(f"   Avg HR: {avg_hr} bpm (Max HR: {max_hr or 'N/A'} bpm)")
                    context_parts.append(f"   Calories: {calories}")
                    
                    if 'strength' in act_type.lower():
                        context_parts.append(f"   💪 Strength Training - detailed exercise data available")
                    
                    context_parts.append("")
        
        if data_type in ["sleep", "all", "comprehensive"]:
            # Get sleep data
            sleep = self.get_sleep_data()
            if sleep and "dailySleepDTO" in sleep:
                sleep_data = sleep["dailySleepDTO"]
                sleep_date = sleep.get("_retrieved_date") or sleep_data.get("calendarDate") or today
                context_parts.append(f"=== Sleep Data (Date: {sleep_date}) ===")
                sleep_seconds = sleep_data.get("sleepTimeSeconds", 0)
                sleep_hours = sleep_seconds / 3600 if sleep_seconds else 0
                context_parts.append(f"Total Sleep: {sleep_hours:.1f} hours")
                if "sleepScores" in sleep_data and "overall" in sleep_data.get("sleepScores", {}):
                    overall = sleep_data["sleepScores"]["overall"]
                    score = overall.get("value", "N/A")
                    qual = overall.get("qualifierKey", "")
                    context_parts.append(f"Sleep Score: {score} ({qual})")
                context_parts.append(f"Deep Sleep: {(sleep_data.get('deepSleepSeconds') or 0) / 3600:.1f} hours")
                context_parts.append(f"Light Sleep: {(sleep_data.get('lightSleepSeconds') or 0) / 3600:.1f} hours")
                context_parts.append(f"REM Sleep: {(sleep_data.get('remSleepSeconds') or 0) / 3600:.1f} hours")
                context_parts.append(f"Awake Time: {(sleep_data.get('awakeSleepSeconds') or 0) / 3600:.1f} hours")
                if sleep_data.get("averageSpO2Value"):
                    context_parts.append(f"Avg SpO2 during Sleep: {sleep_data.get('averageSpO2Value')}%")
                context_parts.append("")

        # Heart Rate Data
        if data_type in ["heart_rate", "hr", "all", "comprehensive"]:
            try:
                hr_data = self.get_heart_rate_data(today)
                if hr_data:
                    context_parts.append(f"=== Heart Rate Data (Date: {today}) ===")
                    if "restingHeartRate" in hr_data:
                        context_parts.append(f"Resting Heart Rate (RHR): {hr_data.get('restingHeartRate')} bpm")
                    if "maxHeartRate" in hr_data:
                        context_parts.append(f"Max Heart Rate Today: {hr_data.get('maxHeartRate')} bpm")
                    context_parts.append("")
            except Exception as e:
                logger.debug(f"Heart rate data error: {e}")
        
        # Body Battery data
        if data_type in ["body_battery", "comprehensive", "all"]:
            bb_data = self.get_body_battery()
            if bb_data and (bb_data.get('charged') or bb_data.get('highest') or bb_data.get('drained') or bb_data.get('current')):
                bb_date = bb_data.get('date', today)
                context_parts.append(f"=== Body Battery Data (Date: {bb_date}) ===")
                context_parts.append(f"Charged: +{bb_data.get('charged', 0)}")
                context_parts.append(f"Drained: -{bb_data.get('drained', 0)}")
                if bb_data.get('highest'):
                    context_parts.append(f"Highest: {bb_data.get('highest')}")
                if bb_data.get('lowest'):
                    context_parts.append(f"Lowest: {bb_data.get('lowest')}")
                if bb_data.get('current'):
                    context_parts.append(f"Current: {bb_data.get('current')}")
                context_parts.append("")
        
        # Stress data
        if data_type in ["stress", "comprehensive", "all"]:
            stress_data = self.get_stress_data()
            if stress_data and stress_data.get('average'):
                stress_date = stress_data.get('date', today)
                context_parts.append(f"=== Stress Levels Data (Date: {stress_date}) ===")
                context_parts.append(f"Average: {stress_data.get('average', 'N/A')}/100")
                context_parts.append(f"Max: {stress_data.get('max', 'N/A')}/100")
                context_parts.append(f"Rest Stress: {stress_data.get('rest', 'N/A')}")
                context_parts.append(f"Activity Stress: {stress_data.get('activity', 'N/A')}")
                context_parts.append(f"Low Stress Duration: {(stress_data.get('low_duration') or 0) / 60:.0f} min")
                context_parts.append(f"High Stress Duration: {(stress_data.get('high_duration') or 0) / 60:.0f} min")
                context_parts.append("")
        
        # Respiration data
        if data_type in ["respiration", "comprehensive"]:
            resp_data = self.get_respiration_data(today)
            if resp_data and resp_data.get('waking_avg'):
                context_parts.append("=== Respiration ===")
                context_parts.append(f"Waking Average: {resp_data.get('waking_avg', 'N/A')} breaths/min")
                context_parts.append(f"Sleeping Average: {resp_data.get('sleeping_avg', 'N/A')} breaths/min")
                context_parts.append("")
        
        # Hydration data
        if data_type in ["hydration", "nutrition", "comprehensive"]:
            hydration = self.get_hydration_data(today)
            if hydration:
                context_parts.append("=== Hydration ===")
                total_ml = hydration.get('valueInML') or 0
                context_parts.append(f"Water Intake: {total_ml} ml ({total_ml / 236.588:.1f} cups)")
                context_parts.append("")
        
        # Calories/Nutrition data
        if data_type in ["calories", "nutrition", "comprehensive", "all"]:
            # Get basic calorie data
            cal_data = self.get_calories_data(today)
            if cal_data and cal_data.get('total_burned'):
                context_parts.append("=== Calories ===")
                context_parts.append(f"Total Burned: {cal_data.get('total_burned', 'N/A')} kcal")
                context_parts.append(f"Active Burned: {cal_data.get('active_burned', 'N/A')} kcal")
                context_parts.append(f"BMR: {cal_data.get('bmr', 'N/A')} kcal")
                if cal_data.get('consumed'):
                    context_parts.append(f"Consumed: {cal_data.get('consumed', 'N/A')} kcal")
                    context_parts.append(f"Net: {cal_data.get('net', 'N/A')} kcal")
                context_parts.append("")
            
            # Get detailed nutrition data if available
            nutrition_data = self.get_nutrition_summary(today)
            if nutrition_data and nutrition_data.get('calories_consumed'):
                context_parts.append("=== Nutrition Details ===")
                context_parts.append(f"Calories Consumed: {nutrition_data.get('calories_consumed', 0)} kcal")
                if nutrition_data.get('protein_g'):
                    context_parts.append(f"Protein: {nutrition_data.get('protein_g', 0)}g")
                if nutrition_data.get('carbs_g'):
                    context_parts.append(f"Carbs: {nutrition_data.get('carbs_g', 0)}g")
                if nutrition_data.get('fat_g'):
                    context_parts.append(f"Fat: {nutrition_data.get('fat_g', 0)}g")
                if nutrition_data.get('fiber_g'):
                    context_parts.append(f"Fiber: {nutrition_data.get('fiber_g', 0)}g")
                if nutrition_data.get('sugar_g'):
                    context_parts.append(f"Sugar: {nutrition_data.get('sugar_g', 0)}g")
                context_parts.append("")
            
            # Get food log if available
            food_log = self.get_food_log(today)
            if food_log:
                context_parts.append("=== Food Log ===")
                context_parts.append(f"Number of meals logged: {len(food_log)}")
                for i, meal in enumerate(food_log[:5], 1):  # Show up to 5 meals
                    meal_name = meal.get('name', meal.get('foodName', 'Unknown'))
                    meal_calories = meal.get('calories', 0)
                    context_parts.append(f"{i}. {meal_name} - {meal_calories} kcal")
                context_parts.append("")
        
        # Floors data
        if data_type in ["floors", "comprehensive", "all"]:
            floors_data = self.get_floors_data(today)
            if floors_data and floors_data.get('floors_ascended'):
                context_parts.append("=== Floors Climbed ===")
                context_parts.append(f"Ascended: {floors_data.get('floors_ascended', 0)}")
                context_parts.append(f"Descended: {floors_data.get('floors_descended', 0)}")
                context_parts.append(f"Goal: {floors_data.get('floors_ascended_goal', 'N/A')}")
                context_parts.append("")
        
        # Intensity Minutes
        if data_type in ["intensity", "comprehensive", "all"]:
            intensity = self.get_intensity_minutes(today)
            if intensity:
                context_parts.append("=== Intensity Minutes ===")
                context_parts.append(f"Today Moderate: {intensity.get('moderate', 0)} min")
                context_parts.append(f"Today Vigorous: {intensity.get('vigorous', 0)} min")
                context_parts.append(f"Weekly Moderate: {intensity.get('weekly_moderate', 0)} min")
                context_parts.append(f"Weekly Vigorous: {intensity.get('weekly_vigorous', 0)} min")
                context_parts.append(f"Weekly Goal: {intensity.get('weekly_goal', 150)} min")
                context_parts.append("")
        
        # SpO2 data
        if data_type in ["spo2", "comprehensive"]:
            spo2 = self.get_spo2_data(today)
            if spo2:
                context_parts.append("=== Blood Oxygen (SpO2) ===")
                if 'latestSpO2Value' in spo2:
                    context_parts.append(f"Latest: {spo2.get('latestSpO2Value', 'N/A')}%")
                if 'lowestSpO2Value' in spo2:
                    context_parts.append(f"Lowest: {spo2.get('lowestSpO2Value', 'N/A')}%")
                if 'averageSpO2Value' in spo2:
                    context_parts.append(f"Average: {spo2.get('averageSpO2Value', 'N/A')}%")
                context_parts.append("")
        
        # HRV data
        if data_type in ["hrv", "comprehensive"]:
            hrv = self.get_hrv_data(today)
            if hrv:
                context_parts.append("=== Heart Rate Variability (HRV) ===")
                if 'lastNightAvg' in hrv:
                    context_parts.append(f"Last Night Average: {hrv.get('lastNightAvg', 'N/A')} ms")
                if 'weeklyAvg' in hrv:
                    context_parts.append(f"Weekly Average: {hrv.get('weeklyAvg', 'N/A')} ms")
                if 'status' in hrv:
                    context_parts.append(f"HRV Status: {hrv.get('status', 'N/A')}")
                if 'baseline' in hrv and isinstance(hrv['baseline'], dict):
                    low = hrv['baseline'].get('balancedLow')
                    high = hrv['baseline'].get('balancedUpper')
                    if low and high:
                        context_parts.append(f"Baseline Range: {low}-{high} ms")
                context_parts.append("")
        
        # Training metrics & readiness
        if data_type in ["training", "comprehensive"]:
            try:
                max_metrics = self.get_max_metrics()
                if max_metrics:
                    context_parts.append("=== Performance Metrics ===")
                    if 'vo2Max' in max_metrics:
                        context_parts.append(f"VO2 Max: {max_metrics.get('vo2Max', 'N/A')}")
                    if 'fitnessAge' in max_metrics:
                        context_parts.append(f"Fitness Age: {max_metrics.get('fitnessAge', 'N/A')}")
                    context_parts.append("")
            except Exception as e:
                logger.debug(f"Max metrics error: {e}")
            
            try:
                training = self.get_training_status()
                if training:
                    context_parts.append("=== Training Status ===")
                    if 'trainingLoad' in training:
                        context_parts.append(f"Load: {training.get('trainingLoad', 'N/A')}")
                    if 'loadFocus' in training:
                        context_parts.append(f"Focus: {training.get('loadFocus', 'N/A')}")
                    if 'trainingStatusKey' in training:
                        context_parts.append(f"Status: {training.get('trainingStatusKey', 'N/A')}")
                    context_parts.append("")
            except Exception as e:
                logger.debug(f"Training status error: {e}")

            try:
                readiness = self.get_training_readiness(today)
                if readiness:
                    context_parts.append("=== Training Readiness ===")
                    if 'score' in readiness:
                        context_parts.append(f"Readiness Score: {readiness.get('score')}")
                    if 'scoreClassification' in readiness:
                        context_parts.append(f"Classification: {readiness.get('scoreClassification')}")
                    context_parts.append("")
            except Exception as e:
                logger.debug(f"Training readiness error: {e}")
        
        # Strength Training detailed data
        if data_type == "strength":
            strength_activities = self.find_strength_training_activities(limit=activity_limit)
            
            if strength_activities:
                context_parts.append(f"=== Recent Strength Training ({len(strength_activities)} workouts) ===")
                context_parts.append("")
                
                for i, st_activity in enumerate(strength_activities, 1):
                    # Get detailed data for this strength workout
                    details = self.get_strength_training_details(st_activity['activity_id'])
                    
                    if 'error' not in details:
                        # Format the detailed workout
                        formatted = self.format_strength_training_for_display(details)
                        context_parts.append(formatted)
                        context_parts.append("")
                        context_parts.append("---")
                        context_parts.append("")
                    else:
                        # Fallback to basic info if details unavailable
                        context_parts.append(f"{i}. {st_activity['name']}")
                        context_parts.append(f"   Date: {st_activity['date']}")
                        context_parts.append(f"   Duration: {st_activity['duration_minutes']} minutes")
                        context_parts.append(f"   Calories: {st_activity['calories']}")
                        context_parts.append(f"   (Detailed exercise data not available)")
                        context_parts.append("")
            else:
                context_parts.append("=== Strength Training ===")
                context_parts.append("No strength training activities found in recent workouts.")
                context_parts.append("")
        
        # Body Composition & Weight (Withings / Garmin)
        try:
            from garmin_db import GarminDatabase
            db = GarminDatabase()
            body_comp = db.get_latest_body_composition()
            if body_comp and (body_comp.get('weight_kg') or body_comp.get('fat_ratio_pct')):
                context_parts.append(f"=== Body Composition & Weight (Source: {body_comp.get('source', 'Withings').title()}) ===")
                context_parts.append(f"Date: {body_comp.get('date')}")
                if body_comp.get('weight_kg'):
                    context_parts.append(f"Weight: {body_comp.get('weight_kg'):.1f} kg")
                if body_comp.get('fat_ratio_pct'):
                    context_parts.append(f"Body Fat: {body_comp.get('fat_ratio_pct'):.1f} %")
                if body_comp.get('muscle_mass_kg'):
                    context_parts.append(f"Muscle Mass: {body_comp.get('muscle_mass_kg'):.1f} kg")
                if body_comp.get('bone_mass_kg'):
                    context_parts.append(f"Bone Mass: {body_comp.get('bone_mass_kg'):.1f} kg")
                if body_comp.get('water_pct'):
                    context_parts.append(f"Body Water: {body_comp.get('water_pct'):.1f} %")
                context_parts.append("")
        except Exception as e:
            logger.debug(f"Body composition context error: {e}")

        return "\n".join(context_parts) if context_parts else "No data available"
