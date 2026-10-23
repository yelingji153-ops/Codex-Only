"""Optional browser integration check: generated audio only, no user approvals."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from acane.library import Library
from acane.media import digest, probe
from acane.webapp import ReviewServer
from playwright.sync_api import sync_playwright, expect


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root/'界面测试：合成音频.wav'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=4',str(source)],check=True)
        with Library(root/'library') as library:
            asset = library.import_one(source)['id']
            job = uuid.uuid4().hex
            folder=library.root/'preprocessing'/job
            folder.mkdir()
            outputs=[]
            for stem,freq in [('Vocals',440),('Instrumental',660)]:
                output=folder/f'fixture_({stem}).wav'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={freq}:duration=1.5',str(output)],check=True)
                outputs.append({'path':output.relative_to(library.root).as_posix(),'sha256':digest(output),**probe(output)})
            with library.db:
                library.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?)',
                    (job,asset,'separate_preview',json.dumps({'model':'UI fixture; not model inference','preview_start_s':1}),
                     'succeeded','2026-10-23','2026-10-23',json.dumps(outputs),None))
        server=ReviewServer(root/'library')
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
                context=browser.new_context(viewport={'width':1360,'height':1000})
                page=context.new_page(); errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(server.url)
                expect(page.locator('#process-view')).to_be_visible()
                page.locator('#file-picker').set_input_files(str(source))
                expect(page.locator('#upload-status')).to_contain_text('已导入 1 份',timeout=20000)
                expect(page.locator('.asset-row')).to_have_count(1)
                page.locator('#tab-review').click()
                expect(page.locator('.queue-item')).to_have_count(2)
                expect(page.locator('#detail')).to_be_visible()
                expect(page.locator('#original')).not_to_have_js_property('readyState',0)
                expect(page.locator('#result')).not_to_have_js_property('readyState',0)
                page.evaluate("document.querySelector('#result').currentTime = .25")
                page.locator('#switch-original').click()
                expect(page.locator('#original')).to_have_js_property('paused',False)
                assert page.evaluate("document.querySelector('#result').paused")
                assert 1.2 <= page.evaluate("document.querySelector('#original').currentTime") < 2.0
                page.locator('#switch-result').click()
                expect(page.locator('#result')).to_have_js_property('paused',False)
                assert page.evaluate("document.querySelector('#original').paused")
                stale=context.new_page();stale.goto(server.url)
                stale.locator('#tab-review').click()
                expect(stale.locator('.queue-item')).to_have_count(2)
                page.locator('#approve').click()
                expect(page.locator('#notice')).to_contain_text('选择音轨类型')
                page.locator('#role').select_option('vocals')
                page.locator('#note').fill('<img src=x onerror=alert(1)> literal review note')
                page.locator('#approve').click()
                expect(page.locator('#decision-badge')).to_have_text('已通过')
                expect(page.locator('#history')).to_contain_text('<img src=x onerror=alert(1)>')
                assert page.locator('#history img').count()==0
                stale.locator('#reject').click()
                expect(stale.locator('#notice')).to_contain_text('已更新')
                page.locator('#filter').select_option('approved')
                expect(page.locator('.queue-item')).to_have_count(1)
                page.locator('#search').fill('no-match-123')
                expect(page.locator('#list-empty')).to_be_visible()
                page.locator('#search').fill('')
                page.reload()
                page.locator('#tab-review').click()
                expect(page.locator('#decision-badge')).to_have_text('已通过')
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#tab-process').click()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert not errors,errors
                browser.close()
            print('Browser checks passed: file upload and deduplication; audio decode and offset switch; review persistence; literal notes; stale tab conflict; filters; reload; both mobile views.')
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    main()
