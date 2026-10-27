import io
import json
import os
import socket
import threading
import unittest
import urllib.request
import urllib.error
from unittest import mock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from receiver import server
from receiver.server import serve, format_alert, validate_subscribe_url, redact_url

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), "rb") as fh:
        return fh.read()


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = io.StringIO()
        cls.httpd = serve(0, out=cls.out)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def url(self, path="/"):
        return f"http://127.0.0.1:{self.port}{path}"

    def post(self, body, msg_type=None):
        headers = {}
        if msg_type is not None:
            headers["x-oci-ns-message-type"] = msg_type
        req = urllib.request.Request(self.url(), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_health(self):
        with urllib.request.urlopen(self.url("/health"), timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.read().decode().strip(), "ok")

    def test_unknown_path_404(self):
        try:
            urllib.request.urlopen(self.url("/nope"), timeout=5)
            self.fail("expected 404")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)

    def test_notification_formats_alert(self):
        code, text = self.post(fixture("notification.json"), "Notification")
        self.assertEqual(code, 200, text)
        logged = self.out.getvalue()
        self.assertIn("invoice-0427.pdf in bucket upload-inbox", logged)
        self.assertIn("com.oraclecloud.objectstorage.createobject", logged)
        self.assertIn("unverified", logged)  # trust boundary is visible

    def test_confirmation_prints_redacted_url(self):
        code, text = self.post(fixture("confirmation.json"), "Confirmation")
        self.assertEqual(code, 200, text)
        logged = self.out.getvalue()
        self.assertIn("CONFIRM by visiting: https://cell1.notification.eu-frankfurt-1.oci.oraclecloud.com", logged)
        self.assertNotIn("token=abc123", logged)  # never log the token

    def test_confirmation_http_url_rejected(self):
        body = b'{"SubscribeURL": "http://cell1.notification.eu-frankfurt-1.oci.oraclecloud.com/x?token=t"}'
        code, text = self.post(body, "Confirmation")
        self.assertEqual(code, 400)
        self.assertIn("not an https URL", text)

    def test_confirmation_non_oci_host_rejected(self):
        body = b'{"SubscribeURL": "https://evil.example.com/confirm?token=t"}'
        code, text = self.post(body, "Confirmation")
        self.assertEqual(code, 400)
        self.assertIn("not an OCI Notifications endpoint", text)

    def test_confirmation_lookalike_host_rejected(self):
        body = b'{"SubscribeURL": "https://cell1.notification.oci.oraclecloud.com.evil.com/x?token=t"}'
        code, text = self.post(body, "Confirmation")
        self.assertEqual(code, 400)

    def test_missing_message_type_400(self):
        code, _ = self.post(fixture("notification.json"))
        self.assertEqual(code, 400)

    def test_unknown_message_type_400(self):
        code, _ = self.post(fixture("notification.json"), "SomethingElse")
        self.assertEqual(code, 400)

    def test_notification_bad_json_400(self):
        code, _ = self.post(b"{not json", "Notification")
        self.assertEqual(code, 400)

    def test_notification_non_event_400(self):
        code, _ = self.post(b'{"hello": "world"}', "Notification")
        self.assertEqual(code, 400)

    def test_confirmation_without_url_400(self):
        code, _ = self.post(b'{"Type": "Confirmation"}', "Confirmation")
        self.assertEqual(code, 400)

    def test_body_too_large_413(self):
        big = b'{"eventType": "' + b"x" * (server.MAX_BODY + 10) + b'"}'
        code, _ = self.post(big, "Notification")
        self.assertEqual(code, 413)


class UrlValidationCase(unittest.TestCase):
    GOOD = "https://cell1.notification.eu-frankfurt-1.oci.oraclecloud.com/20181201/subscriptions/ocid1.x/confirmation?token=abc"

    def test_good_url_passes_without_dns(self):
        ok, _ = validate_subscribe_url(self.GOOD, resolve=False)
        self.assertTrue(ok)

    def test_http_rejected(self):
        ok, reason = validate_subscribe_url("http://cell1.notification.eu-frankfurt-1.oci.oraclecloud.com/x", resolve=False)
        self.assertFalse(ok)
        self.assertIn("https", reason)

    def test_non_oci_host_rejected(self):
        ok, _ = validate_subscribe_url("https://example.com/x", resolve=False)
        self.assertFalse(ok)

    def test_lookalike_host_rejected(self):
        ok, _ = validate_subscribe_url("https://cell1.notification.oci.oraclecloud.com.evil.com/x", resolve=False)
        self.assertFalse(ok)

    def test_private_ip_resolution_rejected(self):
        fake = [(socket.AF_INET, 0, 0, "", ("10.0.0.5", 443))]
        with mock.patch.object(server.socket, "getaddrinfo", return_value=fake):
            ok, reason = validate_subscribe_url(self.GOOD, resolve=True)
        self.assertFalse(ok)
        self.assertIn("non-public", reason)

    def test_dns_failure_rejected(self):
        with mock.patch.object(server.socket, "getaddrinfo", side_effect=OSError("no dns")):
            ok, reason = validate_subscribe_url(self.GOOD, resolve=True)
        self.assertFalse(ok)
        self.assertIn("cannot resolve", reason)

    def test_public_ip_resolution_passes(self):
        fake = [(socket.AF_INET, 0, 0, "", ("129.146.1.1", 443))]
        with mock.patch.object(server.socket, "getaddrinfo", return_value=fake):
            ok, _ = validate_subscribe_url(self.GOOD, resolve=True)
        self.assertTrue(ok)

    def test_redaction_hides_query(self):
        shown = redact_url(self.GOOD)
        self.assertNotIn("token=abc", shown)
        self.assertNotIn("?token", shown)
        self.assertIn("cell1.notification", shown)

    def test_no_redirect_opener_used(self):
        self.assertTrue(issubclass(server._NoRedirect, urllib.request.HTTPRedirectHandler))
        self.assertIsNone(server._NoRedirect().redirect_request(None, None, 302, "", {}, "http://x"))


class FormatAlertCase(unittest.TestCase):
    def test_full_event(self):
        event = json.loads(fixture("notification.json"))
        line = format_alert(event)
        self.assertEqual(
            line,
            "[2026-10-27T10:05:00.000Z] com.oraclecloud.objectstorage.createobject: "
            "invoice-0427.pdf in bucket upload-inbox")

    def test_missing_fields_get_placeholders(self):
        line = format_alert({"eventType": "x.y", "data": {}})
        self.assertIn("?", line)

    def test_non_event_returns_none(self):
        self.assertIsNone(format_alert({"no": "event"}))
        self.assertIsNone(format_alert([1, 2]))


class ServeGuardCase(unittest.TestCase):
    def test_public_bind_refused(self):
        with self.assertRaises(ValueError):
            serve(0, host="0.0.0.0")


if __name__ == "__main__":
    unittest.main()
