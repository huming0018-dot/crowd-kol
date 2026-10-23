import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('media',Path(__file__).with_name('media.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def addresses(ip):return lambda *args,**kwargs:[(None,None,None,None,(ip,443))]

class MediaTests(unittest.TestCase):
    def test_url_boundary(self):
        for url in ['http://a.xhscdn.com/x','https://a.xhscdn.com.evil/x','https://u:p@a.xhscdn.com/x','https://a.xhscdn.com:444/x','https://127.0.0.1/x']:
            with self.assertRaises(ValueError):m.validate_url(url,addresses('8.8.8.8'))
        for ip in ['127.0.0.1','169.254.169.254','10.0.0.1','::1','fc00::1']:
            with self.assertRaises(ValueError):m.validate_url('https://a.xhscdn.com/x',addresses(ip))
        value,ips=m.validate_url('https://a.xhscdn.com/a?locator=local',addresses('8.8.8.8'))
        self.assertEqual(ips,['8.8.8.8']);self.assertEqual(value.hostname,'a.xhscdn.com')
    def test_download_bytes_and_redaction(self):
        class Response:
            status=200
            def __init__(self):self.body=b'fixture'
            def getheader(self,name,default=None):return {'Content-Type':'image/png','Content-Length':'7'}.get(name,default)
            def read1(self,size):b=self.body;self.body=b'';return b
        class Connection:
            def __init__(self,*args):pass
            def request(self,*args,**kwargs):self.headers=kwargs['headers'];assert 'Cookie' not in self.headers and 'Authorization' not in self.headers
            def getresponse(self):return Response()
            def close(self):pass
        with tempfile.TemporaryDirectory() as d,patch.object(m,'PinnedHTTPS',Connection),patch.object(m,'validate_url',lambda url:(m.urlsplit(url),['8.8.8.8'])):
            result=m.download('https://a.xhscdn.com/image?secret=locator',Path(d))
            self.assertEqual(result['bytes'],7);self.assertNotIn('locator',json.dumps(result));self.assertEqual((Path(d)/result['file']).read_bytes(),b'fixture')
            with self.assertRaises(FileExistsError):m.download('https://a.xhscdn.com/image',Path(d))
            self.assertEqual(len(list(Path(d).iterdir())),1)
            with patch.object(m,'MAX_BYTES',2),self.assertRaises(ValueError):m.download('https://a.xhscdn.com/image',Path(d))
            self.assertEqual(len(list(Path(d).iterdir())),1)
    def test_private_redirect_rejected(self):
        class Response:
            status=302
            def getheader(self,name,default=None):return 'http://127.0.0.1/private' if name=='Location' else default
        class Connection:
            def __init__(self,*args):pass
            def request(self,*args,**kwargs):pass
            def getresponse(self):return Response()
            def close(self):pass
        original=m.validate_url
        with tempfile.TemporaryDirectory() as d,patch.object(m,'PinnedHTTPS',Connection),patch.object(m,'validate_url',lambda url:original(url,addresses('8.8.8.8'))):
            with self.assertRaises(ValueError):m.download('https://a.xhscdn.com/image',Path(d))
            self.assertEqual(list(Path(d).iterdir()),[])

if __name__=='__main__':unittest.main()
