import unittest
from types import SimpleNamespace
from midprojectrag.evo_harness.runtime_replay import replay_record,summarize

class RuntimeReplayTests(unittest.TestCase):
    def test_record_drops_answer_and_gold_quality(self):
        case=SimpleNamespace(case_id='c1',lane='core40',source_sha256='a'*64)
        before={'result':{'status':'budget_exhausted','code':'policy_context_budget_exceeded'}}
        result={'status':'answered','code':None,'response':{'answer':'secret','citations':['S1']},
                'usage':{'policy_calls':3,'invalid_actions':0},
                'actions':[{'tool':'search','outcome':'completed','observation':{'candidates':[{'excerpt':'secret'}]}}]}
        row=replay_record(case,before,result,1.5)
        self.assertEqual(row['selection']['code'],'policy_context_budget_exceeded')
        self.assertEqual(row['after']['status'],'answered')
        self.assertNotIn('response',row['after']); self.assertNotIn('answer',row['after'])
        self.assertEqual(row['semantic_answer_quality'],'not_evaluated')

    def test_summary_reports_terminal_delta_only(self):
        rows=[{'selection':{'code':'policy_context_budget_exceeded'},'after':{'status':'answered','code':None,'usage':{'policy_calls':3}}},
              {'selection':{'code':'policy_attempt_budget_exhausted'},'after':{'status':'budget_exhausted','code':'policy_attempt_budget_exhausted','usage':{'policy_calls':12}}}]
        out=summarize(rows,source_pre_candidate='a'*40,source_records_sha256='b'*64,
                      repaired_candidate='c'*40,repaired_runner_commit='e'*40,source_suite_sha256='d'*64)
        self.assertEqual(out['selected_count'],2)
        self.assertEqual(out['repaired_candidate_commit'],'c'*40)
        self.assertEqual(out['repaired_runner_commit'],'e'*40)
        self.assertEqual(out['after_status_counts'],{'answered':1,'budget_exhausted':1})
        self.assertEqual(out['usage']['policy_calls'],15)
        self.assertEqual(out['semantic_answer_quality'],'not_evaluated')

if __name__=='__main__': unittest.main()
