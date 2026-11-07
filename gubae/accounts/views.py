from rest_framework import generics, permissions
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import RegisterSerializer, UserSerializer


class Register(generics.CreateAPIView):
    """POST /api/auth/register/  -> create an account (anyone may call this)"""

    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"  # rate-limited (see REST_FRAMEWORK in settings.py)


class Login(TokenObtainPairView):
    """POST /api/auth/token/  {username, password} -> {access, refresh}

    Same as SimpleJWT's view, plus rate limiting so nobody can try
    thousands of passwords per minute.
    """

    throttle_scope = "auth"


class Me(generics.RetrieveAPIView):
    """GET /api/auth/me/  -> the logged-in user. No token = 401."""

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        # No id in the URL: "me" is whoever the token belongs to.
        return self.request.user
