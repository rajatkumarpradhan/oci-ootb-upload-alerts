# oci-ootb-upload-alerts

An OOTB (out-of-the-box) OCI project with working, tested code: a file-upload alert pipeline wired **only from Oracle Cloud's built-in services** - no custom servers in the cloud path, no Functions to maintain.

**Upload a file to an Object Storage bucket -> an Events rule catches it -> a Notifications topic delivers the alert** to your email (zero code), or to this repo's local HTTPS receiver for formatted, logged alerts (real code, tested below).

![architecture](assets/architecture.svg)

| Built-in OCI feature | Role here | Cost (Oracle published limits, checked 27 Oct 2026) |
|---|---|---|
| Object Storage bucket (`upload-inbox`) | Receives uploads, emits events | 20 GB Always Free |
| Events rule (`upload-inbox-create-events`) | Matches `com.oraclecloud.objectstorage.createobject` on that bucket | Events service is free |
| Notifications topic (`upload-alerts`) + subscription | Delivers the alert | 1,000 emails/month free; 1M HTTPS deliveries/month free |

Sources: [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [Events pricing](https://www.oracle.com/cloud/events-service/), [Notifications pricing](https://www.oracle.com/cloud/cloud-native/notifications/pricing/). Limits, regions and billing are Oracle's to change; the links are the source of truth.

## Run it locally (no OCI needed)

```
python3 -m unittest discover -s tests -v   # 38 tests
python3 scripts/demo.py                    # end-to-end local demo of the receiver
python3 scripts/validate.py                # config consistency check
```

The demo starts the receiver, sends the two documented OCI Notifications message shapes (subscription Confirmation, then an object-create Notification) and prints the receiver output - a redacted confirmation URL to visit, then a formatted alert line. **This is a local simulation of the delivery side, not a live OCI run.**

## The receiver (`receiver/server.py`)

A stdlib-only HTTP endpoint implementing the documented OCI Notifications HTTPS protocol (`x-oci-ns-message-type` header: Confirmation / Notification / UnsubscribeConfirmation). It formats each delivered event into a one-line alert with time, event type, object and bucket.

Security posture, on purpose:

- Binds to 127.0.0.1 only; public binding is refused (`serve()` raises). Public exposure needs HTTPS plus OCI signature verification, which this project does not implement.
- **Trust boundary:** accepted Notifications are *unverified* - output lines say so. Signature verification needs the OCI signing certificate chain and a crypto library.
- Confirmation URLs are validated before use: HTTPS only, host must match the OCI Notifications endpoint pattern, and `--auto-confirm` additionally requires the host to resolve only to public IPs and follows no redirects. Anything else is rejected, so a malicious POST cannot make the receiver fetch an arbitrary URL (SSRF).
- Subscription tokens are never logged: confirmation output redacts the query string.
- Request bodies are capped (128 KB) with 413 for oversize posts.

## Status: prepared, not deployed

**Nothing here has been deployed: no OCI resources exist for this project yet, and the deploy steps in [docs/setup.md](docs/setup.md) have not been executed on a live tenancy.** The configs carry `<...>` placeholders to fill at deploy time, and creating resources is your call on your account. The receiver code and configs are tested locally (24 tests, CI on Python 3.10-3.12); live behavior against OCI is documented but unverified.

## Layout

- `receiver/server.py` - the HTTPS alert receiver (stdlib only).
- `config/events-rule.json` - Events rule create-request body with placeholders.
- `config/notifications-topic.json` - topic and subscription shape.
- `scripts/validate.py` - offline config consistency check (exit 0 ok, 1 bad input, 2 findings).
- `scripts/demo.py` - local end-to-end demo.
- `docs/setup.md` - deploy, verify and cleanup, Console and OCI CLI, EMAIL and HTTPS paths.
- `tests/` - receiver protocol tests, config tests, doc-shape fixtures.
- `assets/architecture.svg` - the diagram above.

## Honest limits

- Local tests and the demo simulate OCI message delivery from documented message shapes; they are not a live OCI integration test.
- The receiver does not verify OCI message signatures, so its alerts are unverified claims, not trusted OCI alerts. Publicly exposing it is out of scope for this project.
- The bucket must have **Emit Object Events** enabled (off by default) and the Events rule must be created in the bucket's compartment - both are called out in [docs/setup.md](docs/setup.md).
- Email subscriptions start Pending until confirmed once; Events are at-least-once, so a rare duplicate alert is possible.
