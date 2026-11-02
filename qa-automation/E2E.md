# Native Ansible Showroom E2E

This suite follows the structure of the [Image Mode Operational Updates E2E
reference](https://github.com/rhpds/image-mode-operational-updates/blob/main/qa-automation/e2e.yml):
initialize inventory and lab facts, perform the lab operations in module order,
validate registered outputs, fail on the first error, and report the outcome.

**There is no Python E2E runner.** `e2e.yml` includes native task files under
`tasks/e2e/`. API operations use `ansible.builtin.uri`, polling uses
`until`/`retries`/`delay`, checks use `assert`, host checks use delegated Ansible
modules, and cleanup uses `block`/`rescue`/`always`.

Use a **disposable, exclusive lab**, never one being used by students. Unlike the
service health check, E2E runs real workflows and makes persistent changes.

## Module sequence and validations

| Module | Cases | Required evidence |
| --- | --- | --- |
| 02 — integrations | `integrations` | Target AAP MCP integration discovers the three tools used by later agents; target LLM integration discovers models |
| 03 — MOTD | `motd` | Real manual AO run; every step completes; linked AAP jobs succeed; AI headline/notice/owner and this run's reference appear in `/etc/motd` on node1–3, alongside kernel facts |
| 04 — disk | `disk_healthy`, `disk_warning`, `disk_critical` | AAP simulator fills to 50/85/97%; its exact AO execution takes the expected branch; linked jobs succeed; cleanup reports reclaimed space, expansion reports increased volume/lower utilization; direct `df` confirms expansion; a new Mattermost card matches host/tier |
| 05 — tickets | `ticket_auto`, `ticket_approval`, `ticket_inform` | AAP simulator creates one incident; exact AO execution takes the correct branch; linked jobs succeed; OpenFlake state/notes match Resolved or In Progress; capacity ballast/process cleanup is independently checked |
| 06 — CVE | `cve_dev`, `cve_prod` | Tag-scoped Insights host is affected before the test; AAP host env is dev/production; correct AO route and successful patch job limited to that host; new Gitea commit/nonempty playbook; new Mattermost card; same Insights system UUID eventually stops reporting the CVE |

Approval cases must be observed **pending**, with downstream remediation not yet
started. The test prints `WAIT` with the exact execution ID; a human reviews and
submits the decision in AO. The playbook then waits for completion. It never
auto-approves production changes. Unlike a subprocess runner, native Ansible
prints the approval instruction immediately; there is no progress-file/tail step.

A Completed workflow alone does not pass: the required graph branch must have
executed, alternative branches must not have completed, and actual linked AAP
jobs must have succeeded. The suite never chooses the newest/historic execution
as a substitute for the one it launched.

## Scope

Default target: the complete, published workflows in `solutions`. Set
`e2e_project=default` to test a student's **completed, published** workflows.
Workflow lookup uses exact name and project. The AAP simulator receives the
matching `webhook_target` (`solutions` or `student`); its existing injected
credentials handle webhook authentication. Before each launch, Ansible reads the
live survey, resolves short values to exact dropdown labels, and sends
multiselect answers as lists. It also reads template prompt permissions: if
arbitrary extra vars are disabled, only survey answers are submitted and the
fixed template limit must match the requested node plus localhost. The test does
not loosen AAP template permissions or silently target a different host.

The suite does not automate browser clicks, create the Student integrations,
complete unfinished drafts, or publish workflows. Module 02 checks existing
integration discovery; later workflows exercise inference and tools. AI wording
is not hardcoded. OCP/Splunk service authentication remains health-check scope.

## Provided variables

The playbook uses the same `vars/services.yml` aliases as the health check:

- AO: `ao_url`, `ao_admin_user`, `ao_admin_password`
- AAP: `aap_controller_web_url`, `aap_controller_admin_user`, `aap_controller_admin_password`
- OpenFlake: `openflake_url`, `openflake_admin_username`, `openflake_admin_password`
- Mattermost: `mattermost_url`, `mattermost_username`, `mattermost_password`,
  `mattermost_webhook_token`
- Gitea: `gitea_console_url`, `gitea_api_token`, `gitea_playbook_repo`
- Insights: `insights_username`, `insights_password`, `guid`
- Gateway: `ssh_command`, `ssh_password`, plus `ssh_address`, `ssh_username`,
  `ssh_port` if available

Pass user-data as Ansible extra vars or use the supported lowercase pod environment
variables. Merely mounting a user-data file does not load it. No environment URL
or credential value is embedded in the tests.

`e2e_gitea_repo` must be `owner/repository`. Override it if the provisioned
`gitea_playbook_repo` is only a repository name or clone URL. Insights REST calls
use the provided username/password, not an invented OAuth client secret.

When `mattermost_webhook_token` is supplied, the suite reads its incoming-hook
metadata to select the actual lab notification channel. It does not post a test
message and does not require the administrator to be a team member. An explicit
`e2e_mattermost_team` overrides that selection; without a hook, unique user-team
membership is required.

## Node-serving certificate repair before job execution

`e2e_approve_kubelet_serving_csrs: true` enables a native Ansible preflight for
cases that execute AAP jobs (it is skipped for integrations-only runs). It uses
the mounted kubeconfig via `oc`, honoring `KUBECONFIG` or
`healthcheck_kubeconfig`, and requires OpenSSL on the runner.

Before approval it verifies this cluster's console Route matches the provided
`openshift_console_url`. It selects the newest `kubernetes.io/kubelet-serving`
request for each registered node, then proceeds only if that request is pending.
Older pending requests are not approved behind a newer approved or denied one.
Requester, node group, server-only usages, cryptographic signature, exact CN/O,
and every DNS/IP SAN must match the registered node; unknown nodes, client CSRs,
unexpected SAN types and invalid requests are never approved.

After approving that specific request, it waits for certificate issuance and
checks API-server-to-kubelet `/proxy/healthz` before starting jobs. Approvals are
recorded in the evidence JSON. This repairs the serving-certificate condition
that can cause `error dialing backend: remote error: tls: internal error` during
AAP pod execution; it does not bypass TLS verification or approve unrelated CSRs.
Set the flag to false to disable this repair. The kubeconfig identity needs
permission to read nodes/console Routes/CSRs, approve serving CSRs and access node
proxy health; a namespace-only service-account token is not sufficient.

## Inventory and gateway

The playbook uses `add_host` to build:

```text
QA runner → e2e_gateway → node1 / node2 / node3
```

Internal names resolve through an SSH `ProxyCommand`; external node IPs are not
needed. The gateway host/user/port come from the flat provisioned SSH values,
falling back to a standard `ssh USER@HOST -p PORT` command. For a command with
custom wrappers/options, supply `e2e_gateway_host`, `e2e_gateway_user`, and
`e2e_gateway_port` explicitly.

The playbook runs `ssh -G node1` (and node2/node3) on the gateway to discover
the username, hostname and port its existing SSH config uses. This follows the
Showroom terminal's node aliases rather than guessing a username. Internal-node
authentication uses the supplied password; override `e2e_node_user` /
`e2e_node_password` if needed. Runner-side SSH keys may also authenticate the
node connection; private keys are not copied from the gateway. New host keys are
accepted; changed host keys are rejected.

Requirements: `ansible-core`, OpenSSH and **sshpass on the QA runner**, plus `oc`
and OpenSSL for the enabled node-serving certificate repair, and Python
on the managed RHEL hosts for normal Ansible modules. No pexpect dependency or
custom SSH script is used by E2E. The health check's separate SSH helper is
unchanged. A mode-0600 temporary password file supplies the gateway proxy; the
password is not placed in `sshpass -p` process arguments. `always` removes this
file on normal/task/delegated-connection failure. Force-killing the runner may
leave the private workspace behind; remove it manually after stopping active work.

## Default unattended run

Invoking `e2e.yml` authorizes changes to this disposable lab. The permission
flags (`e2e_allow_changes`, `e2e_allow_disk_expand`, `e2e_allow_patching`) default
to **true** so the pod's launcher needs no extra E2E options. Set a flag to false
explicitly to prohibit that class of change.

The five default cases are `integrations`, `disk_healthy`, `disk_warning`,
`ticket_auto`, and `ticket_inform`. They do not require a human approval or a CVE
fixture; they still allocate disk ballast and create incidents. MOTD is excluded
while its AO agent returns empty structured output; it is not counted as passed.
Explicitly select `motd` after the workflow/model issue is resolved.

```bash
ansible-playbook -i localhost, qa-automation/e2e.yml \
  -e @/run/secrets/provisioned-user-data.yml
```

For compact output, replace `ansible-playbook -i localhost, qa-automation/e2e.yml`
with `bash qa-automation/run-e2e.sh`. The shell launcher only configures Ansible's
stdout callback; all testing logic is in Ansible tasks. Default callback output
remains available via `ANSIBLE_STDOUT_CALLBACK=default`.

The approval, critical-disk and CVE cases are supported but not selected by
default. For the full ten-case suite, choose a **currently
applicable, remediable critical CVE affecting node1 and node2**, as described in
module 06, and set `E2E_CVE_ID` in the QA pod. Then:

```bash
bash qa-automation/run-e2e.sh \
  -e @/run/secrets/provisioned-user-data.yml \
  -e '{"e2e_cases":["integrations","motd","disk_healthy","disk_warning","disk_critical","ticket_auto","ticket_approval","ticket_inform","cve_dev","cve_prod"]}'
```

Explicitly disabled permissions, or missing CVE/GUID for selected CVE cases, fail
before contacting APIs. API, workflow,
simulator and CVE preflight checks run before module operations. No placeholder
GUID/domain or missing-host skip is used to turn an incomplete run into a pass.

## Timeouts, side effects and cleanup

- Polling: `e2e_timeout` defaults to 900 seconds per wait;
  `e2e_poll_interval` defaults to 5 seconds. API requests use `healthcheck_timeout`.
- TLS verification defaults to enabled. Use `healthcheck_validate_certs=false`
  only as an explicit disposable-lab exception.
- Run only one E2E suite per environment. Use an external CI/environment lock;
  this suite does not implement a cross-runner lock.
- MOTD remains updated. Incidents, work notes, jobs, executions and chat posts
  are retained as evidence.
- Disk tests use a unique rotated-log ballast path when extra-var overrides are
  enabled. For fixed templates, they use the simulator's default and capture its
  actual path from stdout. The `always` block runs reset (0) once AO is known to
  have stopped and no AAP launch remains active, then independently verifies the
  actual ballast is absent. Volume growth is **not** shrunk back.
- Ticket tests refuse to overwrite a preexisting capacity/process fixture.
  Successful remediation verifies cleanup. Failed fixtures are retained for
  investigation, not deleted or killed indiscriminately.
- CVE tests install real patches, commit a playbook, sync AAP projects, create
  remediation job templates and may refresh Insights registration. No rollback
  of these changes is attempted. A rerun may need another CVE or a fresh lab.
- POSTs are not retried. Explicit AAP validation/auth rejection is reported as a
  rejected request, not an active job. A lost launch response is an **unknown outcome**. On
  timeout/unknown execution, the suite stops and does not reset ballast while a
  workflow might still be remediating it. Inspect recorded IDs, stop/wait for
  active work, then run simulator reset for the recorded ballast path.

A private JSON evidence report is retained in the run's temporary workspace;
`e2e_report_path` overrides the destination. It records passed cases, failed task,
not-passed cases, exact execution/job/incident IDs and CVE evidence where available.
The temporary proxy password is removed separately, not the evidence directory.
Logging is enabled: no `no_log: true`; verbose Ansible output can expose secrets.

## API compatibility

AO workflow readback uses `version.workflow_definition`. The playbook reads
OpenAPI to discover the execution input property and node-results endpoint;
unknown mandatory fields fail rather than guessing a launch body. Schema discovery
checks the preferred `e2e_ao_openapi_url`, then same-origin `/api/v1/openapi.json`
and `/api/openapi.json` paths. It rejects HTTP-200 HTML/UI fallback pages and
parses valid JSON even if the response is mislabeled as text. Some AO builds
expose no backend schema at all. In that case, `vars/ao-v1-contract.yml` supplies
the minimal contract verified against the deployed frontend: `input_data`,
`trigger_node_id`, `use_published: true`, and `/executions/{id}/activities`.
This is a versioned compatibility contract, not a complete backend OpenAPI spec.
Set `e2e_allow_bundled_contract=false` to require schema discovery instead; its
failure lists attempted URLs, HTTP statuses and content types.

Override `e2e_ao_openapi_url`, `e2e_ao_execute_path`, `e2e_ao_input_field`, or
`e2e_ao_steps_path` for a different deployed API contract. Node records must expose
`node_id`/`activity_name`/`activity_id`, `status`, and AAP `output.job_id` (or
`output.result.job_id`). AO's `output_data` is normalized to `output`. If node
results are embedded in execution detail, no
separate steps path is needed.

These version-specific contracts, SSH proxy access, all module outcomes and
Insights eventual consistency still require a live disposable-lab validation.
Offline mocks are not proof that the deployed lab passes.

## Offline validation

```bash
ansible-playbook -i localhost, qa-automation/e2e.yml --syntax-check
python3 -m unittest discover -s qa-automation/tests -v
```

The E2E tests execute **real Ansible tasks** against a local mock HTTP server,
using the checked-in workflow graphs. They cover the module-02 entry point,
paginated project lookup, simulator-to-execution-to-incident flow, human approval,
wrong branches/failed jobs, native dev/production CVE evidence, disk cleanup and
independent expansion validation, new-card correlation, consent guards, and
pagination origin checks. Separate CSR tests run the real Ansible/OpenSSL tasks
against a mock `oc`, checking identity/SAN/signature validation, latest-request
selection, idempotence, wrong-cluster protection and backend health failures.
Python is used only for the offline fixtures, not for E2E execution.
