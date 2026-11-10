/*
 * Outlook add-in, Phase 0: connection + sign-in test panel.
 *
 * Proves, in each Outlook client, that:
 *   1. Outlook loads this page from the ERPNext site (framing allowed);
 *   2. the Office.js mailbox API can read the open email;
 *   3. ERPNext OAuth (Authorization Code + PKCE, no client secret) works
 *      through an Office dialog: login -> code -> token;
 *   4. the bearer token calls the ERPNext API as that user, and refreshes.
 *
 * Every request uses credentials: "omit" so a Desk session cookie (shared
 * by the desktop WebView) can never turn a token call into a CSRF-checked
 * session request; the bearer token is the only credential.
 */
(function () {
  "use strict";

  var CONFIG_URL = "/api/method/opportunity_management.opportunity_management.outlook_addin.get_config";
  var STORE_KEY = "om_outlook_tokens_v1";
  var REFRESH_MARGIN_MS = 60 * 1000;

  var config = null;
  var tokens = null;
  var checks = [];
  var env = {};
  var itemInfo = {};

  var $ = function (id) { return document.getElementById(id); };

  // ── checks list ────────────────────────────────────────────────────────
  function check(key, label) {
    var c = { key: key, label: label, state: "pending", detail: "" };
    checks.push(c);
    render();
    return c;
  }
  function set(c, state, detail) {
    c.state = state;
    c.detail = detail || "";
    render();
  }
  function find(key) {
    for (var i = 0; i < checks.length; i++) if (checks[i].key === key) return checks[i];
    return null;
  }
  function upsert(key, label) {
    return find(key) || check(key, label);
  }
  var MARKS = { ok: "✓", fail: "✗", warn: "!", pending: "…" };

  function render() {
    var ul = $("checks");
    ul.innerHTML = "";
    checks.forEach(function (c) {
      var li = document.createElement("li");
      li.className = c.state;
      var mark = document.createElement("span");
      mark.className = "mark";
      mark.textContent = MARKS[c.state];
      var body = document.createElement("span");
      body.textContent = c.label;
      if (c.detail) {
        var d = document.createElement("span");
        d.className = "detail";
        d.textContent = " — " + c.detail;
        body.appendChild(d);
      }
      li.appendChild(mark);
      li.appendChild(body);
      ul.appendChild(li);
    });
    renderReport();
  }

  function renderItem() {
    var dl = $("item");
    dl.innerHTML = "";
    Object.keys(itemInfo).forEach(function (k) {
      var dt = document.createElement("dt");
      dt.textContent = k;
      var dd = document.createElement("dd");
      dd.textContent = itemInfo[k] == null ? "—" : String(itemInfo[k]);
      dl.appendChild(dt);
      dl.appendChild(dd);
    });
    renderReport();
  }

  function renderReport() {
    var lines = ["Outlook add-in Phase 0 report", "time: " + new Date().toISOString()];
    Object.keys(env).forEach(function (k) { lines.push(k + ": " + env[k]); });
    lines.push("");
    checks.forEach(function (c) {
      lines.push("[" + c.state.toUpperCase() + "] " + c.label + (c.detail ? " — " + c.detail : ""));
    });
    lines.push("");
    lines.push("item fields present: " + Object.keys(itemInfo).filter(function (k) {
      return itemInfo[k] != null && itemInfo[k] !== "";
    }).join(", "));
    $("report").value = lines.join("\n");
  }

  // ── storage (partitioned/blocked storage must not break the pane) ──────
  function loadTokens() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }
  function saveTokens(t) {
    tokens = t;
    try {
      if (t) window.localStorage.setItem(STORE_KEY, JSON.stringify(t));
      else window.localStorage.removeItem(STORE_KEY);
      return true;
    } catch (e) {
      return false;
    }
  }

  // ── PKCE helpers ───────────────────────────────────────────────────────
  function b64url(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function randomString(n) {
    var a = new Uint8Array(n);
    crypto.getRandomValues(a);
    return b64url(a);
  }
  function sha256(text) {
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(text)).then(function (buf) {
      return b64url(new Uint8Array(buf));
    });
  }

  // ── HTTP ───────────────────────────────────────────────────────────────
  function form(url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams(data).toString(),
    }).then(function (r) {
      return r.text().then(function (text) {
        var json = null;
        try { json = JSON.parse(text); } catch (e) { /* not JSON */ }
        if (!r.ok || !json || json.error) {
          var why = (json && (json.error_description || json.error || json.exc_type || json.message)) || text.slice(0, 200);
          throw new Error("HTTP " + r.status + ": " + why);
        }
        return json;
      });
    });
  }

  function storeTokenResponse(t) {
    if (!t.access_token) throw new Error("no access_token in response");
    var stored = saveTokens({
      access_token: t.access_token,
      refresh_token: t.refresh_token || (tokens && tokens.refresh_token) || null,
      expires_at: Date.now() + (Number(t.expires_in) || 3600) * 1000,
      scope: t.scope || "",
    });
    var s = upsert("storage", "Token kept on this device");
    set(s, stored ? "ok" : "warn", stored ? "localStorage" : "storage blocked: sign-in lasts until the pane closes");
  }

  function refresh() {
    if (!tokens || !tokens.refresh_token) return Promise.reject(new Error("no refresh token"));
    return form(config.token_url, {
      grant_type: "refresh_token",
      refresh_token: tokens.refresh_token,
      client_id: config.client_id,
    }).then(storeTokenResponse);
  }

  // Bearer GET; refreshes once on expiry or 401.
  function api(path) {
    var ready = tokens && tokens.expires_at - Date.now() < REFRESH_MARGIN_MS ? refresh() : Promise.resolve();
    var call = function () {
      return fetch(config.site + path, {
        credentials: "omit",
        headers: { Authorization: "Bearer " + tokens.access_token, Accept: "application/json" },
      });
    };
    return ready.then(call).then(function (r) {
      if (r.status !== 401 && r.status !== 403) return r;
      return refresh().then(call);
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (json) {
        if (!r.ok) throw new Error("HTTP " + r.status + ": " + (json.exc_type || json.message || "error"));
        return json;
      });
    });
  }

  // ── sign-in through an Office dialog ───────────────────────────────────
  function signIn() {
    var c = upsert("signin", "Sign-in dialog returns an authorization code");
    var t = upsert("token", "Code exchanged for a token (PKCE, no secret)");
    set(c, "pending");
    set(t, "pending");
    $("btn-signin").disabled = true;

    var verifier = randomString(48);
    var state = randomString(16);

    sha256(verifier).then(function (challenge) {
      var url = config.authorize_url + "?" + new URLSearchParams({
        client_id: config.client_id,
        response_type: "code",
        redirect_uri: config.redirect_uri,
        scope: config.scopes,
        state: state,
        code_challenge: challenge,
        code_challenge_method: "S256",
      }).toString();

      Office.context.ui.displayDialogAsync(url, { height: 70, width: 35, promptBeforeOpen: false }, function (res) {
        if (res.status !== Office.AsyncResultStatus.Succeeded) {
          set(c, "fail", "dialog did not open: " + res.error.code + " " + res.error.message);
          set(t, "fail", "not attempted");
          $("btn-signin").disabled = false;
          return;
        }
        var dialog = res.value;
        dialog.addEventHandler(Office.EventType.DialogMessageReceived, function (arg) {
          dialog.close();
          handleCallback(arg.message, state, verifier, c, t);
        });
        dialog.addEventHandler(Office.EventType.DialogEventReceived, function (arg) {
          // 12006 = user closed the window; 12002/12003 = page not reachable / not https.
          set(c, "fail", "dialog closed or failed (code " + arg.error + ")");
          set(t, "fail", "not attempted");
          $("btn-signin").disabled = false;
        });
      });
    }).catch(function (e) {
      set(c, "fail", "PKCE setup failed: " + e.message);
      $("btn-signin").disabled = false;
    });
  }

  function handleCallback(message, state, verifier, c, t) {
    var params;
    try {
      params = new URL(JSON.parse(message).href).searchParams;
    } catch (e) {
      set(c, "fail", "unreadable message from the dialog");
      $("btn-signin").disabled = false;
      return;
    }
    if (params.get("error")) {
      set(c, "fail", "ERPNext said: " + params.get("error"));
      set(t, "fail", "not attempted");
      $("btn-signin").disabled = false;
      return;
    }
    if (params.get("state") !== state) {
      set(c, "fail", "state mismatch (possible stale or forged response)");
      set(t, "fail", "not attempted");
      $("btn-signin").disabled = false;
      return;
    }
    set(c, "ok");
    form(config.token_url, {
      grant_type: "authorization_code",
      code: params.get("code"),
      redirect_uri: config.redirect_uri,
      client_id: config.client_id,
      code_verifier: verifier,
    }).then(function (resp) {
      storeTokenResponse(resp);
      set(t, "ok", "expires in " + (resp.expires_in || "?") + "s" + (resp.refresh_token ? ", refresh token issued" : ", NO refresh token"));
      return verifyUser();
    }).catch(function (e) {
      set(t, "fail", e.message);
    }).then(function () {
      $("btn-signin").disabled = false;
    });
  }

  // ── authenticated API checks ───────────────────────────────────────────
  function verifyUser() {
    var u = upsert("user", "API call as the signed-in user");
    var o = upsert("opps", "Can read Opportunities with the token");
    set(u, "pending");
    set(o, "pending");
    return api("/api/method/frappe.auth.get_logged_user").then(function (r) {
      if (!r.message || r.message === "Guest") throw new Error("token treated as Guest");
      set(u, "ok", r.message);
      $("who").textContent = "Signed in as " + r.message;
      showSignedIn(true);
      var fields = encodeURIComponent(JSON.stringify(["name"]));
      return api("/api/resource/Opportunity?limit_page_length=1&fields=" + fields).then(function (res) {
        var n = (res.data || []).length;
        set(o, "ok", n ? "e.g. " + res.data[0].name : "allowed, but this user sees no Opportunities");
      }).catch(function (e) {
        set(o, "fail", e.message);
      });
    }).catch(function (e) {
      set(u, "fail", e.message);
      set(o, "fail", "not attempted");
      showSignedIn(false);
    });
  }

  function testRefresh() {
    var r = upsert("refresh", "Token refresh works");
    set(r, "pending");
    var before = tokens && tokens.access_token;
    refresh().then(function () {
      set(r, tokens.access_token !== before ? "ok" : "warn", tokens.access_token !== before ? "new access token issued" : "same token returned");
      return verifyUser();
    }).catch(function (e) {
      set(r, "fail", e.message);
    });
  }

  function signOut() {
    var t = tokens;
    saveTokens(null);
    showSignedIn(false);
    $("who").textContent = "Signed out";
    if (t && t.access_token) {
      form(config.revoke_url, { token: t.access_token }).catch(function () { /* revoke returns 200 with no JSON */ });
    }
  }

  function showSignedIn(on) {
    $("btn-signin").hidden = on;
    $("btn-refresh").hidden = !on;
    $("btn-signout").hidden = !on;
    if (!on) $("who").textContent = "Not signed in";
  }

  // ── Outlook environment + current item ─────────────────────────────────
  function readEnvironment(info) {
    var d = Office.context.diagnostics || {};
    env.host = info.host;
    env.platform = info.platform;
    env.outlook = (d.hostName || "?") + " " + (d.hostVersion || "?");
    env.ui = Office.context.displayLanguage || "?";
    var sets = [];
    for (var v = 1; v <= 15; v++) {
      if (Office.context.requirements.isSetSupported("Mailbox", "1." + v)) sets.push("1." + v);
    }
    env.mailbox_sets = sets.length ? sets[0] + "–" + sets[sets.length - 1] : "none";
    var c = check("sets", "Mailbox API level (need 1.8+ for attachments/categories)");
    var has18 = sets.indexOf("1.8") !== -1;
    set(c, has18 ? "ok" : "warn", env.mailbox_sets);
  }

  function readItem() {
    var c = check("item", "Read the open email");
    var item = Office.context.mailbox && Office.context.mailbox.item;
    if (!item) {
      set(c, "warn", "no email selected");
      return;
    }
    try {
      itemInfo = {
        Subject: item.subject,
        From: item.from ? item.from.displayName + " <" + item.from.emailAddress + ">" : null,
        To: (item.to || []).map(function (r) { return r.emailAddress; }).join(", "),
        Cc: (item.cc || []).map(function (r) { return r.emailAddress; }).join(", "),
        "Message-ID": item.internetMessageId,
        "Thread ID": item.conversationId,
        Received: item.dateTimeCreated ? new Date(item.dateTimeCreated).toLocaleString() : null,
        Attachments: (item.attachments || []).length,
      };
      renderItem();
      set(c, item.internetMessageId ? "ok" : "warn", item.internetMessageId ? "" : "no Message-ID (needed to avoid duplicate links)");
    } catch (e) {
      set(c, "fail", e.message);
    }
    if (item.body && item.body.getAsync) {
      var b = check("body", "Read the email body (HTML)");
      item.body.getAsync(Office.CoercionType.Html, function (res) {
        if (res.status === Office.AsyncResultStatus.Succeeded) set(b, "ok", res.value.length + " characters");
        else set(b, "fail", res.error.message);
      });
    }
  }

  function loadConfig() {
    var c = check("config", "Reach ERPNext and load add-in settings");
    return fetch(CONFIG_URL, { credentials: "omit", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok || !j.message) {
            throw new Error("HTTP " + r.status + " — is the app deployed and `bench migrate` run on this site?");
          }
          return j.message;
        });
      })
      .then(function (cfg) {
        config = cfg;
        env.site = cfg.site;
        env.asset_version = cfg.asset_version;
        set(c, "ok", cfg.site);
      })
      .catch(function (e) {
        set(c, "fail", e.message);
        throw e;
      });
  }

  function copyReport() {
    var ta = $("report");
    var done = function () { $("btn-copy").textContent = "Copied"; setTimeout(function () { $("btn-copy").textContent = "Copy report"; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(ta.value).then(done, function () { ta.select(); document.execCommand("copy"); done(); });
    } else {
      ta.select();
      document.execCommand("copy");
      done();
    }
  }

  // ── boot ───────────────────────────────────────────────────────────────
  $("btn-signin").addEventListener("click", signIn);
  $("btn-refresh").addEventListener("click", testRefresh);
  $("btn-signout").addEventListener("click", signOut);
  $("btn-copy").addEventListener("click", copyReport);

  var loaded = check("load", "Outlook loaded this page from ERPNext");

  if (!window.Office) {
    set(loaded, "fail", "office.js did not load");
    return;
  }
  Office.onReady(function (info) {
    if (info.host !== Office.HostType.Outlook) {
      set(loaded, "warn", "opened outside Outlook (" + (info.host || "browser") + ")");
    } else {
      set(loaded, "ok", location.host);
    }
    if (info.host === Office.HostType.Outlook) {
      readEnvironment(info);
      readItem();
    }
    loadConfig().then(function () {
      // The sign-in dialog needs Office.context.ui, which only exists in Outlook.
      $("btn-signin").disabled = info.host !== Office.HostType.Outlook;
      tokens = loadTokens();
      if (tokens && tokens.access_token) verifyUser();
    }).catch(function () { /* shown in checks */ });
  });
})();
