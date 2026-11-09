# Outlook Add-in — Phase 0 (connection + sign-in test)

Goal: prove, before building any real features, that Outlook can load the
add-in from `bms.alkhora.com`, sign the user in with their **ERPNext login**,
and call the ERPNext API as that user, in each Outlook version the team uses.

The panel does nothing to your data. It only reads the open email and calls
two read-only APIs (`get_logged_user`, one Opportunity name).

## What was added

| File | Purpose |
|---|---|
| `opportunity_management/opportunity_management/outlook_addin.py` | `ensure_oauth_client()` creates the trusted **"Outlook Add-in"** OAuth Client; `get_config()` (guest) gives the panel its client ID and endpoints |
| `opportunity_management/opportunity_management/outlook_addin_pure.py` | URL / client-value logic (unit-tested, no Frappe) |
| `opportunity_management/patches/setup_outlook_addin.py` | Runs `ensure_oauth_client()` on `bench migrate` (also called from `after_install`) |
| `opportunity_management/public/outlook/v1/` | The panel: `taskpane.html/js/css`, `auth-callback.html`, icons, `manifest.xml` |
| `opportunity_management/opportunity_management/tests/test_outlook_addin_pure.py` | 11 bench-free tests |

### How sign-in works
1. The panel opens an Office dialog at ERPNext's `/api/method/frappe.integrations.oauth2.authorize`
   (Authorization Code + **PKCE S256**, no client secret).
2. The user logs in on the normal ERPNext login page (only the first time per device).
3. ERPNext redirects to `outlook/v1/auth-callback.html`, which passes the code back to the panel.
4. The panel swaps the code for an access + refresh token and calls the API with
   `Authorization: Bearer …`. Normal ERPNext roles and permissions apply.
5. Tokens are kept in the panel's `localStorage` on that device. **Sign out** revokes the token;
   admins can revoke any token under **OAuth Bearer Token**.

Verified against Frappe v15 source: `authenticate_client` accepts a `client_id`
without a secret and `validate_code` enforces the S256 verifier.

### Caching rule (important for later phases)
Everything under `/assets` is cached for a year by Cloudflare. **Never edit files in
`outlook/v1/` after users have them.** Changes go in a new folder (`v2/`), with
`ASSET_VERSION` in `outlook_addin_pure.py`, the manifest URLs and `<Version>` updated.
The old redirect URI stays registered, so old manifests keep working.

## 1. Deploy

1. Deploy this branch (`feature/outlook-addin-phase0`) to `bms.alkhora.com` the usual way
   (merge into the deployed branch, then deploy on Frappe Cloud). The patch runs during migrate.
2. Check that these work:
   - `https://bms.alkhora.com/api/method/opportunity_management.opportunity_management.outlook_addin.get_config`
     returns JSON with a `client_id`.
   - `https://bms.alkhora.com/assets/opportunity_management/outlook/v1/taskpane.html`
     loads (it will say "opened outside Outlook" — that is expected in a browser).
3. In ERPNext, **OAuth Client** list → there is one called **Outlook Add-in**.

If the client is missing, run in the Frappe Cloud console:
```python
from opportunity_management.opportunity_management.outlook_addin import ensure_oauth_client
ensure_oauth_client(); frappe.db.commit()
```

## 2. Install the test add-in (only for you — no M365 admin needed)

Download the manifest:
`https://bms.alkhora.com/assets/opportunity_management/outlook/v1/manifest.xml`
(save it as `manifest.xml`).

- **Outlook on the web / new Outlook (Windows or Mac):** open
  `https://aka.ms/olksideload` → **My add-ins** → **Custom Add-ins** →
  **Add a custom add-in** → **Add from file** → pick `manifest.xml`.
- **Classic Outlook for Windows:** **Home → Get Add-ins** (or **File → Manage Add-ins**) →
  **My add-ins** → **Add a custom add-in → From file**.

If "Add a custom add-in" is missing, your Microsoft 365 policy blocks custom add-ins:
an admin must allow the **My Custom Apps** role for your account.

## 3. Run the test

1. Open any received email.
2. Click **ERPNext Opportunities** — on the ribbon (classic), or under **Apps** /
   the **…** menu on the email (web and new Outlook).
3. Click **Sign in to ERPNext**, log in, and wait for the window to close.
4. Click **Test token refresh**.
5. Close and reopen the panel on another email — you should still be signed in.
6. Click **Copy report** and send the text back.

Repeat in each Outlook version the team uses (web, new Outlook, classic Windows, Mac).

### Expected result

All lines show ✓:
- Outlook loaded this page from ERPNext
- Mailbox API level (1.8+ wanted)
- Read the open email / Read the email body
- Reach ERPNext and load add-in settings
- Sign-in dialog returns an authorization code
- Code exchanged for a token (PKCE, no secret)
- API call as the signed-in user
- Can read Opportunities with the token
- Token kept on this device
- Token refresh works

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Panel is blank | Page blocked from loading in Outlook, or the asset path 404s (app not built/deployed) |
| "Reach ERPNext…" fails with 404 | App not deployed or `bench migrate` not run |
| Dialog code **12006** | The sign-in window was closed before finishing |
| Dialog code **12002 / 12003** | Login redirect went to a non-https or unreachable URL — send the report |
| "ERPNext said: access_denied" | Your user lacks the OAuth Client's allowed role (default: System User) |
| Token exchange fails with `invalid_grant` | Code expired or PKCE mismatch — try again, then send the report |
| "Token kept…" shows ! | Browser storage is blocked; you'll need to sign in each time the panel opens |

## Removing the test

- Outlook: **My add-ins** → the add-in → **Remove**.
- ERPNext: delete the **Outlook Add-in** OAuth Client (this revokes all its tokens).
