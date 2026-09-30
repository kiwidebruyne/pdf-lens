(function () {
  "use strict";
  function createIndex(data) {
    const tokens = new Map(
      data.pages.flatMap((p) => p.tokens.map((t) => [t.id, t])),
    );
    const order = [],
      positions = new Map();
    const addSentence = (sentence) =>
      sentence.tokens.forEach((id, offset) => {
        positions.set(id, { rank: order.length, sentence, offset });
        order.push(id);
      });
    if (data.live) {
      const byToken = new Map(data.sentences.flatMap((s) => s.tokens.map((id) => [id, s])));
      const emitted = new Set(), excluded = new Set(data.excluded_tokens || []);
      let pending = [];
      const flush = () => {
        if (pending.length) addSentence({id: 'pending:' + pending[0], tokens: pending, pending: true, joins: []});
        pending = [];
      };
      for (const id of tokens.keys()) {
        if (excluded.has(id)) { flush(); continue; }
        const sentence = byToken.get(id);
        if (!sentence) pending.push(id);
        else {
          flush();
          if (!emitted.has(sentence.id)) addSentence(sentence);
          emitted.add(sentence.id);
        }
      }
      flush();
    } else data.sentences.forEach(addSentence);
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
      const part = { type: "math", ref: firstMath };
      return [{
        sentence: position.sentence,
        natural: [part],
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
    return Array.from(touched, ([sentence, range]) => sentence.pending ? {
      pending: true,
      sentence: {...sentence, tokens: sentence.tokens.slice(range[0], range[1])},
      tokenIds: sentence.tokens.slice(range[0], range[1]),
    } : {sentence, tokenIds: sentence.tokens});
  }
  function applyLiveUpdate(data, update) {
    const byId = new Map((update.reset ? [] : data.sentences).map((s) => [s.id, s]));
    for (const id of update.removed_sentence_ids || []) byId.delete(id);
    for (const sentence of update.sentences || []) byId.set(sentence.id, sentence);
    const sentences = update.order ? update.order.map((id) => byId.get(id)).filter(Boolean) : [...byId.values()];
    return {...data, sentences, math: update.math ?? data.math,
      excluded_tokens: update.excluded_tokens ?? data.excluded_tokens,
      title: update.title || data.title, toc: update.toc ?? data.toc,
      live: {...data.live, epoch: update.epoch, revision: update.revision, status: update.status}};
  }
  function translationParts(sentence) {
    return sentence.natural;
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
    sourceParts,
    selectionDiff,
    mathForToken,
    mathHitToken,
    translationParts,
    findPage,
    tableOfContents,
    applyLiveUpdate,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document === "undefined") return;
  let data = JSON.parse(document.getElementById("reader-data").textContent),
    index = createIndex(data);
  const pages = document.getElementById("pages"),
    parent = document.getElementById("sentence-popup"),
    child = document.getElementById("word-popup");
  const elements = new Map(),
    pageElements = [];
  let selected = [],
    selectedIds = new Set(),
    zoom = 1,
    fit = true,
    drag = null,
    suppressClick = false,
    frame = 0,
    anchor = { x: 20, y: 80 },
    selectionRange = null,
    activeWord = null,
    queuedUpdate = null,
    connected = true;
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
    activeWord = null;
    child.hidden = true;
    child.replaceChildren();
  }
  function closeAll() {
    selectionRange = null;
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
    if (!word && !sentence.pending) return;
    activeWord = {id, point: {clientX: event.clientX, clientY: event.clientY}};
    child.replaceChildren(closeButton(closeChild));
    if (!word) {
      child.append(el('h2', '', index.tokens.get(id).text), el('p', 'pending-message', pendingMessage()));
      child.hidden = false;
      clampPopup(child, event.clientX, event.clientY);
      return;
    }
    child.append(
      el("h2", "", index.tokens.get(id).text),
      el("p", "word-base", "기본 뜻 · " + word.base),
    );
    const p = el("p");
    p.append(el("strong", "", "문맥 뜻 "), document.createTextNode(word.meaning));
    child.append(p);
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
  function appendTranslation(node, sentence) {
    node.replaceChildren();
    if (sentence.pending) {
      node.append(el('span', 'pending-message', pendingMessage()));
      return;
    }
    for (const part of translationParts(sentence))
      node.append(part.type === "math" ? mathCrop(part.ref) : document.createTextNode(part.text));
  }
  function pendingMessage() {
    return connected ? '번역 준비 중입니다. 완료되면 여기에 표시됩니다.' : '연결이 끊겼습니다. 완성된 결과는 계속 읽을 수 있습니다.';
  }
  function showResults(results, point, preserve = false) {
    if (!results.length) return;
    const parentPosition = [parent.style.left, parent.style.top];
    const wordState = preserve ? activeWord : null;
    const wordPosition = [child.style.left, child.style.top];
    const parentScroll = parent.scrollTop;
    closeChild();
    highlight(results);
    anchor = point;
    parent.replaceChildren(closeButton(closeAll));
    for (const { sentence, natural, tokenIds } of results) {
      const section = el("section", "passage"),
        english = el("p", "english");
      const first = sentence.tokens.indexOf(tokenIds[0]);
      sourceParts(index, sentence, first, first + tokenIds.length).forEach((part, i) => {
        if (i) english.append(document.createTextNode(" "));
        if (part.type === "math") {
          english.append(mathCrop(part.ref));
          return;
        }
        const id = part.tokenIds.find((id) => sentence.pending || sentence.words?.[id]);
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
      appendTranslation(korean, natural ? {natural} : sentence);
      section.append(english, korean);
      parent.append(section);
    }
    parent.hidden = false;
    if (preserve) {
      [parent.style.left, parent.style.top] = parentPosition;
      parent.scrollTop = parentScroll;
    } else clampPopup(parent, point.x, point.y);
    if (wordState) {
      const result = results.find((r) => r.tokenIds.includes(wordState.id));
      if (result) {
        showWord(result.sentence, wordState.id, wordState.point);
        [child.style.left, child.style.top] = wordPosition;
      }
    }
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
  const mathSignatures = new Map(data.pages.map((page) => [page.number, mathSignature(page)]));
  function mathSignature(page) {
    return JSON.stringify(Object.entries(index.math).flatMap(([ref, item]) =>
      item.regions.filter((region) => region.page === page.number).map((region) => ({ref, region, tokens:item.tokens}))));
  }
  function refreshMathHits() {
    for (const [shell, page] of pageElements) {
      const signature = mathSignature(page);
      if (mathSignatures.get(page.number) === signature) continue;
      const layer = shell.querySelector('.text-layer');
      layer.querySelectorAll('.math-hit').forEach((node) => node.remove());
      for (const item of Object.values(index.math)) {
        for (const region of item.regions) {
          if (region.page !== page.number) continue;
          const hit = el('span', 'math-hit');
          hit.dataset.token = mathHitToken(item, page);
          hit.setAttribute('aria-label', '원문 수식');
          hit.style.left = region.box[0] / page.width * 100 + '%';
          hit.style.top = region.box[1] / page.height * 100 + '%';
          hit.style.width = region.box[2] / page.width * 100 + '%';
          hit.style.height = region.box[3] / page.height * 100 + '%';
          layer.append(hit);
        }
      }
      mathSignatures.set(page.number, signature);
    }
  }
  if (data.version === 3) {
    const form = document.getElementById("page-jump"),
      kind = document.getElementById("page-kind"),
      query = document.getElementById("page-query"),
      status = document.getElementById("page-status"),
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
    tocToggle.onclick = () => {
      tocPanel.hidden = !tocPanel.hidden;
      tocToggle.setAttribute("aria-expanded", String(!tocPanel.hidden));
    };
    refreshToc();
  }
  function refreshToc() {
    if (data.version !== 3) return;
    const toc = tableOfContents(data),
      tocToggle = document.getElementById("toc-toggle"),
      tocPanel = document.getElementById("toc-panel");
    tocToggle.hidden = !toc.length;
    tocPanel.replaceChildren();
    if (!toc.length) {
      tocPanel.hidden = true;
      tocToggle.setAttribute("aria-expanded", "false");
    }
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
    selectionRange = {first: current.first, last: current.moved ? current.last : current.first};
    const results = resolveSelection(index, selectionRange.first, selectionRange.last);
    showResults(results, { x: event.clientX, y: event.clientY });
    flushUpdate();
  });
  window.addEventListener("pointercancel", () => {
    drag = null;
    cancelAnimationFrame(frame);
    flushUpdate();
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
            sourceParts(index, r.sentence, r.sentence.tokens.indexOf(r.tokenIds[0]), r.sentence.tokens.indexOf(r.tokenIds[0]) + r.tokenIds.length)
              .map((p) => p.type === "math" ? index.math[p.ref].tokens.map((id) => index.tokens.get(id).text).join(" ") : p.text)
              .join(" "),
          )
          .join("\n"),
      );
      event.preventDefault();
    }
  });
  document.getElementById("document-title").textContent = data.title;
  function selectionContent(results, viewIndex = index) {
    const refs = new Set(results.flatMap((r) => r.tokenIds.map((id) => mathForToken(viewIndex, id))).filter(Boolean));
    const passages = results.map((r) => ({tokens:r.tokenIds, pending:!!r.pending,
      natural:r.natural || r.sentence.natural,
      words:r.tokenIds.map((id) => r.sentence.words?.[id]), joins:r.sentence.joins}));
    return JSON.stringify({passages, math:[...refs].map((ref) => viewIndex.math[ref])});
  }
  function renderLiveStatus() {
    const status = data.live.status || {};
    const node = document.getElementById('live-status');
    const when = status.last_update ? new Date(status.last_update).toLocaleTimeString() : '아직 없음';
    const phase = !connected ? '연결 끊김 · 저장된 결과 유지' : status.phase === 'complete' ? '완료' :
      status.errors?.length ? '일부 결과를 반영하지 못함 · 이전 결과 유지' : '새 결과 기다리는 중';
    node.textContent = `준비된 문장 ${status.ready_sentences || 0} · 처리 ${status.processed_tokens || 0}/${status.total_tokens || 0} · ${phase} · 마지막 반영 ${when}`;
    node.title = (status.errors || []).join('\n');
    const link = document.getElementById('final-reader');
    link.hidden = !status.final_url;
    if (status.final_url) {
      link.href = status.final_url;
      link.download = 'reader.html';
      link.title = status.final_path || '';
    }
    document.querySelectorAll('.pending-message').forEach((message) => { message.textContent = pendingMessage(); });
  }
  function applyIncoming(update) {
    const changed = update.reset || update.epoch !== data.live.epoch || update.revision !== data.live.revision;
    if (!changed) {
      data.live.status = update.status;
      renderLiveStatus();
      return;
    }
    const before = selectionContent(selected);
    const previousResults = selected, previousIndex = index;
    data = applyLiveUpdate(data, update);
    index = createIndex(data);
    for (const [id, element] of elements) element.hidden = !index.positions.has(id);
    refreshMathHits();
    refreshToc();
    if (update.page_labels) {
      for (const [shell, page] of pageElements) {
        page.printed_label = update.page_labels[String(page.number)];
        shell.setAttribute('aria-label', page.printed_label ? `PDF 페이지 ${page.number}, 책 페이지 ${page.printed_label}` : `페이지 ${page.number}`);
      }
    }
    document.getElementById('document-title').textContent = data.title;
    if (selectionRange && !parent.hidden) {
      const results = resolveSelection(index, selectionRange.first, selectionRange.last);
      if (selectionContent(results) !== before) {
        const corrected = previousResults.filter((r) => !r.pending).some((previous) => {
          const next = results.find((r) => r.tokenIds.some((id) => previous.tokenIds.includes(id)));
          return !next || selectionContent([previous], previousIndex) !== selectionContent([next]);
        });
        if (results.length) {
          showResults(results, anchor, true);
          if (corrected) parent.append(el('p', 'revision-notice', '내용 수정됨'));
        } else closeAll();
      }
    }
    renderLiveStatus();
  }
  function flushUpdate() {
    if (!queuedUpdate || drag) return;
    const update = queuedUpdate;
    queuedUpdate = null;
    applyIncoming(update);
  }
  async function poll() {
    try {
      const url = new URL(data.live.updates_url, location.href);
      url.searchParams.set('since', data.live.revision);
      url.searchParams.set('epoch', data.live.epoch);
      const response = await fetch(url, {cache: 'no-store', signal: AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('Live connection failed');
      const update = await response.json();
      connected = true;
      if (drag) queuedUpdate = update;
      else applyIncoming(update);
      renderLiveStatus();
    } catch (error) {
      connected = false;
      renderLiveStatus();
    } finally {
      setTimeout(poll, 1000);
    }
  }
  if (data.live) {
    document.body.classList.add('live-reader');
    document.getElementById('live-bar').hidden = false;
    renderLiveStatus();
    setTimeout(poll, 1000);
  }
})();
