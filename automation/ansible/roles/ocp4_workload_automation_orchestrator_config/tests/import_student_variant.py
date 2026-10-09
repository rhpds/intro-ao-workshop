#!/usr/bin/env python3
"""Build one student copy against a LIVE AO and POST it into `default`.

This runs the same three filters the role will run — ao_student_bindings,
ao_wire_definition, ao_student_variant — but resolves asset IDs by
reading them off the live instance instead of creating them, so it can
be pointed at an already-provisioned lab and leaves `solutions`
untouched.

It is a test harness, not part of the provision. The role will do this
itself once the shape is settled.

    export AO_URL=https://aap-orchestrator.apps.cluster-xxxxx...
    export AO_PASSWORD=...
    python3 tests/import_student_variant.py ticket_enrichment
    python3 tests/import_student_variant.py ticket_enrichment --delete

Requires PyYAML.
"""

import argparse
import http.client
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ROLE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COLLECTION_DIR = os.path.dirname(os.path.dirname(ROLE_DIR))
sys.path.insert(0, os.path.join(COLLECTION_DIR, "plugins", "filter"))

import yaml  # noqa: E402

from ao_workflow import (  # noqa: E402
    ao_prepare_definition,
    ao_student_bindings,
    ao_student_variant,
    ao_wire_definition,
)

WORKFLOWS = {
    "disk_utilization": (
        "disk-utilization-remediation.json", "Disk Utilization Remediation"),
    "rhel_cve_remediation": (
        "rhel-cve-remediation.json", "RHEL CVE Remediation"),
    "ticket_enrichment": (
        "ticket-enrichment.json", "Ticket Enrichment Demo"),
}

# Asset key -> the name the role gives it. Keep in step with
# defaults/main.yml; a rename there has to land here too.
CREDENTIAL_NAMES = {
    "llm": "LLM Provider",
    "aap": "Ansible Automation Platform",
    "aap_mcp": "AAP MCP Bearer Token",
    "openflake_mcp": "OpenFlake MCP Bearer Token",
    "lightspeed_mcp": "Lightspeed MCP Bearer Token",
}
INTEGRATION_NAMES = {
    "llm": "Solutions LLM",
    "aap": "AAP",
    "aap_mcp": "Solutions AAP MCP",
    "openflake_mcp": "OpenFlake MCP",
    "lightspeed_mcp": "Lightspeed MCP",
}
SERVICE_ACCOUNT_NAMES = {
    "solutions_webhooks": "aap-solutions-webhooks",
    "student_webhooks": "aap-student-webhooks",
}

CONTEXT = ssl.create_default_context()
CONTEXT.check_hostname = False
CONTEXT.verify_mode = ssl.CERT_NONE


class AO(object):
    def __init__(self, url, password, user="admin"):
        self.api = url.rstrip("/") + "/api/v1"
        body, _ = self._call(
            "POST", "/auth/login",
            {"username": user, "password": password}, auth=False)
        self.token = body["access_token"]

    def _call(self, method, path, body=None, auth=True, attempts=8):
        # Larger GETs come back truncated often enough through a
        # proxy that one try is not enough; a retry is cheap and these
        # are all idempotent reads or a single guarded create.
        for attempt in range(attempts):
            request = urllib.request.Request(
                self.api + path, method=method,
                data=json.dumps(body).encode() if body is not None else None)
            request.add_header("Content-Type", "application/json")
            if auth:
                request.add_header("Authorization", "Bearer " + self.token)
            try:
                with urllib.request.urlopen(request, context=CONTEXT,
                                            timeout=90) as response:
                    raw = response.read().decode()
                    return (json.loads(raw, strict=False) if raw else {},
                            response.status)
            except urllib.error.HTTPError as error:
                return json.loads(error.read().decode() or "{}",
                                  strict=False), error.code
            except (http.client.HTTPException, ConnectionError, ValueError,
                    urllib.error.URLError, TimeoutError, OSError) as error:
                if attempt == attempts - 1:
                    raise
                print("  retrying %s %s after %s"
                      % (method, path, type(error).__name__))
                time.sleep(2)

    def get(self, path):
        body, _ = self._call("GET", path)
        return body

    def post(self, path, body):
        return self._call("POST", path, body)

    def delete(self, path):
        return self._call("DELETE", path)[1]

    def name_map(self, kind):
        """name -> id over a `resources` collection."""
        return {o["name"]: o["id"]
                for o in self.get("/%s?limit=100" % kind)["resources"]}

    def tools(self, integration_id):
        """name -> id. The endpoint is CURSOR-paginated: passing
        `offset` silently returns nothing, and limit=200 returns zero,
        so walk it with the cursor it hands back."""
        out = {}
        path = "/integrations/%s/tools?limit=50" % integration_id
        while path:
            page = self.get(path)
            for tool in page.get("resources", []):
                out[tool["name"]] = tool["id"]
            cursor = page.get("next")
            path = ("/integrations/%s/tools?limit=50&cursor=%s"
                    % (integration_id, cursor)) if cursor else None
        return out


def seed_credentials(ao, project_id, bindings, placeholder):
    """Make sure the credentials this copy cites exist in the target project.

    Credentials are hard project-scoped: AO 422s a workflow in
    `default` that cites one from `solutions` with "One or more
    credential references are invalid or belong to a different
    project" — confirmed live 2026-10-08, which is why this exists at
    all. Integration scope does NOT help; a global integration still
    needs a same-project credential on every connection.

    Secrets read back as `$encrypted$`, so a credential cannot be
    cloned through the API. This harness writes the value from
    AO_SEED_<KEY> if set and a visible placeholder otherwise — enough
    to review the workflow's shape in the UI, not enough to run it.
    The role itself has the real values and will not need this.
    """
    wanted = set()
    for binding in (bindings.get("nodes") or {}).values():
        if binding.get("credential"):
            wanted.add(binding["credential"])
        for key in binding.get("integrations") or []:
            wanted.add(key)

    by_project = {}
    for credential in ao.get("/credentials?limit=100")["resources"]:
        by_project.setdefault(credential["project_id"], {})[
            credential["name"]] = credential

    here = by_project.get(project_id, {})
    source = {name: c for creds in by_project.values()
              for name, c in creds.items()}

    created = []
    for key in sorted(wanted):
        name = CREDENTIAL_NAMES.get(key)
        if not name or name in here or name not in source:
            continue
        env_key = "AO_SEED_" + key.upper()
        secret = os.environ.get(env_key)
        inputs = dict(source[name].get("inputs") or {})
        for field, value in inputs.items():
            if value == "$encrypted$":
                inputs[field] = secret or placeholder
        body, status = ao.post("/credentials", {
            "name": name,
            "description": "Created by import_student_variant.py for "
                           "review. %s" % ("real value from %s" % env_key
                                           if secret else "PLACEHOLDER secret"),
            "credential_type_id": source[name]["credential_type_id"],
            "project_id": project_id,
            "inputs": inputs,
        })
        print("  seed credential %-32s HTTP %s  %s"
              % (name, status, "real" if secret else "PLACEHOLDER"))
        if status >= 300:
            print("    %s" % json.dumps(body)[:400])
        else:
            created.append(name)
    return created


def load_gaps(key):
    with open(os.path.join(ROLE_DIR, "files", "student_gaps.yml")) as handle:
        doc = yaml.safe_load(handle)
    return dict(doc.get("ao_student_common") or {},
                **(doc["ao_student_gaps"][key] or {}))


def load_bindings(key):
    with open(os.path.join(ROLE_DIR, "vars",
                           "bindings_%s.yml" % key)) as handle:
        return yaml.safe_load(handle)["ao_workflow_bindings"]


def resolve(ao, bindings, solutions_name, project_id):
    """Build the `resolved` map from what is already on the instance.

    Job template ids and the LLM model id are read off the published
    `solutions` copy rather than from AAP and /models — this harness
    only has AO credentials, and those two values are already sitting
    in the definition the role wired on the last provision.
    """
    # Only credentials in the TARGET project count. A name map across
    # the whole instance would quietly hand back the `solutions` copy
    # and the import would 422 on the project mismatch.
    credentials = {c["name"]: c["id"]
                   for c in ao.get("/credentials?limit=100")["resources"]
                   if c["project_id"] == project_id}
    integrations = ao.name_map("integrations")
    accounts = ao.name_map("service_accounts")
    workflows = {o["name"]: o["id"]
                 for o in ao.get("/workflows?limit=100")["resources"]}

    source = ao.get("/workflows/%s" % workflows[solutions_name])
    version = ao.get("/workflows/%s/versions/%s"
                     % (workflows[solutions_name], source["current_version"]))
    wired = version["workflow_definition"]

    job_templates = {}
    model_id = ""
    for node in wired["nodes"]:
        params = node.get("parameters", {})
        if node["type"] == "aap_job_template" and params.get("job_template_id"):
            job_templates[params["job_template_name"]] = \
                params["job_template_id"]
        if node["type"] == "agentic" and params.get("llm_model_id"):
            model_id = params["llm_model_id"]

    needed = set()
    for binding in (bindings.get("nodes") or {}).values():
        needed.update(binding.get("integrations") or [])
        if binding.get("integration"):
            needed.add(binding["integration"])
    tools = {key: ao.tools(integrations[INTEGRATION_NAMES[key]])
             for key in needed if key in INTEGRATION_NAMES
             and INTEGRATION_NAMES[key] in integrations}

    return {
        "credentials": {k: credentials.get(v)
                        for k, v in CREDENTIAL_NAMES.items()
                        if credentials.get(v)},
        "integrations": {k: integrations.get(v)
                         for k, v in INTEGRATION_NAMES.items()
                         if integrations.get(v)},
        "integration_credentials": {
            "llm": "llm", "aap": "aap", "aap_mcp": "aap_mcp",
            "openflake_mcp": "openflake_mcp",
            "lightspeed_mcp": "lightspeed_mcp",
        },
        "tools": tools,
        "job_templates": job_templates,
        "service_accounts": {k: accounts.get(v)
                             for k, v in SERVICE_ACCOUNT_NAMES.items()
                             if accounts.get(v)},
        "llm_model_id": model_id,
        "organization": "Default",
        "trigger_defaults": {"lab_tag": os.environ.get("AO_LAB_TAG", "")},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("key", choices=sorted(WORKFLOWS))
    parser.add_argument("--delete", action="store_true",
                        help="remove the student copy instead of creating it")
    parser.add_argument("--project", default="default")
    parser.add_argument("--seed-credentials", action="store_true",
                        help="create any credential this copy cites that is "
                             "missing from the target project")
    parser.add_argument("--placeholder", default="REPLACE_ME_review_only",
                        help="secret used when AO_SEED_<KEY> is unset")
    args = parser.parse_args()

    url = os.environ.get("AO_URL")
    password = os.environ.get("AO_PASSWORD")
    if not url or not password:
        sys.exit("set AO_URL and AO_PASSWORD")

    filename, name = WORKFLOWS[args.key]
    ao = AO(url, password)
    projects = ao.name_map("projects")
    project_id = projects[args.project]

    existing = {o["name"]: o["id"]
                for o in ao.get("/workflows?limit=100")["resources"]
                if o.get("project_id") == project_id}
    if args.delete:
        if name not in existing:
            print("nothing to delete: no '%s' in %s" % (name, args.project))
            return
        print("DELETE %s -> %s" % (name, ao.delete("/workflows/%s"
                                                   % existing[name])))
        return

    gaps = load_gaps(args.key)
    bindings = load_bindings(args.key)
    student_bindings = ao_student_bindings(bindings, gaps)
    if args.seed_credentials:
        seed_credentials(ao, project_id, student_bindings, args.placeholder)
    resolved = resolve(ao, student_bindings, name, project_id)

    with open(os.path.join(ROLE_DIR, "files", "workflows", filename)) as fh:
        prepared = ao_prepare_definition(json.load(fh), name)
    definition = ao_student_variant(
        ao_wire_definition(prepared, student_bindings, resolved), gaps)

    body = {
        "name": name,
        "description": "Student exercise. %s"
                       % " ".join((gaps.get("summary") or "").split()),
        "project_id": project_id,
        "workflow_definition": definition,
    }
    if name in existing:
        print("replacing the existing copy in %s first" % args.project)
        ao.delete("/workflows/%s" % existing[name])

    result, status = ao.post("/workflows", body)
    print("POST /workflows -> HTTP %s" % status)
    if status >= 300:
        print(json.dumps(result, indent=2)[:3000])
        sys.exit(1)

    print("  id        %s" % result.get("id"))
    print("  project   %s" % args.project)
    validation = result.get("validation_result") or {}
    print("  is_valid  %s" % validation.get("is_valid"))
    for finding in validation.get("findings", []):
        print("    [%s] %s: %s (%s)"
              % (finding.get("severity"), finding.get("node_id"),
                 finding.get("message"), finding.get("field_path")))


if __name__ == "__main__":
    main()
