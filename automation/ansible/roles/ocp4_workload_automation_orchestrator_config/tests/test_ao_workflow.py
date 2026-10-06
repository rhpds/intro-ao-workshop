#!/usr/bin/env python3
"""Offline tests for the AO workflow wiring filters.

Runs against the real exported workflow JSON in ../files/workflows and
the real binding files in ../vars, with every run-time ID faked. No AO
or AAP instance required:

    python3 tests/test_ao_workflow.py
"""

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
        # Keyed the same way credentials and integrations are. Only
        # Ticket Enrichment's webhook trigger consumes it.
        "service_accounts": {"webhooks": UUID % 50},
        "llm_model_id": UUID % 20,
        "organization": "Default",
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
        "vulnerability__get_cve_details": UUID % 31,
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
        self.assertEqual(len(definition["nodes"]), 12)
        self.assertEqual(len(definition["edges"]), 12)
        self.assertEqual(len(definition["triggers"]), 1)

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

        self.assertEqual(
            sorted(triage["tool_selections"]),
            [
                "advisor__get_hosts_hitting_a_rule",
                "advisor__get_recommendations_stats",
                "advisor__get_rule_details",
                "content-sources__list_repositories",
                "groups_list",
                "hosts_list",
                "hosts_variable_data_retrieve",
                "inventories_list",
                "inventory__get_host_details",
                "inventory__get_host_system_profile",
                "inventory__get_host_tags",
                "inventory__list_hosts",
            ],
        )
        self.assertTrue(triage["tool_selections"], "must be non-empty for SELECTED")

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

    def test_tool_selections_are_bare_strings(self):
        # AO 500s on every object shape; only a list of names is
        # accepted. Guard the regression.
        for node in self.wired["nodes"]:
            for selection in node.get("parameters", {}).get("tool_selections", []):
                self.assertIsInstance(selection, str, node["id"])

    def test_strategy_none_sends_no_tool_selections(self):
        # investigate_agent reasons over what triage gathered, so it gets
        # no tools. AO's enum is ALL|NONE|SELECTED and SELECTED with an
        # empty list is rejected, so this must be NONE — and the key must
        # be absent, matching what AO's own UI sends.
        investigate = self.nodes["investigate_agent"]["parameters"]
        self.assertEqual(investigate["tool_selection_strategy"], "NONE")
        self.assertNotIn("tool_selections", investigate)
        # It still connects to both integrations, and still needs a model
        # and a credential.
        self.assertEqual(len(investigate["integration_connections"]), 2)
        self.assertEqual(investigate["llm_model_id"], UUID % 20)

    def test_tools_all_expands_to_whole_surface(self):
        bindings = copy.deepcopy(self.bindings)
        node = bindings["nodes"]["investigate_agent"]
        node["tool_selection_strategy"] = "SELECTED"
        node["tools_all"] = ["lightspeed_mcp", "aap_mcp"]
        wired = ao_wire_definition(self.definition, bindings, self.resolved)
        investigate = {n["id"]: n for n in wired["nodes"]}["investigate_agent"]
        self.assertEqual(
            sorted(investigate["parameters"]["tool_selections"]),
            sorted(list(CVE_TOOLS["lightspeed_mcp"]) + list(CVE_TOOLS["aap_mcp"])),
        )

    def test_strategy_none_with_tools_is_rejected(self):
        bindings = copy.deepcopy(self.bindings)
        bindings["nodes"]["investigate_agent"]["tools"] = {
            "aap_mcp": ["hosts_list"]
        }
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
            ("parse_investigation", "script"),
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
        # This is the only workflow triggered by webhook rather than
        # manually, and the webhook path is what the aap-webhooks
        # service account is minted for.
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

    def test_agents_get_pinned_tools_as_bare_strings(self):
        agents = {n["id"]: n["parameters"] for n in self.wired["nodes"]
                  if n["type"] == "agentic"}

        triage = agents["triage_agent"]
        self.assertEqual(triage["llm_model_id"], UUID % 20)
        self.assertEqual(
            sorted(triage["tool_selections"]), ["job_templates_list", "perform_query"]
        )

        # The inform-only agent is read-only and needs OpenFlake alone.
        enrich = agents["enrich_and_assign_agent"]
        self.assertEqual(enrich["tool_selections"], ["perform_query"])
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
        resolved = fake_resolved(
            ao_required_job_templates(self.definition, bindings), {}
        )
        with self.assertRaises(AOWiringError) as caught:
            ao_wire_definition(self.definition, bindings, resolved)
        self.assertIn("exposed none", str(caught.exception))


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
