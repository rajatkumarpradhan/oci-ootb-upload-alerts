# oci-ootb-upload-alerts

An OOTB (out-of-the-box) OCI project with working, tested code: a file-upload alert pipeline wired **only from Oracle Cloud's built-in services** - no custom servers in the cloud path, no Functions to maintain.

**Upload a file to an Object Storage bucket -> an Events rule catches it -> a Notifications topic delivers the alert** to your email (zero code), or to this repo's HTTPS receiver for formatted, logged alerts (real code, tested below).

![architecture](assets/architecture.svg)

| Built-in OCI feature | Role here | Cost (Oracle published limits, checked 27 Oct 2026) |
|---|---|---|
| Object Storage bucket (`upload-inbox`) | Receives uploads, emits events | 20 GB Always Free |
| Events rule (`upload-inbox-create-events`) | Matches `com.oraclecloud.objectstorage.createobject` on that bucket | Events service is free |
| Notifications topic (`upload-alerts`) + subscription | Delivers the alert | 1,000 emails/month free; 1M HTTPS deliveries/month free |

Sources: [Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [Events pricing](https://www.oracle.com/cloud/events-service/), [Notifications pricing](https://www.oracle.com/cloud/cloud-native/notifications/pricing/). Limits, regions and billing are Oracle's to change; the links are the source of truth.

## Run it locally (no OCI needed)

```
python3 -m unittest discover -s tests -v   # 24 tests
python3 scripts/demo.py                    # end-to-end local demo of the receiver
python3 scripts/validate.py                # config consistency check
```

The demo starts the receiver, sends the two documented OCI Notifications message shapes (subscription Confirmation, then an object-create Notification) and prints the receiver output - a confirmation URL to visit, then a formatted alert line. **This is a local simulation of the delivery side, not a live OCI run.**

## The receiver (`receiver/server.py`)

A stdlib-only HTTP endpoint implementing the documented OCI Notifications HTTPS protocol (`x-oci-ns-message-type` header: Confirmation / Notification / UnsubscribeConfirmation). It prints the SubscribeURL during confirmation (or confirms automatically with `--auto-confirm`) and formats each event into a one-line alert with time, event type, object and bucket. Run it on any machine - including an Always Free compute VM - and subscribe its URL to the topic for HTTPS delivery.

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
- The receiver does not verify OCI message signatures (needs the OCI signing certificate chain and a crypto library). Before exposing an endpoint publicly, serve it over HTTPS and add signature verification per the OCI docs.
- The bucket must have **Emit Object Events** enabled (off by default) and the Events rule must be created in the bucket's compartment - both are called out in [docs/setup.md](docs/setup.md).
- Email subscriptions start Pending until confirmed once; Events are at-least-once, so a rare duplicate alert is possible.
