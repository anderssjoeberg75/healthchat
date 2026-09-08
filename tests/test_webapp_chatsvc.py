"""Tests for the chat context builder ported from HealthChatApp._process_message."""

import os
import tempfile
from datetime import datetime

os.environ.setdefault("HEALTHCHAT_DATA_DIR", tempfile.mkdtemp(prefix="healthchat-test-"))

from webapp.backend import chatsvc  # noqa: E402


class FakeGarmin:
    """Records which slice of data the router asked for."""

    def __init__(self, activities=None):
        self.calls = []
        self.date_calls = []
        self._activities = activities or []

    def format_data_for_context(self, data_type="summary", activity_limit=None):
        self.calls.append((data_type, activity_limit))
        return f"CONTEXT:{data_type}:{activity_limit}"

    def get_activities_by_date(self, start, end):
        self.date_calls.append((start, end))
        return self._activities


def test_sleep_questions_ask_for_sleep_data():
    handler = FakeGarmin()

    chatsvc.build_garmin_context(handler, "Hur ser min sömn ut?")

    assert handler.calls == [("sleep", None)]


def test_coach_questions_ask_for_the_comprehensive_slice():
    handler = FakeGarmin()

    chatsvc.build_garmin_context(handler, "Analysera min träning som min PT")

    assert handler.calls == [("comprehensive", 15)]


def test_an_unclassified_question_falls_back_to_five_activities():
    handler = FakeGarmin()

    chatsvc.build_garmin_context(handler, "Vad tycker du?")

    assert handler.calls == [("comprehensive", 5)]


def test_show_all_activities_raises_the_limit():
    handler = FakeGarmin()

    chatsvc.build_garmin_context(handler, "show me more please")

    assert handler.calls == [("comprehensive", 30)]


def test_an_explicit_count_is_capped_at_fifty():
    handler = FakeGarmin()

    chatsvc.build_garmin_context(handler, "give me the last 200 sessions")

    assert handler.calls == [("comprehensive", 50)]


def test_a_date_range_question_queries_activities_by_date():
    handler = FakeGarmin(activities=[
        {"activityName": "Run", "activityType": {"typeKey": "running"}, "distance": 10000,
         "duration": 3600, "calories": 700, "startTimeLocal": "2026-01-02 07:00"},
    ])

    context = chatsvc.build_garmin_context(handler, "what did I do the last 7 days")

    assert handler.date_calls, "the date-range branch should have been taken"
    assert "1 activities" in context
    assert "Distance: 10.00 km" in context
    assert "Duration: 60.0 minutes" in context


def test_an_empty_date_range_says_so_instead_of_failing():
    handler = FakeGarmin(activities=[])

    context = chatsvc.build_garmin_context(handler, "how was last month")

    assert "No workouts or activities recorded during this period." in context


def test_a_failing_date_lookup_falls_back_to_the_keyword_router():
    class Failing(FakeGarmin):
        def get_activities_by_date(self, start, end):
            raise RuntimeError("Garmin unreachable")

    handler = Failing()

    context = chatsvc.build_garmin_context(handler, "last 3 weeks of training")

    assert context.startswith("CONTEXT:comprehensive")


def test_this_week_resolves_to_a_range_that_ends_today():
    handler = FakeGarmin(activities=[])

    chatsvc.build_garmin_context(handler, "how did this week go")

    start, end = handler.date_calls[0]
    assert end == datetime.now().strftime("%Y-%m-%d")
    assert start <= end
