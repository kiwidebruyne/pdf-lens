# PDF Lens data contract

Read this when authoring annotations or diagnosing validation. Source IDs point back to the original PDF; never invent, edit, or renumber them. Ranges are zero-based, start-inclusive and end-exclusive unless stated otherwise.

## Prepared source

Prepare, validate and build through the installed `scripts/run.py`, which dispatches to the matching retained processor. `scripts/paper_reader.py` is an internal/source-test entrypoint, not the normal user procedure. New preparations use `version: 2` for a full PDF or a selected inclusive physical-page range. `prepared.json` records the source name and SHA-256, scope, original source-page numbers, PDF backend and processor versions, rendered pages and extracted tokens. A page includes its original physical page number, dimensions, SVG, SVG digest and tokens. A token has a stable ID such as `p214t0`, original text, top-left page box, extraction block/line and character records. A character record contains its text, box and origin. `glyphs.json` retains the per-token character data and `anomalies.json` identifies suspicious control, replacement and private-use characters for visual review.

The retained source PDF, prepared data, SVGs and manifest are bound by source and artifact hashes to the work folder. Do not hand-edit them. Correct logical reading order and language only in annotations. If source text, glyph identity or geometry cannot be recovered from the page image, stop and report the affected page rather than translating a guess.

## Annotations v3

New annotations contain `version: 3`, source_sha256, scope, title, language, page_labels, toc, math, sentences, excluded, unselectable_pages and review. Extraction stays v2 with unchanged token IDs. A sentence is:

```json
{"id":"s1","tokens":["p1t0"],"natural":[{"type":"text","text":"모형"}],"words":{"p1t0":{"base":"모형","meaning":"이 모형"}},"joins":[]}
```

`natural` is one complete sentence translation as text/math parts. A formula part is `{"type":"math","ref":"formula-id"}`. Include each owned formula once, in source order. Do not cut a formula or sentence across authoring boundaries. Headings, captions and short labels can be their own sentence entry. Dragging selects whole prepared sentences; formula-only selection shows the original crop. There is no literal mode or unit array.

Every included ASCII-letter prose token needs nonempty `base` (basic meaning) and `meaning` (this occurrence). Pure numbers, punctuation and formula-owned tokens need no word card. Use concise Korean meanings, such as “어제 비가 왔다”; avoid explanatory padding such as “문맥상 …을 나타냄”. There is no lexicon, lemma, POS, role or expression field. Repeated words may have different base wording; merge does not reconcile dictionary entries. Keep technical notation consistent through a small author reference note.

`tokens` defines visually confirmed logical reading order. Every selected source token belongs to exactly one sentence or one documented exclusion. Sentence IDs are unique and original page order is nondecreasing. Optional `joins` preserve individual token IDs and boxes for physically split words verified on the page image.

`math` maps formula IDs to source tokens and page crop regions `[x,y,width,height]`. Use exact formula regions without nearby prose. Writers check extraction anomalies while authoring; account for meaningful glyphs as math, or verified decoration with a concrete exclusion note. Do not guess unrecovered prose. Do not supply solutions or explanations absent from the source.

Allowed exclusions: references, running_header, page_number, nonlinguistic, each with a concrete note. Prose is never excluded for difficulty. Every selected page needs a printed page label; toc names only selected pages. Truly empty or figure-only pages are accounted for in unselectable_pages; scanned prose is unsupported.

`review.language`, `review.layout`, `review.coverage` record the writer's completed source checks. They are not automatic proof. No separate model performs full language review. Automated validation checks hashes, identities, omissions, duplicates, mandatory meanings, sentence boundaries, formula references and crop geometry. Fix affected parts and rerun when data changes; do not repeat unchanged full checks.

Legacy v2 annotations can be copied and converted using `run.py migrate --work OLD --output NEW`. Natural text, source token IDs, math and joins are retained. Lexicon gloss becomes each token's base and occurrence meaning is retained. The original folder and retained runtime remain unchanged; migration.json records the extraction and new processing runtime separately.

## Generated HTML

The build embeds page images and translation data in one HTML file. It needs no model, network call, server or extra installation to read. Source text is inserted as text, not executable markup. The reader template is shared; do not tailor or hand-edit generated HTML. Correct annotations and rebuild instead.

## Live publication

Live publication uses cumulative v3 fragments with immutable `_chunk` ownership metadata. Sentence contents retain the same v3 contract. `review.language` and `review.layout` attest to the submitted complete sentences; `review.coverage` remains false until all owned tokens have been accounted for. Missing pending tokens are permitted only for live preview, never for the final build. Published sentences must already include all required cards and formula regions.

The loopback reader embeds original pages once and fetches changed annotations, not new page images. Its update envelope contains a session epoch, monotonic revision, changed sentences, removed IDs, source-ordered sentence IDs, math and metadata, and display status. A new session or missed history resets annotation state without replacing pages. Runtime status and accepted snapshots are separate from source artifacts and the annotation v3 schema. Reading interactions never trigger model calls.
