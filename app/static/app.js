(function () {
  "use strict";

  /* ---------- toasts ---------- */
  function dismiss(el) {
    el.classList.add("leaving");
    setTimeout(function () { el.remove(); }, 300);
  }
  function toast(message, kind) {
    var box = document.getElementById("toasts");
    if (!box) { return; }
    var el = document.createElement("div");
    el.className = "toast pointer-events-auto rounded-lg border px-4 py-3 text-sm shadow-lg " +
      (kind === "err" ? "border-red-200 bg-red-50 text-red-800" : "border-green-200 bg-green-50 text-green-800");
    el.textContent = message;
    box.appendChild(el);
    setTimeout(function () { dismiss(el); }, 6000);
  }
  document.querySelectorAll("#toasts .toast").forEach(function (el) {
    el.addEventListener("click", function () { dismiss(el); });
    setTimeout(function () { dismiss(el); }, 7000);
  });

  /* ---------- safe markdown subset (mirrors app/markdown_lite.py; escapes first) ---------- */
  function esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
  }
  function inline(s) {
    s = s.replace(/`([^`\n]+)`/g, '<code class="rounded bg-black/10 px-1 text-[0.85em]">$1</code>');
    return s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
  }
  function md(text) {
    var out = [];
    esc((text || "").trim()).split(/\n{2,}/).forEach(function (block) {
      var lines = block.split("\n");
      var bullets = lines.every(function (l) { return /^\s*[-*] +/.test(l); });
      var numbers = lines.every(function (l) { return /^\s*\d+[.)] +/.test(l); });
      if (bullets) {
        out.push('<ul class="list-disc space-y-1 pl-5">' + lines.map(function (l) {
          return "<li>" + inline(l.replace(/^\s*[-*] +/, "")) + "</li>"; }).join("") + "</ul>");
      } else if (numbers) {
        out.push('<ol class="list-decimal space-y-1 pl-5">' + lines.map(function (l) {
          return "<li>" + inline(l.replace(/^\s*\d+[.)] +/, "")) + "</li>"; }).join("") + "</ol>");
      } else {
        out.push("<p>" + lines.map(inline).join("<br>") + "</p>");
      }
    });
    return '<div class="space-y-2">' + out.join("") + "</div>";
  }
  window.lpMarkdown = md;

  /* ---------- AI panel open/close ---------- */
  var desktop = window.matchMedia("(min-width: 1024px)");
  function panel() { return document.getElementById("ai-panel"); }
  function chatInput() { return document.getElementById("chat-input"); }
  function setPanel(open) {
    if (desktop.matches) {
      document.documentElement.dataset.ai = open ? "open" : "closed";
      try { localStorage.setItem("lp_ai", open ? "open" : "closed"); } catch (e) { /* ignore */ }
    } else {
      panel().classList.toggle("mobile-open", open);
    }
    if (open && chatInput()) { chatInput().focus(); }
  }
  function isOpen() {
    return desktop.matches ? document.documentElement.dataset.ai !== "closed"
                           : panel().classList.contains("mobile-open");
  }

  /* ---------- streaming chat ---------- */
  var controller = null;
  function log() { return document.getElementById("chat-log"); }
  function csrf() { return document.querySelector('meta[name="csrf-token"]').getAttribute("content"); }
  /* Auto-scroll only while the reader is already near the bottom, so scrolling up to read is never fought. */
  var stick = true;
  function nearBottom() { var l = log(); return !l || l.scrollHeight - l.scrollTop - l.clientHeight < 80; }
  function scrollChat(force) { var l = log(); if (l && (force || stick)) { l.scrollTop = l.scrollHeight; } }
  document.addEventListener("scroll", function (e) {
    if (e.target && e.target.id === "chat-log") { stick = nearBottom(); }
  }, true);

  function updateControls() {
    var streaming = controller !== null;
    document.getElementById("chat-stop").hidden = !streaming;
    document.getElementById("chat-send").disabled = streaming;
    document.getElementById("chat-busy").classList.toggle("htmx-request", streaming);
    log().setAttribute("aria-busy", streaming ? "true" : "false");
    var last = log().lastElementChild;
    document.getElementById("chat-regen").hidden = streaming || !(last && last.hasAttribute("data-bubble"));
  }

  function addUserBubble(text) {
    var hint = log().querySelector(".empty-hint");
    if (hint) { hint.remove(); }
    var row = document.createElement("div");
    row.className = "flex justify-end";
    var b = document.createElement("div");
    b.className = "max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-indigo-600 px-3 py-2 text-sm text-white";
    b.textContent = text;
    row.appendChild(b);
    log().appendChild(row);
  }

  function addAssistantBubble() {
    var row = document.createElement("div");
    row.className = "flex items-start gap-2";
    row.setAttribute("data-bubble", "");
    row.innerHTML = '<span class="mt-1 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-indigo-100 text-xs text-indigo-700">AI</span>' +
      '<div class="max-w-[88%]"><div class="content break-words rounded-2xl rounded-tl-sm bg-slate-100 px-3 py-2 text-sm text-slate-800">' +
      '<span class="typing"><i></i><i></i><i></i></span></div>' +
      '<button type="button" data-copy class="mt-1 text-xs text-slate-400 hover:text-slate-600">Copy</button></div>';
    log().appendChild(row);
    return row;
  }

  /* Render at most once per animation frame: re-parsing the whole reply on every token would freeze the UI. */
  function scheduleRender(state) {
    if (state.raf) { return; }
    state.raf = requestAnimationFrame(function () {
      state.raf = 0;
      state.content.innerHTML = md(state.text);
      scrollChat();
    });
  }
  function flushRender(state) {
    if (state.raf) { cancelAnimationFrame(state.raf); state.raf = 0; }
    if (state.text) { state.content.innerHTML = md(state.text); }
    scrollChat();
  }
  function handleEvent(evt, state) {
    if (evt.t === "delta") {
      if (!state.text) { clearTimeout(state.slow); }
      state.text += evt.x;
      scheduleRender(state);
    } else if (evt.t === "error") {
      clearTimeout(state.slow);
      state.failed = true;
      state.text = evt.x;
      state.content.classList.add("text-red-700");
      flushRender(state);
    } else if (evt.t === "done") {
      state.done = true;
    }
  }

  function stream(form, regenerate) {
    if (controller) { return; }
    var input = chatInput();
    var data = new FormData(form);
    if (regenerate) {
      data.set("regenerate", "1");
      data.delete("message");
      var last = log().lastElementChild;
      if (last && last.hasAttribute("data-bubble")) { last.remove(); }
    } else {
      var text = input.value.trim();
      if (!text) { return; }
      addUserBubble(text);
      input.value = "";
    }
    var row = addAssistantBubble();
    var state = { text: "", content: row.querySelector(".content"), raf: 0, done: false, failed: false, slow: 0 };
    /* If nothing arrives for 2 seconds the model is probably loading: say so instead of looking frozen. */
    state.slow = setTimeout(function () {
      if (!state.text) {
        var hint = document.createElement("div");
        hint.className = "mt-1 text-xs text-slate-500";
        hint.textContent = "Waking up the model, the first reply can take a few seconds…";
        state.content.appendChild(hint);
      }
    }, 2000);
    controller = new AbortController();
    stick = true;
    updateControls();
    scrollChat(true);
    fetch("/assistant/stream", { method: "POST", body: data, headers: { "X-CSRF-Token": csrf() },
                                 signal: controller.signal })
      .then(function (resp) {
        if (!resp.ok) { throw new Error(resp.status === 403 ? "Session expired. Reload the page." : "Request failed (" + resp.status + ")."); }
        var reader = resp.body.getReader();
        var decoder = new TextDecoder();
        var buffer = "";
        function pump() {
          return reader.read().then(function (r) {
            if (r.done) { return; }
            buffer += decoder.decode(r.value, { stream: true });
            var parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
            buffer = parts.pop();
            parts.forEach(function (chunk) {
              if (chunk.indexOf("data: ") === 0) {
                try { handleEvent(JSON.parse(chunk.slice(6)), state); } catch (e) { /* ignore malformed */ }
              }
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) {
        if (err.name === "AbortError") { return; }
        state.failed = true;
        if (state.text) {
          /* keep what already arrived and say the stream broke */
          flushRender(state);
          var note = document.createElement("div");
          note.className = "mt-2 text-xs text-red-700";
          note.textContent = "The connection was interrupted. You can press Regenerate.";
          state.content.appendChild(note);
        } else {
          state.content.classList.add("text-red-700");
          state.content.textContent = err.message || "Network error. Check your connection.";
        }
      })
      .finally(function () {
        clearTimeout(state.slow);
        flushRender(state);
        if (!state.done && !state.failed && state.text && !(controller && controller.signal.aborted)) {
          var cut = document.createElement("div");
          cut.className = "mt-2 text-xs text-red-700";
          cut.textContent = "The reply ended early. You can press Regenerate.";
          state.content.appendChild(cut);
        }
        if (!state.text && state.content.querySelector(".typing")) { state.content.textContent = "(no reply)"; }
        controller = null;
        updateControls();
        if (input) { input.focus(); }
      });
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.id === "chat-form") { e.preventDefault(); stream(form, false); return; }
    if (form.hasAttribute && form.hasAttribute("data-busy")) {
      var btn = form.querySelector("button");
      if (btn) {
        var label = form.getAttribute("data-busy");
        setTimeout(function () { btn.disabled = true; btn.textContent = label; }, 0);
      }
    }
  });

  document.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "chat-log") {
      var l = e.detail.target;
      var hint = l.querySelector(".empty-hint");
      if (hint && l.children.length > 1) { hint.remove(); }
      scrollChat();
      updateControls();
    }
  });
  document.addEventListener("htmx:responseError", function (e) {
    var status = e.detail.xhr ? e.detail.xhr.status : "";
    toast(status === 403 ? "Session expired. Reload the page." : "Request failed (" + status + ").", "err");
  });
  document.addEventListener("htmx:sendError", function () { toast("Network error. Check your connection.", "err"); });

  /* ---------- clicks ---------- */
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t.closest) { return; }
    var chip = t.closest(".chip");
    if (chip) { chatInput().value = chip.getAttribute("data-q"); chatInput().focus(); return; }
    if (t.closest("#ai-toggle")) { setPanel(!isOpen()); return; }
    if (t.closest("#ai-close")) { setPanel(false); return; }
    if (t.closest("#chat-stop")) { if (controller) { controller.abort(); } return; }
    if (t.closest("#chat-regen")) { stream(document.getElementById("chat-form"), true); return; }
    var copy = t.closest("[data-copy]");
    if (copy) {
      var sel = copy.getAttribute("data-copy-target");
      var source = sel ? document.querySelector(sel) : copy.closest("[data-bubble]");
      var done = function () { copy.textContent = "Copied"; setTimeout(function () { copy.textContent = "Copy"; }, 1500); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(source.innerText).then(done, function () { toast("Copy failed. Select the text and copy it manually.", "err"); });
      } else {
        toast("Copy needs HTTPS. Select the text and copy it manually.", "err");
      }
      return;
    }
    var tab = t.closest("[data-tab-btn]");
    if (tab) {
      var name = tab.getAttribute("data-tab-btn");
      document.querySelectorAll("[data-tab-btn]").forEach(function (b) {
        var on = b.getAttribute("data-tab-btn") === name;
        b.classList.toggle("border-indigo-600", on);
        b.classList.toggle("text-indigo-700", on);
        b.classList.toggle("border-transparent", !on);
        b.classList.toggle("text-slate-500", !on);
      });
      document.querySelectorAll("[data-tab-panel]").forEach(function (p) {
        p.hidden = p.getAttribute("data-tab-panel") !== name;
      });
    }
  });

  /* ---------- keyboard ---------- */
  document.addEventListener("keydown", function (e) {
    var t = e.target;
    if (t && t.id === "chat-input" && e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      document.getElementById("chat-form").requestSubmit();
      return;
    }
    if (e.key === "Escape" && controller) { controller.abort(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPanel(true); }
  });

  /* Ask the server to preload the local model as soon as an admin page opens (server throttles this). */
  if (document.documentElement.hasAttribute("data-ai-warm")) {
    fetch("/assistant/warm", { method: "POST", headers: { "X-CSRF-Token": csrf() } }).catch(function () { /* best effort */ });
  }

  window.addEventListener("pageshow", function () {
    document.querySelectorAll("form[data-busy] button").forEach(function (b) { b.disabled = false; });
  });
})();
