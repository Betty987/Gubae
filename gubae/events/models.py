from django.conf import settings
from django.db import models
from django.db.models import F, Q

# The built-in Django User model ("auth.User"). Referencing it through
# settings means we could swap in a custom user model later.
User = settings.AUTH_USER_MODEL


class Community(models.Model):
    """A church, mahber, student association, etc."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)  # URL-friendly id, e.g. "st-mary-nyc"
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)  # set once, on create

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Join table: which user belongs to which community, and with what role."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)
    joined_at = models.DateTimeField(auto_now_add=True)
    # Email me when this community posts a new event. Per community, because
    # someone might want every St Mary email but not every student-group one.
    notify_new_events = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # A user can only join a given community once.
            models.UniqueConstraint(fields=["user", "community"], name="unique_membership"),
        ]

    def __str__(self):
        return f"{self.user} in {self.community} ({self.role})"


class Event(models.Model):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    capacity = models.PositiveIntegerField(null=True, blank=True)  # empty = unlimited
    # If the creator's account is deleted, keep the event and just blank this field.
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_events")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]  # default sort: soonest first
        constraints = [
            # The database refuses an event that ends before it starts.
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="event_ends_after_start",
                violation_error_message="An event must end after it starts.",
            ),
        ]
        indexes = [
            # Speeds up the most common query: "upcoming events for this community".
            models.Index(fields=["community", "starts_at"]),
        ]

    def __str__(self):
        return self.title


class RSVP(models.Model):
    class Status(models.TextChoices):
        GOING = "going", "Going"
        MAYBE = "maybe", "Maybe"
        NOT_GOING = "not_going", "Not going"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rsvps")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="rsvps")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GOING)
    created_at = models.DateTimeField(auto_now_add=True)
    # Set when the reminder email goes out, so the job never emails twice.
    reminded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # One RSVP per person per event (answer to question 2).
            models.UniqueConstraint(fields=["user", "event"], name="unique_rsvp"),
        ]

    def __str__(self):
        return f"{self.user} → {self.event} ({self.status})"


class VolunteerSlot(models.Model):
    """A job that needs people, e.g. "Bring injera" (5 people needed)."""

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="volunteer_slots")
    title = models.CharField(max_length=120)
    spots_needed = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.title} ({self.event})"


class VolunteerSignup(models.Model):
    slot = models.ForeignKey(VolunteerSlot, on_delete=models.CASCADE, related_name="signups")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="volunteer_signups")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["slot", "user"], name="unique_volunteer_signup"),
        ]

    def __str__(self):
        return f"{self.user} → {self.slot}"
