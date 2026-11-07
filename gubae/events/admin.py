from django.contrib import admin

from .models import RSVP, Community, Event, Membership, VolunteerSignup, VolunteerSlot


# "Inline" = edit related rows on the same page as the parent.
# E.g. add volunteer slots while you're editing the event.
class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0  # don't show empty blank rows by default


class VolunteerSlotInline(admin.TabularInline):
    model = VolunteerSlot
    extra = 1


class RSVPInline(admin.TabularInline):
    model = RSVP
    extra = 0


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "created_at"]       # columns in the list page
    search_fields = ["name"]                            # adds a search box
    prepopulated_fields = {"slug": ["name"]}            # auto-fills slug as you type the name
    inlines = [MembershipInline]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "community", "starts_at", "location", "capacity"]
    list_filter = ["community", "starts_at"]            # adds a filter sidebar
    search_fields = ["title", "location"]
    inlines = [VolunteerSlotInline, RSVPInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "community", "role", "joined_at"]
    list_filter = ["role", "community"]


@admin.register(RSVP)
class RSVPAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "status", "created_at"]
    list_filter = ["status"]


@admin.register(VolunteerSlot)
class VolunteerSlotAdmin(admin.ModelAdmin):
    list_display = ["title", "event", "spots_needed"]


@admin.register(VolunteerSignup)
class VolunteerSignupAdmin(admin.ModelAdmin):
    list_display = ["user", "slot", "created_at"]
