// Family pins — localStorage plus optional Fly.io sync (trip code, last-write-wins).
(function (w) {
  const LS_PINS = 'nn-family-pins';
  const LS_HOPS = 'nn-family-hops';
  const TRIP_CODE = 'clewbay2026';
  const AT_RE = /@(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)/;
  const BANG_RE = /!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)/;
  const LL_RE = /[?&#](?:ll|q|query|destination|center|daddr|saddr)=(-?\d{1,2}\.\d+)[,+/](-?\d{1,3}\.\d+)/i;
  const GEO_RE = /geo:(?:0,0\?q=)?(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)/i;
  const RAW_RE = /^\s*(-?\d{1,2}\.\d+)\s*[,/\s]\s*(-?\d{1,3}\.\d+)\s*$/;
  const PLACE_RE = /\/maps\/place\/([^/@?#]+)/i;
  const SHORT = /(?:maps\.app\.goo\.gl|goo\.gl\/maps|g\.co\/maps)/i;

  function loadPins() {
    try {
      const v = JSON.parse(localStorage.getItem(LS_PINS) || '[]');
      return Array.isArray(v) ? v : [];
    } catch { return []; }
  }
  function savePins(pins) {
    localStorage.setItem(LS_PINS, JSON.stringify(pins));
  }
  function publicPin(pin) {
    const out = Object.assign({}, pin);
    delete out._off;
    return out;
  }
  function upsertLocal(pin) {
    pin = publicPin(pin);
    const pins = loadPins();
    const i = pins.findIndex(p => p.id === pin.id);
    if (i >= 0) pins[i] = pin; else pins.push(pin);
    savePins(pins);
    return pins;
  }
  function fingerprint(pins) {
    return (pins || []).map(p => (p.id || '') + '\t' + (p.updatedAt || '') + '\t' + (p.deleted ? 1 : 0)).sort().join('|');
  }
  function newer(a, b) {
    const ta = a && a.updatedAt || '';
    const tb = b && b.updatedAt || '';
    if (ta !== tb) return tb > ta ? b : a;
    return b;
  }
  function mergePins(local, remote) {
    const map = new Map();
    (local || []).forEach(p => { if (p && p.id) map.set(p.id, p); });
    (remote || []).forEach(p => {
      if (!p || !p.id) return;
      const cur = map.get(p.id);
      map.set(p.id, cur ? newer(cur, p) : p);
    });
    return Array.from(map.values());
  }
  function headers() {
    return { 'Content-Type': 'application/json', 'X-Trip-Code': TRIP_CODE };
  }
  function plausible(lat, lng) {
    return lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180;
  }
  function pick(pairs) {
    const ie = pairs.filter(([lat, lng]) => lat >= 51.2 && lat <= 55.6 && lng >= -11 && lng <= -5.3);
    const p = (ie.length ? ie : pairs)[0];
    return p ? { lat: +p[0].toFixed(6), lng: +p[1].toFixed(6) } : null;
  }
  function coordsIn(text) {
    const pairs = [];
    [AT_RE, BANG_RE, LL_RE, GEO_RE].forEach(rx => {
      const m = String(text).match(rx);
      if (m && plausible(+m[1], +m[2])) pairs.push([+m[1], +m[2]]);
    });
    const raw = String(text).match(RAW_RE);
    if (raw && plausible(+raw[1], +raw[2])) pairs.push([+raw[1], +raw[2]]);
    return pick(pairs);
  }
  function placeName(text) {
    const m = String(text).match(PLACE_RE);
    if (!m) return '';
    try {
      return decodeURIComponent(m[1].replace(/\+/g, ' ')).replace(/\s+/g, ' ').trim().slice(0, 79);
    } catch {
      return m[1].replace(/\+/g, ' ').trim().slice(0, 79);
    }
  }
  function geoName(text) {
    const m = String(text).match(/geo:[^#]*\(([^)]+)\)/i);
    if (!m) return '';
    try { return decodeURIComponent(m[1]).trim().slice(0, 79); } catch { return m[1].trim().slice(0, 79); }
  }
  function parseLocal(text) {
    const t = String(text || '').trim();
    if (!t || SHORT.test(t)) return null;
    const c = coordsIn(t);
    if (!c) return null;
    const name = geoName(t) || placeName(t);
    const source = /^geo:/i.test(t) ? 'geo' : (/^https?:|\.com|\.gl/i.test(t) ? 'maps' : 'coords');
    return name ? Object.assign({ name, source }, c) : Object.assign({ source }, c);
  }

  function loadHops() {
    try {
      const v = JSON.parse(localStorage.getItem(LS_HOPS) || '[]');
      return Array.isArray(v) ? v : [];
    } catch { return []; }
  }
  function saveHops(hops) {
    localStorage.setItem(LS_HOPS, JSON.stringify(hops));
  }
  function hopKey(frm, to) {
    return String(frm || '') + '>' + String(to || '');
  }
  function upsertHop(hop) {
    if (!hop || !hop.from || !hop.to) return loadHops();
    hop = Object.assign({}, hop, { id: hop.id || hopKey(hop.from, hop.to), generated: true });
    const hops = loadHops();
    const i = hops.findIndex(h => h && (h.id === hop.id || (h.from === hop.from && h.to === hop.to)));
    if (i >= 0) hops[i] = hop; else hops.push(hop);
    saveHops(hops);
    return hops;
  }
  function findHop(frm, to) {
    return loadHops().find(h => h && !h.deleted && h.from === frm && h.to === to) || null;
  }
  function hopFingerprint(hops) {
    return (hops || []).map(h => (h.id || '') + '\t' + (h.updatedAt || '') + '\t' + (h.deleted ? 1 : 0)).sort().join('|');
  }
  function mergeHops(local, remote) {
    const map = new Map();
    (local || []).forEach(h => { if (h && h.id) map.set(h.id, h); });
    (remote || []).forEach(h => {
      if (!h || !h.id) return;
      const cur = map.get(h.id);
      map.set(h.id, cur ? newer(cur, h) : h);
    });
    return Array.from(map.values());
  }

  async function push() {
    if (!navigator.onLine) return false;
    const before = fingerprint(loadPins());
    const r = await fetch('/api/pins', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ pins: loadPins().map(publicPin) })
    });
    if (!r.ok) return false;
    const data = await r.json();
    if (!Array.isArray(data.pins)) return false;
    savePins(mergePins(loadPins(), data.pins));
    return fingerprint(loadPins()) !== before;
  }

  async function pushHops() {
    if (!navigator.onLine) return false;
    const before = hopFingerprint(loadHops());
    const r = await fetch('/api/hops', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ hops: loadHops() })
    });
    if (!r.ok) return false;
    const data = await r.json();
    if (!Array.isArray(data.hops)) return false;
    saveHops(mergeHops(loadHops(), data.hops));
    return hopFingerprint(loadHops()) !== before;
  }

  let syncing = false, lastSync = 0;
  async function sync(force) {
    if (!navigator.onLine || syncing) return false;
    if (!force && Date.now() - lastSync < 4000) return false;
    syncing = true;
    try {
      const pinsChanged = await push();
      const hopsChanged = await pushHops();
      lastSync = Date.now();
      return pinsChanged || hopsChanged;
    } catch {
      return false;
    } finally {
      syncing = false;
    }
  }

  async function resolve(text) {
    const local = parseLocal(text);
    if (local) return local;
    const r = await fetch('/api/resolve', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ text: String(text || '').trim() })
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || 'Could not find that place.');
    return data;
  }

  w.FamilySync = {
    loadPins, savePins, upsertLocal, parseLocal, resolve, sync, push, headers,
    loadHops, saveHops, upsertHop, findHop, hopKey
  };
})(window);
