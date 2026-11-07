"""Tests for the "reach people outside the site" features:
AI drafting, new-event emails, and calendar feeds.

The AI tests never call the real API (no cost, no network, no key needed):
we swap events.ai._client for a fake that returns a canned response. That's
called MOCKING. It lets us test OUR logic (validation, defaults, errors)
without depending on an outside service.
"""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.utils import timezone

from .models import Event, Membership, VolunteerSlot
from .tests import GubaeTestCase


class FakeClient:
    """Pretends to be anthropic.Anthropic(). Records the request it got."""

    def __init__(self, payload=None, stop_reason="end_turn", error=None):
        self.payload, self.stop_reason, self.error, self.kwargs = payload, stop_reason, error, None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        content = [SimpleNamespace(type="text", text=json.dumps(self.payload))] if self.payload else []
        return SimpleNamespace(stop_reason=self.stop_reason, content=content)


def draft_payload(**overrides):
    start = timezone.localtime() + timedelta(days=10)
    data = {
        "title": "Timket Celebration",
        "description": "Wear white. Kids' program after the service.",
        "location": "Church hall",
        "starts_at": start.strftime("%Y-%m-%dT10:00"),
        "ends_at": None,
        "capacity": None,
        "volunteer_slots": [{"title": "Bring injera", "spots_needed": 6}],
        "missing": [],
    }
    data.update(overrides)
    return data


ANNOUNCEMENT = "Selam all! Timket celebration 10am at the church hall, please bring injera (need 6 people) 🙏"


class AIDraftTests(GubaeTestCase):
    def post(self, user, text=ANNOUNCEMENT):
        self.client.force_authenticate(user)
        return self.client.post("/api/events/draft/", {"community": "st-mary", "text": text}, format="json")

    def test_admin_gets_draft_with_defaults_applied(self):
        fake = FakeClient(draft_payload())
        with patch("events.ai._client", return_value=fake):
            r = self.post(self.admin)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["title"], "Timket Celebration")
        self.assertEqual(r.data["volunteer_slots"], [{"title": "Bring injera", "spots_needed": 6}])
        # No end time given -> our code assumes 2 hours and says so
        starts = timezone.datetime.fromisoformat(r.data["starts_at"])
        ends = timezone.datetime.fromisoformat(r.data["ends_at"])
        self.assertEqual(ends - starts, timedelta(hours=2))
        self.assertTrue(any("end time" in m for m in r.data["missing"]))
        # Nothing was saved: it's only a draft
        self.assertEqual(Event.objects.count(), 0)

    def test_request_uses_structured_output_and_fallback(self):
        fake = FakeClient(draft_payload())
        with patch("events.ai._client", return_value=fake):
            self.post(self.admin)
        self.assertEqual(fake.kwargs["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(fake.kwargs["fallbacks"], "default")
        # The announcement is sent as data, wrapped in tags, plus today's date
        content = fake.kwargs["messages"][0]["content"]
        self.assertIn("<announcement>", content)
        self.assertIn("Current date", content)

    def test_member_cannot_draft(self):
        with patch("events.ai._client", return_value=FakeClient(draft_payload())):
            self.assertEqual(self.post(self.member).status_code, 403)

    def test_missing_start_time_is_reported(self):
        payload = draft_payload(starts_at=None, missing=["start time"])
        with patch("events.ai._client", return_value=FakeClient(payload)):
            r = self.post(self.admin)
        self.assertIsNone(r.data["starts_at"])
        self.assertIn("start time", r.data["missing"])

    def test_refusal_is_a_clean_error(self):
        with patch("events.ai._client", return_value=FakeClient(stop_reason="refusal")):
            r = self.post(self.admin)
        self.assertEqual(r.status_code, 422)

    def test_no_api_key_is_a_clean_error(self):
        with patch("events.ai._client", return_value=FakeClient(error=TypeError("no auth"))):
            r = self.post(self.admin)
        self.assertEqual(r.status_code, 503)
        self.assertIn("ANTHROPIC_API_KEY", r.data["detail"])

    def test_empty_text_rejected(self):
        self.assertEqual(self.post(self.admin, text="   ").status_code, 400)


class NewEventEmailTests(GubaeTestCase):
    def create_event(self, **extra):
        start = timezone.now() + timedelta(days=5)
        payload = {"community": "st-mary", "title": "Timket", "starts_at": start.isoformat(),
                   "ends_at": (start + timedelta(hours=3)).isoformat(), **extra}
        self.client.force_authenticate(self.admin)
        # on_commit callbacks don't run inside test transactions unless we ask:
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/events/", payload, format="json")

    def test_members_emailed_but_not_creator(self):
        r = self.create_event()
        self.assertEqual(r.status_code, 201)
        self.assertEqual([m.to for m in mail.outbox], [["member@example.com"]])
        self.assertIn("Timket", mail.outbox[0].subject)
        self.assertIn(f"/events/{r.data['id']}", mail.outbox[0].body)

    def test_opted_out_members_not_emailed(self):
        self.client.force_authenticate(self.member)
        r = self.client.patch("/api/communities/st-mary/membership/", {"notify_new_events": False}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.client.get("/api/communities/st-mary/").data["notify_new_events"])
        self.create_event()
        self.assertEqual(len(mail.outbox), 0)

    def test_event_created_with_volunteer_slots_in_one_request(self):
        r = self.create_event(new_volunteer_slots=[{"title": "Bring injera", "spots_needed": 6},
                                                   {"title": "Set up chairs", "spots_needed": 4}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([s["title"] for s in r.data["volunteer_slots"]], ["Bring injera", "Set up chairs"])
        self.assertIn("Bring injera", mail.outbox[0].body)

    def test_failed_create_sends_nothing(self):
        r = self.create_event(ends_at=(timezone.now() - timedelta(days=1)).isoformat())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)


class CalendarFeedTests(GubaeTestCase):
    def test_community_feed(self):
        self.make_event(title="Genna, Christmas; feast", location="Hall A")
        old = self.make_event(title="Ancient")
        Event.objects.filter(pk=old.pk).update(
            starts_at=timezone.now() - timedelta(days=90), ends_at=timezone.now() - timedelta(days=89))

        r = self.client.get("/api/communities/st-mary/calendar.ics")  # no login needed
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/calendar"))
        body = r.content.decode()
        self.assertTrue(body.startswith("BEGIN:VCALENDAR\r\n"))
        self.assertIn("SUMMARY:Genna\\, Christmas\\; feast", body)  # special chars escaped
        self.assertNotIn("Ancient", body)  # older than 30 days -> left out
        self.assertEqual(body.count("BEGIN:VEVENT"), 1)
        for line in body.split("\r\n"):
            self.assertLessEqual(len(line.encode()), 75)  # RFC 5545 line length

    def test_long_descriptions_fold_and_survive(self):
        self.make_event(description="ቡና " * 60)  # Amharic: multi-byte UTF-8
        body = self.client.get("/api/communities/st-mary/calendar.ics").content.decode()
        unfolded = body.replace("\r\n ", "")
        self.assertIn("ቡና ቡና ቡና", unfolded)

    def test_single_event_download(self):
        event = self.make_event()
        r = self.client.get(f"/api/events/{event.id}/calendar.ics")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"UID:event-{event.id}@gubae", r.content.decode())
        self.assertIn("attachment", r["Content-Disposition"])

    def test_unknown_community_404(self):
        self.assertEqual(self.client.get("/api/communities/nope/calendar.ics").status_code, 404)


class MembershipSettingsTests(GubaeTestCase):
    def test_non_member_cannot_patch(self):
        self.client.force_authenticate(self.outsider)
        r = self.client.patch("/api/communities/st-mary/membership/", {"notify_new_events": False}, format="json")
        self.assertEqual(r.status_code, 404)

    def test_default_is_on(self):
        self.assertTrue(Membership.objects.get(user=self.member).notify_new_events)
        self.assertEqual(VolunteerSlot.objects.count(), 0)
