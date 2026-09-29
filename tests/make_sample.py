#!/usr/bin/env python3
"""Create a tiny, authored public-domain test document and complete reader data."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import paper_reader


def make_sample(directory):
    import pymupdf
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    pdf = directory / 'sample.pdf'
    work = directory / 'sample.work'
    document = pymupdf.open()
    p = document.new_page(width=420, height=540)
    for y, value in [(70,'Models describe systems.'),(120,'A probability is between 0 and 1.'),
                     (180,'P(A) = 0.5'),(480,'An example can')]:
        p.insert_text((40,y),value,fontsize=14)
    p = document.new_page(width=420,height=540)
    p.insert_text((40,70),'continue across pages.',fontsize=14)
    p.insert_text((40,130),'Observe the result.',fontsize=14)
    document.save(pdf)
    document.close()
    paper_reader.prepare(pdf,work)
    prepared = paper_reader.read_json(work/'prepared.json')
    a = paper_reader.read_json(work/'annotations.json')
    tokens = [t for p in prepared['pages'] for t in p['tokens']]
    cursor = 0
    specifications = [
        (['Models','describe','systems.'],'모형은 / 기술한다 / 시스템을.','모형은 시스템을 기술한다.'),
        (['A','probability','is','between','0','and','1.'],'확률은 / 있다 / 0과 1 사이에.','확률은 0과 1 사이에 있다.'),
        (['P(A)','=','0.5'],None,None),
        (['An','example','can','continue','across','pages.'],'한 예제는 / 이어질 수 있다 / 페이지를 넘어서.','예제는 다음 페이지로 이어질 수 있다.'),
        (['Observe','the','result.'],'관찰하라 / 그 결과를.','결과를 관찰하자.'),
    ]
    meanings = {
        'models':('model','명사','모형','현상을 표현하는 모형들','주어'),
        'describe':('describe','동사','기술하다','시스템의 성질을 나타내다','서술어'),
        'systems':('system','명사','시스템','모형이 기술하는 대상','목적어'),
        'a':('a','관사','하나의','일반적인 확률 하나를 도입함','probability를 한정'),
        'probability':('probability','명사','확률','0과 1 사이의 확률값','주어의 중심 명사'),
        'is':('be','동사','있다','확률값이 특정 구간에 속함','서술어'),
        'between':('between','전치사','사이에','0과 1을 양 끝으로 하는 구간 안에','범위를 나타내는 전치사'),
        'and':('and','접속사','그리고','구간의 두 끝값을 연결','0과 1 연결'),
        'an':('an','관사','하나의','예제 하나를 도입함','example을 한정'),
        'example':('example','명사','예제','여러 페이지에 걸친 예제','주어의 중심 명사'),
        'can':('can','조동사','할 수 있다','예제가 다음 페이지로 이어질 가능성','가능성 표현'),
        'continue':('continue','동사','이어지다','예제 내용이 계속되다','서술어'),
        'across':('across','전치사','넘어서','페이지 경계를 가로질러','범위 표현'),
        'pages':('page','명사','페이지','내용이 이어지는 지면들','전치사의 목적어'),
        'observe':('observe','동사','관찰하다','결과를 살펴보라는 지시','명령문의 서술어'),
        'the':('the','관사','그','특정 결과를 지칭함','result를 한정'),
        'result':('result','명사','결과','관찰할 대상인 결과','목적어'),
    }
    for number,(source,literal,natural) in enumerate(specifications):
        part = tokens[cursor:cursor+len(source)]
        assert [t['text'] for t in part] == source
        ids = [t['id'] for t in part]
        cursor += len(part)
        words = {}
        if literal is None:
            x = min(t['box'][0] for t in part)-1
            y = min(t['box'][1] for t in part)-1
            right = max(t['box'][0]+t['box'][2] for t in part)+1
            bottom = max(t['box'][1]+t['box'][3] for t in part)+1
            a['math']['eq1']={'tokens':ids,'regions':[{'page':1,'box':[x,y,right-x,bottom-y]}]}
            lp=np=[{'type':'math','ref':'eq1'}]
        else:
            lp=[{'type':'text','text':literal}]
            np=[{'type':'text','text':natural}]
            for t in part:
                if not paper_reader.ENGLISH.search(t['text']):
                    continue
                key=t['text'].lower().strip('.')
                lemma,pos,gloss,meaning,role=meanings[key]
                a['lexicon'][key]={'lemma':lemma,'pos':pos,'gloss':gloss}
                words[t['id']]={'entry':key,'meaning':meaning,'role':role,'expression':''}
        a['sentences'].append({'id':f's{number}','tokens':ids,'words':words,'joins':[],
            'units':[{'id':f'u{number}','start':0,'end':len(ids),
                      'literal':[{'start':0,'end':len(ids),'parts':lp}],'natural':np}]})
    assert cursor==len(tokens)
    a.update(title='PDF Lens 예제',page_labels={'1':'10','2':'11'},
             toc=[{'title':'모형과 확률','page':1},{'title':'이어지는 예제','page':2}],
             review={'language':True,'layout':True,'coverage':True,
                     'notes':'Synthetic fixture authored together with source; all 22 source tokens and page-spanning sentence checked.'})
    paper_reader.write_json(work/'annotations.json',a)
    html=directory/'sample.html'
    report=paper_reader.build(work,work/'annotations.json',html)
    return {'html':str(html),'work':str(work),'result':report}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    print(json.dumps(make_sample(parser.parse_args().output),ensure_ascii=False,indent=2))
