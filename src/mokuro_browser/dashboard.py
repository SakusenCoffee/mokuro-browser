"""Static live reader; private history is fetched using the URL-fragment token."""

DASHBOARD = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mokuro Browser · Live reading</title>
<style>
:root {color-scheme:dark;font:15px/1.5 ui-sans-serif,system-ui,sans-serif;background:#121a1c;color:#e8f1ee}
* {box-sizing:border-box}
body {margin:0;min-height:100vh;background:radial-gradient(circle at top left,#1c3935,#121a1c 46%)}
main {display:grid;grid-template-columns:minmax(250px,340px) 1fr;min-height:100vh}
.profile {padding:32px;border-right:1px solid #36534e;background:#172725cc;position:sticky;top:0;height:100vh}
.eyebrow {color:#7ce0be;text-transform:uppercase;font-size:11px;letter-spacing:.13em;font-weight:700}
.profile h1 {font-size:26px;margin:7px 0 3px}
.muted {color:#a5bbb5;margin:0}
.status {margin:22px 0;padding:11px 13px;border:1px solid #4e7f70;border-radius:10px;background:#1e3832}
.status.ready {box-shadow:0 0 18px #3ee69b36;border-color:#64e3a0}
.stats {display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:20px 0}
.stat {padding:13px;background:#213531;border:1px solid #35574f;border-radius:10px}
.stat:first-child {grid-column:1/-1}
.stat b {display:block;font-size:24px;color:#fff}
.stat span {font-size:12px;color:#a8c0b9}
.feed {padding:38px;max-width:1000px;width:100%;margin:0 auto}
.feed h2 {margin:0;font-size:28px}
.feed>p {color:#a5bbb5;margin:5px 0 24px}
.page {background:#1b2b28;border:1px solid #35534d;border-radius:12px;padding:16px 18px;margin:10px 0}
.page p {font:20px/1.65 "Noto Sans JP","Meiryo",sans-serif;margin:0;color:#f4f8f6;white-space:pre-wrap;overflow-wrap:anywhere}
.meta {font-size:12px;color:#9db5ae;margin-bottom:12px}
.empty {color:#a9c0b9;border:1px dashed #49675f;border-radius:12px;padding:28px;text-align:center}
@media(max-width:700px) {
  main {display:block}
  .profile {position:static;height:auto;border-right:0;border-bottom:1px solid #36534e}
  .feed {padding:24px}
}
</style>
<main>
  <aside class="profile">
    <div class="eyebrow">Mokuro Browser</div>
    <h1>Reading profile</h1>
    <p class="muted">Live, local OCR reading log</p>
    <div id="status" class="status" role="status">Connecting to local server…</div>
    <div class="stats">
      <div class="stat"><b id="characters">0</b><span>Characters</span></div>
      <div class="stat"><b id="kanji">0</b><span>Kanji</span></div>
      <div class="stat"><b id="hiragana">0</b><span>Hiragana</span></div>
      <div class="stat"><b id="katakana">0</b><span>Katakana</span></div>
      <div class="stat"><b id="pages">0</b><span>Saved pages</span></div>
    </div>
    <p class="muted">Spaces and punctuation are excluded. Edit or delete a page in the launcher's Reading history tab.</p>
  </aside>
  <section class="feed">
    <div class="eyebrow">Live feed</div>
    <h2>Scanned pages</h2>
    <p>All recognized text is grouped by manga page. It stays on this computer.</p>
    <div id="entries"><div class="empty">Waiting for scanned manga text…</div></div>
  </section>
</main>
<script>
const token = location.hash.slice(1), $ = id => document.getElementById(id);
let seen = null;
async function get(path) {
  const response = await fetch(path, {headers:{Authorization:'Bearer ' + token}});
  if (!response.ok) throw Error('Local server request failed');
  return response.json();
}
async function refresh() {
  const status = $('status');
  if (!token) {
    status.textContent = 'Open live reader from the launcher to connect.';
    return;
  }
  try {
    const [history, health] = await Promise.all([get('/history?limit=100'), get('/health')]);
    for (const name of ['characters','kanji','hiragana','katakana','pages']) {
      $(name).textContent = (history.totals[name] || 0).toLocaleString();
    }
    status.textContent = health.model === 'ready' ? '● Server ready · ' + (health.device || 'CPU')
      : health.model === 'loading' ? '● Loading OCR models…' : '● OCR models unavailable';
    status.className = 'status ' + (health.model === 'ready' ? 'ready' : '');
    // Include content, not only IDs: edits and count changes must appear live.
    const key = JSON.stringify(history.pages);
    if (key !== seen) {
      seen = key;
      const entries = $('entries');
      entries.replaceChildren();
      for (const page of history.pages) {
        const article = document.createElement('article');
        article.className = 'page';
        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.textContent = `${page.title || 'Manga page'} · ${page.characters.toLocaleString()} characters`;
        const text = document.createElement('p');
        text.textContent = page.text;
        article.append(meta, text);
        entries.append(article);
      }
      if (!history.pages.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = 'Waiting for scanned manga text…';
        entries.append(empty);
      }
    }
  } catch (error) {
    status.textContent = '● Cannot reach the local server. Start it in the launcher.';
    status.className = 'status';
  } finally {
    setTimeout(refresh, 1000);
  }
}
refresh();
</script>
</html>"""
