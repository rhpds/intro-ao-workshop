"""Offline integration tests of the real Ansible task files.

Run: python3 -m unittest discover -s qa-automation/tests -v
Requires ansible-playbook on PATH and PyYAML. No live lab is contacted.
"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import yaml

QA = Path(__file__).resolve().parents[1]
SECRET = "test-secret-sentinel"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        parsed = urlsplit(self.path)
        status = 200
        data = {"id": "user-1", "login": "admin", "metadata": {"name": "admin"},
                "results": [{"id": 1}], "data": [{"id": "model"}], "result": [],
                "version": "2.7", "status": "OK", "entry": [{"name": "admin"}],
                "access_token": "mock-access-token"}
        if parsed.path == "/unauthorized":
            status, data = 401, {"error": "bad credentials"}
        elif parsed.path == "/html":
            data = "<html>login page</html>"
        elif parsed.path == "/empty":
            data = {"data": []}
        elif parsed.path == "/identity":
            if self.headers.get("Authorization") != "Bearer " + SECRET:
                status, data = 401, {"error": "bad credentials"}
        elif parsed.path == "/readyz":
            data = "ok"
        elif parsed.path in ("/nodes", "/unready", "/completed", "/no-resources", "/api/v1/nodes", "/apis/config.openshift.io/v1/clusteroperators") or parsed.path.endswith('/pods'):
            resources = [{"metadata": {"name": "node1"}, "status": {
                "phase": "Running", "conditions": [
                    {"type": "Ready", "status": "True"},
                    {"type": "Available", "status": "True"},
                    {"type": "Degraded", "status": "False"}]}}]
            if parsed.path == "/unready":
                resources[0]["status"]["conditions"][0]["status"] = "False"
            elif parsed.path == "/completed":
                resources[0]["status"] = {"phase": "Succeeded"}
            elif parsed.path == "/no-resources":
                resources = []
            data = {"items": resources}
        elif parsed.path == "/api/v1/projects":
            if parse_qs(parsed.query).get("cursor") == ["next-page"]:
                data = {"resources": [{"id": "2", "name": "solutions"}], "next": None}
            else:
                data = {"resources": [{"id": "1", "name": "default"}], "next": "next-page"}
        elif parsed.path == "/mcp":
            data = 'event: message\ndata: {"jsonrpc":"2.0","result":{"serverInfo":{"name":"test"}}}\n\n'
        elif parsed.path == "/mcp-error":
            data = {"jsonrpc": "2.0", "error": {"message": "not authorized"}}
        body = (data if isinstance(data, str) else json.dumps(data)).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json" if not isinstance(data, str) else "text/plain")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.do_GET()


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class HealthcheckTests(unittest.TestCase):
    def test_provisioning_aliases_and_override_precedence(self):
        aliases = {
            'ao_url': 'https://ao.example', 'ao_admin_user': 'ao-admin',
            'ao_admin_password': SECRET,
            'aap_controller_web_url': 'https://aap.example/',
            'aap_controller_admin_user': 'aap-admin',
            'aap_controller_admin_password': SECRET,
            'openshift_console_url': 'https://console.example/',
            'openflake_url': 'https://openflake.example',
            'openflake_admin_username': 'flake-admin',
            'openflake_admin_password': SECRET,
            'gitea_console_url': 'https://gitea.example/',
            'gitea_user': 'lab-user', 'gitea_password': SECRET,
            'gitea_api_token': SECRET,
            'litellm_api_base_url': 'https://llm.example/v1/',
            'litellm_virtual_key': SECRET,
            'aap_mcp_url': 'https://aap.example/mcp',
            'openflake_mcp_endpoint': 'https://flake.example/mcp',
            'openflake_mcp_bearer_token': SECRET,
            'lightspeed_mcp_endpoint': 'https://lightspeed.example/mcp',
            'mattermost_url': 'https://chat.example',
            'mattermost_username': 'chat-admin', 'mattermost_password': SECRET,
            'splunk_url': 'https://splunk.example',
            'splunk_username': 'splunk-admin', 'splunk_password': SECRET,
        }
        mapping = {
            'ao_username': 'ao_admin_user', 'ao_password': 'ao_admin_password',
            'aap_url': 'aap_controller_web_url',
            'aap_username': 'aap_controller_admin_user',
            'aap_password': 'aap_controller_admin_password',
            'ocp_console_url': 'openshift_console_url',
            'openflake_username': 'openflake_admin_username',
            'openflake_password': 'openflake_admin_password',
            'gitea_url': 'gitea_console_url', 'gitea_username': 'gitea_user',
            'gitea_token': 'gitea_api_token', 'llm_url': 'litellm_api_base_url',
            'llm_api_key': 'litellm_virtual_key',
            'openflake_mcp_url': 'openflake_mcp_endpoint',
            'openflake_mcp_token': 'openflake_mcp_bearer_token',
            'lightspeed_mcp_url': 'lightspeed_mcp_endpoint',
        }
        for key in ('ao_url', 'openflake_url', 'gitea_password', 'aap_mcp_url',
                    'mattermost_url', 'mattermost_username', 'mattermost_password',
                    'splunk_url', 'splunk_username', 'splunk_password'):
            mapping[key] = key
        env_names = re.findall(r"lookup\('env', '([^']+)'", (QA / 'vars/services.yml').read_text())
        clean_env = {k: v for k, v in os.environ.items() if k not in env_names}
        for mode in ('extra-vars', 'lowercase-env', 'uppercase-override', 'explicit-override'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                env = dict(clean_env)
                extra = {'ansible_python_interpreter': os.sys.executable}
                expected = {key: aliases[source].rstrip('/') for key, source in mapping.items()}
                if mode == 'extra-vars':
                    extra.update(aliases)
                else:
                    env.update(aliases)
                if mode in ('uppercase-override', 'explicit-override'):
                    env['AAP_PASSWORD'] = 'uppercase-secret-sentinel'
                    expected['aap_password'] = env['AAP_PASSWORD']
                if mode == 'explicit-override':
                    extra['aap_password'] = 'explicit-secret-sentinel'
                    expected['aap_password'] = extra['aap_password']
                extra['expected_alias_values'] = expected
                play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                         'vars_files': [str(QA / 'vars/services.yml')],
                         'tasks': [{'assert': {'that': [
                             "lookup('vars', item.key) == item.value"]},
                             'loop': '{{ expected_alias_values | dict2items }}',
                             'no_log': True}]}]
                path = Path(directory) / 'aliases.yml'
                path.write_text(yaml.safe_dump(play))
                var_path = Path(directory) / 'inputs.yml'
                var_path.write_text(yaml.safe_dump(extra))
                result = subprocess.run(
                    ['ansible-playbook', '-i', 'localhost,', str(path), '-e', '@' + str(var_path)],
                    env=env, capture_output=True, text=True, timeout=30)
                output = result.stdout + result.stderr
                for secret in (SECRET, 'uppercase-secret-sentinel', 'explicit-secret-sentinel'):
                    self.assertNotIn(secret, output)
                self.assertEqual(result.returncode, 0, output)

    def test_service_registry_and_all_dynamic_includes(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        variables = yaml.safe_load((QA / 'vars/services.yml').read_text())
        for name, value in list(variables.items()):
            if isinstance(value, str) and "lookup('env'" in value:
                variables[name] = (base + '/mcp' if name.endswith('mcp_url') else base) if name.endswith('_url') else SECRET
        variables.update({
            'healthcheck_timeout': 2, 'ao_url': base,
            'ansible_python_interpreter': os.sys.executable,
            'ao_webhook_accounts': [
                {'name': 'solutions', 'client_id': 'client', 'client_secret': SECRET},
                {'name': 'student', 'client_id': 'client2', 'client_secret': SECRET}],
        })
        for probe in variables['healthcheck_http_probes']:
            if probe['name'] == 'Red Hat Lightspeed service account credentials':
                probe['request']['url'] = base + '/oauth'
        play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                 'vars': variables, 'tasks': [
                     {'include_tasks': str(QA / 'tasks/services.yml')},
                     {'assert': {'that': ['healthcheck_failed | length == 0',
                                          'healthcheck_passed | length > 25']}},
                 ]}]
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'services.yml'
                path.write_text(yaml.safe_dump(play))
                result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)],
                                        capture_output=True, text=True, timeout=120)
                output = result.stdout + result.stderr
                self.assertNotIn(SECRET, output)
                self.assertEqual(result.returncode, 0, output)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_real_tasks_with_mock_http_and_openshift(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        probes = [
            {"name": "authenticated", "request": {"url": base + "/identity", "headers": {"Authorization": "Bearer " + SECRET}}, "json_key": "id"},
            {"name": "bad-password", "request": {"url": base + "/unauthorized"}, "json_key": "id"},
            {"name": "html-login", "request": {"url": base + "/html"}, "json_key": "id"},
            {"name": "empty-models", "request": {"url": base + "/empty"}, "nonempty_key": "data"},
            {"name": "missing-input", "request": {"url": base + "/identity"}, "required": [""]},
            {"name": "mcp-sse", "kind": "mcp", "request": {"url": base + "/mcp"}},
            {"name": "mcp-error", "kind": "mcp", "request": {"url": base + "/mcp-error"}},
        ]
        checks = [
            {"name": "ready-nodes", "path": "/nodes", "condition": "Ready", "expected": "True"},
            {"name": "unready-nodes", "path": "/unready", "condition": "Ready", "expected": "True"},
            {"name": "completed-jobs", "path": "/completed", "condition": "Ready", "expected": "True", "pods": True},
            {"name": "empty-namespace", "path": "/no-resources", "condition": "Ready", "expected": "True", "pods": True},
        ]
        tasks = [
            {"include_tasks": str(QA / "tasks/http-probe.yml"), "loop": probes,
             "loop_control": {"loop_var": "hc_probe", "label": "{{ hc_probe.name }}"}},
            {"include_tasks": str(QA / "tasks/openshift-resource.yml"), "loop": checks,
             "loop_control": {"loop_var": "ocp_check", "label": "{{ ocp_check.name }}"}},
            {"include_tasks": str(QA / "tasks/ao-collection.yml"),
             "vars": {"hc_collection_path": "/projects", "hc_collection_register": "r_projects"}},
            {"assert": {"that": [
                "healthcheck_passed | length == 4",
                "healthcheck_failed | length == 7",
                "healthcheck_failed | select('search', 'missing-input.*not validated') | list | length == 1",
                "healthcheck_failed | select('search', 'bad-password.*HTTP status failed') | list | length == 1",
                "healthcheck_failed | select('search', 'html-login.*response validation failed') | list | length == 1",
                "r_projects.json.resources | length == 2",
                "r_projects.json.resources[1].name == 'solutions'",
            ]}},
        ]
        play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
                 "vars": {"healthcheck_passed": [], "healthcheck_failed": [],
                          "healthcheck_validate_certs": True, "healthcheck_timeout": 2,
                          "ocp_url": base, "ocp_token": SECRET,
                          "ao_api": base + "/api/v1", "ao_headers": {"Authorization": "Bearer " + SECRET},
                          "ao_validate_certs": True,
                          "ansible_python_interpreter": os.sys.executable}, "tasks": tasks}]
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "test.yml"
                path.write_text(yaml.safe_dump(play))
                result = subprocess.run(["ansible-playbook", "-i", "localhost,", str(path)],
                                        capture_output=True, text=True, timeout=120)
                output = result.stdout + result.stderr
                self.assertNotIn(SECRET, output)
                self.assertEqual(result.returncode, 0, output)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
