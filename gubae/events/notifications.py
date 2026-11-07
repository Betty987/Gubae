"""Getting the word out WITHOUT anyone opening the site.

1. Email every member when a new event is posted (they can opt out per community).
2. iCalendar (.ics) feeds: a member adds their community's calendar to their
   phone ONCE; the calendar app re-downloads the feed on its own schedule, so
   new events appear by themselves.
"""
from datetime import UTC, timedelta

from django.conf import settings
from django.core.mail import send_mass_mail
from django.utils import timezone

from .models import Event, Membership


# ---------------------------------------------------------------------------
# New-event email
# ---------------------------------------------------------------------------


def notify_new_event(event_id: int) -> int:
    """Email members of the event's community. Returns how many were sent.

    Called via transaction.on_commit(), i.e. only after the event is really
    saved. If the save rolled back, nobody gets an email about a ghost event.

    Scale note: this runs inside the request. Fine for a church of 300; for
    thousands of members you'd hand it to a background queue (Celery + Redis)
    so the admin isn't waiting for emails to send.
    """
    event = Event.objects.select_related("community", "created_by").get(pk=event_id)
    recipients = (
        Membership.objects.filter(community=event.community, notify_new_events=True)
        .exclude(user=event.created_by)
        .exclude(user__email="")
        .select_related("user")
    )
    when = timezone.localtime(event.starts_at).strftime("%A, %B %-d at %-I:%M %p")
    link = f"{settings.FRONTEND_URL}/events/{event.id}"
    slots = list(event.volunteer_slots.all())

    messages = []
    for m in recipients:
        lines = [
            f"Hi {m.user.first_name or m.user.username},",
            "",
            f"{event.community.name} just posted a new event:",
            "",
            f"  {event.title}",
            f"  {when}",
        ]
        if event.location:
            lines.append(f"  {event.location}")
        if event.description:
            lines += ["", event.description]
        if slots:
            lines += ["", "Volunteers needed: " + ", ".join(s.title for s in slots)]
        lines += [
            "",
            f"RSVP: {link}",
            "",
            f"(Turn these emails off on the Communities page: {settings.FRONTEND_URL}/communities)",
        ]
        messages.append((f"New event: {event.title}", "\n".join(lines), None, [m.user.email]))

    # send_mass_mail opens ONE connection to the mail server for all messages.
    send_mass_mail(messages, fail_silently=True)
    return len(messages)


# ---------------------------------------------------------------------------
# iCalendar feeds (RFC 5545)
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    # In .ics files, these characters have special meaning and must be escaped.
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """The spec says lines must be at most 75 bytes; longer ones continue on
    the next line starting with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(current) + len(b) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += b
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(dt) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build_ics(events, calendar_name: str) -> str:
    now = _utc(timezone.now())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gubae//Community Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(calendar_name)}",
        # Hint to calendar apps: check for updates every hour.
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for e in events:
        description = e.description
        link = f"{settings.FRONTEND_URL}/events/{e.id}"
        description = f"{description}\n\nRSVP: {link}" if description else f"RSVP: {link}"
        lines += [
            "BEGIN:VEVENT",
            # Stable UID: when an event is edited, calendars UPDATE it instead
            # of adding a duplicate.
            f"UID:event-{e.id}@gubae",
            f"DTSTAMP:{now}",
            f"DTSTART:{_utc(e.starts_at)}",
            f"DTEND:{_utc(e.ends_at)}",
            f"SUMMARY:{_escape(e.title)}",
            f"DESCRIPTION:{_escape(description)}",
            f"URL:{link}",
        ]
        if e.location:
            lines.append(f"LOCATION:{_escape(e.location)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def feed_events(community):
    """Upcoming events plus the last 30 days, so recent ones don't vanish."""
    since = timezone.now() - timedelta(days=30)
    return community.events.filter(starts_at__gte=since).order_by("starts_at")
