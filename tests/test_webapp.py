import http.client
import json
import shutil
import tempfile
import threading
import unittest
import uuid
import wave
from pathlib import Path
from urllib.parse import urlencode, quote

from acane.library import Library
from acane.media import digest, probe
from acane.webapp import ReviewServer


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class WebReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root/'source.wav'
        with wave.open(str(source),'wb') as stream:
            stream.setparams((1,2,22050,0,'NONE','not compressed'))
            stream.writeframes(b'\x01\x00'*2205)
        self.library = Library(self.root/'library')
        asset = self.library.import_one(source)['id']
        self.job = uuid.uuid4().hex
        output_path = self.library.root/'preprocessing'/self.job/'vocals.wav'
        output_path.parent.mkdir()
        shutil.copyfile(source, output_path)
        self.output = {'path':output_path.relative_to(self.library.root).as_posix(),'sha256':digest(output_path),**probe(output_path)}
        with self.library.db:
            self.library.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                (self.job,asset,'separate',json.dumps({'model':'fixture'}),'succeeded','2026-10-23','2026-10-23',json.dumps([self.output]),None))
        self.server = ReviewServer(self.library.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = ''

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.library.db.close()
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        base = {'Cookie': self.cookie}
        if method == 'POST':base['Origin']=self.server.origin
        if data is not None:base['Content-Type']='application/json'
        base.update(headers or {})
        connection.request(method,path,json.dumps(data) if data is not None else None,base)
        response=connection.getresponse()
        result=(response.status,dict(response.getheaders()),response.read())
        connection.close()
        return result

    def login(self):
        status,headers,_=self.request('POST','/api/session',headers={'X-Session-Key':self.server.session_key})
        self.assertEqual(status,200)
        self.assertIn('HttpOnly',headers['Set-Cookie'])
        self.cookie=headers['Set-Cookie'].split(';')[0]

    def review_data(self):
        return {'job_id':self.job,'output_path':self.output['path'],'decision':'approved','role':'vocals',
                'note':'<script>not HTML</script>','expected_sequence':None,'expected_sha256':self.output['sha256']}

    def test_session_host_and_origin_guards(self):
        self.assertEqual(self.request('GET','/')[0],200)
        self.assertEqual(self.request('GET','/api/queue')[0],401)
        self.assertEqual(self.request('GET','/api/queue',headers={'Host':'foreign.example'})[0],403)
        self.assertEqual(self.request('POST','/api/session',headers={'X-Session-Key':'wrong'})[0],401)
        self.login()
        self.assertEqual(self.request('POST','/api/review',self.review_data(),{'Origin':'https://foreign.example'})[0],403)
        self.assertEqual(self.library.review_history(),[])

    def test_review_round_trip_and_stale_tab_conflict(self):
        self.login()
        status,_,body=self.request('GET','/api/queue')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['items'][0]['review']['decision'],'pending')
        self.assertEqual(self.request('POST','/api/review',self.review_data())[0],200)
        self.assertEqual(self.request('POST','/api/review',self.review_data())[0],409)
        route='/api/history?'+urlencode({'job':self.job,'output':self.output['path']})
        history=json.loads(self.request('GET',route)[2])['items']
        self.assertEqual(len(history),1)
        self.assertEqual(history[0]['note'],'<script>not HTML</script>')
        bad=self.review_data();bad['expected_sequence']=history[0]['sequence'];bad['expected_sha256']='0'*64
        self.assertEqual(self.request('POST','/api/review',bad)[0],409)

    def test_audio_ranges_head_and_registered_paths_only(self):
        route='/audio?'+urlencode({'job':self.job,'output':self.output['path']})
        self.assertEqual(self.request('GET',route)[0],401)
        self.login()
        expected=(self.library.root/self.output['path']).read_bytes()
        status,headers,body=self.request('GET',route,headers={'Range':'bytes=0-43'})
        self.assertEqual(status,206)
        self.assertEqual(body,expected[:44])
        self.assertEqual(headers['Content-Range'],f'bytes 0-43/{len(expected)}')
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=-10'})[2],expected[-10:])
        self.assertEqual(self.request('HEAD',route)[2],b'')
        self.assertEqual(self.request('GET',route+'&kind=original')[2],expected)
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=999999-'})[0],416)
        self.assertEqual(self.request('GET',route,headers={'Range':'bytes=0-1,3-4'})[0],416)
        self.assertEqual(self.request('GET','/audio?'+urlencode({'job':self.job,'output':'../../secret'}))[0],400)

    def test_export_requires_approval_and_creates_manifest(self):
        self.login()
        payload={'job_ids':[self.job],'sample_rate':16000,'channels':1}
        self.assertEqual(self.request('POST','/api/export',payload)[0],400)
        self.assertEqual(self.request('POST','/api/review',self.review_data())[0],200)
        status,_,body=self.request('POST','/api/export',payload)
        self.assertEqual(status,200)
        manifest=Path(json.loads(body)['manifest'])
        self.assertTrue(manifest.exists())
        self.assertEqual(json.loads(manifest.read_text())['files'][0]['export_metadata']['sample_rate'],16000)

    def test_invalid_json_fields_fail_without_record_changes(self):
        self.login()
        invalid=self.review_data();invalid['note']=['not','text']
        self.assertEqual(self.request('POST','/api/review',invalid)[0],400)
        invalid=self.review_data();del invalid['expected_sha256']
        self.assertEqual(self.request('POST','/api/review',invalid)[0],400)
        self.assertEqual(self.library.review_history(),[])

    def test_changed_audio_is_not_served(self):
        self.login()
        (self.library.root/self.output['path']).write_bytes(b'tampered')
        route='/audio?'+urlencode({'job':self.job,'output':self.output['path']})
        self.assertEqual(self.request('GET',route)[0],400)

    def test_upload_api_and_environment_gate(self):
        self.login()
        raw=(self.root/'source.wav').read_bytes()
        def upload(name):
            connection=http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
            connection.request('POST','/api/upload',raw,{'Cookie':self.cookie,'Origin':self.server.origin,
                'Content-Type':'application/octet-stream','X-File-Name':quote(name)})
            response=connection.getresponse()
            result=response.status, json.loads(response.read())
            connection.close()
            return result
        status, result=upload('弹唱.wav')
        self.assertEqual(status,200)
        self.assertEqual(result['status'],'duplicate')
        self.assertEqual(upload('../unsafe.wav')[0],400)
        self.assertEqual(upload('archive.zip')[0],400)
        self.assertEqual(self.request('POST','/api/separate',{'asset_ids':[result['id']],'force':False})[0],400)
        self.assertEqual(len(json.loads(self.request('GET','/api/workbench')[2])['assets']),1)

    def test_segment_endpoints_preserve_pending_draft_status(self):
        self.login()
        payload={'job_id':self.job,'output_path':self.output['path'],'options':{}}
        self.assertEqual(self.request('POST','/api/segment-plan',payload)[0],400)
        self.assertEqual(self.request('POST','/api/review',self.review_data())[0],200)
        status,_,body=self.request('POST','/api/segment-plan',payload)
        self.assertEqual(status,200)
        plan=json.loads(body)
        status,_,body=self.request('POST','/api/segment-render',{'plan_id':plan['id'],'intervals':[{'start_s':0,'end_s':.1}]})
        self.assertEqual(status,200)
        result=json.loads(body)
        self.assertFalse(result['training_eligible'])
        self.assertEqual(result['review_status'],'pending')
        self.assertTrue(Path(result['manifest']).is_file())
        self.assertEqual(self.request('POST','/api/segment-render',{'plan_id':'../escape','intervals':None})[0],400)
