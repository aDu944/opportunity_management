/*
 * Outlook add-in, Phase 1: link the open email to an ERPNext Opportunity.
 * Server side: opportunity_management/outlook_api.py. Sign-in: auth.js.
 *
 * The pane is pinnable: when the user moves to another email, Outlook fires
 * ItemChanged and everything is reloaded for the new item. `gen` guards
 * against a slow answer for the previous email landing on the new one.
 */
(function () {
  "use strict";

  var API = "opportunity_management.opportunity_management.outlook_api.";
  var SEARCH_DELAY_MS = 300;

  var $ = function (id) { return document.getElementById(id); };
  var gen = 0;
  var email = null;      // what we read from the open item
  var looked = null;     // last lookup result
  var searchTimer = null;
  var busy = false;

  // ── small UI helpers ───────────────────────────────────────────────────
  function show(view) {
    ["loading", "signin", "noitem", "email"].forEach(function (v) {
      $("view-" + v).hidden = v !== view;
    });
    $("btn-signout").hidden = !OMAuth.signedIn();
  }

  var toastTimer = null;
  function toast(text, isError) {
    var t = $("toast");
    t.textContent = text;
    t.className = "toast" + (isError ? " error" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.hidden = true; }, isError ? 7000 : 3500);
  }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function fmtSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function fail(e) {
    if (!OMAuth.signedIn()) {
      show("signin");
      toast(e.message, true);
      return;
    }
    toast(e.message || String(e), true);
  }

  // ── Office.js wrappers ─────────────────────────────────────────────────
  function officeCall(fn) {
    return new Promise(function (resolve, reject) {
      fn(function (res) {
        if (res.status === Office.AsyncResultStatus.Succeeded) resolve(res.value);
        else reject(new Error(res.error && res.error.message || "Outlook call failed"));
      });
    });
  }

  function people(list) {
    return (list || []).map(function (r) { return { email: r.emailAddress, name: r.displayName }; });
  }

  function readItem() {
    var item = Office.context.mailbox.item;
    if (!item || item.itemType !== Office.MailboxEnums.ItemType.Message) return null;
    var from = item.from || item.sender || {};
    return {
      item: item,
      subject: item.subject || "",
      from: { email: from.emailAddress || "", name: from.displayName || "" },
      to: people(item.to),
      cc: people(item.cc),
      date: item.dateTimeCreated ? new Date(item.dateTimeCreated).toISOString() : "",
      message_id: item.internetMessageId || "",
      conversation_id: item.conversationId || "",
      mailbox: (Office.context.mailbox.userProfile || {}).emailAddress || "",
      attachments: (item.attachments || []).slice(),
    };
  }

  function readHeaders(item) {
    if (!item.getAllInternetHeadersAsync) return Promise.resolve("");
    return officeCall(function (cb) { item.getAllInternetHeadersAsync(cb); }).catch(function () { return ""; });
  }

  function readBody(item, type) {
    return officeCall(function (cb) { item.body.getAsync(type, cb); });
  }

  function utf8ToBase64(text) {
    var bytes = new TextEncoder().encode(text);
    var s = "";
    for (var i = 0; i < bytes.length; i += 0x8000) {
      s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(s);
  }

  function attachmentContent(item, att) {
    return officeCall(function (cb) { item.getAttachmentContentAsync(att.id, cb); }).then(function (v) {
      var F = Office.MailboxEnums.AttachmentContentFormat;
      if (v.format === F.Base64) return { name: att.name, b64: v.content };
      if (v.format === F.Eml) return { name: /\.eml$/i.test(att.name) ? att.name : att.name + ".eml", b64: utf8ToBase64(v.content) };
      if (v.format === F.ICalendar) return { name: /\.ics$/i.test(att.name) ? att.name : att.name + ".ics", b64: utf8ToBase64(v.content) };
      return null; // cloud link: nothing to copy
    });
  }

  // ── attachments box ────────────────────────────────────────────────────
  function attachmentPlan(atts) {
    var max = (OMAuth.config() || {}).max_file_size || 25 * 1024 * 1024;
    var canRead = Office.context.requirements.isSetSupported("Mailbox", "1.8");
    return atts.map(function (a) {
      var why = null;
      if (!canRead) why = "this Outlook can't read attachments";
      else if (a.isInline) why = "inline image";
      else if (a.attachmentType === "cloud") why = "cloud link";
      else if (a.size > max) why = "over " + fmtSize(max);
      return { att: a, skip: why };
    });
  }

  function renderAttachments() {
    var plan = attachmentPlan(email.attachments).filter(function (p) { return p.skip !== "inline image"; });
    var usable = plan.filter(function (p) { return !p.skip; });
    $("attach-block").hidden = plan.length === 0;
    if (!plan.length) return;
    $("attach-label").textContent = usable.length
      ? "Also save " + usable.length + " attachment" + (usable.length === 1 ? "" : "s") + " to ERPNext"
      : "No attachments can be saved";
    $("attach-toggle").disabled = !usable.length;
    $("attach-toggle").checked = usable.length > 0;
    var ul = $("attach-list");
    ul.innerHTML = "";
    plan.forEach(function (p) {
      var li = el("li", p.skip ? "skip" : "", p.att.name + " (" + fmtSize(p.att.size) + ")");
      if (p.skip) li.title = p.skip;
      ul.appendChild(li);
      if (p.skip) ul.appendChild(el("li", "", " → skipped: " + p.skip));
    });
  }

  // ── Opportunity rows ───────────────────────────────────────────────────
  function oppUrl(name) {
    return OMAuth.config().site + "/app/opportunity/" + encodeURIComponent(name);
  }

  function renderOpp(o, mode) {
    var li = el("li", "opp" + (o.closed ? " closed" : "") + (mode === "linked" ? " linked" : ""));
    var body = el("div", "body");
    var top = el("div", "top");
    var a = el("a", "name", o.name);
    a.href = oppUrl(o.name);
    a.target = "_blank";
    a.rel = "noopener";
    top.appendChild(a);
    if (o.status) top.appendChild(el("span", "status", o.status));
    body.appendChild(top);
    var line1 = [o.party, o.company].filter(Boolean).join(" · ");
    var tag = function (prefix, value) {
      if (!value) return "";
      return value.toLowerCase().indexOf(prefix.toLowerCase()) === 0 ? value : prefix + " " + value;
    };
    var line2 = [o.title, tag("Tender", o.tender_no), tag("INQ", o.inq_no)].filter(Boolean).join(" · ");
    if (line1) body.appendChild(el("div", "line", line1)).title = line1;
    if (line2) body.appendChild(el("div", "line", line2)).title = line2;
    var why = (o.reason_labels || []).filter(function (r) { return r !== "This email is linked"; });
    if (mode === "suggest" && why.length) body.appendChild(el("div", "why", why.join(" · ")));
    li.appendChild(body);

    var actions = el("div", "actions");
    if (mode === "linked") {
      var un = el("button", "", "Unlink");
      un.addEventListener("click", function () { unlink(o, un); });
      actions.appendChild(un);
    } else {
      var btn = el("button", "primary", "Link");
      btn.addEventListener("click", function () { link(o, btn); });
      actions.appendChild(btn);
    }
    li.appendChild(actions);
    return li;
  }

  function renderList(id, rows, mode) {
    var ul = $(id);
    ul.innerHTML = "";
    rows.forEach(function (o) { ul.appendChild(renderOpp(o, mode)); });
  }

  function linkedNames() {
    return (looked && looked.linked || []).map(function (o) { return o.name; });
  }

  function renderLookup() {
    var linked = looked.linked || [];
    var names = linkedNames();
    var suggestions = (looked.suggestions || []).filter(function (o) { return names.indexOf(o.name) === -1; });
    $("linked-block").hidden = !linked.length;
    renderList("linked", linked, "linked");
    $("suggest-block").hidden = !suggestions.length;
    renderList("suggestions", suggestions, "suggest");
    $("no-suggestions").hidden = !!(suggestions.length || linked.length);
    renderSearchResults(lastResults);
  }

  // ── load an email ──────────────────────────────────────────────────────
  function loadEmail() {
    var my = ++gen;
    email = readItem();
    if (!email) { show("noitem"); return Promise.resolve(); }
    var sent = email.from.email && email.mailbox &&
      email.from.email.toLowerCase() === email.mailbox.toLowerCase();
    var other = sent
      ? "To " + (email.to.map(function (p) { return p.name || p.email; }).join(", ") || "—")
      : "From " + (email.from.name ? email.from.name + " <" + email.from.email + ">" : email.from.email);
    $("email-dir").textContent = other;
    $("email-subject").textContent = email.subject || "(no subject)";
    $("search").value = "";
    lastResults = [];
    renderSearchResults([]);
    $("linked-block").hidden = $("suggest-block").hidden = $("no-suggestions").hidden = true;
    renderAttachments();
    show("email");

    return readHeaders(email.item).then(function (headers) {
      return OMAuth.api(API + "lookup", {
        body: {
          sender: email.from.email,
          to: email.to.map(function (p) { return p.email; }),
          cc: email.cc.map(function (p) { return p.email; }),
          mailbox: email.mailbox,
          message_id: email.message_id,
          conversation_id: email.conversation_id,
          headers: headers,
        },
      });
    }).then(function (res) {
      if (my !== gen) return;
      looked = res;
      renderLookup();
    }).catch(function (e) { if (my === gen) fail(e); });
  }

  // ── search ─────────────────────────────────────────────────────────────
  var lastResults = [];
  function renderSearchResults(rows) {
    lastResults = rows;
    var names = linkedNames();
    renderList("results", rows.filter(function (o) { return names.indexOf(o.name) === -1; }), "result");
  }

  function onSearch() {
    clearTimeout(searchTimer);
    var q = $("search").value.trim();
    $("search-empty").hidden = true;
    if (q.length < 2) { renderSearchResults([]); return; }
    var my = gen;
    searchTimer = setTimeout(function () {
      OMAuth.api(API + "search?q=" + encodeURIComponent(q)).then(function (rows) {
        if (my !== gen || $("search").value.trim() !== q) return;
        renderSearchResults(rows || []);
        $("search-empty").hidden = (rows || []).length > 0;
      }).catch(fail);
    }, SEARCH_DELAY_MS);
  }

  // ── link / unlink ──────────────────────────────────────────────────────
  function setBusy(on) {
    busy = on;
    Array.prototype.forEach.call(document.querySelectorAll(".opp button"), function (b) { b.disabled = on; });
  }

  function link(o, btn) {
    if (busy) return;
    var my = gen;
    var target = email;
    setBusy(true);
    btn.textContent = "Linking…";
    readBody(target.item, Office.CoercionType.Html).then(function (html) {
      var payload = {
        subject: target.subject, from: target.from, to: target.to, cc: target.cc, date: target.date,
        message_id: target.message_id, conversation_id: target.conversation_id, mailbox: target.mailbox,
        body_html: html,
      };
      if (html.length > 1900000) {
        return readBody(target.item, Office.CoercionType.Text).then(function (text) {
          payload.body_text = text;
          return payload;
        });
      }
      return payload;
    }).then(function (payload) {
      return OMAuth.api(API + "link_email", { body: { opportunity: o.name, email: payload } });
    }).then(function (res) {
      var wanted = $("attach-toggle").checked && !$("attach-block").hidden
        ? attachmentPlan(target.attachments).filter(function (p) { return !p.skip; }) : [];
      return saveAttachments(target, o.name, res.communication, wanted, btn).then(function (report) {
        var msg = res.status === "already" ? "Already linked to " + o.name : "Linked to " + o.name;
        if (report.saved) msg += " · " + report.saved + " attachment" + (report.saved === 1 ? "" : "s") + " saved";
        if (report.failed.length) {
          toast(msg + ". Not saved: " + report.failed.join("; "), true);
        } else {
          toast(msg);
        }
      });
    }).catch(fail).then(function () {
      setBusy(false);
      if (my === gen) loadEmail();
    });
  }

  function saveAttachments(target, opp, communication, plan, btn) {
    var report = { saved: 0, failed: [] };
    var i = 0;
    function next() {
      if (i >= plan.length) return Promise.resolve(report);
      var p = plan[i++];
      btn.textContent = "Attachment " + i + "/" + plan.length + "…";
      return attachmentContent(target.item, p.att).then(function (c) {
        if (!c) return;
        return OMAuth.api(API + "add_attachment", {
          body: { communication: communication, opportunity: opp, filename: c.name, content_b64: c.b64 },
        }).then(function () { report.saved++; });
      }).catch(function (e) {
        report.failed.push(p.att.name + " (" + e.message + ")");
      }).then(next);
    }
    return next();
  }

  function unlink(o, btn) {
    if (busy) return;
    if (!window.confirm("Remove this email from " + o.name + "?")) return;
    var my = gen;
    setBusy(true);
    btn.textContent = "Unlinking…";
    OMAuth.api(API + "unlink_email", { body: { opportunity: o.name, message_id: email.message_id } })
      .then(function () { toast("Removed from " + o.name); })
      .catch(fail)
      .then(function () {
        setBusy(false);
        if (my === gen) loadEmail();
      });
  }

  // ── sign-in / boot ─────────────────────────────────────────────────────
  function whoami() {
    return OMAuth.api("frappe.auth.get_logged_user").then(function (user) {
      $("who").textContent = user;
    });
  }

  function start() {
    if (!OMAuth.signedIn()) { show("signin"); return; }
    whoami().then(loadEmail).catch(fail);
  }

  $("btn-signin").addEventListener("click", function () {
    var b = $("btn-signin");
    b.disabled = true;
    OMAuth.signIn().then(start).catch(function (e) { toast(e.message, true); }).then(function () { b.disabled = false; });
  });
  $("btn-signout").addEventListener("click", function () {
    OMAuth.signOut();
    $("who").textContent = "";
    show("signin");
  });
  $("btn-reload").addEventListener("click", function () { if (OMAuth.signedIn()) loadEmail(); });
  $("search").addEventListener("input", onSearch);

  Office.onReady(function (info) {
    if (info.host !== Office.HostType.Outlook) {
      $("view-loading").textContent = "Open this from Outlook.";
      return;
    }
    if (Office.context.requirements.isSetSupported("Mailbox", "1.5")) {
      Office.context.mailbox.addHandlerAsync(Office.EventType.ItemChanged, function () {
        if (OMAuth.signedIn()) loadEmail(); else show(Office.context.mailbox.item ? "signin" : "noitem");
      });
    }
    OMAuth.init().then(start).catch(function (e) {
      $("view-loading").textContent = e.message;
    });
  });
})();
