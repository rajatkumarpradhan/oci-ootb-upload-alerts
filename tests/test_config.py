import json
import os
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

BASE = os.path.join(os.path.dirname(__file__), "..")
VALIDATE = os.path.join(BASE, "scripts", "validate.py")


def load(rel):
    with open(os.path.join(BASE, rel), "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestValidateCli(unittest.TestCase):
    def run_cli(self, base=None):
        cmd = [sys.executable, VALIDATE] + ([base] if base else [])
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_shipped_config_is_clean(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("config ok", r.stdout)

    def test_missing_files_exit_1(self):
        r = self.run_cli(base="/nonexistent-path-xyz")
        self.assertEqual(r.returncode, 1)

    def _broken(self, mutate):
        import tempfile, shutil
        tmp = tempfile.mkdtemp()
        try:
            shutil.copytree(os.path.join(BASE, "config"), os.path.join(tmp, "config"))
            shutil.copytree(os.path.join(BASE, "scripts"), os.path.join(tmp, "scripts"))
            mutate(tmp)
            return self.run_cli(base=tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unknown_event_type_flagged(self):
        def m(tmp):
            p = os.path.join(tmp, "config", "events-rule.json")
            rule = load_rel(p)
            cond = json.loads(rule["condition"])
            cond["eventType"] = ["com.oraclecloud.objectstorage.madeup"]
            rule["condition"] = json.dumps(cond)
            json.dump(rule, open(p, "w"))
        r = self._broken(m)
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown object storage eventType", r.stdout)

    def test_real_topic_ocid_before_deploy_flagged(self):
        def m(tmp):
            p = os.path.join(tmp, "config", "events-rule.json")
            rule = load_rel(p)
            rule["actions"]["actions"][0]["topicId"] = "ocid1.onstopic.oc1..real"
            json.dump(rule, open(p, "w"))
        r = self._broken(m)
        self.assertEqual(r.returncode, 2)
        self.assertIn("placeholder", r.stdout)

    def test_bad_email_flagged(self):
        def m(tmp):
            p = os.path.join(tmp, "config", "notifications-topic.json")
            topic = load_rel(p)
            topic["subscription"]["endpoint"] = "not-an-email"
            json.dump(topic, open(p, "w"))
        r = self._broken(m)
        self.assertEqual(r.returncode, 2)

    def test_bad_bucket_name_flagged(self):
        def m(tmp):
            p = os.path.join(tmp, "config", "events-rule.json")
            rule = load_rel(p)
            cond = json.loads(rule["condition"])
            cond["data"]["additionalDetails"]["bucketName"] = ["Bad Bucket"]
            rule["condition"] = json.dumps(cond)
            json.dump(rule, open(p, "w"))
        r = self._broken(m)
        self.assertEqual(r.returncode, 2)
        self.assertIn("bucket name", r.stdout)


def load_rel(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class TestConfigShapes(unittest.TestCase):
    def test_condition_matches_object_create(self):
        rule = load("config/events-rule.json")
        cond = json.loads(rule["condition"])
        self.assertEqual(cond["eventType"], ["com.oraclecloud.objectstorage.createobject"])

    def test_action_is_notifications(self):
        rule = load("config/events-rule.json")
        action = rule["actions"]["actions"][0]
        self.assertEqual(action["actionType"], "ONS")

    def test_subscription_is_email(self):
        topic = load("config/notifications-topic.json")
        self.assertEqual(topic["subscription"]["protocol"], "EMAIL")


class TestAssets(unittest.TestCase):
    def test_architecture_svg_wellformed(self):
        path = os.path.join(BASE, "assets", "architecture.svg")
        root = ET.parse(path).getroot()
        self.assertTrue(root.tag.endswith("svg"))

    def test_setup_doc_keeps_emit_events_prerequisite(self):
        with open(os.path.join(BASE, "docs", "setup.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("object-events-enabled", text)
        self.assertIn("same compartment", text)

    def test_readme_mentions_not_deployed(self):
        with open(os.path.join(BASE, "README.md"), encoding="utf-8") as fh:
            text = fh.read().lower()
        self.assertIn("not deployed", text)


if __name__ == "__main__":
    unittest.main()
