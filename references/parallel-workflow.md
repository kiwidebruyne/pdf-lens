# Parallel authoring

Use parallel authoring only when the selected document has enough coherent work to benefit from multiple writers. The output still needs one integration owner; splitting by page or creating one worker for every section makes context and terminology drift more likely.

Prepare, validate and build with the installed `scripts/run.py`; it checks for stable updates only for a new work folder and pins that work to one release. The `workflow.py` helper commands below are the only direct script calls in this guide. Invoke them with the private interpreter and source snapshot matched to the work folder's `execution.json` runtime ID, not the current installation state. `paper_reader.py` is internal/source-test only.

## Define the work

Before translation begins, assign one `gpt-6-luna` worker at high reasoning effort to map the rendered pages and extraction into corrected reading order, sentence boundaries, semantic ownership chunks and shared terminology/notation context. This worker establishes a paper glossary from the title, abstract and relevant sections, or a textbook symbol/definition context from the selected problems, examples and proofs. It should not take ownership of the translation chunks. The main agent uses that map to create the immutable worklist.

Divide the source into coherent paragraph groups or complete examples, proofs and exercise steps. Aim for about 200 lexical word cards per chunk as a soft checkpoint, not a hard limit. Do not cut a sentence or calculation across chunks. Keep selected page boundaries on complete sentences and steps. Source reading, translation, formula-crop mapping and source checks belong to the Luna-high authoring lanes; the main agent owns preparation code use, worklist integration, merge and cross-chunk consistency.

Each chunk identifies `owned_tokens` and may include nearby `context_tokens`. Context gives the writer enough surrounding text to resolve terms, pronouns and notation; it does not transfer ownership or authorize translating outside the selected scope. Build the chunk list in source reading order and keep the list fixed while work is underway.

## Worklist contract

Create a plan JSON with the chosen chunk IDs and token assignments:

```json
{
  "chunks": [
    {
      "id": "chunk-01",
      "owned_tokens": ["p1t0", "p1t1"],
      "context_tokens": ["p1t2"]
    }
  ]
}
```

Generate the immutable worklist and validate its coverage against the prepared source:

```
<runtime_path> <source_snapshot>/scripts/workflow.py create-worklist --work WORK --plan PLAN.json --output WORKLIST.json
<runtime_path> <source_snapshot>/scripts/workflow.py validate-plan --work WORK --worklist WORKLIST.json
```

The worklist records version 1, source identity (`source_sha256`, `scope`, `prepared_sha256`) and the ordered chunks. The chunk array is corrected logical reading order; validation constrains page order but does not infer or sort sentence order inside a page. Do not edit the worklist after assigning chunks. Progress is derived from the fragments on disk, not stored by mutating the worklist. If the source or selected scope changes, create and validate a new plan.

Each author saves a non-overlapping fragment as v2 annotation JSON and adds this `_chunk` object:

```json
"_chunk": {
  "worklist_sha256": "...",
  "chunk_id": "chunk-01",
  "owned_tokens": ["p1t0", "p1t1"],
  "context_tokens": ["p1t2"]
}
```

The hash must match the exact immutable worklist. Fragment token ownership must match the assigned chunk. Complete translations for context-only tokens do not count toward chunk coverage and should not be added to the final result.

## Track and merge

Store all fragment JSON files in one directory and inspect derived progress:

```
<runtime_path> <source_snapshot>/scripts/workflow.py status --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/
```

After all chunks are present, merge in worklist order and run full source validation on the merged annotations:

```
<runtime_path> <source_snapshot>/scripts/workflow.py merge --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/ --output annotations.json
scripts/run.py validate --work WORK --annotations annotations.json
```

Do not build from fragments or from a partial merge. Fix ownership, boundary and consistency problems in the fragments, then repeat the merge. A complete worklist is a bookkeeping result; it does not prove language accuracy or reading-order correctness.

## Writer and reviewer roles

Reuse up to six Luna-high authoring lanes across the chunks; do not create a new worker for each chunk. Prefer `gpt-6-luna` at high reasoning effort; use `gpt-5.6-luna` at high effort if the preferred model is unavailable. Give each writer the shared source-linked glossary/notation and only its owned chunk plus relevant surrounding context. For papers, include the title, abstract and relevant section. For textbooks, include definitions, notation and the complete surrounding problem, example or proof. Inspect material outside the selected scope on demand for a specific ambiguity; never treat it as part of the deliverable.

The main agent integrates the fragments, checks terminology and notation across chunk boundaries, and independently checks all selected content against the source for meaning and coverage. A separate reviewer should target material risks and sample representative content for meaning, math, omissions, ownership and consistency; do not duplicate every sentence and word-card check.
