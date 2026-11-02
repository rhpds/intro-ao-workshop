#!/usr/bin/env bash
set -euo pipefail
QA_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export ANSIBLE_CALLBACK_PLUGINS="${QA_DIR}/callback_plugins${ANSIBLE_CALLBACK_PLUGINS:+:${ANSIBLE_CALLBACK_PLUGINS}}"
export ANSIBLE_STDOUT_CALLBACK="${ANSIBLE_STDOUT_CALLBACK:-healthcheck}"
exec ansible-playbook -i localhost, "${QA_DIR}/e2e.yml" "$@"
