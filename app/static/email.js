/* Operator email: an "Email" button with a confirm dialog, and a chat command.
   Chat command: start a message with "send" or "email", include an address, e.g.
     send hi to name@example.com
     email name@example.com saying the meeting moved to 3pm
   A normal question that merely contains an address is NOT sent as an email. */
(function () {
  "use strict";
  var EMAIL = /[^\s@<>,;:]+@[^\s@<>,;:]+\.[^\s@<>,;:]*[^\s@<>,;:.]/;

  function csrfToken() {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.getAttribute("content") : "";
  }

  function banner(text, bad) {
    var d = document.createElement("div");
    d.textContent = text;
    d.setAttribute("role", "status");
    d.style.cssText = "position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:99999;padding:10px 16px;border-radius:8px;color:#fff;font-size:14px;max-width:90vw;background:" + (bad ? "#b91c1c" : "#15803d");
    document.body.appendChild(d);
    setTimeout(function () { d.remove(); }, bad ? 9000 : 5000);
  }

  function post(to, subject, body) {
    var data = new FormData();
    data.append("confirm_send", "yes");
    data.append("recipient", to);
    data.append("subject", subject);
    data.append("body", body);
    return fetch("/assistant/send-email", { method: "POST", body: data, headers: { "X-CSRF-Token": csrfToken() } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          return { ok: r.ok, message: r.ok ? "Email sent to " + to : (j.detail || "Send failed (" + r.status + ").") };
        });
      })
      .catch(function () { return { ok: false, message: "Network error. Is the server running?" }; });
  }

  /* ---------- chat command ---------- */
  function parse(text) {
    if (!/^\s*(send|email|mail)\b/i.test(text)) { return null; }
    var m = text.match(EMAIL);
    if (!m) { return null; }
    var to = m[0];
    var rest = text.replace(to, " ");
    var s = rest.match(/\b(?:saying|says|say|tell them|telling them|message)\s*:?\s+([\s\S]+)$/i);
    var body = s ? s[1] : rest.replace(/^\s*(send|email|mail)\s+(an?\s+)?(email|message)?\s*(to)?\s*/i, "");
    body = body.replace(/\s+/g, " ").trim();
    return { to: to, body: body };
  }

  function tryChatCommand() {
    var input = document.getElementById("chat-input");
    if (!input) { return false; }
    var cmd = parse(input.value);
    if (!cmd) { return false; }
    if (!cmd.body) { banner("What should the email say? Example: send hi to name@example.com", true); return true; }
    if (!window.confirm("Send this email to " + cmd.to + "?\n\n" + cmd.body)) { return true; }
    banner("Sending to " + cmd.to + "...");
    post(cmd.to, cmd.body.slice(0, 60), cmd.body).then(function (res) { banner(res.message, !res.ok); });
    input.value = "";
    return true;
  }

  document.addEventListener("submit", function (e) {
    if (e.target && e.target.id === "chat-form" && tryChatCommand()) { e.preventDefault(); e.stopImmediatePropagation(); }
  }, true);
  document.addEventListener("keydown", function (e) {
    if (e.target && e.target.id === "chat-input" && e.key === "Enter" && !e.shiftKey && !e.isComposing && tryChatCommand()) {
      e.preventDefault(); e.stopImmediatePropagation();
    }
  }, true);

  /* ---------- Email button + dialog ---------- */
  function lastReply() {
    var bubbles = document.querySelectorAll("#chat-log [data-bubble]");
    return bubbles.length ? bubbles[bubbles.length - 1].innerText.trim() : "";
  }

  function labelled(text, el) {
    var w = document.createElement("label");
    w.style.cssText = "display:block;margin-bottom:10px;font-size:13px;font-weight:600";
    w.textContent = text;
    el.style.cssText = "display:block;width:100%;margin-top:4px;padding:8px;border:1px solid #cbd5e1;border-radius:6px;font:inherit;font-weight:400;box-sizing:border-box";
    w.appendChild(el);
    return w;
  }

  function openDialog() {
    var back = document.createElement("div");
    back.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:9999;display:flex;align-items:center;justify-content:center";
    var box = document.createElement("div");
    box.style.cssText = "background:#fff;color:#0f172a;border-radius:12px;padding:20px;width:min(560px,92vw);max-height:90vh;overflow:auto";
    var to = document.createElement("input"); to.type = "email"; to.placeholder = "name@example.com";
    var subject = document.createElement("input"); subject.type = "text";
    var body = document.createElement("textarea"); body.rows = 10; body.value = lastReply();
    var ok = document.createElement("input"); ok.type = "checkbox";
    var okRow = document.createElement("label");
    okRow.style.cssText = "display:flex;gap:8px;align-items:center;font-size:13px;margin:6px 0 12px";
    okRow.appendChild(ok);
    okRow.appendChild(document.createTextNode("I reviewed this email and want to send it now."));
    var send = document.createElement("button"); send.type = "button"; send.textContent = "Send email"; send.disabled = true;
    var cancel = document.createElement("button"); cancel.type = "button"; cancel.textContent = "Cancel";
    [send, cancel].forEach(function (b) { b.style.cssText = "padding:8px 14px;border-radius:6px;border:1px solid #cbd5e1;margin-right:8px;cursor:pointer;background:#fff"; });
    var msg = document.createElement("div"); msg.style.cssText = "font-size:13px;margin-top:10px";
    var h = document.createElement("h3"); h.textContent = "Send email"; h.style.cssText = "margin:0 0 12px;font-weight:700;font-size:16px";
    box.append(h, labelled("To", to), labelled("Subject", subject), labelled("Body", body), okRow, send, cancel, msg);
    back.appendChild(box);
    document.body.appendChild(back);
    to.focus();
    function close() { back.remove(); }
    ok.addEventListener("change", function () { send.disabled = !ok.checked; });
    cancel.addEventListener("click", close);
    back.addEventListener("click", function (e) { if (e.target === back) { close(); } });
    send.addEventListener("click", function () {
      send.disabled = true; msg.style.color = "#334155"; msg.textContent = "Sending...";
      post(to.value, subject.value, body.value).then(function (res) {
        msg.style.color = res.ok ? "#15803d" : "#b91c1c";
        msg.textContent = res.message;
        if (res.ok) { setTimeout(close, 1500); } else { send.disabled = !ok.checked; }
      });
    });
  }

  function install() {
    var regen = document.getElementById("chat-regen");
    if (!regen || document.getElementById("chat-email")) { return; }
    var btn = regen.cloneNode(false);
    btn.id = "chat-email"; btn.type = "button"; btn.hidden = false; btn.textContent = "Email";
    btn.removeAttribute("aria-label");
    btn.setAttribute("aria-label", "Email the last AI reply");
    btn.addEventListener("click", openDialog);
    regen.parentNode.insertBefore(btn, regen);
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", install); }
  else { install(); }
})();
