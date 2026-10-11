import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qor', ROOT/'skills/eda-qor-experiments/scripts/qor.py')
qor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qor)

def run():
 return {'run_id':'baseline','status':'completed','context':{
  'design':'fixture','rtl_sha256':'a'*64,'constraints_sha256':'b'*64,
  'libraries_sha256':'c'*64,'physical_technology_sha256':'d'*64,
  'rc_method':{'type':'extracted','corner':'rcworst'},'stage':'route',
  'tool_versions':{'icc2':'fixture'},'seed':0,'time_unit':'ns','area_unit':'um2',
  'scenarios':['ss','ff']},'validity':{'constraints_checked':True,
  'coverage_checked':True,'parasitics_checked':True,'equivalence':'pass'},
  'metrics':{'cell_area':100,'drc_count':0,'open_net_count':0,'unconstrained_endpoint_count':0,
   'scenarios':{'ss':{'setup_wns':-0.2,'setup_tns':-3,'hold_wns':0.02,'hold_tns':0},
                'ff':{'setup_wns':0.1,'setup_tns':0,'hold_wns':0.01,'hold_tns':0}}},
  'evidence':[{'path':'fixture.rpt','sha256':'e'*64}]}

class TestQor(unittest.TestCase):
 def test_empty_directory_is_insufficient_evidence(self):
  with tempfile.TemporaryDirectory() as td:
   self.assertEqual(qor.audit(td)['status'],'insufficient_reports')
 def test_negative_and_zero_slack_direction(self):
  b=run();c=copy.deepcopy(b);c['run_id']='candidate'
  c['metrics']['scenarios']['ss'].update(setup_wns=0,setup_tns=0)
  result=qor.compare(b,c)
  self.assertEqual(result['relation'],'candidate_dominates')
  self.assertFalse(result['signoff_certified'])
  self.assertAlmostEqual(next(x['delta'] for x in result['deltas'] if x['metric']=='ss.setup_wns'),0.2)
 def test_hold_regression_is_not_hidden(self):
  b=run();c=copy.deepcopy(b)
  c['metrics']['scenarios']['ss']['setup_wns']=0.1
  c['metrics']['scenarios']['ff']['hold_wns']=-0.05
  self.assertEqual(qor.compare(b,c)['relation'],'tradeoff')
 def test_changed_constraints_rejected(self):
  b=run();c=copy.deepcopy(b);c['context']['constraints_sha256']='f'*64
  with self.assertRaisesRegex(ValueError,'Incomparable'):qor.compare(b,c)
 def test_missing_corner_and_nonfinite_rejected(self):
  b=run();c=copy.deepcopy(b);del c['metrics']['scenarios']['ff']
  with self.assertRaises(ValueError):qor.compare(b,c)
  c=copy.deepcopy(b);c['metrics']['cell_area']=float('nan')
  with self.assertRaises(ValueError):qor.compare(b,c)
 def test_physical_failure_prevents_eligibility(self):
  b=run();c=copy.deepcopy(b);c['metrics']['drc_count']=7
  c['validity']['parasitics_checked']=False
  self.assertFalse(qor.compare(b,c)['eligible_for_engineering_review'])
 def test_power_activity_must_match(self):
  b=run();c=copy.deepcopy(b)
  for r in (b,c):
   r['metrics']['total_power']=10
   r['context'].update(power_method='saif',activity_sha256='a'*64,power_unit='mW')
  c['context']['activity_sha256']='b'*64
  with self.assertRaisesRegex(ValueError,'Power requires'):qor.compare(b,c)
 def test_empty_filtered_report_does_not_invent_wns_or_tns(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'pt.rpt';p.write_text('Report : timing\n -max_paths 5\n -slack_lesser_than 0.00\nNo paths with slack less than 0.00.\n')
   result=qor.audit(p)
   self.assertIsNone(result['files'][0]['sampled_min_slack'])
   self.assertIsNone(result['files'][0]['tns'])
   self.assertIn('no_matching_paths_not_numeric_wns',[x['code'] for x in result['findings']])
 def test_invalid_physical_evidence_is_not_accepted(self):
  reports=ROOT/'tests/fixtures/report-observations'
  result=qor.audit(reports)
  self.assertIn('invalid_parasitic_timing_evidence',[x['code'] for x in result['findings']])
  self.assertTrue(any(x['metric']=='drc_count' and x['value']==7 for f in result['files'] for x in f['observations']))
  area=next(f for f in result['files'] if f['path'].endswith('area.rpt'))
  self.assertAlmostEqual(next(x['value'] for x in area['observations'] if x['metric']=='total_cell_area_report_units'),12.5)

if __name__=='__main__':unittest.main()
