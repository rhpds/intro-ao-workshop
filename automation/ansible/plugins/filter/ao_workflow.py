# -*- coding: utf-8 -*-
"""Filter plugins for wiring Automation Orchestrator workflow definitions.

Importing a workflow into AO is two steps: post a `workflow_definition`,
then patch per-node parameters with IDs that only exist once the
surrounding assets (credentials, integrations, AAP job templates) have
been created. The second step is a structural transform over a
moderately deep JSON document, which is miserable to express in Jinja
and easy to unit-test in Python — hence this plugin.

Everything here is pure: no network, no Ansible internals. That means
`tests/test_ao_workflow.py` can exercise the whole wiring path against
the real exported JSON files without a live AO instance.
"""

from __future__ import absolute_import, division, print_function

import copy
import re

__metaclass__ = type


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Node types that carry no wiring of their own. Listed explicitly so an
# unrecognised type is reported rather than silently skipped.
SELF_CONTAINED_NODE_TYPES = ("script", "switch", "approval")

WIRED_NODE_TYPES = ("agentic", "aap_job_template")

# Triggers need wiring too, and are a separate list from `nodes` — a
# workflow's entry points live under `triggers`, so iterating only
# `nodes` silently leaves them inert.
#
# `manual_trigger` and `schedule_trigger` are self-contained. The two
# that expose an HTTP endpoint are not: AO requires
# `authorized_service_account_ids` on them, and rejects the whole
# workflow with "'authorized_service_account_ids' is a required
# property" without it. From AO's own UI schema,
# `authorizedServiceAccountIds: array(uuid).optional()`, and the
# selector that fills it maps GET /service_accounts through
# {id, name} — so the UUIDs are service account ids, not the ids of
# the credentials hanging off them.
AUTHORIZED_TRIGGER_TYPES = ("webhook_trigger", "eda_trigger")

# How an agentic node chooses its tools. Read off AO's own UI schema:
# `tool_selection_strategy: enum(["ALL","NONE","SELECTED"])`. Only
# SELECTED carries a `tool_selections` list; ALL offers the
# integration's whole surface and NONE offers nothing.
TOOL_SELECTION_STRATEGIES = ("ALL", "NONE", "SELECTED")

# A runtime expression such as "${deploy_script.artifacts.template_name}"
# resolves inside AO at execution time. There is no static job template
# to look up for one, so it must not be sent to the AAP controller.
EXPRESSION_RE = re.compile(r"\$\{[^}]+\}")


class AOWiringError(Exception):
    """Raised for a binding that cannot be satisfied."""


def _is_uuid(value):
    return isinstance(value, str) and bool(UUID_RE.match(value))


def is_expression(value):
    """True when a value is (or contains) an AO runtime expression."""
    return isinstance(value, str) and bool(EXPRESSION_RE.search(value))


def ao_prepare_definition(raw, name, description="", schema_version="2.0.0"):
    """Normalise an exported workflow into a postable `workflow_definition`.

    Exports are not uniform. The CVE export carries its own
    `schema_version`, `name` and `description`; the disk-utilisation
    export carries only `triggers`, `nodes` and `edges`, so those fields
    are synthesised here.

    Placeholder credential IDs are stripped. A non-UUID string in
    `credential_id` crashes the AO server with an HTTP 500 rather than
    returning a clean 422, and the disk export ships the literal
    "YOUR_AAP_CREDENTIAL_ID" on all nine of its AAP nodes. Dropping the
    key entirely is correct: the wiring step puts a real UUID back.
    """
    definition = copy.deepcopy(raw)

    # Some exports nest the document under `workflow_definition`.
    if "workflow_definition" in definition and "nodes" not in definition:
        definition = definition["workflow_definition"]

    definition["schema_version"] = definition.get("schema_version") or schema_version
    definition["name"] = definition.get("name") or name
    if description or not definition.get("description"):
        definition["description"] = description or definition.get("description", "")

    definition.setdefault("triggers", [])
    definition.setdefault("nodes", [])
    definition.setdefault("edges", [])

    for node in definition["nodes"]:
        params = node.get("parameters")
        if not isinstance(params, dict):
            continue
        cred = params.get("credential_id")
        if cred is not None and not _is_uuid(cred):
            del params["credential_id"]

    return definition


def ao_required_job_templates(definition, bindings):
    """List the AAP job template names that must resolve to an ID.

    Used as a preflight so a missing job template is reported by name,
    all at once, instead of surfacing as a null `job_template_id` that
    fails validation later with a less obvious message.

    Nodes whose `job_template_name` is a runtime expression are skipped:
    AO resolves those during execution from a prior node's artifacts.
    """
    node_bindings = (bindings or {}).get("nodes", {})
    names = []

    for node in definition.get("nodes", []):
        if node.get("type") != "aap_job_template":
            continue
        binding = node_bindings.get(node.get("id"), {})
        name = binding.get("job_template")
        if name is None:
            name = (node.get("parameters") or {}).get("job_template_name")
        if not name or is_expression(name):
            continue
        if name not in names:
            names.append(name)

    return names


def _tool_selection(integration_id, tool_name, tool_id):
    """Build one `tool_selections` entry.

    AO wants a bare tool *name* string here, not an object. Confirmed
    against a live instance: every dict shape tried
    ({integration_id, tool_name}, {integration_id, tool_id},
    {name}, {id}) is rejected with a 500, while ["hosts_list"] is
    accepted and validates.

    The integration is therefore identified only by
    `integration_connections`, and the tool by name within it — which
    means two integrations exposing the same tool name would be
    ambiguous. Not a case this lab hits (the AAP and Lightspeed MCP
    surfaces are disjoint), but worth knowing.

    integration_id and tool_id are still taken as arguments because the
    caller has already resolved them and uses them to prove the tool
    actually exists on that integration before selecting it.
    """
    del integration_id, tool_id  # identified by name; see docstring
    return tool_name


def _wire_agentic(node, binding, resolved):
    params = node.setdefault("parameters", {})
    node_id = node.get("id")

    model_id = binding.get("llm_model_id") or resolved.get("llm_model_id")
    if not model_id:
        raise AOWiringError(
            "agentic node '%s' has no llm_model_id; the LLM integration "
            "probably returned no models after refresh" % node_id
        )
    params["llm_model_id"] = model_id

    cred_key = binding.get("credential")
    if cred_key:
        params["credential_id"] = _lookup(resolved, "credentials", cred_key, node_id)

    # Each connection needs a credential as well as an integration: AO
    # rejects a bare {integration_id} with "'credential_id' is a
    # required property" at field_path
    # parameters.integration_connections.<n>. The credential is a
    # property of the integration, so it comes from the role's
    # integration -> credential map rather than being restated per node;
    # a binding may still override it.
    integration_keys = binding.get("integrations", [])
    connection_credentials = resolved.get("integration_credentials") or {}
    overrides = binding.get("integration_credentials") or {}
    connections = []
    for key in integration_keys:
        cred_key = overrides.get(key) or connection_credentials.get(key)
        if not cred_key:
            raise AOWiringError(
                "agentic node '%s' connects to integration '%s', but no "
                "credential is mapped to it; AO requires one per connection"
                % (node_id, key)
            )
        connections.append(
            {
                "integration_id": _lookup(resolved, "integrations", key, node_id),
                "credential_id": _lookup(resolved, "credentials", cred_key, node_id),
            }
        )
    params["integration_connections"] = connections

    # tool_selections must be non-empty when the strategy is SELECTED —
    # AO rejects `[]` with "should be non-empty".
    #
    # Two ways to select: `tools` names them explicitly (use this when
    # the node's prompt calls specific tools by name, so that a renamed
    # or missing tool fails loudly), or `tools_all` takes everything an
    # integration exposes (use this when the prompt just says "use the
    # Lightspeed MCP" and pinning a list would be guesswork).
    selected = {}
    for integration_key in (binding.get("tools_all") or []):
        available = (resolved.get("tools") or {}).get(integration_key, {})
        if not available:
            raise AOWiringError(
                "agentic node '%s' selects all tools from integration '%s', "
                "but it exposed none after refresh" % (node_id, integration_key)
            )
        selected[integration_key] = sorted(available)

    for integration_key, tool_names in (binding.get("tools") or {}).items():
        selected.setdefault(integration_key, [])
        for tool_name in tool_names:
            if tool_name not in selected[integration_key]:
                selected[integration_key].append(tool_name)

    selections = []
    for integration_key, tool_names in selected.items():
        integration_id = _lookup(resolved, "integrations", integration_key, node_id)
        available = (resolved.get("tools") or {}).get(integration_key, {})
        for tool_name in tool_names:
            if available and tool_name not in available:
                raise AOWiringError(
                    "agentic node '%s' wants tool '%s' from integration '%s', "
                    "which exposes: %s"
                    % (node_id, tool_name, integration_key,
                       ", ".join(sorted(available)) or "(none)")
                )
            selections.append(
                _tool_selection(integration_id, tool_name, available.get(tool_name))
            )

    strategy = binding.get("tool_selection_strategy") or params.get(
        "tool_selection_strategy", "SELECTED"
    )
    if strategy not in TOOL_SELECTION_STRATEGIES:
        raise AOWiringError(
            "agentic node '%s' uses tool_selection_strategy '%s'; AO accepts "
            "only %s" % (node_id, strategy, ", ".join(sorted(TOOL_SELECTION_STRATEGIES)))
        )
    params["tool_selection_strategy"] = strategy

    if strategy == "SELECTED":
        if not selections:
            raise AOWiringError(
                "agentic node '%s' uses tool_selection_strategy SELECTED but "
                "the binding selects no tools; AO rejects an empty "
                "tool_selections" % node_id
            )
        params["tool_selections"] = selections
    else:
        # ALL and NONE carry no selection list. AO's own UI only sends
        # `tool_selections` when the strategy is SELECTED, so drop any
        # list the export shipped rather than sending one that is
        # ignored at best and contradicts the strategy at worst.
        if selections:
            raise AOWiringError(
                "agentic node '%s' uses tool_selection_strategy %s but the "
                "binding also selects tools; %s takes no tool list"
                % (node_id, strategy, strategy)
            )
        params.pop("tool_selections", None)

    return node


def _wire_aap_job_template(node, binding, resolved):
    params = node.setdefault("parameters", {})
    node_id = node.get("id")

    cred_key = binding.get("credential", "aap")
    params["credential_id"] = _lookup(resolved, "credentials", cred_key, node_id)

    integration_key = binding.get("integration", "aap")
    params["integration_id"] = _lookup(resolved, "integrations", integration_key, node_id)

    name = binding.get("job_template") or params.get("job_template_name")
    if name:
        params["job_template_name"] = name
        if is_expression(name):
            # Resolved at run time from an upstream node's artifacts.
            params.pop("job_template_id", None)
        else:
            job_template_id = (resolved.get("job_templates") or {}).get(name)
            if job_template_id is None:
                raise AOWiringError(
                    "node '%s' references AAP job template '%s', which does "
                    "not exist on the controller" % (node_id, name)
                )
            params["job_template_id"] = job_template_id

    organization = binding.get("organization") or resolved.get("organization")
    if organization:
        params["organization_name"] = organization

    extra_vars = binding.get("extra_vars")
    if extra_vars:
        merged = dict(params.get("extra_vars") or {})
        merged.update(extra_vars)
        params["extra_vars"] = merged

    return node


def _wire_trigger(trigger, binding, resolved):
    params = trigger.setdefault("parameters", {})
    trigger_id = trigger.get("id")
    trigger_type = trigger.get("type")

    keys = (binding or {}).get("service_accounts") or []
    if not keys:
        raise AOWiringError(
            "trigger '%s' (type %s) authorizes no service accounts. AO "
            "requires a non-empty authorized_service_account_ids on this "
            "trigger type and rejects the workflow without one — an empty "
            "list fails the same way, with '[] should be non-empty'."
            % (trigger_id, trigger_type)
        )

    table = resolved.get("service_accounts") or {}
    ids = []
    for key in keys:
        if not table.get(key):
            raise AOWiringError(
                "trigger '%s' authorizes service account '%s', which was not "
                "created (have: %s). The service account phase must run "
                "BEFORE workflow import, and "
                "..._manage_service_account must be true."
                % (trigger_id, key, ", ".join(sorted(table)) or "none")
            )
        ids.append(table[key])

    # AO checks these against the workflow's own project and returns a
    # hard 422 "Service account(s) not found in this project" — not a
    # validation finding — so a service account minted in a different
    # project fails the import outright.
    params["authorized_service_account_ids"] = ids
    return trigger


def _lookup(resolved, bucket, key, node_id):
    table = resolved.get(bucket) or {}
    if key not in table or table[key] is None:
        raise AOWiringError(
            "node '%s' needs %s '%s', which was not created or resolved "
            "(have: %s)" % (node_id, bucket.rstrip("s"), key,
                            ", ".join(sorted(table)) or "none")
        )
    return table[key]


def ao_wire_definition(definition, bindings, resolved):
    """Apply per-node wiring to a prepared workflow definition.

    `bindings` is the declarative node_id -> requirements map from
    vars/bindings_<key>.yml. `resolved` carries the IDs discovered at
    run time:

        {credentials: {key: id}, integrations: {key: id},
         integration_credentials: {integration_key: credential_key},
         tools: {integration_key: {tool_name: tool_id}},
         job_templates: {name: id}, llm_model_id: id, organization: str}

    Raises AOWiringError with a message naming the node and the missing
    asset, which beats letting AO return a generic schema violation.
    """
    wired = copy.deepcopy(definition)
    node_bindings = (bindings or {}).get("nodes", {})
    trigger_bindings = (bindings or {}).get("triggers", {})

    # Triggers are a sibling list of `nodes`, not members of it, so a
    # loop over nodes alone leaves them unwired. Only the types that
    # expose an HTTP endpoint need anything; manual and schedule
    # triggers are self-contained and are left alone.
    for trigger in wired.get("triggers", []):
        if trigger.get("type") not in AUTHORIZED_TRIGGER_TYPES:
            continue
        binding = trigger_bindings.get(trigger.get("id"))
        if binding is None:
            raise AOWiringError(
                "trigger '%s' (type %s) exposes an HTTP endpoint, so AO "
                "requires authorized_service_account_ids on it, but it has "
                "no entry under `triggers:` in the binding file"
                % (trigger.get("id"), trigger.get("type"))
            )
        _wire_trigger(trigger, binding, resolved)

    for node in wired.get("nodes", []):
        node_type = node.get("type")
        if node_type in SELF_CONTAINED_NODE_TYPES:
            continue
        if node_type not in WIRED_NODE_TYPES:
            raise AOWiringError(
                "node '%s' has unhandled type '%s'" % (node.get("id"), node_type)
            )

        binding = node_bindings.get(node.get("id"))
        if binding is None:
            raise AOWiringError(
                "node '%s' (type %s) has no entry in the binding file"
                % (node.get("id"), node_type)
            )

        if node_type == "agentic":
            _wire_agentic(node, binding, resolved)
        else:
            _wire_aap_job_template(node, binding, resolved)

    return wired


def ao_collection(payload):
    """Return the list of objects from an AO collection response.

    AO wraps every collection in {next, prev, total, resources}.
    `resources` is the key that matters; the others are accepted
    because some endpoints return a bare list and to keep this filter
    useful if the envelope ever changes.

    Doing this in Jinja is a trap: for a dict, `payload.items`
    resolves to the built-in `items()` *method* rather than falling
    through to a missing key, so a `default()` chain silently yields a
    bound method instead of the next candidate.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("resources", "items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def ao_name_id_map(payload, key_name="name", value_name="id"):
    """Map name -> id over an AO collection response."""
    return {
        entry[key_name]: entry[value_name]
        for entry in ao_collection(payload)
        if key_name in entry and value_name in entry
    }


def ao_validation_summary(validation_result):
    """Render `validation_result` findings as readable lines.

    AO returns {is_valid, error_count, warning_count, findings:[...]}
    where each finding has severity/category/message/node_id/field_path.
    """
    if not validation_result:
        return "no validation_result returned"

    findings = validation_result.get("findings") or []
    if not findings:
        return "is_valid=%s, no findings" % validation_result.get("is_valid")

    lines = []
    for finding in findings:
        lines.append(
            "[%s] %s: %s (node=%s field=%s)"
            % (
                finding.get("severity", "?"),
                finding.get("category", "?"),
                finding.get("message", "?"),
                finding.get("node_id", "-"),
                finding.get("field_path", "-"),
            )
        )
    return "\n".join(lines)


class FilterModule(object):
    def filters(self):
        return {
            "ao_prepare_definition": ao_prepare_definition,
            "ao_wire_definition": ao_wire_definition,
            "ao_required_job_templates": ao_required_job_templates,
            "ao_collection": ao_collection,
            "ao_name_id_map": ao_name_id_map,
            "ao_validation_summary": ao_validation_summary,
        }
