/*
 * Outlook add-in (asset v4): link the open email to an ERPNext Opportunity,
 * or create and assign one from it; pick which attachments to save; tag the
 * email in Outlook with the Opportunity number (an Outlook category); parse
 * items from the attachments like the desk's "Parse Items from File".
 *
 * Server: outlook_api.py (lookup/search/link/attachments/unlink),
 * outlook_create.py (create + assign) and outlook_parse.py (background parse
 * + review). Sign-in: auth.js.
 *
 * The pane is pinnable: on ItemChanged everything reloads for the new item;
 * `gen` stops a slow answer for the previous email landing on the new one.
 */
(function () {
  "use strict";

  var API = "opportunity_management.opportunity_management.outlook_api.";
  var CREATE = "opportunity_management.opportunity_management.outlook_create.";
  var PARSE = "opportunity_management.opportunity_management.outlook_parse.";
  var PARSE_MAX_BYTES = 15 * 1024 * 1024; // parse_files' limit for all files together
  var PARSE_POLL_MS = 4000;
  var PARSE_GIVE_UP_MS = 12 * 60 * 1000;
  var SEARCH_DELAY_MS = 300;
  var TAG_COLOR = "Preset7"; // blue

  var $ = function (id) { return document.getElementById(id); };
  var gen = 0;
  var email = null;      // what we read from the open item
  var looked = null;     // last lookup result
  var attach = { plan: [], selected: {} };  // attachment picker state
  var busy = false;

  // ── small UI helpers ───────────────────────────────────────────────────
  function show(view) {
    ["loading", "signin", "noitem", "email", "create", "parse"].forEach(function (v) {
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
    toastTimer = setTimeout(function () { t.hidden = true; }, isError ? 8000 : 4000);
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

  function debounce(fn, ms) {
    var t = null;
    return function () { clearTimeout(t); t = setTimeout(fn, ms); };
  }

  // ── Office.js wrappers ─────────────────────────────────────────────────
  function officeCall(fn) {
    return new Promise(function (resolve, reject) {
      fn(function (res) {
        if (res.status === Office.AsyncResultStatus.Succeeded) resolve(res.value);
        else {
          var err = new Error(res.error && res.error.message || "Outlook call failed");
          err.code = res.error && (res.error.name || res.error.code);
          reject(err);
        }
      });
    });
  }
  function hasApi(version) { return Office.context.requirements.isSetSupported("Mailbox", version); }

  function people(list) {
    return (list || []).map(function (r) { return { email: r.emailAddress, name: r.displayName }; });
  }

  function readItem() {
    var item = Office.context.mailbox.item;
    if (!item || item.itemType !== Office.MailboxEnums.ItemType.Message) return null;
    var from = item.from || item.sender || {};
    var mailbox = (Office.context.mailbox.userProfile || {}).emailAddress || "";
    return {
      item: item,
      subject: item.subject || "",
      from: { email: from.emailAddress || "", name: from.displayName || "" },
      to: people(item.to),
      cc: people(item.cc),
      date: item.dateTimeCreated ? new Date(item.dateTimeCreated).toISOString() : "",
      message_id: item.internetMessageId || "",
      conversation_id: item.conversationId || "",
      mailbox: mailbox,
      sent: !!(from.emailAddress && mailbox && from.emailAddress.toLowerCase() === mailbox.toLowerCase()),
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

  // ── Outlook tags (categories named after the Opportunity) ──────────────
  function canTag(item) { return hasApi("1.8") && item && item.categories && Office.context.mailbox.masterCategories; }

  function ensureMasterCategory(name) {
    var master = Office.context.mailbox.masterCategories;
    return officeCall(function (cb) { master.getAsync(cb); }).then(function (list) {
      var exists = (list || []).some(function (c) { return c.displayName === name; });
      if (exists) return;
      var color = (Office.MailboxEnums.CategoryColor || {})[TAG_COLOR] || TAG_COLOR;
      return officeCall(function (cb) { master.addAsync([{ displayName: name, color: color }], cb); })
        .catch(function (e) { if (!/duplicate/i.test(e.code + " " + e.message)) throw e; });
    });
  }

  function tag(item, names) {
    if (!canTag(item) || !names.length) return Promise.resolve(false);
    return officeCall(function (cb) { item.categories.getAsync(cb); }).then(function (current) {
      var have = (current || []).map(function (c) { return c.displayName; });
      var missing = names.filter(function (n) { return have.indexOf(n) === -1; });
      if (!missing.length) return false;
      return missing.reduce(function (p, n) { return p.then(function () { return ensureMasterCategory(n); }); }, Promise.resolve())
        .then(function () { return officeCall(function (cb) { item.categories.addAsync(missing, cb); }); })
        .then(function () { return true; });
    }).catch(function (e) {
      console.warn("Outlook tag failed", e);
      return false;
    });
  }

  function untag(item, name) {
    if (!canTag(item)) return Promise.resolve();
    return officeCall(function (cb) { item.categories.removeAsync([name], cb); })
      .catch(function (e) { console.warn("Outlook untag failed", e); });
  }

  // ── attachment picker (shared by the email view and the create form) ──
  function buildAttachmentPlan(atts) {
    var max = (OMAuth.config() || {}).max_file_size || 25 * 1024 * 1024;
    var canRead = hasApi("1.8");
    attach.plan = atts.filter(function (a) { return !a.isInline; }).map(function (a) {
      var why = null;
      if (!canRead) why = "this Outlook can't read attachments";
      else if (a.attachmentType === "cloud") why = "cloud link";
      else if (a.size > max) why = "over " + fmtSize(max);
      return { att: a, skip: why };
    });
    attach.selected = {};
    attach.plan.forEach(function (p) { if (!p.skip) attach.selected[p.att.id] = true; });
  }

  function selectedAttachments() {
    return attach.plan.filter(function (p) { return !p.skip && attach.selected[p.att.id]; });
  }

  // What the parser reads: PDF, images, .xlsx/.xlsm, .docx (not .xls/.doc).
  function parseable(name) { return /\.(pdf|jpe?g|png|webp|gif|xlsx|xlsm|docx)$/i.test(name || ""); }
  function parseableSelected() {
    return selectedAttachments().filter(function (p) { return parseable(p.att.name); });
  }

  function renderAttachments() {
    var usable = attach.plan.filter(function (p) { return !p.skip; });
    var count = selectedAttachments().length;
    $("parse-after-wrap").hidden = !parseableSelected().length;
    Array.prototype.forEach.call(document.querySelectorAll("[data-attach]"), function (box) {
      box.innerHTML = "";
      box.hidden = attach.plan.length === 0;
      if (!attach.plan.length) return;
      var head = el("div", "attach-head");
      head.appendChild(el("span", "title", "Attachments to save (" + count + " of " + usable.length + ")"));
      if (usable.length > 1) {
        var all = count < usable.length;
        var toggle = el("button", "link", all ? "Select all" : "Select none");
        toggle.addEventListener("click", function () {
          usable.forEach(function (p) { attach.selected[p.att.id] = all; });
          renderAttachments();
        });
        head.appendChild(toggle);
      }
      box.appendChild(head);
      var ul = el("ul", "checks");
      attach.plan.forEach(function (p) {
        var li = el("li", p.skip ? "skip" : "");
        var label = el("label");
        var cb = el("input");
        cb.type = "checkbox";
        cb.disabled = !!p.skip;
        cb.checked = !p.skip && !!attach.selected[p.att.id];
        cb.addEventListener("change", function () {
          attach.selected[p.att.id] = cb.checked;
          renderAttachments();
        });
        label.appendChild(cb);
        label.appendChild(el("span", "name", p.att.name));
        label.appendChild(el("span", "meta", p.skip ? "skipped: " + p.skip : fmtSize(p.att.size)));
        li.appendChild(label);
        ul.appendChild(li);
      });
      box.appendChild(ul);
    });
  }

  // ── Opportunity rows ───────────────────────────────────────────────────
  function oppUrl(name) {
    return OMAuth.config().site + "/app/opportunity/" + encodeURIComponent(name);
  }

  function tagText(prefix, value) {
    if (!value) return "";
    return value.toLowerCase().indexOf(prefix.toLowerCase()) === 0 ? value : prefix + " " + value;
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
    var line2 = [o.title, tagText("Tender", o.tender_no), tagText("INQ", o.inq_no)].filter(Boolean).join(" · ");
    if (line1) body.appendChild(el("div", "line", line1)).title = line1;
    if (line2) body.appendChild(el("div", "line", line2)).title = line2;
    var why = (o.reason_labels || []).filter(function (r) { return r !== "This email is linked"; });
    if (mode === "suggest" && why.length) body.appendChild(el("div", "why", why.join(" · ")));
    li.appendChild(body);

    var actions = el("div", "actions");
    if (mode === "linked") {
      if (selectedAttachments().length) {
        var save = el("button", "", "Save files");
        save.title = "Save the selected attachments to " + o.name;
        save.addEventListener("click", function () { link(o.name, save); });
        actions.appendChild(save);
      }
      if (parseableSelected().length) {
        var parse = el("button", "", "Parse items");
        parse.title = "Read the selected PDF / image / Excel / Word files into " + o.name + "'s items";
        parse.addEventListener("click", function () { parseFromLinked(o.name, parse); });
        actions.appendChild(parse);
      }
      var un = el("button", "", "Unlink");
      un.addEventListener("click", function () { unlink(o, un); });
      actions.appendChild(un);
    } else {
      var btn = el("button", "primary", "Link");
      btn.addEventListener("click", function () { link(o.name, btn); });
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
    if (!looked) return;
    var linked = looked.linked || [];
    var names = linkedNames();
    var suggestions = (looked.suggestions || []).filter(function (o) { return names.indexOf(o.name) === -1; });
    $("linked-block").hidden = !linked.length;
    renderList("linked", linked, "linked");
    $("suggest-block").hidden = !suggestions.length;
    renderList("suggestions", suggestions, "suggest");
    $("no-suggestions").hidden = !!(suggestions.length || linked.length);
    $("btn-create").hidden = !looked.can_create;
    renderSearchResults(lastResults);
  }

  // ── load an email ──────────────────────────────────────────────────────
  function loadEmail() {
    var my = ++gen;
    email = readItem();
    if (!email) { show("noitem"); return Promise.resolve(); }
    var other = email.sent
      ? "To " + (email.to.map(function (p) { return p.name || p.email; }).join(", ") || "—")
      : "From " + (email.from.name ? email.from.name + " <" + email.from.email + ">" : email.from.email);
    $("email-dir").textContent = other;
    $("email-subject").textContent = email.subject || "(no subject)";
    $("search").value = "";
    lastResults = [];
    looked = null;
    renderSearchResults([]);
    $("linked-block").hidden = $("suggest-block").hidden = $("no-suggestions").hidden = true;
    $("btn-create").hidden = true;
    buildAttachmentPlan(email.attachments);
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
      // Linked by a colleague or before tags existed: tag this mailbox's copy too.
      tag(email.item, linkedNames());
    }).catch(function (e) { if (my === gen) fail(e); });
  }

  // ── search ─────────────────────────────────────────────────────────────
  var lastResults = [];
  function renderSearchResults(rows) {
    lastResults = rows;
    var names = linkedNames();
    renderList("results", rows.filter(function (o) { return names.indexOf(o.name) === -1; }), "result");
  }

  var runSearch = debounce(function () {
    var q = $("search").value.trim();
    if (q.length < 2) return;
    var my = gen;
    OMAuth.api(API + "search?q=" + encodeURIComponent(q)).then(function (rows) {
      if (my !== gen || $("search").value.trim() !== q) return;
      renderSearchResults(rows || []);
      $("search-empty").hidden = (rows || []).length > 0;
    }).catch(fail);
  }, SEARCH_DELAY_MS);

  function onSearch() {
    $("search-empty").hidden = true;
    if ($("search").value.trim().length < 2) renderSearchResults([]);
    runSearch();
  }

  // ── link / unlink ──────────────────────────────────────────────────────
  function setBusy(on) {
    busy = on;
    Array.prototype.forEach.call(document.querySelectorAll(".opp button, #create-submit"), function (b) { b.disabled = on; });
  }

  function emailPayload(target) {
    return readBody(target.item, Office.CoercionType.Html).then(function (html) {
      var payload = {
        subject: target.subject, from: target.from, to: target.to, cc: target.cc, date: target.date,
        message_id: target.message_id, conversation_id: target.conversation_id, mailbox: target.mailbox,
        body_html: html,
      };
      if (html.length <= 1900000) return payload;
      return readBody(target.item, Office.CoercionType.Text).then(function (text) {
        payload.body_text = text;
        return payload;
      });
    });
  }

  /* Link the email to `opp`, save the selected attachments, tag it in
   * Outlook. Resolves with a one-line summary; attachment failures are listed. */
  function linkFlow(target, opp, progress, plan) {
    var files = plan || selectedAttachments();
    return emailPayload(target).then(function (payload) {
      return OMAuth.api(API + "link_email", { body: { opportunity: opp, email: payload } });
    }).then(function (res) {
      return saveAttachments(target, opp, res.communication, files, progress).then(function (report) {
        return tag(target.item, [opp]).then(function (tagged) {
          var extras = [];
          if (report.saved) extras.push(report.saved + " file" + (report.saved === 1 ? "" : "s") + " saved");
          if (tagged) extras.push("tagged in Outlook");
          return {
            head: (res.status === "already" ? "Already linked to " : "Linked to ") + opp,
            extras: extras,
            failed: report.failed,
            oppFiles: report.oppFiles,
          };
        });
      });
    });
  }

  function finish(summary) {
    var msg = [summary.head].concat(summary.extras).join(" · ");
    if (summary.failed.length) toast(msg + ". Not saved: " + summary.failed.join("; "), true);
    else toast(msg);
  }

  function link(opp, btn) {
    if (busy) return;
    var my = gen;
    setBusy(true);
    btn.textContent = "Linking…";
    linkFlow(email, opp, function (text) { btn.textContent = text; })
      .then(finish)
      .catch(fail)
      .then(function () {
        setBusy(false);
        if (my === gen) loadEmail();
      });
  }

  function saveAttachments(target, opp, communication, plan, progress) {
    var report = { saved: 0, failed: [], oppFiles: {} };
    var i = 0;
    function next() {
      if (i >= plan.length) return Promise.resolve(report);
      var p = plan[i++];
      progress("File " + i + "/" + plan.length + "…");
      return attachmentContent(target.item, p.att).then(function (c) {
        if (!c) return;
        return OMAuth.api(API + "add_attachment", {
          body: { communication: communication, opportunity: opp, filename: c.name, content_b64: c.b64 },
        }).then(function (r) {
          report.saved++;
          if (r && r.opportunity_file) report.oppFiles[p.att.id] = r.opportunity_file;
        });
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
    var target = email;
    setBusy(true);
    btn.textContent = "Unlinking…";
    OMAuth.api(API + "unlink_email", { body: { opportunity: o.name, message_id: target.message_id } })
      .then(function () { return untag(target.item, o.name); })
      .then(function () { toast("Removed from " + o.name); })
      .catch(fail)
      .then(function () {
        setBusy(false);
        if (my === gen) loadEmail();
      });
  }

  // ── create + assign ────────────────────────────────────────────────────
  var form = null; // {defaults, party, people: {user: bool}}

  function openCreate() {
    if (busy) return;
    var my = gen;
    var b = $("btn-create");
    b.disabled = true;
    OMAuth.api(CREATE + "create_defaults", {
      body: {
        sender: email.from.email, sender_name: email.from.name,
        to: email.to.map(function (p) { return p.email; }),
        cc: email.cc.map(function (p) { return p.email; }),
        mailbox: email.mailbox, subject: email.subject,
      },
    }).then(function (d) {
      if (my !== gen) return;
      form = { defaults: d, party: null, people: {}, extra: [] };
      (d.responsible_parties || []).forEach(function (p) { form.people[p.name] = !!p.selected; });
      if (d.parties.length) form.party = { kind: "existing", row: d.parties[0] };
      else if (d.can_create_lead) form.party = { kind: "new" };
      fillForm(d);
      show("create");
      window.scrollTo(0, 0);
    }).catch(fail).then(function () { b.disabled = false; });
  }

  function options(select, values, chosen) {
    select.innerHTML = "";
    values.forEach(function (v) {
      var o = el("option", "", v);
      o.value = v;
      if (v === chosen) o.selected = true;
      select.appendChild(o);
    });
  }

  function fillForm(d) {
    $("nl-name").value = d.new_lead.lead_name || "";
    $("nl-company").value = d.new_lead.company_name || "";
    $("nl-email").value = d.new_lead.email_id || "";
    $("f-abr").value = "";
    $("f-title").value = d.title || "";
    options($("f-group"), d.companies || [], d.default_company_group);
    $("f-group").parentNode.hidden = !(d.companies || []).length;
    options($("f-series"), d.naming_series || [], d.default_naming_series);
    $("f-tender").value = "";
    $("f-closing").value = d.expected_closing || "";
    $("f-notes").value = "";
    $("party-search").value = "";
    $("party-results").innerHTML = "";
    $("rp-filter").value = "";
    renderParties();
    renderPeople();
    renderAttachments();
  }

  function partyKey(row) { return row.type + "\u0000" + row.name; }

  function partyChoice(label, sub, checked, onPick) {
    var li = el("li");
    var lab = el("label");
    var r = el("input");
    r.type = "radio";
    r.name = "party";
    r.checked = checked;
    r.addEventListener("change", onPick);
    lab.appendChild(r);
    var text = el("span");
    text.appendChild(document.createTextNode(label));
    if (sub) text.appendChild(el("span", "sub-line", sub));
    lab.appendChild(text);
    li.appendChild(lab);
    return li;
  }

  function renderParties() {
    var d = form.defaults;
    var ul = $("party-list");
    ul.innerHTML = "";
    var rows = form.extra.concat(d.parties);
    var current = form.party && form.party.kind === "existing" ? partyKey(form.party.row) : null;
    rows.forEach(function (row) {
      var sub = [row.type, row.name !== row.display ? row.name : "", row.reason].filter(Boolean).join(" · ");
      ul.appendChild(partyChoice(row.display, sub, current === partyKey(row), function () {
        form.party = { kind: "existing", row: row };
        renderParties();
      }));
    });
    if (d.can_create_lead) {
      var nl = d.new_lead;
      ul.appendChild(partyChoice("New lead from " + (email.sent ? "recipient" : "sender"),
        [nl.lead_name, nl.email_id].filter(Boolean).join(" · "),
        !!(form.party && form.party.kind === "new"), function () {
          form.party = { kind: "new" };
          renderParties();
        }));
    }
    $("new-lead-fields").hidden = !(form.party && form.party.kind === "new");
    updateAbr();
  }

  function seriesNeedsAbr() {
    return $("f-series").value.indexOf(form.defaults.abr_placeholder || "{custom_abr}") !== -1;
  }

  function updateAbr() {
    var p = form.party;
    var need = seriesNeedsAbr() && p && (p.kind === "new" || !p.row.abr);
    $("abr-field").hidden = !need;
    if (need && !$("f-abr").value) {
      $("f-abr").value = p.kind === "new" ? (form.defaults.new_lead.abr || "") : "";
    }
  }

  var runPartySearch = debounce(function () {
    var q = $("party-search").value.trim();
    var ul = $("party-results");
    if (q.length < 2) { ul.innerHTML = ""; return; }
    OMAuth.api(CREATE + "search_parties?q=" + encodeURIComponent(q)).then(function (rows) {
      if ($("party-search").value.trim() !== q) return;
      ul.innerHTML = "";
      if (!rows.length) { ul.appendChild(el("li", "muted small", "No customers or leads found.")); return; }
      rows.forEach(function (row) {
        var sub = [row.type, row.name !== row.display ? row.name : ""].filter(Boolean).join(" · ");
        ul.appendChild(partyChoice(row.display, sub, false, function () {
          var known = form.extra.concat(form.defaults.parties).some(function (r) { return partyKey(r) === partyKey(row); });
          if (!known) form.extra.unshift(row);
          form.party = { kind: "existing", row: row };
          $("party-search").value = "";
          ul.innerHTML = "";
          renderParties();
        }));
      });
    }).catch(fail);
  }, SEARCH_DELAY_MS);

  function renderPeople() {
    var q = $("rp-filter").value.trim().toLowerCase();
    var ul = $("rp-list");
    ul.innerHTML = "";
    var list = (form.defaults.responsible_parties || []).slice().sort(function (a, b) {
      return (form.people[b.name] ? 1 : 0) - (form.people[a.name] ? 1 : 0) || a.label.localeCompare(b.label);
    });
    list.forEach(function (p) {
      if (q && (p.label + " " + p.user + " " + p.name).toLowerCase().indexOf(q) === -1) return;
      var li = el("li");
      var lab = el("label");
      var cb = el("input");
      cb.type = "checkbox";
      cb.checked = !!form.people[p.name];
      cb.addEventListener("change", function () {
        form.people[p.name] = cb.checked;
        renderPeople();
      });
      lab.appendChild(cb);
      lab.appendChild(el("span", "name", p.label));
      lab.appendChild(el("span", "meta", p.user || p.name));
      li.appendChild(lab);
      ul.appendChild(li);
    });
    var n = Object.keys(form.people).filter(function (u) { return form.people[u]; }).length;
    $("rp-count").textContent = "(" + n + " selected)";
  }

  function submitCreate() {
    if (busy) return;
    var p = form.party;
    if (!p) { toast("Pick a customer or lead", true); return; }
    var users = Object.keys(form.people).filter(function (u) { return form.people[u]; });
    if (!users.length) { toast("Pick at least one responsible party", true); return; }
    if (!$("abr-field").hidden && !$("f-abr").value.trim()) { toast("Enter an abbreviation", true); return; }
    if (p.kind === "new" && !$("nl-name").value.trim()) { toast("Enter the lead name", true); return; }

    var body = {
      naming_series: $("f-series").value,
      custom_company: $("f-group").value,
      title: $("f-title").value.trim(),
      abr: $("abr-field").hidden ? "" : $("f-abr").value.trim().toUpperCase(),
      responsible_parties: users,
      expected_closing: $("f-closing").value,
      notes: $("f-notes").value,
      tender_no: $("f-tender").value.trim(),
    };
    if (p.kind === "new") {
      body.new_lead = { lead_name: $("nl-name").value.trim(), company_name: $("nl-company").value.trim(), email_id: $("nl-email").value.trim() };
    } else {
      body.party_type = p.row.type;
      body.party_name = p.row.name;
    }

    var parsePlan = !$("parse-after-wrap").hidden && $("parse-after").checked ? parseableSelected() : [];
    if (!checkParseSize(parsePlan)) return;
    var my = gen;
    var target = email;
    var btn = $("create-submit");
    var parseNext = null;
    setBusy(true);
    btn.textContent = "Creating\u2026";
    OMAuth.api(CREATE + "create_opportunity_from_email", { body: body }).then(function (res) {
      var opp = res.opportunity;
      btn.textContent = "Linking…";
      return linkFlow(target, opp, function (text) { btn.textContent = text; }).then(function (summary) {
        summary.head = "Created " + opp + (res.lead_created ? " (new lead " + res.party_name + ")" : "") +
          ", assigned to " + users.length + " responsible part" + (users.length === 1 ? "y" : "ies") + ", email linked";
        finish(summary);
        if (parsePlan.length) parseNext = { opp: opp, files: parseFileNames(parsePlan, summary), plan: parsePlan };
      }, function (e) {
        toast("Created " + opp + ", but linking the email failed: " + e.message, true);
      });
    }).then(function () {
      if (parseNext && parseNext.files.length) return runParse(parseNext.opp, parseNext.files, parseNext.plan);
      if (my === gen) loadEmail();
    }).catch(fail).then(function () {
      setBusy(false);
      btn.textContent = "Create, assign & link";
    });
  }

  // ── parse items (background job + review, like the desk button) ───────
  var parseRun = null; // {opp, token, rows, selected, state}

  function checkParseSize(plan) {
    var total = plan.reduce(function (n, p) { return n + (p.att.size || 0); }, 0);
    if (total > PARSE_MAX_BYTES) {
      toast("The files to parse add up to " + fmtSize(total) + "; parsing takes at most " +
        fmtSize(PARSE_MAX_BYTES) + " at once. Untick some.", true);
      return false;
    }
    return true;
  }

  function parseFileNames(plan, summary) {
    return plan.map(function (p) { return summary.oppFiles[p.att.id]; }).filter(Boolean);
  }

  function parseFromLinked(opp, btn) {
    if (busy) return;
    var plan = parseableSelected();
    if (!plan.length || !checkParseSize(plan)) return;
    setBusy(true);
    btn.textContent = "Saving files…";
    // Same path as Link: idempotent for the email, files de-duplicated by content.
    linkFlow(email, opp, function (text) { btn.textContent = text; }, plan).then(function (summary) {
      if (summary.failed.length) toast("Not saved: " + summary.failed.join("; "), true);
      var files = parseFileNames(plan, summary);
      if (!files.length) throw new Error("No file could be saved to " + opp + " for parsing");
      setBusy(false);
      return runParse(opp, files, plan);
    }).catch(function (e) { setBusy(false); fail(e); });
  }

  function runParse(opp, files, plan) {
    var token = {};
    parseRun = { opp: opp, token: token, rows: [], selected: [], state: null };
    $("parse-title").textContent = "Parse items → " + opp;
    $("parse-wait").hidden = false;
    $("parse-spinner").hidden = false;
    $("parse-review").hidden = true;
    $("parse-status").textContent = "Starting…";
    $("parse-files").textContent = plan.map(function (p) { return p.att.name; }).join(", ");
    show("parse");
    window.scrollTo(0, 0);
    var started = Date.now();
    return OMAuth.api(PARSE + "start_parse", { body: { opportunity: opp, files: files } }).then(function (res) {
      var poll = function () {
        if (!parseRun || parseRun.token !== token) return;
        OMAuth.api(PARSE + "get_parse?parse_id=" + encodeURIComponent(res.parse_id)).then(function (st) {
          if (!parseRun || parseRun.token !== token) return;
          if (st.status === "done") return showReview(st);
          if (st.status === "failed" || st.status === "expired") {
            return parseFailed(st.status === "expired" ? "The parse result expired. Try again." : st.error);
          }
          var secs = Math.round((Date.now() - started) / 1000);
          $("parse-status").textContent = (st.status === "queued" ? "Waiting for a worker… " : "Reading the files… ") + secs + "s";
          if (Date.now() - started > PARSE_GIVE_UP_MS) {
            return parseFailed("Still running after 12 minutes. Try again later; a finished parse comes back from the cache.");
          }
          setTimeout(poll, PARSE_POLL_MS);
        }).catch(function (e) {
          // A dropped poll is not a failed parse: keep trying until the give-up time.
          if (Date.now() - started > PARSE_GIVE_UP_MS) return parseFailed(e.message);
          setTimeout(poll, PARSE_POLL_MS * 2);
        });
      };
      setTimeout(poll, PARSE_POLL_MS);
    }).catch(function (e) { parseFailed(e.message); });
  }

  function parseFailed(message) {
    $("parse-spinner").hidden = true;
    $("parse-status").textContent = "Parsing failed: " + (message || "unknown error");
  }

  function rowLabel(r) {
    return r.item_name || (r.description || "").replace(/<[^>]+>/g, " ").trim().slice(0, 120) || "(no name)";
  }

  function isLow(r, lowList) {
    var c = r._confidence;
    if (typeof c === "number" && c < 0.6) return true;
    if (typeof c === "string" && /low/i.test(c)) return true;
    return (lowList || []).some(function (id) {
      return String(id) === String(r._index + 1) || (r.item_name && String(id) === r.item_name);
    });
  }

  function showReview(st) {
    parseRun.state = st;
    parseRun.rows = st.rows || [];
    parseRun.selected = parseRun.rows.map(function () { return true; });
    var meta = st.meta || {};
    $("parse-wait").hidden = true;
    $("parse-review").hidden = false;
    var bits = [parseRun.rows.length + " line" + (parseRun.rows.length === 1 ? "" : "s") + " found"];
    if (meta.cached) bits.push("from the parse cache");
    if ((meta.skipped || []).length) bits.push("Skipped: " + meta.skipped.join(", "));
    $("parse-summary").textContent = bits.join(" · ");
    var extra = $("parse-extra");
    extra.innerHTML = "";
    [["Title (only if the Opportunity has none)", meta.title],
     ["Conditions → tender notes", st.conditions],
     ["Notes → tender notes", st.notes]].forEach(function (kv) {
      if (!kv[1]) return;
      var para = el("p");
      para.appendChild(el("span", "k", kv[0] + ": "));
      para.appendChild(document.createTextNode(kv[1]));
      extra.appendChild(para);
    });
    renderParseRows();
  }

  function renderParseRows() {
    var rows = parseRun.rows;
    var low = (parseRun.state.meta || {}).low_confidence || [];
    var n = parseRun.selected.filter(Boolean).length;
    $("parse-count").textContent = n + " of " + rows.length + " selected";
    $("parse-toggle").textContent = n < rows.length ? "Select all" : "Select none";
    $("parse-toggle").hidden = rows.length < 2;
    $("parse-add").disabled = busy || !n;
    $("parse-add").textContent = n ? "Add " + n + " line" + (n === 1 ? "" : "s") + " to " + parseRun.opp : "Add selected";
    var ul = $("parse-rows");
    ul.innerHTML = "";
    if (!rows.length) ul.appendChild(el("li", "muted small", "No item lines were found in these files."));
    rows.forEach(function (r, i) {
      var li = el("li");
      var lab = el("label");
      var cb = el("input");
      cb.type = "checkbox";
      cb.checked = parseRun.selected[i];
      cb.addEventListener("change", function () { parseRun.selected[i] = cb.checked; renderParseRows(); });
      lab.appendChild(cb);
      var text = el("span", "row-text");
      text.appendChild(el("span", "row-main", rowLabel(r)));
      var sub = [r.qty + " " + (r.uom || ""), r.custom_part_number && "P/N " + r.custom_part_number,
        r.brand || r.custom_manufacturer].filter(Boolean).join(" · ");
      text.appendChild(el("span", "row-sub", sub));
      if (isLow(r, low)) text.appendChild(el("span", "flag", "Low confidence — check this line"));
      lab.appendChild(text);
      li.appendChild(lab);
      ul.appendChild(li);
    });
  }

  function addParsed() {
    if (busy || !parseRun) return;
    var rows = parseRun.rows.filter(function (r, i) { return parseRun.selected[i]; });
    if (!rows.length) return;
    var st = parseRun.state;
    var btn = $("parse-add");
    setBusy(true);
    btn.disabled = true;
    btn.textContent = "Adding…";
    OMAuth.api(PARSE + "add_parsed_items", {
      body: { opportunity: parseRun.opp, rows: rows, title: (st.meta || {}).title, conditions: st.conditions, notes: st.notes },
    }).then(function (res) {
      toast("Added " + res.rows_added + " line" + (res.rows_added === 1 ? "" : "s") + " to " + res.opportunity);
      setBusy(false);
      closeParse();
    }).catch(function (e) {
      setBusy(false);
      fail(e);
      if (parseRun) renderParseRows();
    });
  }

  function closeParse() {
    parseRun = null;
    loadEmail();
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
  $("btn-create").addEventListener("click", openCreate);
  $("create-back").addEventListener("click", function () { show("email"); renderAttachments(); });
  $("create-submit").addEventListener("click", submitCreate);
  $("party-search").addEventListener("input", runPartySearch);
  $("rp-filter").addEventListener("input", renderPeople);
  $("f-series").addEventListener("change", updateAbr);
  $("parse-back").addEventListener("click", closeParse);
  $("parse-add").addEventListener("click", addParsed);
  $("parse-toggle").addEventListener("click", function () {
    var all = parseRun.selected.filter(Boolean).length < parseRun.rows.length;
    parseRun.selected = parseRun.rows.map(function () { return all; });
    renderParseRows();
  });

  Office.onReady(function (info) {
    if (info.host !== Office.HostType.Outlook) {
      $("view-loading").textContent = "Open this from Outlook.";
      return;
    }
    if (hasApi("1.5")) {
      Office.context.mailbox.addHandlerAsync(Office.EventType.ItemChanged, function () {
        // A parse in progress or under review belongs to its Opportunity, not to
        // the selected email: keep it on screen; closing it loads the new email.
        if (parseRun) return;
        if (OMAuth.signedIn()) loadEmail(); else show(Office.context.mailbox.item ? "signin" : "noitem");
      });
    }
    OMAuth.init().then(start).catch(function (e) {
      $("view-loading").textContent = e.message;
    });
  });
})();
