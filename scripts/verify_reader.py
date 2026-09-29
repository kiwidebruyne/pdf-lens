#!/usr/bin/env python3
"""Exercise the actual offline reader in Chromium; no Node installation required."""
import argparse
import json
import platform
from pathlib import Path


def verify(path, expected_version=2, executable=None):
    from playwright.sync_api import sync_playwright
    checks, skipped, errors, remote = [], [], [], []
    with sync_playwright() as playwright:
        options = {'headless': True}
        if executable:
            options['executable_path'] = executable
        browser = playwright.chromium.launch(**options)
        try:
            context = browser.new_context(viewport={'width': 1180, 'height': 900}, offline=True)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: remote.append(request.url)
                    if request.url.startswith(('http:', 'https:', 'ws:', 'wss:')) else None)
            page.goto(Path(path).resolve().as_uri())
            info = page.evaluate('''() => {
                const d=JSON.parse(document.getElementById('reader-data').textContent);
                const mathTokens=new Set(Object.values(d.math||{}).flatMap(m=>m.tokens));
                return {version:d.version, pages:d.pages.map(p=>({number:p.number,label:p.printed_label,
                  tokens:p.tokens.map(t=>t.id)})), sentences:d.sentences.map(s=>s.tokens),
                  lexical:d.sentences.flatMap(s=>Object.keys(s.words||{})).find(t=>!mathTokens.has(t)),
                  math:Object.values(d.math||{}).map(m=>m.tokens), toc:(d.toc||[]).length};
            }''')
            assert info['version'] == expected_version, 'Unexpected reader contract version'
            assert info['lexical'], 'No contextual vocabulary occurrence to verify'
            assert len(info['pages']) > 0, 'No pages'
            for i in range(len(info['pages'])):
                page.locator('.page').nth(i).scroll_into_view_if_needed()
                page.wait_for_function('i => {const p=document.querySelectorAll(".page-image")[i];return p&&p.naturalWidth>0&&p.naturalHeight>0}', arg=i)
            checks.append('all embedded page images load offline')
            word_selector = lambda token: '.source-word[data-token=' + json.dumps(token) + ']'
            page.locator(word_selector(info['lexical'])).click()
            assert page.locator('#sentence-popup').is_visible(), 'Sentence click failed'
            assert page.locator('#sentence-popup .english').count()
            assert page.locator('#sentence-popup .korean').count()
            expected_translation = page.evaluate('''token => {
              const d=JSON.parse(document.getElementById('reader-data').textContent);
              const u=d.sentences.find(s=>s.tokens.includes(token)).units[0];
              const text=parts=>typeof parts==='string'?parts:parts.filter(p=>p.type==='text').map(p=>p.text).join('');
              return {literal:u.literal.map(c=>text(c.parts||c.text)).join(' / '), natural:text(u.natural)};
            }''', info['lexical'])
            korean_text = lambda: page.locator('#sentence-popup .korean').inner_text().strip()
            normalize = lambda value: ' '.join(value.split())
            # For formulas, image alt labels are not included in innerText.
            assert normalize(korean_text()) == normalize(expected_translation['literal'])
            page.locator('#sentence-popup .english-word').first.click()
            assert page.locator('#word-popup').is_visible(), 'Word popup failed'
            assert page.locator('#sentence-popup').is_visible(), 'Word popup replaced sentence'
            page.keyboard.press('Escape')
            assert not page.locator('#word-popup').is_visible()
            page.locator('.mode-toggle').click()
            assert page.locator('.mode-toggle').get_attribute('aria-pressed') == 'true'
            assert normalize(korean_text()) == normalize(expected_translation['natural'])
            page.locator('.mode-toggle').click()
            assert page.locator('.mode-toggle').get_attribute('aria-pressed') == 'false'
            assert normalize(korean_text()) == normalize(expected_translation['literal'])
            checks.extend(['sentence click', 'nested vocabulary popup', 'translation toggle'])

            def expected_tokens(first, last):
                for formula in info['math']:
                    if first in formula and last in formula:
                        return set(formula)
                positions = [i for i, s in enumerate(info['sentences']) if first in s or last in s]
                assert positions, 'Endpoint without sentence'
                return {t for s in info['sentences'][min(positions):max(positions)+1] for t in s}

            def assert_selection(first, last):
                assert page.locator('#sentence-popup').is_visible(), 'Drag did not open translation'
                actual = set(page.locator('.source-word.selected').evaluate_all('(nodes)=>nodes.map(n=>n.dataset.token)'))
                assert actual, 'Drag did not select text'
                if expected_version == 2:
                    assert actual == expected_tokens(first, last), 'Selection did not expand to whole touched sentences/formula'

            # One real mouse drag; boundary-spanning checks below simulate scrolling pointer events.
            simple = next((s for s in info['sentences'] if len(s) >= 3 and not any(t in m for t in s[:3] for m in info['math'])), None)
            if simple:
                first, last = simple[0], simple[2]
                page.keyboard.press('Escape')
                page.locator(word_selector(first)).scroll_into_view_if_needed()
                a = page.locator(word_selector(first)).bounding_box()
                b = page.locator(word_selector(last)).bounding_box()
                if a and b and 0 <= b['y'] < 850:
                    page.mouse.move(a['x']+a['width']/2, a['y']+a['height']/2)
                    page.mouse.down()
                    page.mouse.move(b['x']+b['width']/2, b['y']+b['height']/2, steps=12)
                    page.mouse.up()
                    assert_selection(first,last)
                    checks.append('real mouse drag')
                else:
                    skipped.append('real mouse drag: endpoints not jointly visible')

            def drag(first, last):
                page.keyboard.press('Escape')
                page.evaluate('''async ([first,last]) => {
                  const find=id=>[...document.querySelectorAll('.source-word')].find(n=>n.dataset.token===id);
                  const a=find(first),b=find(last); if(!a||!b)throw Error('Missing drag endpoint');
                  const event=(type,n,buttons)=>{const r=n.getBoundingClientRect();return new PointerEvent(type,
                    {bubbles:true,button:0,buttons,clientX:r.x+r.width/2,clientY:r.y+r.height/2});};
                  a.scrollIntoView({block:'center'});await new Promise(requestAnimationFrame);
                  a.dispatchEvent(event('pointerdown',a,1));
                  b.scrollIntoView({block:'center'});await new Promise(requestAnimationFrame);
                  window.dispatchEvent(event('pointermove',b,1));window.dispatchEvent(event('pointerup',b,0));
                }''', [first,last])
                assert_selection(first,last)

            selectable = {t for s in info['sentences'] for t in s}
            groups = [[t for t in p['tokens'] if t in selectable] for p in info['pages']]
            groups = [g for g in groups if g]
            first, last = groups[0][0], groups[0][min(12, len(groups[0])-1)]
            drag(first,last); drag(last,first)
            checks.append('forward and reverse drag')
            if len(groups) > 1:
                drag(groups[0][-1],groups[1][0]); drag(groups[1][0],groups[0][-1])
                checks.append('forward and reverse page-boundary drag')
            else:
                skipped.append('page-boundary drag: single text page')
            if info['math']:
                page.locator('.math-hit').first.click()
                for mode in range(2):
                    assert page.locator('#sentence-popup .english .math-crop img').count()
                    assert page.locator('#sentence-popup .korean .math-crop img').count()
                    page.locator('#sentence-popup .english .math-crop img').first.evaluate('(img)=>img.decode()')
                    page.locator('.mode-toggle').click()
                formula = next((m for m in info['math'] if len(m)>1), None)
                if formula:
                    drag(formula[0],formula[-1])
                    assert page.locator('#sentence-popup .english .math-crop img').count()
                checks.append('original formula in both modes and atomic selection')
            else:
                skipped.append('formulas: none annotated')
            if expected_version == 2:
                if info['toc']:
                    page.locator('#toc-toggle').click()
                    assert page.locator('#toc-panel').is_visible()
                    page.locator('.toc-entry').first.click()
                    assert not page.locator('#toc-panel').is_visible()
                    checks.append('table of contents')
                else:
                    skipped.append('table of contents: no headings annotated')
                for kind, value in [('pdf',str(info['pages'][0]['number'])), ('book',info['pages'][0]['label'])]:
                    page.locator('#page-kind').select_option(kind)
                    page.locator('#page-query').fill(value)
                    page.locator('#page-jump button').click()
                    assert page.locator('#page-status').text_content() == ''
                page.locator('#page-query').fill('999999')
                page.locator('#page-jump button').click()
                assert page.locator('#page-status').text_content(), 'Out-of-range jump lacks feedback'
                checks.append('printed/PDF page jumps and missing-page feedback')
            before = page.locator('#zoom-label').text_content()
            page.locator('#zoom-in').click()
            assert page.locator('#zoom-label').text_content() != before
            page.locator('#fit').click()
            assert page.locator('#zoom-label').text_content() == before
            assert not errors, errors
            assert not remote, remote
            checks.extend(['zoom/fit', 'zero external requests', 'zero runtime errors'])
            return {'ok': True, 'browser': browser.version, 'os': platform.platform(),
                    'architecture': platform.machine(), 'pages': len(info['pages']),
                    'checks': checks, 'skipped': skipped}
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('html', type=Path)
    parser.add_argument('--expect-version', type=int, choices=(2,), default=2)
    parser.add_argument('--executable', help='Optional existing Chromium/Chrome executable for local diagnostics')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = verify(args.html, args.expect_version, args.executable)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output+'\n', encoding='utf-8')
    print(output)
