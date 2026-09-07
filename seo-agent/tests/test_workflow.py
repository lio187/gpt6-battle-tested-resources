import datetime as dt,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from seo_operator.core import Store,config,final_date,fingerprint,normalize_url
from seo_operator.google import save_day
from seo_operator.opportunities import discover
from seo_operator.content import stage,validate
from seo_operator.publish import publish,Static

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=config();self.c['_runtime']=self.tmp.name
        self.db=Store(Path(self.tmp.name)/'test.sqlite3');self.end=final_date()
    def tearDown(self):self.db.db.close();self.tmp.cleanup()
    def row(self,imp=100,pos=8):
        return {'keys':['automation workflow','https://example.com/automation','nld','mobile'],'clicks':2,'impressions':imp,'position':pos}
    def doc(self):
        body='## Start with one process\n\n'+('Choose a bounded recurring task with clear inputs and outputs. Document human review, ownership, expected results and failure handling before expanding the workflow. '*4)+'\n\nRead the [automation overview](https://example.com/automation) and [contact us](https://example.com/contact).'
        d={'site':'primary','title':'Choose an automation workflow','slug':'choose-automation-workflow','excerpt':'A bounded framework for selecting and reviewing an automation workflow.','body':body,'language':'en','category':'automation','publishedAt':'2027-01-15T09:00:00+00:00','query':'choose automation workflow','intent':'informational','original_contribution':'A bounded decision framework.','cta':'/contact','sources':[],'claims':[]}
        d['review']={'content_hash':fingerprint(d),'factual_support':True,'original_value':True,'intent_match':True,'brand_accuracy':True,'comparison_fairness':True,'rationale':'Fixture reviewed for structure and unsupported claims.'};return d
    def test_weighted_opportunity_and_idempotency(self):
        for offset in range(28):save_day(self.db,'primary',(self.end-dt.timedelta(days=offset)).isoformat(),[self.row()] if offset==0 else [])
        discover(self.c,self.db);discover(self.c,self.db)
        self.assertEqual(len(self.db.rows('SELECT * FROM opportunities')),1)
    def test_review_is_revision_bound(self):
        doc=self.doc();self.assertTrue(validate(self.c,self.db,doc)['passed'])
        doc['body']+=' changed';self.assertFalse(validate(self.c,self.db,doc)['passed'])
    def test_publish_is_disabled_before_remote_mutation(self):
        row=stage(self.c,self.db,self.doc())
        with patch('seo_operator.publish.validate',return_value={'passed':True}):
            result=publish(self.c,self.db,row['id'],lambda _:self.fail('No connection allowed'))
        self.assertEqual(result['state'],'pending-setup')
    def test_static_package_uses_configuration(self):
        doc=self.doc();doc['site']='academy';doc['cta']='/course';doc['body']=doc['body'].replace('example.com/contact','example.org/course').replace('example.com/automation','example.org/automation');doc['review']['content_hash']=fingerprint({k:v for k,v in doc.items() if k!='review'})
        site=self.c['sites']['academy'];site['publisher']='static';p=Static(self.c,site).package(doc,'fixture')
        text=(p/'guides/choose-automation-workflow/index.html').read_text();self.assertIn('<html lang="en">',text);self.assertIn('Example Organization',text)
    def test_case_sensitive_paths_are_preserved(self):
        self.assertNotEqual(normalize_url('https://EXAMPLE.com/Guide'),normalize_url('https://example.com/guide'))

if __name__=='__main__':unittest.main()
