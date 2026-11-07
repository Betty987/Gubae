from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

User = get_user_model()


class AuthTests(APITestCase):
    def setUp(self):
        cache.clear()

    def register(self, **overrides):
        data = {"username": "abebe", "email": "abebe@example.com", "password": "meskel-2026!"}
        data.update(overrides)
        return self.client.post("/api/auth/register/", data, format="json")

    def test_register_hashes_password_and_hides_it(self):
        r = self.register()
        self.assertEqual(r.status_code, 201)
        self.assertNotIn("password", r.data)
        user = User.objects.get(username="abebe")
        self.assertNotEqual(user.password, "meskel-2026!")
        self.assertTrue(user.check_password("meskel-2026!"))

    def test_weak_password_rejected(self):
        self.assertEqual(self.register(password="123").status_code, 400)

    def test_duplicate_email_rejected(self):
        self.register()
        self.assertEqual(self.register(username="other", email="ABEBE@example.com").status_code, 400)

    def test_login_me_and_refresh(self):
        self.register()
        r = self.client.post("/api/auth/token/", {"username": "abebe", "password": "meskel-2026!"}, format="json")
        self.assertEqual(r.status_code, 200)
        access, refresh = r.data["access"], r.data["refresh"]

        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        self.assertEqual(self.client.get("/api/auth/me/").data["username"], "abebe")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access[:-4]}abcd")  # tampered
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

        self.client.credentials()
        r = self.client.post("/api/auth/token/refresh/", {"refresh": refresh}, format="json")
        self.assertIn("access", r.data)

    def test_wrong_password(self):
        self.register()
        r = self.client.post("/api/auth/token/", {"username": "abebe", "password": "nope-nope-1"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_login_is_rate_limited(self):
        for _ in range(20):
            self.client.post("/api/auth/token/", {"username": "x", "password": "y"}, format="json")
        r = self.client.post("/api/auth/token/", {"username": "x", "password": "y"}, format="json")
        self.assertEqual(r.status_code, 429)  # Too Many Requests
