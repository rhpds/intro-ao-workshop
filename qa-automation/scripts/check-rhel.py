#!/usr/bin/env python3
"""Read SSH inputs from stdin; verify access node or a node reached through it.

Requires pexpect and the OpenSSH client on the runner. Passwords are supplied
only to SSH password prompts, never placed in process arguments. Downstream
connections run ssh ON the access node; the runner never connects to them.
"""
import json
import re
import shlex
import sys
import time

CHECK = "set -eu; . /etc/os-release; test \"$ID\" = rhel; id -un; printf '\\nHEALTHCHECK_RHEL_OK\\n'"


def ssh_arguments(command):
    parts = shlex.split(command)
    if not parts or parts.pop(0) not in ('ssh', '/usr/bin/ssh', '/bin/ssh'):
        raise ValueError('ssh_command must start with ssh (not a shell wrapper)')
    options, destinations = [], []
    takes_value = {'-p', '-l', '-i', '-o', '-F', '-J'}
    flags = {'-4', '-6', '-v', '-vv', '-vvv', '-q', '-C', '-A', '-a', '-t', '-tt'}
    while parts:
        part = parts.pop(0)
        if part in takes_value:
            if not parts:
                raise ValueError('Missing SSH option argument')
            options.extend([part, parts.pop(0)])
        elif part in flags:
            options.append(part)
        elif any(part.startswith(option) and len(part) > 2 for option in takes_value):
            options.append(part)
        elif part.startswith('-'):
            raise ValueError('Unsupported SSH option: ' + part)
        else:
            destinations.append(part)
    if len(destinations) != 1 or not re.fullmatch(r'[A-Za-z0-9_.:@\[\]-]+', destinations[0]):
        raise ValueError('ssh_command must contain one destination and no remote command')
    # Preserve user options, including host-key policy. New host keys are
    # accepted by default; changed host keys remain an error.
    # Allocate a remote TTY so nested SSH can read password prompts from
    # /dev/tty on the access node; a local PTY alone is not sufficient.
    return options + ['-tt', '-o', 'StrictHostKeyChecking=accept-new',
                      '-o', 'PreferredAuthentications=password,keyboard-interactive',
                      '-o', 'PubkeyAuthentication=no', '-o', 'ConnectTimeout=15', destinations[0]]


def remote_command(node):
    if not node:
        return CHECK
    if 'host' in node and not node['host']:
        raise ValueError('Missing host address for downstream node ' + str(node.get('name', '')))
    host = str(node.get('host') or node.get('name') or '')
    user = str(node.get('ssh_user') or '')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]+', host) or host.startswith('-'):
        raise ValueError('Each downstream node needs a valid name or host reachable from the access node')
    if user and (not re.fullmatch(r'[A-Za-z0-9_.-]+', user) or user.startswith('-')):
        raise ValueError('Invalid downstream ssh_user')
    port = int(node.get('ssh_port', 22))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid downstream SSH port')
    return shlex.join(['ssh', '-tt', '-o', 'StrictHostKeyChecking=accept-new',
                       '-o', 'ConnectTimeout=15', '-p', str(port),
                       (user + '@' if user else '') + host, CHECK])


def check(inputs):
    import pexpect
    password = inputs['ssh_password']
    if not password or password.startswith(('REPLACE_', 'YOUR_', '<Change Me>')):
        raise ValueError('Missing SSH password')
    args = ssh_arguments(inputs['ssh_command']) + [remote_command(inputs.get('node', {}))]
    timeout = float(inputs.get('timeout', 30))
    if timeout <= 0:
        raise ValueError('SSH timeout must be positive')
    deadline = time.monotonic() + timeout
    child = pexpect.spawn('ssh', args, encoding='utf-8', echo=False, timeout=timeout)
    output, prompts = [], 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('SSH check timed out')
            found = child.expect([r'(?i)password[^\r\n]*:', pexpect.EOF, pexpect.TIMEOUT], timeout=remaining)
            output.append(child.before)
            if found == 0:
                prompts += 1
                if prompts > 4:
                    raise ValueError('SSH authentication rejected the supplied password')
                child.sendline(password)
            elif found == 1:
                child.close()
                if child.exitstatus != 0 or 'HEALTHCHECK_RHEL_OK' not in ''.join(output):
                    raise ValueError('SSH login or RHEL identity check failed: ' + ''.join(output))
                return
            else:
                raise TimeoutError('SSH connection or authentication timed out')
    finally:
        if child.isalive():
            child.close(force=True)


if __name__ == '__main__':
    try:
        check(json.load(sys.stdin))
        print('PASS — SSH authentication and RHEL identity')
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
