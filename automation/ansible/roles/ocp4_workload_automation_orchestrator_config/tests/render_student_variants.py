#!/usr/bin/env python3
"""Render the student copies of each scenario, for eyeballing.

The role generates these at import time and never writes them to disk.
This does the same transform offline so you can read what the student
actually receives, diff it against `solutions`, or POST it at a live AO
yourself.

    python3 tests/render_student_variants.py            # summary
    python3 tests/render_student_variants.py --write DIR # write the JSON

Requires PyYAML. No network, no AO.
"""

import argparse
import json
import os
import sys

ROLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_DIR = os.path.dirname(os.path.dirname(ROLE_DIR))
sys.path.insert(0, os.path.join(COLLECTION_DIR, "plugins", "filter"))

import yaml  # noqa: E402

from ao_workflow import (  # noqa: E402
    ao_prepare_definition,
    ao_student_bindings,
    ao_student_gaps,
    ao_student_variant,
    ao_wire_definition,
)

# key -> (export filename, workflow name)
WORKFLOWS = {
    "disk_utilization": (
        "disk-utilization-remediation.json", "Disk Utilization Remediation"),
    "rhel_cve_remediation": (
        "rhel-cve-remediation.json", "RHEL CVE Remediation"),
    "ticket_enrichment": (
        "ticket-enrichment.json", "Ticket Enrichment Demo"),
}


# What provisioning owns in `default`. The student creates the LLM and
# AAP MCP integrations by hand, so neither appears here — which is the
# whole point of the exercise and the reason those nodes ship blank.
STUDENT_PROJECT_CREDENTIALS = ("aap", "lightspeed_mcp", "openflake_mcp")


def load_gaps():
    with open(os.path.join(ROLE_DIR, "files", "student_gaps.yml")) as handle:
        return ao_student_gaps(yaml.safe_load(handle))


def load_bindings(key):
    path = os.path.join(ROLE_DIR, "vars", "bindings_%s.yml" % key)
    with open(path) as handle:
        return yaml.safe_load(handle)["ao_workflow_bindings"]


def fake_resolved(bindings, credential_keys):
    """Stand in for the maps the role builds against a live AO.

    IDs are fake but shaped right; what matters is WHICH keys are
    present, because that is what decides whether a node ends up wired
    or blank.
    """
    def uuid_for(text):
        import hashlib
        digest = hashlib.sha1(text.encode()).hexdigest()
        return "%s-%s-%s-%s-%s" % (digest[:8], digest[8:12], digest[12:16],
                                   digest[16:20], digest[20:32])

    tools = {}
    job_templates = {}
    for binding in (bindings.get("nodes") or {}).values():
        for integration_key, names in (binding.get("tools") or {}).items():
            tools.setdefault(integration_key, {}).update(
                {name: uuid_for(integration_key + name) for name in names})
        if binding.get("job_template"):
            job_templates[binding["job_template"]] = uuid_for(
                binding["job_template"])

    return {
        "credentials": {k: uuid_for("cred" + k) for k in credential_keys},
        "integrations": {k: uuid_for("int" + k)
                         for k in ("aap", "lightspeed_mcp", "openflake_mcp",
                                   "aap_mcp", "llm")},
        "integration_credentials": {
            "llm": "llm", "aap": "aap", "aap_mcp": "aap_mcp",
            "openflake_mcp": "openflake_mcp",
            "lightspeed_mcp": "lightspeed_mcp",
        },
        "tools": tools,
        "job_templates": job_templates,
        "service_accounts": {"solutions_webhooks": uuid_for("sa-solutions"),
                             "student_webhooks": uuid_for("sa-student")},
        "llm_model_id": uuid_for("model"),
        "organization": "Default",
        "trigger_defaults": {"lab_tag": "abc12-1"},
    }


def build(key):
    """Wire the solutions copy and the student copy the way the role does."""
    filename, name = WORKFLOWS[key]
    gap = load_gaps()[key]
    bindings = load_bindings(key)
    path = os.path.join(ROLE_DIR, "files", "workflows", filename)
    with open(path) as handle:
        prepared = ao_prepare_definition(json.load(handle), name)

    # solutions: every asset present.
    full = ao_wire_definition(
        prepared, bindings,
        fake_resolved(bindings, ("llm", "aap", "aap_mcp",
                                 "lightspeed_mcp", "openflake_mcp")))

    # default: only the credentials provisioning creates there, and
    # bindings rewritten to stop citing the ones it does not.
    student_bindings = ao_student_bindings(bindings, gap)
    student = ao_wire_definition(
        prepared, student_bindings,
        fake_resolved(student_bindings, STUDENT_PROJECT_CREDENTIALS))
    return name, full, ao_student_variant(student, gap)


def describe(name, full, student, gap):
    print("=" * 72)
    print(name)
    print("  gap: %s" % " ".join((gap.get("summary") or "?").split()))
    print("  solutions: %2d nodes / %2d edges"
          % (len(full["nodes"]), len(full["edges"])))
    print("  student  : %2d nodes / %2d edges"
          % (len(student["nodes"]), len(student["edges"])))

    for switch in [n for n in student["nodes"] if n["type"] == "switch"]:
        params = switch["parameters"]
        wired = {
            e.get("from_port"): e["to"] for e in student["edges"]
            if e.get("from") == switch["id"]
        }
        # A port is only the student's work if solutions wires it and
        # this copy does not. Several default ports are unwired in both
        # — that is the shipped design, not an exercise.
        solutions_wired = {
            e.get("from_port") for e in full["edges"]
            if e.get("from") == switch["id"]
        }
        print("  switch %s:" % (switch.get("name") or switch["id"]))
        rows = [(c["port"], c["label"], c.get("condition", ""))
                for c in params.get("cases", [])]
        rows.append((params.get("default_port"), "(default)", None))
        for port, label, condition in rows:
            target = wired.get(port)
            if target:
                edge = "-> %s" % target
            elif port in solutions_wired:
                edge = "-> EMPTY  <<< student builds this"
            else:
                edge = "-> (unwired in solutions too — by design)"
            print("    %-9s %-26s %s" % (port, label, edge))
            if condition is not None:
                shown = condition or "BLANK  <<< student fills this"
                print("    %-9s %-26s   condition: %s" % ("", "", shown))

    for node in student["nodes"]:
        if node["type"] == "agentic":
            params = node["parameters"]
            print("  agent %-24s strategy=%s tools=%d"
                  % (node["id"], params.get("tool_selection_strategy"),
                     len(params.get("tool_selections") or [])))
            # The LLM is the student's own, so both of these are null
            # on every agent. Connections show which MCP servers were
            # pre-wired and which the student still has to add.
            print("    %-24s llm: %s  model: %s  connections: %d"
                  % ("", "SET" if params.get("credential_id") else "null",
                     "SET" if params.get("llm_model_id") else "null",
                     len(params.get("integration_connections") or [])))

    for trigger in student.get("triggers", []):
        # Only webhook and EDA triggers require an authorized service
        # account. Reporting one as missing on a manual trigger invents
        # an exercise that does not exist.
        needs_sa = trigger["type"] in ("webhook_trigger", "eda_trigger")
        if not needs_sa:
            print("  trigger %-22s type=%s" % (trigger["id"][:20], trigger["type"]))
            continue
        has_sa = "authorized_service_account_ids" in trigger["parameters"]
        print("  trigger %-22s type=%s service account: %s"
              % (trigger["id"][:20], trigger["type"],
                 "present" if has_sa
                 else "ABSENT  <<< student attaches aap-student-webhooks"))

    dropped = {n["id"] for n in full["nodes"]} - {
        n["id"] for n in student["nodes"]}
    if dropped:
        names = {n["id"]: n.get("name") for n in full["nodes"]}
        print("  dropped: %s" % ", ".join(sorted(names[i] for i in dropped)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", metavar="DIR",
                        help="also write each student definition as JSON")
    args = parser.parse_args()

    gaps = load_gaps()
    for key in WORKFLOWS:
        name, full, student = build(key)
        describe(name, full, student, gaps[key])
        if args.write:
            os.makedirs(args.write, exist_ok=True)
            out = os.path.join(args.write, "%s.json" % key)
            with open(out, "w") as handle:
                json.dump(student, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
            print("  written: %s" % out)


if __name__ == "__main__":
    main()
