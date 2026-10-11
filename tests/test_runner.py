"""Behavioral tests use synthetic tools only, including detached worker processes."""
import base64
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import eda
from eda_lib import runtime
from test_qor import run as manifest_fixture

FAKE = '''import os,sys,time,subprocess
from pathlib import Path
mode=sys.argv[1]
if mode == "restore":
    assert Path("result.db").read_text() == "native checkpoint"
    print("RESTORE_OK")
    sys.exit(0)
if mode == "broken_restore":
    print("Error: unreadable checkpoint")
    sys.exit(0)
if mode == "exit":
    Path("result.rpt").write_text("diagnostic from failed run")
    sys.exit(7)
if mode == "retry" and os.environ["EDA_ATTEMPT"] == "1":
    sys.exit(9)
if mode == "retry":
    assert Path("result.db").read_text() == "native checkpoint"
if mode == "sleep":
    print("STARTED",flush=True)
    child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])
    Path("child.pid").write_text(str(child.pid))
    time.sleep(30)
if mode == "brief":
    time.sleep(0.7)
if mode == "memory":
    data=bytearray(64*1024*1024)
    time.sleep(30)
if mode not in ("stale","missing"):
    Path("result.db").write_text("native checkpoint")
    report="Total cell area: 10.0\\nslack (MET) 0.2\\n"
    if mode == "drc": report+="Total number of DRCs = 12\\n"
    if mode == "rc": report+="Warning: Zero interconnect delay\\n"
    Path("result.rpt").write_text(report)
if mode == "error": print("Error: license checkout failed")
if mode == "manifest":
    import json,hashlib
    manifest=json.loads(Path("template.json").read_text())
    manifest["evidence"][0]={"path":"result.rpt","sha256":hashlib.sha256(Path("result.rpt").read_bytes()).hexdigest()}
    if os.environ.get("CORRUPT_EVIDENCE"): manifest["evidence"][0]["sha256"]="0"*64
    Path("qor.json").write_text(json.dumps(manifest))
if mode != "marker": print("STAGE_OK",flush=True)
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='eda-test-')
        self.root = Path(self.tmp.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        (self.project / 'fake.py').write_text(FAKE)
        self.profile = {'version': 1, 'project_root': str(self.project),
                        'run_root': str(self.root / 'runs'), 'transport': {'type': 'local'},
                        'resources': {'threads_per_job': 1}}
        self.flow = {'version': 1, 'isolation': 'reviewed_run_directory', 'budget_seconds': 20,
                     'inputs': [{'source': 'fake.py', 'destination': 'fake.py'}],
                     'stages': [self.stage('first')]}

    def tearDown(self):
        root = Path(self.profile['run_root'])
        if root.exists():
            for state in root.glob('*/state.json'):
                try:
                    eda.call({'action': 'cancel', 'profile': self.profile, 'run_id': state.parent.name})
                    deadline = time.monotonic() + 5
                    while runtime.alive(json.loads(state.read_text()).get('worker')) and time.monotonic() < deadline:
                        time.sleep(0.05)
                except (ValueError, OSError):
                    pass
        self.tmp.cleanup()

    def stage(self, name, mode='ok'):
        return {'id': name, 'tool': 'command', 'argv': ['{python}', 'fake.py', mode],
                'timeout_seconds': 5, 'success_pattern': '^STAGE_OK$',
                'outputs': [{'path': 'result.db', 'kind': 'checkpoint'},
                            {'path': 'result.rpt', 'kind': 'report'}]}

    def rpc(self, action, run_id='test', **extra):
        request = dict(action=action, profile=self.profile, run_id=run_id, **extra)
        if action in ('submit', 'preflight'):
            request['flow'] = self.flow
        return eda.call(request)

    def submit(self, run_id='test'):
        value = self.rpc('submit', run_id)
        self.assertTrue(value['ok'], value)
        return value['result']

    def wait(self, run_id='test'):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            result = self.rpc('status', run_id)
            self.assertTrue(result['ok'], result)
            if result['result']['status'] not in runtime.ACTIVE:
                return result['result']
            time.sleep(0.05)
        self.fail('worker did not finish')

    def checkpoint(self, mode='restore'):
        self.flow['stages'][0]['checkpoint'] = {
            'paths': ['result.db'], 'restore_probe': {
                'argv': ['{python}', 'fake.py', mode], 'timeout_seconds': 5,
                'success_pattern': '^RESTORE_OK$'}}

    def test_success_collect_and_incremental_logs(self):
        self.assertTrue(self.rpc('preflight')['result']['ready'])
        self.submit()
        state = self.wait()
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['result_validity'], 'valid')
        self.assertFalse(state['qor_comparable'])
        first = self.rpc('logs', limit=3)['result']
        second = self.rpc('logs', offset=first['next_offset'])['result']
        self.assertEqual(first['text'] + second['text'], 'STAGE_OK\n')
        collected = self.rpc('collect')
        self.assertTrue(collected['ok'], collected)
        output = self.root / 'download'
        eda.extract_collection(collected['result'], output, 1024 * 1024)
        self.assertTrue(list(output.rglob('result.rpt')))
        self.assertFalse(list(output.rglob('result.db')))
        with self.assertRaises(ValueError):
            eda.extract_collection(collected['result'], output, 1024 * 1024)

    def test_nonzero_and_zero_exit_failures_stop_downstream(self):
        for mode in ('exit', 'error', 'missing', 'marker', 'drc', 'rc'):
            with self.subTest(mode=mode):
                self.flow['stages'] = [self.stage('first', mode), self.stage('second')]
                self.submit(mode)
                state = self.wait(mode)
                self.assertEqual(len(state['stages']), 1)
                self.assertNotEqual(state['result_validity'], 'valid')
                if mode == 'exit':
                    self.assertEqual(state['status'], 'failed')
                    self.assertEqual(state['stages'][0]['execution']['exit_code'], 7)
                    result = self.rpc('collect', mode)['result']
                    self.assertTrue(any(p['path'].endswith('result.rpt') for p in result['files']))
                else:
                    self.assertEqual(state['status'], 'completed')

    def test_stale_report_rejected(self):
        (self.project / 'result.db').write_text('native checkpoint')
        (self.project / 'result.rpt').write_text('old')
        self.flow['inputs'] += [{'source': p, 'destination': p} for p in ('result.db', 'result.rpt')]
        self.flow['stages'] = [self.stage('first', 'stale')]
        self.submit()
        state = self.wait()
        self.assertEqual(state['result_validity'], 'invalid')
        self.assertIn('output_stale: result.rpt', state['stages'][0]['validation']['reasons'])

    def test_checkpoint_resume_preserves_attempt(self):
        self.checkpoint()
        self.flow['stages'].append(self.stage('second', 'retry'))
        self.submit()
        first = self.wait()
        self.assertEqual(first['status'], 'failed')
        self.assertTrue(first['stages'][0]['checkpoint']['verified'])
        resumed = self.rpc('resume')
        self.assertTrue(resumed['ok'], resumed)
        state = self.wait()
        self.assertEqual(state['attempt'], 2)
        self.assertEqual(state['result_validity'], 'valid')
        self.assertEqual(state['stages'][0]['attempt'], 1)
        previous = Path(self.profile['run_root']) / 'test/attempts/1/state.json'
        self.assertEqual(json.loads(previous.read_text())['status'], 'failed')
        self.assertFalse(self.rpc('resume')['ok'])

    def test_failed_restore_blocks_downstream(self):
        self.checkpoint('broken_restore')
        self.flow['stages'].append(self.stage('second'))
        self.submit()
        state = self.wait()
        self.assertEqual(state['reason'], 'checkpoint_restore_failed')
        self.assertEqual(len(state['stages']), 1)

    def test_checkpoint_or_input_mutation_rejects_resume(self):
        self.checkpoint()
        self.flow['stages'].append(self.stage('second', 'exit'))
        self.submit()
        state = self.wait()
        checkpoint = Path(state['stages'][0]['checkpoint']['directory']) / 'result.db'
        checkpoint.write_text('corrupt')
        self.assertFalse(self.rpc('resume')['ok'])
        checkpoint.write_text('native checkpoint')
        (self.project / 'fake.py').write_text(FAKE + '\n# changed')
        self.assertFalse(self.rpc('resume')['ok'])

    def test_resume_without_checkpoint_and_changed_config(self):
        self.flow['stages'] = [self.stage('first', 'exit')]
        self.submit()
        self.wait()
        changed = copy.deepcopy(self.flow)
        changed['budget_seconds'] += 1
        self.assertFalse(self.rpc('resume', flow=changed)['ok'])
        self.assertTrue(self.rpc('resume')['ok'])
        self.assertEqual(self.wait()['attempt'], 2)

    def test_idempotent_submit_and_single_slot(self):
        self.flow['stages'] = [self.stage('first', 'brief')]
        first = self.submit('one')
        again = self.submit('one')
        self.assertEqual(first['worker'], again['worker'])
        self.assertTrue(again['reused'])
        self.submit('two')
        one, two = self.wait('one'), self.wait('two')
        self.assertGreaterEqual(two['started_at'], one['finished_at'])
        self.flow['budget_seconds'] += 1
        self.assertFalse(self.rpc('submit', 'one')['ok'])

    def test_cancel_and_timeout_stop_descendants(self):
        for mode in ('cancel', 'timeout', 'budget'):
            self.flow['stages'] = [self.stage('first', 'sleep')]
            self.flow['stages'][0]['timeout_seconds'] = 0.5 if mode == 'timeout' else 10
            self.flow['budget_seconds'] = 0.5 if mode == 'budget' else 20
            self.submit(mode)
            child = Path(self.profile['run_root']) / mode / 'attempts/1/work/child.pid'
            deadline = time.monotonic() + 5
            while not child.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(child.exists())
            token = runtime.identity(int(child.read_text()))
            if mode == 'cancel':
                self.assertTrue(self.rpc('cancel', mode)['result']['cancellation_requested'])
            state = self.wait(mode)
            self.assertEqual(state['status'], 'cancelled' if mode == 'cancel' else 'timed_out')
            self.assertFalse(runtime.alive(token))

    def test_ssh_disconnect_does_not_kill_submitted_worker(self):
        relay = self.root / 'fake_ssh.py'
        relay.write_text('import subprocess,sys,shlex\n'
                         'p=subprocess.run(shlex.split(sys.argv[-1]),input=sys.stdin.buffer.read(),stdout=subprocess.PIPE)\n'
                         'sys.exit(255)\n')
        self.profile['transport'] = {'type': 'ssh', 'host': 'fake-host',
                                     'ssh_command': [sys.executable, str(relay)]}
        self.flow['stages'] = [self.stage('first', 'brief')]
        with self.assertRaises(eda.TransportError):
            self.rpc('submit')
        self.profile['transport'] = {'type': 'local'}
        state = self.wait()
        self.assertEqual(state['result_validity'], 'valid')
        self.assertTrue(self.submit()['reused'])

    def test_missing_worker_reconciles_and_cancel_orphan(self):
        self.flow['stages'] = [self.stage('first', 'sleep')]
        self.submit()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.rpc('status')['result']
            if state.get('tool_process'):
                break
            time.sleep(0.05)
        os.kill(state['worker']['pid'], signal.SIGKILL)
        interrupted = self.wait()
        self.assertEqual(interrupted['status'], 'interrupted')
        self.assertTrue(interrupted['active_tool_detected'])
        self.assertFalse(self.rpc('resume')['ok'])
        self.flow['stages'] = [self.stage('first')]
        self.submit('blocked-by-orphan')
        blocked = self.wait('blocked-by-orphan')
        self.assertEqual(blocked['status'], 'failed')
        self.assertIn('Orphaned tool group', blocked['reason'])
        self.assertEqual(self.rpc('cancel')['result']['status'], 'cancelled')
        self.assertFalse(runtime.group_members(state['tool_process']))

    def test_preflight_bad_config_and_paths(self):
        self.flow['inputs'][0]['destination'] = '../outside'
        self.assertFalse(self.rpc('preflight')['ok'])
        self.flow['inputs'][0]['destination'] = 'fake.py'
        self.flow['stages'][0]['argv'][0] = '/missing/eda/tool'
        self.assertFalse(self.rpc('preflight')['result']['ready'])

    def test_collect_rejects_hash_mismatch_and_traversal(self):
        self.submit()
        self.wait()
        result = self.rpc('collect')['result']
        result['files'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            eda.extract_collection(result, self.root / 'bad', 1024 * 1024)
        self.assertFalse((self.root / 'bad').exists())
        result['files'][0]['path'] = '../outside'
        with self.assertRaises(ValueError):
            eda.extract_collection(result, self.root / 'bad', 1024 * 1024)

    def test_cancel_queued_job(self):
        self.flow['stages'] = [self.stage('first', 'sleep')]
        self.submit('one')
        self.submit('two')
        self.rpc('cancel', 'two')
        state = self.wait('two')
        self.assertEqual(state['status'], 'cancelled')
        self.assertEqual(state['stages'], [])

    def test_memory_limit_and_minimum_start_budget(self):
        self.flow['stages'] = [self.stage('first', 'memory')]
        self.profile['resources']['memory_limit_gib'] = 0.025
        self.submit('memory')
        state = self.wait('memory')
        self.assertEqual(state['reason'], 'memory_limit_exceeded')
        self.flow['stages'][0]['minimum_start_seconds'] = 30
        self.submit('budget')
        state = self.wait('budget')
        self.assertEqual(state['status'], 'timed_out')
        self.assertEqual(state['stages'], [])

    def test_manifest_and_actual_evidence_hash(self):
        (self.project / 'template.json').write_text(json.dumps(manifest_fixture()))
        self.flow['inputs'].append({'source': 'template.json', 'destination': 'template.json'})
        stage = self.stage('first', 'manifest')
        stage['outputs'].append({'path': 'qor.json', 'kind': 'artifact'})
        stage['qor_manifest'] = 'qor.json'
        self.flow['stages'] = [stage]
        self.submit('valid')
        state = self.wait('valid')
        self.assertTrue(state['qor_comparable'])
        self.assertTrue(state['pipeline_complete'])
        self.profile['env'] = {'CORRUPT_EVIDENCE': '1'}
        self.submit('invalid')
        state = self.wait('invalid')
        self.assertEqual(state['result_validity'], 'invalid')
        self.assertFalse(state['qor_comparable'])

    def test_stage_artifact_snapshot_survives_work_overwrite(self):
        self.flow['stages'].append(self.stage('second'))
        self.submit()
        self.assertEqual(self.wait()['result_validity'], 'valid')
        (Path(self.profile['run_root']) / 'test/attempts/1/work/result.db').write_text('changed after run')
        result = self.rpc('collect', checkpoints=True)
        self.assertTrue(result['ok'], result)
        snapshots = [x['path'] for x in result['result']['files'] if '/artifacts/' in x['path'] and x['path'].endswith('result.db')]
        self.assertEqual(len(snapshots), 2)

    def test_changed_captured_input_rejected(self):
        self.flow['stages'] = [self.stage('first', 'exit')]
        self.submit()
        self.wait()
        (Path(self.profile['run_root']) / 'test/inputs/fake.py').write_text('modified frozen input')
        result = self.rpc('resume')
        self.assertFalse(result['ok'])
        self.assertIn('Captured input fingerprint changed', result['error']['message'])


if __name__ == '__main__':
    unittest.main()
