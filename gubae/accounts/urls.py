from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("register/", views.Register.as_view(), name="register"),
    path("token/", views.Login.as_view(), name="token"),                       # username+password -> access+refresh
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),  # refresh -> new access
    path("me/", views.Me.as_view(), name="me"),
]
