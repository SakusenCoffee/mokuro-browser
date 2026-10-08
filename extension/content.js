(() => {
  if (globalThis.__localMokuroInstalled) return;
  globalThis.__localMokuroInstalled = true;
  const pageKey = crypto.randomUUID();
  const images = new Map();
  const ids = new WeakMap();
  const layers = new Set();
  let pickerCleanup = null;
  let panel = null;
  let noticeTimeout;
  let fullText = "";
  let autoEnabled = false;
  let autoTimer;
  let autoRunning = false;
  let retryAfter = 0;
  let clearedKey = null;
  let missingKey = null;
  let missingUntil = 0;
  let hoverFontPercent = 100;
  const attempted = new Map();

  const host = document.createElement("div");
  host.id = "local-mokuro-overlay";
  host.style.cssText = "all:initial;position:absolute;top:0;left:0;width:0;height:0;z-index:2147483646;pointer-events:none";
  document.documentElement.append(host);
  // Dictionary extensions need ordinary DOM text for caret hit testing.
  // Keep styles scoped instead of hiding OCR behind a closed shadow root.
  const root = host;
  const style = document.createElement("style");
  style.textContent = `
    #local-mokuro-overlay :where(div,p,span,section,pre,button){all:initial;box-sizing:border-box}
  ` + `
    .layer{position:absolute;overflow:hidden;pointer-events:none}
    .inner{position:absolute;transform-origin:0 0;pointer-events:none}.block{position:absolute;pointer-events:none}
    .block:hover{z-index:1000}
    .hit-area{position:absolute;pointer-events:auto}
    .ink-mask{position:absolute;pointer-events:none;opacity:0;background:white}
    .block:hover .ink-mask,.layer.pinned .ink-mask{opacity:1}
    .text-surface{position:absolute;display:flex;align-items:flex-start;width:max-content;height:max-content;
      gap:.2em;padding:.1em;background:white;opacity:0;pointer-events:none}
    .text-surface.vertical{flex-direction:row-reverse}.text-surface.horizontal{flex-direction:column}
    .block:hover .text-surface,.layer.pinned .text-surface{opacity:1}
    .line{position:relative;white-space:nowrap;color:#111;
      margin:0;font-family:"Noto Sans JP","Meiryo",sans-serif;line-height:1.1;letter-spacing:0;user-select:text;cursor:text;
      display:block;pointer-events:none;opacity:0;border:0;outline:none;text-orientation:upright;
      width:max-content;height:max-content}
    .block:hover .line,.layer.pinned .line{pointer-events:auto;opacity:1}
    .digits{text-combine-upright:all;writing-mode:inherit;text-orientation:inherit;
      font:inherit;color:inherit;letter-spacing:0;user-select:text;pointer-events:inherit;white-space:inherit}
    .notice,.panel{position:fixed;pointer-events:auto;font:13px/1.5 system-ui,sans-serif;color:#203b35;
      background:#fffcf3;border:1px solid #c7d8cd;box-shadow:0 3px 20px #0003;border-radius:12px}
    .notice{bottom:24px;left:24px;max-width:430px;padding:14px 18px;white-space:pre-wrap}
    .notice.error{color:#9e3127;border-color:#d8afa6}
    .toolbar{position:fixed;bottom:24px;right:24px;width:44px;height:44px;pointer-events:auto}
    .orb{display:block;position:absolute;right:0;bottom:0;width:24px;height:24px;padding:0;border-radius:50%;border:1px solid #9ad6ff;
      background:radial-gradient(circle at 35% 30%,#e0f5ff,#76b9ed 65%,#4a8dcd);box-shadow:0 0 14px #80c9ff70;
      opacity:0;transform:scale(.8);transition:opacity .3s ease,transform .3s ease;cursor:pointer}
    .layer:has(.block:hover) ~ .toolbar.ready .orb,.toolbar.ready.selection .orb{opacity:.35;transform:scale(1)}
    .toolbar.ready:hover .orb,.toolbar.ready:focus-within .orb{opacity:.65;transform:scale(1)}
    .orb:hover{background:radial-gradient(circle at 35% 30%,#e0f5ff,#76b9ed 65%,#4a8dcd)}
    button{font:600 12px system-ui;color:#225c50;background:#eef3e9;border:0;border-radius:7px;padding:9px 11px;cursor:pointer}
    button:hover{background:#dfe9d9}.panel{top:24px;right:24px;width:360px;max-width:90vw;max-height:70vh;overflow:auto;padding:18px;
      color:#edf3fb;background:rgba(8,12,18,.88);border-color:#91a9c23f;box-shadow:0 8px 32px #0006;backdrop-filter:blur(12px)}
    .panel button{color:#edf3fb;background:#ffffff14;border:1px solid #ffffff25}
    .panel button:hover{background:#ffffff24}
    .panel pre{display:block;white-space:pre-wrap;font:16px/1.8 "Noto Sans JP",sans-serif;color:inherit;user-select:text;margin:14px 0 0}
    .pick-outline{position:fixed;pointer-events:none;border:3px solid #34a78b;background:#34a78b12;border-radius:4px}
  `.replace(/(^|})\s*([^{}]+)\{/g, (_, end, selectors) =>
    `${end} ${selectors.split(",").map(selector => `#local-mokuro-overlay ${selector.trim()}`).join(",")} {`);
  root.append(style);
  function setFontPercent(value) {
    hoverFontPercent = Number.isFinite(Number(value)) ? Math.min(200, Math.max(50, Number(value))) : 100;
    for (const item of layers) item.sizeText();
  }
  const notice = document.createElement("div");
  notice.className = "notice";
  notice.style.display = "none";
  notice.setAttribute("role", "status");
  root.append(notice);

  function notify(text, error = false, temporary = false) {
    clearTimeout(noticeTimeout);
    notice.textContent = text;
    notice.className = `notice${error ? " error" : ""}`;
    notice.style.display = "block";
    if (temporary) noticeTimeout = setTimeout(() => { notice.style.display = "none"; }, 6000);
  }
  function descriptor(image) {
    if (!image?.complete || !image.naturalWidth) throw new Error("Wait for this image to load, then try again.");
    let id = ids.get(image);
    if (!id) { id = crypto.randomUUID(); ids.set(image, id); images.set(id, image); }
    return {kind: "image", id, src: image.currentSrc || image.src, pageKey,
      width: image.naturalWidth, height: image.naturalHeight};
  }
  function visibleImages() {
    return [...document.images].map(image => {
      const rect = image.getBoundingClientRect();
      const width = Math.max(0, Math.min(innerWidth, rect.right) - Math.max(0, rect.left));
      const height = Math.max(0, Math.min(innerHeight, rect.bottom) - Math.max(0, rect.top));
      const css = getComputedStyle(image);
      return {image, area: width * height, css};
    }).filter(item => item.area > 1000 && item.image.naturalWidth * item.image.naturalHeight > 40000
      && item.css.visibility !== "hidden" && item.css.display !== "none")
      .sort((a, b) => b.area - a.area);
  }
  function clear(explicit = false) {
    if (explicit) clearedKey = MokuroResults.key([...layers][0]?.target || {});
    pickerCleanup?.();
    for (const item of layers) { item.cleanup(); item.node.remove(); }
    layers.clear();
    root.querySelector(".toolbar")?.remove();
    panel?.remove(); panel = null;
    fullText = "";
    notice.style.display = "none";
  }

  function button(label, action) {
    const element = document.createElement("button");
    element.textContent = label;
    element.onclick = action;
    return element;
  }
  function toolbar() {
    root.querySelector(".toolbar")?.remove();
    const bar = document.createElement("div"); bar.className = "toolbar";
    const orb = button("", () => {
      if (panel) { panel.remove(); panel = null; return; }
      panel = document.createElement("section"); panel.className = "panel";
      panel.setAttribute("aria-label", "All scanned text");
      panel.append(button("Copy all text", async () => {
        try { await navigator.clipboard.writeText(fullText); notify("Copied OCR text.", false, true); }
        catch { notify("Select the text below and copy it with Ctrl+C.", false, true); }
      }));
      const pre = document.createElement("pre"); pre.textContent = fullText;
      panel.append(pre); root.append(panel);
    });
    orb.className = "orb";
    orb.setAttribute("aria-label", "Show all scanned text");
    orb.title = "All scanned text";
    bar.append(orb);
    bar.addEventListener("click", event => {
      // Mouse clicks should not leave the hover menu latched open. Keyboard
      // users retain focus so the controls remain reachable with Tab.
      if (event.detail > 0 && bar.contains(document.activeElement)) document.activeElement.blur();
    });
    root.append(bar);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (bar.isConnected) bar.classList.add("ready");
    }));
  }
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && panel) { panel.remove(); panel = null; }
  });
  document.addEventListener("selectionchange", () => {
    const selection = window.getSelection();
    root.querySelector(".toolbar")?.classList.toggle("selection", !!selection && !selection.isCollapsed
      && root.contains(selection.anchorNode));
  });

  function fitPosition(value, remaining) {
    if (value.endsWith("%")) return remaining * parseFloat(value) / 100;
    if (value === "left" || value === "top") return 0;
    if (value === "right" || value === "bottom") return remaining;
    if (value === "center") return remaining / 2;
    return parseFloat(value) || 0;
  }

  function sizeBlock(group, font) {
    const {surface, entries, vertical, bounds} = group;
    surface.style.fontSize = `${font}px`;
    for (const entry of entries) entry.node.style.fontSize = `${font}px`;
    // OCR coordinates anchor the group. Flex layout provides consistent gaps,
    // common alignment and a white box sized to the actual replacement text.
    const pad = font * .1;
    const left = vertical ? Math.max(...entries.map(entry => entry.left + entry.width)) - surface.offsetWidth + pad
      : Math.min(...entries.map(entry => entry.left)) - pad;
    const top = Math.min(...entries.map(entry => entry.top)) - pad;
    Object.assign(surface.style, {left: `${Math.max(-bounds.x, left)}px`, top: `${Math.max(-bounds.y, top)}px`});
  }

  function render(target, result) {
    if (!MokuroResults.valid(result)) throw new Error("Incomplete OCR data. Check the page to scan it again.");
    if (target.pageKey !== pageKey) throw new Error("The page changed during scanning. Scan again.");
    const image = target.kind === "image" ? images.get(target.id) : null;
    if (target.kind === "image" && (!image?.isConnected || (image.currentSrc || image.src) !== target.src)) {
      throw new Error("The manga image changed during scanning. Scan again.");
    }
    clear();
    if (!host.isConnected) document.documentElement.append(host);
    clearedKey = null;
    missingKey = null;
    const layer = document.createElement("div"); layer.className = "layer";
    const inner = document.createElement("div"); inner.className = "inner";
    inner.style.width = `${result.img_width}px`; inner.style.height = `${result.img_height}px`;
    layer.append(inner); root.append(layer);
    fullText = result.blocks.map(block => block.lines.join("\n")).join("\n\n");
    const baseFont = MokuroResults.pageFont(result);
    const textGroups = [];
    for (const block of result.blocks) {
      const [x1, y1, x2, y2] = block.box;
      const box = document.createElement("div"); box.className = "block";
      Object.assign(box.style, {left: `${x1}px`, top: `${y1}px`, width: `${x2-x1}px`, height: `${y2-y1}px`});
      const lines = [];
      for (let index = 0; index < block.lines.length; index++) {
        const text = block.lines[index];
        if (!text) continue;
        const poly = block.lines_coords[index];
        const left = Math.min(...poly.map(point => point[0]));
        const top = Math.min(...poly.map(point => point[1]));
        const width = Math.max(...poly.map(point => point[0])) - left;
        const height = Math.max(...poly.map(point => point[1])) - top;
        if (width > 0 && height > 0) lines.push({text, left, top, width, height});
      }
      if (!lines.length) continue;
      const surface = document.createElement("div");
      surface.className = `text-surface ${block.vertical ? "vertical" : "horizontal"}`;
      const masks = [], glyphs = [], entries = [];
      for (const {text, left, top, width, height} of lines) {
        // Keep the original hit regions at every zoom level so reducing the
        // text size cannot make the hover target jump away from the pointer.
        const hit = document.createElement("div"); hit.className = "hit-area";
        hit.setAttribute("aria-hidden", "true");
        Object.assign(hit.style, {left: `${left-x1}px`, top: `${top-y1}px`, width: `${width}px`, height: `${height}px`});
        box.append(hit);
        const mask = document.createElement("div"); mask.className = "ink-mask";
        mask.setAttribute("aria-hidden", "true");
        const sourceFont = Math.min(block.font_size, block.vertical ? width : height);
        const rubyPad = Math.min(sourceFont * .8, block.vertical ? result.img_width - left - width : top);
        const pad = Math.min(2, sourceFont * .08);
        Object.assign(mask.style, {left: `${left-x1-pad}px`, top: `${top-y1-pad-(block.vertical ? 0 : rubyPad)}px`,
          width: `${width+pad*2+(block.vertical ? rubyPad : 0)}px`,
          height: `${height+pad*2+(block.vertical ? 0 : rubyPad)}px`});
        masks.push(mask);
        const line = document.createElement("p"); line.className = "line";
        if (block.vertical) {
          for (const part of MokuroResults.verticalParts(text)) {
            if (part.length === 2 && /^[0-9０-９]{2}$/.test(part)) {
              const digits = document.createElement("span"); digits.className = "digits";
              digits.textContent = part; line.append(digits);
            } else line.append(document.createTextNode(part));
          }
        } else line.textContent = text;
        Object.assign(line.style, {fontSize: `${baseFont}px`, writingMode: block.vertical ? "vertical-rl" : "horizontal-tb"});
        glyphs.push(line);
        entries.push({node: line, left: left-x1, top: top-y1, width, height});
      }
      // Preserve DOM/copy order while laying out vertical columns right-to-left.
      [...entries].sort((a, b) => block.vertical ? (b.left+b.width)-(a.left+a.width) : a.top-b.top)
        .forEach((entry, order) => { entry.node.style.order = String(order); });
      surface.append(...glyphs);
      box.append(...masks, surface);
      inner.append(box);
      textGroups.push({surface, entries, vertical: block.vertical, bounds: {x:x1, y:y1}});
    }
    const sizeText = () => {
      const font = baseFont * hoverFontPercent / 100;
      for (const group of textGroups) sizeBlock(group, font);
    };
    sizeText();
    let frame = 0;
    const layout = () => {
      frame = 0;
      if (image) {
        if (!image.isConnected || (image.currentSrc || image.src) !== target.src) {
          layer.style.display = "none"; return;
        }
        const rect = image.getBoundingClientRect();
        const css = getComputedStyle(image);
        const offsetX = parseFloat(css.borderLeftWidth) + parseFloat(css.paddingLeft);
        const offsetY = parseFloat(css.borderTopWidth) + parseFloat(css.paddingTop);
        const width = rect.width - offsetX - parseFloat(css.borderRightWidth) - parseFloat(css.paddingRight);
        const height = rect.height - offsetY - parseFloat(css.borderBottomWidth) - parseFloat(css.paddingBottom);
        let sx = width / result.img_width, sy = height / result.img_height;
        if (css.objectFit !== "fill") {
          let scale = css.objectFit === "cover" ? Math.max(sx, sy) : Math.min(sx, sy);
          if (css.objectFit === "none") scale = 1;
          if (css.objectFit === "scale-down") scale = Math.min(1, scale);
          sx = sy = scale;
        }
        const positions = css.objectPosition.split(" ");
        const x = fitPosition(positions[0] || "50%", width - result.img_width * sx);
        const y = fitPosition(positions[1] || "50%", height - result.img_height * sy);
        Object.assign(layer.style, {display: "block", left: `${rect.left+scrollX+offsetX}px`, top: `${rect.top+scrollY+offsetY}px`, width: `${width}px`, height: `${height}px`});
        Object.assign(inner.style, {left: `${x}px`, top: `${y}px`, transform: `scale(${sx},${sy})`});
      } else {
        Object.assign(layer.style, {left: `${target.x}px`, top: `${target.y}px`, width: `${target.width}px`, height: `${target.height}px`});
        inner.style.transform = `scale(${target.width/result.img_width},${target.height/result.img_height})`;
      }
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(layout); };
    const resize = new ResizeObserver(schedule);
    if (image) resize.observe(image);
    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    // Position can shift without resizing the image (lazy ads, reader controls).
    const interval = setInterval(schedule, 700);
    layers.add({node: layer, target, result, layout, sizeText, cleanup() {
      resize.disconnect(); clearInterval(interval); cancelAnimationFrame(frame);
      window.removeEventListener("scroll", schedule, true); window.removeEventListener("resize", schedule);
    }});
    layout(); toolbar();
    notify(`${result.blocks.length} text regions ready. Hover to select text.`, false, true);
  }

  function pick() {
    pickerCleanup?.();
    notify("Click the manga image to scan it. Press Esc to cancel.");
    const outline = document.createElement("div"); outline.className = "pick-outline"; outline.style.display = "none";
    root.append(outline);
    const move = event => {
      const image = event.target.closest?.("img");
      outline.style.display = image ? "block" : "none";
      if (image) {
        const rect = image.getBoundingClientRect();
        Object.assign(outline.style, {left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`});
      }
    };
    const click = event => {
      const image = event.target.closest?.("img");
      if (!image) return;
      event.preventDefault(); event.stopImmediatePropagation();
      pickerCleanup();
      try {
        chrome.runtime.sendMessage({type: "SCAN_IMAGE", target: descriptor(image)}).then(reply => {
          if (!reply.ok) notify(reply.error, true);
        });
      } catch (error) { notify(error.message, true); }
    };
    const key = event => { if (event.key === "Escape") { pickerCleanup(); notice.style.display = "none"; } };
    document.addEventListener("mousemove", move, true); document.addEventListener("click", click, true); document.addEventListener("keydown", key, true);
    pickerCleanup = () => {
      outline.remove(); document.removeEventListener("mousemove", move, true); document.removeEventListener("click", click, true);
      document.removeEventListener("keydown", key, true); pickerCleanup = null;
    };
  }

  function remember(target) {
    attempted.set(MokuroResults.key(target), Date.now() + 15000);
    if (attempted.size > 100) attempted.delete(attempted.keys().next().value);
  }

  function mangaImage() {
    return visibleImages().find(({image, area}) => {
      // Auto is opt-in. Reader URLs, CDN filenames and image classes need not
      // mention manga; long strips and landscape pages are valid too.
      return image.complete && area >= 40000 && image.naturalWidth >= 300 && image.naturalHeight >= 300;
    })?.image;
  }

  function scheduleAuto(delay = 650) {
    // A busy page must not postpone scanning indefinitely with DOM mutations.
    if (autoTimer != null) return;
    autoTimer = setTimeout(scanAuto, delay);
  }

  function overlayComplete(target, result) {
    if (!MokuroResults.valid(result) || !host.isConnected) return false;
    const item = [...layers].find(item => item.target.id === target.id
      && MokuroResults.key(item.target) === MokuroResults.key(target));
    if (!item?.node.isConnected) return false;
    item.layout();
    const expected = MokuroResults.lines(result);
    const actual = [...item.node.querySelectorAll(".line")];
    return item.node.style.display !== "none" && item.node.querySelectorAll(".block").length === result.blocks.length
      && actual.length === expected.length && actual.every((line, index) => line.textContent === expected[index]
        && getComputedStyle(line).visibility !== "hidden" && [...line.getClientRects()].some(rect => rect.width > 0 && rect.height > 0));
  }

  async function scanAuto() {
    autoTimer = null;
    if (autoRunning || pickerCleanup || document.visibilityState !== "visible") return;
    if (Date.now() < retryAfter) { scheduleAuto(retryAfter - Date.now()); return; }
    const image = mangaImage() || (!autoEnabled && visibleImages().find(item => item.image.complete)?.image);
    if (!image) return;
    const target = descriptor(image);
    const key = MokuroResults.key(target);
    if (clearedKey && clearedKey !== key) clearedKey = null;
    if (clearedKey === key || (!autoEnabled && missingKey === key && Date.now() < missingUntil)) return;
    const current = [...layers].find(item => item.target.id === target.id && MokuroResults.key(item.target) === key);
    if (current && overlayComplete(target, current.result)) return;
    if ((attempted.get(key) || 0) > Date.now()) return;
    autoRunning = true;
    try {
      const reply = await chrome.runtime.sendMessage({type: autoEnabled ? "AUTO_SCAN" : "CHECK_CACHE", target});
      if (!reply.ok) throw new Error(reply.error);
      if (reply.data.missing) { missingKey = key; missingUntil = Date.now() + 5000; }
      if (reply.data.restored) attempted.delete(key);
      if (reply.data.started || reply.data.started === false) {
        retryAfter = Date.now() + 1500;
        scheduleAuto(1500);
      }
    } catch (error) {
      remember(target); // Back off failures instead of permanently skipping a page.
      notify(error.message, true, true);
    } finally { autoRunning = false; }
  }

  function setAuto(enabled) {
    autoEnabled = enabled === true;
    if (autoEnabled) {
      attempted.clear();
      retryAfter = 0;
      clearedKey = null;
      missingKey = null;
    }
    clearTimeout(autoTimer);
    autoTimer = null;
    scheduleAuto(0);
  }

  chrome.storage.local.get({autoScan: false, hoverFontPercent: 100}).then(settings => {
    setAuto(settings.autoScan);
    setFontPercent(settings.hoverFontPercent);
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes.autoScan) setAuto(changes.autoScan.newValue);
    if (area === "local" && changes.hoverFontPercent) setFontPercent(changes.hoverFontPercent.newValue ?? 100);
  });
  const observer = new MutationObserver(records => {
    // Ignore our own overlay updates so progress notices don't restart the debounce.
    if (records.some(record => !host.contains(record.target))) scheduleAuto();
  });
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true,
    attributeFilter: ["src", "srcset", "sizes", "style", "class"]});
  document.addEventListener("load", event => { if (event.target instanceof HTMLImageElement) scheduleAuto(); }, true);
  document.addEventListener("visibilitychange", () => scheduleAuto());
  window.addEventListener("scroll", () => scheduleAuto(), {passive: true});
  window.addEventListener("resize", () => scheduleAuto());
  window.addEventListener("popstate", () => scheduleAuto());
  // Handles client-side URL changes and responsive sources without DOM mutations.
  setInterval(() => { if (!autoTimer) scheduleAuto(); }, 2500);

  chrome.runtime.onMessage.addListener((message, sender, reply) => {
    (async () => {
      if (message.pageKey && message.pageKey !== pageKey) throw new Error("Page changed.");
      if (message.type === "LARGEST") {
        const image = visibleImages()[0]?.image;
        if (!image) throw new Error("No loaded manga image is visible. Try Scan visible tab area.");
        return descriptor(image);
      }
      if (message.type === "FIND_IMAGE") {
        const image = [...document.images].find(image => (image.currentSrc || image.src) === message.src);
        if (!image) throw new Error("This image is inside a frame or has changed. Use Scan visible tab area.");
        return descriptor(image);
      }
      if (message.type === "VIEWPORT") {
        clear();
        // Hide this extension's notices before capturing the page.
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        return {kind: "viewport", pageKey, x: scrollX, y: scrollY, width: innerWidth, height: innerHeight};
      }
      if (message.type === "PICK_IMAGE") pick();
      if (message.type === "CLEAR") clear(true);
      if (message.type === "NOTICE") notify(message.text, message.error);
      if (message.type === "RENDER") render(message.target, message.result);
      if (message.type === "VERIFY_OVERLAY") return {complete: overlayComplete(message.target, message.result)};
      if (message.type === "CHECK_STATUS") {
        clearedKey = null; missingKey = null; attempted.delete(MokuroResults.key(message.target));
        notify(message.checked.restored ? "Saved page text checked and restored. No new scan needed."
          : message.checked.started ? "Page text is missing or incomplete. Scanning…" : "Waiting for the current scan…", false, true);
      }
      if (message.type === "SCAN_FINISHED") {
        if (message.failed) remember(message.target);
        missingKey = null;
        autoRunning = false; retryAfter = 0; scheduleAuto();
      }
      if (message.type === "READ_IMAGE") {
        const image = images.get(message.target.id);
        if (!image || (image.currentSrc || image.src) !== message.target.src) throw new Error("Image changed; scan again.");
        const response = await fetch(message.target.src);
        const blob = await response.blob();
        if (blob.size > 32 * 1024 * 1024) throw new Error("Image exceeds 32 MB.");
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob);
        });
        return {data};
      }
      return {};
    })().then(reply, error => reply({error: error.message}));
    return true;
  });
})();
