"""Serializers: convert model objects <-> JSON, and validate incoming JSON.

Fields marked read_only=True are computed by the view's query (annotations)
and can't be sent by the client. See views.py for how they're calculated.
"""
from django.utils import timezone
from rest_framework import serializers

from .models import RSVP, Community, Event, VolunteerSlot


class CommunitySerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True)
    my_role = serializers.CharField(read_only=True, allow_null=True)  # "admin" | "member" | null
    notify_new_events = serializers.BooleanField(read_only=True, allow_null=True)  # my email setting

    class Meta:
        model = Community
        fields = ["id", "name", "slug", "description", "member_count", "my_role", "notify_new_events"]


class VolunteerSlotSerializer(serializers.ModelSerializer):
    spots_filled = serializers.IntegerField(read_only=True)
    signed_up = serializers.BooleanField(read_only=True)  # did *I* sign up?

    class Meta:
        model = VolunteerSlot
        fields = ["id", "title", "spots_needed", "spots_filled", "signed_up"]
        read_only_fields = ["id"]


class VolunteerSlotInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    spots_needed = serializers.IntegerField(min_value=1, max_value=500)


class EventSerializer(serializers.ModelSerializer):
    # Writable on create: the client sends {"community": "st-mary-ethiopian-church-nyc"}.
    community = serializers.SlugRelatedField(slug_field="slug", queryset=Community.objects.all())
    community_name = serializers.CharField(source="community.name", read_only=True)
    volunteer_slots = VolunteerSlotSerializer(many=True, read_only=True)
    going_count = serializers.IntegerField(read_only=True)
    spots_left = serializers.SerializerMethodField()
    my_rsvp = serializers.CharField(read_only=True, allow_null=True)  # my status, or null
    can_manage = serializers.BooleanField(read_only=True)  # am I an admin of this community?
    # Write-only: lets the client create the event AND its volunteer slots in
    # one request (one transaction), e.g. from an AI-drafted announcement.
    new_volunteer_slots = VolunteerSlotInputSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = Event
        fields = [
            "id", "community", "community_name", "title", "description", "location",
            "starts_at", "ends_at", "capacity", "going_count", "spots_left",
            "my_rsvp", "can_manage", "volunteer_slots", "new_volunteer_slots",
        ]

    def create(self, validated_data):
        slots = validated_data.pop("new_volunteer_slots", [])
        event = super().create(validated_data)
        VolunteerSlot.objects.bulk_create(VolunteerSlot(event=event, **s) for s in slots)
        return event

    def update(self, instance, validated_data):
        slots = validated_data.pop("new_volunteer_slots", [])
        event = super().update(instance, validated_data)
        VolunteerSlot.objects.bulk_create(VolunteerSlot(event=event, **s) for s in slots)
        return event

    def get_spots_left(self, event):
        if event.capacity is None:
            return None  # unlimited
        return max(event.capacity - getattr(event, "going_count", 0), 0)

    def validate(self, attrs):
        """Cross-field rules. Runs after each field is validated on its own.

        On PATCH the client may send only some fields, so fall back to the
        existing values on self.instance.
        """
        instance = self.instance
        starts = attrs.get("starts_at", getattr(instance, "starts_at", None))
        ends = attrs.get("ends_at", getattr(instance, "ends_at", None))
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "An event must end after it starts."})

        if instance is None and starts and starts < timezone.now():
            raise serializers.ValidationError({"starts_at": "You can't create an event in the past."})

        if instance is not None:
            if "community" in attrs and attrs["community"] != instance.community:
                raise serializers.ValidationError({"community": "An event can't be moved to another community."})
            capacity = attrs.get("capacity", instance.capacity)
            going = getattr(instance, "going_count", 0)
            if capacity is not None and capacity < going:
                raise serializers.ValidationError(
                    {"capacity": f"{going} people are already going; capacity can't be lower than that."}
                )
        return attrs


class RSVPInputSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=RSVP.Status.choices, default=RSVP.Status.GOING)


class RSVPSerializer(serializers.ModelSerializer):
    class Meta:
        model = RSVP
        fields = ["event", "status", "created_at"]


class AttendeeSerializer(serializers.ModelSerializer):
    """What an admin sees on the guest list."""

    username = serializers.CharField(source="user.username")
    name = serializers.SerializerMethodField()

    class Meta:
        model = RSVP
        fields = ["username", "name", "status", "created_at"]

    def get_name(self, rsvp):
        return rsvp.user.get_full_name() or rsvp.user.username


class DraftRequestSerializer(serializers.Serializer):
    community = serializers.SlugRelatedField(slug_field="slug", queryset=Community.objects.all())
    text = serializers.CharField(max_length=5000, trim_whitespace=True)


class MembershipSettingsSerializer(serializers.Serializer):
    notify_new_events = serializers.BooleanField()
