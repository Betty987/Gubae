from django.urls import path

from . import views

urlpatterns = [
    path("communities/", views.CommunityListCreate.as_view(), name="community-list"),
    path("communities/<slug:slug>/", views.CommunityDetail.as_view(), name="community-detail"),
    path("communities/<slug:slug>/membership/", views.CommunityMembership.as_view(), name="community-membership"),
    path("communities/<slug:slug>/calendar.ics", views.community_calendar, name="community-calendar"),
    path("events/", views.EventListCreate.as_view(), name="event-list"),
    path("events/draft/", views.EventDraft.as_view(), name="event-draft"),
    path("events/<int:pk>/calendar.ics", views.event_calendar, name="event-calendar"),
    path("events/<int:pk>/", views.EventDetail.as_view(), name="event-detail"),
    path("events/<int:pk>/rsvp/", views.EventRSVP.as_view(), name="event-rsvp"),
    path("events/<int:pk>/attendees/", views.EventAttendees.as_view(), name="event-attendees"),
    path("events/<int:pk>/volunteer-slots/", views.EventVolunteerSlots.as_view(), name="event-volunteer-slots"),
    path("volunteer-slots/<int:pk>/signup/", views.VolunteerSignupView.as_view(), name="volunteer-signup"),
]
