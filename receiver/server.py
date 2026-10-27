#!/usr/bin/env python3
"""HTTP receiver for OCI Notifications deliveries - local/demo use.

Implements the documented OCI Notifications HTTPS endpoint protocol
(message types Confirmation / Notification / UnsubscribeConfirmation in the
x-oci-ns-message-type header) so the upload-alerts pipeline can deliver to an
HTTPS endpoint instead of, or alongside, email.

Stdlib only. Run: python3 -m receiver.server --port 8080
Binds to 127.0.0.1 on purpose: this receiver is for local runs and demos.

TRUST BOUNDARY (read before trusting any alert): this receiver does NOT verify
OCI message signatures, so a Notification it accepts is an unverified claim,
not a trusted OCI alert. Verification needs the OCI signing certificate chain
and a crypto library and is out of scope here. Publicly exposing this receiver
is not part of this project: a public endpoint must be HTTPS, must verify
signatures per the OCI docs, and must treat subscription tokens as secrets.
"""
import ipaddress
import json
import re
import socket
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MSG_TYPE_HEADER = "x-oci-ns-message-type"
KNOWN_TYPES = {"Confirmation", "Notification", "UnsubscribeConfirmation"}
MAX_BODY = 128 * 1024  # OCI message payloads are documented at 64 KB max
OCI_TOPIC_HOST = re.compile(
    r"^cell\d+\.notification\.[a-z0-9-]+\.oci\.oraclecloud\.com$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redact_url(url):
    """Display form of a subscribe URL: scheme, host, path - query/token hidden."""
    m = re.match(r"^(https://[^/?]+)(/[^?]*)?", url or "")
    return (m.group(1) + (m.group(2) or "") + " (query/token hidden)") if m else "(unparseable url)"


def validate_subscribe_url(url, resolve=True):
    """Return (ok, reason). Only HTTPS URLs on OCI Notifications hosts pass;
    when resolve=True the host must also resolve only to public IPs."""
    if not isinstance(url, str) or not url.startswith("https://"):
        return False, "not an https URL"
    host = url[len("https://"):].split("/")[0].split(":")[0].lower()
    if not OCI_TOPIC_HOST.match(host):
        return False, f"host {host!r} is not an OCI Notifications endpoint"
    if resolve:
        try:
            infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            return False, f"cannot resolve {host!r}: {exc}"
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                return False, f"{host!r} resolves to a non-public address"
    return True, "ok"


def format_alert(event):
    """Render one CloudEvents-style event as a single alert line."""
    if not isinstance(event, dict) or "eventType" not in event:
        return None
    data = event.get("data") or {}
    details = data.get("additionalDetails") or {}
    bucket = details.get("bucketName", "?")
    obj = data.get("resourceName", "?")
    when = event.get("eventTime", "?")
    etype = event.get("eventType", "?")
    return f"[{when}] {etype}: {obj} in bucket {bucket}"


class Handler(BaseHTTPRequestHandler):
    server_version = "oci-ootb-receiver/0.1"
    auto_confirm = False
    out = sys.stdout

    def log_message(self, fmt, *args):  # keep stderr quiet in tests
        pass

    def _send(self, code, text):
        body = text.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _print(self, line):
        print(line, file=self.out, flush=True)

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, "ok\n")
        else:
            self._send(404, "not found\n")

    def do_POST(self):
        msg_type = self.headers.get(MSG_TYPE_HEADER, "")
        if msg_type not in KNOWN_TYPES:
            self._send(400, f"unsupported or missing {MSG_TYPE_HEADER}\n")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, "bad content length\n")
            return
        if length > MAX_BODY:
            self._send(413, "body too large\n")
            return
        try:
            body = self.rfile.read(length).decode("utf-8")
        except UnicodeDecodeError:
            self._send(400, "bad body\n")
            return

        if msg_type == "Notification":
            try:
                event = json.loads(body)
            except json.JSONDecodeError:
                self._send(400, "notification body is not JSON\n")
                return
            line = format_alert(event)
            if line is None:
                self._send(400, "notification body is not an event\n")
                return
            self._print(f"ALERT (unverified) {line}")
            self._send(200, "alert recorded\n")
            return

        # Confirmation / UnsubscribeConfirmation: body is JSON with a subscribe URL
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self._send(400, "confirmation body is not JSON\n")
            return
        url = payload.get("SubscribeURL") or payload.get("subscribeURL")
        if not url:
            self._send(400, "no SubscribeURL in confirmation\n")
            return
        ok, reason = validate_subscribe_url(url, resolve=self.auto_confirm)
        if not ok:
            self._print(f"REJECTED subscribe URL: {reason}")
            self._send(400, f"untrusted subscribe URL: {reason}\n")
            return
        if self.auto_confirm:
            try:
                opener = urllib.request.build_opener(_NoRedirect)
                with opener.open(url, timeout=10) as resp:
                    self._print(f"CONFIRMED subscription at {redact_url(url)} (HTTP {resp.status})")
            except Exception as exc:  # noqa: BLE001 - report any confirm failure
                self._print(f"CONFIRM FAILED at {redact_url(url)}: {exc}")
                self._send(502, "subscribe confirmation failed\n")
                return
        else:
            self._print(f"CONFIRM by visiting: {redact_url(url)}")
        self._send(200, "confirmation received\n")


def serve(port, host="127.0.0.1", auto_confirm=False, out=None):
    if host != "127.0.0.1":
        raise ValueError("this receiver binds to 127.0.0.1 only; public "
                         "exposure needs HTTPS + OCI signature verification, "
                         "which this project does not implement")
    Handler.auto_confirm = auto_confirm
    if out is not None:
        Handler.out = out
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


def main(argv):
    port = 8080
    auto = "--auto-confirm" in argv
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            port = int(argv[i + 1])
    httpd = serve(port, auto_confirm=auto)
    print(f"listening on 127.0.0.1:{port} (auto_confirm={auto})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
