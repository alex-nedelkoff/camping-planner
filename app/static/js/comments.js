/* Per-trip comment bubble. Loads/posts via /api/trips/<slug>/comments without
   reloading the page. Open/closed state is remembered per device. */
(function () {
  "use strict";
  var root = document.getElementById("cp-comments");
  var slug = document.body.dataset.tripSlug;
  if (!root || !slug) return;

  var fab = root.querySelector(".cpc__fab");
  var panel = root.querySelector(".cpc__panel");
  var minBtn = root.querySelector(".cpc__min");
  var list = root.querySelector(".cpc__list");
  var form = root.querySelector(".cpc__form");
  var input = root.querySelector(".cpc__input");
  var send = root.querySelector(".cpc__send");
  var loaded = false;
  var OPEN_KEY = "cp-comments-open";

  var api = "/api/trips/" + encodeURIComponent(slug) + "/comments";

  function reltime(epoch) {
    var d = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
    if (d < 60) return "just now";
    if (d < 3600) return Math.floor(d / 60) + "m";
    if (d < 86400) return Math.floor(d / 3600) + "h";
    return Math.floor(d / 86400) + "d";
  }

  function scrollBottom() { list.scrollTop = list.scrollHeight; }

  function renderItem(c) {
    var item = document.createElement("div");
    item.className = "cpc__item";

    var head = document.createElement("div");
    head.className = "cpc__item-head";
    var author = document.createElement("span");
    author.className = "cpc__author";
    author.textContent = c.author;
    var time = document.createElement("span");
    time.className = "cpc__time";
    time.textContent = "· " + reltime(c.created_at);
    head.appendChild(author);
    head.appendChild(time);
    if (c.mine) {
      var del = document.createElement("button");
      del.type = "button";
      del.className = "cpc__del";
      del.textContent = "delete";
      del.addEventListener("click", function () { remove(c.id, item); });
      head.appendChild(del);
    }

    var body = document.createElement("div");
    body.className = "cpc__body";
    body.textContent = c.body; // textContent escapes user input

    item.appendChild(head);
    item.appendChild(body);
    return item;
  }

  function renderAll(comments) {
    list.textContent = "";
    if (!comments.length) {
      var empty = document.createElement("p");
      empty.className = "cpc__empty";
      empty.textContent = "No comments yet. Start the thread.";
      list.appendChild(empty);
      return;
    }
    comments.forEach(function (c) { list.appendChild(renderItem(c)); });
    scrollBottom();
  }

  function load() {
    list.innerHTML = '<p class="cpc__empty">Loading…</p>';
    fetch(api, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) { loaded = true; renderAll(data.comments || []); })
      .catch(function () { list.innerHTML = '<p class="cpc__empty">Could not load comments.</p>'; });
  }

  function remove(id, node) {
    fetch(api + "/" + encodeURIComponent(id), { method: "DELETE", credentials: "same-origin" })
      .then(function (r) { if (r.ok) { node.remove(); if (!list.children.length) renderAll([]); } });
  }

  function submit(e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text) return;
    send.disabled = true;
    fetch(api, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: text }),
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var empty = list.querySelector(".cpc__empty");
        if (empty) empty.remove();
        list.appendChild(renderItem(data.comment));
        scrollBottom();
        input.value = "";
        input.focus();
      })
      .catch(function () { /* leave text in box so it isn't lost */ })
      .finally(function () { send.disabled = false; });
  }

  function setOpen(open) {
    root.dataset.open = open ? "true" : "false";
    panel.hidden = !open;
    fab.setAttribute("aria-expanded", open ? "true" : "false");
    try { localStorage.setItem(OPEN_KEY, open ? "1" : "0"); } catch (e) {}
    if (open) {
      if (!loaded) load();
      input.focus();
    }
  }

  fab.addEventListener("click", function () { setOpen(true); });
  minBtn.addEventListener("click", function () { setOpen(false); });
  form.addEventListener("submit", submit);

  var remembered = false;
  try { remembered = localStorage.getItem(OPEN_KEY) === "1"; } catch (e) {}
  setOpen(remembered);
})();
