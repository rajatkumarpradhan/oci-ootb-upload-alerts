#!/usr/bin/env python3
"""Offline consistency check for the deploy configs.

Reads config/events-rule.json and config/notifications-topic.json and checks
the two files agree with each other and with the documented OCI shapes.
No OCI calls are made; this validates files only.

Exit codes: 0 ok, 1 bad input / usage, 2 one or more findings.
"""
import json
import os
import re
import sys

KNOWN_OBJECT_EVENTS = {
    "com.oraclecloud.objectstorage.createobject",
    "com.oraclecloud.objectstorage.deleteobject",
    "com.oraclecloud.objectstorage.updateobject",
}
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,255}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOPIC_PLACEHOLDER = "<notifications-topic-ocid>"
COMPARTMENT_PLACEHOLDER = "<compartment-ocid>"
EMAIL_PLACEHOLDER = "<your-email-address>"


def load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate(rule, topic, findings):
    for key in ("compartmentId", "displayName", "isEnabled", "condition", "actions"):
        if key not in rule:
            findings.append(f"events-rule.json: missing key {key!r}")

    if rule.get("compartmentId") != COMPARTMENT_PLACEHOLDER:
        findings.append("events-rule.json: compartmentId must stay the "
                        f"{COMPARTMENT_PLACEHOLDER} placeholder until deploy time")

    cond_raw = rule.get("condition")
    if isinstance(cond_raw, str):
        try:
            cond = json.loads(cond_raw)
        except json.JSONDecodeError as exc:
            findings.append(f"events-rule.json: condition is not valid JSON ({exc})")
            cond = {}
    else:
        findings.append("events-rule.json: condition must be a JSON-encoded string")
        cond = {}

    for et in cond.get("eventType", []):
        if et not in KNOWN_OBJECT_EVENTS:
            findings.append(f"events-rule.json: unknown object storage eventType {et!r}")
    if not cond.get("eventType"):
        findings.append("events-rule.json: condition.eventType is empty")

    buckets = (cond.get("data", {}).get("additionalDetails", {}) or {}).get("bucketName", [])
    if len(buckets) != 1:
        findings.append("events-rule.json: expected exactly one bucketName filter")
    for b in buckets:
        if not BUCKET_RE.match(b):
            findings.append(f"events-rule.json: bucket name {b!r} is not a valid bucket name")

    actions = (rule.get("actions") or {}).get("actions", [])
    if len(actions) != 1:
        findings.append("events-rule.json: expected exactly one action")
    for a in actions:
        if a.get("actionType") != "ONS":
            findings.append(f"events-rule.json: actionType {a.get('actionType')!r} is not ONS")
        if a.get("topicId") != TOPIC_PLACEHOLDER:
            findings.append("events-rule.json: action topicId must stay the "
                            f"{TOPIC_PLACEHOLDER} placeholder until deploy time")
        if a.get("isEnabled") is not True:
            findings.append("events-rule.json: action isEnabled must be true")

    sub = topic.get("subscription", {})
    if sub.get("protocol") != "EMAIL":
        findings.append("notifications-topic.json: subscription.protocol must be EMAIL")
    ep = sub.get("endpoint", "")
    if ep != EMAIL_PLACEHOLDER and not EMAIL_RE.match(ep):
        findings.append(f"notifications-topic.json: endpoint {ep!r} is not an email address")
    if not (topic.get("topic", {}) or {}).get("name"):
        findings.append("notifications-topic.json: topic.name is empty")

    return findings


def main(argv):
    base = argv[1] if len(argv) > 1 else os.path.join(os.path.dirname(__file__), "..")
    rule_path = os.path.join(base, "config", "events-rule.json")
    topic_path = os.path.join(base, "config", "notifications-topic.json")
    try:
        rule = load(rule_path)
        topic = load(topic_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"input error: {exc}")
        return 1
    findings = validate(rule, topic, [])
    if findings:
        for f in findings:
            print(f"FINDING: {f}")
        return 2
    print("config ok: events rule and notifications topic are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
