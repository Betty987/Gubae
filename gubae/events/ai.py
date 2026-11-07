"""Turn a pasted announcement (WhatsApp, email, flyer text) into a DRAFT event.

Why: organizers already write announcements for the group chat. Retyping
them into a form is the reason they'd never use Gubae. So they paste the
message they already wrote, Claude extracts the fields, and the admin
reviews the pre-filled form before saving. A human always confirms, so an
extraction mistake costs one correction, not a wrong event.

Design notes (interview material):
- STRUCTURED OUTPUT: we give the API a JSON schema, so the reply is always
  valid JSON in exactly our shape. No regex-parsing free text.
- The model only EXTRACTS. Our own code (serializers) still validates
  everything before anything touches the database.
- Today's date + time zone go in the prompt, so "this Sunday at 2pm"
  resolves to a real date.
- The pasted text is untrusted input. It's sent as data in the user turn,
  never mixed into our instructions, and the output is only a draft.
"""
import json
from datetime import datetime, timedelta

import anthropic
from django.conf import settings
from django.utils import timezone

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You extract event details from community announcements \
(church, mahber, student association), often written for WhatsApp. Messages may \
mix English with Amharic or Tigrinya, and may use emoji or informal phrasing.

Extract exactly one event: the main one being announced. Rules:
- Resolve relative dates ("this Sunday", "tomorrow", "next week Saturday") using \
the current date and time zone given in the request. Dates in the past are \
almost certainly meant for the next occurrence.
- Times are local wall-clock times in the given time zone. Return them as \
"YYYY-MM-DDTHH:MM" with no offset.
- If no end time is stated, set ends_at to null; don't guess.
- If no start time is stated but a date is, set starts_at to null and list \
"start time" in missing.
- capacity: only if the message states a limit ("only 40 seats", "max 25 people"). \
Otherwise null.
- volunteer_slots: concrete tasks people are asked to help with ("bring injera", \
"help set up chairs", "make coffee"), each with how many people are needed. If a \
count isn't stated, use 1 for a single task-holder or 3 for "volunteers needed".
- title: short and clear, like a calendar entry ("Timket Celebration"), not the \
first line of the message.
- description: 1-3 plain sentences with the useful details (what to bring, dress \
code, who it's for). Leave out greetings and the date/location already captured.
- missing: human-readable names of important things the message doesn't say \
(e.g. "location", "start time"). Empty list if nothing important is missing."""

# The exact JSON shape the model must return. additionalProperties: false +
# every field required = the response can't contain surprises.
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "location": {"type": "string"},
        "starts_at": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "ends_at": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "capacity": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "volunteer_slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "spots_needed": {"type": "integer"},
                },
                "required": ["title", "spots_needed"],
                "additionalProperties": False,
            },
        },
        "missing": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "description", "location", "starts_at", "ends_at",
                 "capacity", "volunteer_slots", "missing"],
    "additionalProperties": False,
}


class DraftError(Exception):
    """Raised with a message that's safe to show the user."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _client():
    # Separate function so tests can replace it with a fake.
    return anthropic.Anthropic()


def _parse_local(value):
    """'2027-01-19T10:00' (local wall time) -> aware datetime, or None."""
    if not value:
        return None
    try:
        naive = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_aware(naive):
        return naive
    return timezone.make_aware(naive)  # uses settings.TIME_ZONE


def draft_event_from_text(text: str, community_name: str) -> dict:
    now = timezone.localtime()
    request_text = (
        f"Current date and time: {now:%A, %B %-d, %Y %-I:%M %p} ({settings.TIME_ZONE}).\n"
        f"Community: {community_name}\n\n"
        f"Announcement:\n<announcement>\n{text}\n</announcement>"
    )

    try:
        response = _client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": request_text}],
            # Extraction is a simple task: low effort = faster and cheaper.
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": DRAFT_SCHEMA},
            },
            # If a safety filter declines, retry on Anthropic's recommended
            # fallback model automatically instead of failing.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except TypeError as exc:
        # The SDK raises TypeError when no API key / credentials are configured.
        raise DraftError("AI drafting isn't set up yet (no ANTHROPIC_API_KEY on the server).", 503) from exc
    except anthropic.RateLimitError as exc:
        raise DraftError("The AI service is busy. Try again in a minute.", 503) from exc
    except anthropic.APIConnectionError as exc:
        raise DraftError("Couldn't reach the AI service. Check the server's internet connection.", 503) from exc
    except anthropic.APIStatusError as exc:
        raise DraftError("The AI service returned an error. Fill the form in manually for now.") from exc

    if response.stop_reason == "refusal":
        raise DraftError("The AI couldn't process that message. Fill the form in manually.", 422)
    if response.stop_reason == "max_tokens":
        raise DraftError("That message was too long to process. Try pasting just the announcement.", 422)

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise DraftError("The AI returned no result. Fill the form in manually.")
    data = json.loads(text_block.text)

    # Post-process in OUR code: turn local times into real datetimes and
    # apply sensible defaults the model was told not to guess.
    starts = _parse_local(data["starts_at"])
    ends = _parse_local(data["ends_at"])
    missing = list(data["missing"])
    if starts and (not ends or ends <= starts):
        ends = starts + timedelta(hours=2)
        if "end time" not in [m.lower() for m in missing]:
            missing.append("end time (assumed 2 hours)")
    if starts and starts < timezone.now():
        missing.append("date looks like it's in the past")

    return {
        "title": data["title"][:200],
        "description": data["description"],
        "location": data["location"][:255],
        "starts_at": starts.isoformat() if starts else None,
        "ends_at": ends.isoformat() if ends else None,
        "capacity": data["capacity"] if data["capacity"] and data["capacity"] > 0 else None,
        "volunteer_slots": [
            {"title": s["title"][:120], "spots_needed": max(1, s["spots_needed"])}
            for s in data["volunteer_slots"]
            if s["title"].strip()
        ],
        "missing": missing,
    }
