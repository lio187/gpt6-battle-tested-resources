import copy,tempfile,unittest
from pathlib import Path
from seo_operator.crm import Ledger,canonical_event

def event(site='primary',kind='application'):
    host='example.com' if site=='primary' else 'example.org'
    value={'event_id':site+'-'+kind,'site':site,'source':'fixture','application_id':'app-1','kind':kind,'occurred_at':'2026-09-01T10:00:00+00:00','contact':{'email':'alex@example.test','first_name':'Alex'},'attribution':{'landing_page':'https://'+host+'/start','channel':'organic'}}
    if kind in ('payment','refund'):value.update(amount_cents=15000,transaction_id='txn-'+kind)
    return value

class CRMTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Ledger(Path(self.tmp.name)/'crm.sqlite3')
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def test_duplicate_event_is_idempotent(self):
        self.assertEqual(self.store.ingest(event())['status'],'accepted');self.assertEqual(self.store.ingest(event())['status'],'duplicate')
    def test_conflicting_event_is_rejected(self):
        value=event();self.store.ingest(value);changed=copy.deepcopy(value);changed['contact']['first_name']='Changed'
        with self.assertRaises(ValueError):self.store.ingest(changed)
    def test_foreign_landing_page_is_rejected(self):
        value=event();value['attribution']['landing_page']='https://evil.example/start'
        with self.assertRaises(ValueError):canonical_event(value)
    def test_revenue_requires_payment_events(self):
        self.store.ingest(event());qualified=event(kind='qualified');qualified['occurred_at']='2026-09-02T10:00:00+00:00';self.store.ingest(qualified)
        payment=event(kind='payment');payment['occurred_at']='2026-09-03T10:00:00+00:00';self.store.ingest(payment)
        self.assertEqual(self.store.summary()['rows'][0]['revenue_cents'],15000)

if __name__=='__main__':unittest.main()
