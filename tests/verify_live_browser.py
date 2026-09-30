"""Exercise progressive reading through a real loopback server and Chromium."""
import copy
import json
from pathlib import Path
import platform
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from make_sample import make_sample
import live_reader
import paper_reader
import workflow
from verify_reader import verify as verify_offline


def verify(directory):
    from playwright.sync_api import sync_playwright
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    make_sample(directory)
    work = directory / 'sample.work'
    annotations = paper_reader.read_json(work / 'annotations.json')
    fragments = work / 'fragments'
    worklist_path = work / 'worklist.json'
    chunks = [{'id': name, 'owned_tokens': [t for s in sentences for t in s['tokens']], 'context_tokens': []}
              for name, sentences in [('first', annotations['sentences'][:3]), ('second', annotations['sentences'][3:])]]
    worklist = workflow.make_worklist(work, {'chunks': chunks})
    document = live_reader.LiveDocument(work, worklist_path, fragments)
    server = live_reader.make_server(document)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    port = server.server_port
    url = f'http://127.0.0.1:{port}/'
    timings, checks, errors, remote = {}, [], [], []

    def publish(chunk, ids, correction=None):
        part = copy.deepcopy(annotations)
        part['sentences'] = [s for s in part['sentences'] if s['id'] in ids]
        refs = {p['ref'] for s in part['sentences'] for p in s['natural'] if p['type'] == 'math'}
        part['math'] = {key: value for key, value in part['math'].items() if key in refs}
        owned = next(c for c in worklist['chunks'] if c['id'] == chunk)
        part['_chunk'] = {'chunk_id': chunk, 'worklist_sha256': workflow.worklist_hash(worklist),
                          'owned_tokens': owned['owned_tokens'], 'context_tokens': []}
        part['review']['coverage'] = len(workflow.assignments(part)) == len(owned['owned_tokens'])
        if correction:
            correction(part)
        path = directory / (chunk + '-draft.json')
        paper_reader.write_json(path, part)
        return live_reader.publish(work, worklist_path, fragments, chunk, path)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1180, 'height': 900})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: remote.append(request.url)
                    if request.url.startswith(('http:', 'https:', 'ws:', 'wss:')) and not request.url.startswith(url) else None)
            initial = time.monotonic()
            page.goto(url)
            page.wait_for_function('() => document.querySelector(".page-image").naturalWidth > 0')
            timings['initial_original_reader_seconds'] = time.monotonic() - initial
            assert page.locator('.source-word').count() == 22
            assert '준비된 문장 0' in page.locator('#live-status').inner_text()
            first = annotations['sentences'][0]['tokens'][0]
            selector = lambda token: '.source-word[data-token=' + json.dumps(token) + ']'
            page.locator(selector(first)).click()
            assert '번역 준비 중' in page.locator('#sentence-popup').inner_text()
            page.locator('#sentence-popup .english-word').first.click()
            assert '번역 준비 중' in page.locator('#word-popup').inner_text()
            position = page.evaluate('''() => ({scroll:scrollY, zoom:document.querySelector('#zoom-label').textContent,
                parent:[document.querySelector('#sentence-popup').style.left,document.querySelector('#sentence-popup').style.top],
                child:[document.querySelector('#word-popup').style.left,document.querySelector('#word-popup').style.top]})''')
            page.evaluate('window.originalPageImage = document.querySelector(".page-image")')
            checks.append('original reader and pending word popup before worklist/authoring')
            paper_reader.write_json(worklist_path, worklist)
            publish('first', ['s0'])
            approved = time.monotonic()
            page.wait_for_function('() => document.querySelector("#sentence-popup .korean").textContent.includes("모형은")', timeout=2000)
            timings['first_sentence_display_seconds'] = time.monotonic() - approved
            assert '기본 뜻' in page.locator('#word-popup').inner_text()
            after = page.evaluate('''() => ({scroll:scrollY, zoom:document.querySelector('#zoom-label').textContent,
                parent:[document.querySelector('#sentence-popup').style.left,document.querySelector('#sentence-popup').style.top],
                child:[document.querySelector('#word-popup').style.left,document.querySelector('#word-popup').style.top]})''')
            assert after == position, (after, position)
            assert page.evaluate('window.originalPageImage === document.querySelector(".page-image")')
            assert page.locator('#sentence-popup .revision-notice').count() == 0
            assert page.locator('#toc-toggle').is_visible(), 'Published TOC must become available in the live reader'
            checks.append('open sentence and word popups fill without refresh or position changes')

            def correction(part):
                part['sentences'][0]['natural'][0]['text'] = '모형은 시스템을 설명한다.'
                part['sentences'][0]['words'][first]['meaning'] = '시스템을 표현하는 모형들'
            publish('first', ['s0'], correction)
            page.wait_for_function('() => document.querySelector("#sentence-popup .korean").textContent.includes("설명한다")', timeout=2000)
            assert '내용 수정됨' in page.locator('#sentence-popup').inner_text()
            assert '시스템을 표현하는 모형들' in page.locator('#word-popup').inner_text()
            checks.append('correction updates current sentence and nested card with notice')

            page.keyboard.press('Escape')
            page.keyboard.press('Escape')
            second_end = annotations['sentences'][1]['tokens'][-1]
            a, b = page.locator(selector(first)).bounding_box(), page.locator(selector(second_end)).bounding_box()
            page.mouse.move(a['x'] + a['width']/2, a['y'] + a['height']/2)
            page.mouse.down()
            page.mouse.move(b['x'] + b['width']/2, b['y'] + b['height']/2, steps=8)
            publish('first', ['s0', 's1'], correction)
            page.wait_for_timeout(1200)
            assert '준비된 문장 1' in page.locator('#live-status').inner_text(), 'Update applied during drag'
            page.mouse.up()
            page.wait_for_function('() => document.querySelector("#live-status").textContent.includes("준비된 문장 2")', timeout=2000)
            assert page.locator('#sentence-popup .passage').count() == 2
            assert page.locator('#sentence-popup .pending-message').count() == 0
            assert page.locator('#sentence-popup .revision-notice').count() == 0, 'Newly ready text is not a correction'
            checks.append('update deferred during a real mouse drag, then mixed selection becomes ready')

            page.keyboard.press('Escape')
            publish('second', ['s3'])
            page.wait_for_function('() => document.querySelector("#live-status").textContent.includes("준비된 문장 3")', timeout=2000)
            cross = annotations['sentences'][3]['tokens']
            page.evaluate('''async ([first,last]) => {
                const find=id=>document.querySelector('.source-word[data-token="'+id+'"]');
                const a=find(first),b=find(last);
                const send=(type,n,buttons)=>{const r=n.getBoundingClientRect();n.dispatchEvent(new PointerEvent(type,
                  {bubbles:true,button:0,buttons,clientX:r.x+r.width/2,clientY:r.y+r.height/2}));};
                a.scrollIntoView({block:'center'});send('pointerdown',a,1);
                b.scrollIntoView({block:'center'});await new Promise(requestAnimationFrame);
                send('pointermove',b,1);send('pointerup',b,0);
            }''', [cross[1], cross[-2]])
            selected = set(page.locator('.source-word.selected').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.token)'))
            assert selected == set(cross)
            assert '예제는 다음 페이지' in page.locator('#sentence-popup').inner_text()
            checks.append('whole sentence selection across original PDF pages')

            page.keyboard.press('Escape')
            publish('first', ['s0', 's1', 's2'], correction)
            page.wait_for_function('() => document.querySelectorAll(".math-hit").length > 0', timeout=2000)
            page.locator('.math-hit').first.click()
            assert page.locator('#sentence-popup .math-crops').count() >= 1
            checks.append('new formula hit regions and original crops appear without replacing pages')
            page.screenshot(path=str(directory / 'live-reader.png'), full_page=False)

            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            page.wait_for_function('() => document.querySelector("#live-status").textContent.includes("연결 끊김")', timeout=7000)
            assert page.locator('#sentence-popup .math-crops').count() >= 1
            checks.append('connection loss retains visible results')
            document = live_reader.LiveDocument(work, worklist_path, fragments)
            server = live_reader.make_server(document, port)
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            page.wait_for_function('() => !document.querySelector("#live-status").textContent.includes("연결 끊김")', timeout=7000)
            assert '준비된 문장 4' in page.locator('#live-status').inner_text()
            assert page.evaluate('window.originalPageImage === document.querySelector(".page-image")')
            checks.append('server restart reconciles saved JSON with existing tab')

            publish('second', ['s3', 's4'])
            page.wait_for_function('() => !document.querySelector("#final-reader").hidden', timeout=3000)
            final = document.final_path
            assert final and final.exists()
            assert page.locator('#sentence-popup').is_visible()
            assert page.evaluate('window.originalPageImage === document.querySelector(".page-image")')
            checks.append('full completion produces offline HTML without leaving live reader')
            assert not errors, errors
            assert not remote, remote
            report = {'ok': True, 'checks': checks, 'timings': timings, 'browser': browser.version,
                      'os': platform.platform(), 'external_requests': remote, 'runtime_errors': errors,
                      'final_html': str(final)}
            browser.close()
        report['offline'] = verify_offline(final)
        (directory / 'live-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), ensure_ascii=False, indent=2))
