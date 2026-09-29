# Research paper workflow

Use this workflow for an English-language research paper the person wants to read closely. The deliverable is a self-contained HTML companion for the full paper by default. If the user names a narrower page scope, confirm that it covers complete sentences and content boundaries, and state exactly what was processed.

## Prepare the source

1. Attach the PDF or locate the named PDF in the workspace. Keep the original file unchanged.
2. Check that text can be extracted and compare representative pages with their rendered images. If the PDF is scanned or prose is unreadable or corrupt, explain the input limitation instead of fabricating an extraction.
3. Establish title, subject, abstract and section structure from the source. Use that shared context to keep terminology consistent throughout the paper.

Prepare the whole paper by default in a stable per-document work folder using `scripts/run.py prepare PDF --work WORK`. This normal entrypoint checks for the latest stable release only for a new work folder and pins that work to its runtime. Do not invoke the internal `paper_reader.py` directly for a normal task.

## Author the full paper

Include the title, author/front matter, abstract, headings, body, appendices, footnotes, captions and readable text in tables and figures. Correct sentence order from the page images, particularly at column changes and page breaks. Do not mistake `et al.`, `Fig.`, `e.g.`, decimals or citation markers for sentence endings. A sentence that continues across a page remains one annotation sentence.

Exclude only reference-list entries, running headers/footers, page numbers and verified nonlinguistic marks as allowed by the [data contract](data-contract.md). Preserve image-only lettering visually; it has no selectable token card and must be mentioned as untranslated in the completion report.

Every included sentence receives one whole-sentence translation unit and every included English prose token receives its contextual word card. Use the [translation guide](translation-guide.md) for literal and natural Korean; use the [data contract](data-contract.md) for exact annotation fields, math crops and validation requirements.

After authoring `annotations.json`, run `scripts/run.py validate --work WORK --annotations ANNOTATIONS`, then `scripts/run.py build --work WORK --annotations ANNOTATIONS --output OUTPUT_HTML`. The runner uses the version pinned in the work folder for both operations.

## Review and deliver

Compare language and reading order against the source pages; verify token coverage and inspect all glyph anomalies. Set the review flags only when the corresponding checks are complete. Build with the shared reader template and report the number of processed pages, sentences and word occurrences, along with image-only text and any actual source limitations.
