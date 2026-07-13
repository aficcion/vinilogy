/* Vinilogy — wishlist (M3c · Fase 1).
 *
 * Dos fuentes de verdad según el estado de sesión (lo dice `body[data-auth]`):
 *   - ANÓNIMO: los ids viven en localStorage (`vb-wishlist`). Cero cuenta. Para
 *     pintar portada+precio en /wishlist se piden al server (/wishlist/cards).
 *   - CON SESIÓN: la wishlist vive en BD; el ♥ hace POST/DELETE /wishlist/{id} y
 *     /wishlist se sirve ya renderizada. Al entrar, si el navegador traía ids de
 *     cuando eras anónimo, se suben una vez (/wishlist/import) y se limpia el LS.
 *
 * Progresivo: los botones ♥ arrancan `hidden` en el HTML; este script los revela.
 * Sin JS no hay wishlist para anónimos, así que no mostramos botones muertos.
 */
(function () {
  "use strict";

  // i18n mínimo: el idioma va en <html lang>; fallback a ES para lo no traducido.
  var _L = document.documentElement.lang === "en" ? "en" : "es";
  var _EN = {
    "Guardada": "Saved", "Guardar": "Save",
    "Guardar en tu wishlist": "Save to your wishlist",
    "Quitar de tu wishlist": "Remove from your wishlist"
  };
  function _t(s) { return _L === "en" && _EN[s] ? _EN[s] : s; }

  var LS_KEY = "vb-wishlist";
  var body = document.body;
  var mode = (body && body.getAttribute("data-auth")) === "user" ? "user" : "anon";

  // Estado en memoria: set de work_ids guardados (fuente para pintar los ♥).
  var wished = new Set();

  // --- localStorage (solo anónimo) -----------------------------------------
  function readLS() {
    try {
      var raw = JSON.parse(localStorage.getItem(LS_KEY) || "[]");
      return Array.isArray(raw) ? raw.map(Number).filter(function (n) { return n > 0; }) : [];
    } catch (e) { return []; }
  }
  function writeLS(ids) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(ids)); } catch (e) {}
  }

  // --- red (solo con sesión) ------------------------------------------------
  function fetchIds() {
    return fetch("/wishlist/ids", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { ids: [] }; })
      .then(function (j) { return (j && j.ids) || []; })
      .catch(function () { return []; });
  }
  function serverToggle(id, add) {
    return fetch("/wishlist/" + id, {
      method: add ? "POST" : "DELETE", credentials: "same-origin",
    }).then(function (r) { return r.ok; });
  }
  function importLS(ids) {
    return fetch("/wishlist/import?works=" + ids.join(","), {
      method: "POST", credentials: "same-origin",
    }).then(function (r) { return r.ok ? r.json() : { added: 0 }; })
      .catch(function () { return { added: 0 }; });
  }

  // --- pintar estado --------------------------------------------------------
  function paintButton(btn) {
    var id = Number(btn.getAttribute("data-work"));
    var on = wished.has(id);
    btn.hidden = false;
    btn.classList.toggle("is-wished", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    var label = btn.querySelector(".wish-label");
    if (label) label.textContent = on ? _t("Guardada") : _t("Guardar");
    if (!btn.querySelector(".wish-label")) {
      btn.setAttribute("aria-label", on ? _t("Quitar de tu wishlist") : _t("Guardar en tu wishlist"));
    }
  }
  function paintAll(root) {
    (root || document).querySelectorAll(".wish-btn[data-work]").forEach(paintButton);
  }
  function updateCount() {
    var el = document.querySelector(".nav-wish-count");
    if (!el) return;
    var n = wished.size;
    el.textContent = n ? String(n) : "";
    el.hidden = n === 0;
  }

  // --- toggle (delegación de clic) -----------------------------------------
  function onClick(ev) {
    var btn = ev.target.closest ? ev.target.closest(".wish-btn[data-work]") : null;
    if (!btn) return;
    ev.preventDefault();
    var id = Number(btn.getAttribute("data-work"));
    if (!id) return;
    var add = !wished.has(id);

    // Optimista: refleja ya, revierte si el server falla.
    if (add) wished.add(id); else wished.delete(id);
    paintButton(btn);
    updateCount();
    if (!add) maybeRemoveCard(btn);

    if (mode === "user") {
      serverToggle(id, add).then(function (ok) {
        if (!ok) {  // revierte
          if (add) wished.delete(id); else wished.add(id);
          paintAll(document); updateCount();
        }
      });
    } else {
      var ids = readLS();
      ids = ids.filter(function (x) { return x !== id; });
      if (add) ids.unshift(id);  // recién guardado primero
      writeLS(ids);
    }
  }

  // En la página /wishlist, quitar un disco lo saca de la lista al momento.
  function maybeRemoveCard(btn) {
    var root = document.getElementById("wishlist-root");
    if (!root || !root.contains(btn)) return;
    var wrap = btn.closest(".card-wrap");
    if (wrap) wrap.remove();
    if (!root.querySelector(".card-wrap")) showEmpty(root);
  }
  function showEmpty(root) {
    var empty = document.getElementById("wishlist-empty");
    if (empty) { empty.hidden = false; return; }
    var p = document.createElement("p");
    p.className = "empty";
    p.textContent = "Tu wishlist está vacía. Pulsa el ♥ en cualquier disco para empezar.";
    root.appendChild(p);
  }

  // --- hidratación de /wishlist en modo anónimo ----------------------------
  function hydrateAnonPage() {
    var root = document.getElementById("wishlist-root");
    if (!root || root.getAttribute("data-mode") !== "anon") return;
    var loading = document.getElementById("wishlist-loading");
    var empty = document.getElementById("wishlist-empty");
    var target = document.getElementById("wishlist-cards");
    var ids = readLS();
    if (!ids.length) {
      if (loading) loading.hidden = true;
      if (empty) empty.hidden = false;
      return;
    }
    fetch("/wishlist/cards?works=" + ids.join(","), { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (html) {
        target.innerHTML = html;
        if (loading) loading.hidden = true;
        if (!target.querySelector(".card-wrap")) { if (empty) empty.hidden = false; }
        paintAll(target);
      })
      .catch(function () { if (loading) loading.textContent = "No pudimos cargar tu wishlist."; });
  }

  // --- arranque -------------------------------------------------------------
  function afterState() {
    paintAll(document);
    updateCount();
    hydrateAnonPage();
  }

  function init() {
    document.addEventListener("click", onClick);
    if (mode === "user") {
      var pending = readLS();
      var chain = pending.length
        ? importLS(pending).then(function (res) {
            writeLS([]);
            // Si aterrizamos DIRECTO en /wishlist con items pendientes, el server
            // ya renderizó sin ellos: recargamos para que la BD mande. (Tras el
            // reload el LS está vacío → no re-importa, no hay bucle.)
            if (res && res.added > 0 && document.getElementById("wishlist-root")) {
              window.location.reload();
              return null;
            }
          })
        : Promise.resolve();
      chain.then(function (halt) {
        if (halt === null) return;  // recargando
        return fetchIds().then(function (ids) {
          wished = new Set(ids.map(Number));
          afterState();
        });
      });
    } else {
      wished = new Set(readLS());
      afterState();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
