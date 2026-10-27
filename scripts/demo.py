#!/usr/bin/env python3
"""Local demo of the alert receiver - no OCI needed.

Starts the receiver on a free local port, sends the two documented OCI
Notifications message shapes (subscription Confirmation, then an object-create
Notification), and prints exactly what the receiver does. This simulates the
delivery side locally; it is not a live OCI run.
"""
import io
import os
import sys
import threading
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from receiver.server import serve

FIX = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")


def post(port, name, msg_type):
    with open(os.path.join(FIX, name), "rb") as fh:
        body = fh.read()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/", data=body,
        headers={"x-oci-ns-message-type": msg_type}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status


def main():
    out = io.StringIO()
    httpd = serve(0, out=out)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"receiver up on 127.0.0.1:{port}")
    print(f"1) subscription Confirmation -> HTTP {post(port, 'confirmation.json', 'Confirmation')}")
    print(f"2) object-create Notification -> HTTP {post(port, 'notification.json', 'Notification')}")
    httpd.shutdown()
    print("receiver output:")
    for line in out.getvalue().splitlines():
        print(f"   {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
