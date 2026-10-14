#!/usr/bin/env python3
"""Build one SOLUTIONS workflow against a LIVE AO and POST it there.

The sibling of import_student_variant.py, for the other half of the
import loop. It runs the same two filters the role runs for `solutions`
— ao_prepare_definition, ao_wire_definition — but resolves asset IDs by
reading them off the live instance instead of creating them, so it can
be pointed at an already-provisioned lab without re-running the whole
workload.

The reason it exists: a new export's first contact with AO should not
be a provision. AO accepts a structurally valid workflow and reports
problems as validation findings rather than a non-2xx, so "did it
import" and "is it actually usable" are two different questions, and
this answers both in one run.

    export AO_URL=https://aap-orchestrator.apps.cluster-xxxxx...
    export AO_PASSWORD=...
    export AO_CA_BUNDLE=/path/to/cluster-ca.pem
    python3 tests/import_solutions_workflow.py vacation_suggestion
    python3 tests/import_solutions_workflow.py vacation_suggestion --publish
    python3 tests/import_solutions_workflow.py vacation_suggestion --delete

Exits non-zero if the POST fails or the workflow does not validate, so
it can gate a change to an export or a binding file.

Requires PyYAML.
"""

import argparse
import json
import os
import sys

ROLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_DIR = os.path.dirname(os.path.dirname(ROLE_DIR))
sys.path.insert(0, os.path.join(COLLECTION_DIR, "plugins", "filter"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yaml  # noqa: E402

from ao_workflow import (  # noqa: E402
    AOWiringError,
    ao_prepare_definition,
    ao_wire_definition,
)

# The TLS context, the login/retry client and the asset name maps are
# the student harness's, imported rather than restated so a fix to
# either reaches both.
from import_student_variant import (  # noqa: E402
    AO,
    CREDENTIAL_NAMES,
    INTEGRATION_NAMES,
    SERVICE_ACCOUNT_NAMES,
    load_bindings,
)


def workflows_from_defaults():
    """key -> (file, name, description), straight out of defaults/main.yml.

    Read rather than restated, so adding a workflow to the role is
    enough to make it testable here. import_student_variant.py predates
    this and still carries its own hand-kept table; the two should
    converge on this one.
    """
    path = os.path.join(ROLE_DIR, "defaults", "main.yml")
    with open(path) as handle:
        defaults = yaml.safe_load(handle)
    entries = defaults["ocp4_workload_automation_orchestrator_config_workflows"]
    return {
        entry["key"]: (
            entry["file"],
            entry["name"],
            " ".join((entry.get("description") or "").split()),
        )
        for entry in entries
    }


def resolve(ao, bindings, project_id):
    """Build the `resolved` map from what is already on the instance.

    Unlike the student harness, this cannot read job template IDs and
    the LLM model ID off the workflow being imported — the whole point
    is that it may not exist yet. They are harvested from EVERY
    workflow already in the project instead, which works because a new
    workflow in this lab reuses job templates and the one model the
    other three already cite. A genuinely new job template will come
    back unresolved and is reported by name below.
    """
    credentials = {
        c["name"]: c["id"]
        for c in ao.get("/credentials?limit=100")["resources"]
        if c["project_id"] == project_id
    }
    integrations = ao.name_map("integrations")
    accounts = ao.name_map("service_accounts")

    job_templates = {}
    model_id = ""
    for summary in ao.get("/workflows?limit=100")["resources"]:
        if summary.get("project_id") != project_id:
            continue
        detail = ao.get("/workflows/%s" % summary["id"])
        version = detail.get("current_version")
        if not version:
            continue
        wired = ao.get(
            "/workflows/%s/versions/%s" % (summary["id"], version)
        )["workflow_definition"]
        for node in wired.get("nodes", []):
            params = node.get("parameters") or {}
            if node["type"] == "aap_job_template" and params.get("job_template_id"):
                job_templates[params["job_template_name"]] = params["job_template_id"]
            if node["type"] == "agentic" and params.get("llm_model_id"):
                model_id = params["llm_model_id"]

    needed = set()
    for binding in (bindings.get("nodes") or {}).values():
        needed.update(binding.get("integrations") or [])
        if binding.get("integration"):
            needed.add(binding["integration"])
    tools = {
        key: ao.tools(integrations[INTEGRATION_NAMES[key]])
        for key in needed
        if key in INTEGRATION_NAMES and INTEGRATION_NAMES[key] in integrations
    }

    return {
        "credentials": {
            k: credentials.get(v)
            for k, v in CREDENTIAL_NAMES.items()
            if credentials.get(v)
        },
        "integrations": {
            k: integrations.get(v)
            for k, v in INTEGRATION_NAMES.items()
            if integrations.get(v)
        },
        "integration_credentials": {
            "llm": "llm",
            "aap": "aap",
            "aap_mcp": "aap_mcp",
            "openflake_mcp": "openflake_mcp",
            "lightspeed_mcp": "lightspeed_mcp",
        },
        "tools": tools,
        "job_templates": job_templates,
        "service_accounts": {
            k: accounts.get(v)
            for k, v in SERVICE_ACCOUNT_NAMES.items()
            if accounts.get(v)
        },
        "llm_model_id": model_id,
        "organization": "Default",
        "trigger_defaults": {"lab_tag": os.environ.get("AO_LAB_TAG") or ""},
    }


def report_validation(validation, readback):
    """Print findings; return True when the workflow validated.

    Two sources, because AO answers the question differently depending
    on which one you ask. The POST may return a rich
    `validation_result` with per-finding node_id and field_path, and
    that is what you want when something is wrong. But it also
    legitimately returns `validation_result: null` — observed on this
    workflow, live — and so does every GET. The GET always carries the
    boolean `has_validation_issues`, so that is the fallback, and the
    same order of preference the role itself uses in
    tasks/ao_import_workflow.yml.

    Reading only the rich object treats "AO said nothing" as "AO said
    no", which is how this script first reported a perfectly valid
    import as a failure.
    """
    findings = validation.get("findings") or []
    for finding in findings:
        print(
            "    [%s] %s: %s (%s)"
            % (
                finding.get("severity"),
                finding.get("node_id"),
                finding.get("message"),
                finding.get("field_path"),
            )
        )

    if validation.get("is_valid") is not None:
        print("  is_valid  %s (from the POST)" % validation["is_valid"])
        return bool(validation["is_valid"])

    issues = readback.get("has_validation_issues")
    print("  is_valid  %s (has_validation_issues=%s, from the GET)"
          % (issues is False, issues))
    return issues is False


def main():
    table = workflows_from_defaults()
    parser = argparse.ArgumentParser()
    parser.add_argument("key", choices=sorted(table))
    parser.add_argument("--project", default="solutions")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="publish the version after it validates, as the role does",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="remove the workflow from the project instead of creating it",
    )
    args = parser.parse_args()

    url = os.environ.get("AO_URL")
    password = os.environ.get("AO_PASSWORD")
    if not url or not password:
        sys.exit("set AO_URL and AO_PASSWORD")

    filename, name, description = table[args.key]
    ao = AO(url, password)
    project_id = ao.name_map("projects")[args.project]

    existing = {
        o["name"]: o["id"]
        for o in ao.get("/workflows?limit=100")["resources"]
        if o.get("project_id") == project_id
    }

    if args.delete:
        if name not in existing:
            print("nothing to delete: no '%s' in %s" % (name, args.project))
            return
        print("DELETE %s -> %s" % (name, ao.delete("/workflows/%s" % existing[name])))
        return

    bindings = load_bindings(args.key)
    resolved = resolve(ao, bindings, project_id)

    with open(os.path.join(ROLE_DIR, "files", "workflows", filename)) as handle:
        prepared = ao_prepare_definition(json.load(handle), name, description)

    try:
        definition = ao_wire_definition(prepared, bindings, resolved)
    except AOWiringError as error:
        # Worth separating from an AO rejection: this one never left
        # the machine, and names the node and the asset itself.
        sys.exit("wiring failed before any request was sent:\n  %s" % error)

    if name in existing:
        print("replacing the existing copy in %s first" % args.project)
        ao.delete("/workflows/%s" % existing[name])

    result, status = ao.post(
        "/workflows",
        {
            "name": name,
            "description": description,
            "project_id": project_id,
            "workflow_definition": definition,
        },
    )
    print("POST /workflows -> HTTP %s" % status)
    if status >= 300:
        print(json.dumps(result, indent=2)[:3000])
        sys.exit(1)

    workflow_id = result.get("id")
    print("  id        %s" % workflow_id)
    print("  project   %s" % args.project)

    # The GET is needed anyway for current_version, which publish takes.
    readback = ao.get("/workflows/%s" % workflow_id)
    if not report_validation(result.get("validation_result") or {}, readback):
        sys.exit("'%s' imported but does not validate" % name)

    if not args.publish:
        return

    # Version-scoped: /workflows/{id}/publish is a 404. 409 means
    # either "does not validate" or "already published".
    version = readback["current_version"]
    _, status = ao.post(
        "/workflows/%s/versions/%s/publish" % (workflow_id, version), {}
    )
    print("  publish   version %s -> HTTP %s" % (version, status))
    if status >= 300 and status != 409:
        sys.exit("publish failed")


if __name__ == "__main__":
    main()
