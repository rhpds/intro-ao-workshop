# Lab health check

`healthcheck.yml` checks service readiness and credentials without running a
workflow, launching an AAP job, changing a ticket, or sending a chat message.
Authentication exchanges create short-lived sessions/tokens; MCP initialization
may create a protocol session. This is not a completely side-effect-free scan.

## Coverage

| Service | Checks |
| --- | --- |
| OpenShift | API `/readyz`, authenticated user identity, console health, all nodes Ready, cluster operators Available and not Degraded, pod readiness in lab namespaces (including databases) |
| Automation Orchestrator | Admin login; complete paginated project/credential/integration/workflow/service-account listings; reference workflow configuration; MCP tool discovery and LLM model discovery; both webhook service accounts active and client credentials accepted |
| AAP | Gateway user authentication, controller API availability, AAP MCP bearer token against controller user API, Automation Decisions API |
| OpenFlake | Readiness and authenticated incident listing (empty incident table is valid) |
| Gitea | User password authentication and lab API token authentication |
| Mattermost | System ping and user login |
| LLM / LiteLLM | Virtual key accepted and at least one advertised model |
| MCP servers | AAP, OpenFlake and Lightspeed JSON-RPC initialization, with configured bearer tokens; JSON and SSE responses supported |
| Red Hat Lightspeed | Red Hat SSO service-account client ID/secret token exchange |
| Splunk | Web login page and authenticated management API current-user context |

Service checks record PASS/FAIL and continue through the remaining probes. A
summary is printed before AO configuration checks. AO configuration assertions
remain fail-fast. Any service failure ultimately gives a nonzero exit; missing
inputs and export placeholders fail rather than silently skipping a service.

## Run

Requirements: Python 3, `ansible-core` (tested with 2.21.5), and network/DNS access
from the runner to every supplied endpoint. No extra Ansible collections or `oc`
CLI are needed. The OpenShift token must represent a user able to read nodes,
cluster operators, and pods in the selected namespaces (an admin token is suitable
for a lab). The identity check intentionally uses an OpenShift **user** token,
not a Kubernetes service-account token. It validates that token, not a separately
supplied OpenShift password.

```bash
python3 -m venv /tmp/ao-qa
source /tmp/ao-qa/bin/activate
pip install ansible-core
cp qa-automation/healthcheck.example.yml /tmp/ao-healthcheck.yml
# Edit /tmp/ao-healthcheck.yml with the provisioned endpoints and credentials.
ansible-vault encrypt /tmp/ao-healthcheck.yml
ansible-playbook -i localhost, qa-automation/healthcheck.yml \
  -e @/tmp/ao-healthcheck.yml --ask-vault-pass
```

Use provisioned `user_data` for the values; the playbook deliberately does not
read cluster Secrets or silently select credentials from your kubeconfig. For a
locally authenticated OpenShift user, obtain `ocp_url` with `oc whoami --show-server`
and `ocp_token` with `oc whoami --show-token`. Treat that output as secret.

All defaults/environment variable names are in `vars/services.yml`. For example,
`AO_URL`, `AO_PASSWORD`, `OCP_URL`, `OCP_TOKEN`, `AAP_URL`, `AAP_PASSWORD`,
`GITEA_TOKEN`, and `LLM_API_KEY` can be exported instead of passed in a vars file.
`llm_url` / `LLM_URL` must include the provider's `/v1` suffix; MCP URLs include
`/mcp`. Do not put real credentials on command lines or in version control.
Request/response tasks use `no_log`; only check names and outcomes are reported.
Avoid debug callbacks that dump all Ansible variables.

TLS verification defaults to **on**. Trust your cluster CA on the runner. For
disposable environments only, explicitly set `healthcheck_validate_certs: false`.
The default request timeout is 15 seconds (`healthcheck_timeout`); there is no
60-second total-runtime guarantee.

### Catalog differences

- The default namespaces are `automation-orchestrator`, `aap`, `openflake`,
  `openflake-mcp`, `lightspeed-mcp`, `mattermost`, and `gitea`; `splunk` is appended
  when enabled. Override `healthcheck_ocp_namespaces` to match your deployment.
  Each namespace must have pods. Completed Job pods are ignored; other pods must
  be Ready and not terminating. This does not prove desired deployment replica
  counts, VM readiness, or database password validity independently of the apps.
- Splunk and Automation Decisions checks are enabled by default. Explicitly set
  `splunk_enabled: false` or `aap_eda_enabled: false` **only if not deployed**.
- `splunk_api_url` is the management API, usually HTTPS port **8089**, not the
  Splunk UI Route. Provide a reachable management endpoint or an SSH/port-forward
  tunnel; the web UI alone cannot prove the password works.
- AAP 2.7 gateway paths are defaults. For standalone Controller use
  `aap_me_path: /api/v2/me/`, `aap_controller_me_path: /api/v2/me/`, and
  `aap_controller_ping_path: /api/v2/ping/`. Override `aap_eda_path` if needed.
- Supply both AO webhook client ID/secret pairs via `ao_webhook_accounts` or
  `AO_SOLUTIONS_CLIENT_ID`, `AO_SOLUTIONS_CLIENT_SECRET`, `AO_STUDENT_CLIENT_ID`,
  and `AO_STUDENT_CLIENT_SECRET`. Provisioning stores these on AAP; do not rotate
  credentials just to run a health check.

## Deliberate limits

A successful model listing does not prove inference works or has quota. MCP
initialization/tool discovery does not execute tools and cannot prove downstream
permissions. In particular Lightspeed MCP discovery is open even with a bogus
token; the separate Red Hat SSO exchange checks the actual service-account pair,
not whether every Lightspeed API operation is authorized. OpenFlake MCP enforces
its bearer token at the proxy; AAP MCP's token is also checked directly against
Controller. A healthy app/database pod is not a separate database login test.
Incoming Mattermost webhook secrets are not exercised because doing so posts a
message. RHEL VM SSH access and Insights registration are not checked here.

The reference workflows are checked only in `solutions`. Incomplete student
workflows in `default` are intentional and are not validated or modified. Use
`e2e.yml` (currently a scaffold stub) for future execution/remediation tests.

## Offline tests

```bash
pip install ansible-core PyYAML
ansible-playbook -i localhost, qa-automation/healthcheck.yml --syntax-check
python3 -m unittest discover -s qa-automation/tests -v
```

The tests run the real reusable Ansible tasks against a local mock HTTP server:
valid/invalid credentials, HTML masquerading as a successful API response, empty
model listings, missing inputs, JSON-RPC errors, SSE initialization, unhealthy
nodes, completed Job pods, empty namespaces, pagination, and secret redaction.
They do not verify the live lab's API contracts; run against a provisioned lab
before declaring it ready.
