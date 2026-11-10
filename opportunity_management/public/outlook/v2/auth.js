/*
 * ERPNext sign-in for the Outlook add-in (OAuth Authorization Code + PKCE,
 * no client secret — see outlook_addin.py). Exposes window.OMAuth.
 *
 * Every request uses credentials: "omit": a Desk session cookie shared by the
 * desktop WebView must never turn a token call into a CSRF-checked session
 * request. The bearer token is the only credential.
 */
(function () {
  "use strict";

  var CONFIG_URL = "/api/method/opportunity_management.opportunity_management.outlook_addin.get_config";
  var STORE_KEY = "om_outlook_tokens_v1"; // shared with v1 so a Phase 0 sign-in carries over
  var REFRESH_MARGIN_MS = 60 * 1000;

  var config = null;
  var tokens = null;
  var refreshing = null;

  function load() {
    try {
      var raw = window.localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }
  function save(t) {
    tokens = t;
    try {
      if (t) window.localStorage.setItem(STORE_KEY, JSON.stringify(t));
      else window.localStorage.removeItem(STORE_KEY);
    } catch (e) { /* storage blocked: sign-in lasts until the pane closes */ }
  }

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

  function errorText(json, status, fallback) {
    if (json) {
      if (json._server_messages) {
        try {
          var msgs = JSON.parse(json._server_messages).map(function (m) {
            try { return JSON.parse(m).message; } catch (e) { return m; }
          });
          var text = msgs.join(" ").replace(/<[^>]+>/g, "");
          if (text) return text;
        } catch (e) { /* fall through */ }
      }
      if (json.error_description || json.error) return json.error_description || json.error;
      if (json.exception) return String(json.exception).split(":").slice(1).join(":").trim() || json.exc_type;
      if (json.exc_type) return json.exc_type;
    }
    return "HTTP " + status + (fallback ? ": " + fallback : "");
  }

  function postForm(url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "omit",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams(data).toString(),
    }).then(function (r) {
      return r.text().then(function (text) {
        var json = null;
        try { json = JSON.parse(text); } catch (e) { /* not JSON */ }
        if (!r.ok || !json || json.error) throw new Error(errorText(json, r.status, text.slice(0, 120)));
        return json;
      });
    });
  }

  function keep(resp) {
    if (!resp.access_token) throw new Error("no access_token in response");
    save({
      access_token: resp.access_token,
      refresh_token: resp.refresh_token || (tokens && tokens.refresh_token) || null,
      expires_at: Date.now() + (Number(resp.expires_in) || 3600) * 1000,
    });
  }

  function refresh() {
    if (!refreshing) {
      if (!tokens || !tokens.refresh_token) return Promise.reject(new Error("Signed out"));
      refreshing = postForm(config.token_url, {
        grant_type: "refresh_token",
        refresh_token: tokens.refresh_token,
        client_id: config.client_id,
      }).then(keep).catch(function (e) {
        save(null); // refresh token dead: the user must sign in again
        throw new Error("Your ERPNext sign-in expired. Please sign in again.");
      }).then(function () { refreshing = null; }, function (e) { refreshing = null; throw e; });
    }
    return refreshing;
  }

  /* Authenticated call. opts: {method, body (object -> JSON)}. Resolves with
   * the response's `message`. 401/403 means the token is bad: refresh once. */
  function api(method, opts) {
    opts = opts || {};
    if (!tokens) return Promise.reject(new Error("Signed out"));
    var url = config.site + "/api/method/" + method;
    var ready = tokens.expires_at - Date.now() < REFRESH_MARGIN_MS ? refresh() : Promise.resolve();
    var call = function () {
      var headers = { Authorization: "Bearer " + tokens.access_token, Accept: "application/json" };
      var init = { method: opts.method || "GET", credentials: "omit", headers: headers };
      if (opts.body !== undefined) {
        headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
        init.method = "POST";
      }
      return fetch(url, init);
    };
    return ready.then(call).then(function (r) {
      if (r.status !== 401 && r.status !== 403) return r;
      return refresh().then(call);
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (json) {
        if (!r.ok) {
          var err = new Error(errorText(json, r.status));
          err.status = r.status;
          throw err;
        }
        return json.message;
      });
    });
  }

  function signIn() {
    var verifier = randomString(48);
    var state = randomString(16);
    return sha256(verifier).then(function (challenge) {
      var url = config.authorize_url + "?" + new URLSearchParams({
        client_id: config.client_id,
        response_type: "code",
        redirect_uri: config.redirect_uri,
        scope: config.scopes,
        state: state,
        code_challenge: challenge,
        code_challenge_method: "S256",
      }).toString();
      return new Promise(function (resolve, reject) {
        Office.context.ui.displayDialogAsync(url, { height: 70, width: 35, promptBeforeOpen: false }, function (res) {
          if (res.status !== Office.AsyncResultStatus.Succeeded) {
            reject(new Error("Could not open the sign-in window (" + res.error.code + ")"));
            return;
          }
          var dialog = res.value;
          dialog.addEventHandler(Office.EventType.DialogMessageReceived, function (arg) {
            dialog.close();
            var params;
            try { params = new URL(JSON.parse(arg.message).href).searchParams; } catch (e) {
              reject(new Error("Unexpected reply from the sign-in window"));
              return;
            }
            if (params.get("error")) return reject(new Error("ERPNext refused sign-in: " + params.get("error")));
            if (params.get("state") !== state) return reject(new Error("Sign-in reply did not match; please try again"));
            resolve(params.get("code"));
          });
          dialog.addEventHandler(Office.EventType.DialogEventReceived, function (arg) {
            reject(new Error(arg.error === 12006 ? "Sign-in window closed" : "Sign-in failed (" + arg.error + ")"));
          });
        });
      });
    }).then(function (code) {
      return postForm(config.token_url, {
        grant_type: "authorization_code",
        code: code,
        redirect_uri: config.redirect_uri,
        client_id: config.client_id,
        code_verifier: verifier,
      });
    }).then(keep);
  }

  function signOut() {
    var t = tokens;
    save(null);
    if (t && t.access_token) postForm(config.revoke_url, { token: t.access_token }).catch(function () {});
  }

  function init() {
    return fetch(CONFIG_URL, { credentials: "omit", headers: { Accept: "application/json" } })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok || !j.message) throw new Error("Cannot reach ERPNext (HTTP " + r.status + ")");
          config = j.message;
          tokens = load();
          return config;
        });
      });
  }

  window.OMAuth = {
    init: init,
    api: api,
    signIn: signIn,
    signOut: signOut,
    signedIn: function () { return !!tokens; },
    config: function () { return config; },
  };
})();
