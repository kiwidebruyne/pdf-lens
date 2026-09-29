#!/usr/bin/env python3
"""Run the real validator on one in-progress textbook annotation fragment.

Errors caused solely by pages assigned to other fragment authors are omitted.
This check does not set the actual review flags or establish language quality.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import tempfile

from paper_reader import read_json, validate
from workflow import validate_fragment


def rendered_parts(value):
    if isinstance(value, list):
        return ''.join(rendered_parts(part) for part in value)
    if isinstance(value, dict):
        if value.get('type') == 'text':
            return value.get('text', '')
        if value.get('type') == 'math':
            return '<math:' + value.get('ref', '') + '>'
        if 'parts' in value:
            return rendered_parts(value['parts'])
    return ''


def audit_report(fragment, prepared):
    tokens = {token['id']: token['text'] for page in prepared['pages']
              for token in page['tokens']}
    lines = ['# Source-span audit', '',
             'Generated from the prepared source and annotation fragment. Compare each Korean field',
             'with the exact English tokens in its selected span before setting review flags.', '']
    for sentence in fragment.get('sentences', []):
        ids = sentence.get('tokens', [])
        if not ids:
            continue
        lines.extend([f"## {sentence.get('id', '')} · {ids[0]}–{ids[-1]}", ''])
        whole = next((unit for unit in sentence.get('units', [])
                      if unit.get('start') == 0 and unit.get('end') == len(ids)), None)
        for unit in [whole] if whole else []:
            start, end = unit.get('start'), unit.get('end')
            if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(ids)):
                continue
            selected = ids[start:end]
            english = ' '.join(tokens.get(key, f'[UNKNOWN:{key}]') for key in selected)
            literal = ' / '.join(rendered_parts(chunk.get('parts')) for chunk in unit.get('literal', []))
            natural = rendered_parts(unit.get('natural'))
            flags = []
            if literal == natural:
                flags.append('same literal/natural rendering')
            lines.extend([f"### {unit.get('id', '')} [{start}:{end}] · {selected[0]}–{selected[-1]}",
                          f'- EN: {json.dumps(english, ensure_ascii=False)}',
                          f'- 직역: {json.dumps(literal, ensure_ascii=False)}',
                          f'- 의역: {json.dumps(natural, ensure_ascii=False)}'])
            if flags:
                lines.append('- CHECK: ' + '; '.join(flags))
            lines.append('')
    roles = {}
    for sentence in fragment.get('sentences', []):
        for key, word in sentence.get('words', {}).items():
            role = word.get('role', '')
            roles.setdefault(role, []).append((key, word))
    lines.extend(['## Most reused word roles', ''])
    for role, occurrences in sorted(roles.items(), key=lambda pair: -len(pair[1]))[:10]:
        lines.append(f"- {len(occurrences)} × {json.dumps(role, ensure_ascii=False)}; tokens: " +
                     ', '.join(key for key, _ in occurrences[:12]))
    lines.extend(['', '## Word cards needing a closer look', ''])
    lexicon = fragment.get('lexicon', {})
    for sentence in fragment.get('sentences', []):
        for key, word in sentence.get('words', {}).items():
            entry = lexicon.get(word.get('entry'), {})
            raw_gloss = entry.get('gloss', '').strip().casefold() == entry.get('lemma', '').strip().casefold()
            meaning = word.get('meaning', '')
            latin_only = bool(re.search(r'[A-Za-z]', meaning)) and not bool(re.search(r'[가-힣]', meaning))
            if raw_gloss or latin_only:
                lines.append(f"- {key} {json.dumps(tokens.get(key, ''), ensure_ascii=False)}: " +
                             f"lemma={json.dumps(entry.get('lemma', ''), ensure_ascii=False)}, " +
                             f"gloss={json.dumps(entry.get('gloss', ''), ensure_ascii=False)}, " +
                             f"meaning={json.dumps(meaning, ensure_ascii=False)}, " +
                             f"role={json.dumps(word.get('role', ''), ensure_ascii=False)}")
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, type=Path)
    parser.add_argument('--fragment', required=True, type=Path)
    parser.add_argument('--worklist', type=Path,
                        help='Validate explicit token ownership from a deterministic worklist')
    parser.add_argument('--chunk',
                        help='Chunk ID owned by this fragment; requires --worklist')
    parser.add_argument('--audit-out', type=Path,
                        help='Write exact English span beside literal/natural Korean for author review')
    args = parser.parse_args()
    if bool(args.worklist) != bool(args.chunk):
        parser.error('--worklist and --chunk must be supplied together')
    source = read_json(args.work / 'annotations.json')
    fragment = read_json(args.fragment)
    ownership_errors = []
    if args.worklist:
        try:
            validate_fragment(args.work, read_json(args.worklist), fragment, args.chunk)
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            ownership_errors.append(str(error))
    if source['version'] != 2:
        parser.error('fragment check requires scoped version-2 preparation')
    for key in ('lexicon', 'sentences', 'math', 'excluded', 'toc'):
        source[key] = fragment.get(key, source[key])
    owned_pages = set(map(str, fragment.get('page_labels', {})))
    source['page_labels'] = {str(page): fragment.get('page_labels', {}).get(str(page), str(page))
                             for page in range(source['scope']['first_page'], source['scope']['last_page'] + 1)}
    source['review'] = {'language': True, 'layout': True, 'coverage': True,
                        'notes': 'Temporary structural fragment check; actual review remains unset.'}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as file:
        json.dump(source, file, ensure_ascii=False)
        file.flush()
        _, _, report = validate(args.work, Path(file.name))
    errors = list(ownership_errors)
    for error in report['errors']:
        if 'source tokens unassigned:' in error:
            continue
        match = re.match(r'^p(\d+)t\d+: unusual extracted glyph', error)
        if match and match.group(1) not in owned_pages:
            continue
        errors.append(error)
    prepared = read_json(args.work / 'prepared.json')
    if args.audit_out:
        args.audit_out.parent.mkdir(parents=True, exist_ok=True)
        args.audit_out.write_text(audit_report(fragment, prepared), encoding='utf-8')
    if args.worklist:
        expected_owned = set(next(chunk['owned_tokens'] for chunk in read_json(args.worklist)['chunks']
                                  if chunk['id'] == args.chunk)) if not ownership_errors else set()
    else:
        expected_owned = {token['id'] for page in prepared['pages'] if str(page['number']) in owned_pages
                          for token in page['tokens']}
    assigned = {key for sentence in fragment.get('sentences', []) for key in sentence.get('tokens', [])}
    assigned.update(key for item in fragment.get('excluded', []) for key in item.get('tokens', []))
    unassigned_owned = sorted(expected_owned - assigned)
    units = [unit for sentence in fragment.get('sentences', [])
             for unit in sentence.get('units', [])
             if unit.get('start') == 0 and unit.get('end') == len(sentence.get('tokens', []))]
    identical_modes = sum(rendered_parts(unit.get('literal')) == rendered_parts(unit.get('natural'))
                          for unit in units)
    generic_glosses = sum('문맥에서' in entry.get('gloss', '') or
                          '문맥상' in entry.get('gloss', '')
                          for entry in fragment.get('lexicon', {}).values())
    raw_english_glosses = sum(entry.get('gloss', '').strip().casefold() ==
                              entry.get('lemma', '').strip().casefold()
                              for entry in fragment.get('lexicon', {}).values())
    roles = Counter(word.get('role', '') for sentence in fragment.get('sentences', [])
                    for word in sentence.get('words', {}).values())
    meaning_without_korean = sum(bool(re.search(r'[A-Za-z]', word.get('meaning', ''))) and
                                 not bool(re.search(r'[가-힣]', word.get('meaning', '')))
                                 for sentence in fragment.get('sentences', [])
                                 for word in sentence.get('words', {}).values())
    print(json.dumps({'structural_ok_excluding_other_fragments': not errors, 'fragment': str(args.fragment),
                      'assigned_in_full_scope': report['coverage']['assigned'],
                      'full_scope_total': report['coverage']['total'],
                      'unassigned_on_declared_pages': len(unassigned_owned),
                      'first_unassigned_on_declared_pages': unassigned_owned[:30],
                      'identical_literal_natural_whole_sentences': identical_modes,
                      'whole_sentence_count': len(units),
                      'potentially_generic_glosses': generic_glosses,
                      'raw_english_glosses': raw_english_glosses,
                      'lexicon_entry_count': len(fragment.get('lexicon', {})),
                      'most_reused_word_role_count': roles.most_common(1)[0][1] if roles else 0,
                      'word_occurrence_count': sum(roles.values()),
                      'word_meanings_without_korean': meaning_without_korean,
                      'fragment_errors': errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == '__main__':
    raise SystemExit(main())
