"""Offline guardrails for the LB1284 Insights platform upload path.

Run with: python3 -m unittest discover -s <this directory> -v
Requires PyYAML, also used by Ansible tooling.
"""
import unittest
from pathlib import Path

import yaml


ROLE = Path(__file__).resolve().parents[1]


def flatten(tasks):
    for task in tasks:
        yield task
        for key in ("block", "rescue", "always"):
            yield from flatten(task.get(key, []))


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROLE / "tasks/register_node.yml").read_text()
        cls.tasks = list(flatten(yaml.safe_load(cls.source)))

    def find(self, suffix):
        matches = [task for task in self.tasks if task.get("name", "").endswith(suffix)]
        self.assertEqual(len(matches), 1, suffix)
        return matches[0]

    def test_protocol_config_precedes_rhc(self):
        config = self.find("Use the Insights platform upload protocol")
        rhc = self.find("Connect to Red Hat account via RHC")
        self.assertLess(self.tasks.index(config), self.tasks.index(rhc))
        options = config["ansible.builtin.lineinfile"]
        self.assertEqual(options["line"], "legacy_upload=False")
        self.assertTrue(options["backup"])
        self.assertNotIn("base_url=", self.source)
        self.assertNotIn("auto_config=False", self.source)
        self.assertNotIn("cert_verify=False", self.source)

    def test_tags_precede_explicit_upload_and_readiness(self):
        tags = self.find("Write custom tags for lab grouping")
        upload = self.find("Upload the report and lab tags to Insights")
        inventory = self.find("Wait for Insights registration")
        advisor = self.find("Wait for Advisor to process the report")
        self.assertLess(self.tasks.index(tags), self.tasks.index(upload))
        self.assertLess(self.tasks.index(upload), self.tasks.index(inventory))
        self.assertLess(self.tasks.index(inventory), self.tasks.index(advisor))
        self.assertIn("group: {{ guid }}", tags["ansible.builtin.copy"]["content"])
        self.assertEqual(upload["ansible.builtin.command"]["cmd"],
                         "timeout --kill-after=10s 180s insights-client")
        self.assertNotIn("failed_when", upload)  # Keep normal command failure handling.
        self.assertNotIn("ignore_errors", upload)

    def test_no_legacy_systems_or_group_commands(self):
        for task in self.tasks:
            command = task.get("ansible.builtin.command", {}).get("cmd", "")
            self.assertNotIn("--group", command)
            uri = task.get("ansible.builtin.uri", {})
            self.assertNotIn("/r/insights/v1/systems", uri.get("url", ""))
        self.assertNotIn("_insights_group", self.source)
        self.assertNotIn("_insights_legacy_registration", self.source)

    def test_advisor_matches_exact_inventory_uuid_with_tls(self):
        task = self.find("Wait for Advisor to process the report")
        uri = task["ansible.builtin.uri"]
        self.assertIn("/platform/insights/v1/system/", uri["url"])
        self.assertTrue(uri["url"].rstrip().endswith("}}/"))
        self.assertEqual(uri["ca_path"], "/etc/insights-client/cert-api.access.redhat.com.pem")
        self.assertIsNot(uri.get("validate_certs"), False)
        self.assertEqual(uri["follow_redirects"], "none")
        self.assertFalse(uri["use_netrc"])
        self.assertIn("system_uuid", task["failed_when"])
        self.assertIn("_insights_inventory_id", task["failed_when"])
        self.assertNotIn("ignore_errors", task)
        self.assertTrue(task["no_log"])

    def test_fail_closed_rescue_has_sanitized_diagnostics(self):
        failure = self.find("Report Insights upload or processing failure")
        msg = failure["ansible.builtin.fail"]["msg"]
        for text in ("Upload return code", "Last inventory HTTP status", "Last Advisor HTTP status"):
            self.assertIn(text, msg)
        self.assertNotIn("stdout", msg)
        self.assertNotIn("password", msg)

    def test_rhc_credentials_still_hidden_without_redundant_override(self):
        task = self.find("Connect to Red Hat account via RHC")
        self.assertTrue(task["no_log"])
        self.assertNotIn("failed_when", task)


if __name__ == "__main__":
    unittest.main()
