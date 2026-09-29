import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
const path = new URL("../assets/reader/reader.js", import.meta.url);
const api = fs.existsSync(path)
  ? createRequire(import.meta.url)(fileURLToPath(path))
  : {};
const unit = (id, start, end) => ({
  id,
  start,
  end,
  literal: [{ start, end, text: id + " 직역" }],
  natural: id + " 자연",
});
const data = {
  version: 2,
  pages: [
    { tokens: ["a", "c", "b"].map((id) => ({ id, text: id })) },
    { tokens: ["d", "e", "f"].map((id) => ({ id, text: id })) },
  ],
  sentences: [
    {
      id: "s1",
      tokens: ["a", "b", "c", "d"],
      units: [unit("whole", 0, 4), unit("ab", 0, 2), unit("cd", 2, 4)],
      joins: [],
    },
    { id: "s2", tokens: ["e", "f"], units: [unit("ef", 0, 2)], joins: [] },
  ],
  lexicon: {},
};
test("corrected reading order and reverse drag resolve identically", () => {
  assert.equal(typeof api.createIndex, "function");
  const index = api.createIndex(data);
  const f = api.resolveSelection(index, "b", "e");
  const r = api.resolveSelection(index, "e", "b");
  assert.deepEqual(
    f.map((x) => x.unit.id),
    ["whole", "ef"],
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
  assert.equal(result[0].unit, data.sentences[0].units[0]);
  assert.deepEqual(result[0].tokenIds, ["a", "b", "c", "d"]);
  assert.equal(api.translation(result[0].unit, false), "whole 직역");
  assert.equal(api.translation(result[0].unit, true), "whole 자연");
});
test("v2 drags resolve to whole touched sentences in either direction", () => {
  const scoped = { ...data, version: 2 };
  const index = api.createIndex(scoped);
  const within = api.resolveSelection(index, "c", "c");
  assert.equal(within[0].unit.id, "whole");
  assert.deepEqual(within[0].tokenIds, ["a", "b", "c", "d"]);
  const forward = api.resolveSelection(index, "c", "e");
  const reverse = api.resolveSelection(index, "e", "c");
  assert.deepEqual(reverse, forward);
  assert.deepEqual(forward.map((x) => x.unit.id), ["whole", "ef"]);
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

test("literal chunks keep prepared source order and delimiters", () => {
  const u = {
    literal: [{ text: "첫 절" }, { text: "둘째 절" }],
    natural: "유창한 문장",
  };
  assert.equal(api.translation(u, false), "첫 절 / 둘째 절");
  assert.equal(api.translation(u, true), "유창한 문장");
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
    version: 2,
    pages: [{ tokens: ["a", "m1", "m2", "b"].map((id) => ({ id, text: id })) }],
    sentences: [{ id: "s", tokens: ["a", "m1", "m2", "b"], units: [unit("whole", 0, 4)] }],
    math: { eq: { tokens: ["m1", "m2"], regions: [{ page: 1, box: [1, 2, 3, 4] }] } },
  };
  const index = api.createIndex(mathData);
  assert.deepEqual(api.resolveSelection(index, "m1", "m1")[0].tokenIds, ["m1", "m2"]);
  assert.deepEqual(api.resolveSelection(index, "m2", "m2")[0].tokenIds, ["m1", "m2"]);
  assert.deepEqual(api.translationParts(api.resolveSelection(index, "m1", "m2")[0].unit, true), [{ type: "math", ref: "eq" }]);
  assert.deepEqual(api.resolveSelection(index, "a", "m1")[0].tokenIds, ["a", "m1", "m2", "b"]);
  assert.equal(api.mathForToken(index, "m2"), "eq");
  assert.deepEqual(api.sourceParts(index, mathData.sentences[0], 1, 3), [
    { type: "math", ref: "eq", tokenIds: ["m1", "m2"] },
  ]);
});

test("v2 translation parts retain math reference in both modes", () => {
  const u = {
    literal: [{ parts: [{ type: "text", text: "값은 " }, { type: "math", ref: "eq" }] }],
    natural: [{ type: "text", text: "값은 " }, { type: "math", ref: "eq" }],
  };
  assert.deepEqual(api.translationParts(u, false), u.literal[0].parts);
  assert.deepEqual(api.translationParts(u, true), u.natural);
});

test("a page-spanning math crop targets a token on its own PDF page", () => {
  const item = { tokens: ["p219t8", "p220t1"] };
  assert.equal(api.mathHitToken(item, { tokens: [{ id: "p219t8" }] }), "p219t8");
  assert.equal(api.mathHitToken(item, { tokens: [{ id: "p220t1" }] }), "p220t1");
});
