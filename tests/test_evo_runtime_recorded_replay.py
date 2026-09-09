import unittest
from midprojectrag.evo_harness.runtime import synthetic_tools
from midprojectrag.evo_harness.runtime_recorded_replay import RecordedRetriever,recorded_search_batches
from midprojectrag.evo_harness.state import HarnessError
from midprojectrag.runtime_integrity import ResolvedScope
class RecordedReplayTests(unittest.TestCase):
    def setUp(self):
        self.tools=synthetic_tools();self.store=self.tools.store;self.ev=list(self.store.evidence)[0]
    def row(self):
        e=self.ev
        return {'doc_id':e.doc_id,'kind':e.kind,'excerpt':e.text[:280],'id':'cand:e1'}
    def test_maps_recorded_candidate_uniquely(self):
        before={'result':{'actions':[{'tool':'search','outcome':'completed','observation':{'duplicate':False,'candidates':[self.row()]}}]}}
        self.assertEqual(recorded_search_batches(before,self.store),[[(self.ev.evidence_id,self.ev.doc_id)]])
    def test_duplicate_search_does_not_consume_recorded_batch(self):
        before={'result':{'actions':[{'tool':'search','outcome':'completed','observation':{'duplicate':True,'candidates':[self.row()]}}]}}
        self.assertEqual(recorded_search_batches(before,self.store),[])
    def test_retriever_scope_and_exhaustion(self):
        other=list(self.store.evidence)[1]
        r=RecordedRetriever(self.store,[[(self.ev.evidence_id,self.ev.doc_id),(other.evidence_id,other.doc_id)]])
        scope=ResolvedScope.from_allowed(frozenset({self.ev.doc_id}),origin='combined')
        out=r.search('ignored',dense_k=10,lexical_k=10,scope=scope)
        self.assertEqual([c.evidence_id for c in out.candidates],[self.ev.evidence_id]);self.assertEqual(r.used,1)
        again=r.search('ignored',dense_k=10,lexical_k=10,scope=scope)
        self.assertEqual([c.evidence_id for c in again.candidates],[self.ev.evidence_id]);self.assertEqual(r.reused,1)
        empty=RecordedRetriever(self.store,[])
        with self.assertRaisesRegex(HarnessError,'recorded_retrieval_exhausted'):
            empty.search('ignored',dense_k=10,lexical_k=10,scope=scope)
if __name__=='__main__':unittest.main()
