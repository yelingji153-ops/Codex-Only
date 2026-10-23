"""Loopback-only review UI; no GPU or third-party Python dependency required."""

import json
import mimetypes
import os
import re
import secrets
import sqlite3
import subprocess
import tempfile
import webbrowser
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .library import EXTENSIONS, Library
from .review import ReviewConflict
from .workbench import Workbench

STATIC = Path(__file__).with_name('web')


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, root, port=0, backend_python=None):
        self.root = Path(root).resolve()
        with Library(self.root):
            pass
        self.session_key = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), ReviewHandler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.hosts = {f'127.0.0.1:{self.server_port}', f'localhost:{self.server_port}'}
        self.origins = {'http://' + host for host in self.hosts}
        self.workbench = Workbench(self.root, backend_python)

    def server_close(self):
        super().server_close()
        if hasattr(self, 'workbench'):
            self.workbench.close()

    @property
    def url(self):
        return self.origin + '/#key=' + self.session_key


class ReviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log session keys, source paths or user notes.

    def _headers(self, status, content_type, length, **headers):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name, value in headers.items():
            self.send_header(name.replace('_', '-'), value)
        self.end_headers()

    def _json(self, status, data, **headers):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self._headers(status, 'application/json; charset=utf-8', len(body), **headers)
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _authenticated(self):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            value = cookie.get('acane_session')
            return value is not None and secrets.compare_digest(value.value, self.server.session_key)
        except (ValueError, TypeError, CookieError):
            return False

    def _dispatch(self):
        if self.headers.get('Host') not in self.server.hosts:
            return self._json(403, {'error': '仅允许本机地址访问。'})
        path = urlsplit(self.path).path
        if self.command == 'POST':
            if self.headers.get('Origin') not in self.server.origins:
                return self._json(403, {'error': '请求来源不匹配，请从启动链接打开界面。'})
            if path == '/api/session':
                supplied = self.headers.get('X-Session-Key', '')
                if not secrets.compare_digest(supplied.encode('utf-8'), self.server.session_key.encode('utf-8')):
                    return self._json(401, {'error': '启动链接已失效，请使用当前终端中的链接。'})
                return self._json(200, {'ok': True}, Set_Cookie=f'acane_session={self.server.session_key}; HttpOnly; SameSite=Strict; Path=/')
        if self.command in ('GET', 'HEAD') and path in ('/', '/app.js', '/style.css'):
            name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[path]
            body = (STATIC / name).read_bytes()
            types = {'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','style.css':'text/css; charset=utf-8'}
            self._headers(200, types[name], len(body))
            if self.command != 'HEAD':
                self.wfile.write(body)
            return
        if not self._authenticated():
            return self._json(401, {'error': '请使用程序启动时显示的完整链接打开界面。'})
        if self.command == 'GET' and path == '/api/workbench':
            return self._json(200, self.server.workbench.status())
        if self.command == 'POST' and path == '/api/upload':
            return self._upload()
        if self.command == 'POST' and path in ('/api/check', '/api/prepare', '/api/separate'):
            data = self._body()
            if path == '/api/check':
                return self._json(200, self.server.workbench.check_environment())
            if path == '/api/prepare':
                return self._json(200, self.server.workbench.prepare())
            if set(data) != {'asset_ids','force'}:
                raise ValueError('处理任务字段不完整。')
            return self._json(200, self.server.workbench.enqueue(**data))
        with Library(self.server.root) as library:
            if self.command in ('GET', 'HEAD'):
                if path == '/api/queue':
                    assets = {a['id']: a for a in library.assets()}
                    records = library.review_queue()
                    for item in records:
                        item['original_duration'] = assets[item['asset_id']]['duration']
                    return self._json(200, {'items': records})
                if path == '/api/history':
                    params = parse_qs(urlsplit(self.path).query)
                    job = params.get('job', [None])[0]
                    output = params.get('output', [None])[0]
                    if not job or not output:
                        raise ValueError('缺少任务或输出。')
                    records = [r for r in library.review_history(job) if r['output_path'] == output]
                    return self._json(200, {'items': records})
                if path == '/audio':
                    return self._audio(library)
            elif self.command == 'POST':
                data = self._body()
                if path == '/api/review':
                    required = {'job_id','output_path','decision','role','note','expected_sequence','expected_sha256'}
                    if set(data) != required:
                        raise ValueError('审核请求字段不完整。')
                    for key in required - {'expected_sequence'}:
                        if not isinstance(data[key], str) or len(data[key]) > (8000 if key == 'note' else 2048):
                            raise ValueError('审核字段格式错误。')
                    if data['expected_sequence'] is not None and type(data['expected_sequence']) is not int:
                        raise ValueError('审核版本格式错误。')
                    result = library.review_output(**data)
                    return self._json(200, result)
                if path == '/api/export':
                    if set(data) != {'job_ids', 'sample_rate', 'channels'}:
                        raise ValueError('导出请求字段不完整。')
                    jobs = data['job_ids']
                    if jobs is not None and (not isinstance(jobs,list) or len(jobs)>1000
                                             or any(not isinstance(j,str) for j in jobs)):
                        raise ValueError('任务选择格式错误。')
                    return self._json(200, library.export_dataset(**data))
        self._json(404, {'error': '页面不存在。'})

    def _upload(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 1024**3:
            raise ValueError('请选择小于 1 GB 的非空音频或视频文件。')
        filename = unquote(self.headers.get('X-File-Name',''))
        suffix = Path(filename).suffix.lower()
        if (not filename or len(filename)>255 or '/' in filename or '\\' in filename
                or any(ord(c)<32 for c in filename) or suffix not in EXTENSIONS):
            raise ValueError('文件名或格式无效；请上传音频或视频，压缩包请先解压。')
        with tempfile.TemporaryDirectory(prefix='.acane-upload-', dir=self.server.root.parent) as directory:
            source = Path(directory) / ('upload' + suffix)
            remaining = length
            with source.open('wb') as stream:
                while remaining:
                    chunk = self.rfile.read(min(1024*1024,remaining))
                    if not chunk:
                        raise ValueError('文件传输中断，请重新导入。')
                    stream.write(chunk)
                    remaining -= len(chunk)
            result = self.server.workbench.import_upload(source,filename)
        self._json(200,result)

    def _body(self):
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('请求必须为 JSON。')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 65536:
            raise ValueError('请求内容为空或过长。')
        data = json.loads(self.rfile.read(length))
        if not isinstance(data,dict):
            raise ValueError('JSON 内容必须为对象。')
        return data

    def _audio(self, library):
        params = parse_qs(urlsplit(self.path).query)
        job_id, output_path = params.get('job', [''])[0], params.get('output', [''])[0]
        job, output = library._review_target(job_id, output_path)
        kind = params.get('kind', ['result'])[0]
        if kind == 'original':
            asset = library.asset(job['asset_id'])
            path = library._verified_path(asset['original_path'], asset['id'])
        elif kind == 'result':
            path = library._verified_path(output['path'], output['sha256'])
        else:
            raise ValueError('未知音轨。')
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        raw = self.headers.get('Range')
        if raw:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', raw)
            if not match or not any(match.groups()):
                return self._json(416, {'error':'不支持的音频范围。'}, Content_Range=f'bytes */{size}')
            first, last = match.groups()
            if first:
                start, end = int(first), min(int(last), size-1) if last else size-1
            else:
                start = max(0, size-int(last))
            if start >= size or end < start:
                return self._json(416, {'error':'音频范围超出文件。'}, Content_Range=f'bytes */{size}')
            status = 206
        headers = {'Accept_Ranges': 'bytes'}
        if status == 206:
            headers['Content_Range'] = f'bytes {start}-{end}/{size}'
        if params.get('download') == ['1']:
            headers['Content_Disposition'] = "attachment; filename*=UTF-8''" + quote(path.name, safe='')
        self._headers(status, mimetypes.guess_type(path.name)[0] or 'application/octet-stream', end-start+1, **headers)
        if self.command == 'HEAD':
            return
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = end-start+1
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _handle(self):
        try:
            self._dispatch()
        except ReviewConflict as exc:
            self._json(409, {'error': str(exc)})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
            if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
                return
            self._json(400, {'error': str(exc)})

    do_GET = _handle
    do_HEAD = _handle
    do_POST = _handle


def serve(root, port=8765, open_browser=True, backend_python=None):
    if not 0 <= port <= 65535:
        raise ValueError('端口必须在 0–65535 之间。')
    with ReviewServer(root, port, backend_python) as server:
        print('ACAね 人声分离工作台：' + server.url, flush=True)
        print('保留此终端窗口；按 Ctrl+C 停止。素材仅在本机提供。', flush=True)
        if open_browser:
            webbrowser.open(server.url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
