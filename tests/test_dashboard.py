"""Monitor privacy, bounded reads, transport faults and local HTTP behavior."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import eda
from eda_lib import runtime
from eda_lib.dashboard import DashboardServer, SnapshotCache


def sample():
    return {'sampled_at': '2026-01-01T00:00:00+00:00', 'host': {'cpu_count': 4, 'available_memory_gib': 8},
            'runs': [], 'selected': {'run_id': 'synthetic', 'attempt': 1,
            'resources': {'sample_time': 10, 'cpu_seconds': 1, 'rss_bytes': 1024,
                          'process_key': 'synthetic-process', 'process_count': 1}}}


class DashboardCacheTests(unittest.TestCase):
    def test_cache_single_flight_and_cpu_sampling(self):
        count = []
        data = sample()
        def fetch(request):
            count.append(request['action'])
            self.assertEqual(request['action'], 'monitor')
            time.sleep(0.03)
            return {'ok': True, 'result': copy.deepcopy(data)}
        cache = SnapshotCache({'run_root': '/synthetic/runs'}, fetch, refresh=5)
        threads = [threading.Thread(target=cache.snapshot) for _ in range(4)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(count, ['monitor'])
        self.assertIsNone(cache.snapshot()['data']['selected']['resources']['cpu_percent'])
        cache.refresh = 0
        data['selected']['resources'].update(sample_time=12, cpu_seconds=4)
        current = cache.snapshot()['data']['selected']['resources']
        self.assertEqual(current['cpu_percent'], 150)
        data['selected']['resources'].update(sample_time=14, cpu_seconds=0.5, process_key='new-process')
        self.assertIsNone(cache.snapshot()['data']['selected']['resources']['cpu_percent'])

    def test_disconnect_retains_last_success_without_changing_run(self):
        offline = []
        def fetch(request):
            if offline: raise eda.TransportError('synthetic connection lost')
            data = sample()
            data['selected']['status'] = 'running'
            return {'ok': True, 'result': data}
        cache = SnapshotCache({'run_root': '/synthetic/runs'}, fetch, refresh=0)
        self.assertTrue(cache.snapshot()['connected'])
        offline.append(True)
        result = cache.snapshot()
        self.assertFalse(result['connected'])
        self.assertEqual(result['data']['selected']['status'], 'running')
        self.assertIsNotNone(result['last_success_at'])


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        def fetch(request):
            self.calls.append(request)
            return {'ok': True, 'result': sample()}
        self.server = DashboardServer(SnapshotCache({'run_root': '/synthetic/runs'}, fetch), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://localhost:' + str(self.server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_assets_and_snapshot(self):
        for path in ('/', '/app.js', '/style.css'):
            with self.opener.open(self.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertGreater(len(response.read()), 100)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
        with self.opener.open(self.url + '/api/snapshot?run_id=synthetic&attempt=1') as response:
            self.assertTrue(json.load(response)['connected'])
        self.assertEqual(self.calls[0]['run_id'], 'synthetic')
        self.assertEqual(self.calls[0]['attempt'], 1)

    def test_no_write_file_or_cross_origin_routes(self):
        cases = [('/api/cancel', {}, None, 404),
                 ('/api/snapshot', {}, b'{}', 405),
                 ('/../../profiles/machine.local.json', {}, None, 404),
                 ('/api/snapshot?command=cancel', {}, None, 400),
                 ('/api/snapshot?attempt=-1', {}, None, 400),
                 ('/api/snapshot', {'Origin': 'https://unrelated.example'}, None, 403),
                 ('/api/snapshot', {'Host': 'unrelated.example'}, None, 403),
                 ('/api/snapshot', {'Sec-Fetch-Site': 'cross-site'}, None, 403)]
        for path, headers, body, code in cases:
            with self.subTest(path=path, headers=headers):
                request = urllib.request.Request(self.url + path, data=body, headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.opener.open(request)
                self.assertEqual(error.exception.code, code)
        self.assertEqual(self.calls, [])


class MonitorRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='eda-monitor-test-')
        self.root = Path(self.tmp.name)
        self.run = self.root / 'sample'
        self.attempt = self.run / 'attempts/1'
        (self.attempt / 'logs').mkdir(parents=True)
        self.profile = {'run_root': str(self.root)}
        self.state = {'run_id': 'sample', 'attempt': 1, 'status': 'completed',
                      'result_validity': 'invalid', 'worker': None, 'tool_process': None,
                      'reason': 'stage_validation_blocked', 'current_stage': 'route',
                      'created_at': '2026-01-01T00:00:00+00:00', 'stages': [{
                          'id': 'route', 'index': 0, 'attempt': 1, 'execution_status': 'completed',
                          'execution': {'exit_code': 0, 'wall_seconds': 2, 'peak_group_rss_bytes': 4096},
                          'validation': {'status': 'invalid', 'reasons': ['report_finding: nonzero_drc_observed']}}]}
        runtime.atomic(self.run / 'state.json', self.state)
        runtime.atomic(self.attempt / 'state.json', self.state)
        runtime.atomic(self.run / 'request.json', {'profile': {'env': {'SECRET': 'private-profile-sentinel'}},
                       'input_identity': {'large_private_tree': 'not_for_dashboard'},
                       'flow': {'budget_seconds': 60, 'stages': [
                           {'id': 'route', 'tool': 'icc2_shell'}, {'id': 'timing', 'tool': 'pt_shell'}]}})

    def tearDown(self):
        self.tmp.cleanup()

    def snapshot(self, **values):
        return runtime.monitor_snapshot(dict(profile=self.profile, run_id='sample', **values))

    def test_invalid_stage_blocks_view_and_no_profile_leak(self):
        text = '<script>alert("synthetic")</script>\n'
        (self.attempt / 'logs/route.log').write_text(text)
        before = (self.run / 'state.json').read_bytes()
        result = self.snapshot()
        selected = result['selected']
        self.assertEqual(selected['stages'][0]['status'], 'invalid')
        self.assertEqual(selected['stages'][1]['status'], 'not_run')
        self.assertEqual(selected['log']['text'], text)
        self.assertNotIn('private-profile-sentinel', json.dumps(result))
        self.assertNotIn('large_private_tree', json.dumps(result))
        self.assertEqual(before, (self.run / 'state.json').read_bytes())
        self.state['stages'][0]['validation']['status'] = 'insufficient'
        runtime.atomic(self.run / 'state.json', self.state)
        self.assertEqual(self.snapshot()['selected']['stages'][0]['status'], 'insufficient')

    def test_tail_is_bounded_and_paths_are_allowlisted(self):
        log = self.attempt / 'logs/route.log'
        log.write_text('old line\n' * 20000 + 'LAST_LINE\n')
        result = self.snapshot()['selected']['log']
        self.assertLessEqual(len(result['text'].encode()), 65536)
        self.assertTrue(result['text'].endswith('LAST_LINE\n'))
        self.assertEqual(result['total_bytes'], log.stat().st_size)
        with self.assertRaises(runtime.RequestError): self.snapshot(log='../request.json')
        with self.assertRaises(runtime.RequestError): self.snapshot(attempt=999)
        with self.assertRaises(runtime.RequestError):
            runtime.monitor_snapshot({'profile': self.profile, 'run_id': '../sample'})

    def test_dead_worker_view_is_read_only(self):
        self.state.update(status='running', result_validity='insufficient')
        runtime.atomic(self.run / 'state.json', self.state)
        before = (self.run / 'state.json').read_bytes()
        self.assertEqual(self.snapshot()['selected']['status'], 'interrupted')
        self.assertEqual(before, (self.run / 'state.json').read_bytes())

    def test_previous_attempt_can_be_selected(self):
        self.state.update(attempt=2, status='queued')
        runtime.atomic(self.run / 'state.json', self.state)
        runtime.atomic(self.run / 'attempts/2/state.json', self.state)
        selected = self.snapshot(attempt=1)['selected']
        self.assertEqual(selected['attempt'], 1)
        self.assertEqual(selected['attempts'], [1, 2])
        self.assertEqual(selected['status'], 'completed')

    def test_empty_run_root(self):
        result = runtime.monitor_snapshot({'profile': {'run_root': str(self.root / 'missing')}})
        self.assertEqual(result['runs'], [])
        self.assertIsNone(result['selected'])

    def test_live_process_metrics_without_changing_worker_state(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'live.py').write_text('import time\nfrom pathlib import Path\n'
            'print("LIVE_START",flush=True)\nend=time.monotonic()+4\n'
            'while time.monotonic()<end: sum(range(1000))\n'
            'Path("result.rpt").write_text("Synthetic process finished")\nprint("LIVE_END")\n')
        profile = {'version': 1, 'project_root': str(project), 'run_root': str(self.root),
                   'transport': {'type': 'local'}, 'resources': {'threads_per_job': 1}}
        flow = {'version': 1, 'isolation': 'reviewed_run_directory', 'budget_seconds': 10,
                'inputs': [{'source': 'live.py', 'destination': 'live.py'}], 'stages': [{
                    'id': 'synthetic', 'argv': ['{python}', 'live.py'], 'timeout_seconds': 8,
                    'success_pattern': '^LIVE_END$', 'outputs': [{'path': 'result.rpt', 'kind': 'report'}]}]}
        result = eda.call({'action': 'submit', 'profile': profile, 'flow': flow, 'run_id': 'live'})
        self.assertTrue(result['ok'], result)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                view = runtime.monitor_snapshot({'profile': profile, 'run_id': 'live'})['selected']
                if view['resources']['process_count'] and 'LIVE_START' in view['log']['text']:
                    break
                time.sleep(0.03)
            self.assertGreater(view['resources']['rss_bytes'], 0)
            self.assertEqual(view['stages'][0]['status'], 'running')
            before = (self.root / 'live/state.json').read_bytes()
            time.sleep(0.2)
            later = runtime.monitor_snapshot({'profile': profile, 'run_id': 'live'})['selected']
            self.assertGreater(later['resources']['cpu_seconds'], view['resources']['cpu_seconds'])
            self.assertEqual(before, (self.root / 'live/state.json').read_bytes())
        finally:
            eda.call({'action': 'cancel', 'profile': profile, 'run_id': 'live'})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                state = runtime.load(self.root / 'live/state.json')
                if state['status'] not in runtime.ACTIVE: break
                time.sleep(0.05)


if __name__ == '__main__':
    unittest.main()
