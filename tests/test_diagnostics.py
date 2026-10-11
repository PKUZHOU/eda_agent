"""Counts must be complete, repeatable, and attributable to original log lines."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from eda_lib import runtime
from eda_lib.diagnostics import DiagnosticStore, message


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='eda-diagnostics-')
        self.run = Path(self.tmp.name) / 'synthetic'
        self.logs = self.run / 'attempts/1/logs'
        self.logs.mkdir(parents=True)
        self.stage = {'id': 'route', 'attempt': 1, 'status': 'completed', 'execution_done': True}
        self.store = DiagnosticStore()

    def tearDown(self):
        self.tmp.cleanup()

    def take(self, stages=None):
        stages = copy.deepcopy(stages or [self.stage])
        selected = {'stages': stages, 'diagnostic_streams': runtime.diagnostic_chunks(
                    self.run, stages, self.store.cursors())}
        self.store.update(selected)
        return selected

    def test_counts_grouping_ignore_echo_and_summary(self):
        (self.logs / 'route.log').write_text('echo "Warning: not emitted (TEST-0)"\n'
            'Warning: first cell (LIB-7)\nWarning: second cell (LIB-7)\n'
            'Error: missing input (FILE-3)\nFatal: stopped (RUN-1)\n'
            'Information: linking (LINK-1)\nDiagnostics summary: 99 warnings, 99 errors\n'
            'Total number of DRCs = 211\nUVM_ERROR : 0\n')
        result = self.take()['diagnostics']
        self.assertEqual(result['counts'], {'fatal': 1, 'error': 1, 'warning': 2, 'info': 1})
        group = next(g for g in result['groups'] if g['code'] == 'LIB-7')
        self.assertEqual(group['count'], 2)
        self.assertEqual([s['line'] for s in group['samples']], [2, 3])
        self.assertTrue(result['complete'])
        self.assertEqual(self.take()['diagnostics']['counts'], result['counts'])

    def test_partial_utf8_and_line_offset_across_append(self):
        self.stage.update(status='running', execution_done=False)
        path = self.logs / 'route.log'
        raw = 'header\nWarning: 中文消息 (TEST-7)\n'.encode()
        split = raw.index('中'.encode()) + 1
        path.write_bytes(raw[:split])
        self.assertEqual(self.take()['diagnostics']['counts']['warning'], 0)
        self.assertFalse(self.take()['diagnostics']['complete'])
        with path.open('ab') as stream: stream.write(raw[split:])
        result = self.take()['diagnostics']
        self.assertEqual(result['counts']['warning'], 1)
        sample = result['groups'][0]['samples'][0]
        self.assertEqual(sample['line'], 2)
        self.assertEqual(sample['offset'], len(b'header\n'))
        self.assertIn('中文消息', sample['text'])

    def test_unterminated_line_counted_after_tool_finishes(self):
        self.stage.update(status='running', execution_done=False)
        (self.logs / 'route.log').write_text('Warning: final message (FINAL-1)')
        self.assertEqual(self.take()['diagnostics']['counts']['warning'], 0)
        self.stage.update(status='completed', execution_done=True)
        self.assertEqual(self.take()['diagnostics']['counts']['warning'], 1)
        self.assertEqual(self.take()['diagnostics']['counts']['warning'], 1)

    def test_truncation_rotation_and_same_size_rewrite_reset_counts(self):
        path = self.logs / 'route.log'
        path.write_text('Warning: old (OLD-1)\n' * 3)
        self.assertEqual(self.take()['diagnostics']['counts']['warning'], 3)
        path.write_text('Error: new (NEW-1)\n')
        self.assertEqual(self.take()['diagnostics']['counts']['error'], 1)
        path.rename(self.logs / 'old.log')
        path.write_text('Warning: replacement (NEW-2)\n')
        self.assertEqual(self.take()['diagnostics']['counts']['warning'], 1)
        path.write_text('Warning: replacement (NEW-3)\n')
        groups = self.take()['diagnostics']['groups']
        self.assertEqual([g['code'] for g in groups], ['NEW-3'])

    def test_restore_and_inherited_stage_counts_are_separate(self):
        (self.logs / 'route.log').write_text('Warning: inherited (MAIN-1)\n')
        (self.logs / 'route.restore.log').write_text('Warning: probe (PROBE-1)\n' * 3)
        newer = self.run / 'attempts/2/logs'
        newer.mkdir(parents=True)
        (newer / 'timing.log').write_text('Error: timing (PT-1)\n')
        stages = [self.stage, dict(self.stage, id='timing', attempt=2)]
        result = self.take(stages)
        self.assertEqual(result['diagnostics']['counts']['warning'], 1)
        self.assertEqual(result['diagnostics']['counts']['error'], 1)
        self.assertEqual(result['stages'][0]['diagnostics']['restore']['counts']['warning'], 3)
        inherited = next(g for g in result['diagnostics']['groups'] if g['code'] == 'MAIN-1')
        self.assertEqual(inherited['attempt'], 1)
        self.assertEqual(inherited['log'], 'route.log')

    def test_missing_logs_stay_unknown(self):
        result = self.take()
        self.assertIsNone(result['diagnostics']['counts'])
        self.assertIsNone(result['stages'][0]['diagnostics']['main']['counts'])
        self.assertFalse(result['diagnostics']['complete'])

    def test_large_log_initial_scan_is_bounded_then_incremental(self):
        path = self.logs / 'route.log'
        path.write_bytes(b'line\n' * 450000 + b'Warning: end of log (END-1)\n')
        first = self.take()
        self.assertFalse(first['diagnostics']['complete'])
        self.assertLessEqual(first['stages'][0]['diagnostics']['main']['bytes_scanned'], 2 * 1024 * 1024)
        second = self.take()
        self.assertTrue(second['diagnostics']['complete'])
        self.assertEqual(second['diagnostics']['counts']['warning'], 1)
        self.assertEqual(second['diagnostics']['groups'][0]['samples'][0]['line'], 450001)

    def test_groups_bounded_without_losing_occurrence_totals(self):
        (self.logs / 'route.log').write_text(''.join('Warning: unique {} (CODE-{})\n'.format(i,i) for i in range(230)))
        result = self.take()
        view = result['stages'][0]['diagnostics']['main']
        self.assertEqual(view['counts']['warning'], 230)
        self.assertTrue(view['groups_truncated'])
        self.assertLessEqual(len(view['groups']), 204)

    def test_vcs_uvm_and_traceback_prefixes(self):
        self.assertEqual(message('Error-[PARSE] bad token'), ('error', 'PARSE'))
        self.assertEqual(message('UVM_WARNING file.sv(7) @ 100: [BUS] delayed'), ('warning', None))
        self.assertIsNone(message('UVM_WARNING : 0'))
        self.assertIsNone(message('  echo "Error: example"'))
        self.assertEqual(message('Traceback (most recent call last):'), ('error', 'PYTHON-TRACEBACK'))


if __name__ == '__main__':
    unittest.main()
