# ocp4_workload_automation_orchestrator

Installs the Automation Orchestrator operator via OLM and creates a ready-to-use
`AutomationOrchestrator` instance backed by a dedicated PostgreSQL 15 StatefulSet.

## What this role does

**Provision (`ACTION: provision`)**

1. Installs `automation-orchestrator-operator` from the `redhat-operators` catalog via OLM
2. Creates PostgreSQL secrets and deploys a PostgreSQL 15 StatefulSet with PVC and Service
3. Runs a one-shot database setup Job to create the orchestrator and Temporal databases
4. Creates an `AutomationOrchestrator` CR and waits for it to reach `Ready`
5. Publishes the AO URL and initial admin password via `agnosticd.core.agnosticd_user_info`

**Destroy (`ACTION: destroy`)**

Removes the `AutomationOrchestrator` CR, database secrets, PostgreSQL StatefulSet/Service/PVC,
the operator, and the namespace.

## Requirements

**Collections**

- `kubernetes.core` — `k8s`, `k8s_info` modules
- `agnosticd.core` — `agnosticd_user_info` module
- A role named `install_operator` available on the Ansible path (AgnosticD convention)

**Cluster variables** (must be set before calling this role)

| Variable | Description |
|---|---|
| `openshift_cluster_ingress_domain` | Cluster apps domain, e.g. `apps.cluster-GUID.example.com` |
| `output_dir` | Path where generated password files are written (AgnosticD convention) |

## Role Variables

### OLM Operator

| Variable | Default | Description |
|---|---|---|
| `ocp4_workload_automation_orchestrator_channel` | `stable` | OLM subscription channel |
| `ocp4_workload_automation_orchestrator_automatic_install_plan_approval` | `true` | Auto-approve install plans |
| `ocp4_workload_automation_orchestrator_starting_csv` | `""` | Pin a specific CSV; empty = latest in channel |

### Namespace and Instance

| Variable | Default | Description |
|---|---|---|
| `ocp4_workload_automation_orchestrator_namespace` | `automation-orchestrator` | Namespace for all resources |
| `ocp4_workload_automation_orchestrator_name` | `aap-orchestrator` | Name of the `AutomationOrchestrator` CR |
| `ocp4_workload_automation_orchestrator_ingress_hostname` | `""` | Ingress hostname prefix; empty = `<name>.<cluster-apps-domain>` |

### PostgreSQL Instance

| Variable | Default | Description |
|---|---|---|
| `ocp4_workload_automation_orchestrator_postgres_service` | `ao-postgres-15` | StatefulSet and Service name |
| `ocp4_workload_automation_orchestrator_postgres_image` | `registry.redhat.io/rhel9/postgresql-15` | Container image |
| `ocp4_workload_automation_orchestrator_postgres_image_tag` | `latest` | Image tag |
| `ocp4_workload_automation_orchestrator_postgres_storage_size` | `10Gi` | PVC size |
| `ocp4_workload_automation_orchestrator_postgres_storage_class` | `""` | StorageClass; empty = cluster default |

### PostgreSQL Connection

| Variable | Default | Description |
|---|---|---|
| `ocp4_workload_automation_orchestrator_postgres_port` | `5432` | Port |
| `ocp4_workload_automation_orchestrator_postgres_ssl_mode` | `prefer` | SSL mode |
| `ocp4_workload_automation_orchestrator_postgres_pool_size` | `20` | Connection pool size |
| `ocp4_workload_automation_orchestrator_postgres_max_overflow` | `10` | Max pool overflow |
| `ocp4_workload_automation_orchestrator_postgres_pool_timeout_seconds` | `5` | Pool timeout |

### Credentials (auto-generated)

Passwords are generated via `lookup('password', output_dir ~ '/...', length=20)` and written
to files under `output_dir`. Do not set these manually unless you need to pin a specific value.

| Variable | Secret name | Description |
|---|---|---|
| `ocp4_workload_automation_orchestrator_postgres_admin_password` | `ao-postgres-admin` | PostgreSQL superuser password |
| `ocp4_workload_automation_orchestrator_backend_db_password` | `orchestrator-pg-credentials` | Orchestrator database password |
| `ocp4_workload_automation_orchestrator_temporal_db_password` | `temporal-pg-credentials` | Temporal database password |

### Wait / Retry Tuning

| Variable | Default | Description |
|---|---|---|
| `ocp4_workload_automation_orchestrator_operator_wait_retries` | `30` | Retries waiting for operator |
| `ocp4_workload_automation_orchestrator_operator_wait_delay` | `10` | Delay (s) between operator retries |
| `ocp4_workload_automation_orchestrator_postgres_wait_retries` | `20` | Retries waiting for PostgreSQL pod |
| `ocp4_workload_automation_orchestrator_postgres_wait_delay` | `10` | Delay (s) between PostgreSQL retries |
| `ocp4_workload_automation_orchestrator_db_setup_wait_retries` | `20` | Retries waiting for DB setup Job |
| `ocp4_workload_automation_orchestrator_db_setup_wait_delay` | `10` | Delay (s) between DB setup retries |
| `ocp4_workload_automation_orchestrator_instance_wait_retries` | `40` | Retries waiting for AO instance Ready |
| `ocp4_workload_automation_orchestrator_instance_wait_delay` | `15` | Delay (s) between AO instance retries |

## Outputs

Published via `agnosticd.core.agnosticd_user_info` at the end of provisioning:

| Key | Description |
|---|---|
| `ao_url` | HTTPS URL of the Automation Orchestrator UI |
| `ao_admin_user` | Admin username (`admin`) |
| `ao_admin_password` | Initial admin password (retrieved from `<name>-initial-admin-password` secret) |

## Dependencies

- Role `install_operator` (AgnosticD)

## Example Playbook

```yaml
- hosts: localhost
  gather_facts: false
  roles:
    - role: intro_ao_workshop.automation.ocp4_workload_automation_orchestrator
  vars:
    ACTION: provision
    openshift_cluster_ingress_domain: apps.cluster-guid.example.com
    output_dir: /tmp/output_dir
```

## License

Apache-2.0
