// Web Push service worker of the web Team Inbox. Served un-versioned from
// /assets/opportunity_management/inbox/firebase-messaging-sw.js (copied there
// by tool/build_inbox_web.sh) and registered by the app with
//   scope '/assets/opportunity_management/inbox/'
//   url   '…/firebase-messaging-sw.js?v=<firebase-config.js version>'
// so one worker covers every versioned build folder. It has no `fetch`
// handler: it never caches or serves the app.
//
// Our `push` / `notificationclick` listeners are added BEFORE the Firebase
// SDK's and stop the SDK's copies, so a message is shown exactly once:
//   • an inbox tab is visible → no system notification; the payload is
//     posted to the tab ({type:'push'}) which refreshes the lists and plays
//     the in-app sound;
//   • otherwise → showNotification(title, {body, icon, badge,
//     tag: conversation, renotify, data}).
// A click focuses an open inbox tab and posts {type:'open', route:
// '/chats/<id>'}; with no inbox tab it opens the message's link. The Firebase
// compat SDK stays loaded for `pushsubscriptionchange` (token refresh).

const SCOPE = self.registration.scope; // …/assets/opportunity_management/inbox/
const ICON = SCOPE + "icons/Icon-192.png";
const BADGE = SCOPE + "icons/Icon-192.png";
const SDK = "11.9.1"; // = firebase_core_web's supportedFirebaseJsSdkVersion

function str(v) {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

// "/chats/<id>" from the link's hash (…/inbox#/chats/WAC-1) or an explicit
// data.conversation; anything else opens the inbox root.
function routeOf(link, data) {
  const hash = str(link).split("#")[1] || "";
  if (/^\/chats\/[^/?#]+$/.test(hash)) return hash;
  const conv = str(data.conversation);
  if (conv && !/[/?#]/.test(conv)) return "/chats/" + encodeURIComponent(conv);
  return "/";
}

function parse(event) {
  let raw = {};
  try {
    raw = event.data ? event.data.json() : {};
  } catch (_) {
    raw = { notification: { body: event.data ? event.data.text() : "" } };
  }
  const n = raw.notification || {};
  const data = raw.data || {};
  const opts = raw.fcmOptions || raw.fcm_options || {};
  const link = str(opts.link || data.link) || self.location.origin + "/inbox";
  const route = routeOf(link, data);
  let tag = "inbox";
  if (route.startsWith("/chats/")) {
    try {
      tag = decodeURIComponent(route.slice(7));
    } catch (_) {
      tag = route.slice(7);
    }
  }
  return {
    title: str(n.title || data.title) || "ALKHORA Team Inbox",
    body: str(n.body || data.body),
    icon: str(n.icon) || ICON,
    tag,
    link,
    route,
    data,
  };
}

async function inboxClients() {
  const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
  return all.filter((c) => c.url.startsWith(SCOPE));
}

self.addEventListener("push", (event) => {
  event.stopImmediatePropagation();
  event.waitUntil(
    (async () => {
      const m = parse(event);
      const clients = await inboxClients();
      const visible = clients.filter((c) => c.visibilityState === "visible");
      if (visible.length) {
        visible.forEach((c) => c.postMessage({ type: "push", route: m.route, data: m.data }));
        return;
      }
      await self.registration.showNotification(m.title, {
        body: m.body,
        icon: m.icon,
        badge: BADGE,
        tag: m.tag,
        renotify: true,
        data: { link: m.link, route: m.route, payload: m.data },
      });
    })()
  );
});

self.addEventListener("notificationclick", (event) => {
  event.stopImmediatePropagation();
  const d = event.notification.data || {};
  event.notification.close();
  event.waitUntil(
    (async () => {
      const route = str(d.route) || "/";
      const clients = await inboxClients();
      const c = clients[0];
      if (c) {
        try {
          await c.focus();
        } catch (_) {}
        c.postMessage({ type: "open", route });
        return;
      }
      await self.clients.openWindow(str(d.link) || self.location.origin + "/inbox#" + route);
    })()
  );
});

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Settings (same cache key as this worker), then the SDK when configured.
try {
  const v = new URL(self.location.href).searchParams.get("v") || "0";
  importScripts("firebase-config.js?v=" + encodeURIComponent(v));
  const fb = self.__ALKHORA_FIREBASE__ || {};
  const cfg = fb.config || {};
  const ready = ["apiKey", "projectId", "messagingSenderId", "appId"].every(
    (k) => typeof cfg[k] === "string" && cfg[k] && !cfg[k].startsWith("REPLACE_")
  );
  if (ready) {
    importScripts(
      "https://www.gstatic.com/firebasejs/" + SDK + "/firebase-app-compat.js",
      "https://www.gstatic.com/firebasejs/" + SDK + "/firebase-messaging-compat.js"
    );
    firebase.initializeApp(cfg);
    firebase.messaging();
  }
} catch (e) {
  console.warn("[inbox push] service worker setup:", e);
}
