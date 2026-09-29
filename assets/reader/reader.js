(function () {
  "use strict";
  function createIndex(data) {
    const tokens = new Map(
      data.pages.flatMap((p) => p.tokens.map((t) => [t.id, t])),
    );
    const order = [],
      positions = new Map();
    data.sentences.forEach((sentence) =>
      sentence.tokens.forEach((id, offset) => {
        positions.set(id, { rank: order.length, sentence, offset });
        order.push(id);
      }),
    );
    const mathByToken = new Map();
    for (const [ref, item] of Object.entries(data.math || {}))
      for (const id of item.tokens) mathByToken.set(id, ref);
    return { tokens, order, positions, sentences: data.sentences, mathByToken, math: data.math || {} };
  }
  function mathForToken(index, id) {
    return index.mathByToken?.get(id);
  }
  function mathHitToken(item, page) {
    const pageIds = new Set(page.tokens.map((token) => token.id));
    return item.tokens.find((id) => pageIds.has(id));
  }
  function resolveSelection(index, first, last) {
    const a = index.positions.get(first),
      b = index.positions.get(last);
    if (!a || !b) return [];
    const firstMath = mathForToken(index, first);
    if (firstMath && firstMath === mathForToken(index, last)) {
      const ids = index.math[firstMath].tokens;
      const position = index.positions.get(ids[0]);
      const start = position.offset;
      const end = start + ids.length;
      const part = { type: "math", ref: firstMath };
      return [{
        sentence: position.sentence,
        unit: { start, end, literal: [{ start, end, parts: [part] }], natural: [part] },
        tokenIds: ids,
      }];
    }
    let lo = Math.min(a.rank, b.rank),
      hi = Math.max(a.rank, b.rank);
    for (const id of [first, last]) {
      const ref = mathForToken(index, id);
      if (ref) {
        const ranks = index.math[ref].tokens.map((token) => index.positions.get(token).rank);
        lo = Math.min(lo, ...ranks);
        hi = Math.max(hi, ...ranks);
      }
    }
    const touched = new Map();
    index.order.slice(lo, hi + 1).forEach((id) => {
      const p = index.positions.get(id);
      const range = touched.get(p.sentence) || [p.offset, p.offset + 1];
      range[0] = Math.min(range[0], p.offset);
      range[1] = Math.max(range[1], p.offset + 1);
      touched.set(p.sentence, range);
    });
    return Array.from(touched, ([sentence, [start, end]]) => {
      const unit = sentence.units.find((u) => u.start === 0 && u.end === sentence.tokens.length);
      return {
        sentence,
        unit,
        tokenIds: sentence.tokens.slice(unit.start, unit.end),
      };
    });
  }
  function translation(unit, natural) {
    return natural ? unit.natural : unit.literal.map((c) => c.text).join(" / ");
  }
  function translationParts(unit, natural) {
    if (natural) return typeof unit.natural === "string" ? [{ type: "text", text: unit.natural }] : unit.natural;
    return unit.literal.flatMap((chunk, i) => [
      ...(i ? [{ type: "text", text: " / " }] : []),
      ...(chunk.parts || [{ type: "text", text: chunk.text }]),
    ]);
  }
  function sourceParts(index, sentence, start, end) {
    const parts = [];
    for (let i = start; i < end; ) {
      const ref = mathForToken(index, sentence.tokens[i]);
      if (ref) {
        const ids = index.math[ref].tokens;
        if (ids[0] === sentence.tokens[i]) parts.push({ type: "math", ref, tokenIds: ids });
        i += 1;
        continue;
      }
      const join = (sentence.joins || []).find(
        (j) => j.start === i && j.end <= end,
      );
      const next = join ? join.end : i + 1;
      parts.push({
        text: join ? join.text : index.tokens.get(sentence.tokens[i]).text,
        tokenIds: sentence.tokens.slice(i, next),
      });
      i = next;
    }
    return parts;
  }
  function selectionDiff(previous, next) {
    return {
      added: [...next].filter((id) => !previous.has(id)),
      removed: [...previous].filter((id) => !next.has(id)),
    };
  }
  function findPage(pages, kind, value) {
    const query = String(value).trim();
    if (!query) return null;
    return pages.find((page) =>
      kind === "pdf"
        ? /^\d+$/.test(query) && page.number === Number(query)
        : kind === "book" && page.printed_label === query,
    ) || null;
  }
  function tableOfContents(data) {
    return Array.isArray(data.toc) ? data.toc : [];
  }
  const api = {
    createIndex,
    resolveSelection,
    translation,
    sourceParts,
    selectionDiff,
    mathForToken,
    mathHitToken,
    translationParts,
    findPage,
    tableOfContents,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;
  const data = JSON.parse(document.getElementById("reader-data").textContent),
    index = createIndex(data);
  const pages = document.getElementById("pages"),
    parent = document.getElementById("sentence-popup"),
    child = document.getElementById("word-popup");
  const elements = new Map(),
    pageElements = [],
    translations = [];
  let selected = [],
    selectedIds = new Set(),
    natural = false,
    zoom = 1,
    fit = true,
    drag = null,
    suppressClick = false,
    frame = 0,
    anchor = { x: 20, y: 80 };
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function clampPopup(node, x, y) {
    node.style.left = "8px";
    node.style.top = "8px";
    const r = node.getBoundingClientRect();
    node.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
    node.style.top =
      Math.max(8, Math.min(y + 12, innerHeight - r.height - 8)) + "px";
  }
  function highlight(results) {
    const nextIds = new Set(results.flatMap((result) => result.tokenIds));
    const { added, removed } = selectionDiff(selectedIds, nextIds);
    for (const id of removed) elements.get(id)?.classList.remove("selected");
    for (const id of added) elements.get(id)?.classList.add("selected");
    selected = results;
    selectedIds = nextIds;
  }
  function closeChild() {
    child.hidden = true;
    child.replaceChildren();
  }
  function closeAll() {
    closeChild();
    parent.hidden = true;
    highlight([]);
  }
  function closeButton(action) {
    const b = el("button", "close", "×");
    b.type = "button";
    b.setAttribute("aria-label", "닫기");
    b.onclick = action;
    return b;
  }
  function showWord(sentence, id, event) {
    const word = sentence.words?.[id];
    if (!word) return;
    const entry = data.lexicon[word.entry];
    child.replaceChildren(closeButton(closeChild));
    child.append(
      el("h2", "", entry.lemma),
      el("p", "word-base", entry.pos + " · " + entry.gloss),
    );
    for (const [label, value] of [
      ["문맥 뜻", word.meaning],
      ["문장 역할", word.role],
      ["표현", word.expression],
    ])
      if (value) {
        const p = el("p");
        p.append(el("strong", "", label + " "), document.createTextNode(value));
        child.append(p);
      }
    child.hidden = false;
    clampPopup(child, event.clientX, event.clientY);
  }
  function mathCrop(ref) {
    const wrap = el("span", "math-crops");
    wrap.setAttribute("aria-label", "원문 수식");
    for (const region of index.math[ref].regions) {
      const page = data.pages.find((item) => item.number === region.page);
      if (!page) continue;
      const [x, y, width, height] = region.box;
      const crop = el("span", "math-crop"), img = el("img");
      crop.style.width = width + "px";
      crop.style.height = height + "px";
      img.src = page.image;
      img.alt = "";
      img.width = page.width;
      img.height = page.height;
      img.style.left = -x + "px";
      img.style.top = -y + "px";
      crop.append(img);
      wrap.append(crop);
    }
    return wrap;
  }
  function appendTranslation(node, unit) {
    node.replaceChildren();
    for (const part of translationParts(unit, natural))
      node.append(part.type === "math" ? mathCrop(part.ref) : document.createTextNode(part.text));
  }
  function showResults(results, point) {
    if (!results.length) return;
    closeChild();
    highlight(results);
    anchor = point;
    translations.length = 0;
    parent.replaceChildren(closeButton(closeAll));
    const toolbar = el("div", "translation-mode");
    toolbar.append(el("span", "", "번역"));
    const toggle = el(
      "button",
      "mode-toggle",
      natural ? "자연스러운 번역" : "직역",
    );
    toggle.type = "button";
    toggle.setAttribute("aria-pressed", String(natural));
    toggle.onclick = () => {
      natural = !natural;
      toggle.textContent = natural ? "자연스러운 번역" : "직역";
      toggle.setAttribute("aria-pressed", String(natural));
      translations.forEach(
        ([node, unit]) => appendTranslation(node, unit),
      );
      clampPopup(parent, anchor.x, anchor.y);
    };
    toolbar.append(toggle);
    parent.append(toolbar);
    for (const { sentence, unit } of results) {
      const section = el("section", "passage"),
        english = el("p", "english");
      sourceParts(index, sentence, unit.start, unit.end).forEach((part, i) => {
        if (i) english.append(document.createTextNode(" "));
        if (part.type === "math") {
          english.append(mathCrop(part.ref));
          return;
        }
        const id = part.tokenIds.find((id) => sentence.words?.[id]);
        const word = el(
          id ? "button" : "span",
          id ? "english-word" : "",
          part.text,
        );
        if (id) {
          word.type = "button";
          word.onclick = (event) => showWord(sentence, id, event);
        }
        english.append(word);
      });
      const korean = el("p", "korean");
      appendTranslation(korean, unit);
      translations.push([korean, unit]);
      section.append(english, korean);
      parent.append(section);
    }
    parent.hidden = false;
    clampPopup(parent, point.x, point.y);
  }
  const observer =
    "IntersectionObserver" in window
      ? new IntersectionObserver(
          (entries) =>
            entries.forEach((entry) => {
              if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.image;
                delete img.dataset.image;
                observer.unobserve(img);
              }
            }),
          { rootMargin: "1000px" },
        )
      : null;
  for (const page of data.pages) {
    const shell = el("section", "page");
    shell.setAttribute("aria-label", "페이지 " + page.number);
    shell.dataset.page = page.number;
    if (page.printed_label) shell.setAttribute("aria-label", "PDF 페이지 " + page.number + ", 책 페이지 " + page.printed_label);
    const img = el("img", "page-image");
    img.alt = "";
    img.draggable = false;
    img.width = page.width;
    img.height = page.height;
    img.dataset.image = page.image;
    const layer = el("div", "text-layer");
    for (const token of page.tokens) {
      if (!index.positions.has(token.id)) continue;
      const word = el("span", "source-word", token.text);
      word.dataset.token = token.id;
      word.style.left = (token.box[0] / page.width) * 100 + "%";
      word.style.top = (token.box[1] / page.height) * 100 + "%";
      word.style.width = (token.box[2] / page.width) * 100 + "%";
      word.style.height = (token.box[3] / page.height) * 100 + "%";
      word.setAttribute("aria-label", token.text);
      elements.set(token.id, word);
      layer.append(word);
    }
    for (const item of Object.values(index.math)) {
      for (const region of item.regions) {
        if (region.page !== page.number) continue;
        const hit = el("span", "math-hit");
        hit.dataset.token = mathHitToken(item, page);
        hit.setAttribute("aria-label", "원문 수식");
        hit.style.left = (region.box[0] / page.width) * 100 + "%";
        hit.style.top = (region.box[1] / page.height) * 100 + "%";
        hit.style.width = (region.box[2] / page.width) * 100 + "%";
        hit.style.height = (region.box[3] / page.height) * 100 + "%";
        layer.append(hit);
      }
    }
    shell.append(img, layer);
    pages.append(shell);
    pageElements.push([shell, page]);
    if (observer) observer.observe(img);
    else img.src = page.image;
  }
  if (data.version === 2) {
    const form = document.getElementById("page-jump"),
      kind = document.getElementById("page-kind"),
      query = document.getElementById("page-query"),
      status = document.getElementById("page-status"),
      toc = tableOfContents(data),
      tocToggle = document.getElementById("toc-toggle"),
      tocPanel = document.getElementById("toc-panel");
    form.hidden = false;
    if (!data.pages.some((page) => page.printed_label)) kind.value = "pdf";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const page = findPage(data.pages, kind.value, query.value);
      status.textContent = page ? "" : "해당 페이지가 없습니다";
      if (page) pageElements.find(([node, item]) => item === page)[0].scrollIntoView({ block: "start" });
    });
    if (toc.length) {
      tocToggle.hidden = false;
      tocToggle.onclick = () => {
        tocPanel.hidden = !tocPanel.hidden;
        tocToggle.setAttribute("aria-expanded", String(!tocPanel.hidden));
      };
      for (const entry of toc) {
        const button = el("button", "toc-entry", entry.title);
        button.type = "button";
        button.onclick = () => {
          const page = findPage(data.pages, "pdf", entry.page);
          if (page) pageElements.find(([node, item]) => item === page)[0].scrollIntoView({ block: "start" });
          tocPanel.hidden = true;
          tocToggle.setAttribute("aria-expanded", "false");
        };
        tocPanel.append(button);
      }
    }
  }
  function sizePages() {
    const available = Math.max(240, document.documentElement.clientWidth - 32),
      maxWidth = Math.max(...data.pages.map((p) => p.width));
    const scale = fit ? available / maxWidth : zoom;
    pageElements.forEach(([node, page]) => {
      node.style.width = page.width * scale + "px";
      node.style.height = page.height * scale + "px";
    });
    document.getElementById("zoom-label").textContent =
      Math.round(scale * 100) + "%";
    zoom = scale;
    if (!parent.hidden) clampPopup(parent, anchor.x, anchor.y);
    if (!child.hidden)
      clampPopup(
        child,
        parseFloat(child.style.left),
        parseFloat(child.style.top) - 12,
      );
  }
  document.getElementById("zoom-in").onclick = () => {
    fit = false;
    zoom = Math.min(4, zoom * 1.2);
    sizePages();
  };
  document.getElementById("zoom-out").onclick = () => {
    fit = false;
    zoom = Math.max(0.25, zoom / 1.2);
    sizePages();
  };
  document.getElementById("fit").onclick = () => {
    fit = true;
    sizePages();
  };
  window.addEventListener("resize", sizePages);
  sizePages();
  function tokenAt(x, y) {
    return document.elementFromPoint(x, y)?.closest("[data-token]")?.dataset
      .token;
  }
  function updateDrag(x, y) {
    if (!drag) return;
    drag.x = x;
    drag.y = y;
    const id = tokenAt(x, y);
    if (id) drag.last = id;
    if (Math.hypot(x - drag.startX, y - drag.startY) > 4) drag.moved = true;
    if (drag.moved && drag.last !== drag.renderedLast) {
      highlight(resolveSelection(index, drag.first, drag.last));
      drag.renderedLast = drag.last;
    }
  }
  function autoScroll() {
    if (!drag) return;
    const dy = drag.y < 70 ? -18 : drag.y > innerHeight - 45 ? 18 : 0;
    if (dy) {
      window.scrollBy(0, dy);
      updateDrag(drag.x, drag.y);
    }
    frame = requestAnimationFrame(autoScroll);
  }
  pages.addEventListener("pointerdown", (event) => {
    const id = event.target.closest("[data-token]")?.dataset.token;
    if (!id || event.button !== 0) return;
    event.preventDefault();
    closeChild();
    parent.hidden = true;
    drag = {
      first: id,
      last: id,
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      moved: false,
    };
    frame = requestAnimationFrame(autoScroll);
  });
  window.addEventListener("pointermove", (event) => {
    if (drag) {
      event.preventDefault();
      updateDrag(event.clientX, event.clientY);
    }
  });
  window.addEventListener("pointerup", (event) => {
    if (!drag) return;
    cancelAnimationFrame(frame);
    updateDrag(event.clientX, event.clientY);
    const current = drag;
    drag = null;
    suppressClick = current.moved;
    const p = index.positions.get(current.first);
    const results = current.moved
      ? resolveSelection(index, current.first, current.last)
      : mathForToken(index, current.first)
        ? resolveSelection(index, current.first, current.first)
        : resolveSelection(index, p.sentence.tokens[0], p.sentence.tokens.at(-1));
    showResults(results, { x: event.clientX, y: event.clientY });
  });
  window.addEventListener("pointercancel", () => {
    drag = null;
    cancelAnimationFrame(frame);
  });
  pages.addEventListener(
    "click",
    (event) => {
      if (suppressClick) {
        event.preventDefault();
        event.stopPropagation();
        suppressClick = false;
      }
    },
    true,
  );
  document.addEventListener("pointerdown", (event) => {
    if (
      !parent.contains(event.target) &&
      !child.contains(event.target) &&
      !event.target.closest("[data-token]")
    )
      closeAll();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!child.hidden) closeChild();
      else closeAll();
    }
  });
  document.addEventListener("copy", (event) => {
    if (selected.length && !window.getSelection().toString()) {
      event.clipboardData.setData(
        "text/plain",
      selected
          .map((r) =>
            sourceParts(index, r.sentence, r.unit.start, r.unit.end)
              .map((p) => p.type === "math" ? index.math[p.ref].tokens.map((id) => index.tokens.get(id).text).join(" ") : p.text)
              .join(" "),
          )
          .join("\n"),
      );
      event.preventDefault();
    }
  });
  document.getElementById("document-title").textContent = data.title;
})();
