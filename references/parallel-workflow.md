# Parallel authoring

Use parallel authoring only when the selected document has enough coherent work to benefit from multiple writers. The output still needs one integration owner; splitting by page or creating one worker for every section makes context and terminology drift more likely.

Prepare, validate and build with the installed `scripts/run.py`; it checks for stable updates only for a new work folder and pins that work to one release. The `workflow.py` helper commands below are the only direct script calls in this guide. Invoke them with the private interpreter and source snapshot matched to the processing runtime ID in `migration.json` for migrated work, otherwise `execution.json`, not the current installation state. `paper_reader.py` is internal/source-test only.

## Define the work

Divide the source into coherent paragraph groups and complete examples, proofs or exercise steps. Writers read the original pages, determine sentence order and map formulas while authoring; do not require a separate structure model before every job. The main agent creates a fixed token-ownership worklist and a small source-linked terminology/notation note. Provide a common title and consistent printed page labels so authors do not invent conflicting metadata. Do not split a sentence or calculation between owners. Use gpt-6.1-sol low, or gpt-6-luna high if unavailable. The main agent owns integration.

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

Each author saves a non-overlapping fragment as v3 annotation JSON and adds this `_chunk` object:

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

### Open early and publish sentences

Immediately after preparation, start the installed runner as a continuing process:

```
scripts/run.py serve --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/
```

Open the printed loopback URL in Codex. It initially shows original pages and selectable pending source; WORKLIST.json can arrive later. The server remains running while authors work. It serves prepared data only, never invokes a model on a click, and does not expose arbitrary work files.

Assign chunks in source order while preserving parallel authoring. Each author creates a cumulative v3 fragment **outside FRAGMENTS/**, includes the exact `_chunk` metadata, and adds one complete sentence at a time with all its word cards and math references/regions. Use chunk-qualified sentence and formula IDs. Check each sentence's source, meaning, formula placement and boundary before publication, then immediately run:

```
scripts/run.py publish --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/ --chunk CHUNK_ID --input DRAFT.json
```

Publish the checked sentence before authoring the next sentence. Do not prewrite the entire chunk in a script and then replay its publications in a batch. Do not start a new model invocation per sentence. The command validates the cumulative result, atomically replaces only that owner's fragment, and prints its saved path, changed flag and chunk-complete status. Do not place draft, backup or unrelated JSON files in FRAGMENTS/. A repeated unchanged publication does not create another update. Corrections replace the affected entry in the cumulative draft and retain previously assigned source tokens.

Set `review.language` and `review.layout` true with concrete notes after checking the currently published sentences. Keep `review.coverage` false while any owned token remains pending; set it true and republish when the entire chunk, including permitted exclusions, is accounted for. Never mark unfinished sentences reviewed or publish bare translations before their cards and formulas are ready. In particular, inspect article a versus variable a, clauses after display math, and duplicated formula crops.

The live reader checks for changes about once per second and keeps scroll, zoom, selection and popups. It defers changes during a drag. The status shows checked sentence count, processed/total source tokens, connection and last-update time; it does not claim an ETA or prove that an author is currently running. If connection stops, keep the work and fragments and restart the same `serve` command. The last good results survive invalid inputs and server restarts. Do not auto-remove a publication lock left by an interrupted process; confirm the publisher has stopped before removing that lock.

### Final coverage and offline HTML

Store all fragment JSON files in one directory and inspect derived progress:

```
<runtime_path> <source_snapshot>/scripts/workflow.py status --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/
```

After all chunks are present, merge in worklist order and run full source validation on the merged annotations:

```
<runtime_path> <source_snapshot>/scripts/workflow.py merge --work WORK --worklist WORKLIST.json --fragments FRAGMENTS/ --output annotations.json
scripts/run.py validate --work WORK --annotations annotations.json
```

The live server automatically runs the existing merge and full validation/build when all chunks are complete and actually reviewed. It writes WORK/annotations.json and WORK/reader.html and exposes the final file's path and download link without leaving the current page. Do not generate intermediate standalone HTML files. The commands above remain available for diagnosis or a requested alternative output path; avoid repeating unchanged full checks.

Do not create final HTML from partial coverage or a partial merge. Fix evidenced problems in the fragments and republish. A complete worklist is a bookkeeping result; it does not prove language accuracy or reading-order correctness.

## Writer and integration roles

Reuse authoring lanes for enough coherent work to justify parallelism. In Codex, use gpt-6.1-sol with low reasoning effort by default; if unavailable, use gpt-6-luna with high reasoning effort. Provide owned source plus surrounding context and the small terminology note. Each writer checks its source, meanings, formulas and boundaries during authoring, including article a versus variable a, clauses after display formulas within the same complete sentence, and duplicate formula crops. Repair evidenced defects before acceptance. There is no separate model-wide language review or shared-dictionary normalization stage. The integration owner verifies structural results and repairs only evidenced issues. Record each lane's elapsed time separately from total parallel wall time.
