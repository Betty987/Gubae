"""Run:  python manage.py test

Each test gets a fresh, empty test database (Django creates and destroys it),
so tests never touch your real db.sqlite3 and never depend on each other.
"""
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import RSVP, Community, Event, Membership, VolunteerSlot

User = get_user_model()


class GubaeTestCase(APITestCase):
    """Shared setup: one community with an admin, a member, and an outsider."""

    def setUp(self):
        cache.clear()  # reset rate-limit counters between tests
        self.community = Community.objects.create(name="St Mary", slug="st-mary")
        self.admin = User.objects.create_user("admin", "admin@example.com", "pw-12345678!")
        self.member = User.objects.create_user("member", "member@example.com", "pw-12345678!")
        self.outsider = User.objects.create_user("outsider", "out@example.com", "pw-12345678!")
        Membership.objects.create(user=self.admin, community=self.community, role=Membership.Role.ADMIN)
        Membership.objects.create(user=self.member, community=self.community, role=Membership.Role.MEMBER)

    def make_event(self, capacity=None, days=3, **kwargs):
        start = timezone.now() + timedelta(days=days)
        return Event.objects.create(
            community=self.community, title=kwargs.pop("title", "Genna"), starts_at=start,
            ends_at=start + timedelta(hours=3), capacity=capacity, created_by=self.admin, **kwargs,
        )

    def event_payload(self, **overrides):
        start = timezone.now() + timedelta(days=5)
        data = {"community": "st-mary", "title": "Timket", "starts_at": start.isoformat(),
                "ends_at": (start + timedelta(hours=4)).isoformat(), "capacity": 100}
        data.update(overrides)
        return data


class EventPermissionTests(GubaeTestCase):
    def test_anyone_can_list_events(self):
        self.make_event()
        r = self.client.get("/api/events/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["count"], 1)
        self.assertIsNone(r.data["results"][0]["my_rsvp"])
        self.assertFalse(r.data["results"][0]["can_manage"])

    def test_admin_can_create_event(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post("/api/events/", self.event_payload(), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data["can_manage"])
        self.assertEqual(Event.objects.get().created_by, self.admin)

    def test_member_cannot_create_event(self):
        self.client.force_authenticate(self.member)
        r = self.client.post("/api/events/", self.event_payload(), format="json")
        self.assertEqual(r.status_code, 403)

    def test_anonymous_cannot_create_event(self):
        r = self.client.post("/api/events/", self.event_payload(), format="json")
        self.assertEqual(r.status_code, 401)

    def test_member_cannot_edit_or_delete(self):
        event = self.make_event()
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.patch(f"/api/events/{event.id}/", {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"/api/events/{event.id}/").status_code, 403)

    def test_admin_can_edit(self):
        event = self.make_event()
        self.client.force_authenticate(self.admin)
        r = self.client.patch(f"/api/events/{event.id}/", {"location": "Hall B"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["location"], "Hall B")

    def test_admin_of_another_community_cannot_edit(self):
        other = Community.objects.create(name="Other", slug="other")
        Membership.objects.create(user=self.outsider, community=other, role=Membership.Role.ADMIN)
        event = self.make_event()
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.patch(f"/api/events/{event.id}/", {"title": "x"}, format="json").status_code, 403)


class EventValidationTests(GubaeTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def test_end_before_start_rejected(self):
        start = timezone.now() + timedelta(days=2)
        r = self.client.post("/api/events/", self.event_payload(
            starts_at=start.isoformat(), ends_at=(start - timedelta(hours=1)).isoformat()), format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("ends_at", r.data)

    def test_past_event_rejected(self):
        start = timezone.now() - timedelta(days=1)
        r = self.client.post("/api/events/", self.event_payload(
            starts_at=start.isoformat(), ends_at=(start + timedelta(hours=1)).isoformat()), format="json")
        self.assertEqual(r.status_code, 400)

    def test_capacity_cannot_drop_below_going(self):
        event = self.make_event(capacity=10)
        RSVP.objects.create(event=event, user=self.member)
        RSVP.objects.create(event=event, user=self.admin)
        r = self.client.patch(f"/api/events/{event.id}/", {"capacity": 1}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_upcoming_filter(self):
        self.make_event(title="Future", days=3)
        past = self.make_event(title="Past", days=3)
        Event.objects.filter(pk=past.pk).update(
            starts_at=timezone.now() - timedelta(days=2), ends_at=timezone.now() - timedelta(days=1))
        titles = [e["title"] for e in self.client.get("/api/events/?upcoming=true").data["results"]]
        self.assertEqual(titles, ["Future"])

    def test_events_sorted_soonest_first(self):
        self.make_event(title="Later", days=9)
        self.make_event(title="Sooner", days=2)
        self.make_event(title="Middle", days=5)
        titles = [e["title"] for e in self.client.get("/api/events/").data["results"]]
        self.assertEqual(titles, ["Sooner", "Middle", "Later"])

    def test_list_has_no_n_plus_one(self):
        """Query count must NOT grow with the number of events."""
        for i in range(10):
            e = self.make_event(title=f"E{i}")
            VolunteerSlot.objects.create(event=e, title="Bring injera", spots_needed=2)
        # auth lookup is skipped (force_authenticate), so: 1 COUNT for pagination,
        # 1 for events, 1 for all volunteer slots
        with self.assertNumQueries(3):
            r = self.client.get("/api/events/")
        self.assertEqual(len(r.data["results"]), 10)


class RSVPTests(GubaeTestCase):
    def test_member_can_rsvp_and_change_it(self):
        event = self.make_event()
        self.client.force_authenticate(self.member)
        r = self.client.post(f"/api/events/{event.id}/rsvp/", {"status": "going"}, format="json")
        self.assertEqual(r.status_code, 201)
        r = self.client.post(f"/api/events/{event.id}/rsvp/", {"status": "maybe"}, format="json")
        self.assertEqual(r.status_code, 200)  # updated, not duplicated
        self.assertEqual(RSVP.objects.filter(event=event).count(), 1)
        self.assertEqual(self.client.get(f"/api/events/{event.id}/").data["my_rsvp"], "maybe")

    def test_non_member_cannot_rsvp(self):
        event = self.make_event()
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json").status_code, 403)

    def test_capacity_enforced(self):
        event = self.make_event(capacity=1)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json").status_code, 201)
        self.client.force_authenticate(self.member)
        r = self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json")
        self.assertEqual(r.status_code, 409)
        # "maybe" doesn't take a spot, so it's still allowed
        r = self.client.post(f"/api/events/{event.id}/rsvp/", {"status": "maybe"}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_cancelling_frees_a_spot(self):
        event = self.make_event(capacity=1)
        self.client.force_authenticate(self.admin)
        self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json")
        self.assertEqual(self.client.delete(f"/api/events/{event.id}/rsvp/").status_code, 204)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json").status_code, 201)
        self.assertEqual(self.client.get(f"/api/events/{event.id}/").data["spots_left"], 0)

    def test_already_going_can_resubmit_going_when_full(self):
        event = self.make_event(capacity=1)
        self.client.force_authenticate(self.member)
        self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json")
        r = self.client.post(f"/api/events/{event.id}/rsvp/", {"status": "going"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_cannot_rsvp_to_started_event(self):
        event = self.make_event()
        Event.objects.filter(pk=event.pk).update(starts_at=timezone.now() - timedelta(minutes=5))
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(f"/api/events/{event.id}/rsvp/", {}, format="json").status_code, 400)

    def test_invalid_status_rejected(self):
        event = self.make_event()
        self.client.force_authenticate(self.member)
        r = self.client.post(f"/api/events/{event.id}/rsvp/", {"status": "definitely"}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_attendee_list_is_admin_only(self):
        event = self.make_event()
        RSVP.objects.create(event=event, user=self.member)
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(f"/api/events/{event.id}/attendees/").status_code, 403)
        self.client.force_authenticate(self.admin)
        r = self.client.get(f"/api/events/{event.id}/attendees/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[0]["username"], "member")


class VolunteerTests(GubaeTestCase):
    def setUp(self):
        super().setUp()
        self.event = self.make_event()
        self.slot = VolunteerSlot.objects.create(event=self.event, title="Bring injera", spots_needed=1)

    def test_signup_and_full(self):
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(f"/api/volunteer-slots/{self.slot.id}/signup/").status_code, 201)
        self.assertEqual(self.client.post(f"/api/volunteer-slots/{self.slot.id}/signup/").status_code, 200)  # idempotent
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f"/api/volunteer-slots/{self.slot.id}/signup/").status_code, 409)

    def test_signed_up_flag_and_counts(self):
        self.client.force_authenticate(self.member)
        self.client.post(f"/api/volunteer-slots/{self.slot.id}/signup/")
        slot = self.client.get(f"/api/events/{self.event.id}/").data["volunteer_slots"][0]
        self.assertEqual((slot["spots_filled"], slot["signed_up"]), (1, True))

    def test_non_member_cannot_volunteer(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post(f"/api/volunteer-slots/{self.slot.id}/signup/").status_code, 403)

    def test_only_admin_adds_slots(self):
        url = f"/api/events/{self.event.id}/volunteer-slots/"
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.post(url, {"title": "Chairs", "spots_needed": 3}, format="json").status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(url, {"title": "Chairs", "spots_needed": 3}, format="json").status_code, 201)


class CommunityTests(GubaeTestCase):
    def test_creator_becomes_admin(self):
        self.client.force_authenticate(self.outsider)
        r = self.client.post("/api/communities/", {"name": "Habesha Students", "slug": "habesha"}, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["my_role"], "admin")
        self.assertEqual(r.data["member_count"], 1)

    def test_join_is_idempotent_then_leave(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.post("/api/communities/st-mary/membership/").status_code, 201)
        self.assertEqual(self.client.post("/api/communities/st-mary/membership/").status_code, 200)
        self.assertEqual(self.client.get("/api/communities/st-mary/").data["my_role"], "member")
        self.assertEqual(self.client.delete("/api/communities/st-mary/membership/").status_code, 204)

    def test_last_admin_cannot_leave(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.delete("/api/communities/st-mary/membership/").status_code, 400)


class ReminderTests(GubaeTestCase):
    def test_reminders_sent_once(self):
        soon = self.make_event(title="Coffee ceremony")
        Event.objects.filter(pk=soon.pk).update(
            starts_at=timezone.now() + timedelta(hours=5), ends_at=timezone.now() + timedelta(hours=7))
        later = self.make_event(title="Far away", days=10)
        RSVP.objects.create(event=soon, user=self.member, status=RSVP.Status.GOING)
        RSVP.objects.create(event=soon, user=self.admin, status=RSVP.Status.MAYBE)  # maybe -> no email
        RSVP.objects.create(event=later, user=self.member)  # too far ahead -> no email

        call_command("send_reminders", stdout=StringIO())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["member@example.com"])
        self.assertIn("Coffee ceremony", mail.outbox[0].subject)

        call_command("send_reminders", stdout=StringIO())  # second run: nothing new
        self.assertEqual(len(mail.outbox), 1)


class SeedTests(GubaeTestCase):
    def test_seed_is_repeatable(self):
        call_command("seed_demo", stdout=StringIO())
        count = Event.objects.count()
        call_command("seed_demo", stdout=StringIO())
        self.assertEqual(Event.objects.count(), count)
