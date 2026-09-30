import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
const path = new URL("../assets/reader/reader.js", import.meta.url);
const api = fs.existsSync(path)
  ? createRequire(import.meta.url)(fileURLToPath(path))
  : {};
const data = {
  version: 3,
  pages: [
    { tokens: ["a", "c", "b"].map((id) => ({ id, text: id })) },
    { tokens: ["d", "e", "f"].map((id) => ({ id, text: id })) },
  ],
  sentences: [
    {
      id: "s1",
      tokens: ["a", "b", "c", "d"],
      natural: [{type:"text", text:"문장 하나"}], words: {a:{base:"기본",meaning:"문맥"}},
      joins: [],
    },
    { id: "s2", tokens: ["e", "f"], natural: [{type:"text",text:"문장 둘"}], joins: [] },
  ],
};
test('live original-only selection reports a region without inventing sentence boundaries', () => {
  const initial = {...data, sentences: [], live: {revision: 0}};
  const results = api.resolveSelection(api.createIndex(initial), 'c', 'e');
  assert.equal(results.length, 1);
  assert.equal(results[0].pending, true);
  assert.deepEqual(results[0].tokenIds, ['c', 'b', 'd', 'e']);
  assert.deepEqual(results[0].sentence.tokens, results[0].tokenIds);
});
test('live mixed selection combines a complete corrected sentence with a pending region', () => {
  const partial = {...data, sentences: [data.sentences[0]], live: {revision: 1}};
  const results = api.resolveSelection(api.createIndex(partial), 'c', 'e');
  assert.equal(results.length, 2);
  assert.equal(results[0].sentence.id, 's1');
  assert.deepEqual(results[0].tokenIds, ['a', 'b', 'c', 'd']);
  assert.equal(results[1].pending, true);
  assert.deepEqual(results[1].tokenIds, ['e']);
});
test('live delta retains untouched sentences and reset removes old session content', () => {
  assert.equal(typeof api.applyLiveUpdate, 'function');
  const initial = {...data, live: {epoch: 'old', revision: 1}};
  const changed = {...data.sentences[0], natural: [{type:'text', text:'수정된 문장'}]};
  const delta = api.applyLiveUpdate(initial, {epoch:'old', revision:2, reset:false,
    sentences:[changed], removed_sentence_ids:[], order:['s1','s2'], math:{}});
  assert.equal(delta.sentences[1], data.sentences[1]);
  assert.equal(delta.pages, data.pages);
  assert.equal(delta.sentences[0].natural[0].text, '수정된 문장');
  const reset = api.applyLiveUpdate(delta, {epoch:'new', revision:1, reset:true,
    sentences:[], removed_sentence_ids:[], order:[], math:{}});
  assert.deepEqual(reset.sentences, []);
  assert.equal(reset.live.epoch, 'new');
});
test("corrected reading order and reverse drag resolve identically", () => {
  assert.equal(typeof api.createIndex, "function");
  const index = api.createIndex(data);
  const f = api.resolveSelection(index, "b", "e");
  const r = api.resolveSelection(index, "e", "b");
  assert.deepEqual(
    f.map((x) => x.sentence.id),
    ["s1", "s2"],
  );
  assert.deepEqual(r, f);
  assert.deepEqual(
    f.flatMap((x) => x.tokenIds),
    ["a", "b", "c", "d", "e", "f"],
  );
});
test("a partial sentence selects its stored whole translation", () => {
  assert.equal(typeof api.createIndex, "function");
  const result = api.resolveSelection(api.createIndex(data), "c", "c");
  assert.equal(result[0].sentence, data.sentences[0]);
  assert.deepEqual(result[0].tokenIds, ["a", "b", "c", "d"]);
  assert.deepEqual(api.translationParts(result[0].sentence), data.sentences[0].natural);
});
test("v3 drags resolve to whole touched sentences in either direction", () => {
  const scoped = { ...data, version: 3 };
  const index = api.createIndex(scoped);
  const within = api.resolveSelection(index, "c", "c");
  assert.equal(within[0].sentence.id, "s1");
  assert.deepEqual(within[0].tokenIds, ["a", "b", "c", "d"]);
  const forward = api.resolveSelection(index, "c", "e");
  const reverse = api.resolveSelection(index, "e", "c");
  assert.deepEqual(reverse, forward);
  assert.deepEqual(forward.map((x) => x.sentence.id), ["s1", "s2"]);
  assert.deepEqual(forward.flatMap((x) => x.tokenIds), ["a", "b", "c", "d", "e", "f"]);
});
test("unknown excluded token cannot create a selection", () => {
  assert.equal(typeof api.createIndex, "function");
  assert.deepEqual(
    api.resolveSelection(api.createIndex(data), "excluded", "a"),
    [],
  );
});
test("popup source preserves prepared line-break join and source identity", () => {
  assert.equal(typeof api.sourceParts, "function");
  const s = {
    tokens: ["a", "b", "c"],
    joins: [{ start: 0, end: 2, text: "models" }],
  };
  const index = {
    tokens: new Map([
      ["a", { text: "mod-" }],
      ["b", { text: "els" }],
      ["c", { text: "work." }],
    ]),
  };
  assert.deepEqual(api.sourceParts(index, s, 0, 3), [
    { text: "models", tokenIds: ["a", "b"] },
    { text: "work.", tokenIds: ["c"] },
  ]);
});

test("v3 word data needs only basic and contextual meanings", () => {
  assert.deepEqual(data.sentences[0].words.a, {base:"기본", meaning:"문맥"});
});

test("selection diff only mutates entering and leaving token IDs", () => {
  assert.equal(typeof api.selectionDiff, "function");
  const previous = new Set(["a", "b", "c"]);
  const next = new Set(["b", "c", "d"]);
  assert.deepEqual(api.selectionDiff(previous, next), {
    added: ["d"],
    removed: ["a"],
  });
  assert.deepEqual(api.selectionDiff(next, next), { added: [], removed: [] });
  assert.deepEqual(api.selectionDiff(next, new Set()), {
    added: [],
    removed: ["b", "c", "d"],
  });
  assert.deepEqual([...previous], ["a", "b", "c"]);
});

test("book and PDF page lookup retain distinct numbering", () => {
  const pages = [
    { number: 1, printed_label: "표지" },
    { number: 12, printed_label: "1" },
    { number: 13, printed_label: "2" },
  ];
  assert.equal(api.findPage(pages, "pdf", "12"), pages[1]);
  assert.equal(api.findPage(pages, "book", "1"), pages[1]);
  assert.equal(api.findPage(pages, "book", "2"), pages[2]);
  assert.equal(api.findPage(pages, "pdf", "2"), null);
  assert.equal(api.findPage(pages, "book", "3"), null);
});

test("TOC targets original PDF page and an empty TOC stays empty", () => {
  const pages = [{ number: 1 }, { number: 2 }];
  assert.equal(api.findPage(pages, "pdf", "2"), pages[1]);
  assert.equal(api.findPage(pages, "book", "2"), null);
  assert.deepEqual(api.tableOfContents({ pages }), []);
  assert.deepEqual(
    api.tableOfContents({ pages, toc: [{ title: "Chapter 1", page: 2 }] }),
    [{ title: "Chapter 1", page: 2 }],
  );
});

test("math tokens resolve atomically from either end of a formula", () => {
  const mathData = {
    version: 3,
    pages: [{ tokens: ["a", "m1", "m2", "b"].map((id) => ({ id, text: id })) }],
    sentences: [{ id: "s", tokens: ["a", "m1", "m2", "b"], natural:[{type:"text",text:"값 "},{type:"math",ref:"eq"}] }],
    math: { eq: { tokens: ["m1", "m2"], regions: [{ page: 1, box: [1, 2, 3, 4] }] } },
  };
  const index = api.createIndex(mathData);
  assert.deepEqual(api.resolveSelection(index, "m1", "m1")[0].tokenIds, ["m1", "m2"]);
  assert.deepEqual(api.resolveSelection(index, "m2", "m2")[0].tokenIds, ["m1", "m2"]);
  assert.deepEqual(api.translationParts(api.resolveSelection(index, "m1", "m2")[0]), [{ type: "math", ref: "eq" }]);
  assert.deepEqual(api.resolveSelection(index, "a", "m1")[0].tokenIds, ["a", "m1", "m2", "b"]);
  assert.equal(api.mathForToken(index, "m2"), "eq");
  assert.deepEqual(api.sourceParts(index, mathData.sentences[0], 1, 3), [
    { type: "math", ref: "eq", tokenIds: ["m1", "m2"] },
  ]);
});

test("v3 translation parts retain exact math reference", () => {
  const s = {natural:[{type:"text",text:"값은 "},{type:"math",ref:"eq"}]};
  assert.deepEqual(api.translationParts(s), s.natural);
});

test("a page-spanning math crop targets a token on its own PDF page", () => {
  const item = { tokens: ["p219t8", "p220t1"] };
  assert.equal(api.mathHitToken(item, { tokens: [{ id: "p219t8" }] }), "p219t8");
  assert.equal(api.mathHitToken(item, { tokens: [{ id: "p220t1" }] }), "p220t1");
});
