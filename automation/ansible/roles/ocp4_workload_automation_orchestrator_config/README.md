# ocp4_workload_automation_orchestrator_config

Day-2 configuration of a running Automation Orchestrator (AO), over its REST API.

The sibling role `ocp4_workload_automation_orchestrator` installs AO and stops at
"AO is up". This role fills it: project, credentials, integrations, and imported
workflows. Install and configuration are kept separate on purpose.

## What it builds

Everything lands in a single project, `solutions` — the reference implementation,
so the lab is runnable the moment it finishes provisioning.

| Asset | Type | Credential |
|---|---|---|
| `solutions` | project | — |
| LLM | integration | LLM Provider, from LiteLLM user_data |
| AAP | integration | Ansible Automation Platform |
| AAP MCP | integration | HTTP Bearer Token, **minted at provision time** |
| OpenFlake MCP | integration | HTTP Bearer Token, from `openflake_mcp_bearer_token` |
| Lightspeed MCP | integration | HTTP Bearer Token, **read off the cluster** |
| RHEL CVE Remediation | workflow | imported, wired, validated, published |
| Disk Utilization Remediation | workflow | imported, wired, validated, published |
| Ticket Enrichment Demo | workflow | imported, wired, validated, published |
| `aap-webhooks` | service account | client_id/secret patched onto AAP |

Lightspeed MCP's handshake and discovery are open — an `initialize` POST
returns 200 with no `Authorization` header and 200 with a bogus bearer, and
`/tools` listed 46 tools unauthenticated. Its tool *calls* are not: they reach
console.redhat.com on a service account's behalf.

That service account secret is the one the MCP server itself was deployed with,
so rather than make the catalog supply it twice this role reads it back out of
the cluster — `LIGHTSPEED_CLIENT_SECRET` in the `lightspeed-mcp-credentials`
Secret, created by the sibling `ocp4_workload_lightspeed_mcp_server` role. Set
`..._lightspeed_mcp_token` to override, and the Secret is not read at all.

The `default` project is deliberately **not** seeded. Module 02 is "Set Up
Integrations and Credentials" and module 03 is "Build the Workflow" — pre-seeding
`default` would hand students the answers.

## Ordering

This role must run **after** `infra.aap_configuration.dispatch`. Every
`aap_job_template` node needs a `job_template_id` resolved against the live AAP
controller, and dispatch is what creates those job templates. They are not
defined anywhere in this repo.

It must also run after the three MCP server workloads — it reads their Routes,
and for Lightspeed it reads the Secret `ocp4_workload_lightspeed_mcp_server`
creates. In the catalog it is the last workload in the list, so this holds.

## How workflow wiring works

An imported workflow is inert until its nodes carry IDs that only exist after the
surrounding assets are created. Only two node types need it — `agentic` and
`aap_job_template`. `script`, `switch` and `approval` are self-contained.

**Triggers need wiring too, and they are a sibling list of `nodes`, not members
of it** — so a loop over `nodes` alone leaves them inert. `manual_trigger` and
`schedule_trigger` are self-contained, but `webhook_trigger` and `eda_trigger`
expose an HTTP endpoint and must carry `authorized_service_account_ids`. AO
rejects the workflow without one:

```
[error] schema_violation: 'authorized_service_account_ids' is a required property
        (node=activity_e34a948c_7ecc_4414_85fe_8ad26beb2370 field=parameters)
```

That is a *trigger* id, not a node id, which is what makes the finding
confusing — the node it names is not in `nodes`. Ticket Enrichment Demo is the
only workflow here with one.

The mapping is declarative, one file per workflow, keyed by node ID:

- `vars/bindings_rhel_cve_remediation.yml`
- `vars/bindings_disk_utilization.yml`
- `vars/bindings_ticket_enrichment.yml`

A binding names the credential, integration, tools and job template a node needs
using role-local keys (`llm`, `aap`, `lightspeed_mcp`, …), never AO UUIDs.

The transform lives at the **collection** level, in
`automation/ansible/plugins/filter/ao_workflow.py`, and the task files reference
it by FQCN (`intro_ao_workshop.automation.ao_wire_definition`). It cannot live in
the role's own `filter_plugins/`: that directory is only loaded for a standalone
role, and is silently ignored once the role ships inside a collection — the
symptom is `No filter named 'ao_collection'` at the first `set_fact` that uses
one.

`tool_selection_strategy` is an enum of exactly **`ALL` | `NONE` | `SELECTED`**,
and only `SELECTED` carries a `tool_selections` list. `SELECTED` with an empty
list is rejected ("should be non-empty"), so a node that should get no tools is
`NONE`, not an empty `SELECTED`. The wiring filter enforces all three rules:
unknown strategy, empty `SELECTED`, and tools listed under `ALL`/`NONE` each
fail the provision.

Under `SELECTED` there are two ways to choose:

- `tools:` names them explicitly. Use this when the node's prompt calls specific
  tools by name — a renamed tool then fails the provision instead of silently
  handing the agent something it cannot call.
- `tools_all:` takes an integration's whole surface, pinned at provision time.
  Prefer the `ALL` strategy if you genuinely want "whatever the server offers",
  since that is resolved by AO at run time and cannot go stale.

In this role, `triage_agent` in RHEL CVE Remediation does the gathering and
carries 12 pinned read-only tools across Lightspeed and AAP MCP;
`investigate_agent` reasons over what triage found and is `NONE`. Both Ticket
Enrichment agents are pinned. Disk Utilization has no agentic nodes.

### Testing the wiring without an AO instance

```bash
python3 tests/test_ao_workflow.py
```

44 tests, no network. They run the real exported JSON through the real binding
files with faked IDs, and cover placeholder scrubbing, metadata synthesis,
expression handling, and each failure mode. Requires PyYAML.

## The three workflow exports differ

`rhel-cve-remediation.json` is a clean export: it carries its own
`schema_version`, `name` and `description`, and 12 nodes / 12 edges / 1 manual
trigger round-trip intact.

`ticket-enrichment.json` is also clean, and is the only one with a
`webhook_trigger` (path `openflake-incident`) instead of a manual trigger — so it
is the only workflow that needs the service account. Both its agentic nodes ship
`tool_selections: []`, which AO rejects outright when the strategy is `SELECTED`,
so they are not optional to wire. Its four "Update OpenFlake Ticket" nodes carry
opaque `activity_<uuid>` IDs and all resolve to the same job template; its two
remediation nodes launch whatever template the triage agent names at run time.
Neither agent writes to OpenFlake — every write goes through an AAP job template.

`disk-utilization-remediation.json` came from the AO workshop rather than this
repo, and needs more work before it can be posted:

- No `name`, `description` or `schema_version` — all synthesised at import.
- All nine of its `aap_job_template` nodes ship
  `"credential_id": "YOUR_AAP_CREDENTIAL_ID"`. A non-UUID string there crashes
  the AO server with an HTTP 500 rather than returning a clean 422, so the
  placeholder is stripped before the POST and a real UUID wired in afterwards.
  (The 500 is arguably an AO bug worth reporting upstream — a malformed
  `credential_id` should be a 422.)
- Its node IDs are opaque `activity_<uuid>` strings, so every binding entry is
  commented with the node's display name.

It has no `agentic` nodes at all, so it needs no LLM or MCP wiring — just the AAP
credential, the AAP integration, and resolved job template IDs.

## Payload shapes

Every shape this role sends was confirmed by creating the real object against a
live AO instance and reading the response back. The ones that are not guessable
from the exports, and that a reader would otherwise get wrong:

- **Collections are enveloped** as `{next, prev, total, resources}` — not a bare
  list. Always go through the `ao_collection` filter. (In Jinja, `json.items`
  resolves to the dict's built-in `items()` *method*, so a `default()` chain
  never falls through. That trap is why the filter exists.)
- **`integration_type`** is `llm_provider` / `ansible_automation_platform` /
  `mcp_server`, and must appear **both** at the top level and inside
  `configuration` — it is the discriminator for the configuration union.
  Omitting the nested copy fails with *"Unable to extract tag using
  discriminator"*.
- **The endpoint field is `base_url`** for all three integration types.
  `llm_provider` additionally requires `provider_hint`
  (`red_hat_ai|openai|anthropic|gemini|custom`).
- **Credential `inputs`** — `HTTP Bearer Token` takes `token`; `LLM Provider`
  takes `api_key` *only*; `Ansible Automation Platform` takes
  `username`+`password` **or** `oauth_token`, never both. `base_url`/`host` and
  `verify_ssl` are integration configuration, not credential inputs.
- **`tool_selections` holds tool *ids*, not tool names.** Both are strings and
  the request model is only `array(string)`, so AO accepts names without a
  murmur: the workflow imports `201`, reads back `has_validation_issues: false`,
  and publishes. The damage shows only in the UI, which resolves the list
  against live tool ids and drops what does not match —

  ```js
  hQ = integration => integration.discovered_tools.map(gQ)   // gQ = tool => tool.id
  valid = toolIds.filter(id => new Set(integrations.flatMap(hQ)).has(id))
  ```

  then reports *"N previously selected tools are no longer available and have
  been removed."* On a provisioned lab this cost RHEL CVE Remediation all 12 of
  its tools and Ticket Enrichment's two agents 2 and 1 — every selection, since
  a name never matches a UUID. **Neither validation nor the publish gate catches
  this**, so the only defence is sending ids and failing loudly when one cannot
  be resolved.
- **`scope` is `global` | `project`** (anything else: *"Input should be 'global'
  or 'project'"*). It is settable on create and on PATCH, and defaults to
  `project` when omitted. `project_id` is not accepted on create and
  `project_ids` is read-only, so a project-scoped integration is attached with
  a separate `POST /integrations/{id}/projects/{project_id}`.
- **A global integration cannot be associated with a project** — that POST is a
  422, and its project listing stays empty. Association is therefore
  project-scope-only, which is why `ao_create_integration.yml` guards it.
- **Accessibility is scope-aware, not association-based.** This is the part
  worth knowing, because the two findings above suggest the opposite: a global
  integration has no project associations, yet a workflow in `solutions` that
  cites it still imports. Measured by replaying the live RHEL CVE definition —
  7 `aap_job_template` nodes pointing at a global, unassociated AAP integration
  — which posted `201` with `has_validation_issues: false`. So "not accessible
  in this project" applies to *project*-scoped integrations attached elsewhere,
  not to global ones.
- **`GET /integrations/{id}/tools` is MCP-only.** For `ansible_automation_platform`
  and `llm_provider` it is a 422 *"Integration Type Mismatch"*, not an empty
  list — the same type-guard shape as `/refresh`.
- **`integration_connections` entries need `credential_id` as well as
  `integration_id`.** A bare `{integration_id}` fails validation with
  *"'credential_id' is a required property"* at
  `parameters.integration_connections.<n>`. Which credential belongs to which
  integration is the `_ao_integration_credentials` map in
  `tasks/setup_integrations.yml`, not something each binding restates.
- **`tool_selections` is a list of bare tool-name strings** (`["hosts_list"]`).
  Every object shape returns a 500.
- **Project association** is `POST /integrations/{id}/projects/{project_id}`,
  and the matching `GET` returns `project_id`/`project_name` — not `id`/`name`
  like every other collection.
- **Publish is version-scoped**: `POST /workflows/{id}/versions/{n}/publish`
  with an empty body. `/workflows/{id}/publish` is a 404. Take `n` from the
  workflow's `current_version`.
- **`validation_result` is only on write responses.** A later `GET` returns
  `null` and reports the outcome as the boolean `has_validation_issues`, so the
  findings must be captured from the POST/PATCH or they are lost. It is also
  absent on a *clean* write — a workflow that validates returns no
  `validation_result` at all, so "no findings" and "no result" look alike.
- **`authorized_service_account_ids` takes service ACCOUNT ids**, as a
  non-empty list. All four wrong answers fail differently, which is worth
  knowing because only the first is a validation finding: omitting the key is
  `'authorized_service_account_ids' is a required property`; `[]` is
  `'[] should be non-empty'`; the id of a *credential* belonging to that
  account, or any id from another project, is a hard **422** *"Service
  account(s) not found in this project"*.
- **A webhook path is globally unique.** A second trigger on the same
  `webhook_path` is a 409 `WEBHOOK_TRIGGER_PATH_CONFLICT`, across projects —
  so a student who builds a workflow on `openflake-incident` in `default`
  blocks this role's re-run.
- **Workflow references are checked at the API layer, before validation.**
  A node naming an integration of the wrong kind is a 422 (*"Integration 'AAP
  MCP' is type 'mcp_server', but this node requires type
  'ansible_automation_platform'"*), as is an integration not associated with
  the workflow's project (*"not accessible in this project"*) or a credential
  from another project. These never reach `validation_result`.

Two further things worth knowing:

**AO's base_url has an SSRF guard.** It rejects any URL resolving to a private,
reserved or cloud-metadata address, so integrations must point at public Routes
— an in-cluster `.svc` name will not work.

**Workflow validation is shallow but not absent.** A workflow with no
`credential_id`, no `llm_model_id`, no `integration_id` and no `job_template_id`
on any node still validates and publishes. What it does enforce is the JSON
schema of each node's parameters — a malformed `tool_selections`, or an
`integration_connections` entry missing `credential_id`, is rejected. `is_valid`
therefore means "structurally parseable", not "runnable" — it is not a
substitute for the qa-automation assertions.

## Re-run behaviour

Assets are matched on **name only** and reconciled with PATCH.

The reference implementation this role replaces deletes and recreates any
integration whose `validation_status` is not `available`. MCP integrations in
this lab routinely report a failed validation while the MCP protocol itself works
fine — so that rule re-creates them on every run, issuing fresh UUIDs and
silently breaking the workflow nodes still pointing at the old ones. Matching on
name keeps IDs stable.

The role does still *run* the validation — otherwise every integration it
creates would sit at `unknown`, looking unchecked next to the ones a student
creates by hand in module 02 — but a `success: false` is a loud warning naming
AO's own `error_type` and `error`, not a failed provision. The distinction is
the point: the status should be accurate, and it should not be load-bearing.

Secret material (`inputs`) and workflow definitions are re-pushed on every run,
so a rotated key or a corrected binding file actually lands.

`ACTION=destroy` deletes the `solutions` project, which cascades. `default` and
`built-in` are never touched.

## Conventions worth keeping

- **No trailing slashes.** `/api/v1/workflows/` 307-redirects to
  `/api/v1/workflows`, and a 307 does not reliably carry method, body and
  `Authorization` through Ansible's redirect handling.
- **Tokens expire in 900 s.** Each phase re-authenticates on entry and every poll
  loop is bounded below that, so a token cannot expire mid-phase.
- **Poll, never sleep.** `POST /api/v1/integrations/{id}/refresh` is mandatory
  before `/models` or `/tools` return addressable IDs, and it is asynchronous.
- **`/refresh` and `/validate` are orthogonal, and both are needed.** An
  integration is created at `validation_status: unknown` and stays there — a
  refresh that synced all 140 of AAP MCP's tools left the status untouched 20 s
  later. `POST /integrations/{id}/validate` is the only thing that moves it, and
  is what the UI's "Validate" button fires. Refresh populates `/models` and
  `/tools`; validate checks that the endpoint and credential actually work.
  Unlike refresh, validate has **no type guard** — `ansible_automation_platform`
  422s on refresh but validates normally — so it runs for all three types.
  It is synchronous: the status has moved by the time it returns.
- **A failed validation is HTTP 200.** The body is
  `{success, checked_at, error, error_type}`, and a base_url pointing at a live
  host that speaks no MCP returns
  `200 {"success": false, "error": "Method not allowed: HTTP 405",
  "error_type": "connection_error"}` while the integration goes to
  `validation_status: error`. So the status code proves nothing; only `success`
  does. The role warns on a false rather than failing — see *Re-run behaviour*.
- **`/tools` needs defensive parsing.** Tool descriptions contain raw control
  characters, which are illegal inside JSON strings — the response is read as
  text, scrubbed, then parsed.
- **`/tools` must be paged, and the pagination is keyset.** `limit` is capped at
  100 (101 is a hard 422, not a clamp) and AAP MCP exposes **140** tools — two
  pages. A run before paging returned exactly 100 with `job_templates_list`
  missing while `job_templates_retrieve` was present — a truncated list that
  wires cleanly and leaves the agent unable to call the tool its prompt names.
  Both are real tools; only the page boundary separated them. The
  envelope's `total` is **always null**; `next` carries a base64 cursor that
  decodes to `{created_at, direction, id, sort_field, sort_direction}`, sorted
  `created_at desc` (which is why a page is not alphabetical). So there is no
  page count up front — `ao_poll_tools.yml` runs a page budget and stops when
  the cursor is spent, and warns loudly if it stalls or the budget runs out.
  The envelope names the cursor but not the parameter that takes it back; that
  was measured against a live AO and is **`cursor`**.
- **AO validates the query string strictly.** Any parameter it does not declare
  is a 422 — `"Unknown query parameter(s): next"` — and one unknown name
  rejects the whole request even when the rest are valid. So an unknown
  parameter cannot be passed speculatively alongside a good one, and a
  mis-spelled cursor parameter fails loudly rather than being ignored.
  Pagination is implemented once for the whole API: `/projects` with `limit=1`
  returns the same cursor shape as `/tools`, which makes any collection a
  usable probe when no MCP integration exists yet.
- **Every collection GET sends `limit`.** AO's default page size is **20** when
  `limit` is omitted — measured by asking a 140-tool integration for its
  listing without one. Because every lookup here matches assets *by name*, a
  listing that quietly stops at 20 does not fail: it reports the asset as
  absent and creates a duplicate instead of reconciling. The lab's own assets
  are far under 20, but students create credentials and integrations by hand in
  module 02 in the same AO, so re-runs have no guaranteed margin.
  `_ao_collection_page_size` covers the ten collection GETs; `/workflows/{id}`
  and the other single-object GETs take no `limit`.
- **Model choice comes from `litellm_available_models`.** A hardcoded preference
  chain silently falls through to "first available" on this lab's qwen/minimax
  models, which makes a misconfiguration look like a success.

## The service account, and the `REPLACE_ME` bug

AgnosticV's `controller_credentials` creates an AAP credential named "Automation
Orchestrator" (type `AO webhooks`) with literal `client_id: REPLACE_ME` /
`client_secret: REPLACE_ME`, annotated "set manually". This role closes that: it
mints an AO service account and patches the pair onto the AAP credential.

Two API facts shape how:

- **`client_secret` is returned exactly once**, by the call that mints it. A
  later `GET` of the same credential omits the field. An existing service
  account's secret cannot be read back.
- **`rotate` is therefore the re-run path.** It keeps the credential record and
  its `identifier` stable, returns a fresh one-time secret, and leaves the
  previous one valid for `grace_period_seconds` (1 h). Create on the first run,
  rotate on every run after — minting a new credential each time would
  accumulate live credentials forever.

`identifier` is the client_id; it looks like `nx_sa_<16 hex>`. The token exchange
is `POST /api/v1/auth/token`, **form-encoded**, `grant_type=client_credentials`.

A service account is scoped to one project and is sharply limited: a token for an
account scoped to project X lists zero projects and 403s on `/integrations`. The
account is created in `solutions`; point
`..._service_account_project` at `default` if the lab ever needs AAP to trigger a
workflow the student built.

Its consumer is **Ticket Enrichment Demo**, the one workflow here with a
`webhook_trigger` rather than a manual trigger. AAP calls
`POST /api/v1/webhooks/openflake-incident`, which the API documents as
"Requires a service account Bearer token".

That makes the service account a **prerequisite of workflow import**, not a
step after it: the trigger has to carry the account's id, and AO validates the
reference when the workflow is posted. So `setup_service_account.yml` runs
*before* `setup_workflows.yml` — reversing those two is the
`'authorized_service_account_ids' is a required property` failure.

`..._manage_service_account: false` therefore **skips** Ticket Enrichment
rather than importing it unauthorized; AO will not accept a webhook trigger
with no authorized account, and an empty list fails too, so there is no
third option. The other two workflows are unaffected.

For the same reason, pointing `..._service_account_project` at `default` while
the workflows live in `solutions` breaks the import with a 422 — AO requires
the account and the workflow to share a project.

The AAP-side field names (`client_id`, `client_secret`) come from the AgnosticV
credential-type definition, not from any API, and are the one thing in this role
not verified against a live system — no AAP instance was available. They are
variables; correct them in `defaults/main.yml` if the PATCH 400s.

## Testing

Offline, no infrastructure — the wiring transform, against the real exports:

```bash
python3 tests/test_ao_workflow.py     # 44 tests
```

Against a live lab, after provisioning:

```bash
ansible-playbook qa-automation/healthcheck.yml \
  -e ao_url=https://<ao-route> -e ao_password=<admin-password>
```

The health check asserts what AO's own validation does not. Because validation is
structural, it asserts per-node that every `agentic` and `aap_job_template` node
carries a real `credential_id` (and no surviving `YOUR_*`/`REPLACE_*`
placeholder), that every agentic node has an `llm_model_id` and a non-empty tool
selection, and that every static AAP node resolved a `job_template_id` — skipping
nodes whose `job_template_name` is a `${...}` runtime expression. It also checks
that each MCP integration actually exposes tools and the LLM integration exposes
models, since a failed refresh leaves an integration that exists but is useless.

It asserts the student's `default` project still exists and is untouched.

## Not yet implemented

- **Seeding the `default` project**, which is intentionally a separate decision.
- **`qa-automation/e2e.yml`** — still the scaffold stub. Executing a workflow
  (`POST /api/v1/executions`) and polling it to completion would be the real
  end-to-end proof; the health check stops at "runnable".
