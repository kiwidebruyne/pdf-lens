# Textbook workflow

Use this workflow when the person wants a selected portion of a textbook or other teaching text. The output is one HTML companion for the requested page range.

## Confirm the scope

1. Attach the PDF or locate it in the workspace; leave the original unchanged.
2. Ask which printed pages, chapter or section they want only when the requested boundary cannot be determined from the PDF. Map printed labels to physical PDF page numbers from the rendered source.
3. Keep the deliverable inside the selected physical page range. Do not silently include adjacent sections. If a page boundary cuts a sentence, example, proof or exercise step, adjust to the nearest complete unit and tell the person the actual range.
4. Inspect extraction and page images. If the selected pages are scans or contain prose that cannot be reliably recovered, explain the limitation instead of guessing.

Prepare only the selected inclusive physical PDF page range in a stable per-range work folder using `scripts/run.py prepare PDF --work WORK --pages FIRST-LAST`. This normal entrypoint checks for the latest stable release only for a new work folder and pins that work to its runtime. Do not invoke the internal `paper_reader.py` directly for a normal task.

After extraction, open the original-page live reader before waiting for translations. Use the [worklist and sentence publication workflow](parallel-workflow.md), even for one author. Publish checked sentences as they are completed.

## Translate and prepare math

Translate the source as written, including definitions, assumptions, worked examples, proofs, instructions and exercise prompts. Do not solve exercises, add proof steps or introduce facts from outside the selected pages. You may inspect surrounding pages on demand to understand notation or terminology, but keep that context out of the delivered translation. State a symbol's meaning only if the book establishes it; otherwise say it is not defined at that point.

Compare formula tokens against the page image. Attach each meaningful equation, matrix, set or other math region to its original-page crop so a formula-only selection shows the source formula. Translate surrounding prose in full. Inspect and account for every anomalous glyph; never label meaningful math or prose decorative.

Use one natural translation per complete sentence. Every selected page needs a printed label for reader navigation. Add TOC entries only for headings actually shown in the selected range. Follow the [translation guide](translation-guide.md) for Korean and the [data contract](data-contract.md) for page labels, math crops, token ownership and validation.

On completion the live server merges, validates and builds WORK/reader.html. Supply the resulting file to the person. The normal validate/build commands remain available for diagnosis or an explicitly chosen output path, using the work's pinned runtime.

## Review and deliver

Review each selected page for definitions, examples, proof steps, table/caption text and problem instructions. Check the natural translation, notation and formula crop alignment against the original pages. Report the processed printed and PDF page ranges, sentence and word-card counts, and any actual gaps such as visible image-only lettering.
