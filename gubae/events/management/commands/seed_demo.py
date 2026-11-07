"""python manage.py seed_demo

Fills the database with realistic demo data so anyone (a recruiter, an
interviewer, you on a fresh laptop) can try the app in 30 seconds.
Safe to run repeatedly: get_or_create never duplicates rows.

Demo logins (password for all: gubae-demo-2026)
  demo_admin   - admin of St Mary + Habesha Students Association
  demo_member  - member of St Mary
"""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from events.models import RSVP, Community, Event, Membership, VolunteerSignup, VolunteerSlot

PASSWORD = "gubae-demo-2026"
User = get_user_model()


def at(days_from_now, hour, minute=0):
    """A timezone-aware datetime N days from today at a local (New York) time."""
    day = timezone.localdate() + timedelta(days=days_from_now)
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


def next_annual(month, day, hour, minute=0):
    """The next upcoming occurrence of a fixed-date holiday, e.g. Genna = Jan 7.

    Note: in the Gregorian year before a leap year, the Ethiopian calendar
    adds a 6th day of Pagume, which moves Timket to Jan 20 (and Genna is then
    observed on Tahsas 28 to stay on Jan 7). A proper Ethiopian-calendar
    converter would handle that; for demo data, the usual dates are enough.
    """
    today = timezone.localdate()
    year = today.year if (today.month, today.day) <= (month, day) else today.year + 1
    return timezone.make_aware(datetime(year, month, day, hour, minute))


class Command(BaseCommand):
    help = "Create demo communities, users, events, RSVPs and volunteer slots."

    @transaction.atomic
    def handle(self, *args, **options):
        admin = self.user("demo_admin", "Selam", "Bekele", "selam@example.com")
        member = self.user("demo_member", "Dawit", "Haile", "dawit@example.com")

        st_mary, _ = Community.objects.get_or_create(
            slug="st-mary-ethiopian-church-nyc",
            defaults={"name": "St Mary Ethiopian Church NYC",
                      "description": "Ethiopian Orthodox Tewahedo church community in New York."},
        )
        students, _ = Community.objects.get_or_create(
            slug="habesha-students-association",
            defaults={"name": "Habesha Students Association",
                      "description": "Ethiopian & Eritrean students across NYC universities."},
        )
        for community, user, role in [
            (st_mary, admin, Membership.Role.ADMIN),
            (students, admin, Membership.Role.ADMIN),
            (st_mary, member, Membership.Role.MEMBER),
        ]:
            Membership.objects.get_or_create(community=community, user=user, defaults={"role": role})

        events = [
            (st_mary, "Sunday Coffee Ceremony & Fellowship", "Buna after liturgy. Everyone welcome.",
             "Church hall", at(1, 12), at(1, 14), 40,
             [("Roast coffee", 2), ("Bring snacks (dabo, kolo)", 4)]),
            # Real holiday dates, not "N days from now".
            (st_mary, "Genna (Ethiopian Christmas) Celebration",
             "Feast and fellowship after the night liturgy. Kids' program included.",
             "Main sanctuary", next_annual(1, 7, 12), next_annual(1, 7, 17), 150,
             [("Bring injera", 6), ("Set up chairs", 5), ("Kids' program helpers", 3)]),
            (st_mary, "Timket (Epiphany) Celebration",
             "Procession and blessing of the water. Wear white.",
             "Church grounds", next_annual(1, 19, 9), next_annual(1, 19, 14), None,
             [("Carry the procession banners", 4), ("Serve food after the blessing", 6)]),
            (st_mary, "Youth Bible Study", "Weekly study for ages 16-30.",
             "Room 2", at(4, 19), at(4, 21), 20, []),
            (students, "Habesha Night Planning Meeting", "Plan the spring cultural show.",
             "Fordham Lincoln Center, Room 410", at(6, 18), at(6, 20), 25,
             [("Take meeting notes", 1)]),
        ]
        for community, title, desc, loc, starts, ends, cap, slots in events:
            # update_or_create (not get_or_create): re-running the seed also
            # FIXES demo events that already exist, e.g. a wrong date.
            event, _ = Event.objects.update_or_create(
                community=community, title=title,
                defaults={"description": desc, "location": loc, "starts_at": starts,
                          "ends_at": ends, "capacity": cap, "created_by": admin},
            )
            for slot_title, spots in slots:
                VolunteerSlot.objects.get_or_create(event=event, title=slot_title, defaults={"spots_needed": spots})

        coffee = Event.objects.get(community=st_mary, title__startswith="Sunday Coffee")
        RSVP.objects.get_or_create(event=coffee, user=member, defaults={"status": RSVP.Status.GOING})
        RSVP.objects.get_or_create(event=coffee, user=admin, defaults={"status": RSVP.Status.GOING})
        VolunteerSignup.objects.get_or_create(slot=coffee.volunteer_slots.get(title="Roast coffee"), user=admin)

        self.stdout.write(self.style.SUCCESS(
            f"Demo data ready. Log in as demo_admin or demo_member (password: {PASSWORD})."
        ))

    def user(self, username, first, last, email):
        user, created = User.objects.get_or_create(
            username=username, defaults={"first_name": first, "last_name": last, "email": email}
        )
        if created:
            user.set_password(PASSWORD)  # hashes it
            user.save()
        return user
