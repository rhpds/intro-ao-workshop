"""Offline integration tests of the real Ansible task files.

Run: python3 -m unittest discover -s qa-automation/tests -v
Requires ansible-playbook on PATH and PyYAML. No live lab is contacted.
"""
import json
import os
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
