"""OCI Notifications HTTPS alert receiver (stdlib only, local demo).

Implements the documented OCI Notifications delivery protocol: OCI posts
messages with an x-oci-ns-message-type header of Confirmation, Notification
or UnsubscribeConfirmation. A Confirmation carries a SubscribeURL that
activates the subscription when visited; a Notification carries the event.

Security posture, on purpose:
- Loopback only: serve() refuses any host but 127.0.0.1. Public exposure
  needs HTTPS plus OCI message signature verification, which this project
  deliberately does not implement.
- The receiver NEVER fetches a URL it receives. The SubscribeURL is
  untrusted input; it is logged with the query redacted and confirming the
  subscription is a manual step in the OCI Console or CLI (docs/setup.md).
  There is no outbound request path in this file, so there is no SSRF
  surface. The SubscribeURL shape check below is protocol hygiene only
  (reject malformed messages), not fetch protection.
- Trust boundary: accepted events are UNVERIFIED (no signature check), so
  alert lines are labelled "(unverified)". Treat them as demo/log data.
- Confirmation tokens are never logged (query string is redacted).
- Request bodies are capped at MAX_BODY bytes (413 beyond that).
"""
import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, urlunsplit

MAX_BODY = 128 * 1024  # bytes

_OCI_NOTIFICATIONS_HOST = re.compile(
    r"^[a-z0-9-]+\.notification\.[a-z0-9-]+\.oci\.oraclecloud\.com$")


def redact_url(url):
    """Strip the query string (it carries the subscription token)."""
    parts = urlsplit(url)
    shown = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    return shown + "?<redacted>" if parts.query else shown


def validate_subscribe_url(url):
    """Shape check for protocol hygiene. Returns (ok, reason).

    This is NOT fetch protection: the receiver never fetches any URL.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "unparseable URL"
    if parts.scheme != "https":
        return False, "not an https URL"
    if not _OCI_NOTIFICATIONS_HOST.match(parts.netloc):
        return False, "not an OCI Notifications endpoint"
    return True, ""


def format_alert(event):
    """One-line alert from a documented Object Storage event, else None."""
    if not isinstance(event, dict) or "eventType" not in event:
        return None
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    name = data.get("resourceName", "?")
    bucket = data.get("additionalDetails", {}).get("bucketName", "?")
    return (f"[{event.get('eventTime', '?')}] {event['eventType']}: "
            f"{name} in bucket {bucket}")


class Handler(BaseHTTPRequestHandler):
    server_version = "OCINotificationsReceiver/1.0"

    def log_message(self, fmt, *args):
        self._out(f"{self.address_string()} - {fmt % args}")

    def _out(self, line):
        out = getattr(self.server, "out", None) or sys.stdout
        out.write(line + "\n")
        out.flush()

    def _send(self, code, body, content_type="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._json(400, {"error": "missing body"})
            return None
        if length > MAX_BODY:
            self._json(413, {"error": "body too large"})
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid JSON"})
            return None

    def do_GET(self):
        if self.path.split("?")[0].rstrip("/") == "/health":
            self._send(200, "ok", "text/plain")
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        mtype = self.headers.get("x-oci-ns-message-type")
        if mtype not in ("Confirmation", "Notification",
                         "UnsubscribeConfirmation"):
            self._json(400, {"error": "unknown message type"})
            return
        msg = self._read_json()
        if msg is None:
            return
        {"Confirmation": self._confirmation,
         "Notification": self._notification,
         "UnsubscribeConfirmation": self._unsubscribe}[mtype](msg)

    def _confirmation(self, msg):
        url = msg.get("SubscribeURL") if isinstance(msg, dict) else None
        if not url:
            self._json(400, {"error": "missing SubscribeURL"})
            return
        ok, reason = validate_subscribe_url(url)
        if not ok:
            self._json(400, {"error": reason})
            return
        self._out(f"CONFIRM by visiting: {redact_url(url)}")
        self._out("Confirm this subscription in the OCI Console or CLI "
                  "(docs/setup.md). This receiver never fetches the URL "
                  "itself.")
        self._json(200, {"status": "confirmation_received"})

    def _notification(self, msg):
        event = msg
        if isinstance(msg, dict) and msg.get("Type") == "Notification":
            try:
                event = json.loads(msg.get("Message", ""))
            except (json.JSONDecodeError, TypeError):
                event = None
        line = format_alert(event)
        if line is None:
            self._json(400, {"error": "not an event"})
            return
        self._out(f"ALERT (unverified): {line}")
        self._json(200, {"status": "notification_received"})

    def _unsubscribe(self, msg):
        self._out("UNSUBSCRIBE confirmation received")
        self._json(200, {"status": "unsubscribe_received"})


def serve(port, host="127.0.0.1", out=None):
    """Start the receiver. Loopback only - anything else raises ValueError."""
    if host != "127.0.0.1":
        raise ValueError(
            f"refusing to bind {host!r}: loopback only, see docs/setup.md")
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.out = out
    return httpd


def main():
    ap = argparse.ArgumentParser(
        description="Local OCI Notifications alert receiver (demo).")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    httpd = serve(args.port)
    print(f"receiver on http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
