"""Offline tests. Requires ansible-core, PyYAML and pexpect; no live lab access."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yaml

QA = Path(__file__).resolve().parents[1]
SECRET = 'test-secret-sentinel'
spec = importlib.util.spec_from_file_location('check_rhel', QA / 'scripts/check-rhel.py')
rhel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rhel)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = self.path.split('?')[0]
        payload = {'results': [{'id': 1}], 'login': 'lab-user', 'result': [],
                   'data': [{'id': 'model'}], 'id': 'admin', 'access_token': 'mock-token'}
        status, content_type = 200, 'application/json'
        if path == '/unauthorized':
            status, payload = 401, {'error': 'bad credentials'}
        elif path == '/html':
            payload, content_type = '<html>login</html>', 'text/html'
        elif path == '/empty':
            payload = {'data': []}
        elif path == '/mcp':
            payload = 'event: message\ndata: {"jsonrpc":"2.0","result":{"serverInfo":{"name":"mock"}}}\n\n'
            content_type = 'text/event-stream'
        elif path == '/mcp-error':
            payload = {'jsonrpc': '2.0', 'error': {'message': 'not authorized'}}
        elif path == '/en-US/account/login':
            payload = {'status': 0}
        body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        if path == '/en-US/account/login':
            self.send_header('Set-Cookie', 'session_id_8000=mock-session; Path=/')
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.do_GET()


class SSHParsingTests(unittest.TestCase):
    def test_ssh_command_and_downstream_hop(self):
        args = rhel.ssh_arguments('ssh student@bastion.example -p 30852')
        self.assertEqual(args[:2], ['-p', '30852'])
        self.assertEqual(args[-1], 'student@bastion.example')
        remote = rhel.remote_command({'name': 'node1', 'ssh_user': 'cloud-user'})
        self.assertIn('cloud-user@node1', remote)
        self.assertIn('ssh -tt', remote)
        self.assertIn('/etc/os-release', remote)
        self.assertNotIn(SECRET, remote)

    def test_reject_shell_wrappers_and_invalid_targets(self):
        for command in ('bash -c ssh', 'ssh host; touch /tmp/file', 'ssh host uptime'):
            with self.assertRaises(ValueError):
                rhel.ssh_arguments(command)
        with self.assertRaises(ValueError):
            rhel.remote_command({'name': '-oProxyCommand=bad'})


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_full_playbook_with_provisioning_inputs_and_mounted_kubeconfig(self):
        aliases = {
            'ao_url': self.base, 'ao_admin_user': 'admin', 'ao_admin_password': SECRET,
            'aap_controller_web_url': self.base, 'aap_controller_admin_user': 'admin',
            'aap_controller_admin_password': SECRET, 'openshift_console_url': self.base,
            'openflake_url': self.base, 'openflake_admin_username': 'admin',
            'openflake_admin_password': SECRET, 'gitea_console_url': self.base,
            'gitea_user': 'lab-user', 'gitea_password': SECRET, 'gitea_api_token': SECRET,
            'mattermost_url': self.base, 'mattermost_username': 'admin',
            'mattermost_password': SECRET, 'splunk_url': self.base,
            'splunk_username': 'admin', 'splunk_password': SECRET,
            'litellm_api_base_url': self.base + '/v1', 'litellm_virtual_key': SECRET,
            'openflake_mcp_endpoint': self.base + '/mcp', 'openflake_mcp_bearer_token': SECRET,
            'ssh_command': 'ssh student@bastion.example -p 30852', 'ssh_password': SECRET,
            'cnv_nodes': [{'name': f'node{n}', 'ssh_user': 'cloud-user'} for n in range(1, 4)],
        }
        for mode in ('extra-vars', 'lowercase-env', 'missing-kubeconfig', 'bad-ssh-password'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                oc = root / 'oc'
                oc.write_text('#!/usr/bin/env python3\nimport os, sys\n'
                              'from pathlib import Path\n'
                              'if not Path(os.environ["KUBECONFIG"]).is_file(): sys.exit(1)\n'
                              'print("admin" if "whoami" in sys.argv else "ok")\n')
                oc.chmod(0o700)
                ssh = root / 'ssh'
                ssh.write_text('#!/usr/bin/env python3\nimport sys\n'
                               'print("Password: ", end="", flush=True)\n'
                               f'if input() != {SECRET!r}: sys.exit(1)\n'
                               '# Nested connections may prompt for the same password.\n'
                               'if "ssh -tt" in sys.argv[-1]:\n'
                               '    print("Password: ", end="", flush=True)\n'
                               f'    if input() != {SECRET!r}: sys.exit(1)\n'
                               'print("HEALTHCHECK_RHEL_OK")\n')
                ssh.chmod(0o700)
                kubeconfig = root / 'kubeconfig'
                if mode != 'missing-kubeconfig':
                    kubeconfig.write_text('mock mounted kubeconfig')
                variables = {'ansible_python_interpreter': os.sys.executable,
                             'healthcheck_timeout': 2, 'healthcheck_ssh_timeout': 3}
                env = {key: value for key, value in os.environ.items()
                       if key not in aliases and not key.startswith(('AO_', 'AAP_', 'OCP_', 'GITEA_', 'OPENFLAKE_', 'MATTERMOST_', 'SPLUNK_', 'LLM_', 'SSH_'))}
                env.update({'PATH': str(root) + os.pathsep + env['PATH'], 'KUBECONFIG': str(kubeconfig)})
                if mode == 'lowercase-env':
                    env.update({key: json.dumps(value) if isinstance(value, list) else value
                                for key, value in aliases.items()})
                else:
                    variables.update(aliases)
                if mode == 'bad-ssh-password':
                    variables['ssh_password'] = 'bad-password'
                path = root / 'inputs.yml'
                path.write_text(yaml.safe_dump(variables))
                result = subprocess.run(['ansible-playbook', '-i', 'localhost,',
                                         str(QA / 'healthcheck.yml'), '-e', '@' + str(path)],
                                        env=env, capture_output=True, text=True, timeout=90)
                output = result.stdout + result.stderr
                if mode in ('missing-kubeconfig', 'bad-ssh-password'):
                    self.assertNotEqual(result.returncode, 0, output)
                    self.assertIn('Checks failed or not validated', output)
                else:
                    self.assertEqual(result.returncode, 0, output)
                    self.assertIn('Service availability and supplied credentials verified', output)
                self.assertNotIn('List workflows', output)
                self.assertNotIn('censored', output)

    def test_probe_failure_categories(self):
        probes = [
            {'name': 'good', 'request': {'url': self.base}, 'json_key': 'id'},
            {'name': 'bad-password', 'request': {'url': self.base + '/unauthorized'}},
            {'name': 'html-login', 'request': {'url': self.base + '/html'}, 'json_key': 'id'},
            {'name': 'empty-models', 'request': {'url': self.base + '/empty'}, 'nonempty_key': 'data'},
            {'name': 'missing-input', 'request': {'url': self.base}, 'required': ['']},
            {'name': 'mcp-sse', 'kind': 'mcp', 'request': {'url': self.base + '/mcp'}},
            {'name': 'mcp-error', 'kind': 'mcp', 'request': {'url': self.base + '/mcp-error'}},
        ]
        play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                 'vars': {'healthcheck_passed': [], 'healthcheck_failed': [],
                          'healthcheck_validate_certs': True, 'healthcheck_timeout': 2,
                          'ansible_python_interpreter': os.sys.executable},
                 'tasks': [{'include_tasks': str(QA / 'tasks/http-probe.yml'), 'loop': probes,
                            'loop_control': {'loop_var': 'hc_probe', 'label': '{{ hc_probe.name }}'}},
                           {'assert': {'that': ['healthcheck_passed | length == 2',
                                                'healthcheck_failed | length == 5',
                                                "healthcheck_failed | select('search', 'missing-input.*not validated') | list | length == 1"]}}]}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.yml'
            path.write_text(yaml.safe_dump(play))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
