"""Who is allowed to do what.

Authentication = WHO are you?          (JWT, handled by SimpleJWT)
Authorization  = what may you DO?      (this file)

Rules:
  - Anyone can read communities and events.
  - Logged-in users can create a community (and become its admin) or join one.
  - Only MEMBERS of a community can RSVP or volunteer for its events.
  - Only ADMINS of a community can create / edit / delete its events.
"""
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .models import Community, Event, Membership


def role_in(user, community_id):
    """Return "admin", "member", or None."""
    if not user.is_authenticated:
        return None
    return (
        Membership.objects.filter(user=user, community_id=community_id)
        .values_list("role", flat=True)
        .first()
    )


def is_admin_of(user, community_id) -> bool:
    return role_in(user, community_id) == Membership.Role.ADMIN


def is_member_of(user, community_id) -> bool:
    return role_in(user, community_id) is not None  # admins count as members


class IsCommunityAdminOrReadOnly(BasePermission):
    """GET is open to everyone; PATCH/PUT/DELETE require being an admin of
    the community that owns the object."""

    message = "Only admins of this community can do that."

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:  # GET, HEAD, OPTIONS
            return True
        if isinstance(obj, Event):
            return is_admin_of(request.user, obj.community_id)
        if isinstance(obj, Community):
            return is_admin_of(request.user, obj.id)
        return False
