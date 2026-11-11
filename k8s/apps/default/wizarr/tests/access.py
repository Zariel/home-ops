#!/usr/bin/env python3
"""Check the public Wizarr authentication boundary without creating accounts."""

import http.client
import os
import unittest
from urllib.parse import parse_qs, urlsplit


BASE_URL = os.environ.get("WIZARR_URL", "https://join.cbannister.xyz")


def request(path, headers=None):
    url = urlsplit(BASE_URL)
    connection = http.client.HTTPSConnection(url.hostname, url.port or 443, timeout=10)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        response.read()
        return response.status, response.getheader("Location", "")
    finally:
        connection.close()


class Access(unittest.TestCase):
    def assert_login(self, status, location):
        self.assertEqual(status, 302)
        target = urlsplit(location)
        self.assertEqual((target.scheme, target.netloc, target.path),
                         ("https", "id.cbannister.xyz", "/authorize"))
        query = parse_qs(target.query)
        self.assertEqual(query["client_id"], ["wizarr"])
        self.assertEqual(query["redirect_uri"], [BASE_URL + "/oauth2/callback"])
        self.assertEqual(query["code_challenge_method"], ["S256"])

    def test_admin_requires_login(self):
        for path in ("/", "/admin", "/login", "/setup/", "/settings",
                     "/api/docs/", "/wizard/bundle-preview/1/0"):
            with self.subTest(path=path):
                self.assert_login(*request(path))

    def test_headers_do_not_grant_access(self):
        for headers in (
            {"Authorization": "Bearer invalid"},
            {"Cookie": "session=invalid"},
            {"X-Auth-Request-Email": "admin@example.com",
             "X-Auth-Request-Groups": "admin",
             "Remote-User": "admin"},
        ):
            with self.subTest(headers=list(headers)):
                self.assert_login(*request("/admin", headers))

    def test_guest_pages(self):
        status, _ = request("/join")
        self.assertEqual(status, 200)

        # Invalid codes must reach Wizarr's guest handler, without an IdP login.
        for path in ("/j/INVALID", "/reset/INVALID", "/wizard/help",
                     "/static/manifest.json", "/favicon.ico"):
            with self.subTest(path=path):
                for _ in range(5):
                    status, location = request(path)
                    self.assertLess(status, 500)
                    self.assertNotEqual(urlsplit(location).netloc, "id.cbannister.xyz")
                    if status not in (301, 302, 303, 307, 308):
                        break
                    self.assertTrue(location.startswith("/"), location)
                    path = location
                else:
                    self.fail("Guest page did not finish redirecting")

    def test_path_variants(self):
        for path in ("/static/../login", "/j/../admin", "/j/%2e%2e/login",
                     "/wizard/pre-wizard/../../login", "/%6cogin", "//login"):
            with self.subTest(path=path):
                status, location = request(path)
                if status not in (400, 404):
                    self.assert_login(status, location)

    def test_callback_requires_state(self):
        status, _ = request("/oauth2/callback?code=invalid&state=invalid")
        self.assertIn(status, (401, 403))


if __name__ == "__main__":
    unittest.main()
