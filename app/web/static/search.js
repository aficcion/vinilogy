/* Vinylbe v2 — buscador type-ahead + multi-select (§6).
 *
 * Progresivo: si el JS no carga, el <form> sigue haciendo GET /buscar?q=… (texto
 * libre, búsqueda §1). Con JS: al teclear (debounce ~180ms) pide /api/suggest y
 * muestra un desplegable de ARTISTAS y DISCOS; al clicar una sugerencia la añade
 * como CHIP (multi-select); "Buscar" navega a /buscar?artists=…&works=… si hay
 * chips, o a /buscar?q=… si solo hay texto.
 *
 * Se autoinstala en cada <form data-typeahead> que contenga un <input name="q">.
 */
(function () {
  "use strict";

  var MIN_CHARS = 3;
  var DEBOUNCE_MS = 180;

  function h(tag, cls, text) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
  }

  function install(form) {
    var input = form.querySelector('input[name="q"]');
    if (!input) return;

    // Estado de la selección: mapas id->label por tipo.
    var chosen = { artists: {}, works: {} };

    // Contenedores: una "caja" que envuelve input + chips + dropdown.
    var box = h("div", "ta-box");
    input.parentNode.insertBefore(box, input);
    var chipsEl = h("div", "ta-chips");
    box.appendChild(chipsEl);
    box.appendChild(input);
    var menu = h("div", "ta-menu");
    menu.hidden = true;
    box.appendChild(menu);

    // Campos ocultos que viajan en el submit (CSV de ids).
    var hidA = h("input"); hidA.type = "hidden"; hidA.name = "artists";
    var hidW = h("input"); hidW.type = "hidden"; hidW.name = "works";
    form.appendChild(hidA);
    form.appendChild(hidW);

    function syncHidden() {
      hidA.value = Object.keys(chosen.artists).join(",");
      hidW.value = Object.keys(chosen.works).join(",");
      // Si hay chips, el texto libre no debe competir (modo selección manda).
      input.disabled = false;
    }

    function renderChips() {
      chipsEl.innerHTML = "";
      var kinds = [["artists", "artista"], ["works", "disco"]];
      kinds.forEach(function (k) {
        Object.keys(chosen[k[0]]).forEach(function (id) {
          var label = chosen[k[0]][id];
          var chip = h("span", "ta-chip ta-chip-" + k[0]);
          chip.appendChild(h("span", "ta-chip-kind", k[1]));
          chip.appendChild(h("span", "ta-chip-label", label));
          var x = h("button", "ta-chip-x", "×");
          x.type = "button";
          x.setAttribute("aria-label", "Quitar " + label);
          x.addEventListener("click", function () {
            delete chosen[k[0]][id];
            renderChips();
            syncHidden();
          });
          chip.appendChild(x);
          chipsEl.appendChild(chip);
        });
      });
      syncHidden();
    }

    function closeMenu() {
      menu.hidden = true;
      menu.innerHTML = "";
    }

    function addChip(kind, id, label) {
      chosen[kind][id] = label;
      input.value = "";
      closeMenu();
      renderChips();
      input.focus();
    }

    function renderMenu(data) {
      menu.innerHTML = "";
      var any = false;
      function section(title, items, kind, toLabel) {
        if (!items || !items.length) return;
        any = true;
        menu.appendChild(h("div", "ta-sec", title));
        items.forEach(function (it) {
          if (chosen[kind][it.id]) return; // ya elegido
          var row = h("button", "ta-opt");
          row.type = "button";
          row.appendChild(h("span", "ta-opt-main", toLabel(it)));
          menu.appendChild(row);
          row.addEventListener("mousedown", function (ev) {
            ev.preventDefault(); // no perder el foco antes del click
            addChip(kind, it.id, toLabel(it));
          });
        });
      }
      section("Artistas", data.artists, "artists", function (a) {
        return a.name;
      });
      section("Discos", data.works, "works", function (w) {
        return w.title + (w.artist_name ? " · " + w.artist_name : "") +
          (w.year ? " (" + w.year + ")" : "");
      });
      if (!any) {
        menu.appendChild(h("div", "ta-empty", "Sin sugerencias"));
      }
      menu.hidden = false;
    }

    var timer = null;
    var lastReq = 0;
    function query() {
      var q = input.value.trim();
      if (q.length < MIN_CHARS) { closeMenu(); return; }
      var mine = ++lastReq;
      fetch("/api/suggest?q=" + encodeURIComponent(q), {
        headers: { "Accept": "application/json" },
      })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          if (!data || mine !== lastReq) return; // respuesta obsoleta
          if (input.value.trim().length < MIN_CHARS) return;
          renderMenu(data);
        })
        .catch(function () { /* red caída → sin dropdown, el form sigue */ });
    }

    input.addEventListener("input", function () {
      if (timer) clearTimeout(timer);
      timer = setTimeout(query, DEBOUNCE_MS);
    });
    input.addEventListener("focus", function () {
      if (input.value.trim().length >= MIN_CHARS && menu.innerHTML) {
        menu.hidden = false;
      }
    });
    input.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeMenu();
    });
    document.addEventListener("click", function (ev) {
      if (!box.contains(ev.target)) closeMenu();
    });

    // En submit: si hay chips, no mandes también q vacío ruidoso.
    form.addEventListener("submit", function () {
      syncHidden();
      if (!hidA.value && !hidW.value) {
        // solo texto: quita los hidden vacíos para no ensuciar la URL
        hidA.disabled = true;
        hidW.disabled = true;
      }
    });

    renderChips();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var forms = document.querySelectorAll("form[data-typeahead]");
    Array.prototype.forEach.call(forms, install);
  });
})();
