"""Real Ansible/OpenSSL tests with a mock oc executable, never a live cluster."""
import base64
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
import yaml

QA = Path(__file__).resolve().parents[1]
NODE = 'node.test'
ADDRESS = '10.0.0.10'
MOCK_OC = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ['CSR_STATE'])
state = json.loads(path.read_text())
args = sys.argv[1:]
if 'auth' in args:
    allowed = state.get('rbac_allowed', True)
    print('yes' if allowed else 'no')
    sys.exit(0 if allowed else 1)
elif 'certificate' in args:
    index = args.index('certificate')
    assert args[index + 1] == 'approve'
    name = args[index + 2]
    state['approved'].append(name)
    csr = next(c for c in state['csrs'] if c['metadata']['name'] == name)
    csr['status'] = {'conditions': [{'type': 'Approved', 'status': 'True'}], 'certificate': 'issued'}
    path.write_text(json.dumps(state))
    print('certificatesigningrequest/' + name + ' approved')
elif 'get' in args:
    args = args[args.index('get') + 1:]
    if args[0] == 'route':
        print(json.dumps({'spec': {'host': state.get('console_host', 'console.apps.node.test')}}))
    elif args[0] == 'nodes':
        print(json.dumps({'items': state['nodes']}))
    elif args[0] == 'csr':
        if args[1] == '-o':
            print(json.dumps({'items': state['csrs']}))
        else:
            print(json.dumps(next(c for c in state['csrs'] if c['metadata']['name'] == args[1])))
    elif args[0] == '--raw':
        assert '/proxy/healthz' in args[1]
        if not state.get('health_ok', True):
            print('tls: internal error', file=sys.stderr)
            sys.exit(1)
        print('ok')
    else:
        sys.exit('unexpected get command')
else:
    sys.exit('unexpected oc command')
'''


def request(name, created, subject_node=NODE, sans=None):
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'system:nodes'),
                         x509.NameAttribute(NameOID.COMMON_NAME, 'system:node:' + subject_node)])
    csr = (x509.CertificateSigningRequestBuilder().subject_name(subject)
           .add_extension(x509.SubjectAlternativeName(sans or [x509.DNSName(NODE),
                                                              x509.IPAddress(ipaddress.ip_address(ADDRESS))]), critical=False)
           .sign(key, hashes.SHA256()))
    return {'metadata': {'name': name, 'uid': 'uid-' + name, 'creationTimestamp': created},
            'spec': {'signerName': 'kubernetes.io/kubelet-serving', 'username': 'system:node:' + NODE,
                     'groups': ['system:nodes', 'system:authenticated'],
                     'usages': ['digital signature', 'server auth'],
                     'request': base64.b64encode(csr.public_bytes(serialization.Encoding.PEM)).decode()},
            'status': {}}


@unittest.skipUnless(shutil.which('ansible-playbook') and shutil.which('openssl'), 'Ansible and OpenSSL required')
class CSRTasksTests(unittest.TestCase):
    def state(self):
        return {'nodes': [{'metadata': {'name': NODE}, 'status': {'addresses': [
            {'type': 'Hostname', 'address': NODE}, {'type': 'InternalIP', 'address': ADDRESS}]}}],
                'csrs': [], 'approved': []}

    def run_tasks(self, state, repeat=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'oc'
            binary.write_text(MOCK_OC.replace('#!/usr/bin/env python3', '#!' + os.sys.executable))
            binary.chmod(0o700)
            state_path = root / 'state.json'
            state_path.write_text(json.dumps(state))
            tasks = [{'include_tasks': str(QA / 'tasks/e2e/kubelet-csrs.yml')}]
            if repeat:
                tasks += [{'set_fact': {'first_approvals': '{{ e2e_approved_serving_csrs }}'}},
                          {'include_tasks': str(QA / 'tasks/e2e/kubelet-csrs.yml')},
                          {'assert': {'that': ["first_approvals == ['csr-new']", 'e2e_approved_serving_csrs | length == 0']}}]
            play = [{'hosts': 'localhost', 'connection': 'local', 'gather_facts': False,
                     'vars_files': [str(QA / 'vars/services.yml'), str(QA / 'vars/e2e.yml')],
                     'vars': {'e2e_workspace': {'path': str(root)}, 'healthcheck_oc_binary': str(binary),
                              'healthcheck_kubeconfig': '/mounted/lab/kubeconfig',
                              'ocp_console_url': 'https://console.apps.node.test',
                              'healthcheck_timeout': 2, 'e2e_csr_retries': 1, 'e2e_csr_poll_interval': 0,
                              'ansible_python_interpreter': os.sys.executable},
                     'environment': {'CSR_STATE': str(state_path)}, 'tasks': tasks}]
            inputs = root / 'inputs.yml'
            inputs.write_text(yaml.safe_dump(play[0].pop('vars')))
            playbook = root / 'test.yml'
            playbook.write_text(yaml.safe_dump(play))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', str(playbook), '-e', '@' + str(inputs)],
                                    capture_output=True, text=True, timeout=45)
            self.assertEqual(list(root.glob('csr-*.pem')), [], 'Temporary CSR requests must be cleaned even on failure')
            return result.returncode, result.stdout + result.stderr, json.loads(state_path.read_text())

    def test_only_latest_registered_node_serving_csr_is_approved_and_repeated_run_is_noop(self):
        state = self.state()
        old = request('csr-old', '2026-11-02T01:00:00Z')
        new = request('csr-new', '2026-11-02T02:00:00Z')
        client = request('csr-client', '2026-11-02T03:00:00Z')
        client['spec']['signerName'] = 'kubernetes.io/kube-apiserver-client-kubelet'
        unknown = request('csr-unknown', '2026-11-02T04:00:00Z')
        unknown['spec']['username'] = 'system:node:unregistered.test'
        state['csrs'] = [old, new, client, unknown]
        rc, output, after = self.run_tasks(state, repeat=True)
        self.assertEqual(rc, 0, output)
        self.assertEqual(after['approved'], ['csr-new'])
        self.assertEqual(after['csrs'][0]['status'], {})

    def test_wrong_subject_san_or_client_usage_is_never_approved(self):
        invalid = [request('csr-bad-subject', '2026-11-02T01:00:00Z', subject_node='different.test'),
                   request('csr-bad-san', '2026-11-02T01:00:00Z', sans=[x509.DNSName('attacker.example')])]
        bad_usage = request('csr-client-usage', '2026-11-02T01:00:00Z')
        bad_usage['spec']['usages'].append('client auth')
        invalid.append(bad_usage)
        for csr in invalid:
            with self.subTest(name=csr['metadata']['name']):
                state = self.state()
                state['csrs'] = [csr]
                rc, output, after = self.run_tasks(state)
                self.assertEqual(rc, 2, output)
                self.assertEqual(after['approved'], [])
                self.assertIn('Refusing', output)

    def test_namespace_only_identity_fails_with_actionable_permission_error(self):
        state = self.state()
        state['csrs'] = [request('csr-new', '2026-11-02T02:00:00Z')]
        state['rbac_allowed'] = False
        rc, output, after = self.run_tasks(state)
        self.assertEqual(rc, 2, output)
        self.assertEqual(after['approved'], [])
        self.assertIn('namespace-only', output)
        self.assertIn('healthcheck_kubeconfig', output)

    def test_wrong_cluster_kubeconfig_cannot_approve_anything(self):
        state = self.state()
        state['csrs'] = [request('csr-new', '2026-11-02T02:00:00Z')]
        state['console_host'] = 'console.other-cluster.test'
        rc, output, after = self.run_tasks(state)
        self.assertEqual(rc, 2, output)
        self.assertEqual(after['approved'], [])
        self.assertIn('does not target the provided OpenShift console', output)

    def test_invalid_signature_cannot_be_approved(self):
        state = self.state()
        csr = request('csr-new', '2026-11-02T02:00:00Z')
        parsed = x509.load_pem_x509_csr(base64.b64decode(csr['spec']['request']))
        der = bytearray(parsed.public_bytes(serialization.Encoding.DER))
        der[-1] ^= 1
        encoded = base64.b64encode(der).decode()
        pem = '-----BEGIN CERTIFICATE REQUEST-----\n' + '\n'.join(encoded[i:i + 64] for i in range(0, len(encoded), 64)) + '\n-----END CERTIFICATE REQUEST-----\n'
        csr['spec']['request'] = base64.b64encode(pem.encode()).decode()
        state['csrs'] = [csr]
        rc, output, after = self.run_tasks(state)
        self.assertEqual(rc, 2, output)
        self.assertEqual(after['approved'], [])

    def test_latest_denied_request_does_not_cause_approval_of_an_older_pending_request(self):
        state = self.state()
        denied = request('csr-denied', '2026-11-02T02:00:00Z')
        denied['status'] = {'conditions': [{'type': 'Denied', 'status': 'True'}]}
        state['csrs'] = [request('csr-old', '2026-11-02T01:00:00Z'), denied]
        rc, output, after = self.run_tasks(state)
        self.assertEqual(rc, 0, output)
        self.assertEqual(after['approved'], [])

    def test_no_pending_serving_requests_needs_no_approval(self):
        rc, output, after = self.run_tasks(self.state())
        self.assertEqual(rc, 0, output)
        self.assertEqual(after['approved'], [])

    def test_issued_certificate_does_not_hide_a_remaining_kubelet_tls_failure(self):
        state = self.state()
        state['csrs'] = [request('csr-new', '2026-11-02T02:00:00Z')]
        state['health_ok'] = False
        rc, output, after = self.run_tasks(state)
        self.assertEqual(rc, 2, output)
        self.assertEqual(after['approved'], ['csr-new'], output)
        self.assertIn('tls: internal error', output)


if __name__ == '__main__':
    unittest.main()
