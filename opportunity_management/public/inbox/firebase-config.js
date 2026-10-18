// Firebase Web Push settings of the web Team Inbox. NOT compiled into the
// app: `tool/build_inbox_web.sh` copies this file (un-versioned) to
// `public/inbox/firebase-config.js`, where both the page (`<script>` in
// index.html) and the service worker (`firebase-messaging-sw.js`,
// `importScripts`) read it.
//
// To turn Web Push on: paste the Firebase console values (Project settings →
// General → "Your apps" → the Web app's config, and Cloud Messaging → Web
// Push certificates → the key pair) below, then BUMP `version` — it is the
// cache key of the service worker and of this file (everything under /assets
// is cached for a year). While any value still starts with "REPLACE_" the
// push code stays dormant and the inbox works exactly as before (polling +
// in-tab notifications).
self.__ALKHORA_FIREBASE__ = {
  version: "4",
  config: {
    apiKey: "AIzaSyAZWoOC8Pm3WTJFkwIgRMG5Ty-m8WytHfQ",
    authDomain: "alkhora-ess.firebaseapp.com",
    projectId: "alkhora-ess",
    storageBucket: "alkhora-ess.firebasestorage.app",
    messagingSenderId: "235645099913",
    appId: "1:235645099913:web:877402b70b52e965d74b58",
  },
  vapidKey: "BPlEolzSZ44zSZaCuWg7tQXWqDuFnw0ORuqukuKU_nK1EvZeh3cm1w2MFO9koee3q_A1L3m2dmuW3ah_cHVDDEo",
};
