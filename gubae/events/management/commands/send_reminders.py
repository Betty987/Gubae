"""python manage.py send_reminders

Emails everyone who RSVP'd "going" to an event starting in the next 24 hours.

Run it on a schedule (e.g. every hour with cron, or Celery Beat later).
It is IDEMPOTENT: running it twice never sends a duplicate, because each
RSVP is stamped with reminded_at after its email goes out.

Design note: we stamp AFTER sending. If the job crashes between sending
and stamping, that person might get a second email next run ("at-least-once"
delivery). Stamping BEFORE sending risks nobody getting it ("at-most-once").
For reminders, a rare duplicate beats a missed reminder.
"""
from datetime import timedelta

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import RSVP


class Command(BaseCommand):
    help = "Email reminders for events starting within the next 24 hours."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Look-ahead window in hours.")

    def handle(self, *args, **options):
        now = timezone.now()
        window_end = now + timedelta(hours=options["hours"])
        due = (
            RSVP.objects.select_related("user", "event", "event__community")
            .filter(
                status=RSVP.Status.GOING,
                reminded_at__isnull=True,
                event__starts_at__gt=now,
                event__starts_at__lte=window_end,
            )
            .exclude(user__email="")
        )

        sent = 0
        for rsvp in due:
            event = rsvp.event
            when = timezone.localtime(event.starts_at).strftime("%A %b %-d at %-I:%M %p")
            send_mail(
                subject=f"Reminder: {event.title} is coming up",
                message=(
                    f"Hi {rsvp.user.first_name or rsvp.user.username},\n\n"
                    f"See you at {event.title} ({event.community.name}) on {when}"
                    f"{' at ' + event.location if event.location else ''}.\n\n- Gubae"
                ),
                from_email=None,  # uses DEFAULT_FROM_EMAIL
                recipient_list=[rsvp.user.email],
            )
            rsvp.reminded_at = timezone.now()
            rsvp.save(update_fields=["reminded_at"])  # only write this one column
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} reminder(s)."))
