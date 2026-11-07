"""Views: receive a request, check permissions, query the database, respond.

Endpoint map
  GET    /api/communities/                    list (anyone)
  POST   /api/communities/                    create; creator becomes admin
  GET    /api/communities/<slug>/             detail
  POST   /api/communities/<slug>/membership/  join
  DELETE /api/communities/<slug>/membership/  leave
  GET    /api/events/?community=&upcoming=    list (anyone)
  POST   /api/events/                         create (community admins)
  GET    /api/events/<id>/                    detail
  PATCH  /api/events/<id>/                    edit (community admins)
  DELETE /api/events/<id>/                    delete (community admins)
  POST   /api/events/<id>/rsvp/               RSVP / change RSVP (members)
  DELETE /api/events/<id>/rsvp/               remove my RSVP
  GET    /api/events/<id>/attendees/          guest list (community admins)
  POST   /api/events/<id>/volunteer-slots/    add a slot (community admins)
  POST   /api/volunteer-slots/<id>/signup/    volunteer (members)
  DELETE /api/volunteer-slots/<id>/signup/    un-volunteer
  PATCH  /api/communities/<slug>/membership/  my email settings
  POST   /api/events/draft/                   AI: announcement text -> draft event (admins)
  GET    /api/communities/<slug>/calendar.ics subscribable calendar feed (public)
  GET    /api/events/<id>/calendar.ics        add one event to your calendar
"""
from django.db import transaction
from django.db.models import BooleanField, CharField, Count, Exists, OuterRef, Prefetch, Q, Subquery, Value
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .ai import DraftError, draft_event_from_text
from .models import RSVP, Community, Event, Membership, VolunteerSignup, VolunteerSlot
from .notifications import build_ics, feed_events, notify_new_event
from .permissions import IsCommunityAdminOrReadOnly, is_admin_of, is_member_of
from .serializers import (
    AttendeeSerializer,
    CommunitySerializer,
    DraftRequestSerializer,
    EventSerializer,
    MembershipSettingsSerializer,
    RSVPInputSerializer,
    RSVPSerializer,
    VolunteerSlotSerializer,
)

# ---------------------------------------------------------------------------
# Querysets: ONE place that knows how to load everything a response needs.
# ---------------------------------------------------------------------------


def community_queryset(user):
    qs = Community.objects.annotate(member_count=Count("memberships"))
    if user.is_authenticated:
        # Subquery = a small SELECT inside the big one: "my role in THIS community".
        mine = Membership.objects.filter(community=OuterRef("pk"), user=user)
        qs = qs.annotate(
            my_role=Subquery(mine.values("role")[:1]),
            notify_new_events=Subquery(mine.values("notify_new_events")[:1]),
        )
    else:
        qs = qs.annotate(
            my_role=Value(None, output_field=CharField()),
            notify_new_events=Value(None, output_field=BooleanField()),
        )
    return qs.order_by("name")


def event_queryset(user):
    """Avoiding the N+1 query problem.

    A naive version runs 1 query for the events, then 1 more PER event to
    count RSVPs, then 1 more PER slot to count signups: 100 events = 300+
    queries. Here the database does the counting (annotate = SQL GROUP BY /
    subqueries), so a page of events costs 3 queries no matter its size
    (page count + events + all their slots).
    """
    slots = VolunteerSlot.objects.annotate(spots_filled=Count("signups")).order_by("id")
    if user.is_authenticated:
        slots = slots.annotate(
            signed_up=Exists(VolunteerSignup.objects.filter(slot=OuterRef("pk"), user=user))
        )
    else:
        slots = slots.annotate(signed_up=Value(False, output_field=BooleanField()))

    qs = (
        Event.objects.select_related("community")  # SQL JOIN: community comes in the same query
        .annotate(going_count=Count("rsvps", filter=Q(rsvps__status=RSVP.Status.GOING)))
        .prefetch_related(Prefetch("volunteer_slots", queryset=slots))  # 1 query for ALL slots
        # Explicit order is required: Django ignores Meta.ordering on GROUP BY
        # queries (which Count() creates). "id" breaks ties so pages are stable.
        .order_by("starts_at", "id")
    )
    if user.is_authenticated:
        my_rsvp = RSVP.objects.filter(event=OuterRef("pk"), user=user).values("status")[:1]
        is_admin = Membership.objects.filter(
            community=OuterRef("community"), user=user, role=Membership.Role.ADMIN
        )
        qs = qs.annotate(my_rsvp=Subquery(my_rsvp), can_manage=Exists(is_admin))
    else:
        qs = qs.annotate(
            my_rsvp=Value(None, output_field=CharField()),
            can_manage=Value(False, output_field=BooleanField()),
        )
    return qs


# ---------------------------------------------------------------------------
# Communities
# ---------------------------------------------------------------------------


class CommunityListCreate(generics.ListCreateAPIView):
    serializer_class = CommunitySerializer

    def get_queryset(self):
        return community_queryset(self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # Transaction: the community and its first admin are saved together,
        # or not at all. No community can ever exist without an admin.
        with transaction.atomic():
            community = serializer.save()
            Membership.objects.create(user=request.user, community=community, role=Membership.Role.ADMIN)
        fresh = community_queryset(request.user).get(pk=community.pk)
        return Response(self.get_serializer(fresh).data, status=status.HTTP_201_CREATED)


class CommunityDetail(generics.RetrieveUpdateAPIView):
    serializer_class = CommunitySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsCommunityAdminOrReadOnly]
    lookup_field = "slug"

    def get_queryset(self):
        return community_queryset(self.request.user)


class CommunityMembership(APIView):
    """Join (POST) or leave (DELETE) a community."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        community = get_object_or_404(Community, slug=slug)
        membership, created = Membership.objects.get_or_create(user=request.user, community=community)
        # Idempotent: joining twice is not an error; it just returns your membership.
        return Response(
            {"community": community.slug, "role": membership.role},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, slug):
        community = get_object_or_404(Community, slug=slug)
        membership = get_object_or_404(Membership, user=request.user, community=community)
        if membership.role == Membership.Role.ADMIN:
            other_admins = community.memberships.filter(role=Membership.Role.ADMIN).exclude(pk=membership.pk)
            if not other_admins.exists():
                raise ValidationError("You're the only admin. Make someone else an admin before leaving.")
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, slug):
        membership = get_object_or_404(Membership, user=request.user, community__slug=slug)
        data = MembershipSettingsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        membership.notify_new_events = data.validated_data["notify_new_events"]
        membership.save(update_fields=["notify_new_events"])
        return Response({"community": slug, "notify_new_events": membership.notify_new_events})


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class EventListCreate(generics.ListCreateAPIView):
    serializer_class = EventSerializer

    def get_queryset(self):
        qs = event_queryset(self.request.user)
        community = self.request.query_params.get("community")
        if community:
            qs = qs.filter(community__slug=community)
        upcoming = self.request.query_params.get("upcoming")  # Beth's filter from Step 4
        if upcoming == "true":
            qs = qs.filter(starts_at__gte=timezone.now())
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        community = serializer.validated_data["community"]
        if not is_admin_of(request.user, community.id):
            raise PermissionDenied("Only admins of this community can create events.")
        with transaction.atomic():
            event = serializer.save(created_by=request.user)  # event + its slots, together
            # Email members, but only AFTER the transaction commits: if the
            # save fails and rolls back, nobody hears about a ghost event.
            transaction.on_commit(lambda: notify_new_event(event.id))
        fresh = event_queryset(request.user).get(pk=event.pk)
        return Response(self.get_serializer(fresh).data, status=status.HTTP_201_CREATED)


class EventDetail(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsCommunityAdminOrReadOnly]

    def get_queryset(self):
        return event_queryset(self.request.user)


class EventRSVP(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        data = RSVPInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        new_status = data.validated_data["status"]

        # THE RACE CONDITION FIX.
        # Two people click "Going" for the last spot at the same moment.
        # Without protection both read "49/50 taken", both insert, and 51 go.
        # select_for_update() LOCKS this event's row until the transaction
        # ends, so the second request waits, then re-counts and sees 50/50.
        # (Postgres enforces the lock. SQLite has no row locks, but it only
        # allows one writer at a time, which gives the same safety locally.)
        with transaction.atomic():
            event = get_object_or_404(Event.objects.select_for_update(), pk=pk)
            if not is_member_of(request.user, event.community_id):
                raise PermissionDenied("Join this community to RSVP.")
            if event.starts_at <= timezone.now():
                raise ValidationError("This event has already started.")

            existing = RSVP.objects.filter(event=event, user=request.user).first()
            becoming_going = new_status == RSVP.Status.GOING and (existing is None or existing.status != RSVP.Status.GOING)
            if becoming_going and event.capacity is not None:
                going = event.rsvps.filter(status=RSVP.Status.GOING).count()
                if going >= event.capacity:
                    return Response({"detail": "Sorry, this event is full."}, status=status.HTTP_409_CONFLICT)

            # update_or_create = an "upsert": change my RSVP if I have one, else make it.
            rsvp, created = RSVP.objects.update_or_create(
                event=event, user=request.user, defaults={"status": new_status}
            )
        return Response(RSVPSerializer(rsvp).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    def delete(self, request, pk):
        RSVP.objects.filter(event_id=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class EventAttendees(generics.ListAPIView):
    """Guest list. Admins only: members shouldn't see who else RSVP'd (privacy)."""

    serializer_class = AttendeeSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        event = get_object_or_404(Event, pk=self.kwargs["pk"])
        if not is_admin_of(self.request.user, event.community_id):
            raise PermissionDenied("Only admins of this community can see the guest list.")
        return event.rsvps.select_related("user").order_by("status", "created_at")


class EventVolunteerSlots(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        event = get_object_or_404(Event, pk=pk)
        if not is_admin_of(request.user, event.community_id):
            raise PermissionDenied("Only admins of this community can add volunteer slots.")
        serializer = VolunteerSlotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slot = serializer.save(event=event)
        return Response(
            {"id": slot.id, "title": slot.title, "spots_needed": slot.spots_needed, "spots_filled": 0, "signed_up": False},
            status=status.HTTP_201_CREATED,
        )


class VolunteerSignupView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        # Same locking pattern as RSVPs: the slot row is the thing with limited capacity.
        with transaction.atomic():
            slot = get_object_or_404(VolunteerSlot.objects.select_for_update().select_related("event"), pk=pk)
            if not is_member_of(request.user, slot.event.community_id):
                raise PermissionDenied("Join this community to volunteer.")
            if VolunteerSignup.objects.filter(slot=slot, user=request.user).exists():
                return Response({"detail": "You're already signed up."}, status=status.HTTP_200_OK)
            if slot.signups.count() >= slot.spots_needed:
                return Response({"detail": "This slot is already filled."}, status=status.HTTP_409_CONFLICT)
            VolunteerSignup.objects.create(slot=slot, user=request.user)
        return Response({"detail": "Thanks for volunteering!"}, status=status.HTTP_201_CREATED)

    def delete(self, request, pk):
        VolunteerSignup.objects.filter(slot_id=pk, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# AI drafting
# ---------------------------------------------------------------------------


class EventDraft(APIView):
    """POST {community, text} -> a draft event. NOTHING is saved here: the
    admin reviews the pre-filled form and saves it through POST /api/events/."""

    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "ai"  # each call costs money; 10/min per user

    def post(self, request):
        data = DraftRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        community = data.validated_data["community"]
        # Only admins can create events, so only admins may spend AI credits.
        if not is_admin_of(request.user, community.id):
            raise PermissionDenied("Only admins of this community can draft events.")
        try:
            draft = draft_event_from_text(data.validated_data["text"], community.name)
        except DraftError as exc:
            return Response({"detail": str(exc)}, status=exc.status)
        return Response({"community": community.slug, **draft})


# ---------------------------------------------------------------------------
# Calendar feeds. Plain Django views (not DRF): calendar apps want raw
# text/calendar, and they can't send a JWT, so these are public. That's fine
# because events are already publicly readable through the API.
# ---------------------------------------------------------------------------


def community_calendar(request, slug):
    community = get_object_or_404(Community, slug=slug)
    body = build_ics(feed_events(community), f"{community.name} (Gubae)")
    return HttpResponse(body, content_type="text/calendar; charset=utf-8")


def event_calendar(request, pk):
    event = get_object_or_404(Event, pk=pk)
    response = HttpResponse(build_ics([event], event.title), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="gubae-event-{event.id}.ics"'
    return response
