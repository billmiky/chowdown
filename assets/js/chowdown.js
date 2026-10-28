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

  /* ---- Token sync across devices ----
     The token is encrypted in the browser with a passphrase (PBKDF2 -> AES-GCM) and the
     ciphertext is committed to .sync/token.json. A new device only needs the passphrase:
     it fetches the ciphertext and decrypts it locally. The passphrase never leaves the
     browser. The file is public, so the passphrase should be strong. */
  var SYNC_FILE = '.sync/token.json';
  var SYNC_ITER = 310000;

  function b64(buf) {
    var s = '', b = new Uint8Array(buf);
    for (var i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
    return btoa(s);
  }
  function unb64(str) {
    var s = atob(str), b = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) b[i] = s.charCodeAt(i);
    return b;
  }
  async function deriveKey(pass, salt, iter) {
    var base = await crypto.subtle.importKey('raw', new TextEncoder().encode(pass), 'PBKDF2', false, ['deriveKey']);
    return crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt: salt, iterations: iter, hash: 'SHA-256' },
      base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']
    );
  }
  async function encryptToken(pass, plain) {
    var salt = crypto.getRandomValues(new Uint8Array(16));
    var iv = crypto.getRandomValues(new Uint8Array(12));
    var key = await deriveKey(pass, salt, SYNC_ITER);
    var ct = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: iv }, key, new TextEncoder().encode(plain));
    return { v: 1, iter: SYNC_ITER, salt: b64(salt), iv: b64(iv), ct: b64(ct) };
  }
  async function decryptToken(pass, blob) {
    var key = await deriveKey(pass, unb64(blob.salt), blob.iter);
    try {
      var pt = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64(blob.iv) }, key, unb64(blob.ct));
      return new TextDecoder().decode(pt);
    } catch (e) { throw new Error('Wrong passphrase'); }
  }

  /* Encrypts the saved token and commits it to the repo (needs Contents: write). */
  async function uploadSyncedToken(pass) {
    var t = token();
    if (!t) throw new Error('Save a token on this device first');
    var url = 'https://api.github.com/repos/' + REPO + '/contents/' + SYNC_FILE;
    var headers = { 'Authorization': 'token ' + t, 'Accept': 'application/vnd.github.v3+json', 'Content-Type': 'application/json' };
    var blob = await encryptToken(pass, t);
    var sha;
    var cur = await fetch(url + '?ref=' + BRANCH, { headers: headers, cache: 'no-store' });
    if (cur.ok) sha = (await cur.json()).sha;
    else if (cur.status !== 404) throw new Error(cur.status === 401 ? 'GitHub token was rejected' : 'HTTP ' + cur.status);
    var resp = await fetch(url, {
      method: 'PUT',
      headers: headers,
      body: JSON.stringify({
        message: 'Update synced token',
        branch: BRANCH,
        sha: sha,
        content: btoa(JSON.stringify(blob)),
      }),
    });
    if (!resp.ok) {
      var body = {};
      try { body = await resp.json(); } catch (e) {}
      if (resp.status === 403 || resp.status === 404) throw new Error('Token needs Contents: Read and write on ' + REPO);
      throw new Error(body.message || ('HTTP ' + resp.status));
    }
  }

  /* Fetches the ciphertext, decrypts it and stores it as this device's token. */
  async function fetchSyncedToken(pass) {
    var resp = await fetch(
      'https://api.github.com/repos/' + REPO + '/contents/' + SYNC_FILE + '?ref=' + BRANCH + '&t=' + Date.now(),
      { headers: { 'Accept': 'application/vnd.github.raw+json' }, cache: 'no-store' }
    );
    if (resp.status === 404) throw new Error('No synced token yet — upload one from a device that has it');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    var t = await decryptToken(pass, await resp.json());
    try { localStorage.setItem('gh_pat', t); } catch (e) {}
    return t;
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
  }

  return {
    REPO: REPO,
    BASE: BASE,
    load: load,
    save: save,
    token: token,
    uploadSyncedToken: uploadSyncedToken,
    fetchSyncedToken: fetchSyncedToken,
    triggerWorkflow: triggerWorkflow,
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
