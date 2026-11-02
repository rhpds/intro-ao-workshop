"""Compact stdout for the service health check; enable via run-healthcheck.sh."""
from collections.abc import Mapping
import time

from ansible.plugins.callback import CallbackBase

DOCUMENTATION = r'''
name: healthcheck
type: stdout
short_description: Compact service results and a final health-check summary
version_added: "1.0"
description:
  - Prints explicit PASS/FAIL debug messages and compact failure diagnostics.
  - Does not dump successful task results, registered HTTP bodies, or include banners.
  - This is output formatting, not secret redaction. Use the default callback for raw diagnostics.
author: Mitesh Sharma
'''


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'stdout'
    CALLBACK_NAME = 'healthcheck'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started = time.monotonic()
        self.summary_seen = False

    def v2_playbook_on_play_start(self, play):
        self._display.display('Health check — service availability and credentials\n')

    def v2_runner_on_ok(self, result):
        if result._task.action not in ('debug', 'ansible.builtin.debug'):
            return
        message = result._result.get('msg')
        if isinstance(message, Mapping) and 'passed' in message and 'failed' in message:
            self.summary_seen = True
            passed, failed = message['passed'], message['failed']
            self._display.display(f'\nSummary: {len(passed)} passed, {len(failed)} failed')
            if failed:
                self._display.display('Failed / not validated:')
                for check in failed:
                    self._display.display('  - ' + str(check))
        elif isinstance(message, str) and message.startswith(('PASS', 'FAIL')):
            self._display.display(message)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        # The summary already lists all service failures; avoid repeating it
        # as the final assert's large message.
        if self.summary_seen and result._task.name == 'Require every requested service check to pass':
            return
        data = result._result
        reason = str(data.get('msg', 'Task failed'))
        if reason == 'Assertion failed' and data.get('assertion'):
            reason = 'assertion failed: ' + str(data['assertion'])
        # One line per failure, no full module payload. Raw diagnostics remain
        # available with ANSIBLE_STDOUT_CALLBACK=default (no no_log settings).
        reason = ' '.join(reason.split())
        if len(reason) > 300:
            reason = reason[:297] + '...'
        self._display.display(f'  ! {result._task.get_name()}: {reason}')

    def v2_runner_on_unreachable(self, result):
        self._display.display(f'ERROR — {result._host.get_name()}: unreachable')

    def v2_playbook_on_stats(self, stats):
        failed = any(stats.summarize(host).get('failures', 0) or
                     stats.summarize(host).get('unreachable', 0) for host in stats.processed)
        outcome = 'FAILED' if failed else 'PASSED'
        self._display.display(f'\nRESULT: {outcome} ({time.monotonic() - self.started:.1f}s)')
