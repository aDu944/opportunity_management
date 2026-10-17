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
  version: "1",
  config: {
    apiKey: "REPLACE_API_KEY",
    authDomain: "REPLACE_PROJECT_ID.firebaseapp.com",
    projectId: "REPLACE_PROJECT_ID",
    storageBucket: "REPLACE_PROJECT_ID.appspot.com",
    messagingSenderId: "REPLACE_SENDER_ID",
    appId: "REPLACE_APP_ID",
  },
  vapidKey: "REPLACE_VAPID_KEY",
};
