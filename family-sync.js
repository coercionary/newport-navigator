// Family pins — on-device only (localStorage). Shared sync will be a Fly.io API later.
(function (w) {
  const LS_PINS = 'nn-family-pins';
  const LS_NICK = 'nn-nickname';

  function loadPins() {
    try { return JSON.parse(localStorage.getItem(LS_PINS) || '[]'); } catch { return []; }
  }
  function savePins(pins) {
    localStorage.setItem(LS_PINS, JSON.stringify(pins));
  }
  function loadNick() { return localStorage.getItem(LS_NICK) || ''; }
  function saveNick(n) {
    const v = String(n || '').trim();
    if (v) localStorage.setItem(LS_NICK, v);
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

  w.FamilySync = { loadPins, savePins, loadNick, saveNick, upsertLocal };
})(window);
