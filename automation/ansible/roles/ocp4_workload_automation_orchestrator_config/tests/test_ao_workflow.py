#!/usr/bin/env python3
"""Offline tests for the AO workflow wiring filters.

Runs against the real exported workflow JSON in ../files/workflows and
the real binding files in ../vars, with every run-time ID faked. No AO
or AAP instance required:

    python3 tests/test_ao_workflow.py
"""

import collections
import copy
import json
import os
import sys
import unittest

ROLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The filters live at the COLLECTION level, not in the role: a role's
# own filter_plugins/ is never loaded once the role ships inside a
# collection.
COLLECTION_DIR = os.path.dirname(os.path.dirname(ROLE_DIR))
sys.path.insert(0, os.path.join(COLLECTION_DIR, "plugins", "filter"))

import yaml  # noqa: E402

from ao_workflow import (  # noqa: E402
    AOWiringError,
    ao_collection,
    ao_name_id_map,
    ao_prepare_definition,
    ao_required_job_templates,
    ao_student_bindings,
    ao_student_gaps,
    ao_student_variant,
    ao_validation_summary,
    ao_wire_definition,
)

UUID = "00000000-0000-4000-8000-%012d"


def load_workflow(filename):
    path = os.path.join(ROLE_DIR, "files", "workflows", filename)
    with open(path) as handle:
        return json.load(handle)


def load_bindings(key):
    path = os.path.join(ROLE_DIR, "vars", "bindings_%s.yml" % key)
    with open(path) as handle:
        return yaml.safe_load(handle)["ao_workflow_bindings"]


def fake_resolved(job_template_names, tools=None):
    return {
        "credentials": {
            "llm": UUID % 1,
            "aap": UUID % 2,
            "aap_mcp": UUID % 3,
            "openflake_mcp": UUID % 4,
            "lightspeed_mcp": UUID % 5,
        },
        "integrations": {
            "llm": UUID % 10,
            "aap": UUID % 11,
            "aap_mcp": UUID % 12,
            "openflake_mcp": UUID % 13,
            "lightspeed_mcp": UUID % 14,
        },
        "integration_credentials": {
            "llm": "llm",
            "aap": "aap",
            "aap_mcp": "aap_mcp",
            "openflake_mcp": "openflake_mcp",
            "lightspeed_mcp": "lightspeed_mcp",
        },
        "tools": tools or {},
        "job_templates": {
            name: 100 + index for index, name in enumerate(sorted(job_template_names))
        },
        # Keyed the same way credentials and integrations are. Both
        # accounts the role mints are present, because the point of
        # the key is that a binding file can name the wrong one: only
        # `solutions_webhooks` shares a project with these workflows,
        # and AO 422s a trigger authorized for an account outside it.
        "service_accounts": {
            "solutions_webhooks": UUID % 50,
            "student_webhooks": UUID % 51,
        },
        "llm_model_id": UUID % 20,
        "organization": "Default",
        # Provision-time values prefilled into a trigger's input schema.
        # The guid gets a component-index suffix on a multi-component
        # catalog item, so the fixture carries one: nothing here may
        # assume a bare five characters.
        "trigger_defaults": {"lab_tag": "abc12-1"},
    }


# Every tool the CVE bindings pin, plus one spare per integration so
# that "pinned a tool the server does not expose" stays distinguishable
# from "the fixture is short".
CVE_TOOLS = {
    "lightspeed_mcp": {
        "advisor__get_hosts_hitting_a_rule": UUID % 20,
        "advisor__get_recommendations_stats": UUID % 21,
        "advisor__get_rule_details": UUID % 22,
        "content-sources__list_repositories": UUID % 23,
        "inventory__get_host_details": UUID % 24,
        "inventory__get_host_system_profile": UUID % 25,
        "inventory__get_host_tags": UUID % 26,
        "inventory__list_hosts": UUID % 27,
        "vulnerability__get_cve_systems": UUID % 30,
        "vulnerability__get_cve": UUID % 31,
    },
    "aap_mcp": {
        "hosts_list": UUID % 32,
        "hosts_variable_data_retrieve": UUID % 33,
        "groups_list": UUID % 34,
        "inventories_list": UUID % 35,
        "jobs_list": UUID % 36,
    },
}


class TestPrepare(unittest.TestCase):
    def test_cve_export_keeps_its_own_metadata(self):
        raw = load_workflow("rhel-cve-remediation.json")
        definition = ao_prepare_definition(raw, "Fallback Name", "Fallback desc")

        self.assertEqual(definition["schema_version"], "2.0.0")
        # The export names itself; the fallback must not clobber it.
        self.assertNotEqual(definition["name"], "Fallback Name")
        self.assertEqual(len(definition["nodes"]), 13)
        self.assertEqual(len(definition["edges"]), 13)
        self.assertEqual(len(definition["triggers"]), 1)

    def test_no_node_waits_on_more_than_one_edge(self):
        # AO skips a node unless every inbound edge fires, so a node fed
        # by two mutually exclusive branches never runs. investigate_agent
        # was wired from both case_2 and default and sat dead for the
        # whole of its life; nothing caught it because the branch was
        # never reached. Converging branches need one node each.
        for name in (
            "rhel-cve-remediation.json",
            "disk-utilization-remediation.json",
            "ticket-enrichment.json",
        ):
            raw = load_workflow(name)
            inbound = collections.Counter(e["to"] for e in raw["edges"])
            joins = {node: n for node, n in inbound.items() if n > 1}
            self.assertEqual(joins, {}, f"{name} has join nodes: {joins}")

    def test_triage_scopes_the_cve_lookup_by_insights_tag(self):
        # The lab tag is an Insights TAG, not a substring of a display
        # name. Display names in this lab are bare ("node1") and every
        # other lab on the account reuses them, so neither field alone
        # identifies a host. A prompt that goes back to
        # get_cve_systems(filter_=<tag>) gets zero rows and reports
        # every host as unaffected -- which is exactly what it did.
        raw = load_workflow("rhel-cve-remediation.json")
        prompt = next(
            n for n in raw["nodes"] if n["id"] == "triage_agent"
        )["parameters"]["prompt"]
        self.assertIn("inventory__list_hosts", prompt)
        self.assertIn("insights-client/group=", prompt)
        self.assertIn("system_uuid", prompt)
        self.assertIn("Do NOT pass filter_", prompt)

    def test_triage_handles_both_display_name_shapes(self):
        # A node registers in Insights as the bare hostname or as a
        # fully qualified one, and it flips between them: node1 was
        # `node1` at 16:07 and
        # `node1.lab.sandbox-vqbwv-ocp4-cluster.svc.cluster.local` at
        # 16:12, after the remediation rebooted it. The inventory UUID
        # held. display_name is a substring filter so one query finds
        # either, but the prompt has to say how to pick a row, or
        # "exactly one host" is luck rather than a rule.
        raw = load_workflow("rhel-cve-remediation.json")
        prompt = next(
            n for n in raw["nodes"] if n["id"] == "triage_agent"
        )["parameters"]["prompt"]
        self.assertIn("SUBSTRING", prompt)
        self.assertIn("reboots", prompt)
        self.assertIn("starts with", prompt)

    def test_disk_export_gets_synthesised_metadata(self):
        raw = load_workflow("disk-utilization-remediation.json")
        self.assertNotIn("name", raw)
        self.assertNotIn("schema_version", raw)

        definition = ao_prepare_definition(
            raw, "Disk Utilization Remediation", "Branch on disk usage."
        )
        self.assertEqual(definition["name"], "Disk Utilization Remediation")
        self.assertEqual(definition["schema_version"], "2.0.0")
        self.assertEqual(definition["description"], "Branch on disk usage.")
        self.assertEqual(len(definition["nodes"]), 10)

    def test_placeholder_credential_ids_are_stripped(self):
        raw = load_workflow("disk-utilization-remediation.json")
        poisoned = [
            node["id"]
            for node in raw["nodes"]
            if (node.get("parameters") or {}).get("credential_id")
            == "YOUR_AAP_CREDENTIAL_ID"
        ]
        self.assertEqual(len(poisoned), 9, "fixture should carry 9 placeholders")

        definition = ao_prepare_definition(raw, "Disk")
        for node in definition["nodes"]:
            self.assertNotIn(
                "credential_id",
                node.get("parameters", {}),
                "%s still carries a placeholder credential_id" % node["id"],
            )

    def test_prepare_does_not_mutate_input(self):
        raw = load_workflow("disk-utilization-remediation.json")
        ao_prepare_definition(raw, "Disk")
        self.assertEqual(
            raw["nodes"][0]["parameters"]["credential_id"], "YOUR_AAP_CREDENTIAL_ID"
        )


class TestRequiredJobTemplates(unittest.TestCase):
    def test_cve_skips_runtime_expressions(self):
        definition = ao_prepare_definition(
            load_workflow("rhel-cve-remediation.json"), "CVE"
        )
        names = ao_required_job_templates(
            definition, load_bindings("rhel_cve_remediation")
        )
        self.assertEqual(
            sorted(names),
            [
                "CVE - Fetch and Commit",
                "CVE - Notify Mattermost Investigation",
                "CVE - Sync and Deploy Remediation",
            ],
        )
        # run_cve_remediation* use ${...artifacts.template_name}.
        for name in names:
            self.assertNotIn("${", name)

    def test_disk_requires_six_distinct_templates(self):
        definition = ao_prepare_definition(
            load_workflow("disk-utilization-remediation.json"), "Disk"
        )
        names = ao_required_job_templates(definition, load_bindings("disk_utilization"))
        self.assertEqual(
            sorted(names),
            [
                "Disk Utilization - Fallback",
                "Disk Utilization Check",
                "Linux - Remediate - Continue",
                "Linux - Remediate - Disk Cleanup",
                "Linux - Remediate - Disk Expand",
                "Notify Chatroom",
            ],
        )


class TestWireCVE(unittest.TestCase):
    def setUp(self):
        self.definition = ao_prepare_definition(
            load_workflow("rhel-cve-remediation.json"), "CVE"
        )
        self.bindings = load_bindings("rhel_cve_remediation")
        self.resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings), CVE_TOOLS
        )
        self.wired = ao_wire_definition(self.definition, self.bindings, self.resolved)
        self.nodes = {node["id"]: node for node in self.wired["nodes"]}

    def test_every_wired_node_is_covered(self):
        # A node missing from the binding file must raise, not pass.
        for node in self.wired["nodes"]:
            if node["type"] in ("agentic", "aap_job_template"):
                self.assertIn("credential_id", node["parameters"], node["id"])

    def test_agentic_node_gets_model_and_pinned_tools(self):
        triage = self.nodes["triage_agent"]["parameters"]
        self.assertEqual(triage["llm_model_id"], UUID % 20)
        self.assertEqual(triage["credential_id"], UUID % 1)
        self.assertEqual(triage["tool_selection_strategy"], "SELECTED")
        self.assertEqual(len(triage["integration_connections"]), 2)

        # Named here for readability, asserted as the ids AO actually
        # wants — the UI resolves tool_selections against live tool ids
        # and silently drops anything else.
        expected = sorted(
            [
                CVE_TOOLS["lightspeed_mcp"][name]
                for name in (
                    "inventory__list_hosts",
                    "vulnerability__get_cve",
                    "vulnerability__get_cve_systems",
                )
            ]
            + [
                CVE_TOOLS["aap_mcp"][name]
                for name in (
                    "hosts_list",
                    "hosts_variable_data_retrieve",
                )
            ]
        )
        self.assertEqual(sorted(triage["tool_selections"]), expected)
        self.assertEqual(len(expected), 5)
        self.assertTrue(triage["tool_selections"], "must be non-empty for SELECTED")

    def _trigger_properties(self, wired=None):
        trigger = (wired or self.wired)["triggers"][0]
        return trigger["parameters"]["input_schema"]["properties"]

    def test_manual_trigger_prefills_the_lab_tag(self):
        # The student should not have to go read
        # /etc/insights-client/tags.yaml to fill in their own guid.
        self.assertEqual(self._trigger_properties()["lab_tag"]["default"], "abc12-1")

    def test_prefilling_leaves_the_input_required_and_editable(self):
        # A default is a prefill, not a lock: the field stays required
        # so AO still renders and validates it, and the student can
        # still point the run at another lab's tag.
        trigger = self.wired["triggers"][0]
        schema = trigger["parameters"]["input_schema"]
        self.assertIn("lab_tag", schema["required"])
        self.assertEqual(schema["properties"]["lab_tag"]["type"], "string")
        self.assertEqual(trigger["type"], "manual_trigger")

    def test_only_the_bound_input_is_prefilled(self):
        # Choosing the host and the CVE is the exercise; prefilling
        # either would hand the student the answer.
        properties = self._trigger_properties()
        self.assertEqual(properties["cve_id"]["default"], "")
        # host's default ships in the export and must survive untouched.
        self.assertEqual(properties["host"]["default"], "node1")

    def test_an_unresolved_lab_tag_leaves_the_export_default(self):
        # guid is undefined outside AgnosticD, where the role default
        # folds to "". Writing that back is no improvement on the
        # export and would read as "a value was known".
        resolved = copy.deepcopy(self.resolved)
        resolved["trigger_defaults"] = {"lab_tag": ""}
        wired = ao_wire_definition(self.definition, self.bindings, resolved)
        self.assertEqual(self._trigger_properties(wired)["lab_tag"]["default"], "")

    def test_prefilling_an_undeclared_input_is_rejected(self):
        # A re-export that renames an input must rename it in the
        # binding too, or the prefill silently stops happening.
        bindings = copy.deepcopy(self.bindings)
        bindings["triggers"]["trigger_manual"]["input_defaults"] = ["lab_tags"]
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, bindings, self.resolved)
        self.assertIn("lab_tags", str(caught.exception))
        self.assertIn("input_schema", str(caught.exception))

    def test_prefill_without_a_resolved_value_is_rejected(self):
        # Dropping trigger_defaults from the set_fact must fail the
        # provision, not quietly ship an empty field.
        resolved = copy.deepcopy(self.resolved)
        del resolved["trigger_defaults"]
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, self.bindings, resolved)
        self.assertIn("lab_tag", str(caught.exception))

    def test_every_connection_carries_both_ids(self):
        # AO rejects a bare {integration_id} with "'credential_id' is a
        # required property". Lightspeed MCP is the interesting case: it
        # has no management credential and still needs one here.
        triage = self.nodes["triage_agent"]["parameters"]
        self.assertEqual(
            triage["integration_connections"],
            [
                {"integration_id": UUID % 14, "credential_id": UUID % 5},
                {"integration_id": UUID % 12, "credential_id": UUID % 3},
            ],
        )

    def test_unmapped_integration_credential_raises(self):
        resolved = dict(self.resolved)
        resolved["integration_credentials"] = {"aap_mcp": "aap_mcp"}
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, self.bindings, resolved)
        self.assertIn("lightspeed_mcp", str(caught.exception))

    def test_tool_selections_are_bare_id_strings(self):
        # Two regressions in one. AO 500s on every object shape, so each
        # entry must be a bare string — and the string must be the
        # tool's id. Sending names passes AO's schema and the publish
        # gate, then the UI drops every one of them as "no longer
        # available", which is how this shipped broken.
        known = {tid for tools in CVE_TOOLS.values() for tid in tools.values()}
        names = {name for tools in CVE_TOOLS for name in CVE_TOOLS[tools]}
        for node in self.wired["nodes"]:
            for selection in node.get("parameters", {}).get("tool_selections", []):
                self.assertIsInstance(selection, str, node["id"])
                self.assertIn(selection, known, node["id"])
                self.assertNotIn(selection, names, node["id"])

    def test_strategy_none_sends_no_tool_selections(self):
        # AO's enum is ALL|NONE|SELECTED and SELECTED with an empty list is
        # rejected, so a toolless node must be NONE — and the key must be
        # absent, matching what AO's own UI sends. Both shipped agents pin
        # tools, so build the NONE case rather than borrowing one.
        bindings = copy.deepcopy(self.bindings)
        node = bindings["nodes"]["investigate_agent"]
        node["tool_selection_strategy"] = "NONE"
        node.pop("tools", None)
        wired = ao_wire_definition(self.definition, bindings, self.resolved)
        investigate = {n["id"]: n for n in wired["nodes"]}["investigate_agent"][
            "parameters"
        ]
        self.assertEqual(investigate["tool_selection_strategy"], "NONE")
        self.assertNotIn("tool_selections", investigate)
        # It still connects to both integrations, and still needs a model
        # and a credential.
        self.assertEqual(len(investigate["integration_connections"]), 2)
        self.assertEqual(investigate["llm_model_id"], UUID % 20)

    def test_shipped_agents_both_pin_tools(self):
        # The investigate branch reaches its agent with nothing gathered,
        # so it does its own lookups; neither agent may run toolless.
        for node_id in ("triage_agent", "investigate_agent"):
            params = self.nodes[node_id]["parameters"]
            self.assertEqual(params["tool_selection_strategy"], "SELECTED", node_id)
            self.assertTrue(params["tool_selections"], node_id)

    def test_tools_all_expands_to_whole_surface(self):
        bindings = copy.deepcopy(self.bindings)
        node = bindings["nodes"]["investigate_agent"]
        node["tool_selection_strategy"] = "SELECTED"
        node["tools_all"] = ["lightspeed_mcp", "aap_mcp"]
        wired = ao_wire_definition(self.definition, bindings, self.resolved)
        investigate = {n["id"]: n for n in wired["nodes"]}["investigate_agent"]
        self.assertEqual(
            sorted(investigate["parameters"]["tool_selections"]),
            sorted(
                list(CVE_TOOLS["lightspeed_mcp"].values())
                + list(CVE_TOOLS["aap_mcp"].values())
            ),
        )

    def test_strategy_none_with_tools_is_rejected(self):
        bindings = copy.deepcopy(self.bindings)
        node = bindings["nodes"]["investigate_agent"]
        node["tool_selection_strategy"] = "NONE"
        node["tools"] = {"aap_mcp": ["hosts_list"]}
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, bindings, self.resolved)
        self.assertIn("NONE", str(caught.exception))

    def test_unknown_strategy_is_rejected(self):
        bindings = copy.deepcopy(self.bindings)
        bindings["nodes"]["investigate_agent"]["tool_selection_strategy"] = "EVERY"
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, bindings, self.resolved)
        self.assertIn("EVERY", str(caught.exception))

    def test_static_job_template_resolves_to_id(self):
        fetch = self.nodes["fetch_and_commit"]["parameters"]
        self.assertEqual(fetch["job_template_name"], "CVE - Fetch and Commit")
        self.assertIn("job_template_id", fetch)
        self.assertEqual(fetch["integration_id"], UUID % 11)

    def test_expression_job_template_gets_no_id(self):
        run = self.nodes["run_cve_remediation"]["parameters"]
        self.assertIn("${", run["job_template_name"])
        self.assertNotIn(
            "job_template_id", run, "a runtime expression must not be resolved here"
        )
        # It still needs a credential and integration.
        self.assertEqual(run["credential_id"], UUID % 2)
        self.assertEqual(run["integration_id"], UUID % 11)

    def test_self_contained_nodes_untouched(self):
        for node_id, node_type in (
            ("route_switch", "switch"),
            ("approval_prod", "approval"),
        ):
            node = self.nodes[node_id]
            self.assertEqual(node["type"], node_type)
            self.assertNotIn("credential_id", node.get("parameters", {}))

    def test_extra_vars_are_preserved(self):
        deploy = self.nodes["deploy_script"]["parameters"]
        self.assertEqual(
            deploy["extra_vars"]["playbook_filename"],
            "${fetch_and_commit.artifacts.playbook_filename}",
        )


class TestWireDisk(unittest.TestCase):
    def setUp(self):
        self.definition = ao_prepare_definition(
            load_workflow("disk-utilization-remediation.json"), "Disk"
        )
        self.bindings = load_bindings("disk_utilization")
        self.resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings)
        )
        self.wired = ao_wire_definition(self.definition, self.bindings, self.resolved)

    def test_all_nine_aap_nodes_wired_with_real_uuids(self):
        aap_nodes = [n for n in self.wired["nodes"] if n["type"] == "aap_job_template"]
        self.assertEqual(len(aap_nodes), 9)
        for node in aap_nodes:
            params = node["parameters"]
            self.assertEqual(params["credential_id"], UUID % 2)
            self.assertEqual(params["integration_id"], UUID % 11)
            self.assertIn("job_template_id", params)
            self.assertNotEqual(params["credential_id"], "YOUR_AAP_CREDENTIAL_ID")

    def test_switch_conditions_survive(self):
        switch = [n for n in self.wired["nodes"] if n["type"] == "switch"][0]
        self.assertEqual(len(switch["parameters"]["cases"]), 3)

    def test_no_llm_assets_needed(self):
        # Wiring must succeed with no LLM or MCP assets resolved at all.
        resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings)
        )
        resolved["integrations"] = {"aap": UUID % 11}
        resolved["credentials"] = {"aap": UUID % 2}
        resolved["llm_model_id"] = None
        ao_wire_definition(self.definition, self.bindings, resolved)

    def test_webhook_trigger_is_authorized_for_the_service_account(self):
        # Also catches the export and the binding file drifting apart:
        # the trigger id is hand-written in bindings_disk_utilization.yml,
        # and an id that matches nothing in the export leaves the
        # trigger unwired, which AO rejects at import.
        trigger = self.wired["triggers"][0]
        self.assertEqual(trigger["type"], "webhook_trigger")
        self.assertEqual(
            trigger["parameters"]["authorized_service_account_ids"], [UUID % 50]
        )
        self.assertEqual(
            trigger["parameters"]["webhook_path"], "disk-utilization"
        )
        # The solutions account, not the student one — see
        # TestWireTicketEnrichment.test_binding_names_the_solutions_account.
        self.assertEqual(
            self.bindings["triggers"][trigger["id"]]["service_accounts"],
            ["solutions_webhooks"],
        )

    def test_check_node_sends_no_simulated_percentage(self):
        # The premise of the whole scenario: AAP fills the disk for
        # real and the check step measures it. A `test_disk_use_percent`
        # here puts the faked number back and the switch stops reading
        # reality — which is easy to reintroduce, because re-exporting
        # from the AO UI after a manual test carries it along.
        check = [
            n for n in self.wired["nodes"]
            if n["parameters"].get("job_template_name") == "Disk Utilization Check"
        ]
        self.assertEqual(len(check), 1)
        self.assertNotIn(
            "test_disk_use_percent", check[0]["parameters"].get("extra_vars", {})
        )


TICKET_TOOLS = {
    "openflake_mcp": {
        "perform_query": UUID % 40,
        "add_comment": UUID % 41,
    },
    "aap_mcp": {
        "job_templates_list": UUID % 42,
        "hosts_list": UUID % 43,
    },
}


class TestWireTicketEnrichment(unittest.TestCase):
    def setUp(self):
        self.definition = ao_prepare_definition(
            load_workflow("ticket-enrichment.json"), "Ticket Enrichment Demo"
        )
        self.bindings = load_bindings("ticket_enrichment")
        self.resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings), TICKET_TOOLS
        )
        self.wired = ao_wire_definition(self.definition, self.bindings, self.resolved)

    def test_every_wired_node_is_covered(self):
        # The binding file must name every agentic and aap_job_template
        # node in the export; a missing one raises, so reaching setUp
        # already proves it. This pins the counts so a re-export that
        # adds a node fails here rather than at provision time.
        types = [n["type"] for n in self.wired["nodes"]]
        self.assertEqual(types.count("agentic"), 2)
        self.assertEqual(types.count("aap_job_template"), 6)

    def test_webhook_trigger_survives_wiring(self):
        # The solutions copy of the path. `student-openflake-incident`
        # is the student's, created by hand in module 03 — a re-export
        # that brought that path in here would mean the two workflows
        # had been confused.
        triggers = self.wired["triggers"]
        self.assertEqual(len(triggers), 1)
        self.assertEqual(triggers[0]["type"], "webhook_trigger")
        self.assertEqual(
            triggers[0]["parameters"]["webhook_path"], "openflake-incident"
        )

    def test_webhook_trigger_is_authorized_for_the_service_account(self):
        # The export ships no authorized_service_account_ids, and AO
        # rejects the workflow without one: a measured import returned
        # is_valid=False with "'authorized_service_account_ids' is a
        # required property" against this exact trigger id.
        params = self.wired["triggers"][0]["parameters"]
        self.assertEqual(params["authorized_service_account_ids"], [UUID % 50])

    def test_binding_names_the_solutions_account(self):
        # The key is load-bearing, not cosmetic. Both accounts resolve,
        # so swapping this to `student_webhooks` wires perfectly
        # cleanly here and then fails at import — AO 422s a trigger
        # authorized for an account outside the workflow's project.
        # Pinned so that swap has to be deliberate.
        bindings = copy.deepcopy(self.bindings)
        trigger_id = next(iter(bindings["triggers"]))
        self.assertEqual(
            bindings["triggers"][trigger_id]["service_accounts"],
            ["solutions_webhooks"],
        )
        bindings["triggers"][trigger_id]["service_accounts"] = ["student_webhooks"]
        wired = ao_wire_definition(self.definition, bindings, self.resolved)
        self.assertEqual(
            wired["triggers"][0]["parameters"]["authorized_service_account_ids"],
            [UUID % 51],
        )

    def test_unknown_service_account_key_is_rejected(self):
        # A typo or a key renamed in defaults/main.yml without the
        # binding following it.
        bindings = copy.deepcopy(self.bindings)
        trigger_id = next(iter(bindings["triggers"]))
        bindings["triggers"][trigger_id]["service_accounts"] = ["webhooks"]
        with self.assertRaises(AOWiringError):
            ao_wire_definition(self.definition, bindings, self.resolved)

    def test_trigger_without_a_service_account_is_rejected(self):
        # AO rejects an empty list too ("[] should be non-empty"), so
        # wiring one is never the right answer — fail here instead,
        # where the message names the trigger.
        bindings = copy.deepcopy(self.bindings)
        trigger_id = next(iter(bindings["triggers"]))
        bindings["triggers"][trigger_id]["service_accounts"] = []
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, bindings, self.resolved)
        self.assertIn("authorizes no service accounts", str(caught.exception))

    def test_trigger_fails_when_the_service_account_was_not_created(self):
        # The symptom when the service account phase runs after the
        # workflow phase, which is how this was ordered originally.
        resolved = copy.deepcopy(self.resolved)
        resolved["service_accounts"] = {}
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, self.bindings, resolved)
        self.assertIn("must run", str(caught.exception))

    def test_unbound_http_trigger_is_rejected(self):
        # A re-export that adds a webhook or EDA trigger must not slip
        # through unwired just because the binding file wasn't updated.
        definition = copy.deepcopy(self.definition)
        definition["triggers"][0]["id"] = "activity_brand_new_trigger"
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(definition, self.bindings, self.resolved)
        self.assertIn("no entry under `triggers:`", str(caught.exception))

    def test_agents_get_pinned_tools_as_id_strings(self):
        agents = {n["id"]: n["parameters"] for n in self.wired["nodes"]
                  if n["type"] == "agentic"}

        # These two agents are exactly where the live lab reported "2
        # previously selected tools are no longer available" and "1 ...
        # no longer available": both had been wired with names.
        triage = agents["triage_agent"]
        self.assertEqual(triage["llm_model_id"], UUID % 20)
        self.assertEqual(
            sorted(triage["tool_selections"]),
            sorted([TICKET_TOOLS["aap_mcp"]["job_templates_list"],
                    TICKET_TOOLS["openflake_mcp"]["perform_query"]]),
        )

        # The inform-only agent is read-only and needs OpenFlake alone.
        enrich = agents["enrich_and_assign_agent"]
        self.assertEqual(
            enrich["tool_selections"], [TICKET_TOOLS["openflake_mcp"]["perform_query"]]
        )
        self.assertEqual(
            [c["integration_id"] for c in enrich["integration_connections"]],
            [UUID % 13],
        )

    def test_only_the_update_template_is_required(self):
        # The two remediation nodes launch whichever template the triage
        # agent names, so they must not demand a static resolution.
        required = ao_required_job_templates(self.definition, self.bindings)
        self.assertEqual(sorted(required), ["Incidents | Update Ticket"])

    def test_dynamic_remediation_nodes_get_no_job_template_id(self):
        by_id = {n["id"]: n["parameters"] for n in self.wired["nodes"]}
        for node_id in ("auto_remediation_job", "remediation_job_approved"):
            self.assertNotIn("job_template_id", by_id[node_id])
            self.assertEqual(by_id[node_id]["credential_id"], UUID % 2)

    def test_all_four_update_nodes_resolve_the_same_template(self):
        update_ids = [
            params["job_template_id"]
            for params in (n["parameters"] for n in self.wired["nodes"])
            if params.get("job_template_name") == "Incidents | Update Ticket"
        ]
        self.assertEqual(len(update_ids), 4)
        self.assertEqual(len(set(update_ids)), 1)


class TestFailureModes(unittest.TestCase):
    def setUp(self):
        self.definition = ao_prepare_definition(
            load_workflow("rhel-cve-remediation.json"), "CVE"
        )
        self.bindings = load_bindings("rhel_cve_remediation")

    def test_missing_job_template_names_the_node(self):
        resolved = fake_resolved([], CVE_TOOLS)
        with self.assertRaises(AOWiringError) as ctx:
            ao_wire_definition(self.definition, self.bindings, resolved)
        self.assertIn("job template", str(ctx.exception))

    def test_missing_binding_entry_is_an_error(self):
        bindings = {"nodes": dict(self.bindings["nodes"])}
        del bindings["nodes"]["fetch_and_commit"]
        resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings), CVE_TOOLS
        )
        with self.assertRaises(AOWiringError) as ctx:
            ao_wire_definition(self.definition, bindings, resolved)
        self.assertIn("fetch_and_commit", str(ctx.exception))

    def test_unknown_tool_is_rejected(self):
        bindings = {"nodes": dict(self.bindings["nodes"])}
        bindings["nodes"]["triage_agent"] = dict(bindings["nodes"]["triage_agent"])
        bindings["nodes"]["triage_agent"]["tools"] = {
            "lightspeed_mcp": ["tool_that_does_not_exist"]
        }
        resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings), CVE_TOOLS
        )
        with self.assertRaises(AOWiringError) as ctx:
            ao_wire_definition(self.definition, bindings, resolved)
        self.assertIn("tool_that_does_not_exist", str(ctx.exception))

    def test_empty_tools_with_selected_strategy_is_rejected(self):
        # An integration that exposed nothing after refresh must fail
        # tools_all rather than emit the empty list AO rejects. Pinned
        # tools can no longer reach this: every agentic node in the CVE
        # bindings is now either explicitly pinned or NONE, so the case
        # is set up directly.
        bindings = copy.deepcopy(self.bindings)
        node = bindings["nodes"]["investigate_agent"]
        node["tool_selection_strategy"] = "SELECTED"
        node["tools_all"] = ["lightspeed_mcp"]
        # Silence the other agent. With an empty tool surface its pinned
        # selections now fail first — correctly, but that is the
        # neighbouring test's business, not this one's.
        triage = bindings["nodes"]["triage_agent"]
        triage["tool_selection_strategy"] = "NONE"
        triage.pop("tools", None)
        resolved = fake_resolved(
            ao_required_job_templates(self.definition, bindings), {}
        )
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, bindings, resolved)
        self.assertIn("exposed none", str(caught.exception))

    def test_pinned_tool_on_an_empty_surface_is_rejected(self):
        # The counterpart: a pinned tool against an integration that
        # exposed nothing used to be selected anyway, with a null id.
        # AO accepts that and the UI drops it later, so it must fail here.
        resolved = fake_resolved(
            ao_required_job_templates(self.definition, self.bindings), {}
        )
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, self.bindings, resolved)
        self.assertIn("which exposes: (none)", str(caught.exception))


class TestStudentGapsFile(unittest.TestCase):
    """files/student_gaps.yml, as the role and the harnesses read it."""

    def setUp(self):
        path = os.path.join(ROLE_DIR, "files", "student_gaps.yml")
        with open(path) as handle:
            self.document = yaml.safe_load(handle)
        self.merged = ao_student_gaps(self.document)

    def test_every_workflow_in_defaults_has_a_gap(self):
        # A workflow with no entry would import into `default` fully
        # wired — a finished workflow handed over as an exercise, and
        # nothing would say so.
        path = os.path.join(ROLE_DIR, "defaults", "main.yml")
        with open(path) as handle:
            defaults = yaml.safe_load(handle)
        keys = {w["key"] for w in defaults[
            "ocp4_workload_automation_orchestrator_config_workflows"]}
        self.assertEqual(keys, set(self.merged))

    def test_common_settings_reach_every_entry(self):
        for key, gap in self.merged.items():
            self.assertEqual(gap["student_credentials"], ["llm"],
                             "%s lost student_credentials" % key)
            self.assertEqual(gap["student_integrations"], ["aap_mcp"],
                             "%s lost student_integrations" % key)
            self.assertEqual(gap["webhook_path_prefix"], "student-",
                             "%s lost webhook_path_prefix" % key)

    def test_a_per_workflow_key_beats_the_common_one(self):
        # The merge got this backwards once in Jinja, which is why it
        # lives in the filter now. Common must not clobber an entry.
        merged = ao_student_gaps({
            "ao_student_common": {"webhook_path_prefix": "student-"},
            "ao_student_gaps": {"x": {"webhook_path_prefix": "other-"}},
        })
        self.assertEqual(merged["x"]["webhook_path_prefix"], "other-")

    def test_missing_common_block_is_not_an_error(self):
        merged = ao_student_gaps({"ao_student_gaps": {"x": None}})
        self.assertEqual(merged, {"x": {}})


class TestStudentVariant(unittest.TestCase):
    """The copies that land in the student's `default` project.

    Generated from the same exports `solutions` uses, so these tests
    are the thing standing between a re-export and an exercise that
    quietly stopped existing.
    """

    # Which credentials provisioning creates in `default`. The LLM and
    # AAP MCP ones are the student's own work, so they are absent —
    # that absence is what blanks the agents, and a test that wires
    # against the full set would not be testing the student copy.
    STUDENT_PROJECT_CREDENTIALS = ("aap", "lightspeed_mcp", "openflake_mcp")

    def setUp(self):
        path = os.path.join(ROLE_DIR, "files", "student_gaps.yml")
        with open(path) as handle:
            self.gaps = ao_student_gaps(yaml.safe_load(handle))

    def _variant(self, filename, key, name):
        """Run the pipeline the role runs, both ways round.

        Returns (solutions, student). Both come off the same export,
        wired by the same pass; they differ only in the asset map and
        the gaps. Checking the student copy against a raw export would
        miss everything the wiring itself decides — which is most of
        it, now that the blank agents come from a missing credential
        rather than from an explicit gap.
        """
        definition = ao_prepare_definition(load_workflow(filename), name)
        bindings = load_bindings(key)
        gaps = self.gaps[key]
        tools = {}
        for fixture in (CVE_TOOLS, TICKET_TOOLS):
            for integration, listing in fixture.items():
                tools.setdefault(integration, {}).update(listing)

        solutions = ao_wire_definition(
            definition, bindings,
            fake_resolved(ao_required_job_templates(definition, bindings),
                          tools))

        student_bindings = ao_student_bindings(bindings, gaps)
        resolved = fake_resolved(
            ao_required_job_templates(definition, student_bindings), tools)
        resolved["credentials"] = {
            key_: value for key_, value in resolved["credentials"].items()
            if key_ in self.STUDENT_PROJECT_CREDENTIALS
        }
        student = ao_wire_definition(definition, student_bindings, resolved)
        return solutions, ao_student_variant(student, gaps)

    # --- Disk: build the >95% branch --------------------------------

    def test_disk_drops_only_the_over_95_branch(self):
        full, student = self._variant(
            "disk-utilization-remediation.json", "disk_utilization",
            "Disk Utilization Remediation",
        )
        self.assertEqual(len(full["nodes"]), 10)
        self.assertEqual(len(student["nodes"]), 8)
        names = {n.get("name") for n in student["nodes"]}
        # The branch the student builds is gone...
        self.assertNotIn("Remediate - Expand Disk", names)
        self.assertNotIn("Critical - Notify Chatroom - Expand Disk", names)
        # ...and the one they copy from is not.
        self.assertIn("Remediate  - Clean Disk", names)
        self.assertIn("Warn - Notify Chatroom - Clean Disk", names)

    def test_disk_leaves_exactly_one_switch_port_empty(self):
        # Three of four ports wired and one obviously empty is the
        # whole design: the student sees the shape they are copying one
        # port above the hole they are filling.
        _, student = self._variant(
            "disk-utilization-remediation.json", "disk_utilization",
            "Disk Utilization Remediation",
        )
        switch = next(n for n in student["nodes"] if n["type"] == "switch")
        wired = {
            e.get("from_port") for e in student["edges"]
            if e.get("from") == switch["id"]
        }
        ports = [c["port"] for c in switch["parameters"]["cases"]]
        ports.append(switch["parameters"]["default_port"])
        self.assertEqual(set(ports) - wired, {"case_2"})

    def test_dropping_a_node_takes_its_edges(self):
        _, student = self._variant(
            "disk-utilization-remediation.json", "disk_utilization",
            "Disk Utilization Remediation",
        )
        # Triggers are a sibling list of `nodes`, not members of it, so
        # the trigger -> first node edge points out of the node set by
        # design and has to be allowed for here.
        ids = {n["id"] for n in student["nodes"]}
        ids |= {t["id"] for t in student.get("triggers", [])}
        for edge in student["edges"]:
            self.assertIn(edge["from"], ids, edge)
            self.assertIn(edge["to"], ids, edge)

    # --- CVE: fill in the routing conditions ------------------------

    def test_cve_blanks_conditions_but_keeps_ports_and_labels(self):
        # Losing the labels would leave the student guessing how many
        # routes there are and what each one is for.
        full, student = self._variant(
            "rhel-cve-remediation.json", "rhel_cve_remediation",
            "RHEL CVE Remediation",
        )
        self.assertEqual(len(student["nodes"]), len(full["nodes"]))
        self.assertEqual(len(student["edges"]), len(full["edges"]))
        cases = next(
            n for n in student["nodes"] if n["type"] == "switch"
        )["parameters"]["cases"]
        self.assertEqual(
            [c["port"] for c in cases], ["case_0", "case_1", "case_2"]
        )
        self.assertTrue(all(c["label"] for c in cases))
        self.assertEqual([c["condition"] for c in cases], ["", "", ""])

    # --- Ticket: service account and tools --------------------------

    def test_ticket_triage_agent_keeps_openflake_and_loses_aap_mcp(self):
        # Reviewed in the UI on 2026-10-08: forcing this agent to NONE
        # was wrong. It took OpenFlake's perform_query down with the
        # AAP MCP tool, and NONE makes the UI draw the OpenFlake
        # connection as disabled — so the student was shown a server
        # that looked broken and was never asked to fix it. OpenFlake
        # is provisioning's, so it stays wired and pinned; only the
        # AAP MCP connection and its tool are the student's to add.
        solutions, student = self._variant(
            "ticket-enrichment.json", "ticket_enrichment",
            "Ticket Enrichment Demo",
        )
        triage = next(n for n in student["nodes"] if n["id"] == "triage_agent")
        params = triage["parameters"]
        self.assertEqual(params["tool_selection_strategy"], "SELECTED")

        openflake = UUID % 13
        aap_mcp = UUID % 12
        connected = {c["integration_id"]
                     for c in params["integration_connections"]}
        self.assertIn(openflake, connected)
        self.assertNotIn(aap_mcp, connected)

        # perform_query survives; job_templates_list goes with AAP MCP.
        self.assertEqual(params["tool_selections"], [UUID % 40])
        before = next(n for n in solutions["nodes"]
                      if n["id"] == "triage_agent")["parameters"]
        self.assertEqual(len(before["tool_selections"]), 2)

    def test_ticket_agents_have_no_llm_for_the_student_to_find(self):
        # Both agents, not just the one carrying the declared gap: the
        # LLM is the student's own credential and provisioning has no
        # copy of it to wire.
        _, student = self._variant(
            "ticket-enrichment.json", "ticket_enrichment",
            "Ticket Enrichment Demo",
        )
        agents = [n for n in student["nodes"] if n["type"] == "agentic"]
        self.assertEqual(len(agents), 2)
        for agent in agents:
            self.assertIsNone(agent["parameters"]["credential_id"])
            self.assertIsNone(agent["parameters"]["llm_model_id"])

    def test_ticket_job_template_nodes_are_fully_wired(self):
        # The six AAP nodes are not an exercise. They are also the
        # reason `default` needs its own AAP credential: AO 422s a
        # workflow citing one from another project.
        _, student = self._variant(
            "ticket-enrichment.json", "ticket_enrichment",
            "Ticket Enrichment Demo",
        )
        jobs = [n for n in student["nodes"]
                if n["type"] == "aap_job_template"]
        self.assertEqual(len(jobs), 6)
        for job in jobs:
            self.assertEqual(job["parameters"]["credential_id"], UUID % 2)
            self.assertEqual(job["parameters"]["integration_id"], UUID % 11)

    def test_student_webhook_paths_do_not_collide_with_solutions(self):
        # Paths are unique instance-wide, not per project, so an
        # unprefixed copy is "The requested webhook path is already in
        # use by another trigger" and never imports.
        for filename, key, name in (
            ("ticket-enrichment.json", "ticket_enrichment",
             "Ticket Enrichment Demo"),
            ("disk-utilization-remediation.json", "disk_utilization",
             "Disk Utilization Remediation"),
        ):
            solutions, student = self._variant(filename, key, name)
            theirs = student["triggers"][0]["parameters"]["webhook_path"]
            ours = solutions["triggers"][0]["parameters"]["webhook_path"]
            self.assertNotEqual(theirs, ours)
            self.assertEqual(theirs, "student-" + ours)

    def test_disk_student_trigger_authorizes_the_student_account(self):
        # Disk's trigger is NOT a declared gap — it has to work out of
        # the box — but it cannot cite the solutions account, because
        # AO 422s a trigger whose account is outside the workflow's
        # project.
        _, student = self._variant(
            "disk-utilization-remediation.json", "disk_utilization",
            "Disk Utilization Remediation",
        )
        params = student["triggers"][0]["parameters"]
        self.assertEqual(params["authorized_service_account_ids"],
                         [UUID % 51])

    def test_ticket_trigger_has_no_authorized_service_account(self):
        # Confirmed live: this imports HTTP 201 with is_valid false, so
        # the workflow is present and editable but will not publish
        # until the student attaches aap-student-webhooks.
        _, student = self._variant(
            "ticket-enrichment.json", "ticket_enrichment",
            "Ticket Enrichment Demo",
        )
        params = student["triggers"][0]["parameters"]
        self.assertNotIn("authorized_service_account_ids", params)

    # --- The gaps file cannot rot quietly ---------------------------

    def test_dropping_an_unknown_node_is_rejected(self):
        full = ao_prepare_definition(
            load_workflow("disk-utilization-remediation.json"), "Disk"
        )
        with self.assertRaises(AOWiringError) as caught:
            ao_student_variant(full, {"drop_nodes": ["activity_not_here"]})
        self.assertIn("activity_not_here", str(caught.exception))

    def test_naming_an_unknown_switch_is_rejected(self):
        full = ao_prepare_definition(
            load_workflow("rhel-cve-remediation.json"), "CVE"
        )
        with self.assertRaises(AOWiringError) as caught:
            ao_student_variant(full, {"blank_switch_conditions": ["nope"]})
        self.assertIn("nope", str(caught.exception))

    def test_the_solutions_definition_is_not_mutated(self):
        # Both copies are built from one export in the same run. If the
        # transform mutated in place, solutions would ship with the
        # student's holes in it.
        full, student = self._variant(
            "disk-utilization-remediation.json", "disk_utilization",
            "Disk Utilization Remediation",
        )
        self.assertEqual(len(full["nodes"]), 10)
        self.assertEqual(len(full["edges"]), 10)
        self.assertNotEqual(len(student["nodes"]), len(full["nodes"]))

    def test_every_gap_key_matches_a_real_workflow(self):
        # A typo'd key here would mean a scenario silently shipping
        # complete, with the exercise gone and nothing to notice it.
        known = {
            "disk_utilization": "disk-utilization-remediation.json",
            "rhel_cve_remediation": "rhel-cve-remediation.json",
            "ticket_enrichment": "ticket-enrichment.json",
        }
        self.assertEqual(set(self.gaps), set(known))


class TestCollection(unittest.TestCase):
    def test_bare_list(self):
        self.assertEqual(ao_collection([{"id": 1}]), [{"id": 1}])

    def test_real_ao_envelope(self):
        # The shape AO actually returns.
        payload = {"next": None, "prev": None, "total": 1,
                   "resources": [{"id": 1, "name": "a"}]}
        self.assertEqual(ao_collection(payload), [{"id": 1, "name": "a"}])

    def test_envelopes(self):
        for key in ("resources", "items", "results", "data"):
            self.assertEqual(ao_collection({key: [{"id": 1}]}), [{"id": 1}])

    def test_results_envelope_is_not_shadowed_by_dict_items_method(self):
        # The reason this filter exists. In Jinja, {'results': [...]}.items
        # resolves to the dict's built-in items() method — truthy — so a
        # `.items | default(.results)` chain yields a bound method rather
        # than falling through to the real payload.
        payload = {"results": [{"id": 1, "name": "a"}], "count": 1}
        self.assertEqual(ao_collection(payload), [{"id": 1, "name": "a"}])
        self.assertNotIn("count", ao_collection(payload))

    def test_unknown_shape_is_empty_not_an_exception(self):
        self.assertEqual(ao_collection({"detail": "nope"}), [])
        self.assertEqual(ao_collection(None), [])

    def test_name_id_map_skips_incomplete_entries(self):
        payload = {"items": [
            {"name": "a", "id": 1},
            {"name": "b"},
            {"id": 3},
        ]}
        self.assertEqual(ao_name_id_map(payload), {"a": 1})


class TestValidationSummary(unittest.TestCase):
    def test_renders_findings(self):
        text = ao_validation_summary(
            {
                "is_valid": False,
                "error_count": 1,
                "findings": [
                    {
                        "severity": "error",
                        "category": "schema_violation",
                        "message": "[] should be non-empty",
                        "node_id": "triage_agent",
                        "field_path": "parameters.tool_selections",
                    }
                ],
            }
        )
        self.assertIn("triage_agent", text)
        self.assertIn("parameters.tool_selections", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
