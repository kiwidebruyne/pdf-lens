---
name: pdf-lens
description: Create an offline Korean close-reading HTML companion for English research papers or selected textbook pages. Use when someone wants to read and interact with the original PDF, not receive a summary. Scanned PDFs are unsupported.
---

# PDF Lens

Turn a supported English PDF into a reader that keeps the original pages and adds prepared Korean translations and contextual word cards. Open the original-page reader as soon as extraction is ready; publish each checked complete sentence while authoring continues. The final self-contained HTML works offline. The person supplies a PDF and chooses the paper or textbook pages; Codex handles execution without asking them to run terminal commands.

Use the installed `scripts/run.py` for preparation, validation and build. It checks for the latest stable release only when preparing a new work folder, never downgrades a newer local version, then records the selected runtime in `execution.json`; resume and later validation/build use that pinned runtime. If an update fails, keep working with the current known-good release where possible. See [setup and updates](references/setup.md).

After preparation, start `scripts/run.py serve --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/` as a continuing local process and open its returned URL in Codex. The worklist may be created after the original-only preview opens. For authoring, publication and finalization, read [parallel authoring](references/parallel-workflow.md), including a small document assigned to one worker. In Codex, use `gpt-6.1-sol` with low reasoning effort; if unavailable, use `gpt-6-luna` with high reasoning effort. Writers check source, language and formulas as they author; do not add a separate full language-review model pass or call a model in response to a reading interaction.

Use coherent paragraph groups and complete examples, proofs or exercise steps as assignment units; never split a sentence or calculation between owners. Each complete sentence is the publication unit. Read [translation guidance](references/translation-guide.md) and the relevant [paper](references/paper-workflow.md) or [textbook](references/textbook-workflow.md) workflow.

Read [the data contract](references/data-contract.md) before editing annotations or diagnosing validation. Read [installation and release details](references/setup.md) only when installing, updating, or diagnosing the tool environment. Read [verification guidance](docs/verification.md) before claiming a reader is complete.

Treat image-only/scanned text as unsupported. Preserve the source PDF and all work files needed for correction or resumption. Put work and reader files under `output/pdf-lens/`.

New annotations use v3: one natural sentence translation and token-local `base` / `meaning` word cards. For legacy conversion use `run.py migrate --work OLD --output NEW`; keep the original and extraction pin intact. Existing jobs retain their version and may not support live reading; do not silently repin them. If interrupted, restart `serve` against the same worklist and fragments to recover saved results. Only complete, fully validated work becomes the final offline HTML; deliver its reported path and actual source limitations.
