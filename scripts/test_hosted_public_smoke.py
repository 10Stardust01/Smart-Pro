"""Offline regression for hosted smoke HTTP header handling; no network calls."""
import unittest
from email.message import Message
from unittest.mock import patch

from hosted_public_smoke import OPENER, get


class FakeResponse:
    status = 302

    def __init__(self):
        self.headers = Message()
        self.headers["location"] = "/reviewer/login"

    def read(self, size):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class HostedSmokeHeadersTest(unittest.TestCase):
    def test_redirect_location_lookup_is_case_insensitive(self):
        with patch.object(OPENER, "open", return_value=FakeResponse()) as opened:
            status, body, headers = get("/")
        self.assertEqual(status, 302)
        self.assertEqual(body, "")
        self.assertEqual(headers.get("Location"), "/reviewer/login")
        self.assertEqual(headers.get("location"), "/reviewer/login")
        opened.assert_called_once()


if __name__ == "__main__":
    unittest.main()
