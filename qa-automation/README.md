# Service and credential health check

`healthcheck.yml` verifies availability and the supplied credentials for:

| Service | Checks |
| --- | --- |
| AAP | Authenticated gateway user API |
| AO | Admin login returns an access token |
| OCP | Console `/health`; `oc whoami` and API `/readyz` using the mounted kubeconfig |
| Gitea | User/password login and API token against the user API |
| Mattermost | User login against its API |
| Splunk | Web availability, Web login, and authenticated user context; alternatively authenticated management API if explicitly provided |
| OpenFlake | Readiness and authenticated incident listing (an empty incident table is valid) |
| RHEL access node | SSH using `ssh_command` and `ssh_password`; authenticated identity and `/etc/os-release` confirms RHEL |
| RHEL downstream nodes | SSH **from the access node** to internal `node1`, `node2`, `node3` (overridable); same supplied password if prompted; confirm RHEL |
| OpenFlake MCP | JSON-RPC initialization with the provided bearer token; JSON/SSE supported |
| LiteMaaS | Virtual key accepted and at least one model advertised |

No AO projects, workflow wiring, webhook accounts, Lightspeed service accounts,
cluster-wide node/operator/pod readiness, or EDA configuration are inspected.
No workflows, AAP jobs, MCP tools, LLM inference, or remediation are executed.
Authentication creates sessions/tokens. This is not a side-effect-free scan.

All service checks continue after failures and report a final passed/failed list.
Missing inputs are failures, not silent skips. Exit zero means all requested
checks passed; any failure or missing input results in a nonzero exit.

## Runner requirements

- Python 3, `ansible-core`, `pexpect`, and OpenSSH `ssh` on the runner.
- `oc` on the runner and a mounted, valid kubeconfig for the **lab cluster**.
- `ssh` on the RHEL access node, with network/DNS access to downstream nodes.
- Network/DNS access from the runner to the service URLs.

```bash
pip install ansible-core pexpect PyYAML
bash qa-automation/run-healthcheck.sh \
  -e @/run/secrets/provisioned-user-data.yml
```

Provisioning inputs can be Ansible extra vars or lowercase pod environment
variables. A mounted user-data file is not loaded automatically: pass it using
`-e @file.yml`. Lowercase `cnv_nodes` environment input must be a JSON array.
Canonical health-check extra vars override defaults; uppercase environment
variables take precedence over provisioning aliases.

### Provisioning aliases

| Canonical input | Pod / user-data name |
| --- | --- |
| `ao_url` | `ao_url` |
| `ao_username`, `ao_password` | `ao_admin_user`, `ao_admin_password` |
| `aap_url`, `aap_username`, `aap_password` | `aap_controller_web_url`, `aap_controller_admin_user`, `aap_controller_admin_password` |
| `ocp_console_url` | `openshift_console_url` |
| `openflake_url` | `openflake_url` or fallback `openflake_instance_url` |
| `openflake_username`, `openflake_password` | `openflake_admin_username`, `openflake_admin_password` |
| `gitea_url`, `gitea_username`, `gitea_password`, `gitea_token` | `gitea_console_url`, `gitea_user`, `gitea_password`, `gitea_api_token` |
| `mattermost_url`, `mattermost_username`, `mattermost_password` | Same names |
| `splunk_url`, `splunk_username`, `splunk_password` | Same names |
| `llm_url`, `llm_api_key` | `litellm_api_base_url` (includes `/v1`), `litellm_virtual_key` |
| `openflake_mcp_url`, `openflake_mcp_token` | `openflake_mcp_endpoint` (includes `/mcp`), `openflake_mcp_bearer_token` |
| `healthcheck_ssh_command`, `healthcheck_ssh_password` | `ssh_command`, `ssh_password` |
| `healthcheck_rhel_nodes` | `cnv_nodes`, or default internal names `node1`, `node2`, `node3` |

See `vars/services.yml` for uppercase environment variable names and defaults.
Use the lab Gitea user credentials, not the separate administrator pair.

### OpenShift kubeconfig

`oc` honors the runner's `KUBECONFIG` environment variable or `~/.kube/config`.
Set `healthcheck_kubeconfig` to select an explicit mounted file instead. Its
selected context must point to the lab, not the cluster hosting the runner.
The console URL is checked separately; it is not used to guess an API URL or
overwrite the kubeconfig server. Kubeconfig auth can be a user or service account;
no cluster-admin privileges are needed just to authenticate and read `/readyz`.
TLS and auth for the API follow kubeconfig settings.

### RHEL SSH topology

The supplied `ssh_command` must be an OpenSSH command with one destination, e.g.
`ssh student@bastion.example -p 30852`, with no shell wrapper or remote command.
The password is sent to SSH password prompts, not put in process arguments.
The access-node connection defaults to password/keyboard-interactive auth with
public-key auth disabled, so an existing key cannot mask a bad supplied password.
Explicit SSH options in `ssh_command` can override that policy.
Each downstream connection is a nested SSH command on that access node. The
runner never connects directly to `node*_external_ip`.

Each `cnv_nodes` entry uses `name` (or explicit `host`) reachable from the access
node, optional `ssh_user`, and optional `ssh_port` (default 22). Without a user,
SSH uses its normal remote-side defaults/config. For downstream connections,
existing keys may authenticate without a password prompt; in that case the check
proves SSH access, not password validity independently. Password prompts on either hop use `ssh_password`.
Override `healthcheck_rhel_nodes` if provisioning names do not resolve from the
access node. If `cnv_nodes` is missing or empty, the targets default to internal
hostnames `node1`, `node2`, and `node3` on port 22. Resolution and connections
happen on the gateway; no external IP variables are used. Gateway-side SSH
configuration selects the downstream username/key unless explicitly overridden.
An explicitly empty `healthcheck_rhel_nodes` fails rather than claiming success.

New SSH host keys are accepted by default; changed keys fail. Options supplied
in `ssh_command` take precedence. Normal SSH known-hosts files may be updated.
`healthcheck_ssh_timeout` (30 seconds) bounds each SSH check including both hops.

### Splunk

By default the check logs in through `/en-US/account/login` using the supplied
Web URL. It requires Splunk's JSON success status (`0`), merges the cookies from
both the initial page and login response, and requests authenticated user context
through `/en-US/splunkd/__raw/services/authentication/current-context?output_mode=json`.
The returned username must match the supplied user. No particular cookie name
or newly issued cookie is required. Override `splunk_web_context_path` if your
version uses a different proxy path. Alternatively, supply `splunk_api_url` / `SPLUNK_API_URL` for a reachable
management endpoint (usually HTTPS port 8089); the check then verifies current
user context using basic authentication. HEC/syslog NodePorts are not management
API endpoints.

## Readable output

Use `run-healthcheck.sh` in the pod's health-check launcher instead of calling
`ansible-playbook` directly. It selects the local `healthcheck` stdout callback
and supplies localhost inventory, removing the inventory warnings. Extra CLI
arguments are forwarded unchanged; the Ansible exit code is preserved.

```text
Health check — service availability and credentials

PASS — OpenShift console
PASS — AAP credentials and API
PASS — AO credentials and API
...
PASS — Splunk availability and credentials
PASS — OpenShift kubeconfig authentication and API readiness
PASS — RHEL access node
PASS — RHEL node node1 via access node
PASS — RHEL node node2 via access node
PASS — RHEL node node3 via access node

Summary: 16 passed, 0 failed

RESULT: PASSED (12.3s)
```

Failures include a one-line task diagnostic (limited to 300 characters) and a
final list of failed/not-validated checks. Successful intermediate tasks, skipped
tasks, include banners and full response objects are not printed. These are
individual probes, so multiple checks may belong to one service.

If your launcher must invoke `ansible-playbook` directly, configure its environment:

```bash
export ANSIBLE_CALLBACK_PLUGINS=/app/qa-automation/callback_plugins
export ANSIBLE_STDOUT_CALLBACK=healthcheck
ansible-playbook -i localhost, /app/qa-automation/healthcheck.yml
```

For raw Ansible troubleshooting, use:

```bash
ANSIBLE_STDOUT_CALLBACK=default bash qa-automation/run-healthcheck.sh -vv
```

## Logging and TLS

Compact output is formatting, not secret redaction. Logging is enabled; no tasks use `no_log: true`. Output may expose passwords,
tokens, cookies and API responses, particularly at high verbosity. Restrict log
access and redact before sharing. Never commit real credentials.

HTTP TLS verification defaults to on (`healthcheck_validate_certs`). Trust the
cluster CA on the runner. For disposable labs only, explicitly override to false.
The HTTP timeout is 15 seconds per request; there is no total-runtime guarantee.

## Offline tests

```bash
ansible-playbook -i localhost, qa-automation/healthcheck.yml --syntax-check
python3 -m unittest discover -s qa-automation/tests -v
```

Tests run real Ansible tasks against mock HTTP endpoints, an executable standing
in for `oc` with a mounted-file check, and a mock SSH client with password prompts
on both hops. They cover provisioning input mapping, missing kubeconfig, rejected
SSH passwords, internal-node defaults (ignoring external IPs), retained Splunk cookies, rejected Splunk
passwords, downstream command construction, response validation, missing
inputs, and JSON/SSE MCP initialization. They do not prove live service contracts
or actual network/SSH connectivity; rerun against the provisioned lab. Tests also
verify compact success/failure summaries, preserved nonzero exit codes, and
running the wrapper from outside the repository.
