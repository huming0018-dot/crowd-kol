"""Value-node accounting matches the existing gateway. No network/database mutation."""
import hashlib,json,os,subprocess,unittest
from pathlib import Path
from cloud_sync import canonical,CloudError,_strict_json

class BudgetTests(unittest.TestCase):
    def test_object_value_node_boundaries(self):
        for count in (4999,5000,5001):
            value={str(i):0 for i in range(count-1)}
            if count<=5000:
                budget=[0,5000];canonical(value,budget=budget);self.assertEqual(budget[0],count);self.assertEqual(_strict_json(json.dumps(value)),value)
            else:
                with self.assertRaisesRegex(CloudError,'encoding_limit'):canonical(value)
                with self.assertRaisesRegex(CloudError,'encoding_limit'):_strict_json(json.dumps(value))
    def test_array_value_node_limit_is_not_raised(self):
        canonical([0]*4999)
        with self.assertRaisesRegex(CloudError,'encoding_limit'):canonical([0]*5000)
    def test_dict_depth_12_and_13(self):
        value=0
        for _ in range(12):value={'key':value}
        canonical(value);self.assertEqual(_strict_json(json.dumps(value)),value)
        with self.assertRaisesRegex(CloudError,'encoding_limit'):canonical({'outer':value})
        with self.assertRaisesRegex(CloudError,'encoding_limit'):_strict_json(json.dumps({'outer':value}))
    def test_key_unicode_and_controls_keep_validation(self):
        self.assertEqual(canonical({'😀':1,'\ue000':2,'line\n\t':'\r\\"'}),'{"line\\u000a\\u0009":"\\u000d\\\\\\\"","":2,"😀":1}')
        for value in ({'\ud800':1},{'key':'\udfff'}):
            with self.assertRaisesRegex(CloudError,'invalid_unicode'):canonical(value)
        with self.assertRaisesRegex(CloudError,'invalid_encoding'):canonical({1:'bad'})
    def test_numbers_duplicates_and_custom_limit_keep_rejection(self):
        for value in (1.5,9007199254740992,float('nan')):
            with self.assertRaisesRegex(CloudError,'integer_required'):canonical(value)
        with self.assertRaisesRegex(CloudError,'duplicate_json_key'):_strict_json('{"a":1,"a":2}')
        self.assertEqual(canonical({'a':1},budget=[0,2]),'{"a":1}')
        with self.assertRaisesRegex(CloudError,'encoding_limit'):canonical({'a':1},budget=[0,1])
    def test_existing_canonical_hash_does_not_change(self):
        value={'nested':{'😀':'原文\n\t','null':None,'bool':False},'array':[1,-0.0,'e\u0301']}
        expected='{"array":[1,0,"é"],"nested":{"bool":false,"null":null,"😀":"原文\\u000a\\u0009"}}'
        self.assertEqual(canonical(value),expected)
        self.assertEqual(hashlib.sha256(canonical(value).encode()).hexdigest(),hashlib.sha256(expected.encode()).hexdigest())
    def test_javascript_canonical_and_strict_json_same_boundaries(self):
        contract=os.environ.get('CROWD_JS_CONTRACT')
        if not contract:raise RuntimeError('CROWD_JS_CONTRACT required')
        script="""import fs from 'node:fs';import{pathToFileURL}from'node:url';import{createHash}from'node:crypto';const m=await import(pathToFileURL(process.argv[1]));const values=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(values.map(value=>{try{const a=m.canonical(value),b=m.canonical(m.strictJSON(JSON.stringify(value)));if(a!==b)throw Error('parser_mismatch');return{hash:createHash('sha256').update(a).digest('hex')};}catch(e){return{error:e.message};}})));"""
        nested=0
        for _ in range(12):nested={'key':nested}
        values=[{str(i):0 for i in range(n-1)}for n in(4999,5000,5001)]+[nested,{'outer':nested},{'😀':'\n\t','\ue000':'原文'}]
        output=json.loads(subprocess.check_output([os.environ.get('CROWD_NODE','node'),'--input-type=module','-e',script,contract],input=json.dumps(values,ensure_ascii=True).encode()))
        for value,result in zip(values,output):
            try:expected={'hash':hashlib.sha256(canonical(value).encode()).hexdigest()}
            except CloudError as e:expected={'error':str(e)}
            self.assertEqual(result,expected)

if __name__=='__main__':unittest.main()
