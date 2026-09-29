# PDF Lens data contract

Read this when authoring annotations or diagnosing validation. Source IDs point back to the original PDF; never invent, edit, or renumber them. Ranges are zero-based, start-inclusive and end-exclusive unless stated otherwise.

## Prepared source

Prepare, validate and build through the installed `scripts/run.py`, which dispatches to the matching retained processor. `scripts/paper_reader.py` is an internal/source-test entrypoint, not the normal user procedure. New preparations use `version: 2` for a full PDF or a selected inclusive physical-page range. `prepared.json` records the source name and SHA-256, scope, original source-page numbers, PDF backend and processor versions, rendered pages and extracted tokens. A page includes its original physical page number, dimensions, SVG, SVG digest and tokens. A token has a stable ID such as `p214t0`, original text, top-left page box, extraction block/line and character records. A character record contains its text, box and origin. `glyphs.json` retains the per-token character data and `anomalies.json` identifies suspicious control, replacement and private-use characters for visual review.

The retained source PDF, prepared data, SVGs and manifest are bound by source and artifact hashes to the work folder. Do not hand-edit them. Correct logical reading order and language only in annotations. If source text, glyph identity or geometry cannot be recovered from the page image, stop and report the affected page rather than translating a guess.

## Annotations

New v2 annotations contain `version: 2`, `source_sha256`, `scope`, `title`, `language`, `page_labels`, `toc`, `math`, `lexicon`, `sentences`, `excluded`, `unselectable_pages` and `review`. Selected physical page numbers are inclusive in `scope`. Keep every selected page's printed label in `page_labels`; a TOC entry names a selected physical page. The preparation command writes an unfinished starter with blank labels and review flags false. Validation should reject unfinished annotations.

```json
{
  "version": 2,
  "source_sha256": "COPY_FROM_PREPARED",
  "scope": {"first_page": 1, "last_page": 1},
  "title": "Paper title",
  "language": "en",
  "page_labels": {"1": "1"},
  "toc": [],
  "math": {},
  "lexicon": {
    "model-n": {"lemma": "model", "pos": "명사", "gloss": "모형, 모델"}
  },
  "sentences": [
    {
      "id": "s1",
      "tokens": ["p1t0", "p1t1"],
      "units": [{
        "id": "s1-whole",
        "start": 0,
        "end": 2,
        "literal": [{"start": 0, "end": 2, "parts": [{"type": "text", "text": "모형들"}]}],
        "natural": [{"type": "text", "text": "모형들"}]
      }],
      "words": {
        "p1t0": {"entry": "model-n", "meaning": "이 연구의 모형", "role": "명사구의 중심어", "expression": ""}
      },
      "joins": []
    }
  ],
  "excluded": [],
  "unselectable_pages": [],
  "review": {"language": false, "layout": false, "coverage": false, "notes": ""}
}
```

This example only illustrates the field shapes. Populate the annotations from the actual source. Mark review flags true only after completing the named review.

### Sentences and translation units

- The sentence `tokens` list defines corrected logical reading order across lines, columns and pages. Each source token in scope belongs to exactly one sentence or one documented exclusion. A title, heading, table cell, caption fragment or short label can be its own entry.
- New v2 work prepares exactly one whole-sentence unit per sentence, covering `[0, tokens.length)`. Do not prepare clause, phrase or arbitrary substring variants. Literal chunks partition the sentence span in source order without gaps or overlaps; their translated parts preserve meaningful English phrase/clause order and display separated by ` / `. Natural parts give fluent Korean with the same meaning, without adding explanation or summary.
- A drag touching one or more sentences displays each complete prepared sentence in annotated reading order and highlights those sentences. A drag restricted to one formula displays its original formula crop. The reader must not synthesize translations or call an LLM.
- Each v2 chunk has `parts`: a sequence of exactly `{"type":"text","text":"..."}` or `{"type":"math","ref":"formula-id"}`. `natural` is also a parts array. Korean text next to a formula remains a separate text part. A formula reference appears once and in source order in both modes; no unit or chunk may cut through a formula.
- Sentence and unit IDs are unique. Keep sentences and sentence tokens in nondecreasing original page order; within a page use visually confirmed reading order.

### Words, joins and math

- Every included prose token with an ASCII letter needs a `words` entry. Punctuation, pure numbers and tokens owned by a math reference do not. Share a lexicon entry only when lemma, part of speech and base sense match; make occurrence-level `meaning` and `role` specific to the source context. `expression` explains a relevant idiom or technical expression, or is empty.
- Optional `joins` join consecutive tokens physically split by extraction, such as a line-break hyphen. Preserve their individual IDs and boxes. Use only when the rendered source confirms the joined spelling; this is not a general text correction mechanism.
- A `math` entry identifies formula tokens and one or more page-specific crop regions in `[x,y,width,height]` page coordinates. Attach math only to formula content, not nearby prose. Check extracted characters against the page image, especially entries in `anomalies.json`. Every anomaly must be accounted for as meaningful math with an exact crop or as a verified decorative mark excluded with a concrete note. Never exclude a prose glyph or an unrecovered word as decorative.
- Translate the definition, explanation, proof, example or exercise prompt around a formula faithfully. Do not supply a derivation or solution absent from the source.

### Scope, exclusions and review

Allowed exclusion reasons are `references`, `running_header`, `page_number` and `nonlinguistic`. Give a concrete region in each note. Do not exclude prose because it is difficult: front matter, headings, captions, footnotes, table text, exercise prompts and body prose remain in scope. Image-only lettering stays visible on the original page but is not translated and must be disclosed.

For a page with no extracted tokens, visually inspect it and account for it as truly `blank` or `figure_only` in `unselectable_pages`. A scanned text page is unsupported, not an empty page. A PDF with no usable text is unsupported.

`review.language`, `review.layout` and `review.coverage` are attestations, not automatic proof. Read the source and compare its rendered pages before setting them true. Structural validation checks identities, coverage and spans; it cannot prove translation correctness or visual reading order.

## Generated HTML

The build embeds page images and translation data in one HTML file. It needs no model, network call, server or extra installation to read. Source text is inserted as text, not executable markup. The reader template is shared; do not tailor or hand-edit generated HTML. Correct annotations and rebuild instead.
