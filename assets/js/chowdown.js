/* Chowdown — shared helpers used by every page.
   Exposes window.Chowdown. Page scripts run after this file loads. */
window.Chowdown = (function () {
  var REPO = 'billmiky/chowdown';
  var BRANCH = 'main';
  var BASE = (document.documentElement.dataset.base || '').replace(/\/$/, '');

  /* ---- Storage (never throws: private mode / blocked storage) ---- */
  function load(key, fallback) {
    try {
      var raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  }

  function save(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  function token() {
    try { return localStorage.getItem('gh_pat') || ''; } catch (e) { return ''; }
  }

  /* ---- GitHub Actions dispatch ---- */
  async function triggerWorkflow(workflow, inputs) {
    var t = token();
    if (!t) {
      throw new Error('No GitHub token — save one on the <a href="' + BASE + '/import/">Import page</a>');
    }
    var resp = await fetch(
      'https://api.github.com/repos/' + REPO + '/actions/workflows/' + workflow + '/dispatches',
      {
        method: 'POST',
        headers: {
          'Authorization': 'token ' + t,
          'Accept': 'application/vnd.github.v3+json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ ref: BRANCH, inputs: inputs || {} }),
      }
    );
    if (resp.status === 204) return;
    var body = {};
    try { body = await resp.json(); } catch (e) {}
    if (resp.status === 401) throw new Error('GitHub token was rejected — update it on the <a href="' + BASE + '/import/">Import page</a>');
    if (resp.status === 403 || resp.status === 404) {
      throw new Error('GitHub token lacks permission — it needs <em>Actions: Read and write</em> and <em>Contents: Read and write</em> on ' + REPO + ' (or the <em>repo</em> + <em>workflow</em> scopes for a classic token). Update it on the <a href="' + BASE + '/import/">Import page</a>');
    }
    throw new Error(body.message || ('HTTP ' + resp.status));
  }

  /* ---- Read / write a file in the repo (GitHub Contents API) ----
     putFile fails with a 409 if the file changed since getFile, so callers can't
     overwrite someone else's edit by accident. */
  function apiHeaders() {
    var t = token();
    if (!t) throw new Error('No GitHub token — save one on the <a href="' + BASE + '/import/">Import page</a>');
    return { 'Authorization': 'token ' + t, 'Accept': 'application/vnd.github.v3+json' };
  }

  async function apiError(resp) {
    var body = {};
    try { body = await resp.json(); } catch (e) {}
    if (resp.status === 401) return new Error('GitHub token was rejected — update it on the <a href="' + BASE + '/import/">Import page</a>');
    if (resp.status === 409) return new Error('The file changed on GitHub — reload and try again');
    return new Error(body.message || ('HTTP ' + resp.status));
  }

  async function getFile(path) {
    var resp = await fetch('https://api.github.com/repos/' + REPO + '/contents/' + path + '?ref=' + BRANCH,
      { headers: apiHeaders(), cache: 'no-store' });
    if (!resp.ok) throw await apiError(resp);
    var data = await resp.json();
    var bytes = Uint8Array.from(atob(data.content.replace(/\n/g, '')), function (c) { return c.charCodeAt(0); });
    return { text: new TextDecoder().decode(bytes), sha: data.sha };
  }

  async function putFile(path, text, sha, message) {
    var bytes = new TextEncoder().encode(text);
    var bin = '';
    bytes.forEach(function (b) { bin += String.fromCharCode(b); });
    var headers = apiHeaders();
    headers['Content-Type'] = 'application/json';
    var resp = await fetch('https://api.github.com/repos/' + REPO + '/contents/' + path, {
      method: 'PUT',
      headers: headers,
      body: JSON.stringify({ message: message, content: btoa(bin), sha: sha, branch: BRANCH }),
    });
    if (!resp.ok) throw await apiError(resp);
    return (await resp.json()).content.sha;
  }

  /* ---- Dates ----
     Front matter dates are plain YYYY-MM-DD. `new Date('2026-09-21')` parses that
     as UTC midnight, which is the previous evening in US time zones, so parse the
     parts into a local date instead. */
  function parseDate(raw) {
    if (!raw) return null;
    var s = String(raw).trim();
    if (!s || s === 'null' || s === 'None' || s === 'false' || s === '~') return null;
    var m = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (m) return new Date(+m[1], +m[2] - 1, +m[3]);
    var d = new Date(s);
    return isNaN(d) ? null : d;
  }

  function startOfDay(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function daysSince(raw) {
    var d = parseDate(raw);
    if (!d) return null;
    return Math.round((startOfDay(new Date()) - startOfDay(d)) / 86400000);
  }

  function relativeDays(days) {
    if (days === null) return '';
    if (days <= 0)  return 'today';
    if (days === 1) return 'yesterday';
    if (days < 14)  return days + ' days ago';
    if (days < 60)  return Math.floor(days / 7) + ' weeks ago';
    if (days < 730) return Math.floor(days / 30) + ' months ago';
    return Math.floor(days / 365) + ' years ago';
  }

  function isoDate(d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function mondayOf(d) {
    var mon = startOfDay(d);
    mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
    return mon;
  }

  /* ---- Time ("30", "45 minutes", "10 mins" → "30 min", "1 hr 15 min") ---- */
  function minutes(raw) {
    var n = parseInt(raw, 10);
    return isNaN(n) ? null : n;
  }

  function formatMinutes(raw) {
    var n = minutes(raw);
    if (n === null) return raw ? String(raw) : '';
    if (n < 60) return n + ' min';
    var h = Math.floor(n / 60), m = n % 60;
    return h + ' hr' + (m ? ' ' + m + ' min' : '');
  }

  /* ---- Misc ---- */
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  var toastWrap = null;
  function toast(html, kind, ms) {
    if (!toastWrap) {
      toastWrap = document.createElement('div');
      toastWrap.className = 'cd-toast-wrap';
      toastWrap.setAttribute('role', 'status');
      toastWrap.setAttribute('aria-live', 'polite');
      document.body.appendChild(toastWrap);
    }
    var el = document.createElement('div');
    el.className = 'cd-toast' + (kind ? ' ' + kind : '');
    el.innerHTML = html;
    toastWrap.appendChild(el);
    setTimeout(function () { el.remove(); }, ms || (kind === 'err' ? 6000 : 3500));
    return el;
  }

  return {
    REPO: REPO,
    BASE: BASE,
    load: load,
    save: save,
    token: token,
    triggerWorkflow: triggerWorkflow,
    getFile: getFile,
    putFile: putFile,
    parseDate: parseDate,
    daysSince: daysSince,
    relativeDays: relativeDays,
    isoDate: isoDate,
    mondayOf: mondayOf,
    minutes: minutes,
    formatMinutes: formatMinutes,
    escapeHtml: escapeHtml,
    toast: toast,
  };
})();
