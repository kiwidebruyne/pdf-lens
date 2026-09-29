---
name: pdf-lens
description: Create an offline Korean close-reading HTML companion for English research papers or selected textbook pages. Use when someone wants to read and interact with the original PDF, not receive a summary. Scanned PDFs are unsupported.
---

# PDF Lens

Turn a supported English PDF into a self-contained HTML reader that keeps the original pages and adds prepared Korean translations and contextual word cards. The reader works offline after creation. For the normal user workflow, the person attaches the PDF or identifies a PDF already in the workspace, then chooses the paper or textbook pages to process; do not ask them to run terminal commands.

Use the installed `scripts/run.py` for preparation, validation and build. It checks for the latest stable release only when preparing a new work folder, then records the selected runtime in `execution.json`; resume and later validation/build use that pinned runtime. If an update fails, keep working with the current known-good release where possible. See [setup and updates](references/setup.md).

Prepare every selected sentence and word card before building the reader. Assign source reading, translation, vocabulary, formula mapping and source checks to `gpt-6-luna` workers with high reasoning effort for every PDF, including a small document handled by one worker. Fall back to `gpt-5.6-luna` with high effort when unavailable. The main agent owns code, integration and final verification. Read the [translation guide](references/translation-guide.md) for language quality. For a paper, follow [paper workflow](references/paper-workflow.md); for a textbook range, follow [textbook workflow](references/textbook-workflow.md). Never call a model or translation service while reading the generated HTML.

For work that can be divided across authoring lanes, use the immutable source-ordered worklist workflow in [parallel authoring](references/parallel-workflow.md). Divide coherent paragraph groups and complete examples, proofs, or exercise steps, aiming for roughly 200 word cards per chunk as a soft checkpoint. Do not assign one worker per section or page, and do not split a sentence or calculation across ownership boundaries.

Read [the data contract](references/data-contract.md) before editing annotations or diagnosing validation. Read [installation and release details](references/setup.md) only when installing, updating, or diagnosing the tool environment. Read [verification guidance](docs/verification.md) before claiming a reader is complete.

Treat image-only/scanned text as unsupported. Preserve the source PDF and all work files needed for correction or resumption. Put work and reader files under `output/pdf-lens/`.
