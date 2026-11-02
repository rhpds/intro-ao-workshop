"""Run the real native Ansible E2E tasks against offline HTTP fixtures.

Python is used only by this mock test server, never by the E2E execution path.
"""
import base64
import copy
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
EXPORTS = QA.parent / 'automation/ansible/roles/ocp4_workload_automation_orchestrator_config/files/workflows'
NAMES = {'motd': 'Message of the Day', 'disk': 'Disk Utilization Remediation',
         'ticket': 'Ticket Enrichment Demo', 'cve': 'RHEL CVE Remediation'}
FILES = {'motd': 'message-of-the-day', 'disk': 'disk-utilization-remediation',
         'ticket': 'ticket-enrichment', 'cve': 'rhel-cve-remediation'}


def branch(definition, label):
    switch = next(n for n in definition['nodes'] if n['type'] == 'switch')
    port = next(c['port'] for c in switch['parameters']['cases'] if c['label'] == label)
    todo = [e['to'] for e in definition['edges'] if e['from'] == switch['id'] and e.get('from_port') == port]
    visited = set()
    while todo:
        node = todo.pop()
        if node in visited:
            continue
        visited.add(node)
        todo += [e['to'] for e in definition['edges'] if e['from'] == node and e.get('from_port') in (None, 'approved')]
    return visited


class Lab:
    def __init__(self):
        self.calls, self.jobs = [], {}
        self.workflows = {}
        self.execution = None
        self.execution_reads = 0
        self.pending_approval = False
        self.matching_chat = True
        self.mm_no_teams = False
        self.ticket_scenario = 'inform_only'
        self.manual_body = None
        self.schema_mode = 'json'
        self.activity_contract = False
        self.patched = False
        self.cve_host = 'node1'
        self.launch_bodies = []
        self.reject_launch = False
        self.template_name = 'Disk Utilization Simulate Alert'
        self.ask_variables_on_launch = True
        for kind, stem in FILES.items():
            definition = json.loads((EXPORTS / (stem + '.json')).read_text())
            self.workflows[kind] = {'id': kind, 'name': NAMES[kind], 'project_id': 'solutions',
                                    'current_version': 1, 'version': {'workflow_definition': definition}}

    def start(self, route='Inform Only', approval=False, failed_job=False, kind='ticket', inputs=None):
        inputs = inputs or {}
        definition = self.workflows[kind]['version']['workflow_definition']
        chosen = branch(definition, route)
        labels = next(n['parameters']['cases'] for n in definition['nodes'] if n['type'] == 'switch')
        alternatives = set().union(*(branch(definition, case['label']) for case in labels))
        selected = chosen | ({n['id'] for n in definition['nodes']} - alternatives)
        rows = []
        for node in definition['nodes']:
            row = {'node_id': node['id'], 'status': 'completed' if node['id'] in selected else 'skipped', 'output': {}}
            if node['type'] == 'aap_job_template' and node['id'] in selected:
                job_id = len(self.jobs) + 1
                name = node['parameters']['job_template_name']
                if name.startswith('${'):
                    name = f'CVE Remediation - {inputs["cve_id"]} - {inputs["host"]}' if kind == 'cve' else 'Remediation'
                self.jobs[job_id] = {'id': job_id, 'name': name, 'status': 'failed' if failed_job else 'successful', 'artifacts': {'disk_tier': {'<80%': 'ok', '80-95%': 'warn', '>95%': 'critical'}.get(route), 'total_reclaimed_mb': 500, 'volume_size_before_gb': 25, 'volume_size_after_gb': 30, 'disk_use_percent_before': 97, 'disk_use_percent_after': 80}, 'limit': inputs.get('host', '')}
                row['output'] = {'job_id': job_id}
            rows.append(row)
        self.execution = {'id': '11111111-1111-4111-8111-111111111111', 'workflow_id': kind, 'status': 'completed', 'nodes': rows}
        self.pending_approval = approval
        self.execution_reads = 0
        self.chosen = chosen


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def respond(self, data, code=200, content_type=None):
        body = (data if isinstance(data, str) else json.dumps(data)).encode()
        self.send_response(code)
        self.send_header('Content-Type', content_type or ('text/plain' if isinstance(data, str) else 'application/json'))
        if self.command == 'POST' and self.path == '/api/v4/users/login':
            self.send_header('Token', 'mock-chat-session')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        path, query, lab = parsed.path, parse_qs(parsed.query), self.server.lab
        lab.calls.append(('GET', self.path))
        if path.startswith(('/api/controller/', '/api/gateway/', '/api/flake/', '/api/inventory/', '/api/vulnerability/')):
            expected = 'Basic ' + base64.b64encode(b'admin:mock-password').decode()
            if self.headers.get('Authorization') != expected:
                self.respond({'error': 'credentials not mapped'}, 401)
                return
        if path == '/api/gateway/v1/me/':
            self.respond({'results': [{'id': 1}]})
        elif path == '/api/v1/projects':
            if 'cursor' in query:
                self.respond({'resources': [{'id': 'solutions', 'name': 'solutions'}], 'next': None})
            else:
                self.respond({'resources': [{'id': 'default', 'name': 'default'}], 'next': 'page2'})
        elif path == '/api/v1/workflows':
            self.respond({'resources': list(lab.workflows.values())})
        elif path.startswith('/api/v1/workflows/'):
            self.respond(lab.workflows[path.split('/')[-1]])
        elif path == '/api/v1/integrations':
            self.respond({'resources': [{'id': 'mcp', 'name': 'Solutions AAP MCP', 'integration_type': 'mcp_server'},
                                        {'id': 'llm', 'name': 'Solutions LLM', 'integration_type': 'llm_provider'}]})
        elif path == '/api/v1/integrations/mcp/tools':
            self.respond({'resources': [{'name': n} for n in ('job_templates_list', 'hosts_list', 'hosts_variable_data_retrieve')]})
        elif path == '/api/v1/integrations/llm/models':
            self.respond({'resources': [{'name': 'qwen3-235b'}]})
        elif path in ('/openapi.json', '/api/v1/openapi.json', '/api/openapi.json'):
            schema = {'paths': {'/api/v1/executions': {'post': {'requestBody': {'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Launch'}}}}}}},
                      'components': {'schemas': {'Launch': {'properties': {'workflow_id': {}, 'input_data': {}, 'trigger_id': {}}, 'required': ['workflow_id', 'input_data']}}}}
            if lab.schema_mode == 'all_html' or (path == '/openapi.json' and lab.schema_mode == 'html_fallback'):
                self.respond('<html>AO user interface</html>', content_type='text/html')
            elif path == '/openapi.json' and lab.schema_mode == 'malformed_fallback':
                self.respond('{broken JSON', content_type='text/plain')
            elif lab.schema_mode == 'text_json':
                self.respond(json.dumps(schema), content_type='text/plain')
            else:
                self.respond(schema)
        elif path.startswith('/api/v1/executions/'):
            if path.endswith('/activities'):
                self.respond({'resources': [
                    {'id': 'execution-activity-' + str(index), 'activity_name': row['node_id'],
                     'status': row['status'], 'output_data': row['output']}
                    for index, row in enumerate(lab.execution['nodes'])]})
                return
            lab.execution_reads += 1
            result = copy.deepcopy(lab.execution)
            if lab.pending_approval and lab.execution_reads == 1:
                result['status'] = 'paused'
                gate_ids = {n['id'] for n in lab.workflows[result['workflow_id']]['version']['workflow_definition']['nodes'] if n['type'] == 'approval'}
                for row in result['nodes']:
                    if row['node_id'] in lab.chosen:
                        row['status'] = 'pending' if row['node_id'] in gate_ids else 'not_started'
            if result['workflow_id'] == 'cve' and result['status'] == 'completed':
                lab.patched = True
            if lab.activity_contract:
                result.pop('nodes')
                result['activities'] = None
            self.respond(result)
        elif path == '/api/controller/v2/job_templates/100/':
            self.respond({'id': 100, 'name': lab.template_name,
                          'ask_variables_on_launch': lab.ask_variables_on_launch,
                          'limit': 'node1,localhost' if lab.template_name.startswith('Ticket') else 'node2,localhost'})
        elif path == '/api/controller/v2/job_templates/100/survey_spec/':
            self.respond({'spec': [
                {'variable': 'disk_fill_target', 'type': 'multiplechoice', 'choices': '50% - healthy, no remediation\n85% - warning, triggers log cleanup\n97% - critical, triggers volume expansion\n0% - reset, clear the ballast and fire nothing'},
                {'variable': 'webhook_target', 'type': 'multiplechoice', 'choices': ['student - the workflow I built', 'solutions - the pre-built workflow']},
                {'variable': 'scenario_list', 'type': 'multiselect', 'choices': ['auto_remediate', 'needs_approval', 'inform_only']} ]})
        elif path == '/api/controller/v2/job_templates/':
            lab.template_name = query['name'][0]
            self.respond({'results': [{'id': 100, 'name': query['name'][0]}]})
        elif path.startswith('/api/controller/v2/jobs/'):
            job_id = int(path.split('/jobs/')[1].split('/')[0])
            if path.endswith('/stdout/'):
                self.respond('Ticket: INC0000001\nExecution: 11111111-1111-4111-8111-111111111111\n')
            else:
                self.respond(lab.jobs[job_id])
        elif path == '/api/flake/table/incident':
            self.respond({'result': [{'sys_id': 'ticket-1', 'number': 'INC0000001', 'state': '2',
                                      'work_notes': 'Enriched for security team', 'comments': 'Please investigate'}]})
        elif path == '/api/v4/users/me/teams':
            self.respond([] if lab.mm_no_teams else [{'id': 'team', 'name': 'lab'}])
        elif path == '/api/v4/hooks/incoming/mock-hook':
            self.respond({'channel_id': 'channel', 'team_id': 'team'})
        elif path == '/api/v4/channels/channel':
            self.respond({'id': 'channel', 'name': 'town-square', 'team_id': 'team'})
        elif path == '/api/v4/teams/team/channels/name/town-square':
            self.respond({'id': 'channel'})
        elif path == '/api/inventory/v1/hosts':
            if query.get('tags') != ['insights-client/group=test-guid']:
                self.respond({'error': 'missing lab tag'}, 400)
                return
            lab.cve_host = query['display_name'][0]
            self.respond({'results': [{'id': lab.cve_host, 'display_name': lab.cve_host}]})
        elif path.startswith('/api/vulnerability/v1/systems/'):
            self.respond({'data': [] if lab.patched else [{'id': 'CVE-2026-12345'}]})
        elif path == '/api/controller/v2/inventories/':
            self.respond({'results': [{'id': 1}]})
        elif path == '/api/controller/v2/inventories/1/hosts/':
            self.respond({'results': [{'id': query['name'][0]}]})
        elif path.endswith('/variable_data/'):
            self.respond({'env': 'dev' if '/node1/' in path else 'production'})
        elif path == '/api/v1/repos/lab-user/playbooks/commits':
            self.respond([{'sha': 'after' if lab.patched else 'before'}])
        elif path.startswith('/api/v1/repos/lab-user/playbooks/contents/'):
            self.respond({'content': base64.b64encode(b'- hosts: all\n  tasks: []').decode()})
        elif path == '/api/v4/channels/channel/posts':
            posts = {'old': {'message': 'node2 critical'}}
            posts['new1'] = {'message': 'node2 healthy'}
            posts['new2'] = {'message': 'node1 critical'}
            if lab.matching_chat:
                posts['correct'] = {'message': 'node2 critical', 'props': {}}
            if lab.execution and lab.execution['workflow_id'] == 'disk' and lab.execution_reads:
                tier = next(j['artifacts']['disk_tier'] for j in lab.jobs.values() if j.get('artifacts', {}).get('disk_tier'))
                posts['disk-new'] = {'message': 'node2 ' + tier}
            if lab.patched:
                posts['cve-new'] = {'message': 'CVE-2026-12345 ' + lab.cve_host + ' remediation ' + ('dev' if lab.cve_host == 'node1' else 'production')}
            self.respond({'posts': posts})
        elif path == '/bad-pagination':
            self.respond({'results': [], 'next': 'http://example.invalid/steal'})
        else:
            self.respond({'error': 'unmocked ' + path}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        lab = self.server.lab
        lab.calls.append(('POST', self.path))
        if self.path == '/api/v1/auth/login':
            self.respond({'access_token': 'mock-session'})
        elif self.path == '/api/v1/executions':
            lab.manual_body = body
            if body['workflow_id'] == 'cve':
                prod = body['input_data']['host'] == 'node2'
                lab.start('Approval Required (Prod)' if prod else 'Auto-Patch (Dev)', approval=prod, kind='cve', inputs=body['input_data'])
                lab.execution['id'] = '22222222-2222-4222-8222-222222222222'
            self.respond({'execution_id': '22222222-2222-4222-8222-222222222222'}, 201)
        elif self.path == '/api/v4/users/login':
            self.respond({'id': 'user'})
        elif self.path == '/api/controller/v2/job_templates/100/launch/':
            expected = 'Basic ' + base64.b64encode(b'admin:mock-password').decode()
            if self.headers.get('Authorization') != expected:
                self.respond({'error': 'credentials not mapped'}, 401)
                return
            lab.launch_bodies.append(body)
            if not lab.ask_variables_on_launch and any(k in body['extra_vars'] for k in ('target_host', 'ballast_path')):
                self.respond({'error': 'non-survey overrides are not accepted'}, 400)
                return
            if 'scenario_list' in body['extra_vars'] and not isinstance(body['extra_vars']['scenario_list'], list):
                self.respond({'error': 'multiselect must be a list'}, 400)
                return
            if lab.reject_launch:
                self.respond({'variables_needed_to_start': ['survey validation rejected']}, 400)
                return
            if body['extra_vars'].get('webhook_target') not in (None, 'student - the workflow I built', 'solutions - the pre-built workflow'):
                self.respond({'variables_needed_to_start': ['full webhook target label required']}, 400)
                return
            if 'disk_fill_target' in body['extra_vars']:
                value = body['extra_vars']['disk_fill_target']
                if not isinstance(value, str) or '% - ' not in value:
                    self.respond({'variables_needed_to_start': ['full disk fill label required']}, 400)
                    return
                pct = value.split('%', 1)[0]
                if pct != '0':
                    lab.start({'50': '<80%', '85': '80-95%', '97': '>95%'}[pct], kind='disk')
            else:
                lab.start()
            lab.jobs[100] = {'id': 100, 'status': 'successful', 'name': 'Simulator'}
            self.respond({'id': 100}, 201)
        else:
            self.respond({'error': 'unexpected write'}, 400)


@unittest.skipUnless(shutil.which('ansible-playbook'), 'ansible-playbook required')
class NativeE2ETests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.lab = Lab()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def variables(self):
        return {'ao_url': self.base, 'ao_admin_user': 'admin', 'ao_admin_password': 'mock-password',
                'aap_controller_web_url': self.base, 'aap_controller_admin_user': 'admin', 'aap_controller_admin_password': 'mock-password',
                'openflake_url': self.base, 'openflake_admin_username': 'admin', 'openflake_admin_password': 'mock-password',
                'mattermost_url': self.base, 'e2e_approve_kubelet_serving_csrs': False, 'e2e_poll_interval': 1, 'e2e_timeout': 2,
                'ansible_python_interpreter': os.sys.executable}

    def run_ansible(self, tasks=None, extra=None, root=False):
        with tempfile.TemporaryDirectory() as directory:
            root_dir = Path(directory)
            variables = {**self.variables(), **(extra or {}), 'e2e_report_path': str(root_dir / 'evidence.json')}
            inputs = root_dir / 'inputs.yml'
            inputs.write_text(yaml.safe_dump(variables))
            path = QA / 'e2e.yml'
            if not root:
                play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                         'vars_files': [str(QA / 'vars/services.yml'), str(QA / 'vars/e2e.yml')],
                         'tasks': tasks}]
                path = root_dir / 'test.yml'
                path.write_text(yaml.safe_dump(play))
            # Test-only df executable: read-only local node fixture, no real
            # disk allocation or expansion can happen in the offline suite.
            binary = root_dir / 'df'
            binary.write_text('#!/bin/sh\nprintf "Filesystem 1B-blocks Used Available Use%% Mounted on\\n/dev/mock 26843545600 1000000 2000000 40%% /\\n"\n')
            binary.chmod(0o700)
            env = dict(os.environ)
            env['PATH'] = str(root_dir) + os.pathsep + env['PATH']
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(path), '-e', '@' + str(inputs)],
                                    env=env, capture_output=True, text=True, timeout=90)
            report = json.loads((root_dir / 'evidence.json').read_text()) if (root_dir / 'evidence.json').exists() else None
            return result.returncode, result.stdout + result.stderr, report

    def initial_tasks(self):
        return [{'set_fact': {'e2e_ao_api': self.base + '/api/v1', 'e2e_aap_api': self.base + '/api/controller/v2',
                              'e2e_run_id': 'offline-run', 'e2e_results': []}},
                {'include_tasks': str(QA / 'tasks/e2e/preflight.yml')}]

    def test_native_entrypoint_with_provisioned_credentials_and_paginated_projects(self):
        rc, output, report = self.run_ansible(root=True, extra={'e2e_cases': ['integrations']})
        self.assertEqual(rc, 0, output)
        self.assertEqual(report['passed'][0]['case'], 'integrations')
        self.assertTrue(any('cursor=page2' in path for _, path in self.server.lab.calls))
        self.assertNotIn('scripts/e2e.py', output)

    def test_schema_discovery_handles_html_fallback_text_json_and_malformed_json(self):
        for mode, suffix in (('html_fallback', '/api/v1/openapi.json'),
                             ('text_json', '/openapi.json'),
                             ('malformed_fallback', '/api/v1/openapi.json')):
            with self.subTest(mode=mode):
                self.server.lab = Lab()
                self.server.lab.schema_mode = mode
                tasks = self.initial_tasks() + [{'assert': {'that': [
                    "e2e_openapi_selected_url == '" + self.base + suffix + "'",
                    "e2e_input_field == 'input_data'",
                    "'workflow_id' in e2e_launch_schema.properties"]}}]
                rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['motd']})
                self.assertEqual(rc, 0, output)
                self.assertFalse(any(method == 'POST' and path.endswith(('/executions', '/launch/'))
                                     for method, path in self.server.lab.calls))

    def test_html_only_schema_endpoints_fail_with_actionable_diagnostics(self):
        self.server.lab.schema_mode = 'all_html'
        rc, output, _ = self.run_ansible(self.initial_tasks(), {'e2e_cases': ['motd'], 'e2e_allow_bundled_contract': False})
        self.assertEqual(rc, 2, output)
        self.assertIn('No valid AO OpenAPI JSON document was found', output)
        self.assertIn('text/html', output)
        self.assertIn('/api/v1/openapi.json', output)
        self.assertNotIn("has no attribute 'json'", output)
        self.assertFalse(any(method == 'POST' and path.endswith(('/executions', '/launch/'))
                             for method, path in self.server.lab.calls))

    def test_bundled_frontend_contract_uses_real_trigger_field_and_published_workflow(self):
        self.server.lab.schema_mode = 'all_html'
        tasks = self.initial_tasks() + [
            {'set_fact': {'e2e_workflow': '{{ e2e_workflows.motd }}',
                          'e2e_definition': '{{ e2e_workflows.motd.version.workflow_definition }}',
                          'e2e_inputs': {'banner_request': 'offline-test'}}},
            {'include_tasks': str(QA / 'tasks/e2e/manual-launch.yml')},
            {'assert': {'that': ["e2e_steps_path == '/executions/{execution_id}/activities'"]}}]
        rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['motd']})
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.server.lab.manual_body['trigger_node_id'], 'trigger_manual')
        self.assertTrue(self.server.lab.manual_body['use_published'])
        self.assertNotIn('trigger_id', self.server.lab.manual_body)

    def test_real_activity_name_and_output_data_contract_is_normalized(self):
        self.server.lab.schema_mode = 'all_html'
        self.server.lab.activity_contract = True
        self.server.lab.start('Inform Only')
        tasks = self.initial_tasks() + [
            {'set_fact': {'e2e_workflow': '{{ e2e_workflows.ticket }}',
                          'e2e_definition': '{{ e2e_workflows.ticket.version.workflow_definition }}',
                          'e2e_expected_route': 'Inform Only', 'e2e_expects_approval': False,
                          'e2e_execution_id': '11111111-1111-4111-8111-111111111111'}},
            {'include_tasks': str(QA / 'tasks/e2e/branch-map.yml')},
            {'include_tasks': str(QA / 'tasks/e2e/execution-validate.yml')},
            {'assert': {'that': ['e2e_jobs | length > 0',
                                "e2e_nodes | selectattr('node_id', 'equalto', 'triage_agent') | list | length == 1"]}}]
        rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['ticket_inform']})
        self.assertEqual(rc, 0, output)

    def test_failed_execution_reports_ao_error_before_reading_null_activities(self):
        self.server.lab.activity_contract = True
        self.server.lab.start('Inform Only')
        self.server.lab.execution['status'] = 'failed'
        self.server.lab.execution['error_details'] = 'motd_agent.result.content.headline: Property headline not found'
        tasks = self.initial_tasks() + [
            {'set_fact': {'e2e_workflow': '{{ e2e_workflows.ticket }}',
                          'e2e_definition': '{{ e2e_workflows.ticket.version.workflow_definition }}',
                          'e2e_expects_approval': False,
                          'e2e_execution_id': '11111111-1111-4111-8111-111111111111'}},
            {'include_tasks': str(QA / 'tasks/e2e/execution-validate.yml')}]
        rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['ticket_inform']})
        self.assertEqual(rc, 2, output)
        self.assertIn('Property headline not found', output)
        self.assertNotIn('NoneType', output)
        self.assertFalse(any('/activities' in path for method, path in self.server.lab.calls))

    def test_manual_launch_uses_deployed_schema_without_a_python_runner(self):
        tasks = self.initial_tasks() + [
            {'set_fact': {'e2e_workflow': '{{ e2e_workflows.motd }}',
                          'e2e_definition': '{{ e2e_workflows.motd.version.workflow_definition }}',
                          'e2e_inputs': {'banner_request': 'offline-test'}}},
            {'include_tasks': str(QA / 'tasks/e2e/manual-launch.yml')},
            {'assert': {'that': ["e2e_execution_id == '22222222-2222-4222-8222-222222222222'"]}}]
        rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['motd']})
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.server.lab.manual_body['input_data'], {'banner_request': 'offline-test'})
        self.assertEqual(self.server.lab.manual_body['workflow_id'], 'motd')

    def test_native_inventory_parses_ssh_command_and_proxies_internal_names(self):
        definitions = yaml.safe_load((QA / 'tasks/e2e/inventory.yml').read_text())
        # Exercise inventory declarations/facts without contacting a real SSH host.
        tasks = [task for task in definitions if any(key in task for key in ('ansible.builtin.add_host', 'ansible.builtin.set_fact'))]
        tasks += [{'assert': {'that': ["hostvars['e2e_gateway'].ansible_host == 'gateway.example'",
                                      "hostvars['e2e_gateway'].ansible_port | int == 30852",
                                      "hostvars['e2e_node1'].ansible_host == 'node1'",
                                      "hostvars['e2e_node1'].ansible_user == 'appuser'",
                                      "'ProxyCommand' in hostvars['e2e_node1'].ansible_ssh_common_args",
                                      "'gateway.example' in hostvars['e2e_node3'].ansible_ssh_common_args"]}}]
        rc, output, _ = self.run_ansible(tasks, {'ssh_command': 'ssh student@gateway.example -p 30852',
                                                'ssh_password': 'mock-password', 'e2e_password_file': '/tmp/mock-password-file',
                                                'e2e_discovered_nodes': {'results': [
                                                    {'item': name, 'rc': 0, 'stdout_lines': ['user appuser', 'hostname ' + name, 'port 22']}
                                                    for name in ('node1', 'node2', 'node3')]}})
        self.assertEqual(rc, 0, output)

    def test_native_cve_module_cross_system_evidence_and_production_gate(self):
        for case in ('cve_dev', 'cve_prod'):
            with self.subTest(case=case):
                self.server.lab = Lab()
                rc, output, report = self.run_ansible(root=True, extra={
                    'e2e_cases': [case], 'e2e_allow_patching': True,
                    'e2e_cve_id': 'CVE-2026-12345', 'guid': 'test-guid',
                    'insights_username': 'admin', 'insights_password': 'mock-password',
                    'e2e_insights_url': self.base, 'gitea_console_url': self.base,
                    'gitea_api_token': 'mock-token', 'gitea_playbook_repo': 'lab-user/playbooks',
                    'mattermost_username': 'admin', 'mattermost_password': 'mock-password'})
                self.assertEqual(rc, 0, output)
                self.assertEqual(report['passed'][0]['case'], case)
                self.assertEqual(report['passed'][0]['gitea_commit'], 'after')
                if case == 'cve_prod':
                    self.assertIn('WAIT', output)

    def test_native_disk_cases_cleanup_and_independent_volume_validation(self):
        for case in ('disk_healthy', 'disk_warning', 'disk_critical'):
            with self.subTest(case=case):
                self.server.lab = Lab()
                tasks = self.initial_tasks() + [
                    {'add_host': {'name': 'e2e_node2', 'ansible_connection': 'local', 'ansible_python_interpreter': os.sys.executable}},
                    {'include_tasks': str(QA / 'tasks/e2e/disk.yml'), 'vars': {'e2e_case': case}}]
                rc, output, _ = self.run_ansible(tasks, {'e2e_cases': [case], 'mattermost_username': 'admin',
                                                        'mattermost_password': 'mock-password'})
                self.assertEqual(rc, 2 if case == 'disk_critical' else 0, output)
                self.assertEqual(len(self.server.lab.launch_bodies), 2)
                reset = self.server.lab.launch_bodies[-1]['extra_vars']
                self.assertEqual(reset['disk_fill_target'], '0% - reset, clear the ballast and fire nothing')
                self.assertEqual(reset['webhook_target'], 'solutions - the pre-built workflow')
                self.assertIn('offline-run', reset['ballast_path'])
                if case == 'disk_critical':
                    self.assertIn('e2e_df_after.stdout_lines', output)

    def test_fixed_limit_template_uses_only_survey_vars_and_rejects_wrong_target(self):
        for host in ('node2', 'node3'):
            with self.subTest(host=host):
                self.server.lab = Lab()
                self.server.lab.ask_variables_on_launch = False
                tasks = [{'set_fact': {'e2e_aap_api': self.base + '/api/controller/v2', 'e2e_active_execution': ''}},
                         {'include_tasks': str(QA / 'tasks/e2e/aap-launch.yml'),
                          'vars': {'e2e_template_id': 100, 'e2e_extra_vars': {'disk_fill_target': '50', 'webhook_target': 'solutions',
                                                                         'target_host': host, 'ballast_path': '/var/log/messages-test'}}}]
                rc, output, _ = self.run_ansible(tasks)
                self.assertEqual(rc, 0 if host == 'node2' else 2, output)
                if host == 'node2':
                    payload = self.server.lab.launch_bodies[0]['extra_vars']
                    self.assertEqual(set(payload), {'disk_fill_target', 'webhook_target'})
                else:
                    self.assertEqual(self.server.lab.launch_bodies, [])

    def test_rejected_aap_launch_does_not_leave_active_work_markers(self):
        self.server.lab.reject_launch = True
        tasks = self.initial_tasks() + [
            {'set_fact': {'e2e_active_execution': 'unknown - simulator may have fired AO'}},
            {'block': [{'include_tasks': str(QA / 'tasks/e2e/aap-launch.yml'),
                        'vars': {'e2e_template_id': 100, 'e2e_extra_vars': {'disk_fill_target': '50', 'webhook_target': 'solutions'}}}],
             'rescue': [{'set_fact': {'e2e_test_rejected': True}}]},
            {'assert': {'that': ['e2e_test_rejected | bool', "e2e_active_aap_job == ''", "e2e_active_execution == ''"]}}]
        rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['ticket_inform']})
        self.assertEqual(rc, 0, output)
        self.assertEqual(len(self.server.lab.launch_bodies), 1)
        self.assertEqual(self.server.lab.launch_bodies[0]['extra_vars']['disk_fill_target'], '50% - healthy, no remediation')

    def test_native_ticket_inform_case_from_simulator_to_incident_update(self):
        tasks = self.initial_tasks() + [
            {'include_tasks': str(QA / 'tasks/e2e/ticket.yml'), 'vars': {'e2e_case': 'ticket_inform'}},
            {'assert': {'that': ["e2e_results[0].case == 'ticket_inform'", "e2e_results[0].incident == 'INC0000001'", "e2e_active_execution == ''"]}}]
        rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['ticket_inform']})
        self.assertEqual(rc, 0, output)
        self.assertEqual(sum(method == 'POST' and path.endswith('/launch/') for method, path in self.server.lab.calls), 1)
        self.assertEqual(self.server.lab.launch_bodies[0]['extra_vars']['scenario_list'], ['inform_only'])

    def test_real_execution_tasks_prove_human_gate_and_reject_wrong_branches_or_jobs(self):
        for route, approval, failed_job, expected_rc in [('Needs Approval', True, False, 0),
                                                        ('Auto Remediate', False, False, 2),
                                                        ('Inform Only', False, True, 2)]:
            with self.subTest(route=route, failed_job=failed_job):
                self.server.lab = Lab()
                self.server.lab.start(route, approval, failed_job)
                tasks = self.initial_tasks() + [
                    {'set_fact': {'e2e_workflow': '{{ e2e_workflows.ticket }}',
                                  'e2e_definition': '{{ e2e_workflows.ticket.version.workflow_definition }}',
                                  'e2e_expected_route': 'Needs Approval' if approval else 'Inform Only',
                                  'e2e_expects_approval': approval,
                                  'e2e_execution_id': '11111111-1111-4111-8111-111111111111'}},
                    {'include_tasks': str(QA / 'tasks/e2e/branch-map.yml')},
                    {'include_tasks': str(QA / 'tasks/e2e/execution-validate.yml')},
                ]
                rc, output, _ = self.run_ansible(tasks, {'e2e_cases': ['ticket_inform']})
                self.assertEqual(rc, expected_rc, output)
                if approval:
                    self.assertIn('WAIT', output)
                elif failed_job:
                    self.assertIn('e2e_linked_job.json.status', output)
                else:
                    self.assertIn('Execution failed, skipped a required branch node', output)
                self.assertFalse(any(method == 'POST' and 'approv' in path for method, path in self.server.lab.calls))

    def test_mattermost_admin_without_team_membership_uses_provided_webhook(self):
        self.server.lab.mm_no_teams = True
        tasks = [{'include_tasks': str(QA / 'tasks/e2e/chat-login.yml')},
                 {'assert': {'that': ["e2e_chat_channel == 'channel'"]}}]
        rc, output, _ = self.run_ansible(tasks, {'mattermost_username': 'admin',
                                                'mattermost_password': 'mock-password',
                                                'mattermost_webhook_token': 'mock-hook'})
        self.assertEqual(rc, 0, output)
        self.assertIn(('GET', '/api/v4/hooks/incoming/mock-hook'), self.server.lab.calls)
        self.assertNotIn(('GET', '/api/v4/users/me/teams'), self.server.lab.calls)

    def test_new_chat_card_must_match_every_term_on_one_post(self):
        tasks = [{'set_fact': {'e2e_chat_channel': 'channel', 'e2e_chat_headers': {}, 'e2e_chat_baseline': ['old']}},
                 {'include_tasks': str(QA / 'tasks/e2e/chat-validate.yml'), 'vars': {'e2e_chat_terms': ['node2', 'critical']}}]
        for match in (True, False):
            with self.subTest(match=match):
                self.server.lab.matching_chat = match
                rc, output, _ = self.run_ansible(tasks)
                self.assertEqual(rc, 0 if match else 2, output)

    def test_default_run_needs_no_e2e_options_and_has_no_manual_or_cve_cases(self):
        tasks = [{'assert': {'that': [
            'e2e_allow_changes | bool', 'e2e_allow_patching | bool', 'e2e_allow_disk_expand | bool',
            "e2e_cases == ['integrations', 'disk_healthy', 'disk_warning', 'ticket_auto', 'ticket_inform']"]}}]
        rc, output, _ = self.run_ansible(tasks)
        self.assertEqual(rc, 0, output)
        self.assertEqual(self.server.lab.calls, [])

    def test_consent_and_irreversible_flags_fail_before_http_requests(self):
        for extra in ({'e2e_allow_changes': False},
                      {'e2e_cases': ['disk_critical'], 'e2e_allow_disk_expand': False},
                      {'e2e_cases': ['cve_dev'], 'e2e_allow_patching': False},
                      {'e2e_cases': ['cve_dev'], 'e2e_cve_id': ''}):
            with self.subTest(extra=extra):
                self.server.lab.calls = []
                rc, output, _ = self.run_ansible(root=True, extra=extra)
                self.assertEqual(rc, 2, output)
                self.assertEqual(self.server.lab.calls, [])

    def test_cross_origin_pagination_is_rejected_before_following_it(self):
        rc, output, _ = self.run_ansible([{'include_tasks': str(QA / 'tasks/e2e/collection.yml'),
                                          'vars': {'e2e_collection_url': self.base + '/bad-pagination', 'e2e_collection_key': 'results'}}])
        self.assertEqual(rc, 2, output)
        self.assertIn('cross-origin', output)


if __name__ == '__main__':
    unittest.main()
