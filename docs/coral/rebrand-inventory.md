# Coral rebrand inventory

Every `omnigent`/`databricks` hit (case-insensitive `git grep`) in the areas the rebrand covers, with its class and reason, plus every image or drawable in those areas. Generated from the step-0 classification and reconciled against the tree after the rebrand: a row whose text changed is a change row with its seam; `PENDING` marks a planned change not yet landed.

Areas: `web/src`, `web/electron`, `web/ios`, `web/android`, `web/*.html`, and the S92 server pages (`omnigent/server/static/api_only_landing.html`, `omnigent/server/routes/auth.py`, `omnigent/server/routes/device_auth.py`). Base commit `2a9cbe2c2`.

## Classes

| Class | Meaning | Rows |
|---|---|---|
| change | Product-name text shown to users, or a test or copy that pinned it. | 399 |
| change-identity | Lowercase ids that follow the desktop app id or the `coral` URL scheme. | 19 |
| change-asset | Images or drawables that show Omnigent artwork (replacement added beside it). | 33 |
| keep-origin | Where Coral comes from (L6 a-c): upstream project, package or docs as facts, attribution; also the Databricks platform as an integration target (workspace sign-in, Unity Gateway), which is not Coral's publisher. | 405 |
| keep-internal | Internal identifiers (package, imports, `OMNIGENT_*`, storage keys, IPC channels, CSS classes, test ids), comments, and tests that do not assert visible text. | 8027 |
| keep-deferred | Install commands, omnigent.ai docs links, the `omnigent` CLI, server messages, App Store metadata and mobile ids, each with the feature that will change it. | 107 |
| keep-L7 | The Powered-by-Omnigent credit (L7), unchanged until counsel answers OQ-30. | 7 |

Total rows: 8997. Pending planned changes: 0.

## Rows by file

Text is an excerpt around the first hit. Seams: S79-S89b, S92 (see `.coral/seams.yaml`).

### `omnigent/server/routes/auth.py`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …ports the ˋˋomnigent loginˋˋ CLI comma… | keep-internal |  | code identifier |
| 22 | …nted when ˋˋOMNIGENT_AUTH_PROVIDER=oid… | keep-internal |  | code identifier |
| 45 | from omnigent.server.accounts_store im… | keep-internal |  | code identifier |
| 46 | from omnigent.server.admin_list import… | keep-internal |  | code identifier |
| 47 | from omnigent.server.auth import ( | keep-internal |  | code identifier |
| 51 | from omnigent.server.device_grant_stor… | keep-internal |  | code identifier |
| 52 | from omnigent.server.oidc import ( | keep-internal |  | code identifier |
| 58 | from omnigent.server.oidc_access impor… | keep-internal |  | code identifier |
| 59 | from omnigent.server.routes._oauth imp… | keep-internal |  | code identifier |
| 60 | from omnigent.server.routes.device_aut… | keep-internal |  | code identifier |
| 64 | from omnigent.stores.permission_store … | keep-internal |  | code identifier |
| 80 | "Upgrade Omnigent to sign in: this server requires a newer login client. " | change | S92,S95 | Changed with its seam: _CLI_UPGRADE_MESSAGE is a server JSON error string for CLI/mobile/Slack clients, outside the S92 pages; server messag |
| 81 | "For the CLI, run ˋomni upgradeˋ, then retry ˋomnigent loginˋ. " | keep-deferred |  | Server error text naming ˋomni upgradeˋ / ˋomnigent loginˋ CLI commands; CLI name changes with OPS-03/FND-01. |
| 100 | {"ai.omnigent.android:/oauth/callback"… | keep-internal |  | NATIVE_APP_REDIRECT_URIS: OAuth redirect schemes |
| 114 | from omnigent.server.oidc import OIDCC… | keep-internal |  | code identifier |
| 202 | :mod:ˋomnigent.server.admin_listˋ). OI… | keep-internal |  | Docstring cross-reference to omnigent.server.adm |
| 204 | ˋˋOMNIGENT_OIDC_ALLOW_INVITESˋˋ is on.… | keep-internal |  | code identifier |
| 211 | ˋˋOMNIGENT_OIDC_ALLOWED_DOMAINSˋˋ and … | keep-internal |  | code identifier |
| 215 | :func:ˋomnigent.server.routes.device_a… | keep-internal |  | Docstring cross-reference to omnigent.server.rou |
| 217 | ˋˋomnigent loginˋˋ. ˋˋNoneˋˋ keeps the… | keep-internal |  | code identifier |
| 234 | …gn in — see omnigent/server/oidc_acces… | keep-internal |  | code comment |
| 522 | …e it unless OMNIGENT_OIDC_REQUIRE_REAU… | keep-internal |  | code comment |
| 527 | "(OMNIGENT_OIDC_REQUIRE_REAUTH is disa… | keep-internal |  | Server log message naming OMNIGENT_OIDC_REQUIRE_ |
| 535 | "set OMNIGENT_OIDC_REQUIRE_REAUTH=0 if… | keep-internal |  | Server log warning naming OMNIGENT_OIDC_REQUIRE_ |
| 542 | "set OMNIGENT_OIDC_REQUIRE_REAUTH=0 if… | keep-internal |  | Server log warning naming OMNIGENT_OIDC_REQUIRE_ |
| 723 | If ˋˋOMNIGENT_OIDC_LOGOUT_REDIRECT_URI… | keep-internal |  | Docstring naming OMNIGENT_OIDC_LOGOUT_REDIRECT_U |
| 918 | "Run ˋomnigent loginˋ again and sign in when prompted." | keep-deferred |  | Error shown on S92 consent page tells user to run ˋomnigent loginˋ; CLI name changes with OPS-03/FND-01. |
| 1016 | …ders.get("X-Omnigent-Code-Verifier") | keep-internal |  | X-Omnigent-Code-Verifier protocol header the ser |
| 1207 | "<h1>Update Omnigent to sign in</h1>" | change | S92,S95 | Changed with its seam: Upgrade-notice text about updating the client (the omnigent CLI, OPS-03/FND-01); prompt keeps upgrade text. Tests pin |
| 1212 | "<code>omnigent login</code> command again. If the upgrade command " | keep-deferred |  | Upgrade instruction naming the ˋomnigent loginˋ CLI command; changes with OPS-03/FND-01. |
| 1214 | "<li><b>iOS or Android:</b> Update the Omnigent app through your " | change | S92,S95 | Changed with its seam: Upgrade instruction for the mobile app via app stores; store listings/bundle ids still Omnigent (OQ-31). |
| 1217 | "<li><b>Slack:</b> Ask your administrator to update the Omnigent " | change | S92,S95 | Changed with its seam: Names the Omnigent Slack integration; integrations/ is out of scope and stays Omnigent-named. |
| 1234 | f"<p>An Omnigent client is requesting a session as " | change | S92 | S92 CLI consent page body: product name in user-visible consent prompt. |
| 1235 | f"<b>{esc(user_id)}</b> on this Omnigent server.</p>" | change | S92 | S92 CLI consent page: 'this Omnigent server' product wording becomes Coral server. |
| 1238 | "from Omnigent. For CLI or Slack sign-in, also check that this code " | change | S92 | S92 CLI consent warning: product name in user-visible text. |
| 1253 | " — Omnigent</title><style>" | change | S92 | S92 CLI consent page <title> suffix shows product name in browser tab. |
| 1581 | ˋˋOMNIGENT_OIDC_SKIP_EMAIL_VERIFICATIO… | keep-internal |  | code identifier |
| 1585 | …mˋˋ (from ˋˋOMNIGENT_OIDC_EMAIL_CLAIMˋ… | keep-internal |  | code identifier |
| 1604 | "can set OMNIGENT_OIDC_EMAIL_CLAIM.", | keep-internal |  | Server log warning naming OMNIGENT_OIDC_EMAIL_CL |
| 1620 | "marker (OMNIGENT_OIDC_SKIP_EMAIL_VERI… | keep-internal |  | Server log message naming OMNIGENT_OIDC_SKIP_EMA |
| 1628 | "OMNIGENT_OIDC_SKIP_EMAIL_VERIFICATION… | keep-internal |  | Server log warning naming OMNIGENT_OIDC_SKIP_EMA |
| 1637 | … opted out (OMNIGENT_OIDC_SKIP_EMAIL_V… | keep-internal |  | code comment |
| 1643 | "(OMNIGENT_OIDC_SKIP_EMAIL_VERIFICATIO… | keep-internal |  | Server log message naming OMNIGENT_OIDC_SKIP_EMA |

### `omnigent/server/routes/device_auth.py`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | ˋˋOMNIGENT_DEVICE_GRANT_ENABLEDˋˋ is s… | keep-internal |  | code identifier |
| 38 | …, setting ˋˋOMNIGENT_DEVICE_CLIENT_SEC… | keep-internal |  | code identifier |
| 64 | from omnigent.errors import ErrorCode,… | keep-internal |  | code identifier |
| 65 | from omnigent.server.auth import Unifi… | keep-internal |  | code identifier |
| 66 | from omnigent.server.device_grant_stor… | keep-internal |  | code identifier |
| 67 | from omnigent.server.routes._oauth imp… | keep-internal |  | code identifier |
| 72 | from omnigent.server.routes._oauth imp… | keep-internal |  | code identifier |
| 73 | from omnigent.server.routes._origin im… | keep-internal |  | code identifier |
| 78 | …ke). When ˋˋOMNIGENT_DEVICE_CLIENT_SEC… | keep-internal |  | code comment |
| 85 | …CRET_ENV = "OMNIGENT_DEVICE_CLIENT_SEC… | keep-internal |  | OMNIGENT_DEVICE_CLIENT_SECRET env var name. |
| 86 | …HEADER = "X-Omnigent-Client-Secret" | keep-internal |  | X-Omnigent-Client-Secret protocol header the ser |
| 94 | # ˋˋomnigent loginˋˋ, not the RFC 8628… | keep-internal |  | code comment |
| 100 | LOGIN_GRANT_CLIENT_ID = "omnigent-cli" | keep-internal |  | LOGIN_GRANT_CLIENT_ID 'omnigent-cli' is a persis |
| 127 | …TIME_ENV = "OMNIGENT_GRANT_MAX_LIFETIM… | keep-internal |  | OMNIGENT_GRANT_MAX_LIFETIME_DAYS env var name. |
| 206 | :func:ˋomnigent.server.oidc.mint_sessi… | keep-internal |  | Docstring cross-reference to omnigent.server.oid |
| 229 | …ser_id: The Omnigent identity the toke… | keep-internal |  | Docstring. |
| 343 | …e-running ˋˋomnigent loginˋˋ. The | keep-internal |  | code identifier |
| 379 | ˋˋOMNIGENT_DEVICE_GRANT_ENABLEDˋˋ). | keep-internal |  | code identifier |
| 395 | :func:ˋomnigent.server.routes.client_c… | keep-internal |  | Docstring cross-reference to omnigent.server.rou |
| 400 | the ˋˋOMNIGENT_DEVICE_CLIENT_SECRETˋˋ … | keep-internal |  | code identifier |
| 440 | raise OmnigentError("grant authority h… | keep-internal |  | code identifier |
| 480 | except OmnigentError: | keep-internal |  | code identifier |
| 485 | except OmnigentError: | keep-internal |  | code identifier |
| 586 | Backs ˋˋ/omnigent logoutˋˋ. Accepts a … | keep-internal |  | Code docstring mentioning the /omnigent logout c |
| 658 | …forced. Set OMNIGENT_DEVICE_GRANT_ENAB… | keep-internal |  | Operator startup RuntimeError naming OMNIGENT_DE |
| 682 | raise OmnigentError("grant authority h… | keep-internal |  | code identifier |
| 823 | Omnigent identity being delegated and … | keep-internal |  | Docstring. |
| 877 | …e approving Omnigent | keep-internal |  | Docstring. |
| 1060 | f"<b>{esc(user_id)}</b> on this Omnigent server.</p>" | change | S92 | S92 device consent page: 'this Omnigent server' product wording becomes Coral server. |
| 1076 | "<title>Authorize access — Omnigent</title><style>" | change | S92 | S92 device consent page <title> shows product name in browser tab. |

### `omnigent/server/static/api_only_landing.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | <title>Omnigent — web UI not installed</title> | change | S92 | S92 API-only landing page <title> shows product name. |
| 25 | <h1>Omnigent is running — but the web UI isn't installed</h1> | change | S92 | S92 landing page heading uses product name. |
| 34 | (<code>OMNIGENT_SKIP_WEB_UI</code>) — … | keep-internal |  | Names OMNIGENT_SKIP_WEB_UI env var (tests/server |
| 46 | … sure <code>OMNIGENT_SKIP_WEB_UI</code… | keep-internal |  | Names OMNIGENT_SKIP_WEB_UI env var. |
| 50 | <pre>uv cache clean omnigent</pre> | keep-deferred |  | Reinstall command names the omnigent Python distribution; install commands change with OPS-09. |
| 55 | Details: <a href="https://github.com/omnigent-ai/omnigent#readme">omnigent-ai/omnigent</a> | change | S92 | Website/GitHub 'Details' link points at Omnigent repo; becomes Coral's GitHub. |

### `web/android/README.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | # Omnigent Android | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 3 | Thin Kotlin/ˋWebViewˋ shell for Omnigent. Like the Electron app and the iOS | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 22 | runtime via ˋwindow.omnigentNativeˋ — see ˋweb/src/lib/nativeBridge.tsˋ. This | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 27 | (ˋOmnigentBridgeListenerˋ) **origin-allowlisted to the pinned server** and | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 38 | (measured insets injected as ˋ--omnigent-android-safe-area-*ˋ, consumed by the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 41 | bridge, which closes omnigent-ai/omnigent#969 (the iOS shell drops these) — | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 58 | ## Databricks workspaces | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 64 | optional ˋoˋ, and client ID. Databricks Apps keep their existing inline platform | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 77 | [ˋdocs/databricks-oauth.mdˋ](docs/databricks-oauth.md). | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 79 | A Databricks workspace serves its own landing page at the root and mounts the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 80 | Omnigent SPA at ˋ/omnigentˋ, so the shell rewrites a **bare** workspace root to | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 81 | that mount (ˋOrigins.databricksWorkspaceUiUrlˋ): | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 83 | - ˋhttps://dbc-a5d4177a-49dc.cloud.databricks.comˋ → | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 84 | ˋhttps://dbc-a5d4177a-49dc.cloud.databricks.com/omnigentˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 86 | (a deep link, or ˋ/omnigentˋ itself) is left alone. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 89 | (ˋServerStore.currentServerUrlˋ), and in all three ˋOmnigentWebViewClientˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 101 | workspace answers ˋ/omnigentˋ with a redirect back to the root, the user stays | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 106 | Host matching is by domain (ˋ*.databricks.comˋ, ˋ*.azuredatabricks.netˋ) — no | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 107 | probe request. ˋ*.databricksapps.comˋ is excluded: Apps serve their own app at | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 109 | workspace root to ˋ/omnigentˋ. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 113 | Omnigent servers that sign in with OIDC (ˋOMNIGENT_AUTH_PROVIDER=oidcˋ) open | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 115 | server that isn't a Databricks host, the app reads its unauthenticated | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 116 | ˋ/.well-known/omnigent.jsonˋ. Native sign-in applies only when ˋauth.modeˋ is | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 117 | ˋ"oidc"ˋ, ˋauth.native_redirect_urisˋ lists ˋai.omnigent.android:/oauth/callbackˋ, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 126 | \| Databricks workspaces and Apps                             \| Unchanged: detected by URL, manifest … | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 131 | Auth Tab returns the server's redirect to ˋai.omnigent.android:/oauth/callbackˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 158 | sidebar picker offers the same sign-out for Databricks workspaces. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 169 | server with ˋOMNIGENT_AUTH_PROVIDER=oidcˋ against the e2e fake identity provider | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 184 | 5. Start a sign-in, run ˋadb shell am kill ai.omnigent.androidˋ while the browser | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 195 | sign-in), a Databricks workspace, and a Databricks App behave as before. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 211 | { "serverUrls": "https://omnigent.corp.example.com" } | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 236 | Then Test DPC → _Managed configurations_ → pick Omnigent → **Load manifest | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 273 | - ˋOMNIGENT_KEYSTORE_FILEˋ — path to the upload keystore | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 274 | - ˋOMNIGENT_KEYSTORE_PASSWORDˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 275 | - ˋOMNIGENT_KEY_ALIASˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 276 | - ˋOMNIGENT_KEY_PASSWORDˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 282 | keytool -genkeypair -v -keystore omnigent-upload.jks \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 283 | -keyalg RSA -keysize 2048 -validity 10000 -alias omnigent-upload | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 330 | > Implementation for omnigent-ai/omnigent#1604; not yet exercised on a device | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/android/app/build.gradle.kts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 31 | …toreFile", "OMNIGENT_KEYSTORE_FILE") | keep-internal |  | OMNIGENT_KEYSTORE_FILE env var name for release |
| 41 | …first-party Databricks client the desk… | keep-internal |  | code comment |
| 42 | val databricksOAuthClientId = buildPro… | keep-internal |  | Default Databricks OAuth client_id "omnigent" is |
| 43 | val databricksOAuthRedirectUrl = | keep-internal |  | code identifier |
| 44 | …ldProperty("databricksOAuthRedirectUrl… | keep-internal |  | ai.omnigent.android://mobile-redirect OAuth redi |
| 45 | val databricksOAuthRedirectUri = URI(d… | keep-internal |  | code identifier |
| 48 | databricksOAuthRedirectUri.scheme == "… | keep-internal |  | code identifier |
| 49 | !databricksOAuthRedirectUri.host.isNul… | keep-internal |  | code identifier |
| 50 | !databricksOAuthRedirectUri.path.isNul… | keep-internal |  | code identifier |
| 52 | databricksOAuthRedirectUrl == "ai.omni… | keep-internal |  | Validation compares against the ai.omnigent.andr |
| 54 | "databricksOAuthRedirectUrl must be an… | keep-internal |  | Build-time require message naming the databricks |
| 61 | namespace = "ai.omnigent.android" | keep-internal |  | Android namespace ai.omnigent.android is the Kot |
| 65 | applicationId = "ai.omnigent.android" | keep-deferred |  | Android applicationId is the Play Store bundle id; mobile bundle ids/store listings deferred to OQ-31. |
| 72 | "DATABRICKS_OAUTH_CLIENT_ID", | keep-internal |  | BuildConfig field name DATABRICKS_OAUTH_CLIENT_I |
| 73 | …BuildConfig(databricksOAuthClientId), | keep-internal |  | code identifier |
| 77 | "DATABRICKS_OAUTH_REDIRECT_URL", | keep-internal |  | BuildConfig field name DATABRICKS_OAUTH_REDIRECT |
| 78 | …BuildConfig(databricksOAuthRedirectUrl… | keep-internal |  | code identifier |
| 80 | …aceholders["databricksOAuthRedirectSch… | keep-internal |  | Manifest placeholder name databricksOAuthRedirec |
| 81 | databricksOAuthRedirectUri.scheme | keep-internal |  | code identifier |
| 82 | …aceholders["databricksOAuthRedirectHos… | keep-internal |  | Manifest placeholder name databricksOAuthRedirec |
| 83 | databricksOAuthRedirectUri.host | keep-internal |  | code identifier |
| 84 | …aceholders["databricksOAuthRedirectPat… | keep-internal |  | Manifest placeholder name databricksOAuthRedirec |
| 85 | databricksOAuthRedirectUri.path | keep-internal |  | code identifier |
| 86 | …aceholders["databricksOAuthRedirectAut… | keep-internal |  | Manifest placeholder name databricksOAuthRedirec |
| 87 | (databricksOAuthRedirectUri.scheme == … | keep-internal |  | code identifier |
| 98 | …Password", "OMNIGENT_KEYSTORE_PASSWORD… | keep-internal |  | OMNIGENT_KEYSTORE_PASSWORD signing env var name; |
| 99 | …keyAlias", "OMNIGENT_KEY_ALIAS") | keep-internal |  | OMNIGENT_KEY_ALIAS signing env var name; interna |
| 100 | …Password", "OMNIGENT_KEY_PASSWORD") | keep-internal |  | OMNIGENT_KEY_PASSWORD signing env var name; inte |
| 228 | "ai.omnigent.android/.MainActivity", | keep-deferred |  | adb launch component ai.omnigent.android/.MainActivity derives from applicationId; changes with mobile bundle id (OQ-31). |
| 292 | …** Backend (omnigent server) port — Vi… | keep-internal |  | code comment |
| 339 | …he backend (omnigent server) process w… | keep-internal |  | code comment |
| 444 | // Backend (omnigent server) — isolate… | keep-internal |  | code comment |
| 446 | …ˋ launches ˋomnigent serverˋ with OMNI… | keep-internal |  | code comment |
| 447 | // OMNIGENT_CONFIG_HOME pointed at a t… | keep-internal |  | code comment |
| 448 | …r's real ~/.omnigent. On loopback it's… | keep-internal |  | code comment |
| 449 | …is backend (OMNIGENT_URL default = loc… | keep-internal |  | code comment |
| 458 | "Start an isolated omnigent backend server (temp data dir, no auth) for real SPA data" | keep-deferred |  | Gradle dev task description naming the omnigent backend server/CLI; follows CLI rename OPS-03/FND-01. |
| 468 | …pDirectory("omnigent-screenshot") | keep-internal |  | Temp directory prefix for screenshot backend; de |
| 486 | "omnigent", | keep-deferred |  | Invokes the omnigent CLI binary (omnigent server); CLI name changes under OPS-03/FND-01. |
| 499 | …ironment()["OMNIGENT_DATA_DIR"] = data… | keep-internal |  | OMNIGENT_DATA_DIR env var for the screenshot bac |
| 500 | …ironment()["OMNIGENT_CONFIG_HOME"] = c… | keep-internal |  | OMNIGENT_CONFIG_HOME env var; internal env var. |
| 501 | …ironment()["OMNIGENT_DATABASE_URI"] = … | keep-internal |  | OMNIGENT_DATABASE_URI env var; internal env var. |
| 574 | private val screenshotAppId = "ai.omnigent.android" | keep-deferred |  | screenshotAppId mirrors the applicationId (Play bundle id); changes with mobile bundle ids under OQ-31. |
| 644 | "ai.omnigent.android.ScreenshotTest", | keep-internal |  | Fully-qualified test class name in the ai.omnige |

### `web/android/app/proguard-rules.pro`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | # (OmnigentBridgeListener), invoked th… | keep-internal |  | code comment |

### `web/android/app/src/androidTest/java/ai/omnigent/android/ScreenshotTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 31 | …t needs the omnigent | keep-internal |  | test code |
| 51 | …process ˋai.omnigent.android.testˋ; wr… | keep-internal |  | test code |
| 209 | const val FIELD_HINT = "https://omnigent.example.com" | change | S88 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/android/app/src/debug/java/ai/omnigent/android/DatabricksAuthDebugMenu.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 7 | …rnal object DatabricksAuthDebugMenu { | keep-internal |  | code identifier |
| 26 | tokens: DatabricksTokenManager, | keep-internal |  | code identifier |
| 27 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 28 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 29 | session: DatabricksWebSession, | keep-internal |  | code identifier |

### `web/android/app/src/debug/java/ai/omnigent/android/OidcAuthDebugMenu.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/AndroidManifest.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | android:theme="@style/Theme.Omnigent"> | keep-internal |  | Theme.Omnigent is a style resource name defined |
| 47 | Databricks return page, and the native… | keep-internal |  | XML comment describing the Databricks return pag |
| 53 | …toVerify="${databricksOAuthRedirectAut… | keep-internal |  | Manifest placeholder ${databricksOAuthRedirectAu |
| 58 | …d:scheme="${databricksOAuthRedirectSch… | keep-internal |  | Manifest placeholder ${databricksOAuthRedirectSc |
| 59 | …oid:host="${databricksOAuthRedirectHos… | keep-internal |  | Manifest placeholder ${databricksOAuthRedirectHo |
| 60 | …oid:path="${databricksOAuthRedirectPat… | keep-internal |  | Manifest placeholder ${databricksOAuthRedirectPa |
| 67 | android:scheme="ai.omnigent.android" | keep-internal |  | ai.omnigent.android OAuth redirect scheme (mobil |
| 75 | android:scheme="ai.omnigent.android" | keep-internal |  | ai.omnigent.android:/oauth/callback scheme allow |

### `web/android/app/src/main/java/ai/omnigent/android/BlobDownloadScript.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 6 | …that leaves omnigent-ai/omnigent#969 | keep-internal |  | code comment |
| 9 | …ed bridge ([OmnigentBridgeListener]) f… | keep-internal |  | code comment |
| 36 | … = window.${OmnigentBridgeListener.JS_… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/BlobSaver.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 18 | * [OmnigentBridgeListener]) and writes… | keep-internal |  | code comment |
| 109 | "omnigent-${System.currentTimeMillis()}" | change | S88 | Fallback download filename is saved to Downloads and shown in the 'Saved <name> to Downloads' toast. |

### `web/android/app/src/main/java/ai/omnigent/android/ConnectActivity.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 99 | …R_URL = "ai.omnigent.android.SERVER_UR… | keep-internal |  | Intent extra key passed between MainActivity and |
| 100 | …ERROR = "ai.omnigent.android.CONNECT_E… | keep-internal |  | Intent extra key for connect error; internal ide |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksCredentialScope.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 8 | …ntly stored Databricks workspace grant… | keep-internal |  | code comment |
| 9 | data class DatabricksCredentialScope( | keep-internal |  | code identifier |
| 24 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 25 | ): DatabricksCredentialScope { | keep-internal |  | code identifier |
| 32 | …hentication.DATABRICKS_WORKSPACE | keep-internal |  | code identifier |
| 34 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 37 | … > 1) throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 43 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 46 | return DatabricksCredentialScope(origi… | keep-internal |  | code identifier |
| 67 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksCredentialStore.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 7 | …l interface DatabricksCredentialStorag… | keep-internal |  | code identifier |
| 8 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 11 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 12 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 15 | …lete(scope: DatabricksCredentialScope) | keep-internal |  | code identifier |
| 18 | …ernal class DatabricksCredentialStore( | keep-internal |  | code identifier |
| 21 | …e(context, "databricks-oauth"), | keep-internal |  | Persisted encrypted record store name for Databr |
| 22 | ) : DatabricksCredentialStorage { | keep-internal |  | code identifier |
| 23 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 29 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 30 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 36 | …lete(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 40 | …ode(tokens: DatabricksOAuthTokens): By… | keep-internal |  | code identifier |
| 50 | …ByteArray): DatabricksOAuthTokens { | keep-internal |  | code identifier |
| 56 | DatabricksOAuthIssuer(URI(it)) | keep-internal |  | code identifier |
| 62 | DatabricksOAuthTokens( | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksLoginManager.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 10 | internal class DatabricksLoginManager( | keep-internal |  | code identifier |
| 12 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 13 | DatabricksOAuthConfiguration.fromBuild… | keep-internal |  | code identifier |
| 14 | …al pending: DatabricksPendingAuthStore… | keep-internal |  | code identifier |
| 15 | DatabricksPendingAuthStore(context.app… | keep-internal |  | code identifier |
| 16 | …val client: DatabricksOAuthClient = Da… | keep-internal |  | code identifier |
| 17 | …val tokens: DatabricksTokenManager = D… | keep-internal |  | code identifier |
| 25 | …l attempt = DatabricksOAuthAttempt.cre… | keep-internal |  | code identifier |
| 44 | …back: URI): DatabricksOAuthTokens { | keep-internal |  | code identifier |
| 45 | …() ?: throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 48 | …d) ?: throw DatabricksOAuthException.I… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksOAuthAttempt.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 8 | data class DatabricksOAuthAttempt( | keep-internal |  | code identifier |
| 9 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 10 | …ntialScope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 33 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 39 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 45 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 49 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 52 | throw DatabricksOAuthException.Authori… | keep-internal |  | code identifier |
| 54 | throw DatabricksOAuthException.Authori… | keep-internal |  | code identifier |
| 57 | …ty()) throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 61 | DatabricksOAuthIssuer(URI("${credentia… | keep-internal |  | code identifier |
| 64 | …ty()) throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 66 | DatabricksOAuthIssuer(URI(value)) | keep-internal |  | code identifier |
| 67 | …tch (error: DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 70 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 78 | val issuer: DatabricksOAuthIssuer, | keep-internal |  | code identifier |
| 86 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 88 | ): DatabricksOAuthAttempt = | keep-internal |  | code identifier |
| 89 | DatabricksOAuthAttempt( | keep-internal |  | code identifier |
| 91 | …tialScope = DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 105 | …CHEME = "ai.omnigent.android" | keep-internal |  | MOBILE_REDIRECT_SCHEME ai.omnigent.android is th |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksOAuthClient.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 7 | data class DatabricksOAuthTokens( | keep-internal |  | code identifier |
| 11 | val issuer: DatabricksOAuthIssuer?, | keep-internal |  | code identifier |
| 20 | …n interface DatabricksTokenRefreshing … | keep-internal |  | code identifier |
| 23 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 24 | issuer: DatabricksOAuthIssuer?, | keep-internal |  | code identifier |
| 25 | ): DatabricksOAuthTokens | keep-internal |  | code identifier |
| 28 | class DatabricksOAuthClient internal c… | keep-internal |  | code identifier |
| 31 | ) : DatabricksTokenRefreshing { | keep-internal |  | code identifier |
| 34 | attempt: DatabricksOAuthAttempt, | keep-internal |  | code identifier |
| 35 | issuer: DatabricksOAuthIssuer, | keep-internal |  | code identifier |
| 36 | ): DatabricksOAuthTokens { | keep-internal |  | code identifier |
| 44 | … 200) throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 65 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 66 | issuer: DatabricksOAuthIssuer?, | keep-internal |  | code identifier |
| 67 | ): DatabricksOAuthTokens = | keep-internal |  | code identifier |
| 85 | issuer: DatabricksOAuthIssuer? = null, | keep-internal |  | code identifier |
| 86 | ): DatabricksOAuthTokens { | keep-internal |  | code identifier |
| 96 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 98 | … 200) throw DatabricksOAuthException.T… | keep-internal |  | code identifier |
| 107 | throw DatabricksOAuthException.Network… | keep-internal |  | code identifier |
| 109 | ….uri) throw DatabricksOAuthException.T… | keep-internal |  | code identifier |
| 115 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 117 | issuer: DatabricksOAuthIssuer?, | keep-internal |  | code identifier |
| 137 | issuer: DatabricksOAuthIssuer? = null, | keep-internal |  | code identifier |
| 138 | ): DatabricksOAuthTokens { | keep-internal |  | code identifier |
| 143 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 148 | ?: throw DatabricksOAuthException.Inva… | keep-internal |  | code identifier |
| 153 | …se -> throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 162 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 167 | …lse { throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 168 | …al tokens = DatabricksOAuthTokens(acce… | keep-internal |  | code identifier |
| 169 | …alid) throw DatabricksOAuthException.I… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksOAuthConfiguration.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 6 | data class DatabricksOAuthConfiguratio… | keep-internal |  | code identifier |
| 15 | ) { "Configure a Databricks OAuth client ID for this build." } | keep-origin |  | Names Databricks OAuth as the integration target (build misconfiguration message); third-party service, not publisher. |
| 48 | …CK_SCHEME = DatabricksOAuthAttempt.MOB… | keep-internal |  | code identifier |
| 51 | …ldConfig(): DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 52 | DatabricksOAuthConfiguration( | keep-internal |  | code identifier |
| 53 | …BuildConfig.DATABRICKS_OAUTH_CLIENT_ID… | keep-internal |  | code identifier |
| 54 | …BuildConfig.DATABRICKS_OAUTH_REDIRECT_… | keep-internal |  | code identifier |
| 75 | sealed class DatabricksOAuthException( | keep-internal |  | code identifier |
| 79 | DatabricksOAuthException("Databricks OAuth requires an HTTPS workspace URL.") | keep-origin |  | Error text naming Databricks OAuth/workspace as the integration target. |
| 82 | DatabricksOAuthException("Databricks returned an invalid sign-in callback.") | keep-origin |  | Error text naming Databricks as the sign-in provider being integrated. |
| 85 | DatabricksOAuthException("Databricks returned an unsupported OAuth issuer.") | keep-origin |  | Error text naming Databricks as the OAuth provider; integration target. |
| 88 | DatabricksOAuthException("Databricks returned inconsistent OAuth provider metadata.") | keep-origin |  | Error text naming Databricks OAuth provider metadata; integration target. |
| 90 | class AuthorizationDenied : DatabricksOAuthException("Databricks sign-in was not authorized.") | keep-origin |  | Error text naming Databricks sign-in; integration target. |
| 93 | DatabricksOAuthException("Databricks could not authorize this sign-in.") | keep-origin |  | Error text naming Databricks sign-in authorization; integration target. |
| 96 | DatabricksOAuthException("Could not reach Databricks. Please try again.") | keep-origin |  | Error text naming Databricks network reachability; integration target. |
| 99 | DatabricksOAuthException("Databricks could not complete sign-in. Please sign in again.") | keep-origin |  | Error text naming Databricks sign-in completion; integration target. |
| 102 | DatabricksOAuthException("The saved Databricks session has expired. Please sign in again.") | keep-origin |  | Error text naming the saved Databricks session; integration target. |
| 105 | DatabricksOAuthException("Databricks returned an invalid token response.") | keep-origin |  | Error text naming Databricks token response; integration target. |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksOAuthIssuer.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 6 | …returned by Databricks, distinct from … | keep-internal |  | code comment |
| 7 | data class DatabricksOAuthIssuer( | keep-internal |  | code identifier |
| 11 | …uri)) throw DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 25 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 31 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 47 | …hentication.DATABRICKS_WORKSPACE | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksPendingAuthStore.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 9 | …ernal class DatabricksPendingAuthStore… | keep-internal |  | code identifier |
| 12 | …e(context, "databricks-oauth-attempt")… | keep-internal |  | Persisted encrypted record store name for pendin |
| 17 | …in(attempt: DatabricksOAuthAttempt): P… | keep-internal |  | code identifier |
| 53 | val attempt: DatabricksOAuthAttempt, | keep-internal |  | code identifier |
| 83 | DatabricksOAuthConfiguration( | keep-internal |  | code identifier |
| 94 | DatabricksOAuthAttempt( | keep-internal |  | code identifier |
| 96 | DatabricksCredentialScope.from(workspa… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksSessionClient.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 7 | … data class DatabricksWebContext( | keep-internal |  | code identifier |
| 8 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 9 | val scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 13 | get() = "omnigent-databricks-${sha256H… | keep-internal |  | Persisted WebView profile name (also stored in s |
| 17 | …nCatching { DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 21 | …(uri: URI): DatabricksWebContext { | keep-internal |  | code identifier |
| 22 | …al target = DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 28 | throw DatabricksSessionException.Works… | keep-internal |  | code identifier |
| 34 | …(uri: URI): DatabricksWebContext? { | keep-internal |  | code identifier |
| 36 | …hentication.DATABRICKS_WORKSPACE | keep-internal |  | code identifier |
| 40 | …iguration = DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 41 | val scope = DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 42 | … page = URI(databricksWorkspaceUiUrl(u… | keep-internal |  | code identifier |
| 43 | if (DatabricksWebSession.isLoginPath(p… | keep-internal |  | code identifier |
| 44 | throw DatabricksOAuthException.Invalid… | keep-internal |  | code identifier |
| 46 | return DatabricksWebContext(configurat… | keep-internal |  | code identifier |
| 51 | … data class DatabricksWebSession( | keep-internal |  | code identifier |
| 55 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 67 | …nCatching { DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 74 | …nCatching { DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 161 | throw DatabricksSessionException.Netwo… | keep-internal |  | code identifier |
| 168 | …n interface DatabricksSessionCreating … | keep-internal |  | code identifier |
| 170 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 171 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 172 | ): DatabricksWebSession | keep-internal |  | code identifier |
| 175 | …ernal class DatabricksSessionClient( | keep-internal |  | code identifier |
| 177 | ) : DatabricksSessionCreating { | keep-internal |  | code identifier |
| 179 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 180 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 181 | ): DatabricksWebSession { | keep-internal |  | code identifier |
| 182 | ….isValid \|\| DatabricksWebSession.isLog… | keep-internal |  | code identifier |
| 183 | throw DatabricksSessionException.Inval… | keep-internal |  | code identifier |
| 191 | throw DatabricksSessionException.Works… | keep-internal |  | code identifier |
| 211 | …rent) throw DatabricksSessionException… | keep-internal |  | code identifier |
| 219 | …ECTS) throw DatabricksSessionException… | keep-internal |  | code identifier |
| 221 | …") ?: throw DatabricksSessionException… | keep-internal |  | code identifier |
| 224 | …t) ?: throw DatabricksSessionException… | keep-internal |  | code identifier |
| 227 | throw DatabricksSessionException.Works… | keep-internal |  | code identifier |
| 242 | throw DatabricksSessionException.Rejec… | keep-internal |  | code identifier |
| 255 | throw DatabricksSessionException.Unexp… | keep-internal |  | code identifier |
| 280 | throw DatabricksSessionException.Missi… | keep-internal |  | code identifier |
| 282 | return DatabricksWebSession( | keep-internal |  | code identifier |
| 295 | throw DatabricksSessionException.Unsaf… | keep-internal |  | code identifier |
| 299 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 300 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 305 | DatabricksCredentialScope.from(issuer.… | keep-internal |  | code identifier |
| 311 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 312 | ): DatabricksCredentialScope? = | keep-internal |  | code identifier |
| 313 | …nCatching { DatabricksCredentialScope.… | keep-internal |  | code identifier |
| 320 | …ttps" \|\| !isDatabricksWorkspaceHost(re… | keep-internal |  | code identifier |
| 321 | throw DatabricksSessionException.Inval… | keep-internal |  | code identifier |
| 335 | ?: throw DatabricksSessionException.Un… | keep-internal |  | code identifier |
| 341 | !isDatabricksWorkspaceHost(domain) \|\| | keep-internal |  | code identifier |
| 347 | throw DatabricksSessionException.Unsaf… | keep-internal |  | code identifier |
| 366 | throw DatabricksSessionException.Unsaf… | keep-internal |  | code identifier |
| 387 | …ealed class DatabricksSessionException… | keep-internal |  | code identifier |
| 391 | DatabricksSessionException("Databricks returned an invalid session response.") | keep-origin |  | Error text naming Databricks session response; integration target. |
| 394 | DatabricksSessionException("Databricks returned an unsupported session redirect.") | keep-origin |  | Error text naming Databricks session redirect; integration target. |
| 396 | …ceChanged : DatabricksSessionException… | keep-internal |  | code identifier |
| 398 | class UnsafeCookie : DatabricksSessionException("Databricks returned an unsafe session cookie.") | keep-origin |  | Error text naming Databricks session cookie; integration target. |
| 401 | DatabricksSessionException("Databricks did not create a workspace session cookie.") | keep-origin |  | Error text naming Databricks workspace session cookie; integration target. |
| 404 | DatabricksSessionException("Databricks did not finish loading the workspace session.") | keep-origin |  | Error text naming Databricks workspace session loading; integration target. |
| 407 | DatabricksSessionException("Could not reach Databricks. Please try again.") | keep-origin |  | Error text naming Databricks reachability; integration target. |
| 411 | ) : DatabricksSessionException("Databricks rejected session creation (HTTP $status).") | keep-origin |  | Error text naming Databricks rejecting session creation; integration target. |
| 414 | DatabricksSessionException("Enter a wo… | keep-internal |  | code identifier |
| 417 | DatabricksSessionException("Sign in to… | keep-internal |  | code identifier |
| 420 | DatabricksSessionException("Update And… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksTokenManager.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 11 | internal class DatabricksTokenManager( | keep-internal |  | code identifier |
| 12 | … val store: DatabricksCredentialStorag… | keep-internal |  | code identifier |
| 13 | …val client: DatabricksTokenRefreshing … | keep-internal |  | code identifier |
| 17 | …utableMapOf<DatabricksCredentialScope,… | keep-internal |  | code identifier |
| 18 | …utableMapOf<DatabricksCredentialScope,… | keep-internal |  | code identifier |
| 19 | …utableMapOf<DatabricksCredentialScope,… | keep-internal |  | code identifier |
| 22 | …kens(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 27 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 28 | rejected: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 29 | …tableFuture<DatabricksOAuthTokens?> { | keep-internal |  | code identifier |
| 38 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 39 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 48 | …lear(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 57 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 58 | transform: (DatabricksOAuthTokens) -> … | keep-internal |  | code identifier |
| 67 | …sent(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 76 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 77 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 85 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 87 | …tableFuture<DatabricksOAuthTokens?> { | keep-internal |  | code identifier |
| 99 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 100 | saved: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 101 | …tableFuture<DatabricksOAuthTokens?> { | keep-internal |  | code identifier |
| 104 | …tableFuture<DatabricksOAuthTokens?>() | keep-internal |  | code identifier |
| 115 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 118 | result: Result<DatabricksOAuthTokens>, | keep-internal |  | code identifier |
| 130 | …f (error is DatabricksOAuthException.I… | keep-internal |  | code identifier |
| 146 | …rite(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 154 | …date(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 160 | …tableFuture<DatabricksOAuthTokens?>) = | keep-internal |  | code identifier |
| 165 | val tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 173 | …tableFuture<DatabricksOAuthTokens?>, | keep-internal |  | code identifier |
| 179 | …var shared: DatabricksTokenManager? = … | keep-internal |  | code identifier |
| 181 | …: Context): DatabricksTokenManager = | keep-internal |  | code identifier |
| 183 | shared ?: DatabricksTokenManager( | keep-internal |  | code identifier |
| 184 | DatabricksCredentialStore(context.appl… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksWebProfile.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 52 | internal class DatabricksWebProfile( | keep-internal |  | code identifier |
| 60 | …ll(session: DatabricksWebSession): Com… | keep-internal |  | code identifier |
| 79 | …ceptionally(DatabricksSessionException… | keep-internal |  | code identifier |
| 89 | …ie(session: DatabricksWebSession): Com… | keep-internal |  | code identifier |
| 109 | …ceptionally(DatabricksSessionException… | keep-internal |  | code identifier |
| 154 | completion(DatabricksSessionException.… | keep-internal |  | code identifier |
| 165 | …en(context: DatabricksWebContext): Dat… | keep-internal |  | code identifier |
| 167 | throw DatabricksSessionException.Unsup… | keep-internal |  | code identifier |
| 170 | return DatabricksWebProfile(context.pr… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksWorkspaceCoordinator.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 10 | …ernal class DatabricksWorkspaceCoordin… | keep-internal |  | code identifier |
| 12 | …val tokens: DatabricksTokenManager = D… | keep-internal |  | code identifier |
| 13 | …l sessions: DatabricksSessionCreating … | keep-internal |  | code identifier |
| 15 | …l signOuts: DatabricksSignOutManager =… | keep-internal |  | code identifier |
| 18 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 19 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 20 | …tableFuture<DatabricksWebSession> = | keep-internal |  | code identifier |
| 26 | ?: throw DatabricksSessionException.Re… | keep-internal |  | code identifier |
| 30 | …tch (error: DatabricksSessionException… | keep-internal |  | code identifier |
| 34 | ?: throw DatabricksSessionException.Re… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/DatabricksWorkspaceLifecycle.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 7 | …ernal class DatabricksRecoveryPolicy( | keep-internal |  | code identifier |
| 31 | …ernal class DatabricksSignOutManager( | keep-internal |  | code identifier |
| 33 | …val tokens: DatabricksTokenManager = D… | keep-internal |  | code identifier |
| 35 | …erences("ai.omnigent.android.workspace… | keep-internal |  | SharedPreferences file name holding pending work |
| 40 | …ng(context: DatabricksWebContext): Boo… | keep-internal |  | code identifier |
| 45 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 46 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 91 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 92 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 100 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 101 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/EncryptedRecordStore.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 106 | …dCipher("ai.omnigent.android.$namespac… | keep-internal |  | Android Keystore key alias derived from ai.omnig |
| 109 | …erences("ai.omnigent.android.$namespac… | keep-internal |  | SharedPreferences file name (storage key); persi |
| 110 | …refix = "ai.omnigent.android.$namespac… | keep-internal |  | AEAD associated-data prefix bound into existing |
| 166 | "Could not access saved Databricks credentials. Unlock the device and try again.", | keep-origin |  | Error text names Databricks credentials, the third-party integration target (Databricks workspace sign-in). |
| 170 | CredentialStorageException("The saved Databricks credentials are invalid. Sign in again.") | keep-origin |  | Error text names saved Databricks credentials, the third-party integration target. |

### `web/android/app/src/main/java/ai/omnigent/android/Js.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/Logging.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 11 | …BUG) Log.i("OmnigentAuth", message) | keep-internal |  | Logcat tag for debug-only auth traces; not shown |

### `web/android/app/src/main/java/ai/omnigent/android/MainActivity.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 62 | workspace: DatabricksWebContext?, | keep-internal |  | code identifier |
| 71 | …ellViewˋ + ˋOmnigentWebViewˋ: | keep-internal |  | code comment |
| 72 | …the ˋwindow.omnigentNativeˋ bridge, an… | keep-internal |  | code comment |
| 91 | private var databricksLoginManager: Da… | keep-internal |  | code identifier |
| 96 | private val databricksAuthExecutor = E… | keep-internal |  | code identifier |
| 98 | private val databricksAuthLauncher = | keep-internal |  | code identifier |
| 99 | …is, ::handleDatabricksAuthResult) | keep-internal |  | code identifier |
| 100 | …oordinator: DatabricksWorkspaceCoordin… | keep-internal |  | code identifier |
| 101 | …paceTokens: DatabricksTokenManager? = … | keep-internal |  | code identifier |
| 102 | …ceSignOuts: DatabricksSignOutManager? … | keep-internal |  | code identifier |
| 103 | …aceContext: DatabricksWebContext? = nu… | keep-internal |  | code identifier |
| 104 | …eryContext: DatabricksWebContext? = nu… | keep-internal |  | code identifier |
| 106 | …eryPolicy = DatabricksRecoveryPolicy() | keep-internal |  | code identifier |
| 107 | …aceProfile: DatabricksWebProfile? = nu… | keep-internal |  | code identifier |
| 108 | …aceSession: DatabricksWebSession? = nu… | keep-internal |  | code identifier |
| 109 | …tableFuture<DatabricksWebSession>? = n… | keep-internal |  | code identifier |
| 189 | …nCatching { DatabricksWebContext.resol… | keep-internal |  | code identifier |
| 198 | DatabricksWebProfile.open(context) | keep-internal |  | code identifier |
| 205 | …al tokens = DatabricksTokenManager.sha… | keep-internal |  | code identifier |
| 206 | … signOuts = DatabricksSignOutManager(a… | keep-internal |  | code identifier |
| 214 | …ordinator = DatabricksWorkspaceCoordin… | keep-internal |  | code identifier |
| 307 | …!!(window.__omnigentNativeHandleBack &… | keep-internal |  | window.__omnigentNativeHandleBack JS bridge glob |
| 340 | …hat isn't a Databricks workspace. Serv… | keep-internal |  | code comment |
| 470 | …e fun handleDatabricksAuthResult(resul… | keep-internal |  | code identifier |
| 475 | databricksLoginManager ?: DatabricksLo… | keep-internal |  | code identifier |
| 476 | databricksLoginManager = it | keep-internal |  | code identifier |
| 514 | databricksAuthExecutor.execute { | keep-internal |  | code identifier |
| 588 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 589 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 618 | …f (error is DatabricksSessionException… | keep-internal |  | code identifier |
| 637 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 638 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 657 | …l manager = DatabricksLoginManager(app… | keep-internal |  | code identifier |
| 658 | databricksLoginManager = manager | keep-internal |  | code identifier |
| 659 | …nager.start(databricksAuthLauncher, co… | keep-internal |  | code identifier |
| 686 | databricksLoginManager?.cancel() | keep-internal |  | code identifier |
| 728 | databricksLoginManager?.cancel() | keep-internal |  | code identifier |
| 833 | "window.__omnigentNativeEmitServerPick… | keep-internal |  | window.__omnigentNativeEmitServerPicker JS bridg |
| 834 | "window.__omnigentNativeEmitServerPick… | keep-internal |  | window.__omnigentNativeEmitServerPicker JS bridg |
| 857 | …hentication.DATABRICKS_WORKSPACE | keep-internal |  | code identifier |
| 879 | "window.__omnigentNativeEmitSignOutRes… | keep-internal |  | window.__omnigentNativeEmitSignOutResult JS brid |
| 900 | …ew(profile: DatabricksWebProfile? = nu… | keep-internal |  | code identifier |
| 908 | OmnigentWebViewClient( | keep-internal |  | code identifier |
| 926 | OmnigentWebChromeClient( | keep-internal |  | code identifier |
| 1116 | session: DatabricksWebSession, | keep-internal |  | code identifier |
| 1120 | databricksAuthExecutor.execute { | keep-internal |  | code identifier |
| 1150 | …rigin, and [OmnigentBridgeListener] al… | keep-internal |  | code comment |
| 1162 | OmnigentBridgeListener.JS_OBJECT_NAME, | keep-internal |  | code identifier |
| 1164 | OmnigentBridgeListener( | keep-internal |  | code identifier |
| 1209 | …iggered by [OmnigentWebViewClient] whe… | keep-internal |  | code comment |
| 1327 | …he iOS ˋURL.omnigentHostLabelˋ in ˋURL… | keep-internal |  | code comment |
| 1358 | databricksAuthExecutor.shutdownNow() | keep-internal |  | code identifier |
| 1404 | …hentication.DATABRICKS_WORKSPACE | keep-internal |  | code identifier |
| 1463 | OmnigentBridgeListener.JS_OBJECT_NAME, | keep-internal |  | code identifier |
| 1497 | DatabricksAuthDebugMenu.addItems(this) | keep-internal |  | code identifier |
| 1532 | if (DatabricksAuthDebugMenu.handles(it… | keep-internal |  | code identifier |
| 1554 | DatabricksAuthDebugMenu | keep-internal |  | code identifier |
| 1577 | …guration ?: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 1578 | DatabricksCredentialScope.from(URI(url… | keep-internal |  | code identifier |
| 1628 | "window.__omnigentNativeEmitNotificati… | keep-internal |  | window.__omnigentNativeEmitNotificationActivated |
| 1629 | "window.__omnigentNativeEmitNotificati… | keep-internal |  | window.__omnigentNativeEmitNotificationActivated |
| 1639 | //   1. ˋ--omnigent-safe-top/bottomˋ —… | keep-internal |  | code comment |
| 1640 | … derives ˋ--omnigent-inset-*ˋ and its … | keep-internal |  | code comment |
| 1644 | //   2. ˋ--omnigent-android-safe-area-… | keep-internal |  | code comment |
| 1647 | …NOT call ˋ__omnigentNativeEmitInsetsˋ … | keep-internal |  | code comment |
| 1648 | …otprints (--omnigent-native-*-bar; nat… | keep-internal |  | code comment |
| 1659 | …Property('--omnigent-safe-top', top); | keep-internal |  | --omnigent-safe-top CSS custom property read by |
| 1660 | …Property('--omnigent-safe-bottom', bot… | keep-internal |  | --omnigent-safe-bottom CSS custom property; inte |
| 1661 | …Property('--omnigent-android-safe-area… | keep-internal |  | --omnigent-android-safe-area-top CSS custom prop |
| 1662 | …Property('--omnigent-android-safe-area… | keep-internal |  | --omnigent-android-safe-area-bottom CSS custom p |
| 1663 | …Property('--omnigent-android-safe-area… | keep-internal |  | --omnigent-android-safe-area-left CSS custom pro |
| 1664 | …Property('--omnigent-android-safe-area… | keep-internal |  | --omnigent-android-safe-area-right CSS custom pr |
| 1681 | /** Back [OmnigentWebChromeClient.onSh… | keep-internal |  | code comment |
| 1727 | /** Back [OmnigentWebChromeClient.onPe… | keep-internal |  | code comment |
| 1752 | // (fixes omnigent-ai/omnigent#969, wh… | keep-internal |  | code comment |
| 1789 | …QUEST = "ai.omnigent.android.CONNECT_R… | keep-internal |  | Intent extra key namespaced by the ai.omnigent.a |

### `web/android/app/src/main/java/ai/omnigent/android/ManagedConfig.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/NativeBridgeScript.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 5 | * ˋwindow.omnigentNativeˋ with ˋkind: … | keep-internal |  | code comment |
| 6 | …e (ˋweb/ios/Omnigent/OmnigentWebView.s… | keep-internal |  | code comment |
| 8 | * ˋ__omnigentNativeEmit*ˋ callback nam… | keep-internal |  | code comment |
| 11 | …es through [OmnigentBridgeListener.JS_… | keep-internal |  | code comment |
| 15 | …e ˋwindow.__omnigentNativeEmit*ˋ funct… | keep-internal |  | code comment |
| 21 | if (window.omnigentNative && window.om… | keep-internal |  | code identifier |
| 51 | // feeds --omnigent-safe-top/bottom (t… | keep-internal |  | code comment |
| 62 | …lementById("omnigent-android-insets"))… | keep-internal |  | DOM element id omnigent-android-insets used as a |
| 63 | … T = "var(--omnigent-safe-top, 0px)"; | keep-internal |  | --omnigent-safe-top CSS variable reference; inte |
| 64 | … B = "var(--omnigent-safe-bottom, 0px)… | keep-internal |  | --omnigent-safe-bottom CSS variable reference; i |
| 66 | style.id = "omnigent-android-insets"; | keep-internal |  | Injected style element id omnigent-android-inset |
| 69 | …:calc(var(--omnigent-header-height, 3.… | keep-internal |  | --omnigent-header-height CSS variable in injecte |
| 87 | … = window.${OmnigentBridgeListener.JS_… | keep-internal |  | code identifier |
| 98 | …(window, "__omnigentNativeEmitNotifica… | keep-internal |  | Defines window.__omnigentNativeEmitNotificationA |
| 110 | …(window, "__omnigentNativeEmitServerPi… | keep-internal |  | Defines window.__omnigentNativeEmitServerPicker |
| 131 | …(window, "__omnigentNativeEmitSignOutR… | keep-internal |  | Defines window.__omnigentNativeEmitSignOutResult |
| 144 | …(window, "__omnigentNativeEmitInsets",… | keep-internal |  | Defines window.__omnigentNativeEmitInsets bridge |
| 161 | …(window, "__omnigentNativeHandleBack",… | keep-internal |  | Defines window.__omnigentNativeHandleBack bridge |
| 236 | window.omnigentNative = Object.freeze(… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/NativeNotificationManager.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 18 | * ˋwindow.__omnigentNativeEmitNotifica… | keep-internal |  | code comment |
| 173 | …_PATH = "ai.omnigent.android.NAVIGATE_… | keep-internal |  | Intent extra key namespaced by Kotlin package; i |
| 174 | …ANNEL_ID = "omnigent.sessions" | keep-internal |  | Notification channel id (persisted by OS); user- |

### `web/android/app/src/main/java/ai/omnigent/android/OAuthCallbackActivity.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 12 | …m Tabs: the Databricks | keep-internal |  | code comment |
| 55 | DatabricksLoginManager(applicationCont… | keep-internal |  | code identifier |
| 71 | …LBACK = "ai.omnigent.android.OAUTH_CAL… | keep-internal |  | Intent extra key namespaced by Kotlin package; i |
| 72 | …ERROR = "ai.omnigent.android.OAUTH_ERR… | keep-internal |  | Intent extra key namespaced by Kotlin package; i |

### `web/android/app/src/main/java/ai/omnigent/android/OAuthCallbackCompletions.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OAuthCallbackHandoff.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 11 | …erences("ai.omnigent.android.oauth-cal… | keep-internal |  | SharedPreferences file name (storage key); not u |

### `web/android/app/src/main/java/ai/omnigent/android/OAuthSupport.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OAuthTransport.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OidcCredentialStore.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OidcCredentials.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 28 | …CHEME = "ai.omnigent.android" | keep-internal |  | OAuth redirect scheme ai.omnigent.android, allow |
| 29 | …T_URI = "ai.omnigent.android:/oauth/ca… | keep-internal |  | OAuth redirect URI ai.omnigent.android:/oauth/ca |

### `web/android/app/src/main/java/ai/omnigent/android/OidcLoginManager.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 30 | * ˋomnigent loginˋ CLI uses, no server… | keep-internal |  | code comment |
| 34 | …..ˋ with ˋX-Omnigent-Code-Verifierˋ ->… | keep-internal |  | code comment |
| 220 | …Property("X-Omnigent-Code-Verifier", c… | keep-internal |  | X-Omnigent-Code-Verifier protocol header parsed |

### `web/android/app/src/main/java/ai/omnigent/android/OidcPendingSignInStore.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OidcSessionController.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OidcSignInLauncher.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OidcWebSession.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OmnigentBridgeListener.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 23 | class OmnigentBridgeListener( | keep-internal |  | code identifier |
| 133 | …ECT_NAME = "omnigentNativeBridge" | keep-internal |  | omnigentNativeBridge injected JS object name use |

### `web/android/app/src/main/java/ai/omnigent/android/OmnigentWebChromeClient.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 19 | class OmnigentWebChromeClient( | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/OmnigentWebViewClient.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 20 | * bare Databricks workspace root is bo… | keep-internal |  | code comment |
| 34 | internal class OmnigentWebViewClient( | keep-internal |  | code identifier |
| 42 | …sion: () -> DatabricksWebSession? = { … | keep-internal |  | code identifier |
| 51 | …re-root -> /omnigent bounces since the… | keep-internal |  | code comment |
| 120 | // Databricks login chain hands the se… | keep-internal |  | code comment |
| 161 | …edOrigin && databricksWorkspaceUiUrl(u… | keep-internal |  | code identifier |
| 162 | // Databricks workspace-hosted Omnigen… | keep-internal |  | code comment |
| 164 | // Omnigent's own root — see [Workspac… | keep-internal |  | code comment |
| 218 | … belongs to Databricks rather than the… | keep-internal |  | code comment |
| 273 | session: DatabricksWebSession, | keep-internal |  | code identifier |
| 294 | * The ˋ/omnigentˋ URL to bounce to whe… | keep-internal |  | code comment |
| 299 | * ˋ/omnigentˋ with a redirect back to … | keep-internal |  | code comment |
| 305 | …al target = databricksWorkspaceUiUrl(u… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/Origins.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 42 | … ˋhttps://h/omnigent/ˋ + ˋ/v1/meˋ is ˋ… | keep-internal |  | code comment |
| 56 | …or a pinned Omnigent server. */ | keep-internal |  | code comment |
| 58 | /** A Databricks workspace, where Omni… | keep-internal |  | code comment |
| 59 | DATABRICKS_WORKSPACE, | keep-internal |  | code identifier |
| 61 | /** A Databricks App, which serves the… | keep-internal |  | code comment |
| 62 | DATABRICKS_APP, | keep-internal |  | code identifier |
| 64 | /** Omnigent's generic OIDC flow for e… | keep-internal |  | code comment |
| 68 | /** Only Databricks Apps retain embedd… | keep-internal |  | code comment |
| 70 | get() = this == DATABRICKS_APP | keep-internal |  | code identifier |
| 73 | …** Path the Omnigent SPA is mounted at… | keep-internal |  | code comment |
| 74 | …UI_PATH = "/omnigent" | keep-internal |  | /omnigent workspace mount path (API/URL path) in |
| 76 | private val WORKSPACE_DOMAINS = listOf("databricks.com", "azuredatabricks.net") | keep-origin |  | Databricks workspace domains used to detect the Databricks integration target. |
| 77 | private const val DATABRICKS_APP_DOMAIN = "databricksapps.com" | keep-origin |  | databricksapps.com domain for Databricks Apps hosting detection; third-party integration. |
| 79 | …suffixes as Databricks hosts. */ | keep-internal |  | code comment |
| 83 | …hentication.DATABRICKS_WORKSPACE | keep-internal |  | code identifier |
| 84 | …ost, listOf(DATABRICKS_APP_DOMAIN)) ->… | keep-internal |  | code identifier |
| 89 | …ts under, a Databricks workspace domai… | keep-internal |  | code comment |
| 90 | fun isDatabricksWorkspaceHost(host: St… | keep-internal |  | code identifier |
| 101 | … for a bare Databricks workspace root,… | keep-internal |  | code comment |
| 105 | …t shows the Databricks landing page, n… | keep-internal |  | code comment |
| 109 | fun databricksWorkspaceUiUrl(url: Stri… | keep-internal |  | code identifier |
| 112 | if (!isDatabricksWorkspaceHost(uri.hos… | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/ServerManifest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 9 | ….well-known/omnigent.jsonˋ, read befor… | keep-internal |  | code comment |
| 49 | ….well-known/omnigent.json" | keep-internal |  | /.well-known/omnigent.json API path served by th |

### `web/android/app/src/main/java/ai/omnigent/android/ServerStore.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 30 | * Databricks workspace root resolves t… | keep-internal |  | code comment |
| 36 | return databricksWorkspaceUiUrl(stored… | keep-internal |  | code identifier |
| 73 | …PREFS = "ai.omnigent.android.servers" | keep-internal |  | SharedPreferences file name holding saved server |

### `web/android/app/src/main/java/ai/omnigent/android/UserConnectRequests.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/WorkspaceChromeScript.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 4 | … Hiding the Databricks workspace navig… | keep-internal |  | code comment |
| 5 | * Omnigent SPA. Kept in its own ˋWebVi… | keep-internal |  | code comment |
| 15 | …t hides the Databricks workspace navig… | keep-internal |  | code comment |
| 17 | … *page*, so Databricks wraps | keep-internal |  | code comment |
| 19 | … We promote Omnigent's own | keep-internal |  | code comment |
| 20 | * root — ˋ.omnigent-appˋ, which the em… | keep-internal |  | code comment |
| 22 | * Omnigent's wrapper (defined in THIS … | keep-internal |  | code comment |
| 24 | * Databricks reshuffles its chrome; on… | keep-internal |  | code comment |
| 25 | * no ˋ.omnigent-appˋ, so the rule is a… | keep-internal |  | code comment |
| 29 | .omnigent-app { | keep-internal |  | code identifier |
| 41 | … than the ˋ/omnigentˋ mount, so a path… | keep-internal |  | code comment |
| 49 | …"style[data-omnigent-workspace-chrome]… | keep-internal |  | data-omnigent-workspace-chrome data attribute us |
| 51 | …yle.dataset.omnigentWorkspaceChrome = … | keep-internal |  | code identifier |

### `web/android/app/src/main/java/ai/omnigent/android/WorkspaceSessionProbe.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 102 | return DatabricksWebSession.isLoginPat… | keep-internal |  | code identifier |

### `web/android/app/src/main/res/drawable/bg_button_primary.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Plain shape drawable (brand colour reference); n |

### `web/android/app/src/main/res/drawable/bg_floating_switch.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Plain shape drawable; not artwork. |

### `web/android/app/src/main/res/drawable/bg_input.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Plain shape drawable; not artwork. |

### `web/android/app/src/main/res/drawable/bg_recent.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Plain shape drawable; not artwork. |

### `web/android/app/src/main/res/drawable/ic_launcher_foreground.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish adaptive-icon foreground; the launcher now uses coral_launcher_foreground. Kept, unused. |

### `web/android/app/src/main/res/drawable/ic_launcher_monochrome.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish themed icon; the launcher now uses coral_launcher_monochrome. Kept, unused. |

### `web/android/app/src/main/res/drawable/ic_notification.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish notification silhouette; notifications now use coral_notification. Kept, unused. |

### `web/android/app/src/main/res/drawable/omnigents_logo.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Omnigent connect-screen logo; activity_connect.xml now uses coral_logo. Kept, unused. |

### `web/android/app/src/main/res/layout/activity_connect.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 32 | android:src="@drawable/omnigents_logo" /> | change-asset | S88 | Connect screen shows omnigents_logo drawable (starfish plus Omnigent wordmark) to users. |

### `web/android/app/src/main/res/values-night/themes.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …name="Theme.Omnigent" parent="Theme.Ap… | keep-internal |  | Theme.Omnigent style resource name referenced by |

### `web/android/app/src/main/res/values/strings.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | <string name="app_name">Omnigent</string> | change | S88 | app_name is the launcher label (manifest android:label) and notification title fallback. |
| 5 | <string name="signed_in_title">Signed in to Omnigent</string> | change | S88 | Notification title shown after sign-in (MainActivity signed_in_title). |
| 11 | <string name="connect_logo_desc">Omnigent</string> | change | S88 | contentDescription (accessibility text) of the connect-screen logo. |
| 12 | …t_subtitle">Enter the URL of the Omnigent server. The Android app loads its web UI directly.</string… | change | S88 | Connect-screen subtitle uses 'Omnigent server' product wording. |
| 14 | <string name="connect_hint">https://omnigent.example.com</string> | change | S88 | Server URL field placeholder shows omnigent as example host to users. |
| 19 | <string name="about_title">About Omnigent</string> | change | S88 | About dialog title (ConnectActivity setTitle about_title). |
| 21 | <string name="oauth_completing">Completing Databricks sign-in…</string> | keep-origin |  | Names Databricks sign-in, the third-party integration target. |
| 23 | <string name="oauth_invalid_callback">Databricks returned an invalid sign-in callback.</string> | keep-origin |  | Names Databricks as the OAuth provider returning the callback; integration target. |
| 24 | <string name="oauth_connecting">Connecting securely to your Databricks workspace…</string> | keep-origin |  | Names the user's Databricks workspace; integration target. |
| 25 | <string name="oauth_opening_browser">Continue sign-in in Auth Tab, then return to Omnigent.</string> | change | S88 | Connection status text shown in MainActivity names the app as Omnigent. |
| 32 | <string name="oauth_permission_denied">Databricks denied access to this workspace.</string> | keep-origin |  | Names Databricks denying workspace access; integration target. |
| 44 | <string name="restriction_server_urls_title">Omnigent server URLs</string> | change | S88 | Managed-config restriction title shown to IT admins in EMM console; display-only, key unchanged. |

### `web/android/app/src/main/res/values/themes.xml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …name="Theme.Omnigent" parent="Theme.Ap… | keep-internal |  | Theme.Omnigent style resource name referenced by |

### `web/android/app/src/release/java/ai/omnigent/android/DatabricksAuthDebugMenu.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 7 | …rnal object DatabricksAuthDebugMenu { | keep-internal |  | code identifier |
| 14 | tokens: DatabricksTokenManager, | keep-internal |  | code identifier |
| 15 | context: DatabricksWebContext, | keep-internal |  | code identifier |
| 16 | profile: DatabricksWebProfile, | keep-internal |  | code identifier |
| 17 | session: DatabricksWebSession, | keep-internal |  | code identifier |

### `web/android/app/src/release/java/ai/omnigent/android/OidcAuthDebugMenu.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |

### `web/android/app/src/test/java/ai/omnigent/android/AndroidKeystoreRecordCipherTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksCredentialStoreTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 15 | class DatabricksCredentialStoreTest { | keep-internal |  | test code |
| 18 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 20 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 23 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 24 | …c-123.cloud.databricks.com?o=42"), | keep-internal |  | test code |
| 27 | …al issuer = DatabricksOAuthIssuer(URI(… | keep-internal |  | test code |
| 32 | val store = DatabricksCredentialStore(… | keep-internal |  | test code |
| 33 | …al tokens = DatabricksOAuthTokens("acc… | keep-internal |  | test code |
| 39 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 40 | …c-123.cloud.databricks.com?o=43"), | keep-internal |  | test code |
| 51 | val store = DatabricksCredentialStore(… | keep-internal |  | test code |
| 52 | …save(scope, DatabricksOAuthTokens("a",… | keep-internal |  | test code |
| 68 | val store = DatabricksCredentialStore(… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksLoginManagerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 24 | class DatabricksLoginManagerTest { | keep-internal |  | test code |
| 27 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 29 | URI("ai.omnigent.android://mobile-redi… | keep-internal |  | test code |
| 37 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 43 | val oauth = DatabricksOAuthClient(tran… | keep-internal |  | test code |
| 45 | DatabricksTokenManager( | keep-internal |  | test code |
| 51 | DatabricksLoginManager( | keep-internal |  | test code |
| 63 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 93 | DatabricksLoginManager( | keep-internal |  | test code |
| 96 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 113 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 121 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 123 | DatabricksLoginManager( | keep-internal |  | test code |
| 126 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 134 | DatabricksOAuthClient(RecordingTranspo… | keep-internal |  | test code |
| 135 | DatabricksTokenManager(MemoryCredentia… | keep-internal |  | test code |
| 139 | …c-123.cloud.databricks.com"))) | keep-internal |  | test code |
| 167 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 177 | DatabricksLoginManager( | keep-internal |  | test code |
| 181 | DatabricksOAuthClient(RecordingTranspo… | keep-internal |  | test code |
| 182 | DatabricksTokenManager(store), | keep-internal |  | test code |
| 184 | …c-123.cloud.databricks.com")) | keep-internal |  | test code |
| 190 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 199 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 208 | DatabricksLoginManager( | keep-internal |  | test code |
| 212 | DatabricksOAuthClient(RecordingTranspo… | keep-internal |  | test code |
| 213 | DatabricksTokenManager(MemoryCredentia… | keep-internal |  | test code |
| 215 | …c-123.cloud.databricks.com")) | keep-internal |  | test code |
| 217 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 247 | …tialStore : DatabricksCredentialStorag… | keep-internal |  | test code |
| 248 | var value: DatabricksOAuthTokens? = nu… | keep-internal |  | test code |
| 250 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 253 | scope: DatabricksCredentialScope, | keep-internal |  | test code |
| 254 | tokens: DatabricksOAuthTokens, | keep-internal |  | test code |
| 259 | …lete(scope: DatabricksCredentialScope)… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksOAuthAttemptTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 14 | class DatabricksOAuthAttemptTest { | keep-internal |  | test code |
| 16 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 18 | URI("ai.omnigent.android://mobile-redi… | keep-internal |  | test code |
| 21 | DatabricksOAuthAttempt( | keep-internal |  | test code |
| 24 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 25 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 48 | …c-123.cloud.databricks.com/oidc/v1/aut… | keep-internal |  | test code |
| 65 | URI("ai.omnigent.android://mobile-redi… | keep-internal |  | test code |
| 70 | …c-123.cloud.databricks.com/oidc"), | keep-internal |  | test code |
| 82 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 89 | …c-123.cloud.databricks.com/oidc"), | keep-internal |  | test code |
| 96 | …ounts.cloud.databricks.com%2Foidc%2Fac… | keep-internal |  | test code |
| 100 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 106 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 115 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 116 | "ai.omnigent.android://other?code=abc&… | keep-internal |  | test code |
| 117 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 118 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 119 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 120 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 123 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 127 | …ssertThrows(DatabricksOAuthException.A… | keep-internal |  | test code |
| 130 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 135 | …ssertThrows(DatabricksOAuthException.A… | keep-internal |  | test code |
| 138 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 149 | DatabricksOAuthAttempt.create( | keep-internal |  | test code |
| 150 | …c-123.cloud.databricks.com"), | keep-internal |  | test code |
| 156 | …tEquals("ai.omnigent.android", stateDo… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksOAuthClientTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 12 | class DatabricksOAuthClientTest { | keep-internal |  | test code |
| 14 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 16 | URI("ai.omnigent.android://mobile-redi… | keep-internal |  | test code |
| 19 | DatabricksOAuthAttempt( | keep-internal |  | test code |
| 21 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 22 | …c-123.cloud.databricks.com?o=42"), | keep-internal |  | test code |
| 29 | DatabricksOAuthIssuer(URI("https://acc… | keep-internal |  | test code |
| 48 | …al client = DatabricksOAuthClient(tran… | keep-internal |  | test code |
| 82 | …al client = DatabricksOAuthClient(tran… | keep-internal |  | test code |
| 84 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 101 | DatabricksOAuthClient(transport) { 2_0… | keep-internal |  | test code |
| 125 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 126 | DatabricksOAuthClient(invalidGrant).re… | keep-internal |  | test code |
| 140 | …ssertThrows(DatabricksOAuthException.T… | keep-internal |  | test code |
| 141 | DatabricksOAuthClient(serverFailure).r… | keep-internal |  | test code |
| 154 | …other.cloud.databricks.com/oidc/.well-… | keep-internal |  | test code |
| 159 | …ssertThrows(DatabricksOAuthException.T… | keep-internal |  | test code |
| 160 | DatabricksOAuthClient(transport).excha… | keep-internal |  | test code |
| 165 | …nse reports Databricks as unreachableˋ… | keep-internal |  | test code |
| 168 | …ssertThrows(DatabricksOAuthException.N… | keep-internal |  | test code |
| 169 | DatabricksOAuthClient(transport).refre… | keep-internal |  | test code |
| 186 | …hrows(body, DatabricksOAuthException.I… | keep-internal |  | test code |
| 187 | DatabricksOAuthClient.tokens(body.toBy… | keep-internal |  | test code |
| 191 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 192 | DatabricksOAuthClient.tokens( | keep-internal |  | test code |
| 203 | DatabricksOAuthClient.tokens( | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksOAuthConfigurationTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 13 | class DatabricksOAuthConfigurationTest… | keep-internal |  | test code |
| 15 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 17 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 23 | DatabricksOAuthConfiguration("", confi… | keep-internal |  | test code |
| 26 | DatabricksOAuthConfiguration("client i… | keep-internal |  | test code |
| 29 | …ttp://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 30 | …/user@login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 31 | …tps://login.databricks.com:8443/mobile… | keep-internal |  | test code |
| 32 | "https://login.databricks.com", | keep-internal |  | test code |
| 33 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 34 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 35 | "ai.omnigent.android://other", | keep-internal |  | test code |
| 36 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 37 | "ai.omnigent.android://user@mobile-red… | keep-internal |  | test code |
| 38 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 39 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 42 | DatabricksOAuthConfiguration("public-c… | keep-internal |  | test code |
| 51 | …tps://LOGIN.DATABRICKS.COM:443/mobile-… | keep-internal |  | test code |
| 56 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 61 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 70 | URI("ai.omnigent.android://mobile-redi… | keep-internal |  | test code |
| 74 | "ai.omnigent.android://other?state=opa… | keep-internal |  | test code |
| 75 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 76 | "ai.omnigent.android://user@mobile-red… | keep-internal |  | test code |
| 77 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 86 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 88 | URI("ai.omnigent.android://mobile-redi… | keep-internal |  | test code |
| 94 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 102 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 103 | …C-123.Cloud.Databricks.com:443/omnigen… | keep-internal |  | test code |
| 107 | …c-123.cloud.databricks.com"), scope.wo… | keep-internal |  | test code |
| 116 | …c-123.cloud.databricks.com/?o=1&o=2", | keep-internal |  | test code |
| 117 | …c-123.cloud.databricks.com/?o=", | keep-internal |  | test code |
| 118 | …c-123.cloud.databricks.com/?o=12a", | keep-internal |  | test code |
| 119 | …c-123.cloud.databricks.com/?o=%D9%A1%D… | keep-internal |  | test code |
| 120 | …ps://my-app.databricksapps.com/?o=12", | keep-internal |  | test code |
| 121 | …c-123.cloud.databricks.com/?o=12", | keep-internal |  | test code |
| 123 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 124 | DatabricksCredentialScope.from(URI(url… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksOAuthIssuerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 11 | class DatabricksOAuthIssuerTest { | keep-internal |  | test code |
| 14 | …workspace = DatabricksOAuthIssuer(URI(… | keep-internal |  | test code |
| 16 | DatabricksOAuthIssuer( | keep-internal |  | test code |
| 17 | …counts.azuredatabricks.net/oidc/accoun… | keep-internal |  | test code |
| 22 | …c-123.cloud.databricks.com/oidc/.well-… | keep-internal |  | test code |
| 27 | …counts.azuredatabricks.net/oidc/accoun… | keep-internal |  | test code |
| 35 | …c-123.cloud.databricks.com/oidc", | keep-internal |  | test code |
| 36 | …c-123.cloud.databricks.com/oidc", | keep-internal |  | test code |
| 37 | …c-123.cloud.databricks.com:8443/oidc", | keep-internal |  | test code |
| 38 | …c-123.cloud.databricks.com/oidc?x=1", | keep-internal |  | test code |
| 39 | …c-123.cloud.databricks.com/oidc#x", | keep-internal |  | test code |
| 40 | …c-123.cloud.databricks.com/oauth", | keep-internal |  | test code |
| 41 | …c-123.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 42 | …c-123.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 43 | …tps://myapp.databricksapps.com/oidc", | keep-internal |  | test code |
| 44 | "https://databricks.com.example.org/oi… | keep-internal |  | test code |
| 46 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |
| 47 | DatabricksOAuthIssuer(URI(value)) | keep-internal |  | test code |
| 54 | …al issuer = DatabricksOAuthIssuer(URI(… | keep-internal |  | test code |
| 61 | …other.cloud.databricks.com/oidc","toke… | keep-internal |  | test code |
| 66 | …ssertThrows(DatabricksOAuthException.I… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksPendingAuthStoreTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 18 | class DatabricksPendingAuthStoreTest { | keep-internal |  | test code |
| 21 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 23 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 26 | DatabricksOAuthAttempt( | keep-internal |  | test code |
| 28 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 29 | …c-123.cloud.databricks.com?o=42"), | keep-internal |  | test code |
| 41 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 47 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 63 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 82 | DatabricksPendingAuthStore( | keep-internal |  | test code |
| 108 | DatabricksPendingAuthStore(context, re… | keep-internal |  | test code |
| 109 | assertNull(DatabricksPendingAuthStore(… | keep-internal |  | test code |
| 113 | DatabricksPendingAuthStore(context, re… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksSessionClientTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 13 | class DatabricksSessionClientTest { | keep-internal |  | test code |
| 15 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 17 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 20 | DatabricksWebContext( | keep-internal |  | test code |
| 22 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 23 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 26 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 28 | …al issuer = DatabricksOAuthIssuer(URI(… | keep-internal |  | test code |
| 29 | …al tokens = DatabricksOAuthTokens("acc… | keep-internal |  | test code |
| 39 | …alias.cloud.databricks.com/auth/sessio… | keep-internal |  | test code |
| 41 | …main=.cloud.databricks.com; Path=/; Se… | keep-internal |  | test code |
| 51 | …main=.cloud.databricks.com; Path=/; Se… | keep-internal |  | test code |
| 58 | …to listOf("/omnigent?o=42&next_url=%2F… | keep-internal |  | test code |
| 62 | …l session = DatabricksSessionClient(tr… | keep-internal |  | test code |
| 65 | …alias.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 73 | …alias.cloud.databricks.com/sso/a%2Fb?o… | keep-internal |  | test code |
| 74 | …alias.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 86 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 88 | …alias.cloud.databricks.com" | keep-internal |  | test code |
| 92 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 102 | DatabricksWebSession( | keep-internal |  | test code |
| 103 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 105 | …c-123.cloud.databricks.com", "https://… | keep-internal |  | test code |
| 111 | …c-123.cloud.databricks.com/auth/logout… | keep-internal |  | test code |
| 113 | …alias.cloud.databricks.com/logout"))) | keep-internal |  | test code |
| 115 | …c-123.cloud.databricks.com/login.html?… | keep-internal |  | test code |
| 119 | …c-123.cloud.databricks.com/auth/logout… | keep-internal |  | test code |
| 121 | …c-456.cloud.databricks.com/auth/logout… | keep-internal |  | test code |
| 122 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 127 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 128 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 129 | …c-456.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 140 | …ssertThrows(DatabricksSessionException… | keep-internal |  | test code |
| 141 | DatabricksSessionClient.parseCookies( | keep-internal |  | test code |
| 143 | …c-123.cloud.databricks.com/auth/sessio… | keep-internal |  | test code |
| 153 | …annot leave Databricks or change works… | keep-internal |  | test code |
| 154 | …eRedirect = DatabricksSessionException… | keep-internal |  | test code |
| 155 | …ceChanged = DatabricksSessionException… | keep-internal |  | test code |
| 157 | …vil.example/omnigent" to unsafeRedirec… | keep-internal |  | test code |
| 158 | …other.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 159 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 164 | DatabricksSessionClient(transport).cre… | keep-internal |  | test code |
| 172 | DatabricksWebContext( | keep-internal |  | test code |
| 174 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 175 | …c-123.cloud.databricks.com"), | keep-internal |  | test code |
| 178 | …c-123.cloud.databricks.com/omnigent"), | keep-internal |  | test code |
| 183 | DatabricksOAuthIssuer( | keep-internal |  | test code |
| 184 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 188 | …ssertThrows(DatabricksSessionException… | keep-internal |  | test code |
| 189 | DatabricksSessionClient(QueueTransport… | keep-internal |  | test code |
| 197 | …ssertThrows(DatabricksSessionException… | keep-internal |  | test code |
| 198 | DatabricksSessionClient(transport).cre… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksTokenManagerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 18 | class DatabricksTokenManagerTest { | keep-internal |  | test code |
| 20 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 22 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 25 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 26 | …c-123.cloud.databricks.com?o=42"), | keep-internal |  | test code |
| 29 | …al issuer = DatabricksOAuthIssuer(URI(… | keep-internal |  | test code |
| 84 | … _ -> throw DatabricksOAuthException.I… | keep-internal |  | test code |
| 93 | … _ -> throw DatabricksOAuthException.N… | keep-internal |  | test code |
| 99 | …or.cause is DatabricksOAuthException.N… | keep-internal |  | test code |
| 158 | refresher: DatabricksTokenRefreshing, | keep-internal |  | test code |
| 159 | ) = DatabricksTokenManager( | keep-internal |  | test code |
| 169 | ) = DatabricksOAuthTokens(access, refr… | keep-internal |  | test code |
| 172 | var value: DatabricksOAuthTokens?, | keep-internal |  | test code |
| 173 | ) : DatabricksCredentialStorage { | keep-internal |  | test code |
| 176 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 179 | scope: DatabricksCredentialScope, | keep-internal |  | test code |
| 180 | tokens: DatabricksOAuthTokens, | keep-internal |  | test code |
| 189 | …lete(scope: DatabricksCredentialScope)… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksWebProfileTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 18 | class DatabricksWebProfileTest { | keep-internal |  | test code |
| 20 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 22 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 31 | DatabricksWebContext( | keep-internal |  | test code |
| 33 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 34 | …c-123.cloud.databricks.com?o=42"), | keep-internal |  | test code |
| 37 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 50 | …l profile = DatabricksWebProfile("prof… | keep-internal |  | test code |
| 64 | …l profile = DatabricksWebProfile("prof… | keep-internal |  | test code |
| 73 | …or.cause is DatabricksSessionException… | keep-internal |  | test code |
| 80 | …l profile = DatabricksWebProfile("prof… | keep-internal |  | test code |
| 97 | …l profile = DatabricksWebProfile("prof… | keep-internal |  | test code |
| 107 | …d: String): DatabricksWebContext { | keep-internal |  | test code |
| 108 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 109 | return DatabricksWebContext( | keep-internal |  | test code |
| 111 | DatabricksCredentialScope.from(uri, co… | keep-internal |  | test code |
| 116 | … session(): DatabricksWebSession { | keep-internal |  | test code |
| 117 | …c-123.cloud.databricks.com/auth/sessio… | keep-internal |  | test code |
| 118 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 119 | return DatabricksWebSession( | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksWorkspaceCoordinatorTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 20 | class DatabricksWorkspaceCoordinatorTe… | keep-internal |  | test code |
| 23 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 25 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 28 | DatabricksWebContext( | keep-internal |  | test code |
| 30 | DatabricksCredentialScope.from( | keep-internal |  | test code |
| 31 | …c-123.cloud.databricks.com?o=42"), | keep-internal |  | test code |
| 34 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 36 | …al issuer = DatabricksOAuthIssuer(URI(… | keep-internal |  | test code |
| 42 | …enManager = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 44 | …l profile = DatabricksWebProfile(conte… | keep-internal |  | test code |
| 47 | DatabricksWorkspaceCoordinator( | keep-internal |  | test code |
| 50 | DatabricksSessionCreating { _, receive… | keep-internal |  | test code |
| 71 | DatabricksTokenManager( | keep-internal |  | test code |
| 81 | DatabricksWorkspaceCoordinator( | keep-internal |  | test code |
| 84 | DatabricksSessionCreating { _, receive… | keep-internal |  | test code |
| 85 | …== 0) throw DatabricksSessionException… | keep-internal |  | test code |
| 91 | …l profile = DatabricksWebProfile(conte… | keep-internal |  | test code |
| 112 | …enManager = DatabricksTokenManager(Mem… | keep-internal |  | test code |
| 114 | DatabricksWorkspaceCoordinator( | keep-internal |  | test code |
| 117 | DatabricksSessionCreating { _, _ -> | keep-internal |  | test code |
| 126 | DatabricksWebProfile(context.profileNa… | keep-internal |  | test code |
| 130 | …or.cause is DatabricksSessionException… | keep-internal |  | test code |
| 145 | ) = DatabricksOAuthTokens(access, refr… | keep-internal |  | test code |
| 147 | …e: String): DatabricksWebSession { | keep-internal |  | test code |
| 148 | …c-123.cloud.databricks.com/auth/sessio… | keep-internal |  | test code |
| 149 | return DatabricksWebSession( | keep-internal |  | test code |
| 172 | var value: DatabricksOAuthTokens?, | keep-internal |  | test code |
| 173 | ) : DatabricksCredentialStorage { | keep-internal |  | test code |
| 174 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 177 | scope: DatabricksCredentialScope, | keep-internal |  | test code |
| 178 | tokens: DatabricksOAuthTokens, | keep-internal |  | test code |
| 183 | …lete(scope: DatabricksCredentialScope)… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/DatabricksWorkspaceLifecycleTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 23 | class DatabricksWorkspaceLifecycleTest… | keep-internal |  | test code |
| 28 | …al policy = DatabricksRecoveryPolicy(c… | keep-internal |  | test code |
| 42 | …l manager = DatabricksSignOutManager(a… | keep-internal |  | test code |
| 44 | …l profile = DatabricksWebProfile(fixtu… | keep-internal |  | test code |
| 79 | …l manager = DatabricksSignOutManager(a… | keep-internal |  | test code |
| 81 | …l profile = DatabricksWebProfile(fixtu… | keep-internal |  | test code |
| 112 | …l manager = DatabricksSignOutManager(a… | keep-internal |  | test code |
| 114 | …l profile = DatabricksWebProfile(fixtu… | keep-internal |  | test code |
| 137 | …erences("ai.omnigent.android.workspace… | keep-internal |  | test code |
| 141 | …l manager = DatabricksSignOutManager(a… | keep-internal |  | test code |
| 147 | DatabricksWebProfile(fixture.context.p… | keep-internal |  | test code |
| 160 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 162 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 164 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 166 | DatabricksWebContext( | keep-internal |  | test code |
| 168 | DatabricksCredentialScope.from(uri, co… | keep-internal |  | test code |
| 173 | DatabricksOAuthTokens( | keep-internal |  | test code |
| 177 | DatabricksOAuthIssuer(URI("https://dbc… | keep-internal |  | test code |
| 180 | …ext, store, DatabricksTokenManager(sto… | keep-internal |  | test code |
| 184 | val context: DatabricksWebContext, | keep-internal |  | test code |
| 186 | val tokens: DatabricksTokenManager, | keep-internal |  | test code |
| 190 | var value: DatabricksOAuthTokens?, | keep-internal |  | test code |
| 191 | ) : DatabricksCredentialStorage { | keep-internal |  | test code |
| 192 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 195 | scope: DatabricksCredentialScope, | keep-internal |  | test code |
| 196 | tokens: DatabricksOAuthTokens, | keep-internal |  | test code |
| 201 | …lete(scope: DatabricksCredentialScope)… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/LocalHttpServer.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/MainActivityTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 167 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 272 | …contains("__omnigentNativeEmitServerPi… | keep-internal |  | test code |
| 286 | "window.__omnigentNativeEmitSignOutRes… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/ManagedConfigTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 42 | …Of("https://omnigent.example.com"), | keep-internal |  | test code |
| 43 | …Of("https://omnigent.example.com").ser… | keep-internal |  | test code |
| 59 | …Of("https://omnigent.example.com"), | keep-internal |  | test code |
| 60 | configOf("omnigent.example.com/").serv… | keep-internal |  | test code |
| 75 | …Of("https://omnigent.example.com"), | keep-internal |  | test code |
| 76 | …Of("https://omnigent.example.com,https… | keep-internal |  | test code |
| 89 | …Of("https://omnigent.example.com") | keep-internal |  | test code |
| 91 | …es("https://omnigent.example.com:443")… | keep-internal |  | test code |
| 92 | …es("https://OMNIGENT.example.com")) | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/NativeNotificationManagerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OAuthCallbackActivityTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 40 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OAuthCallbackHandoffTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OAuthCallbackIntentFilterTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 24 | …ceivers("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 28 | …ceivers("ai.omnigent.android://mobile-… | keep-internal |  | test code |
| 30 | …ceivers("ai.omnigent.android:/somewher… | keep-internal |  | test code |
| 31 | …ceivers("ai.omnigent.android://oauth/c… | keep-internal |  | test code |
| 38 | …verText("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 41 | "Completing Databricks sign-in…", | keep-internal |  | test code |
| 42 | …verText("ai.omnigent.android://mobile-… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OAuthTransportTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 116 | ….well-known/omnigent.json")), | keep-internal |  | test code |
| 121 | ….well-known/omnigent.json")), | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcCredentialStoreTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcCredentialsTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 23 | …mni.example/omnigent/" | keep-internal |  | test code |
| 49 | …mni.example/omnigent/auth/login", | keep-internal |  | test code |
| 54 | …uri" to "ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 83 | …mni.example/omnigent/auth/native-token… | keep-internal |  | test code |
| 88 | …uri" to "ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 167 | …mni.example/omnigent/oauth/revoke"), r… | keep-internal |  | test code |
| 175 | "ai.omnigent.ios:/oauth/callback?state… | keep-internal |  | test code |
| 176 | "ai.omnigent.android://oauth/callback?… | keep-internal |  | test code |
| 177 | "ai.omnigent.android://mobile-redirect… | keep-internal |  | test code |
| 178 | "ai.omnigent.android:/oauth/other?stat… | keep-internal |  | test code |
| 179 | "ai.omnigent.android:/oauth/callback?c… | keep-internal |  | test code |
| 180 | "ai.omnigent.android:/oauth/callback?s… | keep-internal |  | test code |
| 181 | "ai.omnigent.android:/oauth/callback?s… | keep-internal |  | test code |
| 182 | "ai.omnigent.android:/oauth/callback?s… | keep-internal |  | test code |
| 331 | …mni.example/omnigent/oauth/token"), re… | keep-internal |  | test code |
| 463 | …mni.example/omnigent/v1/me"), check.ur… | keep-internal |  | test code |
| 493 | listOf("/omnigent/oauth/token", "/omni… | keep-internal |  | test code |
| 516 | "/omnigent/oauth/revoke", | keep-internal |  | test code |
| 632 | …hes(URI("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 633 | …hes(URI("AI.OMNIGENT.ANDROID:/oauth/ca… | keep-internal |  | test code |
| 635 | "ai.omnigent.android://oauth/callback"… | keep-internal |  | test code |
| 636 | "ai.omnigent.android://user@host/oauth… | keep-internal |  | test code |
| 637 | "ai.omnigent.android:/oauth/callback/"… | keep-internal |  | test code |
| 638 | "ai.omnigent.android:/OAuth/Callback", | keep-internal |  | test code |
| 639 | "ai.omnigent.ios:/oauth/callback", | keep-internal |  | test code |
| 655 | …) = URI("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcLoginManagerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 190 | …getFirst("X-Omnigent-Code-Verifier").o… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcPendingSignInStoreTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 20 | …mni.example/omnigent", "ap_session", "… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcSessionControllerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 65 | …istOf("GET /omnigent/v1/me"), server.r… | keep-internal |  | test code |
| 89 | …istOf("GET /omnigent/v1/me", "POST /om… | keep-internal |  | test code |
| 267 | …her.example/omnigent/auth/login")) | keep-internal |  | test code |
| 303 | URI("ai.omnigent.android:/oauth/callba… | keep-internal |  | test code |
| 473 | …uals("POST /omnigent/oauth/revoke", se… | keep-internal |  | test code |
| 558 | …ack(URI("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 579 | URI("ai.omnigent.android:/oauth/callba… | keep-internal |  | test code |
| 761 | …) = URI("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 845 | …mni.example/omnigent" | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcSignInLauncherTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 60 | "ai.omnigent.android", | keep-internal |  | test code |
| 78 | …nIn(URI("ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OidcWebSessionTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 15 | …mni.example/omnigent/" | keep-internal |  | test code |
| 18 | …mni.example/omnigent/auth/login?return… | keep-internal |  | test code |
| 22 | …mni.example/omnigent/auth/logout", mou… | keep-internal |  | test code |
| 30 | …mni.example/omnigent/auth/login/", | keep-internal |  | test code |
| 31 | …mni.example/omnigent/auth/loginx", | keep-internal |  | test code |
| 32 | …mni.example/omnigent/auth/callback", | keep-internal |  | test code |
| 33 | …xample:8443/omnigent/auth/login", | keep-internal |  | test code |
| 34 | …mni.example/omnigent/auth/login", | keep-internal |  | test code |
| 35 | …idp.example/omnigent/auth/login", | keep-internal |  | test code |
| 45 | "https://omni.example/omnigent", | keep-internal |  | test code |
| 46 | "https://omni.example/omnigent/", | keep-internal |  | test code |
| 51 | …mni.example/omnigent/c/1?x=1", | keep-internal |  | test code |
| 52 | "https://omni.example/omnigent", | keep-internal |  | test code |
| 58 | "https://omni.example/omnigentx", | keep-internal |  | test code |
| 59 | "https://omni.example/omnigent", | keep-internal |  | test code |
| 79 | "https://omni.example/omnigent", | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OmnigentBridgeListenerTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 26 | class OmnigentBridgeListenerTest { | keep-internal |  | test code |
| 28 | …r listener: OmnigentBridgeListener | keep-internal |  | test code |
| 38 | OmnigentBridgeListener( | keep-internal |  | test code |
| 142 | ) = OmnigentBridgeListener( | keep-internal |  | test code |
| 168 | OmnigentBridgeListener( | keep-internal |  | test code |
| 186 | OmnigentBridgeListener( | keep-internal |  | test code |
| 196 | …contains("__omnigentNativeEmitSignOutR… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OmnigentWebViewClientRenderProcessGoneTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 22 | class OmnigentWebViewClientRenderProce… | keep-internal |  | test code |
| 51 | OmnigentWebViewClient( | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OmnigentWebViewClientTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 22 | class OmnigentWebViewClientTest { | keep-internal |  | test code |
| 121 | …NNED_ORIGIN/omnigent/c/abc") | keep-internal |  | test code |
| 143 | …nedOrigin = DATABRICKS_APP_ORIGIN, onL… | keep-internal |  | test code |
| 166 | …rentUrl = "$DATABRICKS_APP_ORIGIN/app" | keep-internal |  | test code |
| 168 | …nedOrigin = DATABRICKS_APP_ORIGIN, onL… | keep-internal |  | test code |
| 185 | …nedOrigin = DATABRICKS_APP_ORIGIN, onL… | keep-internal |  | test code |
| 192 | …st("https://databricks.okta.com/login/… | keep-internal |  | test code |
| 203 | …nedOrigin = DATABRICKS_APP_ORIGIN, onL… | keep-internal |  | test code |
| 226 | …rentUrl = "$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 232 | pinnedOrigin = DATABRICKS_ORIGIN, | keep-internal |  | test code |
| 238 | …, request("$DATABRICKS_ORIGIN/login")) | keep-internal |  | test code |
| 243 | request("$DATABRICKS_ORIGIN/login", ha… | keep-internal |  | test code |
| 264 | pinnedOrigin = DATABRICKS_ORIGIN, | keep-internal |  | test code |
| 272 | request("$DATABRICKS_ORIGIN/omnigent?q… | keep-internal |  | test code |
| 288 | pinnedOrigin = DATABRICKS_ORIGIN, | keep-internal |  | test code |
| 294 | …alias.cloud.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 313 | pinnedOrigin = DATABRICKS_ORIGIN, | keep-internal |  | test code |
| 322 | request("$DATABRICKS_ORIGIN/auth/logou… | keep-internal |  | test code |
| 337 | pinnedOrigin = DATABRICKS_ORIGIN, | keep-internal |  | test code |
| 346 | request("$DATABRICKS_ORIGIN/omnigent")… | keep-internal |  | test code |
| 359 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 363 | …(webView, "$DATABRICKS_ORIGIN/", null) | keep-internal |  | test code |
| 367 | …ertEquals("$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 373 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 377 | …(webView, "$DATABRICKS_ORIGIN/?o=123",… | keep-internal |  | test code |
| 380 | …ertEquals("$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 386 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 388 | …(webView, "$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 399 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 401 | …(webView, "$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 409 | …nces to the omnigent mountˋ() { | keep-internal |  | test code |
| 411 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 414 | …, request("$DATABRICKS_ORIGIN/?o=123")… | keep-internal |  | test code |
| 418 | …ertEquals("$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 424 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 426 | …, request("$DATABRICKS_ORIGIN/")) | keep-internal |  | test code |
| 430 | // /omnigent answered with a redirect … | keep-internal |  | test code |
| 432 | …, request("$DATABRICKS_ORIGIN/")) | keep-internal |  | test code |
| 442 | …nedOrigin = DATABRICKS_ORIGIN) | keep-internal |  | test code |
| 444 | …(webView, "$DATABRICKS_ORIGIN/", false… | keep-internal |  | test code |
| 446 | …(webView, "$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 450 | …(webView, "$DATABRICKS_ORIGIN/", false… | keep-internal |  | test code |
| 453 | …ertEquals("$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 457 | …ges and non-databricks roots load unto… | keep-internal |  | test code |
| 459 | val databricks = client(pinnedOrigin =… | keep-internal |  | test code |
| 462 | databricks.shouldOverrideUrlLoading( | keep-internal |  | test code |
| 464 | request("$DATABRICKS_ORIGIN/omnigent/c… | keep-internal |  | test code |
| 538 | …sion: () -> DatabricksWebSession? = { … | keep-internal |  | test code |
| 543 | ) = OmnigentWebViewClient( | keep-internal |  | test code |
| 558 | …eSession(): DatabricksWebSession { | keep-internal |  | test code |
| 560 | DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 562 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 564 | return DatabricksWebSession( | keep-internal |  | test code |
| 565 | …a.net.URI("$DATABRICKS_ORIGIN/omnigent… | keep-internal |  | test code |
| 567 | setOf(DATABRICKS_ORIGIN, "https://alia… | keep-internal |  | test code |
| 636 | const val DATABRICKS_ORIGIN = "https:/… | keep-internal |  | test code |
| 637 | const val DATABRICKS_APP_ORIGIN = "htt… | keep-internal |  | test code |
| 638 | … = "https://databricks.okta.com/author… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/OriginsWorkspaceUiUrlTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 9 | /** Bare Databricks workspace roots re… | keep-internal |  | test code |
| 15 | …-49dc.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 16 | databricksWorkspaceUiUrl("https://dbc-… | keep-internal |  | test code |
| 19 | …agent.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 20 | databricksWorkspaceUiUrl("https://gtm-… | keep-internal |  | test code |
| 23 | …db-123.azuredatabricks.net/omnigent", | keep-internal |  | test code |
| 24 | databricksWorkspaceUiUrl("https://adb-… | keep-internal |  | test code |
| 31 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 32 | databricksWorkspaceUiUrl("https://ws.c… | keep-internal |  | test code |
| 39 | …://ws.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 40 | databricksWorkspaceUiUrl("https://WS.C… | keep-internal |  | test code |
| 47 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 48 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 49 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 54 | // Databricks Apps serve their own app… | keep-internal |  | test code |
| 55 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 56 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 58 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 59 | assertNull(databricksWorkspaceUiUrl("h… | keep-internal |  | test code |
| 64 | assertNull(databricksWorkspaceUiUrl(nu… | keep-internal |  | test code |
| 65 | assertNull(databricksWorkspaceUiUrl("a… | keep-internal |  | test code |
| 66 | assertNull(databricksWorkspaceUiUrl("o… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/ServerAuthenticationTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 13 | …ˋclassifies Databricks workspace domai… | keep-internal |  | test code |
| 15 | …hentication.DATABRICKS_WORKSPACE, | keep-internal |  | test code |
| 16 | …on("https://databricks.com"), | keep-internal |  | test code |
| 19 | …hentication.DATABRICKS_WORKSPACE, | keep-internal |  | test code |
| 20 | …//foo.cloud.databricks.com"), | keep-internal |  | test code |
| 23 | …hentication.DATABRICKS_WORKSPACE, | keep-internal |  | test code |
| 24 | …db-123.azuredatabricks.net"), | keep-internal |  | test code |
| 27 | …hentication.DATABRICKS_WORKSPACE, | keep-internal |  | test code |
| 28 | …https://Foo.Databricks.COM"), | keep-internal |  | test code |
| 33 | …ˋclassifies Databricks Apps separately… | keep-internal |  | test code |
| 35 | ServerAuthentication.DATABRICKS_APP, | keep-internal |  | test code |
| 36 | …tps://myapp.databricksapps.com"), | keep-internal |  | test code |
| 39 | ServerAuthentication.DATABRICKS_APP, | keep-internal |  | test code |
| 40 | …on("https://DATABRICKSAPPS.COM"), | keep-internal |  | test code |
| 47 | "https://databricks.com.example.org", | keep-internal |  | test code |
| 48 | "https://notdatabricks.com", | keep-internal |  | test code |
| 49 | …ttps://azuredatabricks.net.evil.tld", | keep-internal |  | test code |
| 50 | "https://databricksapps.com.evil.tld", | keep-internal |  | test code |
| 60 | fun ˋonly Databricks Apps retain inlin… | keep-internal |  | test code |
| 61 | …hentication.DATABRICKS_WORKSPACE.usesI… | keep-internal |  | test code |
| 62 | …hentication.DATABRICKS_APP.usesInWebVi… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/ServerEndpointTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 17 | URI("https://h/omnigent/v1/me"), | keep-internal |  | test code |
| 18 | …("https://h/omnigent/", "/v1/me"), | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/ServerManifestTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 21 | …uris": ["ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 26 | …ver.origin}/omnigent/?o=1#chat") | keep-internal |  | test code |
| 34 | listOf("ai.omnigent.android:/oauth/cal… | keep-internal |  | test code |
| 40 | ….well-known/omnigent.json"), server.re… | keep-internal |  | test code |
| 119 | ….well-known/omnigent.json"), server.re… | keep-internal |  | test code |
| 146 | …irect = "ai.omnigent.android:/oauth/ca… | keep-internal |  | test code |
| 163 | listOf("ai.omnigent.ios:/oauth/callbac… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/ServerStoreTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 93 | fun ˋa databricks workspace connects t… | keep-internal |  | test code |
| 96 | …-49dc.cloud.databricks.com") | keep-internal |  | test code |
| 99 | …-49dc.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 104 | …-49dc.cloud.databricks.com"), | keep-internal |  | test code |
| 110 | fun ˋa databricks url with a path is u… | keep-internal |  | test code |
| 113 | …://ws.cloud.databricks.com/omnigent") | keep-internal |  | test code |
| 115 | …://ws.cloud.databricks.com/omnigent", … | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/ThemeTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 27 | …style.Theme_Omnigent) | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/UserConnectRequestsTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/WorkspaceChromeScriptTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 9 | …must key on Omnigent's own embed root,… | keep-internal |  | test code |
| 16 | .omnigent-app { | keep-internal |  | test code |
| 35 | …"style[data-omnigent-workspace-chrome]… | keep-internal |  | test code |

### `web/android/app/src/test/java/ai/omnigent/android/WorkspaceSessionProbeTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | test code |
| 8 | …c-123.cloud.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 18 | …c-123.cloud.databricks.com/omnigent/v1… | keep-internal |  | test code |
| 43 | …tml?next=%2Fomnigent")), | keep-internal |  | test code |
| 55 | …to listOf("/omnigent/elsewhere"))) | keep-internal |  | test code |
| 74 | …obe { throw DatabricksSessionException… | keep-internal |  | test code |

### `web/android/app/src/testDebug/java/ai/omnigent/android/DatabricksAuthDebugMenuTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 19 | class DatabricksAuthDebugMenuTest { | keep-internal |  | code identifier |
| 22 | DatabricksOAuthConfiguration( | keep-internal |  | code identifier |
| 23 | "omnigent", | keep-internal |  | Test fixture OAuth clientId value passed to Data |
| 24 | URI("https://login.databricks.com/mobile-redirect"), | keep-origin |  | Databricks OAuth mobile-redirect URL in a test fixture; names the third-party Databricks integration, not Coral's publisher. |
| 26 | …c-123.cloud.databricks.com/omnigent?o=… | keep-internal |  | Test fixture Databricks workspace page URL with |
| 28 | DatabricksWebContext( | keep-internal |  | code identifier |
| 30 | DatabricksCredentialScope.from(pageUri… | keep-internal |  | code identifier |
| 33 | private val issuer = DatabricksOAuthIssuer(URI("https://dbc-123.cloud.databricks.com/oidc")) | keep-origin |  | Databricks workspace OIDC issuer URL in a test fixture; Databricks OAuth integration target. |
| 39 | DatabricksAuthDebugMenu.addItems(popup… | keep-internal |  | code identifier |
| 41 | …nu.findItem(DatabricksAuthDebugMenu.CL… | keep-internal |  | code identifier |
| 42 | …nu.findItem(DatabricksAuthDebugMenu.EX… | keep-internal |  | code identifier |
| 43 | …nu.findItem(DatabricksAuthDebugMenu.RE… | keep-internal |  | code identifier |
| 44 | …nu.findItem(DatabricksAuthDebugMenu.CL… | keep-internal |  | code identifier |
| 54 | …l profile = DatabricksWebProfile(conte… | keep-internal |  | code identifier |
| 56 | DatabricksAuthDebugMenu.run( | keep-internal |  | code identifier |
| 57 | DatabricksAuthDebugMenu.CLEAR_SESSION_… | keep-internal |  | code identifier |
| 74 | …l profile = DatabricksWebProfile(conte… | keep-internal |  | code identifier |
| 76 | DatabricksAuthDebugMenu | keep-internal |  | code identifier |
| 78 | DatabricksAuthDebugMenu.EXPIRE_ACCESS_… | keep-internal |  | code identifier |
| 88 | DatabricksAuthDebugMenu | keep-internal |  | code identifier |
| 90 | DatabricksAuthDebugMenu.REJECT_ACCESS_… | keep-internal |  | code identifier |
| 100 | DatabricksAuthDebugMenu | keep-internal |  | code identifier |
| 102 | DatabricksAuthDebugMenu.CLEAR_REFRESH_… | keep-internal |  | code identifier |
| 111 | …oryStore) = DatabricksTokenManager(sto… | keep-internal |  | code identifier |
| 113 | … tokens() = DatabricksOAuthTokens("acc… | keep-internal |  | code identifier |
| 115 | … session(): DatabricksWebSession { | keep-internal |  | code identifier |
| 116 | val source = URI("https://dbc-123.cloud.databricks.com/auth/session/create") | keep-origin |  | Databricks workspace session-create URL in a test fixture; Databricks sign-in integration target. |
| 117 | return DatabricksWebSession( | keep-internal |  | code identifier |
| 152 | var value: DatabricksOAuthTokens?, | keep-internal |  | code identifier |
| 153 | ) : DatabricksCredentialStorage { | keep-internal |  | code identifier |
| 154 | …load(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 157 | scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 158 | tokens: DatabricksOAuthTokens, | keep-internal |  | code identifier |
| 163 | …lete(scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |

### `web/android/app/src/testDebug/java/ai/omnigent/android/OidcAuthDebugMenuTest.kt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | package ai.omnigent.android | keep-internal |  | code identifier |
| 27 | …enu.handles(DatabricksAuthDebugMenu.CL… | keep-internal |  | code identifier |

### `web/android/docs/databricks-oauth.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | # Databricks OAuth on Android | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 3 | The Android app uses a public-client Databricks OAuth flow for workspace-hosted | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 4 | Omnigent. It authenticates, creates the platform web session, and installs that | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 7 | Databricks Apps are a different server type and retain inline platform SSO. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 8 | Other Omnigent servers follow [OIDC sign-in](../README.md#oidc-sign-in), which | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 9 | reuses Auth Tab and the callback receiver but never reads Databricks credentials. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 17 | \| ˋdatabricksOAuthClientIdˋ    \| ˋomnigentˋ                              \| Registered Databricks pub… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 18 | \| ˋdatabricksOAuthRedirectUrlˋ \| ˋai.omnigent.android://mobile-redirectˋ \| Exact callback registered… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 25 | -PdatabricksOAuthClientId=your-public-client-id \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 26 | -PdatabricksOAuthRedirectUrl=ai.omnigent.android://mobile-redirect | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 29 | The values are public configuration, not secrets. The default ˋomnigentˋ is the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 32 | borrow a Databricks CLI client ID. An empty client ID is accepted by Gradle, but | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 35 | The default private callback must be registered on the Databricks OAuth client | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 36 | as ˋai.omnigent.android://mobile-redirectˋ (including both slashes). No Android | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 50 | Register ˋai.omnigent.android://mobile-redirectˋ as an exact redirect URI for | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 51 | the public client used by the build (default ˋomnigentˋ). Then install this | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 101 | ˋ{"scheme":"ai.omnigent.android","nonce":"<random>"}ˋ; form encoding converts | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 122 | Databricks workspace ˋ/oidcˋ authority or an account | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 143 | Databricks Apps, unrelated domains, duplicate ˋoˋ values, non-decimal IDs, and | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 176 | Databricks workspace domains without changing an explicit workspace ID. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 183 | The intended Omnigent path, query, fragment, and workspace hint survive the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 221 | native recovery menu and ˋwindow.omnigentNative.signOut()ˋ to the trusted main | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/android/keystore.properties.example`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | #   OMNIGENT_KEYSTORE_FILE, OMNIGENT_K… | keep-internal |  | code comment |
| 6 | #   OMNIGENT_KEY_ALIAS, OMNIGENT_KEY_P… | keep-internal |  | code comment |
| 12 | …ute/path/to/omnigent-upload.jks | keep-internal |  | code identifier |
| 14 | keyAlias=omnigent-upload | keep-internal |  | code identifier |

### `web/android/settings.gradle.kts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | rootProject.name = "Omnigent" | keep-internal |  | Gradle rootProject name is an internal Android p |

### `web/electron/README.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | # Omnigent Desktop (Electron) | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 4 | existing Omnigent web UI. It shows the **same** UI you get in a browser, but | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 29 | the shell plays it, the alert is audible **whether Omnigent is backgrounded or | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 38 | publish an HTTPS ˋserverUrlsˋ list in the ˋai.omnigent.desktopˋ preference | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 53 | **About Omnigent** opens a shell-owned modal showing the platform app and | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 105 | Connect). You enter your Omnigent server URL (default | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 129 | ## Databricks sign-in and embedded-auth rollback | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 131 | HTTPS Databricks workspace and account URLs use **system-browser OAuth** by | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 132 | default. Databricks Apps (ˋ*.databricksapps.comˋ), localhost, and other servers | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 156 | under a **Reconnecting to Databricks…** overlay and retries every 5s for a minute, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 163 | For the packaged macOS app, explicitly roll back to embedded Databricks sign-in: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 166 | # Quit Omnigent first, then set the preference and reopen it. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 167 | defaults write ai.omnigent.desktop DatabricksBrowserAuthEnabled -bool false | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 175 | To restore browser authentication, quit Omnigent and remove the override: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 178 | defaults delete ai.omnigent.desktop DatabricksBrowserAuthEnabled | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 183 | NSUserDefaults domain, not the packaged app's ˋai.omnigent.desktopˋ domain. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 194 | You can exercise the classic button states, cancel, and retry without Databricks | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 199 | … cancellation' web/electron/test/databricks-oauth.test.js | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 203 | OAuth-enabled Databricks test workspace. Complete system-browser sign-in and | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 204 | confirm the desktop opens Omnigent. Terminal output must include | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 205 | ˋdatabricks session: signed in to ...ˋ; merely reaching a login page is not success. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 218 | and does not revoke the grant at Databricks. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 224 | token actions require a connected Databricks workspace in browser-auth mode. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 232 | ### Databricks authentication diagnostics | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 239 | ˋ~/Library/Logs/Omnigent/ˋ (or ˋOmnigent Devˋ for development). This is an | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 245 | For development, ˋjust electron-devˋ still prints ˋ[omnigent] databricksˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 270 | to the Databricks platform owner to check the denial reason (client enablement, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 275 | Omnigent servers that sign in with OIDC (ˋOMNIGENT_AUTH_PROVIDER=oidcˋ) open | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 281 | ˋ/.well-known/omnigent.jsonˋ manifest. Only ˋauth.mode: "oidc"ˋ switches to | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 290 | \| Databricks workspaces, accounts, and Apps                  \| Unchanged: detected by URL, manifest … | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 317 | The refresh grant is stored per server in ˋ~/.omnigent/oidc_tokens.jsonˋ, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 330 | after sign-in the browser tab says "Return to Omnigent". The app comes to the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 347 | Omnigent, set its macOS user default, and reopen it: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 350 | defaults write ai.omnigent.desktop DeveloperMode -bool true | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 355 | again, quit Omnigent and remove the override: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 358 | defaults delete ai.omnigent.desktop DeveloperMode | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 367 | Electron shell at runtime (the preload exposes ˋwindow.omnigentDesktopˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 378 | src/preload.js           # contextBridge: window.omnigentDesktop + omnigentSetup | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 382 | src/find_preload.js      # contextBridge for the find bar: window.omnigentFind | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 385 | src/browserIpc.js           # omnigent:browser-* IPC handlers (extracted from main.js) | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 429 | (ˋomnigentSetupˋ) only works for the bundled setup page itself, so a | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 483 | participant S as Omnigent server | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 543 | On a Databricks-managed server with internal desktop features enabled, an | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 547 | the app's remote port. Omnigent does not establish or verify forwarding or | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 556 | a Databricks server. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 689 | - ˋsrc/browserIpc.jsˋ — the whole ˋipcMain.handle('omnigent:browser-*')ˋ surface, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 716 | ˋonBrowserElementPromptDismissˋ to ˋwindow.omnigentDesktopˋ, each a thin | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 847 | **JS trust boundary:** ˋomnigent:browser-perform-actionˋ accepts only snapshot, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 893 | The shell opens on the bundled setup page. Point it at a running Omnigent | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 918 | OMNIGENT_DESKTOP_VERSION_OVERRIDE=0.9.0 pnpm start | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 940 | Local packages use the ˋai.omnigent.desktop-devˋ app ID and the **Omnigent Dev** | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 942 | ˋOmnigent Dev-<version>-<arch>.dmgˋ). They keep their own app data and do not | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 944 | ˋai.omnigent.desktopˋ, **Omnigent**, and ˋelectron/dist/ˋ. For the full | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 949 | ˋdatabricksInternalFeaturesEnabledˋ is ˋtrueˋ, for both new and existing profiles. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 952 | platform, and ˋOMNIGENT_SERVER_SELECTOR_V2=1ˋ forces V2 regardless of the saved | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 956 | bundle, but reads local preferences from ˋai.omnigent.desktop-devˋ explicitly | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 957 | and stores settings in **Omnigent Dev** app data. To try a managed preference, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1031 | spctl -a -vv dist/mac-arm64/Omnigent.app   # → "accepted, source=Notarized Developer ID" | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1032 | codesign --verify --verbose=2 dist/Omnigent-*-arm64.dmg | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1033 | xcrun stapler validate -v dist/Omnigent-*-arm64.dmg | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1042 | Any reachable Omnigent server works. For a quick local target, run the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1047 | .venv/bin/python -m omnigent.server   # serves on http://localhost:8000 | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1055 | ˋomnigentˋ CLI to start a server and register this machine as a **host** (a | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1072 | The CLI ships under two names that resolve to the same entry point — ˋomnigentˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1074 | ˋsettings.omnigent_pathˋ first, then ˋPATHˋ (ˋomnigentˋ then ˋomniˋ), then the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1088 | curl -fsSL https://raw.githubusercontent.com/omnigent-ai/omnigent/main/scripts/install_oss.sh \| sh | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1096 | A configured path is saved to ˋsettings.jsonˋ (ˋomnigent_pathˋ) only once it | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1102 | **"Start a server on this machine"** runs ˋomnigent server --backgroundˋ (idempotent — | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1115 | dialog** ("Allow _host_ to manage Omnigent on this machine?") with **Don't Allow** | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1119 | ˋomnigent host --server <url>ˋ. **Allow Once** connects this time and re-prompts | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1126 | bridge — ˋwindow.omnigentDesktopˋ → ˋgetHostStatusˋ / ˋgetHostIdentityˋ / | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1155 | platform passkey served no supported sign-in path: Databricks Touch ID | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1200 | ˋ~/Library/Application Support/Omnigent/settings.jsonˋ.) | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1215 | An ˋomnigent://<hostname>/c/<session_id>ˋ URL opens that session on that | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1219 | omnigent://localhost:8000/c/conv_abc              → http://localhost:8000/c/conv_abc | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1220 | omnigent://my-workspace.cloud.databricks.com/c/x → https://…/omnigent/c/x | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1226 | pasted URL can never disagree. The Databricks workspace mount (ˋ/omnigentˋ) | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1229 | ˋ/ˋ; other paths are ignored. ˋomnigent start --open-in-desktopˋ emits these | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1269 | packaged installs, plus a runtime ˋapp.setAsDefaultProtocolClient("omnigent")ˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 1279 | - **Native bridge detection:** ˋwindow.omnigentDesktopˋ (ˋkind: "electron"ˋ), | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/electron/RELEASING.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …are built and published by the [ˋomnigent-desktopˋ workflow](https://github.com/databricks/secure-pu… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 7 | …n/package.jsonˋ on a PR against ˋomnigent-ai/omnigentˋ (unless the release also needs other changes)… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 14 | gh workflow run omnigent-desktop.yml \ | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 15 | --repo databricks/secure-public-registry-releases-eng --ref main \ | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 19 | …nder ˋwin/ˋ and ˋlinux/ˋ in the ˋomnigent-buildsˋ Vercel Blob store, and opens a PR updating ˋlatest… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 23 | Use a Mac with the **Databricks, Inc. (8RMX4WU6F8)** Developer ID Application certificate and Apple … | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 34 | …dˋ for a release.** Those make **Omnigent Dev** in ˋdist-dev/ˋ and do not notarize. The release comm… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 38 | spctl -a -vv "web/electron/dist/$arch/Omnigent.app" # Notarized Developer ID | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 40 | for dmg in web/electron/dist/Omnigent-"$VERSION"-*.dmg; do | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 84 | …RSIONˋ and names the production ˋOmnigent-...ˋ artifacts, **not** ˋOmnigent Dev-...ˋ. Re-check all f… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 88 | Use the ˋomnigent-buildsˋ store's ˋBLOB_READ_WRITE_TOKENˋ (for example, from an ignored root ˋ.envˋ)… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 94 | vercel blob list --prefix "mac/Omnigent-$VERSION" --limit 100 | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 96 | for file in web/electron/dist/Omnigent-"$VERSION"-*.zip \ | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 97 | web/electron/dist/Omnigent-"$VERSION"-*.dmg \ | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 98 | web/electron/dist/Omnigent-"$VERSION"-*.blockmap; do | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 101 | vercel blob list --prefix "mac/Omnigent-$VERSION" --limit 100 | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 108 | On the workflow-created ˋomnigent-siteˋ PR branch, copy the corrected ˋweb/electron/dist/latest-mac.… | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |

### `web/electron/about/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | <title>About Omnigent</title> | change | S87 | About window document title shows the product name. |
| 341 | <h1>Omnigent</h1> | change | S87 | About window h1 shows the product name. |
| 349 | <h2 id="desktop-heading">Omnigent Desktop app</h2> | change | S87 | Static default of the desktop-heading shown in About before index.js fills it. |
| 383 | <h2 id="cli-heading">Omnigent CLI</h2> | keep-deferred |  | Heading names the detected omnigent CLI (upstream package, out of scope); renamed with the CLI in OPS-03/FND-01. |

### `web/electron/about/index.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | const api = window.omnigentAbout; | keep-internal |  | code identifier |
| 23 | …lue.match(/^omnigent\s+(\S+)/i)?.[1] ?… | keep-internal |  | code identifier |
| 67 | message: "Omnigent Desktop is up to date.", | change | S87 | Update status message shown in the About window uses the product name. |
| 128 | desktopHeading.textContent = ˋOmnigent ${platformName} appˋ; | change | S87 | Runtime About heading text shows the product name. |

### `web/electron/browser-permission/index.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …ge = window.omnigentBrowserPermission; | keep-internal |  | code identifier |

### `web/electron/build/afterAllArtifactBuild.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 80 | …process.env.OMNIGENT_NOTARIZE_DMG !== … | keep-internal |  | code identifier |

### `web/electron/connection-loading/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | <title>Opening Omnigent</title> | change | S87 | Title of the shell-owned loading window shows the product name. |
| 55 | <span id="status">Opening Omnigent…</span> | change | S87 | Visible loading status text shows the product name. |

### `web/electron/dev-app-update.yml`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | url: https://omnigent.ai/_desktop/updates/ | change | S87 | Changed with its seam: code identifier |
| 3 | updaterCacheDirName: omnigent-desktop-electron-updater-dev | change | S87 | Changed with its seam: code identifier |

### `web/electron/dmg/background.tiff`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S87 | Starfish sandbox DMG background; build.dmg.background is now coral-background.tiff. Kept, unused. |

### `web/electron/docs/managed-preferences.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | Omnigent Desktop. People can then choose their organization’s server instead of | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 10 | ai.omnigent.desktop | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 18 | \| ˋdatabricksInternalFeaturesEnabledˋ \| Boolean          \| No       \| ˋfalseˋ \| Defaults macOS apps … | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 24 | https://my-workspace.cloud.databricks.com/ml/omnigents | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 30 | To give a server a display name, add an ˋomnigentServerNameˋ query parameter | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 31 | to its entry. Omnigent removes the parameter before connecting: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 34 | https://my-workspace.cloud.databricks.com/?o=123&omnigentServerName=Engineering | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 47 | - Omnigent does not connect automatically. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 57 | ## Databricks-internal features | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 59 | When ˋdatabricksInternalFeaturesEnabledˋ is ˋtrueˋ, macOS apps, including unpackaged | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 63 | keep the legacy default; ˋOMNIGENT_SERVER_SELECTOR_V2=1ˋ still | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 66 | When ˋdatabricksInternalFeaturesEnabledˋ is ˋtrueˋ **and** the window is | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 67 | connected to a Databricks-managed server (a workspace mount on | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 68 | ˋ*.databricks.comˋ / ˋ*.azuredatabricks.netˋ, or a Databricks App on | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 69 | ˋ*.databricksapps.comˋ, https only), the new-session host picker offers | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 75 | pane; the instance authenticates with its own Databricks credentials. A | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 89 | Remote hosts need their own renewable **Omnigent** OAuth grant. Desktop browser | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 98 | Use an Isaac release that supports Omnigent-app login and the | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 99 | ˋOMNIGENT_AUTH_REQUIREDˋ startup diagnostic before deploying this flow. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 100 | SPOG entries can include ˋ/omnigent?o=<workspace-id>ˋ to select the workspace; | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 109 | ˋai.omnigent.desktopˋ application preference domain. Most MDM products expose | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 123 | <key>ai.omnigent.desktop</key> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 132 | <string>https://omnigent.corp.example.com/?omnigentServerName=Engineering</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 133 | <string>https://my-workspace.cloud.databricks.com/ml/omnigents</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 135 | <key>databricksInternalFeaturesEnabled</key> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 143 | <string>Omnigent Desktop Managed Preferences</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 145 | <string>com.example.omnigent.preferences</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 155 | <string>Omnigent Desktop</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 157 | <string>com.example.omnigent</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 175 | Packaged release builds use ˋai.omnigent.desktopˋ; packaged local builds and | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 176 | ˋjust electron-devˋ use ˋai.omnigent.desktop-devˋ. The unpackaged Electron | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 182 | defaults write ai.omnigent.desktop serverUrls -array \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 183 | "https://omnigent.corp.example.com/?omnigentServerName=Engineering" \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 184 | "https://my-workspace.cloud.databricks.com/ml/omnigents" | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 185 | defaults write ai.omnigent.desktop databricksInternalFeaturesEnabled -bool true | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 191 | defaults delete ai.omnigent.desktop serverUrls | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 192 | defaults delete ai.omnigent.desktop databricksInternalFeaturesEnabled | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 195 | For development, substitute ˋai.omnigent.desktop-devˋ in the commands above. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 196 | A profile for ˋai.omnigent.desktopˋ doesn't apply to local builds, so they can | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 201 | just electron-mdm set "https://omnigent.corp.example.com/?omnigentServerName=Engineering" --internal | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/electron/e2e/README.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | …mock-LLM + ˋomnigent serverˋ pair the | keep-internal |  | test code |
| 28 | …mock LLM + ˋomnigent serverˋ, and laun… | keep-internal |  | test code |
| 66 | …isplay; set OMNIGENT_PW_NO_SANDBOX so … | keep-internal |  | test code |
| 69 | OMNIGENT_PW_NO_SANDBOX=1 xvfb-run -a n… | keep-internal |  | test code |
| 72 | …rverˋ runs ˋomnigent serverˋ via ˋpyth… | keep-internal |  | test code |
| 73 | …reter with ˋOMNIGENT_PYTHONˋ when your… | keep-internal |  | test code |
| 76 | OMNIGENT_PYTHON=/path/to/.venv/bin/pyt… | keep-internal |  | test code |
| 80 | …stead uses ˋOMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 109 | …pm --filter omnigent-desktop-electron … | keep-internal |  | test code |
| 110 | OMNIGENT_PYTHON="$PWD/.venv/bin/python… | keep-internal |  | test code |
| 115 | …ssertions. ˋOMNIGENT_DESKTOP_EXECUTABL… | keep-internal |  | test code |
| 116 | ˋOMNIGENT_DESKTOP_COMPOSITED_VIDEO=1ˋ … | keep-internal |  | test code |
| 117 | …sion). Set ˋOMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 142 | OMNIGENT_PYTHON=/path/to/venv/bin/pyth… | keep-internal |  | test code |
| 143 | OMNIGENT_PW_NO_SANDBOX=1 \ | keep-internal |  | test code |
| 144 | OMNIGENT_DESKTOP_RECORD_DIR=/absolute/… | keep-internal |  | test code |
| 166 | ˋOMNIGENT_PYTHON="$PWD/.venv/bin/pytho… | keep-internal |  | test code |
| 169 | ˋOMNIGENT_DESKTOP_RECORD_DIRˋ outside … | keep-internal |  | test code |
| 211 | OMNIGENT_DESKTOP_RECORD_DIR=/absolute/… | keep-internal |  | test code |
| 212 | OMNIGENT_PW_NO_SANDBOX=1 xvfb-run -a n… | keep-internal |  | test code |

### `web/electron/e2e/desktopDesignPromptHarness.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …process.env.OMNIGENT_PYTHON \|\| "python… | keep-internal |  | test code |
| 38 | !/^(OMNIGENT_\|RUNNER_\|OPENAI_\|ANTHROPI… | keep-internal |  | test code |
| 43 | OMNIGENT_CONFIG_HOME: configDir, | keep-internal |  | test code |
| 44 | OMNIGENT_DATA_DIR: path.join(configDir… | keep-internal |  | test code |
| 116 | "from omnigent.cli import main; main()… | keep-internal |  | test code |
| 127 | …roviderEnv, OMNIGENT_WEB_UI_DIST: WEB_… | keep-internal |  | test code |
| 129 | …thˋ), "real Omnigent server", 60_000); | keep-internal |  | test code |
| 132 | …6").update(ˋomnigent-runner:${bindingT… | keep-internal |  | test code |
| 133 | …r", ["-m", "omnigent.runner._entry"], … | keep-internal |  | test code |
| 136 | OMNIGENT_RUNNER_ID: runnerId, | keep-internal |  | test code |
| 137 | OMNIGENT_RUNNER_TUNNEL_BINDING_TOKEN: … | keep-internal |  | test code |
| 138 | OMNIGENT_RUNNER_PARENT_PID: String(pro… | keep-internal |  | test code |
| 139 | OMNIGENT_RUNNER_WORKSPACE: tmpDir, | keep-internal |  | test code |
| 140 | OMNIGENT_RUNNER_HOST_OWNS_GLOBAL_CLEAN… | keep-internal |  | test code |
| 223 | …process.env.OMNIGENT_DESKTOP_FORM_URL)… | keep-internal |  | test code |
| 224 | …process.env.OMNIGENT_DESKTOP_FORM_URL,… | keep-internal |  | test code |
| 257 | …process.env.OMNIGENT_DESKTOP_EXECUTABL… | keep-internal |  | test code |
| 259 | …process.env.OMNIGENT_PW_NO_SANDBOX) ar… | keep-internal |  | test code |
| 266 | OMNIGENT_DESKTOP_VERSION_OVERRIDE: "99… | keep-internal |  | test code |
| 284 | …process.env.OMNIGENT_DESKTOP_COMPOSITE… | keep-internal |  | test code |
| 288 | process.env.OMNIGENT_DESKTOP_CAPTURE_W… | keep-internal |  | test code |
| 294 | …ureTitle = ˋOmnigent design prompt reg… | keep-internal |  | test code |

### `web/electron/e2e/desktopHarness.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …ess for the Omnigent desktop shell (El… | keep-internal |  | test code |
| 12 | …mock-LLM + ˋomnigent serverˋ pair the | keep-internal |  | test code |
| 38 | …REPO_ROOT, "omnigent", "server", "stat… | keep-internal |  | test code |
| 49 | …process.env.OMNIGENT_PYTHON \|\| "python… | keep-internal |  | test code |
| 145 | …ver and an ˋomnigent serverˋ wired to … | keep-internal |  | test code |
| 212 | …startsWith("OMNIGENT_RUNNER_") && !key… | keep-internal |  | test code |
| 219 | "from omnigent.cli import main; main()… | keep-internal |  | test code |
| 239 | OMNIGENT_WEB_UI_DIST: WEB_UI_DIST, | keep-internal |  | test code |
| 271 | …}/healthˋ, "omnigent server", serverLo… | keep-internal |  | test code |
| 385 | for (const profile of [userDataDir, path.join(userDataDir, "Omnigent Dev")]) { | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 403 | ˋglobal.omnigentTestBrowserRegistries … | keep-internal |  | test code |
| 404 | …gs); global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 413 | …process.env.OMNIGENT_PW_NO_SANDBOX) { | keep-internal |  | test code |
| 436 | …rocess.env, OMNIGENT_DESKTOP_VERSION_O… | keep-internal |  | test code |
| 536 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 557 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |

### `web/electron/e2e/desktop_arca_onboarding.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 58 | …istered.\n__OMNIGENT_ARCA_IDENTITY_STA… | keep-internal |  | test code |
| 74 | ….write("\n__OMNIGENT_ARCA_IDENTITY_END… | keep-internal |  | test code |
| 98 | …derr.write(ˋOmnigent OAuth URL: https:… | keep-internal |  | test code |
| 123 | managed.getDatabricksInternalFeaturesE… | keep-internal |  | test code |
| 126 | …, "url")).isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 128 | ….join(src, "omnigent_cli")); | keep-internal |  | test code |
| 194 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 195 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 205 | ….well-known/omnigent.json") { | keep-internal |  | test code |
| 254 | OMNIGENT_SERVER_SELECTOR_V2: "1", | keep-internal |  | test code |
| 255 | OMNIGENT_SERVER_SELECTOR_V2_DEV_URL: "… | keep-internal |  | test code |
| 256 | OMNIGENT_ONBOARDING_MOCK: "", | keep-internal |  | test code |
| 257 | OMNIGENT_ARCA_AUTO_CONNECT: "", | keep-internal |  | test code |
| 258 | OMNIGENT_CONFIG_HOME: path.join(stateD… | keep-internal |  | test code |
| 259 | OMNIGENT_DATA_DIR: path.join(stateDir,… | keep-internal |  | test code |
| 267 | window.omnigentSetup.onRunnerConnectLo… | keep-internal |  | test code |
| 332 | await page.getByRole("button", { name: "Open Omnigent", exact: true }).click(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 400 | await page.getByRole("button", { name: "Open Omnigent", exact: true }).click(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/electron/e2e/desktop_cookie_isolation.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | //   OMNIGENT_PW_NO_SANDBOX=1 xvfb-run… | keep-internal |  | test code |
| 34 | …here window.omnigentDesktop exists. | keep-internal |  | test code |
| 41 | …) => window.omnigentDesktop.browserSet… | keep-internal |  | test code |
| 111 | process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 134 | …=> !!window.omnigentDesktop?.browserPe… | keep-internal |  | test code |
| 158 | window.omnigentDesktop.browserPerformA… | keep-internal |  | test code |
| 166 | …) => window.omnigentDesktop.browserExe… | keep-internal |  | test code |
| 222 | !!window.omnigentDesktop && | keep-internal |  | test code |
| 223 | …peof window.omnigentDesktop.browserOpe… | keep-internal |  | test code |
| 246 | window.omnigentDesktop.browserOpenOrNa… | keep-internal |  | test code |
| 272 | …) => window.omnigentDesktop.browserClo… | keep-internal |  | test code |

### `web/electron/e2e/desktop_dbcert_preflight.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 33 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 49 | …process.env.OMNIGENT_DBCERT_TEST_DIR; | keep-internal |  | test code |
| 82 | …ences")).getDatabricksInternalFeatures… | keep-internal |  | test code |
| 84 | urls.isDatabricksManagedServerUrl = ur… | keep-internal |  | test code |
| 102 | …startsWith("OMNIGENT_RUNNER_") && !key… | keep-internal |  | test code |
| 108 | process.env.OMNIGENT_PYTHON \|\| "python… | keep-internal |  | test code |
| 115 | OMNIGENT_CONFIG_HOME: path.join(root, … | keep-internal |  | test code |
| 116 | OMNIGENT_CONFIG: "", | keep-internal |  | test code |
| 117 | OMNIGENT_BUILTIN_AGENT_DIRS: agent, | keep-internal |  | test code |
| 118 | OMNIGENT_DATA_DIR: path.join(root, "da… | keep-internal |  | test code |
| 119 | OMNIGENT_SKIP_ONBOARD: "1", | keep-internal |  | test code |
| 120 | OMNIGENT_LOCAL_SINGLE_USER: "1", | keep-internal |  | test code |
| 121 | OMNIGENT_WEB_UI_DIST: WEB_UI_DIST, | keep-internal |  | test code |
| 153 | …env.PATH}ˋ, OMNIGENT_DBCERT_TEST_DIR: … | keep-internal |  | test code |
| 210 | …ler-name", "omnigent", "--update-kubec… | keep-internal |  | test code |
| 220 | …) => window.omnigentDesktop.checkDbcer… | keep-internal |  | test code |
| 248 | …) => window.omnigentDesktop.checkDbcer… | keep-internal |  | test code |

### `web/electron/e2e/desktop_design_prompt.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | // OMNIGENT_PYTHON selects the backend… | keep-internal |  | test code |
| 131 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 169 | …process.env.OMNIGENT_DESKTOP_COMPOSITE… | keep-internal |  | test code |
| 317 | …process.env.OMNIGENT_DESKTOP_COMPOSITE… | keep-internal |  | test code |

### `web/electron/e2e/desktop_html_preview_zoom.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | //   OMNIGENT_PW_NO_SANDBOX=1 xvfb-run… | keep-internal |  | test code |
| 3 | // OMNIGENT_PYTHON selects the backend… | keep-internal |  | test code |
| 16 | …process.env.OMNIGENT_PYTHON \|\| "python… | keep-internal |  | test code |
| 18 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 60 | ….tmpdir(), "omnigent-preview-zoom-")); | keep-internal |  | test code |

### `web/electron/e2e/desktop_navigation_policy.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 77 | …hineHome, ".omnigent"); | keep-internal |  | test code |
| 97 | …achineHome, OMNIGENT_CONFIG_HOME: stat… | keep-internal |  | test code |
| 158 | process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 254 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 355 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 431 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 480 | global.omnigentTestBrowserRegistries[0… | keep-internal |  | test code |
| 521 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 609 | process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 657 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 670 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 680 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 768 | …turn global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 809 | process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 857 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 878 | global.omnigentTestBrowserRegistries[0… | keep-internal |  | test code |
| 887 | …ry = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |
| 920 | global.omnigentTestBrowserRegistries[0… | keep-internal |  | test code |
| 1003 | global.omnigentTestBrowserRegistries[0… | keep-internal |  | test code |
| 1039 | … } = global.omnigentTestBrowserRegistr… | keep-internal |  | test code |

### `web/electron/e2e/desktop_oidc_browser_sign_in.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 78 | …h grant (~/.omnigent) out of the real … | keep-internal |  | test code |
| 111 | …oin(home, ".omnigent", "oidc_tokens.js… | keep-internal |  | test code |
| 151 | …oin(home, ".omnigent", "oidc_tokens.js… | keep-internal |  | test code |

### `web/electron/e2e/desktop_recording_shows_views.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | //   OMNIGENT_PW_NO_SANDBOX=1 xvfb-run… | keep-internal |  | test code |
| 106 | …) => window.omnigentDesktop.browserSet… | keep-internal |  | test code |
| 170 | !!window.omnigentDesktop && | keep-internal |  | test code |
| 171 | …peof window.omnigentDesktop.browserOpe… | keep-internal |  | test code |

### `web/electron/e2e/desktop_saved_server_unresponsive.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 50 | process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 98 | ˋstill on "Opening Omnigent…" ${LEAVE_LOADING_WITHIN_MS / 1000}s after launch: ${JSON.stringify(stat… | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/electron/e2e/desktop_session_expiry_browser_view.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …ly what the Databricks gate does after… | keep-internal |  | test code |
| 13 | //   OMNIGENT_PW_NO_SANDBOX=1 xvfb-run… | keep-internal |  | test code |
| 64 | …ront of the omnigent server, mirroring… | keep-internal |  | test code |
| 70 | …rl The real omnigent server, e.g. "htt… | keep-internal |  | test code |
| 180 | …here window.omnigentDesktop exists. | keep-internal |  | test code |
| 186 | …) => window.omnigentDesktop.browserSet… | keep-internal |  | test code |
| 241 | process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |
| 276 | !!window.omnigentDesktop && | keep-internal |  | test code |
| 277 | …peof window.omnigentDesktop.browserOpe… | keep-internal |  | test code |

### `web/electron/e2e/desktop_titlebar_zoom.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 19 | ….tmpdir(), "omnigent-titlebar-zoom-"))… | keep-internal |  | test code |
| 26 | …process.env.OMNIGENT_DESKTOP_RECORD_DI… | keep-internal |  | test code |

### `web/electron/e2e/desktop_update_window.e2e.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | // (titled "Omnigent Update"), so wind… | keep-internal |  | test code |
| 14 | //   OMNIGENT_PW_NO_SANDBOX=1 xvfb-run… | keep-internal |  | test code |
| 45 | ˋ  - url: Omnigent-${FEED_VERSION}-x86… | keep-internal |  | test code |
| 48 | ˋpath: Omnigent-${FEED_VERSION}-x86_64… | keep-internal |  | test code |
| 167 | …d renders ("Omnigent Desktop … is avai… | keep-internal |  | test code |
| 177 | …OS window ("Omnigent Update"), so Miss… | keep-internal |  | test code |

### `web/electron/e2e/fixtures/fakeOidcIdp.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 107 | … OIDC-mode ˋomnigent serverˋ signing i… | keep-internal |  | test code |
| 110 | OMNIGENT_AUTH_PROVIDER: "oidc", | keep-internal |  | test code |
| 111 | OMNIGENT_OIDC_ISSUER: idp.issuer, | keep-internal |  | test code |
| 112 | OMNIGENT_OIDC_CLIENT_ID: idp.clientId, | keep-internal |  | test code |
| 113 | OMNIGENT_OIDC_CLIENT_SECRET: idp.clien… | keep-internal |  | test code |
| 115 | OMNIGENT_OIDC_TOKEN_ENDPOINT_AUTH_METH… | keep-internal |  | test code |
| 116 | OMNIGENT_OIDC_REDIRECT_URI: ˋ${serverU… | keep-internal |  | test code |
| 117 | OMNIGENT_OIDC_COOKIE_SECRET: "ab".repe… | keep-internal |  | test code |
| 118 | OMNIGENT_OIDC_AUTHORIZATION_ENDPOINT: … | keep-internal |  | test code |
| 119 | OMNIGENT_OIDC_TOKEN_ENDPOINT: ˋ${idp.i… | keep-internal |  | test code |
| 120 | OMNIGENT_OIDC_JWKS_URI: ˋ${idp.issuer}… | keep-internal |  | test code |

### `web/electron/find/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 82 | const find = window.omnigentFind; | keep-internal |  | window.omnigentFind preload bridge name; interna |

### `web/electron/icons/Assets.car`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Compiled macOS 26 dynamic icon; now built from the Coral AppIcon.icon with Xcode 27.2's actool. |

### `web/electron/icons/README.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | copy of the square ˋdocs/images/omnigent-logo.svgˋ. electron-builder | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/electron/icons/icon.icns`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish macOS icon; build.mac.icon is now coral-icon.icns. Kept, unused. |

### `web/electron/icons/icon.ico`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish Windows icon; build.win.icon is now coral-icon.ico. Kept, unused. |

### `web/electron/icons/icon.png`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish app icon; runtime and About now use coral-icon.png. Kept, unused. |

### `web/electron/icons/icon.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish Linux icon; build.linux.icon is now coral-icon.svg. Kept, unused. |

### `web/electron/package.json`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | "name": "omnigent-desktop-electron", | keep-internal |  | npm package name; REBRAND step 4 says keep the n |
| 3 | "productName": "Omnigent", | change | S87 | Electron productName metadata: app bundle and window/app name. |
| 5 | "description": "Omnigent desktop shell (Electron edition) \u2014 a thin native wrapper around the se… | change | S87 | Electron package description metadata names the product. |
| 8 | "homepage": "https://omnigent.ai", | change | S87 | Homepage metadata points at an Omnigent destination. |
| 11 | "url": "https://github.com/omnigent-ai/omnigent.git" | change | S87 | Repository URL metadata points at the Omnigent repo; Coral has its own repository. |
| 14 | "name": "Databricks, Inc.", | change | S87 | Author names Databricks as Coral's author; L8 forbids it. |
| 15 | "email": "support@omnigent.ai" | change | S87 | Author/support email is an Omnigent address. |
| 21 | …": "electron-builder -c.appId=ai.omnigent.desktop-dev -c.productName='Omnigent Dev' -c.directories.o… | change-identity | S87 | Dev build overrides use the Omnigent dev app id and product name. |
| 22 | …ectron-builder --mac -c.appId=ai.omnigent.desktop-dev -c.productName='Omnigent Dev' -c.directories.o… | change-identity | S87 | Dev mac build overrides use the Omnigent dev app id and product name. |
| 23 | …:release": "OMNIGENT_NOTARIZE_DMG=true… | keep-internal |  | OMNIGENT_NOTARIZE_DMG env var; REBRAND step 4 sa |
| 24 | …tron-builder --linux -c.appId=ai.omnigent.desktop-dev -c.productName='Omnigent Dev' -c.directories.o… | change-identity | S87 | Dev linux build overrides use the Omnigent dev app id and product name. |
| 25 | …ectron-builder --win -c.appId=ai.omnigent.desktop-dev -c.productName='Omnigent Dev' -c.directories.o… | change-identity | S87 | Dev windows build overrides use the Omnigent dev app id and product name. |
| 42 | "appId": "ai.omnigent.desktop", | change-identity | S87 | Desktop app id ai.omnigent.desktop must become Coral's DESKTOP_APP_ID. |
| 43 | "productName": "Omnigent", | change | S87 | build.productName shows as the packaged app name. |
| 49 | "name": "Omnigent session link", | change | S87 | Protocol display name (CFBundleURLName) names the product. |
| 51 | "omnigent" | change-identity | S38 | Registered deep-link URL scheme becomes coral. |
| 58 | "url": "https://omnigent.ai/_desktop/updates/" | change | S87 | Updater publish feed points at omnigent.ai; L8 forbids Omnigent/Databricks update source. |
| 96 | "identity": "Databricks, Inc. (8RMX4WU6F8)", | change | S87 | mac signing identity names Databricks as signer; L8 forbids it, REBRAND sets null (unsigned). |
| 101 | "NSMicrophoneUsageDescription": "Omnigent uses the microphone for voice dictation in the message com… | change | S87 | macOS microphone permission prompt text shown to users names the product. |
| 126 | "url": "https://omnigent.ai/_desktop/updates/" | change | S87 | mac updater publish feed points at omnigent.ai. |
| 154 | "maintainer": "Databricks, Inc. <support@omnigent.ai>", | change | S87 | Linux maintainer names Databricks and an Omnigent email; L8 forbids it. |
| 162 | "url": "https://omnigent.ai/_desktop/updates/" | change | S87 | Linux updater publish feed points at omnigent.ai. |
| 174 | "url": "https://omnigent.ai/_desktop/updates/" | change | S87 | Windows updater publish feed points at omnigent.ai. |

### `web/electron/reconnect-overlay/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 110 | <p id="title"><span id="spinner" aria-hidden="true"></span>Reconnecting to Databricks…</p> | keep-origin |  | Reconnecting to a Databricks workspace; names the Databricks integration target, not Coral's publisher. |
| 118 | …) => window.omnigentReconnectOverlay.c… | keep-internal |  | window.omnigentReconnectOverlay preload bridge n |

### `web/electron/return-banner/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 92 | <span id="msg">If you are stuck, return to Omnigent here.</span> | change | S87 | Visible banner text uses Omnigent as the app name. |
| 99 | window.omnigentReturnBanner.goBack(); | keep-internal |  | window.omnigentReturnBanner preload bridge name. |
| 102 | window.omnigentReturnBanner.dismiss(); | keep-internal |  | window.omnigentReturnBanner preload bridge name. |

### `web/electron/setup/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | <title>Omnigents — Connect</title> | change | S89b | Setup/connect window tab title shows the product name to users. |
| 273 | …— opens the Omnigent CLI modal. no-dra… | keep-internal |  | CSS code comment, not shown to users. |
| 425 | aria-label="Configure the Omnigent CLI" | keep-deferred |  | aria-label names the omnigent CLI binary Coral still uses; renamed by OPS-03/FND-01 when a coral CLI exists. |
| 426 | title="Configure the Omnigent CLI" | keep-deferred |  | Tooltip names the omnigent CLI binary; changes with OPS-03/FND-01 CLI naming. |
| 450 | srcset="../../platform-assets/logos/omnigents-logo-reverse.svg" | change-asset | S89b | Dark-mode srcset shows the Omnigent wordmark logo on the connect page. |
| 453 | <img class="logo" src="../../platform-assets/logos/omnigents-logo.svg" alt="Omnigents" /> | change-asset | S89b | Connect page logo image is the Omnigent wordmark, alt text names Omnigents. |
| 455 | <p class="sub">Run an Omnigent server on this machine, or connect to an existing one.</p> | change | S89b | Visible subtitle uses Omnigent server product wording. |
| 499 | <!-- Omnigent CLI settings, opened fro… | keep-internal |  | code comment |
| 501 | <div class="modal" role="dialog" aria-modal="true" aria-label="Omnigent CLI settings"> | keep-deferred |  | Dialog aria-label names the omnigent CLI; OPS-03/FND-01 renames the CLI. |
| 502 | <p class="modal-title">Omnigent CLI</p> | keep-deferred |  | Modal title names the omnigent CLI binary; changes with OPS-03/FND-01. |
| 510 | href="https://omnigent.ai/quickstart/install#install-omnigent" | keep-deferred |  | omnigent.ai install docs link; Coral has no distribution yet (OPS-09). |
| 513 | >Install the Omnigent CLI ↗</a | keep-deferred |  | Install link label for the omnigent CLI; changes with OPS-09 distribution and OPS-03/FND-01 CLI name. |
| 519 | <p id="cli-path-label">Path to the Omnigent CLI</p> | keep-deferred |  | Label for path to the omnigent CLI binary; OPS-03/FND-01. |
| 539 | …d as window.omnigentUrl | keep-internal |  | Code comment naming the window.omnigentUrl prelo |
| 541 | … } = window.omnigentUrl; | keep-internal |  | window.omnigentUrl preload bridge identifier. |
| 543 | const setup = window.omnigentSetup; | keep-internal |  | window.omnigentSetup preload bridge identifier. |
| 779 | …t locally + omnigent CLI detection ---… | keep-internal |  | Code comment about omnigent CLI detection. |
| 780 | …ally" runs ˋomnigent serverˋ via the m… | keep-internal |  | Code comment describing ˋomnigent serverˋ launch |
| 782 | …s the local omnigent CLI, so we detect… | keep-internal |  | Code comment about the local omnigent CLI. |
| 836 | : "Omnigent CLI found." | keep-deferred |  | Status text names the omnigent CLI binary; changes with OPS-03/FND-01. |
| 837 | : "Omnigent CLI not found."; | keep-deferred |  | Status text names the omnigent CLI binary; changes with OPS-03/FND-01. |
| 862 | : "Found the Omnigent CLI."; | keep-deferred |  | Path-accepted note names the omnigent CLI; OPS-03/FND-01. |
| 870 | cliPathNote.textContent = "That path is not a runnable Omnigent CLI."; | keep-deferred |  | Path-rejected error names the omnigent CLI; OPS-03/FND-01. |
| 926 | "The Omnigent CLI was not found. CLI customization is disabled by your organization."; | keep-deferred |  | Managed-mode error names the omnigent CLI binary; OPS-03/FND-01. |

### `web/electron/src/about_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | "omnigentAbout", | keep-internal |  | window.omnigentAbout preload bridge name used by |
| 10 | …rer.invoke("omnigent:about-get-info"), | keep-internal |  | 'omnigent:' IPC channel name. |
| 11 | …rer.invoke("omnigent:about-get-desktop… | keep-internal |  | 'omnigent:' IPC channel name. |
| 12 | …rer.invoke("omnigent:about-check-deskt… | keep-internal |  | 'omnigent:' IPC channel name. |
| 13 | …rer.invoke("omnigent:about-download-de… | keep-internal |  | 'omnigent:' IPC channel name. |
| 14 | …rer.invoke("omnigent:about-install-des… | keep-internal |  | 'omnigent:' IPC channel name. |
| 17 | …enderer.on("omnigent:update-status", l… | keep-internal |  | 'omnigent:update-status' IPC channel name. |
| 18 | …veListener("omnigent:update-status", l… | keep-internal |  | 'omnigent:update-status' IPC channel name. |
| 20 | …derer.send("omnigent:about-close"), | keep-internal |  | 'omnigent:about-close' IPC channel name. |

### `web/electron/src/about_window.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 125 | title: "About Omnigent", | change | S87 | BrowserWindow title shown in the window chrome for the About dialog. |
| 175 | …ain.handle("omnigent:about-get-info", … | keep-internal |  | 'omnigent:' IPC handler channel. |
| 186 | …ain.handle("omnigent:about-get-desktop… | keep-internal |  | 'omnigent:' IPC handler channel. |
| 191 | …ain.handle("omnigent:about-check-deskt… | keep-internal |  | 'omnigent:' IPC handler channel. |
| 197 | …ain.handle("omnigent:about-download-de… | keep-internal |  | 'omnigent:' IPC handler channel. |
| 203 | …ain.handle("omnigent:about-install-des… | keep-internal |  | 'omnigent:' IPC handler channel. |
| 210 | ipcMain.on("omnigent:about-close", (ev… | keep-internal |  | 'omnigent:about-close' IPC listener channel. |

### `web/electron/src/arca.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …connection (Databricks-internal). | keep-internal |  | code comment |
| 6 | * Arca is Databricks' internal sandbox… | keep-internal |  | code comment |
| 9 | * Omnigent host means running, over ˋa… | keep-internal |  | code comment |
| 13 | …aacˋ is the Databricks-internal launch… | keep-internal |  | code comment |
| 17 | …a box's own Omnigent OAuth grant; gene… | keep-internal |  | code comment |
| 64 | …mirrors the omnigent CLI | keep-internal |  | code comment |
| 65 | * resolution in omnigent_cli.js). | keep-internal |  | code comment |
| 216 | …nown arca / omnigent CLI failure shape… | keep-internal |  | code comment |
| 246 | … Arca box's Databricks credentials can… | keep-internal |  | code comment |
| 247 | if (/OMNIGENT_AUTH_REQUIRED\|not signed… | keep-internal |  | code identifier |
| 661 | …rUrlˋ as an Omnigent | keep-internal |  | code comment |
| 837 | …rUrlˋ as an Omnigent host. Thin | keep-internal |  | code comment |
| 890 | …ler-name", "omnigent", "--update-kubec… | keep-internal |  | dbcert --caller-name protocol token passed to an |

### `web/electron/src/arcaIdentity.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …dServerUrl, databricksWorkspaceUiUrl }… | keep-internal |  | code identifier |
| 5 | …_START = "__OMNIGENT_ARCA_IDENTITY_STA… | keep-internal |  | Machine-readable output marker parsed by arca.js |
| 6 | …TY_END = "__OMNIGENT_ARCA_IDENTITY_END… | keep-internal |  | Machine-readable output marker parsed by arca.js |
| 12 | …l = new URL(databricksWorkspaceUiUrl(s… | keep-internal |  | code identifier |

### `web/electron/src/arca_autoconnect.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …to-connect (Databricks-internal): when… | keep-internal |  | code comment |
| 20 | … require("./omnigent_cli"); | keep-internal |  | require of the internal omnigent_cli module (JS |

### `web/electron/src/arca_onboarding.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …rkspace and Omnigent browser sign-ins. | keep-internal |  | code comment |

### `web/electron/src/away_banner.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | // Databricks ˋˋ…/omnigentˋˋ mount wit… | keep-internal |  | code comment |
| 31 | … Covers the Databricks workspace login… | keep-internal |  | code comment |

### `web/electron/src/browserIpc.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 65 | message: ˋImport ${what} into Omnigent?ˋ, | change | S87 | Native Electron consent dialog message shown to the user names the product as Omnigent. |
| 69 | "agent controls, until you quit Omnigent.", | change | S87 | Native consent dialog detail text shown to the user says 'until you quit Omnigent' (app name). |
| 340 | …ster every ˋomnigent:browser-*ˋ IPC ha… | keep-internal |  | code comment |
| 423 | …ain.handle("omnigent:browser-open-or-n… | keep-internal |  | IPC channel name 'omnigent:browser-open-or-navig |
| 509 | …ain.handle("omnigent:browser-set-activ… | keep-internal |  | IPC channel name 'omnigent:browser-set-active'. |
| 523 | …ain.handle("omnigent:browser-focused-v… | keep-internal |  | IPC channel name 'omnigent:browser-focused-view' |
| 538 | …ain.handle("omnigent:browser-set-suppr… | keep-internal |  | IPC channel name 'omnigent:browser-set-suppresse |
| 547 | …ain.handle("omnigent:browser-set-recen… | keep-internal |  | IPC channel name 'omnigent:browser-set-recent-se |
| 554 | …ain.handle("omnigent:browser-cancel-re… | keep-internal |  | IPC channel name 'omnigent:browser-cancel-recent |
| 561 | …ain.handle("omnigent:browser-resize", … | keep-internal |  | IPC channel name 'omnigent:browser-resize'. |
| 575 | …ain.handle("omnigent:browser-screensho… | keep-internal |  | IPC channel name 'omnigent:browser-screenshot'. |
| 602 | …ain.handle("omnigent:browser-perform-a… | keep-internal |  | IPC channel name 'omnigent:browser-perform-actio |
| 605 | …ain.handle("omnigent:browser-execute",… | keep-internal |  | IPC channel name 'omnigent:browser-execute'. |
| 611 | …ain.handle("omnigent:browser-has-view"… | keep-internal |  | IPC channel name 'omnigent:browser-has-view'. |
| 636 | …ain.handle("omnigent:browser-close", (… | keep-internal |  | IPC channel name 'omnigent:browser-close'. |
| 648 | …ain.handle("omnigent:browser-go-back",… | keep-internal |  | IPC channel name 'omnigent:browser-go-back'. |
| 657 | …ain.handle("omnigent:browser-go-forwar… | keep-internal |  | IPC channel name 'omnigent:browser-go-forward'. |
| 666 | …ain.handle("omnigent:browser-reload", … | keep-internal |  | IPC channel name 'omnigent:browser-reload'. |
| 682 | …ain.handle("omnigent:open-browser-devt… | keep-internal |  | IPC channel name 'omnigent:open-browser-devtools |
| 705 | …ain.handle("omnigent:browser-enable-de… | keep-internal |  | IPC channel name 'omnigent:browser-enable-design |
| 741 | …ain.handle("omnigent:browser-disable-d… | keep-internal |  | IPC channel name 'omnigent:browser-disable-desig |
| 777 | …ain.handle("omnigent:browser-chrome-co… | keep-internal |  | IPC channel name 'omnigent:browser-chrome-cookie |
| 794 | …ain.handle("omnigent:browser-chrome-co… | keep-internal |  | IPC channel name 'omnigent:browser-chrome-cookie |
| 880 | …ain.handle("omnigent:browser-signal-de… | keep-internal |  | IPC channel name 'omnigent:browser-signal-design |

### `web/electron/src/browserPermissionPrompt.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 64 | partition: "omnigent-browser-permissio… | keep-internal |  | Electron session partition name for the permissi |
| 118 | …ain.handle("omnigent:browser-permissio… | keep-internal |  | IPC channel 'omnigent:browser-permission-info' u |
| 122 | …ain.handle("omnigent:browser-permissio… | keep-internal |  | IPC channel 'omnigent:browser-permission-choose' |

### `web/electron/src/browserUrlPolicy.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 42 | * ˋomnigent/util/ssrf.pyˋ, but deliber… | keep-internal |  | code comment |

### `web/electron/src/browserViewRegistry.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 68 | return ˋomnigent-agent-${scope}-${conv… | keep-internal |  | Agent browser-view session partition name; asser |

### `web/electron/src/browser_permission_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …nMainWorld("omnigentBrowserPermission"… | keep-internal |  | Preload bridge name window.omnigentBrowserPermis |
| 6 | …rer.invoke("omnigent:browser-permissio… | keep-internal |  | IPC channel 'omnigent:browser-permission-info'. |
| 7 | …rer.invoke("omnigent:browser-permissio… | keep-internal |  | IPC channel 'omnigent:browser-permission-choose' |

### `web/electron/src/chromeCookieStore.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 387 | ….tmpdir(), "omnigent-chrome-cookie-"))… | keep-internal |  | Temp-directory name prefix for the Chrome cookie |

### `web/electron/src/cli_install.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | * In-app Omnigent CLI installation (ma… | keep-internal |  | code comment |
| 7 | …python 3.12 omnigentˋ and drops the ˋo… | keep-internal |  | code comment |
| 165 | onOutput("Installing uv (required by the Omnigent installer)…\n"); | keep-deferred |  | Setup-terminal output names the bundled Omnigent installer (install_oss.sh); OPS-09 changes the install path. |
| 180 | "Couldn't install uv, which the Omnigent installer requires. " + | keep-deferred |  | Error naming the Omnigent installer (install_oss.sh); unchanged until OPS-09 provides Coral distribution. |
| 189 | …uv (and the omnigent binaries it later… | keep-internal |  | code comment |
| 224 | …Install the Omnigent CLI. Ensures uv, … | keep-internal |  | code comment |
| 244 | error: "In-app install is macOS-only for now. Install the CLI from https://omnigent.ai/.", | keep-deferred |  | Install link to https://omnigent.ai/; Coral has no distribution yet, OPS-09 changes it. |
| 258 | onOutput("Installing the Omnigent CLI…\n"); | keep-deferred |  | Names the omnigent CLI being installed; OPS-03/FND-01 (CLI name) and OPS-09 (installer). Mirrored in onboarding SetupTerminalStep/mockSetup. |

### `web/electron/src/connection_loading.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 84 | …tents.send("omnigent:connection-loadin… | keep-internal |  | IPC channel 'omnigent:connection-loading' sent t |
| 94 | …tents.send("omnigent:connection-loadin… | keep-internal |  | IPC channel 'omnigent:connection-loading'. |

### `web/electron/src/connection_loading_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …enderer.on("omnigent:connection-loadin… | keep-internal |  | IPC channel 'omnigent:connection-loading' listen |

### `web/electron/src/databricks-account.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | … { isTrustedDatabricksOrigin } = requi… | keep-internal |  | JS import of the Databricks OAuth integration mo |
| 31 | …nts.<cloud>.databricks.com/oidc/accoun… | keep-internal |  | code comment |
| 57 | …er to a non-Databricks host. accountOr… | keep-internal |  | code comment |
| 59 | … (!isTrustedDatabricksOrigin(account.a… | keep-internal |  | code identifier |

### `web/electron/src/databricks-auth.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | // Databricks browser-auth lifecycle. … | keep-internal |  | code comment |
| 4 | const { isDatabricksOAuthServerUrl } =… | keep-internal |  | code identifier |
| 6 | const DATABRICKS_BROWSER_AUTH_KEY = "D… | keep-internal |  | NSUserDefaults key DatabricksBrowserAuthEnabled, |
| 8 | function readDatabricksAuthMode({ | keep-internal |  | code identifier |
| 16 | …Defaults({ [DATABRICKS_BROWSER_AUTH_KE… | keep-internal |  | code identifier |
| 17 | …UserDefault(DATABRICKS_BROWSER_AUTH_KE… | keep-internal |  | code identifier |
| 25 | …unction usesDatabricksBrowserAuth(url,… | keep-internal |  | code identifier |
| 26 | …owser" && isDatabricksOAuthServerUrl(u… | keep-internal |  | code identifier |
| 29 | function isDatabricksLoginUrl(rawUrl, … | keep-internal |  | code identifier |
| 61 | …as cut off (databricks-session.js). | keep-internal |  | code comment |
| 79 | function createDatabricksAuth({ | keep-internal |  | code identifier |
| 145 | if (!cookies.length) throw new Error("Databricks session cookie is missing"); | keep-origin |  | Error about the Databricks workspace session cookie; names the third-party Databricks integration, not the publisher. |
| 150 | if (remaining <= 0) throw new Error("Databricks session cookie is expired"); | keep-origin |  | Error about an expired Databricks session cookie; factual Databricks integration reference. |
| 166 | …nsole.log("[omnigent] databricks auth:… | keep-internal |  | Console log prefix '[omnigent] databricks auth' |
| 189 | …sole.warn("[omnigent] databricks auth:… | keep-internal |  | Console warn prefix '[omnigent] databricks auth' |
| 210 | sessionRejected("Databricks rejected the renewed session; sign in again in your browser"), | keep-origin |  | Sign-in error naming Databricks as the workspace auth provider; factual integration reference. |
| 220 | if (!isDatabricksOAuthServerUrl(origin… | keep-internal |  | code identifier |
| 221 | throw new Error("Browser session renewal requires a pinned Databricks workspace"); | keep-origin |  | Error requiring a pinned Databricks workspace; factual Databricks integration reference. |
| 241 | if (isDatabricksLoginUrl(url, origin))… | keep-internal |  | code identifier |
| 293 | …t login = isDatabricksLoginUrl(details… | keep-internal |  | code identifier |
| 339 | DATABRICKS_BROWSER_AUTH_KEY, | keep-internal |  | code identifier |
| 340 | readDatabricksAuthMode, | keep-internal |  | code identifier |
| 341 | usesDatabricksBrowserAuth, | keep-internal |  | code identifier |
| 342 | isDatabricksLoginUrl, | keep-internal |  | code identifier |
| 348 | createDatabricksAuth, | keep-internal |  | code identifier |

### `web/electron/src/databricks-oauth.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | // Databricks OAuth (PKCE + loopback) … | keep-internal |  | code comment |
| 3 | …w against a Databricks | keep-internal |  | code comment |
| 5 | …esh tokens. databricks-session.js | keep-internal |  | code comment |
| 7 | …top driving Databricks login inside it… | keep-internal |  | code comment |
| 8 | // and Databricks itself are locking d… | keep-internal |  | code comment |
| 10 | …first-party Databricks app (client_id … | keep-internal |  | code comment |
| 12 | //   OMNIGENT_DATABRICKS_OAUTH_CLIENT_… | keep-internal |  | code comment |
| 13 | //   OMNIGENT_DATABRICKS_OAUTH_CLIENT_… | keep-internal |  | code comment |
| 14 | …           "omnigent" client, which au… | keep-internal |  | code comment |
| 15 | //   OMNIGENT_DATABRICKS_OAUTH_SCOPES … | keep-internal |  | code comment |
| 16 | //   OMNIGENT_DATABRICKS_OAUTH_FORCE_R… | keep-internal |  | code comment |
| 22 | …es API (see databricks-session.js). Ac… | keep-internal |  | code comment |
| 35 | …r RFC 8252 (Databricks ignores it), an… | keep-internal |  | code comment |
| 41 | … published "omnigent" connector exists… | keep-internal |  | code comment |
| 42 | …process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | OMNIGENT_* env var plus the Databricks-registere |
| 43 | …he shipped "omnigent" client is public… | keep-internal |  | code comment |
| 46 | …process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | code identifier |
| 56 | …k a trusted Databricks origin. The lea… | keep-internal |  | code comment |
| 57 | …likes (evil-databricks.com, databricks… | keep-internal |  | code comment |
| 58 | …sts (…cloud.databricks.com, …gcp.datab… | keep-internal |  | code comment |
| 59 | … (accounts.…databricks.com) since all … | keep-internal |  | code comment |
| 60 | const TRUSTED_HOST_SUFFIXES = [".databricks.com", ".azuredatabricks.net"]; | keep-origin |  | Trusted Databricks host suffixes for the Databricks workspace integration (security allowlist) |
| 65 | …process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | code identifier |
| 70 | …n a trusted Databricks host. The OAuth… | keep-internal |  | code comment |
| 75 | …on isTrustedDatabricksOrigin(url) { | keep-internal |  | code identifier |
| 84 | …n store (~/.omnigent, encrypted at res… | keep-internal |  | code comment |
| 87 | fileName: "databricks_oauth_tokens.jso… | keep-internal |  | Persisted token-store file name under ~/.omnigen |
| 88 | label: "Databricks tokens", | keep-origin |  | Names the Databricks integration credentials; only used in a console.warn about unencrypted storage |
| 135 | …nsole.log("[omnigent] databricks oauth… | keep-internal |  | Console log prefix, not shown in UI |
| 167 | …ers?.get("x-databricks-request-id") ??… | keep-internal |  | Databricks response header name read for request |
| 169 | …ics.record("databricks_token", { | keep-internal |  | Diagnostics event key written to desktop-diagnos |
| 177 | …nsole.log("[omnigent] databricks oauth… | keep-internal |  | Console log prefix, not shown in UI |
| 246 | ˋ[omnigent] databricks oauth: refreshi… | keep-internal |  | Console log prefix, not shown in UI |
| 257 | ˋ[omnigent] databricks oauth: grant de… | keep-internal |  | Console warn log, not shown in UI |
| 274 | ˋ[omnigent] databricks oauth: refreshe… | keep-internal |  | Console log prefix, not shown in UI |
| 301 | throw Object.assign(new Error(ˋno stored Databricks token for ${workspaceOrigin}ˋ), { | keep-origin |  | Error text factually naming the Databricks integration token |
| 306 | …ting lever: OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | code comment |
| 309 | …process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | code identifier |
| 312 | ˋ[omnigent] databricks oauth: using ca… | keep-internal |  | Console log prefix, not shown in UI |
| 319 | ˋ[omnigent] databricks oauth: ${forceR… | keep-internal |  | Console log prefix, not shown in UI |
| 325 | new Error(ˋstored Databricks token for ${workspaceOrigin} is expired with no refresh tokenˋ), | keep-origin |  | Error text factually naming the Databricks integration token |
| 373 | …nsole.log("[omnigent] databricks oauth… | keep-internal |  | Console log prefix, not shown in UI |
| 381 | ˋ[omnigent] databricks oauth: authoriz… | keep-internal |  | Console warn log, not shown in UI |
| 388 | …sole.warn(ˋ[omnigent] databricks oauth… | keep-internal |  | Console warn log, not shown in UI |
| 396 | …nsole.log("[omnigent] databricks oauth… | keep-internal |  | Console log prefix, not shown in UI |
| 413 | // Databricks matches the registration… | keep-internal |  | code comment |
| 431 | …nsole.log("[omnigent] databricks oauth… | keep-internal |  | Console log in onOpened callback, not shown in U |
| 434 | "Databricks sign-in received", | keep-origin |  | Loopback browser page heading naming the Databricks sign-in integration |
| 435 | "Return to Omnigent to finish connecting, then close this tab.", | change | S87 | Loopback callback page rendered in the user's browser names the app as Omnigent |
| 438 | "Databricks sign-in was not completed", | keep-origin |  | Loopback browser page heading naming the Databricks sign-in integration |
| 439 | "Close this tab and try connecting again in Omnigent.", | change | S87 | Loopback failure page shown in the user's browser names the app as Omnigent |
| 442 | "Databricks sign-in could not be completed", | keep-origin |  | Loopback browser page heading naming the Databricks sign-in integration |
| 443 | "Close this tab and try connecting again in Omnigent.", | change | S87 | Loopback incomplete page shown in the user's browser names the app as Omnigent |
| 457 | … (!isTrustedDatabricksOrigin(callback.… | keep-internal |  | code identifier |
| 458 | throw new Error(ˋauthorization issuer is not a trusted Databricks origin: ${callback.iss}ˋ); | keep-origin |  | Error text factually naming trusted Databricks origins (integration) |
| 462 | …nsole.log("[omnigent] databricks oauth… | keep-internal |  | Console log prefix, not shown in UI |
| 485 | isTrustedDatabricksOrigin, | keep-internal |  | code identifier |

### `web/electron/src/databricks-session.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | // Bridge a Databricks OAuth access to… | keep-internal |  | code comment |
| 4 | // the Databricks One mobile design) w… | keep-internal |  | code comment |
| 7 | …ed, so the /omnigent SPA | keep-internal |  | code comment |
| 8 | …henticated. databricks-oauth.js suppli… | keep-internal |  | code comment |
| 9 | …calls ensureDatabricksSession at the p… | keep-internal |  | code comment |
| 20 | isTrustedDatabricksOrigin, | keep-internal |  | code identifier |
| 21 | } = require("./databricks-oauth"); | keep-internal |  | Module require path for the Databricks integrati |
| 22 | … require("./databricks-account"); | keep-internal |  | Module require path for the Databricks integrati |
| 23 | const { isDatabricksOAuthServerUrl } =… | keep-internal |  | code identifier |
| 29 | } = require("./databricks-auth"); | keep-internal |  | Module require path for the Databricks integrati |
| 60 | …ction ensureDatabricksSession( | keep-internal |  | code identifier |
| 67 | nextPath = "/omnigent", | keep-internal |  | Default /omnigent SPA mount path on the Databric |
| 74 | if (!isDatabricksOAuthServerUrl(origin… | keep-internal |  | code identifier |
| 75 | throw new Error("Browser OAuth requires an HTTPS Databricks workspace/account URL"); | keep-origin |  | Error text factually naming the Databricks workspace/account URL integration |
| 77 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 84 | …await ensureDatabricksSession(ses, sto… | keep-internal |  | code identifier |
| 97 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 122 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 131 | … (!isTrustedDatabricksOrigin(account.a… | keep-internal |  | code identifier |
| 138 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 152 | …nsole.log(ˋ[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 156 | ˋ[omnigent] databricks session: o=${wo… | keep-internal |  | Console warn log, not shown in UI |
| 173 | …nsole.log(ˋ[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 183 | …er to a non-Databricks host. | keep-internal |  | code comment |
| 184 | … (!isTrustedDatabricksOrigin(bridgeOri… | keep-internal |  | code identifier |
| 210 | if (!isDatabricksOAuthServerUrl(origin… | keep-internal |  | code identifier |
| 211 | throw new Error("Session creation requires a same-origin Databricks destination"); | keep-origin |  | Error text factually naming the Databricks destination (integration) |
| 224 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 253 | …sole.warn("[omnigent] databricks sessi… | keep-internal |  | Console warn log, not shown in UI |
| 268 | () => abort(transportError("Databricks session creation timed out")), | keep-origin |  | Error text factually naming the Databricks session integration |
| 280 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 293 | "Databricks session creation redirected to authentication or an unexpected destination", | keep-origin |  | Error text factually naming the Databricks session integration |
| 303 | …eaders?.["x-databricks-request-id"] ??… | keep-internal |  | Databricks response header name read for request |
| 305 | …ics.record("databricks_bridge", { | keep-internal |  | Diagnostics event key written to desktop-diagnos |
| 311 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 326 | response.on("aborted", () => finish(transportError("Databricks session response aborted"))); | keep-origin |  | Error text factually naming the Databricks session integration |
| 328 | finish(transportError("Databricks session response closed before completion")), | keep-origin |  | Error text factually naming the Databricks session integration |
| 334 | request.on("abort", () => finish(new Error("Databricks session request aborted"))); | keep-origin |  | Error text factually naming the Databricks session integration |
| 348 | … blocked by Databricks IP ACL/.test(er… | keep-internal |  | Regex matching a Databricks server error body. |
| 363 | …sole.warn("[omnigent] databricks sessi… | keep-internal |  | Console warn log, not shown in UI |
| 379 | …nsole.log("[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 389 | …ics.record("databricks_session", { ori… | keep-internal |  | Diagnostics event key written to desktop-diagnos |
| 390 | …nsole.log(ˋ[omnigent] databricks sessi… | keep-internal |  | Console log prefix, not shown in UI |
| 396 | …s = { ensureDatabricksSession, mintSes… | keep-internal |  | code identifier |

### `web/electron/src/deepLink.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | // An ˋomnigent://<hostname>/c/<sessio… | keep-internal |  | code comment |
| 11 | …ce mount (ˋ/omnigentˋ) is deliberately… | keep-internal |  | code comment |
| 12 | …ed by expandDatabricksWorkspaceUrl, ex… | keep-internal |  | code comment |
| 25 | * Parse an ˋomnigent://ˋ deep link int… | keep-internal |  | code comment |
| 33 | …raw e.g. ˋˋ"omnigent://localhost:8000/… | keep-internal |  | code comment |
| 35 | …'t a valid ˋomnigent://.../c/<id>ˋ or … | keep-internal |  | code comment |
| 38 | function parseOmnigentDeepLink(raw) { | keep-internal |  | code identifier |
| 45 | if (url.protocol !== "omnigent:") return null; | change-identity | S38 | Deep-link scheme check must follow the new coral:// URL scheme |
| 46 | …t → a bare ˋomnigent://ˋ or ˋomnigent:… | keep-internal |  | code comment |
| 48 | …thname for ˋomnigent://hostˋ — | keep-internal |  | code comment |
| 133 | …aw A parsed Omnigent deep link. | keep-internal |  | code comment |
| 137 | if (!parseOmnigentDeepLink(raw)) retur… | keep-internal |  | code identifier |
| 157 | parseOmnigentDeepLink, | keep-internal |  | code identifier |

### `web/electron/src/desktop_updater.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …ion for the Omnigent Electron shell. | keep-internal |  | code comment |
| 9 | … menu, the ˋomnigent:*update*ˋ IPC sur… | keep-internal |  | code comment |
| 160 | …tents.send("omnigent:update-status", s… | keep-internal |  | IPC channel name 'omnigent:update-status' consum |
| 244 | …: "warn"]("[omnigent] update error:", … | keep-internal |  | Console log prefix in main process, not shown in |
| 347 | message: "Download an Omnigent update?", | change | S87 | Native confirm-dialog message shown to the user names the product. |
| 349 | ˋ${host} wants to download a desktop update for this Omnigent app.\n\nˋ + | change | S87 | Native dialog detail text shown to the user names the product app. |
| 353 | message: "Restart Omnigent to install an update?", | change | S87 | Native confirm-dialog message shown to the user names the product. |
| 355 | ˋ${host} wants to restart Omnigent and install the downloaded desktop update.\n\nˋ + | change | S87 | Native dialog detail text shown to the user names the product. |
| 359 | message: "Change Omnigent update settings?", | change | S87 | Native confirm-dialog message shown to the user names the product. |
| 361 | ˋ${host} wants to change how this Omnigent app checks for and installs updates.\n\nˋ + | change | S87 | Native dialog detail text shown to the user names the product app. |
| 371 | title: "Omnigent", | change | S87 | Native message box title shown to the user is the product name. |
| 383 | …ain.handle("omnigent:get-update-config… | keep-internal |  | IPC channel name 'omnigent:get-update-config'; i |
| 390 | …ain.handle("omnigent:get-update-status… | keep-internal |  | IPC channel name 'omnigent:get-update-status'; i |
| 397 | …ain.handle("omnigent:update-check", as… | keep-internal |  | IPC channel name 'omnigent:update-check'; intern |
| 404 | …ain.handle("omnigent:update-download",… | keep-internal |  | IPC channel name 'omnigent:update-download'; int |
| 419 | …ain.handle("omnigent:update-install", … | keep-internal |  | IPC channel name 'omnigent:update-install'; inte |
| 436 | …ain.handle("omnigent:set-update-config… | keep-internal |  | IPC channel name 'omnigent:set-update-config'; i |

### `web/electron/src/dev_preferences.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | const DEV_DOMAIN = "ai.omnigent.desktop-dev"; | change-identity | S87 | Dev macOS defaults domain / Windows AppUserModelId (main.js:6092) derived from dev app id ai.omnigent.desktop-dev. |

### `web/electron/src/developer_mode.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …y in the ai.omnigent.desktop preferenc… | keep-internal |  | code comment |

### `web/electron/src/diagnostics.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 44 | "databricks", | keep-internal |  | Allowlisted diagnostics phase label for Databric |
| 112 | …sole.warn("[omnigent] could not initia… | keep-internal |  | Console warning prefix, not shown in UI. |
| 132 | …sole.warn("[omnigent] could not write … | keep-internal |  | Console warning prefix, not shown in UI. |
| 186 | …sole.warn("[omnigent] could not remove… | keep-internal |  | Console warning prefix, not shown in UI. |

### `web/electron/src/fileReveal.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 39 | …ain.handle("omnigent:reveal-file", asy… | keep-internal |  | IPC channel name 'omnigent:reveal-file'; interna |

### `web/electron/src/find_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …nMainWorld("omnigentFind", { | keep-internal |  | Preload bridge name window.omnigentFind used by |
| 20 | …derer.send("omnigent:find-query", { | keep-internal |  | IPC channel name 'omnigent:find-query'. |
| 28 | …derer.send("omnigent:find-close"); | keep-internal |  | IPC channel name 'omnigent:find-close'. |
| 35 | …enderer.on("omnigent:find-result", (_e… | keep-internal |  | IPC channel name 'omnigent:find-result'. |
| 39 | …enderer.on("omnigent:find-activate", (… | keep-internal |  | IPC channel name 'omnigent:find-activate'. |

### `web/electron/src/folderChooser.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …ain.handle("omnigent:choose-directory"… | keep-internal |  | IPC channel name 'omnigent:choose-directory'. |
| 30 | …ain.handle("omnigent:dropped-file-path… | keep-internal |  | IPC channel name 'omnigent:dropped-file-path'. |

### `web/electron/src/globalShowShortcut.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 185 | …sole.warn("[omnigent] could not save t… | keep-internal |  | Console warning prefix, not shown in UI. |

### `web/electron/src/hostIdentity.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | … require("./omnigent_cli")) { | keep-internal |  | require of internal module ./omnigent_cli; JS mo |

### `web/electron/src/isaac.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | * Locate Databricks' internal ˋisaacˋ … | keep-internal |  | code comment |
| 5 | … mirror the Omnigent/Arca | keep-internal |  | code comment |

### `web/electron/src/loginShellPath.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | … START = "__OMNIGENT_PATH_START__"; | keep-internal |  | Internal stdout marker parsed by extractPath; ne |
| 8 | const END = "__OMNIGENT_PATH_END__"; | keep-internal |  | Internal stdout marker parsed by extractPath; ne |

### `web/electron/src/main.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | // Omnigent desktop shell — Electron e… | keep-internal |  | code comment |
| 5 | …rved by the Omnigent server itself. At… | keep-internal |  | code comment |
| 9 | … on ˋwindow.omnigentDesktopˋ). | keep-internal |  | code comment |
| 45 | const { omnigentBuild } = require("../… | keep-internal |  | code identifier |
| 57 | expandDatabricksWorkspaceUrl, | keep-internal |  | code identifier |
| 60 | isDatabricksManagedServerUrl, | keep-internal |  | code identifier |
| 62 | databricksWorkspaceUiUrl, | keep-internal |  | code identifier |
| 67 | …onst { parseOmnigentDeepLink, chooseDe… | keep-internal |  | code identifier |
| 88 | getDatabricksInternalFeaturesEnabled, | keep-internal |  | code identifier |
| 101 | …nst { ensureDatabricksSession } = requ… | keep-internal |  | require of ./databricks-session module; JS ident |
| 103 | …oken: forgetDatabricksToken, | keep-internal |  | code identifier |
| 106 | …ettled: whenDatabricksRefreshSettled, | keep-internal |  | code identifier |
| 107 | } = require("./databricks-oauth"); | keep-internal |  | require of ./databricks-oauth module path; inter |
| 111 | readDatabricksAuthMode, | keep-internal |  | code identifier |
| 112 | usesDatabricksBrowserAuth, | keep-internal |  | code identifier |
| 113 | isDatabricksLoginUrl, | keep-internal |  | code identifier |
| 114 | createDatabricksAuth, | keep-internal |  | code identifier |
| 118 | } = require("./databricks-auth"); | keep-internal |  | require of ./databricks-auth module path; intern |
| 133 | const omnigentCli = require("./omnigen… | keep-internal |  | require of ./omnigent_cli module and omnigentCli |
| 158 | …* True when OMNIGENT_SERVER_SELECTOR_V… | keep-internal |  | code comment |
| 160 | …process.env.OMNIGENT_SERVER_SELECTOR_V… | keep-internal |  | code identifier |
| 163 | …MDM-enabled Databricks macOS users. */ | keep-internal |  | code comment |
| 170 | const isDatabricksManaged = databricks… | keep-internal |  | code identifier |
| 182 | …/ Enable on Databricks managed devices… | keep-internal |  | code comment |
| 183 | if (isDatabricksManaged) { | keep-internal |  | code identifier |
| 200 | * OMNIGENT_SERVER_SELECTOR_V2_DEV_URL … | keep-internal |  | code comment |
| 206 | process.env.OMNIGENT_SERVER_SELECTOR_V… | keep-internal |  | code identifier |
| 214 | … Translates OMNIGENT_ONBOARDING_MOCK* … | keep-internal |  | code comment |
| 218 | *   OMNIGENT_ONBOARDING_MOCK=1        … | keep-internal |  | code comment |
| 219 | *   OMNIGENT_ONBOARDING_MOCK_MANAGED=u… | keep-internal |  | code comment |
| 220 | *   OMNIGENT_ONBOARDING_MOCK_RECENTS=u… | keep-internal |  | code comment |
| 221 | *   OMNIGENT_ONBOARDING_MOCK_INSTALLED… | keep-internal |  | code comment |
| 222 | *   OMNIGENT_ONBOARDING_MOCK_REMOTE_EN… | keep-internal |  | code comment |
| 227 | …process.env.OMNIGENT_ONBOARDING_MOCK !… | keep-internal |  | code identifier |
| 229 | …process.env.OMNIGENT_ONBOARDING_MOCK_M… | keep-internal |  | code identifier |
| 230 | …process.env.OMNIGENT_ONBOARDING_MOCK_M… | keep-internal |  | code identifier |
| 231 | …process.env.OMNIGENT_ONBOARDING_MOCK_R… | keep-internal |  | code identifier |
| 232 | …process.env.OMNIGENT_ONBOARDING_MOCK_R… | keep-internal |  | code identifier |
| 233 | …process.env.OMNIGENT_ONBOARDING_MOCK_I… | keep-internal |  | code identifier |
| 234 | …process.env.OMNIGENT_ONBOARDING_MOCK_R… | keep-internal |  | code identifier |
| 243 | …keeping the omnigentSetup | keep-internal |  | code comment |
| 313 | …Packaged \|\| omnigentBuild === "dev"; | keep-internal |  | code identifier |
| 339 | …MDM-managed Databricks-internal-featur… | keep-internal |  | code comment |
| 342 | function databricksInternalFeaturesEna… | keep-internal |  | code identifier |
| 343 | return getDatabricksInternalFeaturesEn… | keep-internal |  | code identifier |
| 360 | …nsole.log(ˋ[omnigent] Arca daemon iden… | keep-internal |  | console.log [omnigent] prefix; main-process log |
| 386 | …nsole.log(ˋ[omnigent] ${message}ˋ), | keep-internal |  | console.log [omnigent] log prefix for arca conne |
| 403 | …nsole.log(ˋ[omnigent] ${message}ˋ), | keep-internal |  | console.log [omnigent] log prefix for ssh connec |
| 406 | …nsole.log(ˋ[omnigent] ${message}ˋ), | keep-internal |  | console.log [omnigent] log prefix for ssh connec |
| 450 | …y default: ˋOMNIGENT_ARCA_AUTO_CONNECT… | keep-internal |  | code comment |
| 459 | process.env.OMNIGENT_ARCA_AUTO_CONNECT… | keep-internal |  | code identifier |
| 469 | isDatabricksManagedServerUrl(serverUrl… | keep-internal |  | code identifier |
| 480 | …nsole.log(ˋ[omnigent] ${message}ˋ), | keep-internal |  | console.log [omnigent] log prefix for arca autoc |
| 537 | …st target = omnigentCli.normalizeServe… | keep-internal |  | code identifier |
| 616 | // Silent Databricks reconnects: every… | keep-internal |  | code comment |
| 797 | * ˋˋabc.aws.databricksapps.comˋˋ → an … | keep-internal |  | code comment |
| 914 | let databricksAuthMode; | keep-internal |  | code identifier |
| 915 | let databricksAuth; | keep-internal |  | code identifier |
| 918 | …d a session Databricks then rejected; | keep-internal |  | code comment |
| 920 | const databricksBrowserSignInRequired … | keep-internal |  | code identifier |
| 923 | const databricksSignOuts = new Map(); | keep-internal |  | code identifier |
| 943 | …tents.send("omnigent:connection-progre… | keep-internal |  | IPC channel omnigent:connection-progress; intern |
| 947 | if (databricksAuthMode === undefined) … | keep-internal |  | code identifier |
| 948 | databricksAuthMode = readDatabricksAut… | keep-internal |  | code identifier |
| 952 | …nsole.log(ˋ[omnigent] databricks auth:… | keep-internal |  | console.log databricks auth mode debug output; n |
| 954 | return usesDatabricksBrowserAuth(url, … | keep-internal |  | code identifier |
| 998 | …nsole.log("[omnigent] databricks auth:… | keep-internal |  | console.log databricks auth reconnect debug outp |
| 1003 | databricksAuth?.rejectConnection(win); | keep-internal |  | code identifier |
| 1046 | …nsole.log("[omnigent] databricks auth:… | keep-internal |  | console.log databricks auth reconnect debug outp |
| 1061 | …nsole.log("[omnigent] databricks auth:… | keep-internal |  | console.log databricks auth reconnect debug outp |
| 1093 | …nsole.log("[omnigent] databricks auth:… | keep-internal |  | console.log databricks auth reconnect debug outp |
| 1108 | if (databricksInternalFeaturesEnabled(… | keep-internal |  | code identifier |
| 1117 | return blocked ? ˋDatabricks blocked this network. ${hint}ˋ : hint; | keep-origin |  | Overlay hint 'Databricks blocked this network' names the Databricks workspace the user connects to (integration target), not Coral's publish |
| 1122 | const problem = blocked ? "Databricks blocked this network." : "Couldn't reach Databricks."; | keep-origin |  | Setup-page message about reaching a Databricks workspace; factual integration-target reference. |
| 1126 | const UNAVAILABLE_HINT = "Databricks isn't responding."; | keep-origin |  | UNAVAILABLE_HINT 'Databricks isn't responding' refers to the connected Databricks workspace service. |
| 1128 | function showDatabricksAuthRequired( | keep-internal |  | code identifier |
| 1137 | phase: "databricks", | keep-internal |  | Diagnostics record phase key "databricks"; inter |
| 1142 | …sole.warn("[omnigent] databricks auth:… | keep-internal |  | console.warn [omnigent] databricks auth debug ou |
| 1150 | databricksBrowserSignInRequired.add(or… | keep-internal |  | code identifier |
| 1156 | …esumable && databricksWorkspaceUiUrl(f… | keep-internal |  | code identifier |
| 1165 | : "Couldn't sign in to Databricks. Please try again."; | keep-origin |  | 'Couldn't sign in to Databricks' is Databricks workspace sign-in integration text, not publisher branding. |
| 1169 | databricksAuth?.rejectConnection(win); | keep-internal |  | code identifier |
| 1185 | function getDatabricksAuth() { | keep-internal |  | code identifier |
| 1186 | databricksAuth ??= createDatabricksAut… | keep-internal |  | code identifier |
| 1188 | …sion: ensureDatabricksSession, | keep-internal |  | code identifier |
| 1192 | …quired: showDatabricksAuthRequired, | keep-internal |  | code identifier |
| 1195 | return databricksAuth; | keep-internal |  | code identifier |
| 1244 | …sole.warn("[omnigent] oidc auth: conne… | keep-internal |  | console.warn [omnigent] oidc auth log prefix; no |
| 1362 | … providers. Databricks browser-auth co… | keep-internal |  | code comment |
| 1422 | …nsole.log(ˋ[omnigent] setBadgeCount(${… | keep-internal |  | console.log [omnigent] setBadgeCount debug outpu |
| 1500 | …te.origin)) databricksAuth?.rejectConn… | keep-internal |  | code identifier |
| 1501 | else databricksAuth?.detach(win); | keep-internal |  | code identifier |
| 1527 | …ith (e.g. a Databricks ˋˋ…/omnigentˋˋ … | keep-internal |  | code comment |
| 1608 | …tents.send("omnigent:host-status-chang… | keep-internal |  | IPC channel omnigent:host-status-changed; intern |
| 1634 | …process.env.OMNIGENT_DESKTOP_VERSION_O… | keep-internal |  | code identifier |
| 1647 | ˋOMNIGENT_DESKTOP_VERSION_OVERRIDE mus… | keep-internal |  | Thrown error names the OMNIGENT_DESKTOP_VERSION_ |
| 1701 | title: "Omnigent", | change | S87 | Global-shortcut consent dialog title shows product name to users. |
| 1702 | message: ˋUse ${label} to show Omnigent from any app?ˋ, | change | S87 | Global-shortcut consent dialog message names the app. |
| 1704 | ˋ${host} wants to set a system-wide shortcut. While Omnigent is running, pressing ˋ + | change | S87 | Global-shortcut dialog detail text names the running app. |
| 1705 | ˋ${label} in any app brings Omnigent to the front.\n\nOnly allow servers you trust.ˋ, | change | S87 | Global-shortcut dialog detail says the shortcut brings Omnigent to front; user-visible app name. |
| 1734 | // "Show Omnigent from anywhere" (opt-… | keep-internal |  | code comment |
| 1767 | …atus: () => omnigentCli.getCliStatus(l… | keep-internal |  | code identifier |
| 1777 | …running old omnigent web. | keep-internal |  | code comment |
| 1801 | …nnecting to Databricks…" overlay over … | keep-internal |  | code comment |
| 1847 | …esolve the ˋomnigentˋ CLI binary path … | keep-internal |  | code comment |
| 1848 | …(ˋˋsettings.omnigent_pathˋˋ) plus the … | keep-internal |  | code comment |
| 1863 | …dSettings().omnigent_path ?? null; | keep-internal |  | code identifier |
| 1868 | omnigentCli.isExecutableFile(cachedCli… | keep-internal |  | code identifier |
| 1872 | … resolved = omnigentCli.resolveCliPath… | keep-internal |  | code identifier |
| 1890 | return databricksInternalFeaturesEnabl… | keep-internal |  | code identifier |
| 1896 | errorMessage: "The omnigent CLI was not found.", | keep-deferred |  | Error names the omnigent CLI binary; CLI rename deferred to OPS-03/FND-01. |
| 1912 | …eturn expandDatabricksWorkspaceUrl(man… | keep-internal |  | code identifier |
| 1917 | … take once (omnigent:take-onboarding-r… | keep-internal |  | code comment |
| 1934 | …serverUrlˋ. Databricks-internal | keep-internal |  | code comment |
| 1936 | * Databricks-managed HTTPS server); ev… | keep-internal |  | code comment |
| 1937 | …cted public Omnigent CLI. Returns null… | keep-internal |  | code comment |
| 1948 | … useIsaac = databricksInternalFeatures… | keep-internal |  | code identifier |
| 1967 | …tus = await omnigentCli.getCliStatus(t… | keep-internal |  | code identifier |
| 1971 | settings.omnigent_path = trimmed; | keep-internal |  | code identifier |
| 1975 | delete settings.omnigent_path; | keep-internal |  | code identifier |
| 1989 | delete settings.omnigent_path; | keep-internal |  | code identifier |
| 1991 | return omnigentCli.getCliStatus(null); | keep-internal |  | code identifier |
| 2259 | …ttps://host/omnigent/ˋˋ). The path is | keep-internal |  | code comment |
| 2262 | * ˋˋ/omnigentˋˋ — so we string-concate… | keep-internal |  | code comment |
| 2305 | databricksAuth?.reset(win); | keep-internal |  | code identifier |
| 2322 | …l), phase: "databricks" }); | keep-internal |  | Diagnostics auth_mode phase key "databricks"; in |
| 2324 | const auth = getDatabricksAuth(); | keep-internal |  | code identifier |
| 2332 | …igningOut = databricksSignOuts.get(ent… | keep-internal |  | code identifier |
| 2346 | (databricksBrowserSignInRequired.has(e… | keep-internal |  | code identifier |
| 2347 | databricksBrowserSignInRequired.has(st… | keep-internal |  | code identifier |
| 2348 | …await ensureDatabricksSession( | keep-internal |  | code identifier |
| 2362 | databricksBrowserSignInRequired.delete… | keep-internal |  | code identifier |
| 2363 | databricksBrowserSignInRequired.delete… | keep-internal |  | code identifier |
| 2367 | serverUrl = databricksWorkspaceUiUrl(r… | keep-internal |  | code identifier |
| 2387 | …edOrigin && databricksWorkspaceUiUrl(e… | keep-internal |  | code identifier |
| 2388 | showDatabricksAuthRequired(win, worksp… | keep-internal |  | code identifier |
| 2396 | …else if (!isDatabricksManagedServerUrl… | keep-internal |  | code identifier |
| 2398 | // Databricks hosts keep their URL-bas… | keep-internal |  | code comment |
| 2445 | if (!reconnectOverlay.isShown(win)) connectionLoading.show(win, attempt, "Opening Omnigent…"); | change | S87 | Connection-loading overlay status 'Opening Omnigent…' is shown in the window while connecting. |
| 2571 | …sole.warn("[omnigent] databricks auth:… | keep-internal |  | console.warn databricks auth page load failed; l |
| 2578 | databricksAuth?.rejectConnection(win); | keep-internal |  | code identifier |
| 2626 | …sole.warn("[omnigent] databricks auth:… | keep-internal |  | console.warn databricks auth page load failed; l |
| 2630 | databricksAuth?.rejectConnection(win); | keep-internal |  | code identifier |
| 2677 | title: "Omnigent", | change | S87 | BrowserWindow title shown in window chrome/taskbar before page title loads. |
| 2713 | // (ˋˋomnigent host --serverˋˋ, ˋˋomni… | keep-internal |  | code comment |
| 2770 | …sole.warn(ˋ[omnigent] ${message}ˋ), | keep-internal |  | console.warn [omnigent] debug log prefix for ser |
| 2811 | …rigin) && isDatabricksLoginUrl(url, or… | keep-internal |  | code identifier |
| 2812 | getDatabricksAuth().recover(win); | keep-internal |  | code identifier |
| 2865 | // Databricks workspace-hosted Omnigen… | keep-internal |  | code comment |
| 2867 | … overlaying Omnigent's own root — see | keep-internal |  | code comment |
| 2877 | databricksAuth?.reset(win); | keep-internal |  | code identifier |
| 3008 | …tents.send("omnigent:find-opened"); | keep-internal |  | IPC channel omnigent:find-opened; internal chann |
| 3012 | …tents.send("omnigent:find-activate"); | keep-internal |  | IPC channel omnigent:find-activate; internal cha |
| 3038 | …tents.send("omnigent:find-result", { | keep-internal |  | IPC channel omnigent:find-result; internal chann |
| 3151 | …nsole.log(ˋ[omnigent] dev: cleared ${c… | keep-internal |  | console.log [omnigent] dev cookie-clear debug ou |
| 3202 | … existing = databricksSignOuts.get(ori… | keep-internal |  | code identifier |
| 3206 | … = signOutOfDatabricks(origin); | keep-internal |  | code identifier |
| 3207 | databricksSignOuts.set(origin, pending… | keep-internal |  | code identifier |
| 3211 | if (databricksSignOuts.get(origin) ===… | keep-internal |  | code identifier |
| 3215 | /** The Databricks half of {@link sign… | keep-internal |  | code comment |
| 3216 | …on signOutOfDatabricks(origin) { | keep-internal |  | code identifier |
| 3240 | await databricksAuth?.whenSettled(orig… | keep-internal |  | code identifier |
| 3241 | await whenDatabricksRefreshSettled(ori… | keep-internal |  | code identifier |
| 3245 | forgetDatabricksToken(origin); | keep-internal |  | code identifier |
| 3248 | …sole.warn("[omnigent] databricks auth:… | keep-internal |  | console.warn databricks auth token-forget failur |
| 3257 | …sole.warn("[omnigent] databricks auth:… | keep-internal |  | console.warn databricks auth DBAUTH clear failur |
| 3261 | … (complete) databricksBrowserSignInReq… | keep-internal |  | code identifier |
| 3262 | else databricksBrowserSignInRequired.a… | keep-internal |  | code identifier |
| 3273 | …nsole.log("[omnigent] databricks auth:… | keep-internal |  | console.log databricks auth signed out; log outp |
| 3292 | ˋ[omnigent] dev: removed the cached re… | keep-internal |  | console.log [omnigent] dev refresh-token debug o |
| 3309 | message: "Connect to a Databricks workspace using browser OAuth first.", | keep-origin |  | Dev dialog 'Connect to a Databricks workspace using browser OAuth first' names the Databricks OAuth integration target. |
| 3328 | …nsole.log(ˋ[omnigent] dev: ${action} f… | keep-internal |  | console.log [omnigent] dev token-expiry debug ou |
| 3437 | // Omnigent's own prompt rather than a… | keep-internal |  | code comment |
| 3453 | title: "Omnigent", | change | S87 | Runner-permission consent dialog title shows product name. |
| 3454 | message: ˋAllow ${host} to manage Omnigent on this machine?ˋ, | change | S87 | Runner-permission dialog message 'Allow host to manage Omnigent on this machine?' is user-visible. |
| 3498 | …sole.warn("[omnigent] signalForeground… | keep-internal |  | console.warn signalForeground failure log; not U |
| 3589 | …sole.warn("[omnigent] afplay failed:",… | keep-internal |  | console.warn afplay failure log; not UI. |
| 3593 | …sole.warn("[omnigent] failed to spawn … | keep-internal |  | console.warn afplay spawn failure log; not UI. |
| 3655 | title: "Export Omnigent Desktop Diagnostics", | change | S87 | Save dialog title 'Export Omnigent Desktop Diagnostics' shown to users. |
| 3656 | defaultPath: ˋOmnigent-desktop-diagnostics-${new Date().toISOString().slice(0, 10)}.jsonlˋ, | change | S87 | Default diagnostics file name shown in save dialog; only referenced here, not parsed elsewhere. |
| 3668 | message: "Omnigent could not save the desktop diagnostics.", | change | S87 | Error dialog message 'Omnigent could not save the desktop diagnostics' shown to users. |
| 3679 | const aboutItem = aboutMenuItem("Omnigent", () => { | change | S87 | About menu item label becomes 'About Omnigent'; user-visible menu label. |
| 3706 | title: "Omnigent", | change | S87 | 'No update is ready to install' dialog title shows product name. |
| 3843 | // omnigent:set-server-selector-v2 IPC… | keep-internal |  | code comment |
| 4043 | …dge (window.omnigentDesktop) forwards … | keep-internal |  | code comment |
| 4131 | // ˋomnigent:browser-executeˋ runs JS … | keep-internal |  | code comment |
| 4187 | !databricksInternalFeaturesEnabled() | keep-internal |  | code identifier |
| 4193 | !isDatabricksManagedServerUrl(windows.… | keep-internal |  | code identifier |
| 4194 | !isDatabricksManagedServerUrl(target) … | keep-internal |  | code identifier |
| 4238 | …sole.warn("[omnigent] Arca preview rec… | keep-internal |  | console.warn Arca preview recovery log; not UI. |
| 4243 | …sole.warn(ˋ[omnigent] Arca preview rec… | keep-internal |  | console.warn Arca preview recovery failure log; |
| 4291 | enabled: databricksInternalFeaturesEna… | keep-internal |  | code identifier |
| 4293 | isDatabricksManagedServerUrl(windows.g… | keep-internal |  | code identifier |
| 4294 | isDatabricksManagedServerUrl(target), | keep-internal |  | code identifier |
| 4419 | ˋ[omnigent] databricks workspace picke… | keep-internal |  | console.log databricks workspace picker debug ou |
| 4429 | …ain.handle("omnigent:cancel-server-con… | keep-internal |  | IPC handler channel omnigent:cancel-server-conne |
| 4445 | …ain.handle("omnigent:set-server-url", … | keep-internal |  | IPC handler channel omnigent:set-server-url; int |
| 4512 | …ain.handle("omnigent:get-server-url", … | keep-internal |  | IPC handler channel omnigent:get-server-url; int |
| 4526 | …ain.handle("omnigent:get-recent-server… | keep-internal |  | IPC handler channel omnigent:get-recent-servers; |
| 4536 | …ain.handle("omnigent:forget-recent-ser… | keep-internal |  | IPC handler channel omnigent:forget-recent-serve |
| 4564 | …oks like an Omnigent server (has the m… | keep-internal |  | code comment |
| 4567 | …ain.handle("omnigent:check-server", as… | keep-internal |  | IPC handler channel omnigent:check-server; inter |
| 4577 | …nitively an Omnigent server. | keep-internal |  | code comment |
| 4595 | …ain.handle("omnigent:set-server-select… | keep-internal |  | IPC handler channel omnigent:set-server-selector |
| 4610 | …ain.handle("omnigent:get-managed-serve… | keep-internal |  | IPC handler channel omnigent:get-managed-servers |
| 4618 | …ain.handle("omnigent:get-server-names"… | keep-internal |  | IPC handler channel omnigent:get-server-names; i |
| 4626 | …ain.handle("omnigent:get-managed-serve… | keep-internal |  | IPC handler channel omnigent:get-managed-server- |
| 4637 | …ain.handle("omnigent:get-setup-capabil… | keep-internal |  | IPC handler channel omnigent:get-setup-capabilit |
| 4649 | …ngs its own Omnigent, so onboarding sk… | keep-internal |  | code comment |
| 4650 | …ain.handle("omnigent:get-runner-option… | keep-internal |  | 'omnigent:' IPC channel name shared with the pre |
| 4656 | databricksInternalFeaturesEnabled() && | keep-internal |  | code identifier |
| 4657 | isDatabricksManagedServerUrl(url); | keep-internal |  | code identifier |
| 4664 | …ain.handle("omnigent:connect-runner", … | keep-internal |  | 'omnigent:' IPC channel name shared with the pre |
| 4675 | …ender.send("omnigent:runner-connect-lo… | keep-internal |  | 'omnigent:' IPC event channel name sent to the s |
| 4681 | if (!databricksInternalFeaturesEnabled… | keep-internal |  | code identifier |
| 4697 | log(ˋ$ ${omnigentCli.cliCommandParts(c… | keep-internal |  | omnigentCli is a JS module identifier; the shown |
| 4721 | …ain.handle("omnigent:copy-setup-text",… | keep-internal |  | 'omnigent:' IPC channel name |
| 4735 | …ain.handle("omnigent:get-server-picker… | keep-internal |  | 'omnigent:' IPC channel name |
| 4737 | …sole.warn("[omnigent] get-server-picke… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 4774 | …ain.handle("omnigent:sign-out-of-serve… | keep-internal |  | 'omnigent:' IPC channel name |
| 4785 | …ain.handle("omnigent:switch-server", (… | keep-internal |  | 'omnigent:' IPC channel name |
| 4820 | ipcMain.on("omnigent:open-server-setup… | keep-internal |  | 'omnigent:' IPC channel name |
| 4822 | …sole.warn("[omnigent] open-server-setu… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 4840 | ipcMain.on("omnigent:find-query", (eve… | keep-internal |  | 'omnigent:' IPC channel name |
| 4842 | …sole.warn("[omnigent] find-query from … | keep-internal |  | console.warn debug output tag, not shown in UI |
| 4850 | …ender.send("omnigent:find-result", { a… | keep-internal |  | 'omnigent:' IPC event channel name |
| 4861 | ipcMain.on("omnigent:find-close", (eve… | keep-internal |  | 'omnigent:' IPC channel name |
| 4863 | …sole.warn("[omnigent] find-close from … | keep-internal |  | console.warn debug output tag, not shown in UI |
| 4872 | ipcMain.on("omnigent:set-desktop-comma… | keep-internal |  | 'omnigent:' IPC channel name |
| 4880 | …ain.handle("omnigent:close-window", (e… | keep-internal |  | 'omnigent:' IPC channel name |
| 4887 | …ain.handle("omnigent:confirm-quit", (e… | keep-internal |  | 'omnigent:' IPC channel name |
| 4893 | …ngs → "Show Omnigent from anywhere" (o… | keep-internal |  | code comment |
| 4894 | …ain.handle("omnigent:get-global-shortc… | keep-internal |  | 'omnigent:' IPC channel name |
| 4900 | …ain.handle("omnigent:set-global-shortc… | keep-internal |  | 'omnigent:' IPC channel name |
| 4910 | …ain.handle("omnigent:record-global-sho… | keep-internal |  | 'omnigent:' IPC channel name |
| 4916 | …ain.handle("omnigent:cancel-global-sho… | keep-internal |  | 'omnigent:' IPC channel name |
| 4925 | ipcMain.on("omnigent:set-badge-count",… | keep-internal |  | 'omnigent:' IPC channel name |
| 4927 | …sole.warn("[omnigent] set-badge-count … | keep-internal |  | console.warn debug output tag, not shown in UI |
| 4947 | …ain.handle("omnigent:notify", (event, … | keep-internal |  | 'omnigent:' IPC channel name |
| 4951 | …sole.warn("[omnigent] notify from untr… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 4993 | …ender.send("omnigent:notification-acti… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5022 | …e → is the ˋomnigentˋ CLI installed an… | keep-internal |  | code comment |
| 5024 | …ain.handle("omnigent:get-cli-status", … | keep-internal |  | 'omnigent:' IPC channel name |
| 5030 | omnigentCli.getCliStatus(loadSettings(… | keep-internal |  | code identifier |
| 5031 | omnigentCli.localServerHealthy(), | keep-internal |  | code identifier |
| 5035 | …onDisabled: databricksInternalFeatures… | keep-internal |  | code identifier |
| 5039 | …" vs "Start Omnigent" matches it. | keep-internal |  | code comment |
| 5044 | …ath to the ˋomnigentˋ binary. Persiste… | keep-internal |  | code comment |
| 5045 | … a runnable omnigent (so a typo doesn'… | keep-internal |  | code comment |
| 5048 | …ain.handle("omnigent:set-cli-path", as… | keep-internal |  | 'omnigent:' IPC channel name |
| 5052 | if (databricksInternalFeaturesEnabled(… | keep-internal |  | code identifier |
| 5054 | ...(await omnigentCli.getCliStatus(loa… | keep-internal |  | code identifier |
| 5062 | …ker for the omnigent binary. Returns t… | keep-internal |  | code comment |
| 5064 | …ain.handle("omnigent:browse-cli-path",… | keep-internal |  | 'omnigent:' IPC channel name |
| 5068 | if (databricksInternalFeaturesEnabled(… | keep-internal |  | code identifier |
| 5071 | title: "Locate the Omnigent CLI binary", | keep-deferred |  | File-picker title names the omnigent CLI binary; changes with the CLI rename (OPS-03/FND-01) |
| 5080 | …ain.handle("omnigent:start-local-serve… | keep-internal |  | 'omnigent:' IPC channel name |
| 5086 | const errorMessage = "The omnigent CLI was not found."; | keep-deferred |  | Setup-page error names the omnigent CLI binary; changes with the CLI rename (OPS-03/FND-01) |
| 5093 | …ender.send("omnigent:local-server-setu… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5101 | …install the omnigent CLI (macOS). Runs… | keep-internal |  | code comment |
| 5107 | …ain.handle("omnigent:cli-install", asy… | keep-internal |  | 'omnigent:' IPC channel name |
| 5114 | …ender.send("omnigent:cli-install-log",… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5121 | …tus = await omnigentCli.getCliStatus(l… | keep-internal |  | code identifier |
| 5133 | …stId: () => omnigentCli.localHostId(), | keep-internal |  | code identifier |
| 5144 | …config (no ˋomnigent host statusˋ subp… | keep-internal |  | code comment |
| 5147 | …ain.handle("omnigent:host-get-identity… | keep-internal |  | 'omnigent:' IPC channel name |
| 5149 | …sole.warn("[omnigent] host-get-identit… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 5154 | hostId: omnigentCli.localHostId(), | keep-internal |  | code identifier |
| 5160 | …ain.handle("omnigent:take-onboarding-r… | keep-internal |  | 'omnigent:' IPC channel name |
| 5176 | …ain.handle("omnigent:cli-get-status", … | keep-internal |  | 'omnigent:' IPC channel name |
| 5178 | …sole.warn("[omnigent] cli-get-status f… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 5182 | ...(await omnigentCli.getCliStatus(loa… | keep-internal |  | code identifier |
| 5183 | …onDisabled: databricksInternalFeatures… | keep-internal |  | code identifier |
| 5193 | …ain.handle("omnigent:cli-reset-path", … | keep-internal |  | 'omnigent:' IPC channel name |
| 5197 | if (databricksInternalFeaturesEnabled(… | keep-internal |  | code identifier |
| 5199 | ...(await omnigentCli.getCliStatus(loa… | keep-internal |  | code identifier |
| 5220 | ipcMain.on("omnigent:set-color-scheme"… | keep-internal |  | 'omnigent:' IPC channel name |
| 5236 | …ain.handle("omnigent:setup-get-color-s… | keep-internal |  | 'omnigent:' IPC channel name |
| 5244 | ipcMain.on("omnigent:setup-set-color-s… | keep-internal |  | 'omnigent:' IPC channel name |
| 5248 | …ender.send("omnigent:setup-theme", nat… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5260 | wc.send("omnigent:setup-theme", theme)… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5267 | …ain.handle("omnigent:host-control", as… | keep-internal |  | 'omnigent:' IPC channel name |
| 5305 | …MDM-managed Databricks-internal flag (… | keep-internal |  | code comment |
| 5306 | …n server is Databricks-managed | keep-internal |  | code comment |
| 5307 | … mount or a Databricks App) — internal… | keep-internal |  | code comment |
| 5311 | databricksInternalFeaturesEnabled() &&… | keep-internal |  | code identifier |
| 5313 | …ain.handle("omnigent:get-desktop-featu… | keep-internal |  | 'omnigent:' IPC channel name |
| 5315 | …sole.warn("[omnigent] get-desktop-feat… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 5320 | databricksInternalFeatures: enabled, | keep-internal |  | code identifier |
| 5332 | …ain.handle("omnigent:ssh-connect", asy… | keep-internal |  | 'omnigent:' IPC channel name |
| 5343 | if (databricksInternalFeaturesEnabled(… | keep-internal |  | code identifier |
| 5357 | …t} runs this server itself, run "omnigent host" there.ˋ, | keep-deferred |  | Error text tells the user to run the "omnigent host" CLI command; changes with the CLI rename (OPS-03/FND-01) |
| 5363 | …a instance (Databricks-internal sandbo… | keep-internal |  | code comment |
| 5373 | …ain.handle("omnigent:arca-connect", as… | keep-internal |  | 'omnigent:' IPC channel name |
| 5377 | if (!databricksInternalFeaturesEnabled… | keep-internal |  | code identifier |
| 5383 | …d against a Databricks-managed server. | keep-internal |  | code comment |
| 5384 | if (!isDatabricksManagedServerUrl(serv… | keep-internal |  | code identifier |
| 5385 | return { ok: false, error: "Arca hosts can only connect to Databricks-managed servers." }; | keep-origin |  | Names Databricks-managed servers, the third-party platform the internal Arca integration targets, not Coral's publisher |
| 5390 | if (!isDatabricksManagedServerUrl(arca… | keep-internal |  | code identifier |
| 5391 | return { ok: false, error: "Arca hosts can only connect to Databricks-managed servers." }; | keep-origin |  | Names Databricks-managed servers, the third-party platform the internal Arca integration targets, not Coral's publisher |
| 5419 | …ain.handle("omnigent:arca-extend", asy… | keep-internal |  | 'omnigent:' IPC channel name |
| 5444 | …ain.handle("omnigent:dbcert-refresh", … | keep-internal |  | 'omnigent:' IPC channel name |
| 5490 | …ain.handle("omnigent:dbcert-check", as… | keep-internal |  | 'omnigent:' IPC channel name |
| 5505 | …pane — the ˋomnigent:browser-*ˋ surfac… | keep-internal |  | code comment |
| 5561 | …sole.warn(ˋ[omnigent] Arca preview rec… | keep-internal |  | console.warn debug output tag, not shown in UI |
| 5592 | return "Finish the Arca reconnect in Omnigent, then retry the preview."; | change | S87 | Navigation-error hint uses Omnigent as the app name; browserIpc appends it to the error returned to the agent/user |
| 5594 | return "Omnigent couldn't restore the Arca connection details. Retry the preview to reconnect."; | change | S87 | Navigation-error hint uses Omnigent as the app name, shown as an error |
| 5600 | …eep links (ˋomnigent://<hostname>/c/<s… | keep-internal |  | code comment |
| 5602 | …OS-clicked ˋomnigent://ˋ URL opens the… | keep-internal |  | code comment |
| 5621 | …space.cloud.databricks.com"ˋˋ. | keep-internal |  | code comment |
| 5728 | …tents.send("omnigent:desktop-command",… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5829 | …nsole.log(ˋ[omnigent] send open-path $… | keep-internal |  | console.log debug output tag, not shown in UI |
| 5831 | …tents.send("omnigent:open-path", route… | keep-internal |  | 'omnigent:' IPC event channel name |
| 5862 | title: "Omnigent", | change | S87 | Title of the deep-link confirm dialog shows the product name |
| 5863 | message: ˋOpen this Omnigent link?ˋ, | change | S87 | Message of the deep-link confirm dialog shows the product name |
| 5865 | ˋThis link will connect Omnigent to ${host}.\n\nˋ + | change | S87 | Detail text of the deep-link confirm dialog shows the product name |
| 5882 | …links (parseOmnigentDeepLink | keep-internal |  | code comment |
| 5890 | if (!parseOmnigentDeepLink(raw)) { | keep-internal |  | code identifier |
| 5891 | …nsole.log("[omnigent] deep-link: ignor… | keep-internal |  | console.log debug output tag, not shown in UI |
| 5894 | …nsole.log(ˋ[omnigent] deep-link: queue… | keep-internal |  | console.log debug output tag, not shown in UI |
| 5912 | …sole.warn("[omnigent] deep-link handli… | keep-internal |  | console.warn log prefix "[omnigent]" for deep-li |
| 5925 | * Open an ˋomnigent://ˋ deep link on t… | keep-internal |  | code comment |
| 5934 | * (expandDatabricksWorkspaceUrl) runs … | keep-internal |  | code comment |
| 5937 | …d a path (ˋ/omnigentˋ) | keep-internal |  | code comment |
| 5940 | …aw The raw ˋomnigent://...ˋ URL. | keep-internal |  | code comment |
| 5944 | …rsed = parseOmnigentDeepLink(raw); | keep-internal |  | code identifier |
| 5948 | …sion. expandDatabricksWorkspaceUrl onl… | keep-internal |  | code comment |
| 5952 | …ttps://host/omnigentˋ) so we SKIP the … | keep-internal |  | code comment |
| 5970 | ˋ[omnigent] deep-link: strategy=${deci… | keep-internal |  | console.log debug prefix "[omnigent] deep-link: |
| 6008 | …await expandDatabricksWorkspaceUrl(tar… | keep-internal |  | code identifier |
| 6031 | app.setName(isDevBuild ? "Omnigent Dev" : "Omnigent"); | change | S87 | app.setName drives the macOS app menu title and notification source name shown to users. |
| 6033 | const devData = path.join(app.getPath("appData"), "Omnigent Dev"); | change-identity | S87 | Dev userData folder name derives from the dev product name; follows DEV_PRODUCT_NAME. |
| 6044 | // omnigent:// URL as a command-line a… | keep-internal |  | code comment |
| 6049 | …m start -- 'omnigent://...'ˋ exercise … | keep-internal |  | code comment |
| 6050 | …unch has no omnigent:// in argv, so no… | keep-internal |  | code comment |
| 6052 | if (typeof arg === "string" && arg.startsWith("omnigent://")) enqueueDeepLink(arg); | change-identity | S38 | Cold-start argv check for the registered deep-link scheme; must follow the new coral:// scheme. |
| 6055 | …ˋ fires for omnigent:// links, includi… | keep-internal |  | code comment |
| 6067 | // omnigent:// URL on its command line… | keep-internal |  | code comment |
| 6069 | …m start -- 'omnigent://...'ˋ reaches t… | keep-internal |  | code comment |
| 6074 | if (typeof arg === "string" && arg.startsWith("omnigent://")) { | change-identity | S38 | second-instance argv check for the deep-link scheme; must follow the coral:// scheme. |
| 6092 | app.setAppUserModelId(isDevBuild ? DEV_DOMAIN : "ai.omnigent.desktop"); | change-identity | S87 | Windows App User Model ID must match the new desktop app id (io.github.coral-hq.coral / -dev). |
| 6116 | …egister the omnigent:// scheme so OS c… | keep-internal |  | code comment |
| 6121 | app.setAsDefaultProtocolClient("omnigent"); | change-identity | S38 | Registers the OS deep-link URL scheme; becomes coral per the new scheme. |
| 6160 | …s (a stuck ˋomnigent server stopˋ), th… | keep-internal |  | code comment |
| 6164 | …d a normal ˋomnigent server stopˋ is s… | keep-internal |  | code comment |
| 6168 | … reuses or ˋomnigent server stopˋ recl… | keep-internal |  | code comment |
| 6201 | …hin 4s and ˋomnigent server stopˋ has … | keep-internal |  | code comment |

### `web/electron/src/managed_preferences.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …y in the ai.omnigent.desktop domain. *… | keep-internal |  | code comment |
| 7 | …ME_PARAM = "omnigentServerName"; | keep-internal |  | MDM config key omnigentServerName is parsed from |
| 10 | … key gating Databricks-internal featur… | keep-internal |  | code comment |
| 13 | const DATABRICKS_INTERNAL_FEATURES_KEY… | keep-internal |  | Managed Preferences config key gating Databricks |
| 123 | * Read the Databricks-internal-feature… | keep-internal |  | code comment |
| 134 | function getDatabricksInternalFeatures… | keep-internal |  | code identifier |
| 140 | …UserDefault(DATABRICKS_INTERNAL_FEATUR… | keep-internal |  | code identifier |
| 167 | DATABRICKS_INTERNAL_FEATURES_KEY, | keep-internal |  | code identifier |
| 172 | getDatabricksInternalFeaturesEnabled, | keep-internal |  | code identifier |

### `web/electron/src/oidc-auth.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 290 | …nsole.log("[omnigent] oidc auth: silen… | keep-internal |  | console.log prefix "[omnigent] oidc auth: silent |
| 303 | …sole.warn("[omnigent] oidc auth: recov… | keep-internal |  | console.warn log prefix; not shown in UI. |
| 319 | …sole.warn("[omnigent] oidc auth: backg… | keep-internal |  | console.warn log prefix for background renewal f |
| 363 | …nsole.log("[omnigent] oidc auth: signi… | keep-internal |  | console.log log prefix for sign-out; log only. |
| 373 | …sole.warn("[omnigent] oidc auth: could… | keep-internal |  | console.warn log prefix; log only. |
| 382 | …sole.warn("[omnigent] oidc auth: could… | keep-internal |  | console.warn log prefix; log only. |

### `web/electron/src/oidc-credentials.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | …ttps://host/omnigent/ˋ → ˋhttps://host… | keep-internal |  | code comment |
| 115 | …nsole.log("[omnigent] oidc sign-in: op… | keep-internal |  | console.log log prefix in onOpened callback; log |
| 119 | "Return to Omnigent to finish connecting, then close this tab.", | change | S87 | Loopback OAuth result page shown in the user's browser names the app as Omnigent. |
| 123 | "Close this tab and try connecting again in Omnigent.", | change | S87 | Failed sign-in browser page names the app as Omnigent; user-visible. |
| 127 | "Close this tab and try connecting again in Omnigent.", | change | S87 | Incomplete sign-in browser page names the app as Omnigent; user-visible. |
| 174 | …nsole.log("[omnigent] oidc sign-in: si… | keep-internal |  | console.log log prefix "[omnigent] oidc sign-in: |
| 248 | ˋ[omnigent] oidc sign-out: revoking th… | keep-internal |  | console.warn log prefix for grant revocation sta |
| 252 | …sole.warn(ˋ[omnigent] oidc sign-out: c… | keep-internal |  | console.warn log prefix for grant revocation fai |

### `web/electron/src/omnigent_cli.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | … the local ˋomnigentˋ CLI for the desk… | keep-internal |  | code comment |
| 3 | …o the same ˋomnigentˋ binary a | keep-internal |  | code comment |
| 15 | // test/omnigent_cli.test.js, as is ru… | keep-internal |  | code comment |
| 40 | …ttps://raw.githubusercontent.com/omnigent-ai/omnigent/main/scripts/install_oss.sh \| sh"; | change | S87 | Changed with its seam: Install command (omnigent install_oss.sh) shown on the setup page. OPS-09 changes it; it moves to brand.js INSTALL_CO |
| 94 | * The Omnigent local runtime data dir … | keep-internal |  | code comment |
| 95 | …ded) or ˋ~/.omnigentˋ. Mirrors ˋ_local… | keep-internal |  | code comment |
| 96 | * omnigent/host/local_server.py. The l… | keep-internal |  | code comment |
| 101 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | code identifier |
| 106 | …omedir(), ".omnigent"); | keep-internal |  | ~/.omnigent data dir path, mirrors the CLI's _lo |
| 110 | * The Omnigent config dir — ˋ$OMNIGENT… | keep-internal |  | code comment |
| 111 | * ˋ~/.omnigentˋ. config.yaml (machine … | keep-internal |  | code comment |
| 117 | …process.env.OMNIGENT_CONFIG_HOME; | keep-internal |  | code identifier |
| 122 | …omedir(), ".omnigent"); | keep-internal |  | ~/.omnigent config dir path (OMNIGENT_CONFIG_HOM |
| 126 | … The shared Omnigent state dir, ALWAYS… | keep-internal |  | code comment |
| 127 | * ˋ$OMNIGENT_DATA_DIRˋ, mirroring ˋsta… | keep-internal |  | code comment |
| 128 | * sdks/ui/omnigent_ui_sdk/terminal/_co… | keep-internal |  | code comment |
| 129 | * omnigent/cli.py (both hardcode ˋPath… | keep-internal |  | code comment |
| 131 | …le honors ˋ$OMNIGENT_DATA_DIRˋ (see {@… | keep-internal |  | code comment |
| 136 | …omedir(), ".omnigent"); | keep-internal |  | ~/.omnigent state dir (auth_tokens.json, daemon |
| 143 | …s machine's Omnigent host id (bare 32-… | keep-internal |  | code comment |
| 145 | * omnigent/host/identity.py) — instant… | keep-internal |  | code comment |
| 154 | …host_idˋ in omnigent/host/identity.py. | keep-internal |  | code comment |
| 179 | * omnigent/host/local_server.py. | keep-internal |  | code comment |
| 228 | …check — no ˋomnigent | keep-internal |  | code comment |
| 250 | * omnigent/host/local_server.py. Retur… | keep-internal |  | code comment |
| 273 | * point (ˋomnigent.cli:mainˋ); ˋomniˋ is the short alias. We probe ˋomnigentˋ | change | S87 | Changed with its seam: code comment |
| 277 | const CLI_NAMES = ["omnigent", "omni"]; | change-identity | S87 | CLI_NAMES detection list gains coral (keeping omnigent/omni) so a future coral CLI binary is found. |
| 281 | …e list the ˋomnigentˋ name then the ˋo… | keep-internal |  | code comment |
| 321 | … name e.g. "omnigent" or "omni" | keep-internal |  | code comment |
| 340 | …TH, trying ˋomnigentˋ then the ˋomniˋ … | keep-internal |  | code comment |
| 345 | function whichOmnigent() { | keep-internal |  | code identifier |
| 354 | …Locate the ˋomnigentˋ binary. Resoluti… | keep-internal |  | code comment |
| 361 | …th settings.omnigent_path | keep-internal |  | code comment |
| 364 | *   whichOmnigent?: () => string \| nul… | keep-internal |  | code comment |
| 371 | …= deps.whichOmnigent \|\| whichOmnigent; | keep-internal |  | code identifier |
| 390 | …ing (ˋ/path/omnigentˋ); | keep-internal |  | code comment |
| 391 | * Databricks-internal host enrollment … | keep-internal |  | code comment |
| 403 | return { executable: command, prefixArgs: [], displayName: "omnigent" }; | keep-deferred |  | displayName "omnigent" names the CLI binary in sign-in error text (ˋomnigent loginˋ). OPS-03/FND-01 renames the CLI. |
| 470 | * Run an Omnigent CLI subcommand and r… | keep-internal |  | code comment |
| 502 | * from ˋ~/.omnigent/auth_tokens.jsonˋ … | keep-internal |  | code comment |
| 503 | * omnigent/cli_auth.py: keyed by the t… | keep-internal |  | code comment |
| 504 | …d if it's a Databricks pointer (has ˋw… | keep-internal |  | code comment |
| 505 | …oded to ˋ~/.omnigentˋ. | keep-internal |  | code comment |
| 521 | …h_type === "databricks") { | keep-internal |  | auth_type "databricks" is a value the CLI persis |
| 533 | * Run ˋomnigent login <serverUrl>ˋ to … | keep-internal |  | code comment |
| 535 | … for OIDC / Databricks, and fails fast… | keep-internal |  | code comment |
| 538 | …SECONDSˋ in omnigent/cli.py) | keep-internal |  | code comment |
| 610 | … as omni — ˋomnigent --versionˋ prints | keep-internal |  | code comment |
| 611 | // e.g. "omnigent 0.3.0.dev0 (…)". The… | keep-internal |  | code comment |
| 625 | * ˋomnigent server status --jsonˋ. Ret… | keep-internal |  | code comment |
| 749 | … stop (its ˋomnigent server --backgrou… | keep-internal |  | code comment |
| 885 | …y_dir()ˋ in omnigent/cli.py (ˋ<state_d… | keep-internal |  | code comment |
| 895 | …om_json()ˋ (omnigent/cli.py): a usable | keep-internal |  | code comment |
| 935 | …m disk (ˋ~/.omnigent/daemons/*.jsonˋ). | keep-internal |  | code comment |
| 936 | …titute for ˋomnigent host status --jso… | keep-internal |  | code comment |
| 967 | * The Omnigent server URL a daemon rec… | keep-internal |  | code comment |
| 968 | …ase_url()ˋ (omnigent/cli.py): a local-… | keep-internal |  | code comment |
| 986 | … stored by ˋomnigent loginˋ in ˋauth_t… | keep-internal |  | code comment |
| 987 | … null for a Databricks-pointer login | keep-internal |  | code comment |
| 991 | …headers()ˋ (omnigent/chat.py), this de… | keep-internal |  | code comment |
| 992 | * honor ˋOMNIGENT_REMOTE_AUTH_TOKENˋ. … | keep-internal |  | code comment |
| 996 | * ˋ~/.omnigent/daemons/ˋ. The desktop … | keep-internal |  | code comment |
| 999 | …r for SDK / Databricks-pointer auth. | keep-internal |  | code comment |
| 1022 | const OMNIGENT_SLICE_KEY_HEADER = "X-D… | keep-internal |  | X-Databricks-Omnigent-Slice-Key is a protocol he |
| 1023 | …= "/api/2.0/omnigent"; | keep-internal |  | /api/2.0/omnigent is the workspace API mount pat |
| 1027 | * rule as ˋdatabricks_request_headers(… | keep-internal |  | code comment |
| 1029 | * ˋOMNIGENT_HOST_SLICE_KEY_ENABLED=1ˋ,… | keep-internal |  | code comment |
| 1035 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | code identifier |
| 1048 | …_status()ˋ (omnigent/cli.py) makes, mi… | keep-internal |  | code comment |
| 1051 | …-process (a Databricks-pointer login, … | keep-internal |  | code comment |
| 1068 | // Databricks-pointer login mints toke… | keep-internal |  | code comment |
| 1075 | …l)) headers[OMNIGENT_SLICE_KEY_HEADER]… | keep-internal |  | code identifier |
| 1094 | * Databricks-edge 302 to the workspace… | keep-internal |  | code comment |
| 1095 | …ng ˋ_ensure_databricks_server_auth()ˋ … | keep-internal |  | code comment |
| 1096 | * omnigent/cli.py, so the desktop and … | keep-internal |  | code comment |
| 1100 | * ˋomnigent loginˋ. A Databricks-point… | keep-internal |  | code comment |
| 1102 | … defers to ˋomnigent loginˋ, itself br… | keep-internal |  | code comment |
| 1105 | …nual"ˋ so a Databricks 302 is never fo… | keep-internal |  | code comment |
| 1138 | …T the slow ˋomnigent | keep-internal |  | code comment |
| 1143 | …obed — e.g. Databricks-pointer auth — … | keep-internal |  | code comment |
| 1193 | …t reproduce Databricks-pointer auth in… | keep-internal |  | code comment |
| 1250 | whichOmnigent, | keep-internal |  | code identifier |

### `web/electron/src/popup_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …d.js, whose omnigentDesktop/omnigentSe… | keep-internal |  | code comment |

### `web/electron/src/preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …  1. window.omnigentDesktop — read by … | keep-internal |  | code comment |
| 9 | …  2. window.omnigentSetup — used only … | keep-internal |  | code comment |
| 23 | "--omnigent-electron-zoom", | keep-internal |  | CSS custom property set on documentElement, read |
| 52 | …nMainWorld("omnigentDesktop", { | keep-internal |  | Preload bridge name window.omnigentDesktop read |
| 56 | …derer.send("omnigent:set-badge-count",… | keep-internal |  | IPC channel omnigent:set-badge-count shared with |
| 63 | …rer.invoke("omnigent:notify", { | keep-internal |  | IPC channel omnigent:notify shared with main pro |
| 82 | …enderer.on("omnigent:notification-acti… | keep-internal |  | IPC channel omnigent:notification-activated shar |
| 83 | …veListener("omnigent:notification-acti… | keep-internal |  | IPC channel omnigent:notification-activated shar |
| 99 | …enderer.on("omnigent:open-path", liste… | keep-internal |  | IPC channel omnigent:open-path shared with main |
| 100 | …veListener("omnigent:open-path", liste… | keep-internal |  | IPC channel omnigent:open-path shared with main |
| 111 | …enderer.on("omnigent:find-opened", lis… | keep-internal |  | IPC channel omnigent:find-opened shared with mai |
| 112 | …veListener("omnigent:find-opened", lis… | keep-internal |  | IPC channel omnigent:find-opened shared with mai |
| 132 | …enderer.on("omnigent:desktop-command",… | keep-internal |  | IPC channel omnigent:desktop-command shared with |
| 133 | …veListener("omnigent:desktop-command",… | keep-internal |  | IPC channel omnigent:desktop-command shared with |
| 142 | …derer.send("omnigent:set-desktop-comma… | keep-internal |  | IPC channel omnigent:set-desktop-command-state s |
| 149 | …rer.invoke("omnigent:close-window"), | keep-internal |  | IPC channel omnigent:close-window shared with ma |
| 152 | …rer.invoke("omnigent:confirm-quit", { … | keep-internal |  | IPC channel omnigent:confirm-quit shared with ma |
| 153 | …* The "Show Omnigent from anywhere" sh… | keep-internal |  | code comment |
| 154 | …rer.invoke("omnigent:get-global-shortc… | keep-internal |  | IPC channel omnigent:get-global-shortcut shared |
| 162 | "omnigent:set-global-shortcut", | keep-internal |  | IPC channel omnigent:set-global-shortcut shared |
| 171 | …rer.invoke("omnigent:record-global-sho… | keep-internal |  | IPC channel omnigent:record-global-shortcut shar |
| 173 | …rer.invoke("omnigent:cancel-global-sho… | keep-internal |  | IPC channel omnigent:cancel-global-shortcut-reco |
| 176 | …rer.invoke("omnigent:take-onboarding-r… | keep-internal |  | IPC channel omnigent:take-onboarding-runner shar |
| 181 | …rer.invoke("omnigent:get-server-picker… | keep-internal |  | IPC channel omnigent:get-server-picker shared wi |
| 186 | …rer.invoke("omnigent:switch-server", u… | keep-internal |  | IPC channel omnigent:switch-server shared with m |
| 188 | …rer.invoke("omnigent:sign-out-of-serve… | keep-internal |  | IPC channel omnigent:sign-out-of-server shared w |
| 191 | …derer.send("omnigent:open-server-setup… | keep-internal |  | IPC channel omnigent:open-server-setup shared wi |
| 194 | …rer.invoke("omnigent:reveal-file", hos… | keep-internal |  | IPC channel omnigent:reveal-file shared with mai |
| 196 | …rer.invoke("omnigent:choose-directory"… | keep-internal |  | IPC channel omnigent:choose-directory shared wit |
| 202 | …rer.invoke("omnigent:dropped-file-path… | keep-internal |  | IPC channel omnigent:dropped-file-path shared wi |
| 208 | …rer.invoke("omnigent:host-get-identity… | keep-internal |  | IPC channel omnigent:host-get-identity shared wi |
| 214 | …rer.invoke("omnigent:host-control", ac… | keep-internal |  | IPC channel omnigent:host-control shared with ma |
| 217 | * ˋ{ databricksInternalFeatures }ˋ fro… | keep-internal |  | code comment |
| 218 | …rue only on Databricks-managed servers… | keep-internal |  | code comment |
| 221 | …rer.invoke("omnigent:get-desktop-featu… | keep-internal |  | IPC channel omnigent:get-desktop-features shared |
| 223 | …a instance (Databricks-internal) to th… | keep-internal |  | code comment |
| 227 | …rer.invoke("omnigent:arca-connect"), | keep-internal |  | IPC channel omnigent:arca-connect shared with ma |
| 237 | …rer.invoke("omnigent:ssh-connect", des… | keep-internal |  | IPC channel omnigent:ssh-connect shared with mai |
| 240 | …rer.invoke("omnigent:arca-extend", mod… | keep-internal |  | IPC channel omnigent:arca-extend shared with mai |
| 242 | …e's dbcert (Databricks-internal); Arca… | keep-internal |  | code comment |
| 245 | …rer.invoke("omnigent:dbcert-refresh", … | keep-internal |  | IPC channel omnigent:dbcert-refresh shared with |
| 247 | …rer.invoke("omnigent:dbcert-check"), | keep-internal |  | IPC channel omnigent:dbcert-check shared with ma |
| 259 | …enderer.on("omnigent:host-status-chang… | keep-internal |  | IPC channel omnigent:host-status-changed shared |
| 260 | …veListener("omnigent:host-status-chang… | keep-internal |  | IPC channel omnigent:host-status-changed shared |
| 267 | …rer.invoke("omnigent:cli-get-status"), | keep-internal |  | IPC channel omnigent:cli-get-status shared with |
| 273 | …rer.invoke("omnigent:cli-reset-path"), | keep-internal |  | IPC channel omnigent:cli-reset-path shared with |
| 286 | …rer.invoke("omnigent:get-update-config… | keep-internal |  | IPC channel omnigent:get-update-config shared wi |
| 287 | …rer.invoke("omnigent:get-update-status… | keep-internal |  | IPC channel omnigent:get-update-status shared wi |
| 288 | …rer.invoke("omnigent:update-check"), | keep-internal |  | IPC channel omnigent:update-check shared with ma |
| 289 | …rer.invoke("omnigent:update-download")… | keep-internal |  | IPC channel omnigent:update-download shared with |
| 290 | …rer.invoke("omnigent:update-install"), | keep-internal |  | IPC channel omnigent:update-install shared with |
| 291 | …rer.invoke("omnigent:set-update-config… | keep-internal |  | IPC channel omnigent:set-update-config shared wi |
| 294 | …enderer.on("omnigent:update-status", l… | keep-internal |  | IPC channel omnigent:update-status shared with m |
| 295 | …veListener("omnigent:update-status", l… | keep-internal |  | IPC channel omnigent:update-status shared with m |
| 298 | …rer.invoke("omnigent:get-update-overla… | keep-internal |  | IPC channel omnigent:get-update-overlay-height s |
| 305 | …enderer.on("omnigent:update-overlay-he… | keep-internal |  | IPC channel omnigent:update-overlay-height share |
| 306 | …veListener("omnigent:update-overlay-he… | keep-internal |  | IPC channel omnigent:update-overlay-height share |
| 315 | …derer.send("omnigent:set-color-scheme"… | keep-internal |  | IPC channel omnigent:set-color-scheme shared wit |
| 333 | …rer.invoke("omnigent:browser-open-or-n… | keep-internal |  | IPC channel omnigent:browser-open-or-navigate sh |
| 340 | …rer.invoke("omnigent:browser-set-activ… | keep-internal |  | IPC channel omnigent:browser-set-active shared w |
| 345 | …rer.invoke("omnigent:browser-focused-v… | keep-internal |  | IPC channel omnigent:browser-focused-view shared |
| 352 | …rer.invoke("omnigent:browser-set-suppr… | keep-internal |  | IPC channel omnigent:browser-set-suppressed shar |
| 359 | …rer.invoke("omnigent:browser-resize", … | keep-internal |  | IPC channel omnigent:browser-resize shared with |
| 366 | …rer.invoke("omnigent:browser-screensho… | keep-internal |  | IPC channel omnigent:browser-screenshot shared w |
| 369 | …rer.invoke("omnigent:browser-perform-a… | keep-internal |  | IPC channel omnigent:browser-perform-action shar |
| 372 | …rer.invoke("omnigent:browser-execute",… | keep-internal |  | IPC channel omnigent:browser-execute shared with |
| 379 | …rer.invoke("omnigent:browser-close", {… | keep-internal |  | IPC channel omnigent:browser-close shared with m |
| 405 | …rer.invoke("omnigent:browser-set-recen… | keep-internal |  | IPC channel omnigent:browser-set-recent-session- |
| 408 | …rer.invoke("omnigent:browser-cancel-re… | keep-internal |  | IPC channel omnigent:browser-cancel-recent-sessi |
| 428 | …rer.invoke("omnigent:browser-has-view"… | keep-internal |  | IPC channel omnigent:browser-has-view shared wit |
| 452 | …rer.invoke("omnigent:browser-go-back",… | keep-internal |  | IPC channel omnigent:browser-go-back shared with |
| 459 | …rer.invoke("omnigent:browser-go-forwar… | keep-internal |  | IPC channel omnigent:browser-go-forward shared w |
| 466 | …rer.invoke("omnigent:browser-reload", … | keep-internal |  | IPC channel omnigent:browser-reload shared with |
| 473 | …rer.invoke("omnigent:open-browser-devt… | keep-internal |  | IPC channel omnigent:open-browser-devtools share |
| 482 | …rer.invoke("omnigent:browser-chrome-co… | keep-internal |  | IPC channel omnigent:browser-chrome-cookie-previ |
| 495 | …rer.invoke("omnigent:browser-chrome-co… | keep-internal |  | IPC channel omnigent:browser-chrome-cookie-impor |
| 535 | …rer.invoke("omnigent:browser-enable-de… | keep-internal |  | IPC channel omnigent:browser-enable-design-mode |
| 542 | …rer.invoke("omnigent:browser-disable-d… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 551 | …rer.invoke("omnigent:browser-signal-de… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 594 | …nMainWorld("omnigentSetup", { | keep-internal |  | window.omnigentSetup preload bridge name, used b |
| 595 | …rer.invoke("omnigent:get-server-url"), | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 602 | …rer.invoke("omnigent:set-server-url", … | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 605 | …rer.invoke("omnigent:cancel-server-con… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 609 | …enderer.on("omnigent:connection-progre… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 610 | …veListener("omnigent:connection-progre… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 613 | …rer.invoke("omnigent:get-managed-serve… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 615 | …rer.invoke("omnigent:get-managed-serve… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 617 | …rer.invoke("omnigent:get-server-names"… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 620 | …rer.invoke("omnigent:get-setup-capabil… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 623 | …rer.invoke("omnigent:get-runner-option… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 627 | …rer.invoke("omnigent:connect-runner", … | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 632 | …enderer.on("omnigent:runner-connect-lo… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 633 | …veListener("omnigent:runner-connect-lo… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 638 | …derer.send("omnigent:setup-set-color-s… | keep-internal |  | 'omnigent:' IPC channel name sent by preload; ma |
| 642 | …rer.invoke("omnigent:setup-get-color-s… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 647 | …enderer.on("omnigent:setup-theme", lis… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 648 | …veListener("omnigent:setup-theme", lis… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 651 | …rer.invoke("omnigent:get-recent-server… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 653 | …rer.invoke("omnigent:forget-recent-ser… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 659 | …rer.invoke("omnigent:check-server", ur… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 661 | …rer.invoke("omnigent:copy-setup-text",… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 668 | …rer.invoke("omnigent:set-server-select… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 670 | …hether the ˋomnigentˋ CLI is installed… | keep-internal |  | code comment |
| 673 | …rer.invoke("omnigent:get-cli-status"), | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 675 | …path to the omnigent binary. Resolves … | keep-internal |  | code comment |
| 679 | …rer.invoke("omnigent:set-cli-path", pa… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 680 | …ker for the omnigent binary; resolves … | keep-internal |  | code comment |
| 681 | …rer.invoke("omnigent:browse-cli-path")… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 686 | …rer.invoke("omnigent:start-local-serve… | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 695 | …enderer.on("omnigent:local-server-setu… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 696 | …veListener("omnigent:local-server-setu… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 699 | …Install the omnigent CLI (macOS). Reso… | keep-internal |  | code comment |
| 702 | …rer.invoke("omnigent:cli-install"), | keep-internal |  | 'omnigent:' IPC channel name invoked by preload; |
| 709 | …enderer.on("omnigent:cli-install-log",… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |
| 710 | …veListener("omnigent:cli-install-log",… | keep-internal |  | 'omnigent:' IPC event channel subscribed in prel |

### `web/electron/src/quitConfirmation.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 28 | …r will go offline, and the local Omnigent server will stop."; | change | S87 | Quit-prompt detail shown in the in-app quit dialog (via desktop-command quitDetail); 'Omnigent server' product wording. |
| 31 | if (localServer) return "The local Omnigent server will stop."; | change | S87 | Quit-prompt detail shown in the in-app quit dialog; 'Omnigent server' product wording. |
| 66 | …sole.warn("[omnigent] could not save t… | keep-internal |  | console.warn log prefix '[omnigent]', debug outp |

### `web/electron/src/reconnect_overlay.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …nnecting to Databricks…" overlay. | keep-internal |  | code comment |
| 3 | // While a Databricks workspace is bri… | keep-internal |  | code comment |
| 101 | ipcMain.on("omnigent:reconnect-overlay… | keep-internal |  | 'omnigent:reconnect-overlay-cancel' IPC channel |

### `web/electron/src/reconnect_overlay_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …nMainWorld("omnigentReconnectOverlay",… | keep-internal |  | window.omnigentReconnectOverlay preload bridge n |
| 12 | …derer.send("omnigent:reconnect-overlay… | keep-internal |  | 'omnigent:reconnect-overlay-cancel' IPC channel |

### `web/electron/src/return_banner.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 130 | …sole.warn(ˋ[omnigent] return-banner: s… | keep-internal |  | console.warn log prefix '[omnigent]' for debug o |
| 143 | …sole.warn("[omnigent] return-banner: N… | keep-internal |  | console.warn log prefix '[omnigent]' for debug o |
| 157 | ipcMain.on("omnigent:return-banner-go-… | keep-internal |  | 'omnigent:return-banner-go-back' IPC channel han |
| 169 | ipcMain.on("omnigent:return-banner-dis… | keep-internal |  | 'omnigent:return-banner-dismiss' IPC channel han |

### `web/electron/src/return_banner_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …nMainWorld("omnigentReturnBanner", { | keep-internal |  | window.omnigentReturnBanner preload bridge name |
| 14 | …derer.send("omnigent:return-banner-go-… | keep-internal |  | 'omnigent:return-banner-go-back' IPC channel nam |
| 18 | …derer.send("omnigent:return-banner-dis… | keep-internal |  | 'omnigent:return-banner-dismiss' IPC channel nam |

### `web/electron/src/server_labels.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …picked when Databricks sign-in moved t… | keep-internal |  | code comment |

### `web/electron/src/server_manager.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …top-managed Omnigent servers and host … | keep-internal |  | code comment |
| 4 | …foreground ˋomnigent host --server <ur… | keep-internal |  | code comment |
| 7 | …r: a local ˋomnigent serverˋ we starte… | keep-internal |  | code comment |
| 12 | // (omnigent_cli.js), which is the sin… | keep-internal |  | code comment |
| 19 | const cli = require("./omnigent_cli"); | keep-internal |  | require('./omnigent_cli') internal module filena |
| 25 | …* The line ˋomnigent hostˋ prints once… | keep-internal |  | code comment |
| 37 | * Every ˋomnigent hostˋ child we have … | keep-internal |  | code comment |
| 63 | * from ˋomnigent hostˋ's own messages … | keep-internal |  | code comment |
| 64 | …ct, or the ˋomnigent loginˋ hint). Let… | keep-internal |  | code comment |
| 71 | …\|login page\|omnigent login/i.test( | keep-internal |  | code identifier |
| 77 | … True when ˋomnigent hostˋ refused to … | keep-internal |  | code comment |
| 121 | * Spawn ˋomnigent host --server <url>ˋ… | keep-internal |  | code comment |
| 136 | // runs ˋomnigent loginˋ first), so th… | keep-internal |  | code comment |
| 139 | …istic "run ˋomnigent loginˋ" error tha… | keep-internal |  | code comment |
| 195 | …uplicate — ˋomnigent hostˋ would other… | keep-internal |  | code comment |
| 209 | // two ˋomnigent hostˋ processes for o… | keep-internal |  | code comment |
| 236 | …t the slow ˋomnigent | keep-internal |  | code comment |
| 310 | …link module:omnigent_cli.probeServerAu… | keep-internal |  | code comment |
| 311 | …en file — a Databricks pointer record … | keep-internal |  | code comment |
| 314 | * ˋomnigent login <url>ˋ (browser/OIDC… | keep-internal |  | code comment |
| 315 | …but-expired Databricks access token re… | keep-internal |  | code comment |
| 323 | …k import("./omnigent_cli").CliFailure}… | keep-internal |  | code comment |
| 335 | …: import("./omnigent_cli").CliFailure, | keep-internal |  | code comment |
| 384 | … {import("./omnigent_cli").CliFailure … | keep-internal |  | code comment |
| 490 | // ˋomnigent server statusˋ (a Python … | keep-internal |  | code comment |
| 498 | … it boots. ˋomnigent server --backgrou… | keep-internal |  | code comment |
| 547 | …n orphaned ˋomnigent hostˋ process. | keep-internal |  | code comment |

### `web/electron/src/session-expiry.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …pace-hosted Omnigent sits behind the D… | keep-internal |  | code comment |
| 8 | // Databricks browser-auth connections… | keep-internal |  | code comment |
| 9 | …ard live in databricks-auth.js, never … | keep-internal |  | code comment |

### `web/electron/src/ssh_askpass.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 24 | …process.env.OMNIGENT_SSH_ASKPASS_SOCKE… | keep-internal |  | code identifier |
| 30 | …process.env.OMNIGENT_SSH_ASKPASS_TOKEN… | keep-internal |  | code identifier |
| 155 | OMNIGENT_SSH_ASKPASS_SOCKET: socketPat… | keep-internal |  | code identifier |
| 156 | OMNIGENT_SSH_ASKPASS_TOKEN: token, | keep-internal |  | code identifier |

### `web/electron/src/ssh_connect.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …r SSH as an Omnigent host. | keep-internal |  | code comment |
| 6 | * ˋdatabricks auth loginˋ on the remot… | keep-internal |  | code comment |
| 9 | …nfig, runs ˋomnigent loginˋ over it, f… | keep-internal |  | code comment |
| 11 | …hen starts ˋomnigent host --background… | keep-internal |  | code comment |
| 28 | const { isDatabricksOAuthServerUrl } =… | keep-internal |  | code identifier |
| 42 | /** The Databricks CLI's sign-in liste… | keep-internal |  | code comment |
| 112 | …taller puts omnigent in ~/.local/bin, … | keep-internal |  | code comment |
| 127 | ˋBROWSER=none $group omnigent login "${serverUrl}" </dev/null & login=$!ˋ, | keep-deferred |  | Remote login script runs the omnigent CLI binary; CLI name changes with OPS-03/FND-01. |
| 142 | ˋomnigent host --server "${serverUrl}" --background --non-interactive && { echo; echo ${IDENTITY_STA… | keep-deferred |  | Remote host script runs ˋomnigent hostˋ and ˋomnigent host statusˋ; CLI name changes with OPS-03/FND-01. |
| 164 | ˋssh ${destination} omnigent login '${serverUrl}'ˋ, | keep-deferred |  | Consent window shows the real ˋomnigent loginˋ command run over SSH; CLI name changes with OPS-03/FND-01. |
| 165 | ˋssh ${destination} omnigent host --server '${serverUrl}' --background --non-interactiveˋ, | keep-deferred |  | Consent window shows the real ˋomnigent hostˋ command run over SSH; CLI name changes with OPS-03/FND-01. |
| 170 | …ne line of ˋomnigent loginˋ output. | keep-internal |  | code comment |
| 173 | …ull, kind: "databricks" \| "server" } \|… | keep-internal |  | code comment |
| 174 | …s on, for a Databricks sign-in; null | keep-internal |  | code comment |
| 186 | …ort, kind: "databricks" }; | keep-internal |  | Internal sign-in link kind enum value 'databrick |
| 191 | …ull, kind: "databricks" }; | keep-internal |  | Internal sign-in link kind enum value 'databrick |
| 202 | …ull, kind: "databricks" \| "server" }} … | keep-internal |  | code comment |
| 218 | …hosts only: Databricks Apps hosts serv… | keep-internal |  | code comment |
| 219 | …rigin && !isDatabricksOAuthServerUrl(l… | keep-internal |  | code identifier |
| 220 | return ˋThe sign-in link goes to ${origin}, which isn't this server or a Databricks workspace.ˋ; | keep-origin |  | Names the Databricks workspace sign-in integration target, not the publisher. |
| 593 | * Run ˋomnigent loginˋ on the remote m… | keep-internal |  | code comment |
| 707 | …h a username and password. Run \ˋomnigent login ${serverUrl}\ˋ on ${destination} in a terminal, then… | keep-deferred |  | Error tells user to run ˋomnigent loginˋ; CLI name changes with OPS-03/FND-01. |
| 720 | …(installing omnigent first if the user… | keep-internal |  | code comment |
| 755 | return { ok: false, canceled: true, error: ˋOmnigent isn't installed on ${destination}.ˋ }; | change | S87 | User-visible SSH connect error uses Omnigent as product name; roadmap lists ssh_connect.js literals for brand.js. |
| 760 | return { ok: false, error: "This build doesn't include the Omnigent installer." }; | change | S87 | User-visible SSH connect error naming the product installer. |
| 773 | ? ˋInstalling Omnigent on ${destination} timed out.ˋ | change | S87 | User-visible SSH install timeout error uses product name. |
| 774 | : ˋInstalling Omnigent on ${destination} failed: ${detail \|\| ˋexit code ${install.code}ˋ}ˋ, | change | S87 | User-visible SSH install failure error uses product name. |
| 781 | ? { ok: false, error: ˋOmnigent still isn't on the PATH on ${destination}.ˋ } | change | S87 | User-visible SSH connect error uses product name. |
| 798 | ? ˋStarting the Omnigent host on ${destination} timed out.ˋ | change | S87 | User-visible host-start timeout error uses product name. |
| 799 | : ˋStarting the Omnigent host on ${destination} failed: ${detail \|\| ˋexit code ${host.code}ˋ}ˋ, | change | S87 | User-visible host-start failure error uses product name. |

### `web/electron/src/ssh_connect_window.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 190 | ˋOmnigent isn't installed on ${destination}. Install it now? This runs the Omnigent installer there,… | change | S87 | Install prompt text shown in SSH connect window uses Omnigent as product name; Databricks CLI mention stays (integration fact). |

### `web/electron/src/token_store.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …es under ~/.omnigent, encrypted at res… | keep-internal |  | code comment |
| 18 | *   ˋ~/.omnigentˋ; ˋlabelˋ names the c… | keep-internal |  | code comment |
| 22 | …omedir(), ".omnigent", fileName); | keep-internal |  | ~/.omnigent credential store path shared with th |
| 50 | …sole.warn(ˋ[omnigent] safeStorage unav… | keep-internal |  | console.warn log prefix, not shown in UI. |

### `web/electron/src/update_overlay.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …rface: its ˋomnigent:overlay-*ˋ IPC dr… | keep-internal |  | code comment |
| 90 | …tents.send("omnigent:update-overlay-he… | keep-internal |  | 'omnigent:' IPC channel name. |
| 195 | "omnigent:overlay-theme", | keep-internal |  | 'omnigent:overlay-theme' IPC channel name. |
| 232 | ipcMain.on("omnigent:overlay-height", … | keep-internal |  | 'omnigent:overlay-height' IPC channel name. |
| 260 | …ain.handle("omnigent:get-update-overla… | keep-internal |  | 'omnigent:get-update-overlay-height' IPC channel |
| 270 | …ain.handle("omnigent:overlay-get-updat… | keep-internal |  | 'omnigent:overlay-get-update-config' IPC channel |
| 274 | …ain.handle("omnigent:overlay-get-updat… | keep-internal |  | 'omnigent:overlay-get-update-status' IPC channel |
| 278 | …ain.handle("omnigent:overlay-update-ch… | keep-internal |  | 'omnigent:overlay-update-check' IPC channel name |
| 282 | …ain.handle("omnigent:overlay-update-do… | keep-internal |  | 'omnigent:overlay-update-download' IPC channel n |
| 297 | …ain.handle("omnigent:overlay-update-in… | keep-internal |  | 'omnigent:overlay-update-install' IPC channel na |
| 303 | …ain.handle("omnigent:overlay-set-updat… | keep-internal |  | 'omnigent:overlay-set-update-config' IPC channel |
| 313 | …tents.send("omnigent:overlay-theme", t… | keep-internal |  | 'omnigent:overlay-theme' IPC channel name. |

### `web/electron/src/update_overlay_preload.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …er its own ˋomnigent:overlay-*ˋ channe… | keep-internal |  | code comment |
| 9 | …ses ˋwindow.omnigentDesktopˋ in the ex… | keep-internal |  | code comment |
| 11 | …lus a tiny ˋomnigentUpdateOverlayˋ use… | keep-internal |  | code comment |
| 18 | …nMainWorld("omnigentDesktop", { | keep-internal |  | window.omnigentDesktop preload bridge name read |
| 21 | …rer.invoke("omnigent:overlay-get-updat… | keep-internal |  | 'omnigent:' IPC channel name. |
| 22 | …rer.invoke("omnigent:overlay-get-updat… | keep-internal |  | 'omnigent:' IPC channel name. |
| 23 | …rer.invoke("omnigent:overlay-update-ch… | keep-internal |  | 'omnigent:' IPC channel name. |
| 24 | …rer.invoke("omnigent:overlay-update-do… | keep-internal |  | 'omnigent:' IPC channel name. |
| 25 | …rer.invoke("omnigent:overlay-update-in… | keep-internal |  | 'omnigent:' IPC channel name. |
| 26 | …rer.invoke("omnigent:overlay-set-updat… | keep-internal |  | 'omnigent:' IPC channel name. |
| 30 | …enderer.on("omnigent:update-status", l… | keep-internal |  | 'omnigent:update-status' IPC channel name. |
| 31 | …veListener("omnigent:update-status", l… | keep-internal |  | 'omnigent:update-status' IPC channel name. |
| 36 | …nMainWorld("omnigentUpdateOverlay", { | keep-internal |  | window.omnigentUpdateOverlay preload bridge name |
| 40 | …derer.send("omnigent:overlay-height", … | keep-internal |  | 'omnigent:overlay-height' IPC channel name. |
| 44 | …enderer.on("omnigent:overlay-theme", l… | keep-internal |  | 'omnigent:overlay-theme' IPC channel name. |
| 45 | …veListener("omnigent:overlay-theme", l… | keep-internal |  | 'omnigent:overlay-theme' IPC channel name. |

### `web/electron/src/url.d.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | var omnigentUrl: { | keep-internal |  | code identifier |

### `web/electron/src/url.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …hes ˋwindow.omnigentUrlˋ). One copy ke… | keep-internal |  | code comment |
| 16 | root.omnigentUrl = api; | keep-internal |  | code identifier |
| 51 | …parameters. Databricks workspace hosts… | keep-internal |  | code comment |
| 55 | …ly by expandDatabricksWorkspaceUrl. | keep-internal |  | code comment |
| 77 | if (isDatabricksWorkspaceHost(url.host… | keep-internal |  | code identifier |
| 87 | …t such as ˋ/omnigentˋ; the picker | keep-internal |  | code comment |
| 115 | …?o=…ˋ for a Databricks organization se… | keep-internal |  | code comment |
| 128 | if (isDatabricksWorkspaceHost(url.host… | keep-internal |  | code identifier |
| 140 | …pgrades for Databricks workspaces. Inv… | keep-internal |  | code comment |
| 170 | …h where the Omnigent SPA is mounted in… | keep-internal |  | code comment |
| 171 | const WORKSPACE_UI_PATH = "/omnigent"; | keep-internal |  | Workspace SPA mount path /omnigent served by Dat |
| 174 | … that serve Databricks workspaces. Dat… | keep-internal |  | code comment |
| 175 | …absent: ˋˋ*.databricksapps.comˋˋ serve… | keep-internal |  | code comment |
| 178 | const WORKSPACE_DOMAINS = ["databricks.com", "azuredatabricks.net"]; | keep-origin |  | Databricks workspace domains for the Databricks workspace integration. |
| 179 | const DATABRICKS_APPS_HOST_SUFFIX = "databricksapps.com"; | keep-origin |  | Databricks Apps host suffix for Databricks Apps hosting integration. |
| 181 | …ts under, a Databricks workspace domai… | keep-internal |  | code comment |
| 182 | function isDatabricksWorkspaceHost(hos… | keep-internal |  | code identifier |
| 191 | ….port \|\| !isDatabricksWorkspaceHost(ur… | keep-internal |  | code identifier |
| 199 | … for a bare Databricks workspace root. | keep-internal |  | code comment |
| 206 | function databricksWorkspaceUiUrl(rawU… | keep-internal |  | code identifier |
| 214 | if (!isDatabricksWorkspaceHost(url.hos… | keep-internal |  | code identifier |
| 221 | "/api/2.0/omnigent", | keep-internal |  | Server API path /api/2.0/omnigent saved by the C |
| 222 | // Databricks keeps this plural route … | keep-internal |  | code comment |
| 223 | "/api/2.0/omnigents", | keep-internal |  | Legacy plural API path /api/2.0/omnigents. |
| 227 | …grade saved Databricks HTTP URLs and m… | keep-internal |  | code comment |
| 245 | if (!isDatabricksWorkspaceHost(url.hos… | keep-internal |  | code identifier |
| 256 | …s hosted by Databricks — a workspace d… | keep-internal |  | code comment |
| 257 | …ace-mounted Omnigent) or a Databricks … | keep-internal |  | code comment |
| 258 | …r is never "Databricks-managed", whate… | keep-internal |  | code comment |
| 259 | …ed to scope Databricks-internal deskto… | keep-internal |  | code comment |
| 260 | … option) to Databricks-managed servers… | keep-internal |  | code comment |
| 265 | function isDatabricksManagedServerUrl(… | keep-internal |  | code identifier |
| 274 | if (host === DATABRICKS_APPS_HOST_SUFFIX \|\| host.endsWith(ˋ.${DATABRICKS_APPS_HOST_SUFFIX}ˋ)) { | keep-origin |  | Databricks Apps host check for the Databricks hosting integration. |
| 277 | return isDatabricksWorkspaceHost(host)… | keep-internal |  | code identifier |
| 280 | …t-only, not Databricks Apps. */ | keep-internal |  | code comment |
| 281 | function isDatabricksOAuthServerUrl(ra… | keep-internal |  | code identifier |
| 297 | …timeout for Databricks workspace detec… | keep-internal |  | code comment |
| 304 | …pand a bare Databricks workspace URL t… | keep-internal |  | code comment |
| 307 | * (ˋˋomnigent/cli.py:_workspace_api_se… | keep-internal |  | code comment |
| 309 | * like a Databricks workspace — a resp… | keep-internal |  | code comment |
| 311 | …he full ˋˋ…/omnigentˋˋ | keep-internal |  | code comment |
| 322 | …ction expandDatabricksWorkspaceUrl(nor… | keep-internal |  | code identifier |
| 331 | … mount, and Databricks workspaces are | keep-internal |  | code comment |
| 336 | // Databricks Apps share the workspace… | keep-internal |  | code comment |
| 339 | if (host === DATABRICKS_APPS_HOST_SUFFIX \|\| host.endsWith(ˋ.${DATABRICKS_APPS_HOST_SUFFIX}ˋ)) { | keep-origin |  | Databricks Apps host check in workspace URL expansion (integration). |
| 356 | if ((probe.headers.get("server") ?? "").toLowerCase() !== "databricks") { | keep-origin |  | Matches the Databricks platform's 'server: databricks' response header to detect a workspace. |
| 367 | ….well-known/omnigent.json"; | keep-internal |  | Server well-known manifest path /.well-known/omn |
| 386 | … cookies an Omnigent server sets. */ | keep-internal |  | code comment |
| 543 | databricksWorkspaceUiUrl, | keep-internal |  | code identifier |
| 544 | expandDatabricksWorkspaceUrl, | keep-internal |  | code identifier |
| 545 | isDatabricksManagedServerUrl, | keep-internal |  | code identifier |
| 546 | isDatabricksOAuthServerUrl, | keep-internal |  | code identifier |

### `web/electron/src/workspace-chrome.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | … Hiding the Databricks workspace navig… | keep-internal |  | code comment |
| 2 | // Omnigent SPA. Kept in its own Elect… | keep-internal |  | code comment |
| 8 | // web/ios/Omnigent/WorkspaceChromeScr… | keep-internal |  | code comment |
| 12 | …t hides the Databricks workspace navig… | keep-internal |  | code comment |
| 14 | … *page*, so Databricks wraps | keep-internal |  | code comment |
| 16 | … We promote Omnigent's | keep-internal |  | code comment |
| 17 | …n root — ˋˋ.omnigent-appˋˋ, the wrappe… | keep-internal |  | code comment |
| 19 | …. Keying on Omnigent's wrapper (define… | keep-internal |  | code comment |
| 21 | …eaking when Databricks reshuffles its … | keep-internal |  | code comment |
| 22 | …re is no ˋˋ.omnigent-appˋˋ, so the rul… | keep-internal |  | code comment |
| 26 | .omnigent-app { | keep-internal |  | code identifier |
| 40 | … targets ˋˋ.omnigent-appˋˋ — which exi… | keep-internal |  | code comment |

### `web/electron/src/workspace-root-bounce.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …ed shell on Omnigent when Databricks n… | keep-internal |  | code comment |
| 7 | const { databricksWorkspaceUiUrl } = r… | keep-internal |  | code identifier |
| 25 | * ˋˋ/omnigentˋˋ redirects back to ˋˋ/ˋ… | keep-internal |  | code comment |
| 38 | …st target = databricksWorkspaceUiUrl(r… | keep-internal |  | code identifier |
| 58 | if (databricksWorkspaceUiUrl(current) … | keep-internal |  | code identifier |

### `web/electron/ssh-connect/console.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 97 | installing: () => ˋInstalling Omnigent on ${destination}. This can take a few minutes.ˋ, | change | S87 | Status text shown in SSH connect console uses product name; renderer script cannot require brand.js. |
| 98 | "starting-host": () => ˋStarting the Omnigent host on ${destination}...ˋ, | change | S87 | Status text shown in SSH connect console uses product name. |
| 122 | install: { title: "Install Omnigent?", ok: "Install", input: null }, | change | S87 | Install prompt dialog title shown to users. |

### `web/electron/test/about_page.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 90 | omnigentAbout: api, | keep-internal |  | test code |
| 117 | assert.equal(page.elements["desktop-heading"].textContent, "Omnigent macOS app"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/electron/test/about_window.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 136 | …/.local/bin/omnigent", | keep-internal |  | test code |
| 137 | version: "omnigent 0.13.0.dev0", | keep-internal |  | test code |
| 139 | installCommand: "install omnigent", | keep-internal |  | test code |
| 190 | …pplications/Omnigent.app/Contents/MacO… | keep-internal |  | test code |
| 206 | …pplications/Omnigent.app/Contents/MacO… | keep-internal |  | test code |
| 250 | assert.match(script, /desktopHeading\.textContent = ˋOmnigent \$\{platformName\} appˋ/); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 255 | …atus:[\s\S]*omnigent:update-status/); | keep-internal |  | test code |
| 256 | …rer\.send\("omnigent:about-close"\)/); | keep-internal |  | test code |
| 326 | …ndlers.get("omnigent:about-get-info"); | keep-internal |  | test code |
| 334 | …/.local/bin/omnigent", | keep-internal |  | test code |
| 335 | version: "omnigent 0.13.0.dev0", | keep-internal |  | test code |
| 337 | installCommand: "install omnigent", | keep-internal |  | test code |
| 343 | "omnigent:about-get-info", | keep-internal |  | test code |
| 344 | "omnigent:about-get-desktop-update-sta… | keep-internal |  | test code |
| 345 | "omnigent:about-check-desktop", | keep-internal |  | test code |
| 346 | "omnigent:about-download-desktop-updat… | keep-internal |  | test code |
| 347 | "omnigent:about-install-desktop-update… | keep-internal |  | test code |
| 368 | …ndlers.get("omnigent:about-close"); | keep-internal |  | test code |
| 386 | …ndlers.get("omnigent:about-get-desktop… | keep-internal |  | test code |
| 389 | …ndlers.get("omnigent:about-check-deskt… | keep-internal |  | test code |
| 392 | …ndlers.get("omnigent:about-download-de… | keep-internal |  | test code |
| 396 | …ndlers.get("omnigent:about-install-des… | keep-internal |  | test code |
| 405 | …ndlers.get("omnigent:about-install-des… | keep-internal |  | test code |

### `web/electron/test/arca.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 156 | …"renews for Omnigent without updating … | keep-internal |  | test code |
| 160 | …ler-name", "omnigent", "--update-kubec… | keep-internal |  | test code |
| 327 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 341 | …mple.com/ml/omnigents"); | keep-internal |  | test code |
| 350 | …mple.com/ml/omnigents'", | keep-internal |  | test code |
| 358 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 361 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 373 | …://ws.cloud.databricks.com/omnigent;id… | keep-internal |  | test code |
| 374 | …://ws.cloud.databricks.com/a$(id)")); | keep-internal |  | test code |
| 375 | …://ws.cloud.databricks.com/a'b")); | keep-internal |  | test code |
| 377 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 384 | "Error: OMNIGENT_AUTH_REQUIRED: sign i… | keep-internal |  | test code |
| 402 | …2026). Run ˋomnigent login https://srv… | keep-internal |  | test code |
| 485 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 504 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 528 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |

### `web/electron/test/arcaIdentity.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 18 | …s://account.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 19 | …s://account.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 34 | …s://account.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 40 | …dbc-1.cloud.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 53 | …s://account.databricks.com/omnigent"; | keep-internal |  | test code |
| 65 | …tps://other.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 69 | …tps://other.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 70 | …s://another.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 73 | …tps://other.databricks.com/api/2.0/omn… | keep-internal |  | test code |

### `web/electron/test/arca_autoconnect.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …space.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 67 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 68 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |

### `web/electron/test/arca_connect_window.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 79 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 205 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 221 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 253 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 267 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |

### `web/electron/test/arca_onboarding.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 19 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 29 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 73 | …it("data", "Omnigent login: https://ex… | keep-internal |  | test code |
| 91 | ["OMNIGENT_AUTH_REQUIRED", 1, "omni-au… | keep-internal |  | test code |
| 112 | …it("data", "OMNIGENT_AUTH_REQUIRED"); | keep-internal |  | test code |

### `web/electron/test/away_banner.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …://ws.cloud.databricks.com"; | keep-internal |  | test code |
| 66 | …vigation (a Databricks /omnigent mount… | keep-internal |  | test code |
| 68 | … ˋ${ORIGIN}/omnigent/c/abc123?o=456ˋ); | keep-internal |  | test code |
| 76 | …[ˋ${ORIGIN}/omnigent/c/abc123?o=456ˋ])… | keep-internal |  | test code |
| 81 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 87 | … ˋ${ORIGIN}/omnigentˋ; | keep-internal |  | test code |
| 88 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 100 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 123 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 140 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 152 | … ˋ${ORIGIN}/omnigent/c/xyzˋ; | keep-internal |  | test code |
| 153 | … ˋ${ORIGIN}/omnigent/c/xyzˋ); | keep-internal |  | test code |
| 157 | …[ˋ${ORIGIN}/omnigentˋ, ˋ${ORIGIN}/omni… | keep-internal |  | test code |
| 162 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 180 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 181 | … ˋ${ORIGIN}/omnigent/c/new-chat?o=7ˋ, … | keep-internal |  | test code |
| 185 | …[ˋ${ORIGIN}/omnigent/c/new-chat?o=7ˋ])… | keep-internal |  | test code |
| 190 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 198 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 203 | … ˋ${ORIGIN}/omnigentˋ; | keep-internal |  | test code |
| 210 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 225 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 230 | …next_url=%2Fomnigent&o=1ˋ; | keep-internal |  | test code |
| 231 | …next_url=%2Fomnigent&o=1ˋ); | keep-internal |  | test code |
| 240 | …[ˋ${ORIGIN}/omnigentˋ]); | keep-internal |  | test code |
| 245 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 250 | …[ˋ${ORIGIN}/omnigentˋ]); | keep-internal |  | test code |
| 256 | …next_url=%2Fomnigent"), true); | keep-internal |  | test code |
| 261 | …("https://h/omnigent"), false); | keep-internal |  | test code |

### `web/electron/test/browserIpc.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 84 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 134 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 189 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 226 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 258 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 290 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 328 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 369 | …ain.invoke("omnigent:browser-open-or-n… | keep-internal |  | test code |
| 537 | …ain.invoke("omnigent:browser-has-view"… | keep-internal |  | test code |
| 546 | …ain.invoke("omnigent:browser-has-view"… | keep-internal |  | test code |
| 563 | …ain.invoke("omnigent:browser-has-view"… | keep-internal |  | test code |
| 583 | …ain.invoke("omnigent:browser-has-view"… | keep-internal |  | test code |
| 592 | …ain.invoke("omnigent:browser-set-activ… | keep-internal |  | test code |
| 594 | …ain.invoke("omnigent:browser-set-activ… | keep-internal |  | test code |
| 607 | …ain.invoke("omnigent:browser-focused-v… | keep-internal |  | test code |
| 609 | …ain.invoke("omnigent:browser-focused-v… | keep-internal |  | test code |
| 612 | …ain.invoke("omnigent:browser-focused-v… | keep-internal |  | test code |
| 618 | …ain.invoke("omnigent:browser-focused-v… | keep-internal |  | test code |
| 627 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 628 | "omnigent:browser-set-active", | keep-internal |  | test code |
| 629 | "omnigent:browser-focused-view", | keep-internal |  | test code |
| 630 | "omnigent:browser-set-suppressed", | keep-internal |  | test code |
| 631 | "omnigent:browser-set-recent-session-s… | keep-internal |  | test code |
| 632 | "omnigent:browser-cancel-recent-sessio… | keep-internal |  | test code |
| 633 | "omnigent:browser-resize", | keep-internal |  | test code |
| 634 | "omnigent:browser-screenshot", | keep-internal |  | test code |
| 635 | "omnigent:browser-perform-action", | keep-internal |  | test code |
| 636 | "omnigent:browser-has-view", | keep-internal |  | test code |
| 637 | "omnigent:browser-close", | keep-internal |  | test code |
| 638 | "omnigent:browser-go-back", | keep-internal |  | test code |
| 639 | "omnigent:browser-go-forward", | keep-internal |  | test code |
| 640 | "omnigent:browser-reload", | keep-internal |  | test code |
| 641 | "omnigent:open-browser-devtools", | keep-internal |  | test code |
| 642 | "omnigent:browser-enable-design-mode", | keep-internal |  | test code |
| 643 | "omnigent:browser-disable-design-mode"… | keep-internal |  | test code |
| 644 | "omnigent:browser-signal-design-result… | keep-internal |  | test code |
| 645 | "omnigent:browser-chrome-cookie-previe… | keep-internal |  | test code |
| 646 | "omnigent:browser-chrome-cookie-import… | keep-internal |  | test code |
| 655 | "omnigent:browser-go-back", | keep-internal |  | test code |
| 656 | "omnigent:browser-go-forward", | keep-internal |  | test code |
| 657 | "omnigent:browser-reload", | keep-internal |  | test code |
| 658 | "omnigent:open-browser-devtools", | keep-internal |  | test code |
| 659 | "omnigent:browser-perform-action", | keep-internal |  | test code |
| 660 | "omnigent:browser-execute", | keep-internal |  | test code |
| 661 | "omnigent:browser-chrome-cookie-previe… | keep-internal |  | test code |
| 662 | "omnigent:browser-chrome-cookie-import… | keep-internal |  | test code |
| 684 | …ain.invoke("omnigent:browser-set-suppr… | keep-internal |  | test code |
| 686 | …ain.invoke("omnigent:browser-set-suppr… | keep-internal |  | test code |
| 693 | …ain.invoke("omnigent:browser-set-suppr… | keep-internal |  | test code |
| 702 | …ain.invoke("omnigent:browser-set-recen… | keep-internal |  | test code |
| 705 | …ain.invoke("omnigent:browser-set-recen… | keep-internal |  | test code |
| 714 | …ain.invoke("omnigent:browser-cancel-re… | keep-internal |  | test code |
| 723 | "omnigent:browser-cancel-recent-sessio… | keep-internal |  | test code |
| 727 | "omnigent:browser-set-recent-session-s… | keep-internal |  | test code |
| 743 | …ain.invoke("omnigent:browser-go-back",… | keep-internal |  | test code |
| 751 | …ain.invoke("omnigent:browser-go-back",… | keep-internal |  | test code |
| 759 | …ain.invoke("omnigent:browser-go-forwar… | keep-internal |  | test code |
| 766 | …ain.invoke("omnigent:browser-reload", … | keep-internal |  | test code |
| 772 | …ain.invoke("omnigent:browser-go-back",… | keep-internal |  | test code |
| 818 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 829 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 856 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 888 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 909 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 940 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 965 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 991 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1011 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1037 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1052 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1069 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1084 | "omnigent:browser-chrome-cookie-previe… | keep-internal |  | test code |
| 1085 | "omnigent:browser-chrome-cookie-import… | keep-internal |  | test code |
| 1102 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1112 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1124 | …ain.invoke("omnigent:browser-chrome-co… | keep-internal |  | test code |
| 1137 | …ain.invoke("omnigent:open-browser-devt… | keep-internal |  | test code |
| 1139 | …ain.invoke("omnigent:open-browser-devt… | keep-internal |  | test code |
| 1148 | …ain.invoke("omnigent:browser-open-or-n… | keep-internal |  | test code |
| 1185 | …ain.invoke("omnigent:browser-open-or-n… | keep-internal |  | test code |
| 1201 | "omnigent:browser-enable-design-mode", | keep-internal |  | test code |
| 1202 | "omnigent:browser-disable-design-mode"… | keep-internal |  | test code |
| 1203 | "omnigent:browser-signal-design-result… | keep-internal |  | test code |
| 1217 | …ain.invoke("omnigent:browser-enable-de… | keep-internal |  | test code |
| 1228 | …ain.invoke("omnigent:browser-enable-de… | keep-internal |  | test code |
| 1252 | …ain.invoke("omnigent:browser-enable-de… | keep-internal |  | test code |
| 1271 | …ain.invoke("omnigent:browser-enable-de… | keep-internal |  | test code |
| 1274 | …ain.invoke("omnigent:browser-enable-de… | keep-internal |  | test code |
| 1283 | …ain.invoke("omnigent:browser-enable-de… | keep-internal |  | test code |
| 1287 | …ain.invoke("omnigent:browser-disable-d… | keep-internal |  | test code |
| 1297 | …ain.invoke("omnigent:browser-signal-de… | keep-internal |  | test code |
| 1416 | …ain.invoke("omnigent:browser-execute",… | keep-internal |  | test code |
| 1428 | …ain.invoke("omnigent:browser-execute",… | keep-internal |  | test code |
| 1440 | …ain.invoke("omnigent:browser-perform-a… | keep-internal |  | test code |
| 1457 | …ain.invoke("omnigent:browser-perform-a… | keep-internal |  | test code |
| 1488 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 1541 | "omnigent:browser-open-or-navigate", | keep-internal |  | test code |
| 1597 | ? "omnigent:browser-screenshot" | keep-internal |  | test code |
| 1599 | ? "omnigent:browser-execute" | keep-internal |  | test code |
| 1600 | : "omnigent:browser-perform-action"; | keep-internal |  | test code |
| 1631 | …eenshot" ? "omnigent:browser-screensho… | keep-internal |  | test code |
| 1659 | …ain.invoke("omnigent:browser-has-view"… | keep-internal |  | test code |
| 1761 | …ain.invoke("omnigent:browser-screensho… | keep-internal |  | test code |

### `web/electron/test/browserPermissionPrompt.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 102 | …ndlers.get("omnigent:browser-permissio… | keep-internal |  | test code |
| 104 | …ndlers.get("omnigent:browser-permissio… | keep-internal |  | test code |
| 119 | partition: "omnigent-browser-permissio… | keep-internal |  | test code |
| 277 | omnigentBrowserPermission: { | keep-internal |  | test code |

### `web/electron/test/browserViewRegistry_storage_isolation.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …g. ˋpersist:omnigent-agent-<conversati… | keep-internal |  | test code |
| 99 | …"w1", id), ˋomnigent-agent-w1-${id}ˋ); | keep-internal |  | test code |

### `web/electron/test/chromeCookieImportPrompt.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 44 | assert.equal(message, "Import 3 cookies into Omnigent?"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/electron/test/chromeCookieStore.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 284 | ….tmpdir(), "omnigent-chrome-cookie-fak… | keep-internal |  | test code |
| 376 | ….tmpdir(), "omnigent-chrome-profiles-"… | keep-internal |  | test code |
| 485 | ….tmpdir(), "omnigent-chrome-db-")); | keep-internal |  | test code |
| 491 | …startsWith("omnigent-chrome-cookie-"))… | keep-internal |  | test code |
| 505 | …startsWith("omnigent-chrome-cookie-"))… | keep-internal |  | test code |
| 514 | ….tmpdir(), "omnigent-chrome-legacy-"))… | keep-internal |  | test code |
| 555 | ….tmpdir(), "omnigent-chrome-psl-")); | keep-internal |  | test code |
| 599 | ….tmpdir(), "omnigent-chrome-chips-")); | keep-internal |  | test code |
| 621 | ….tmpdir(), "omnigent-chrome-preview-")… | keep-internal |  | test code |
| 662 | ….tmpdir(), "omnigent-chrome-import-"))… | keep-internal |  | test code |
| 689 | ….tmpdir(), "omnigent-chrome-scope-")); | keep-internal |  | test code |
| 718 | ….tmpdir(), "omnigent-chrome-badscope-"… | keep-internal |  | test code |
| 740 | ….tmpdir(), "omnigent-chrome-keychain-"… | keep-internal |  | test code |
| 761 | ….tmpdir(), "omnigent-chrome-moved-")); | keep-internal |  | test code |
| 783 | ….tmpdir(), "omnigent-chrome-reject-"))… | keep-internal |  | test code |
| 808 | ….tmpdir(), "omnigent-chrome-broken-"))… | keep-internal |  | test code |
| 824 | …e, /sqlite3\|omnigent-chrome-cookie-\|\/… | keep-internal |  | test code |
| 834 | ….tmpdir(), "omnigent-chrome-noprofile-… | keep-internal |  | test code |

### `web/electron/test/connection_loading.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 50 | …t, "Opening Omnigent…"); | keep-internal |  | test code |
| 58 | …, ["Opening Omnigent…"]); | keep-internal |  | test code |
| 68 | …t, "Opening Omnigent…"); | keep-internal |  | test code |
| 82 | …t, "Opening Omnigent…"); | keep-internal |  | test code |
| 91 | …}, "Opening Omnigent…"); | keep-internal |  | test code |
| 107 | …t, "Opening Omnigent…"); | keep-internal |  | test code |

### `web/electron/test/databricks-account.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | // (src/databricks-account.js), run wi… | keep-internal |  | test code |
| 15 | // databricks-account requires databri… | keep-internal |  | test code |
| 24 | …ire("../src/databricks-account"); | keep-internal |  | test code |
| 36 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 38 | …ounts.cloud.databricks.com", | keep-internal |  | test code |
| 44 | …://ws.cloud.databricks.com/oidc")), nu… | keep-internal |  | test code |
| 54 | …ounts.cloud.databricks.com", accountId… | keep-internal |  | test code |
| 62 | …n: "a.cloud.databricks.com", | keep-internal |  | test code |
| 68 | …n: "b.cloud.databricks.com", | keep-internal |  | test code |
| 80 | …ounts.cloud.databricks.com/api/2.0/acc… | keep-internal |  | test code |
| 82 | …n: "a.cloud.databricks.com" }]); | keep-internal |  | test code |

### `web/electron/test/databricks-auth.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | DATABRICKS_BROWSER_AUTH_KEY, | keep-internal |  | test code |
| 8 | readDatabricksAuthMode, | keep-internal |  | test code |
| 9 | usesDatabricksBrowserAuth, | keep-internal |  | test code |
| 10 | isDatabricksLoginUrl, | keep-internal |  | test code |
| 14 | createDatabricksAuth, | keep-internal |  | test code |
| 15 | } = require("../src/databricks-auth"); | keep-internal |  | test code |
| 17 | …space.cloud.databricks.com"; | keep-internal |  | test code |
| 18 | … ˋ${ORIGIN}/omnigent/c/chatˋ; | keep-internal |  | test code |
| 48 | const auth = createDatabricksAuth({ | keep-internal |  | test code |
| 53 | usesDatabricksBrowserAuth(windows.get(… | keep-internal |  | test code |
| 110 | describe("Databricks authentication mo… | keep-internal |  | test code |
| 114 | readDatabricksAuthMode({ | keep-internal |  | test code |
| 125 | { [DATABRICKS_BROWSER_AUTH_KEY]: true … | keep-internal |  | test code |
| 126 | [DATABRICKS_BROWSER_AUTH_KEY, "boolean… | keep-internal |  | test code |
| 133 | readDatabricksAuthMode({ | keep-internal |  | test code |
| 146 | readDatabricksAuthMode({ | keep-internal |  | test code |
| 156 | readDatabricksAuthMode({ platform: "li… | keep-internal |  | test code |
| 160 | …de to HTTPS Databricks workspace/accou… | keep-internal |  | test code |
| 163 | …ounts.cloud.databricks.com", | keep-internal |  | test code |
| 164 | …db-1.2.azuredatabricks.net/omnigent", | keep-internal |  | test code |
| 166 | …t.equal(usesDatabricksBrowserAuth(url,… | keep-internal |  | test code |
| 167 | …t.equal(usesDatabricksBrowserAuth(url,… | keep-internal |  | test code |
| 170 | "https://demo.databricksapps.com", | keep-internal |  | test code |
| 173 | "https://notdatabricks.com", | keep-internal |  | test code |
| 178 | …t.equal(usesDatabricksBrowserAuth(url,… | keep-internal |  | test code |
| 189 | …ert.equal(isDatabricksLoginUrl(ˋ${ORIG… | keep-internal |  | test code |
| 192 | …ert.equal(isDatabricksLoginUrl(url, OR… | keep-internal |  | test code |
| 197 | describe("Databricks browser session l… | keep-internal |  | test code |
| 202 | … ˋ${ORIGIN}/omnigentˋ, TARGET); | keep-internal |  | test code |
| 215 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 216 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 226 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 236 | … ˋ${ORIGIN}/omnigentˋ, TARGET); | keep-internal |  | test code |
| 251 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 267 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 315 | … ˋ${ORIGIN}/omnigentˋ, TARGET); | keep-internal |  | test code |
| 334 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 347 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 357 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 359 | …https://app.databricksapps.com"); | keep-internal |  | test code |
| 376 | … ˋ${ORIGIN}/omnigentˋ, TARGET); | keep-internal |  | test code |
| 379 | … ˋ${ORIGIN}/omnigent/c/another-chatˋ); | keep-internal |  | test code |
| 388 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 407 | … ˋ${ORIGIN}/omnigentˋ); | keep-internal |  | test code |
| 433 | [failure("Databricks session creation … | keep-internal |  | test code |
| 434 | [failure("Databricks session response … | keep-internal |  | test code |
| 435 | [new Error("Databricks session respons… | keep-internal |  | test code |
| 439 | …("no stored Databricks token", { error… | keep-internal |  | test code |
| 443 | [new Error("Databricks session creatio… | keep-internal |  | test code |

### `web/electron/test/databricks-oauth.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …sts for the Databricks token store + r… | keep-internal |  | test code |
| 2 | // (src/databricks-oauth.js), run with… | keep-internal |  | test code |
| 36 | …ire("../src/databricks-oauth"); | keep-internal |  | test code |
| 49 | …://ws.cloud.databricks.com"; | keep-internal |  | test code |
| 50 | …ounts.cloud.databricks.com", id: "acc-… | keep-internal |  | test code |
| 67 | …process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | test code |
| 68 | process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | test code |
| 71 | …ocess.env, "OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | test code |
| 72 | …process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | test code |
| 126 | assert.match(response.body, /Return to Omnigent/i); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 141 | process.env.OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | test code |
| 142 | …ocess.env, "OMNIGENT_DATABRICKS_OAUTH_… | keep-internal |  | test code |
| 310 | …e("isTrustedDatabricksOrigin", () => { | keep-internal |  | test code |
| 312 | …th.isTrustedDatabricksOrigin("https://… | keep-internal |  | test code |
| 313 | …th.isTrustedDatabricksOrigin("https://… | keep-internal |  | test code |
| 314 | …th.isTrustedDatabricksOrigin("https://… | keep-internal |  | test code |
| 317 | …th.isTrustedDatabricksOrigin("https://… | keep-internal |  | test code |
| 318 | …th.isTrustedDatabricksOrigin("https://… | keep-internal |  | test code |
| 319 | …th.isTrustedDatabricksOrigin("http://w… | keep-internal |  | test code |
| 320 | …th.isTrustedDatabricksOrigin("not a ur… | keep-internal |  | test code |
| 351 | …other.cloud.databricks.com"; | keep-internal |  | test code |
| 387 | …other.cloud.databricks.com"; | keep-internal |  | test code |
| 445 | "x-databricks-request-id": ˋredirect-$… | keep-internal |  | test code |
| 623 | …eaders({ "x-databricks-request-id": "t… | keep-internal |  | test code |
| 640 | "databricks_token", | keep-internal |  | test code |
| 656 | message: /no stored Databricks token/, | keep-internal |  | test code |

### `web/electron/test/databricks-session.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …space.cloud.databricks.com"; | keep-internal |  | test code |
| 18 | … blocked by Databricks IP ACL for work… | keep-internal |  | test code |
| 60 | … ˋ${ORIGIN}/omnigentˋ, {}); | keep-internal |  | test code |
| 89 | …me, "../src/databricks-session.js"); | keep-internal |  | test code |
| 102 | …fier === "./databricks-oauth") | keep-internal |  | test code |
| 104 | isTrustedDatabricksOrigin: realRequire… | keep-internal |  | test code |
| 116 | …fier === "./databricks-account") retur… | keep-internal |  | test code |
| 125 | describe("Databricks session preparati… | keep-internal |  | test code |
| 126 | …rejects non-Databricks and Apps URLs b… | keep-internal |  | test code |
| 129 | …https://app.databricksapps.com", "http… | keep-internal |  | test code |
| 131 | …cts(h.ensureDatabricksSession(h.ses, o… | keep-internal |  | test code |
| 133 | h.ensureDatabricksSession(h.ses, origi… | keep-internal |  | test code |
| 134 | /Databricks workspace/, | keep-internal |  | test code |
| 146 | …("no stored Databricks token", { error… | keep-internal |  | test code |
| 147 | …ounts.cloud.databricks.com"; | keep-internal |  | test code |
| 170 | …/login" : "/omnigent"}ˋ, | keep-internal |  | test code |
| 211 | …t = h.ensureDatabricksSession(h.ses, o… | keep-internal |  | test code |
| 228 | h.ensureDatabricksSession(h.ses, ORIGI… | keep-internal |  | test code |
| 235 | …ait h.ensureDatabricksSession(h.ses, O… | keep-internal |  | test code |
| 241 | describe("Databricks cookie minting", … | keep-internal |  | test code |
| 244 | … "token", "/omnigent"); | keep-internal |  | test code |
| 252 | … "token", "/omnigent"); | keep-internal |  | test code |
| 264 | … "token", "/omnigent"), | keep-internal |  | test code |
| 272 | … "token", "/omnigent"), /no new DBAUTH… | keep-internal |  | test code |
| 276 | … "token", "/omnigent"), /HTTP 401/); | keep-internal |  | test code |
| 287 | "x-databricks-request-id": "trace-123"… | keep-internal |  | test code |
| 293 | …s-token", "/omnigent"), | keep-internal |  | test code |
| 313 | … "token", "/omnigent"), (error) => { | keep-internal |  | test code |
| 325 | … "token", "/omnigent"), (error) => { | keep-internal |  | test code |
| 344 | …e-token", "/omnigent")); | keep-internal |  | test code |
| 353 | … "token", "/omnigent", { | keep-internal |  | test code |
| 371 | … "token", "/omnigent", { signal: contr… | keep-internal |  | test code |
| 383 | … "token", "/omnigent", { | keep-internal |  | test code |
| 410 | … "token", "/omnigent"), | keep-internal |  | test code |
| 430 | … "token", "/omnigent"), (error) => { | keep-internal |  | test code |

### `web/electron/test/deepLink.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | //   - parseOmnigentDeepLink: scheme i… | keep-internal |  | test code |
| 14 | parseOmnigentDeepLink, | keep-internal |  | test code |
| 19 | …cribe("parseOmnigentDeepLink", () => { | keep-internal |  | test code |
| 21 | assert.deepEqual(parseOmnigentDeepLink("omnigent://localhost:8000/c/conv_abc"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 25 | assert.deepEqual(parseOmnigentDeepLink("omnigent://127.0.0.1:8000/c/x"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 32 | assert.deepEqual(parseOmnigentDeepLink("omnigent://my-workspace.cloud.databricks.com/c/x"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 33 | …space.cloud.databricks.com", | keep-internal |  | test code |
| 39 | assert.deepEqual(parseOmnigentDeepLink("omnigent://example.com:8443/c/x"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 46 | assert.deepEqual(parseOmnigentDeepLink("omnigent://[::1]:8000/c/x"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 54 | parseOmnigentDeepLink("omnigent://localhost:8000/c/conv_abc/").path, | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 60 | const parsed = parseOmnigentDeepLink("omnigent://localhost:8000/c/conv_abc?reply=1#frag"); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 65 | …jects a non-omnigent scheme", () => { | keep-internal |  | test code |
| 66 | ….equal(parseOmnigentDeepLink("https://… | keep-internal |  | test code |
| 67 | ….equal(parseOmnigentDeepLink("vscode:/… | keep-internal |  | test code |
| 71 | assert.equal(parseOmnigentDeepLink("omnigent://"), null); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 72 | assert.equal(parseOmnigentDeepLink("omnigent:///c/x"), null); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 76 | // ˋomnigent startˋ opens the host UI … | keep-internal |  | test code |
| 77 | assert.deepEqual(parseOmnigentDeepLink("omnigent://localhost:8000/"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 81 | assert.deepEqual(parseOmnigentDeepLink("omnigent://localhost:8000"), { | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 88 | assert.equal(parseOmnigentDeepLink("omnigent://localhost:8000/inbox"), null); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 89 | assert.equal(parseOmnigentDeepLink("omnigent://localhost:8000/settings/appearance"), null); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 90 | assert.equal(parseOmnigentDeepLink("omnigent://localhost:8000/c/"), null); // empty id | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 91 | assert.equal(parseOmnigentDeepLink("omnigent://localhost:8000/c/a/b"), null); // nested path | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 95 | ….equal(parseOmnigentDeepLink("not a ur… | keep-internal |  | test code |
| 96 | ….equal(parseOmnigentDeepLink(null), nu… | keep-internal |  | test code |
| 97 | ….equal(parseOmnigentDeepLink(undefined… | keep-internal |  | test code |
| 98 | ….equal(parseOmnigentDeepLink(123), nul… | keep-internal |  | test code |
| 103 | …space.cloud.databricks.com"; | keep-internal |  | test code |
| 203 | assert.equal(await acceptCliDeepLink("omnigent://localhost:6767/"), true); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 217 | await acceptCliDeepLink(ˋomnigent://localhost/?desktop_ack=${acknowledgment}ˋ), | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 227 | ˋomnigent://localhost/?desktop_ack=123:${token}&desktop_ack=123:${token}ˋ, | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 232 | await acceptCliDeepLink(ˋomnigent://localhost/settings?desktop_ack=123:${token}ˋ), | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 246 | await acceptCliDeepLink(ˋomnigent://localhost/?desktop_ack=1234:${token}ˋ), | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 256 | assert.equal(await acceptCliDeepLink(ˋomnigent://localhost/?desktop_ack=1234:${token}ˋ), false); | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/electron/test/desktop_updater.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 225 | channel: "omnigent:update-status", | keep-internal |  | test code |
| 378 | "omnigent:update-check", | keep-internal |  | test code |
| 379 | "omnigent:update-download", | keep-internal |  | test code |
| 380 | "omnigent:update-install", | keep-internal |  | test code |
| 381 | "omnigent:set-update-config", | keep-internal |  | test code |
| 402 | ["omnigent:get-update-config", []], | keep-internal |  | test code |
| 403 | ["omnigent:get-update-status", []], | keep-internal |  | test code |
| 404 | ["omnigent:update-check", []], | keep-internal |  | test code |
| 405 | ["omnigent:update-download", []], | keep-internal |  | test code |
| 406 | ["omnigent:update-install", []], | keep-internal |  | test code |
| 407 | ["omnigent:set-update-config", [{ mode… | keep-internal |  | test code |
| 424 | …ndlers.get("omnigent:update-download")… | keep-internal |  | test code |
| 426 | assert.equal(h.calls.showMessageBox[0].options.message, "Download an Omnigent update?"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 433 | …ndlers.get("omnigent:set-update-config… | keep-internal |  | test code |
| 434 | assert.equal(h.calls.showMessageBox[0].options.message, "Change Omnigent update settings?"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 447 | …ndlers.get("omnigent:update-download")… | keep-internal |  | test code |
| 459 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |
| 474 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |

### `web/electron/test/folderChooser.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | …ndlers.get("omnigent:choose-directory"… | keep-internal |  | test code |
| 30 | …ndlers.get("omnigent:dropped-file-path… | keep-internal |  | test code |

### `web/electron/test/local_server_log_tail.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …elpers (src/omnigent_cli.js), run with | keep-internal |  | test code |
| 18 | } = require("../src/omnigent_cli"); | keep-internal |  | test code |
| 68 | … read from <OMNIGENT_DATA_DIR>/logs/se… | keep-internal |  | test code |
| 73 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | test code |
| 76 | ….tmpdir(), "omnigent-logtail-")); | keep-internal |  | test code |
| 77 | process.env.OMNIGENT_DATA_DIR = dataDi… | keep-internal |  | test code |
| 82 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | test code |
| 83 | …process.env.OMNIGENT_DATA_DIR = prevEn… | keep-internal |  | test code |
| 128 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | test code |
| 131 | ….tmpdir(), "omnigent-logtail-run-")); | keep-internal |  | test code |
| 132 | process.env.OMNIGENT_DATA_DIR = dataDi… | keep-internal |  | test code |
| 137 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | test code |
| 138 | …process.env.OMNIGENT_DATA_DIR = prevEn… | keep-internal |  | test code |

### `web/electron/test/loginShellPath.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | … START = "__OMNIGENT_PATH_START__"; | keep-internal |  | test code |
| 22 | const END = "__OMNIGENT_PATH_END__"; | keep-internal |  | test code |

### `web/electron/test/main.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 49 | …nd the real databricks-session module:… | keep-internal |  | test code |
| 82 | … blocked by Databricks IP ACL for work… | keep-internal |  | test code |
| 101 | isTrustedDatabricksOrigin: urlHelpers.… | keep-internal |  | test code |
| 110 | …me, "../src/databricks-session.js"); | keep-internal |  | test code |
| 114 | "./databricks-oauth": oauth, | keep-internal |  | test code |
| 115 | "./databricks-account": { parseAccount… | keep-internal |  | test code |
| 130 | …twork.ensureDatabricksSession = module… | keep-internal |  | test code |
| 138 | ….example/ml/omnigents", | keep-internal |  | test code |
| 141 | databricksMode = "embedded", | keep-internal |  | test code |
| 175 | ….tmpdir(), "omnigent-navigation-test-"… | keep-internal |  | test code |
| 475 | expandDatabricksWorkspaceUrl: expandWo… | keep-internal |  | test code |
| 485 | getDatabricksInternalFeaturesEnabled: … | keep-internal |  | test code |
| 489 | parseOmnigentDeepLink: () => null, | keep-internal |  | test code |
| 550 | "./databricks-session": { | keep-internal |  | test code |
| 551 | ensureDatabricksSession: (...args) => … | keep-internal |  | test code |
| 553 | …work?.ensureDatabricksSession ?? ensur… | keep-internal |  | test code |
| 556 | "./databricks-oauth": { | keep-internal |  | test code |
| 592 | "./databricks-auth": { | keep-internal |  | test code |
| 593 | ...require("../src/databricks-auth"), | keep-internal |  | test code |
| 594 | readDatabricksAuthMode: () => databric… | keep-internal |  | test code |
| 664 | "./omnigent_cli": { | keep-internal |  | test code |
| 667 | …ire("../src/omnigent_cli").cliCommandP… | keep-internal |  | test code |
| 668 | …ire("../src/omnigent_cli").normalizeSe… | keep-internal |  | test code |
| 704 | "\nmodule.exports.testApi = { handleDe | keep-internal |  | test code |
| 721 | …rocess.env, OMNIGENT_SERVER_SELECTOR_V… | keep-internal |  | test code |
| 787 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 795 | … h.ipc.get("omnigent:arca-extend"); | keep-internal |  | test code |
| 806 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 810 | … h.ipc.get("omnigent:arca-extend"); | keep-internal |  | test code |
| 811 | … h.ipc.get("omnigent:get-desktop-featu… | keep-internal |  | test code |
| 816 | databricksInternalFeatures: true, | keep-internal |  | test code |
| 840 | …space.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 845 | …(h.ipc.get("omnigent:get-desktop-featu… | keep-internal |  | test code |
| 846 | … h.ipc.get("omnigent:arca-extend")(eve… | keep-internal |  | test code |
| 856 | …(h.ipc.get("omnigent:get-desktop-featu… | keep-internal |  | test code |
| 857 | … h.ipc.get("omnigent:arca-extend")(eve… | keep-internal |  | test code |
| 863 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 881 | … h.ipc.get("omnigent:dbcert-refresh"); | keep-internal |  | test code |
| 912 | …ss.ipc.get("omnigent:dbcert-refresh"); | keep-internal |  | test code |
| 965 | …ss.ipc.get("omnigent:dbcert-refresh"); | keep-internal |  | test code |
| 982 | h.ipc.get("omnigent:dbcert-refresh")({ | keep-internal |  | test code |
| 990 | h.ipc.get("omnigent:dbcert-check")({ | keep-internal |  | test code |
| 1012 | … h.ipc.get("omnigent:dbcert-check"); | keep-internal |  | test code |
| 1046 | …ss.ipc.get("omnigent:dbcert-check"); | keep-internal |  | test code |
| 1053 | …ss.ipc.get("omnigent:dbcert-refresh")(… | keep-internal |  | test code |
| 1075 | …ine without Databricks-internal featur… | keep-internal |  | test code |
| 1082 | …(h.ipc.get("omnigent:get-desktop-featu… | keep-internal |  | test code |
| 1083 | … h.ipc.get("omnigent:dbcert-refresh")(… | keep-internal |  | test code |
| 1085 | … h.ipc.get("omnigent:dbcert-check")(ev… | keep-internal |  | test code |
| 1092 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 1102 | … workspace, databricksMode: "browser",… | keep-internal |  | test code |
| 1116 | databricksMode: "browser", | keep-internal |  | test code |
| 1124 | … h.ipc.get("omnigent:arca-connect")({ | keep-internal |  | test code |
| 1140 | databricksMode: "browser", | keep-internal |  | test code |
| 1157 | … h.ipc.get("omnigent:arca-connect")({ | keep-internal |  | test code |
| 1177 | …ounts.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 1180 | databricksMode: "browser", | keep-internal |  | test code |
| 1194 | … h.ipc.get("omnigent:connect-runner")( | keep-internal |  | test code |
| 1201 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 1205 | … h.ipc.get("omnigent:take-onboarding-r… | keep-internal |  | test code |
| 1217 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 1248 | h.ipc.get("omnigent:connect-runner")( | keep-internal |  | test code |
| 1256 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 1343 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 1344 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 1401 | …other.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 1467 | … connect on Databricks servers, even t… | keep-internal |  | test code |
| 1478 | … h.ipc.get("omnigent:arca-connect")({ | keep-internal |  | test code |
| 1482 | …ult.error, /Databricks-managed servers… | keep-internal |  | test code |
| 1488 | … workspace, databricksMode: "browser",… | keep-internal |  | test code |
| 1495 | …rns on with OMNIGENT_ARCA_AUTO_CONNECT… | keep-internal |  | test code |
| 1496 | process.env.OMNIGENT_ARCA_AUTO_CONNECT… | keep-internal |  | test code |
| 1499 | … workspace, databricksMode: "browser",… | keep-internal |  | test code |
| 1501 | …process.env.OMNIGENT_ARCA_AUTO_CONNECT… | keep-internal |  | test code |
| 1510 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 1518 | …that aren't Databricks-managed", async… | keep-internal |  | test code |
| 1529 | describe("Databricks auth mode wiring"… | keep-internal |  | test code |
| 1530 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 1532 | …uth and the Omnigent mount", async (t)… | keep-internal |  | test code |
| 1533 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 1535 | …({ server: "databricks" }) }); | keep-internal |  | test code |
| 1541 | databricksMode: "browser", | keep-internal |  | test code |
| 1543 | …lpers.expandDatabricksWorkspaceUrl, | keep-internal |  | test code |
| 1547 | … h.ipc.get("omnigent:set-server-url")( | keep-internal |  | test code |
| 1549 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 1553 | …space.cloud.databricks.com"); | keep-internal |  | test code |
| 1554 | …space.cloud.databricks.com"); | keep-internal |  | test code |
| 1565 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 1577 | databricksMode: "browser", | keep-internal |  | test code |
| 1591 | … sign in to Databricks. Please try aga… | keep-internal |  | test code |
| 1599 | databricksMode: "browser", | keep-internal |  | test code |
| 1618 | …/spog.cloud.databricks.com/?o=123"; | keep-internal |  | test code |
| 1622 | databricksMode: "browser", | keep-internal |  | test code |
| 1649 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 1655 | … h.ipc.get("omnigent:get-server-picker… | keep-internal |  | test code |
| 1681 | … h.ipc.get("omnigent:sign-out-of-serve… | keep-internal |  | test code |
| 1695 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 1724 | databricksMode: "browser", | keep-internal |  | test code |
| 1749 | … h.ipc.get("omnigent:sign-out-of-serve… | keep-internal |  | test code |
| 1762 | databricksMode: "browser", | keep-internal |  | test code |
| 1787 | … h.ipc.get("omnigent:sign-out-of-serve… | keep-internal |  | test code |
| 1806 | databricksMode: "browser", | keep-internal |  | test code |
| 1848 | databricksMode: "browser", | keep-internal |  | test code |
| 1858 | … h.ipc.get("omnigent:sign-out-of-serve… | keep-internal |  | test code |
| 1869 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 1874 | h.ipc.get("omnigent:sign-out-of-server… | keep-internal |  | test code |
| 1890 | databricksMode: "browser", | keep-internal |  | test code |
| 1912 | …ldn't reach Databricks.", "Databricks … | keep-internal |  | test code |
| 1917 | … sign in to Databricks. Please try aga… | keep-internal |  | test code |
| 1918 | …vailable = "Databricks isn't respondin… | keep-internal |  | test code |
| 1936 | databricksMode: "browser", | keep-internal |  | test code |
| 1979 | databricksMode: "browser", | keep-internal |  | test code |
| 2007 | env: { OMNIGENT_SERVER_SELECTOR_V2: v2… | keep-internal |  | test code |
| 2011 | databricksMode: "browser", | keep-internal |  | test code |
| 2029 | … h.ipc.get("omnigent:set-server-url")( | keep-internal |  | test code |
| 2041 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 2045 | databricksMode: "browser", | keep-internal |  | test code |
| 2052 | …space.cloud.databricks.com"); | keep-internal |  | test code |
| 2059 | …ttps://demo.databricksapps.com", "brow… | keep-internal |  | test code |
| 2062 | …erUrl: url, databricksMode: mode }); | keep-internal |  | test code |
| 2073 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 2096 | databricksMode: "browser", | keep-internal |  | test code |
| 2148 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 2159 | … workspace, databricksMode: "embedded"… | keep-internal |  | test code |
| 2172 | … workspace, databricksMode: "browser" … | keep-internal |  | test code |
| 2179 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2184 | … h.ipc.get("omnigent:switch-server")( | keep-internal |  | test code |
| 2194 | …ounts.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 2195 | …ounts.cloud.databricks.com/?o=123"; | keep-internal |  | test code |
| 2210 | databricksMode: "browser", | keep-internal |  | test code |
| 2216 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2226 | … h.ipc.get("omnigent:get-recent-server… | keep-internal |  | test code |
| 2229 | … h.ipc.get("omnigent:get-server-url")(… | keep-internal |  | test code |
| 2230 | … h.ipc.get("omnigent:get-server-picker… | keep-internal |  | test code |
| 2239 | … h.ipc.get("omnigent:get-recent-server… | keep-internal |  | test code |
| 2244 | … h.ipc.get("omnigent:get-recent-server… | keep-internal |  | test code |
| 2255 | … h.ipc.get("omnigent:forget-recent-ser… | keep-internal |  | test code |
| 2261 | …ounts.cloud.databricks.com/?o=456"], | keep-internal |  | test code |
| 2263 | … h.ipc.get("omnigent:get-recent-server… | keep-internal |  | test code |
| 2270 | … h.ipc.get("omnigent:forget-recent-ser… | keep-internal |  | test code |
| 2281 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2283 | … h.ipc.get("omnigent:get-recent-server… | keep-internal |  | test code |
| 2291 | databricksMode: "browser", | keep-internal |  | test code |
| 2298 | …(h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2304 | …ounts.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 2307 | databricksMode: "browser", | keep-internal |  | test code |
| 2322 | …ounts.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 2325 | databricksMode: "browser", | keep-internal |  | test code |
| 2350 | databricksMode: "browser", | keep-internal |  | test code |
| 2360 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2368 | …(h.ipc.get("omnigent:cancel-server-con… | keep-internal |  | test code |
| 2370 | h.ipc.get("omnigent:cancel-server-conn… | keep-internal |  | test code |
| 2375 | h.ipc.get("omnigent:cancel-server-conn… | keep-internal |  | test code |
| 2385 | …(h.ipc.get("omnigent:cancel-server-con… | keep-internal |  | test code |
| 2397 | databricksMode: "browser", | keep-internal |  | test code |
| 2408 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2411 | h.ipc.get("omnigent:cancel-server-conn… | keep-internal |  | test code |
| 2426 | databricksMode: "browser", | keep-internal |  | test code |
| 2435 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2437 | h.ipc.get("omnigent:cancel-server-conn… | keep-internal |  | test code |
| 2438 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 2440 | …(h.ipc.get("omnigent:cancel-server-con… | keep-internal |  | test code |
| 2473 | databricksMode: "browser", | keep-internal |  | test code |
| 2492 | …ver.example/omnigent"; | keep-internal |  | test code |
| 2733 | …r\.invoke\("omnigent:copy-setup-text",… | keep-internal |  | test code |
| 2740 | …n\.handle\("omnigent:copy-setup-text",… | keep-internal |  | test code |
| 2758 | … h.ipc.get("omnigent:copy-setup-text")… | keep-internal |  | test code |
| 2761 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 2762 | ….example/ml/omnigents"]); | keep-internal |  | test code |
| 2783 | …r\.invoke\("omnigent:get-managed-serve… | keep-internal |  | test code |
| 2787 | …n\.handle\("omnigent:get-managed-serve… | keep-internal |  | test code |
| 2794 | …r\.invoke\("omnigent:get-runner-option… | keep-internal |  | test code |
| 2798 | …n\.handle\("omnigent:get-runner-option… | keep-internal |  | test code |
| 2805 | …r\.invoke\("omnigent:connect-runner",\… | keep-internal |  | test code |
| 2809 | …ain.handle("omnigent:connect-runner"')… | keep-internal |  | test code |
| 2810 | …ain.handle("omnigent:copy-setup-text"'… | keep-internal |  | test code |
| 2822 | …r\.invoke\("omnigent:take-onboarding-r… | keep-internal |  | test code |
| 2829 | …0,160}expandDatabricksWorkspaceUrl\(ma… | keep-internal |  | test code |
| 2833 | …n\.handle\("omnigent:set-server-url"[\… | keep-internal |  | test code |
| 2848 | … ˋ${managed}omnigentˋ] }), | keep-internal |  | test code |
| 2850 | … h.ipc.get("omnigent:get-server-picker… | keep-internal |  | test code |
| 2870 | … h.ipc.get("omnigent:get-managed-serve… | keep-internal |  | test code |
| 2885 | …n\.handle\("omnigent:switch-server"[\s… | keep-internal |  | test code |
| 2895 | describe("Databricks-internal local-ho… | keep-internal |  | test code |
| 2896 | …al flag and Databricks server gate", (… | keep-internal |  | test code |
| 2899 | …\s\S]{0,300}databricksInternalFeatures… | keep-internal |  | test code |
| 2917 | /omnigent:set-cli-path[\s\S]{0,300}dat… | keep-internal |  | test code |
| 2921 | /omnigent:browse-cli-path[\s\S]{0,250}… | keep-internal |  | test code |
| 2925 | /omnigent:cli-reset-path[\s\S]{0,250}d… | keep-internal |  | test code |
| 2998 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3013 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3016 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3017 | ….example/ml/omnigents", 200, "OK"); | keep-internal |  | test code |
| 3023 | …ession: the Databricks workspace login… | keep-internal |  | test code |
| 3029 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3033 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3034 | ….example/ml/omnigents", 200, "OK"); | keep-internal |  | test code |
| 3035 | …url=%2Fml%2Fomnigents"); | keep-internal |  | test code |
| 3038 | …url=%2Fml%2Fomnigents", | keep-internal |  | test code |
| 3049 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3051 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3052 | ….example/ml/omnigents", 200, "OK"); | keep-internal |  | test code |
| 3059 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3064 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3065 | ….example/ml/omnigents", 200, "OK"); | keep-internal |  | test code |
| 3083 | …to hide the Databricks workspace", | keep-internal |  | test code |
| 3085 | …gate out of Omnigent into other worksp… | keep-internal |  | test code |
| 3099 | …SS targets .omnigent-app (workspace-em… | keep-internal |  | test code |
| 3147 | env: { OMNIGENT_SERVER_SELECTOR_V2_DEV… | keep-internal |  | test code |
| 3174 | env: { OMNIGENT_SERVER_SELECTOR_V2_DEV… | keep-internal |  | test code |
| 3200 | h.ipc.get("omnigent:set-server-selecto… | keep-internal |  | test code |
| 3223 | env: { OMNIGENT_SERVER_SELECTOR_V2: "1… | keep-internal |  | test code |
| 3236 | …ots a saved Databricks API URL on the … | keep-internal |  | test code |
| 3237 | …space.cloud.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 3247 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 3255 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3256 | ….example/ml/omnigents/", 503, "Unavail… | keep-internal |  | test code |
| 3279 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3281 | …url=%2Fml%2Fomnigents"); | keep-internal |  | test code |
| 3284 | …url=%2Fml%2Fomnigents", | keep-internal |  | test code |
| 3295 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3299 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3300 | ….example/ml/omnigents", 200, "OK"); | keep-internal |  | test code |
| 3434 | "https://host.example/omnigent", | keep-internal |  | test code |
| 3436 | …example.com/omnigent", | keep-internal |  | test code |
| 3440 | … h.ipc.get("omnigent:get-recent-server… | keep-internal |  | test code |
| 3455 | …n\.handle\("omnigent:get-setup-capabil… | keep-internal |  | test code |
| 3462 | …n\.handle\("omnigent:get-cli-status"[\… | keep-internal |  | test code |
| 3468 | …ace mount (/omnigent), so it | keep-internal |  | test code |
| 3480 | … (origin + /omnigent", | keep-internal |  | test code |
| 3488 | …NTITY (for ˋomnigent host --serverˋ et… | keep-internal |  | test code |
| 3496 | …ath out of ˋomnigent host --serverˋ.", | keep-internal |  | test code |
| 3523 | const url = "omnigent://localhost:6767/"; | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3527 | …hannel === "omnigent:open-path"), | keep-internal |  | test code |
| 3528 | …{ channel: "omnigent:open-path", data:… | keep-internal |  | test code |
| 3550 | it("scans second-instance argv for omnigent:// and enqueues as live code", () => { | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3553 | /app\.on\("second-instance"[\s\S]{0,220}startsWith\("omnigent:\/\/"\)[\s\S]{0,60}enqueueDeepLink\(/, | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3555 | …ce argv for omnigent://. Windows/Linux… | keep-internal |  | test code |
| 3562 | it("registers the omnigent:// scheme as live code", () => { | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3565 | /setAsDefaultProtocolClient\("omnigent"\)/, | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3567 | …ocolClient('omnigent'), so dev", | keep-internal |  | test code |
| 3568 | …licks on an omnigent:// link won't rou… | keep-internal |  | test code |
| 3598 | …through the omnigent:open-path channel… | keep-internal |  | test code |
| 3601 | /send\("omnigent:open-path"/, | keep-internal |  | test code |
| 3603 | …onger sends omnigent:open-path to the … | keep-internal |  | test code |
| 3605 | …tents.send('omnigent:open-path', path)… | keep-internal |  | test code |
| 3635 | …robe (expandDatabricksWorkspaceUrl) ma… | keep-internal |  | test code |
| 3643 | …0,300}expandDatabricksWorkspaceUrl\(ta… | keep-internal |  | test code |
| 3645 | …efers expandDatabricksWorkspaceUrl unt… | keep-internal |  | test code |
| 3655 | …0,500}expandDatabricksWorkspaceUrl\(/, | keep-internal |  | test code |
| 3657 | "expandDatabricksWorkspaceUrl reappear… | keep-internal |  | test code |
| 3681 | ….example/ml/omnigents/health", 404, "N… | keep-internal |  | test code |
| 3688 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3695 | ….example/ml/omnigents/", 503, "Service… | keep-internal |  | test code |
| 3701 | ….example/ml/omnigents"); | keep-internal |  | test code |
| 3708 | ….example/ml/omnigents/", 200, "OK"); | keep-internal |  | test code |
| 3709 | ….example/ml/omnigents/login", 302, "Fo… | keep-internal |  | test code |
| 3719 | ….example/ml/omnigents/health"; | keep-internal |  | test code |
| 3730 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 3735 | databricksMode: "browser", | keep-internal |  | test code |
| 3747 | …(ˋretries a Databricks workspace's ${c… | keep-internal |  | test code |
| 3751 | …rlay.hint, "Databricks isn't respondin… | keep-internal |  | test code |
| 3788 | …lback for a Databricks 404 and other s… | keep-internal |  | test code |
| 3794 | ….example/ml/omnigents/", 503, "Service… | keep-internal |  | test code |
| 3816 | "https://host.example/ml/omnigents/", | keep-internal |  | test code |
| 3824 | ….example/ml/omnigents/", true); | keep-internal |  | test code |
| 3830 | // While a Databricks workspace is unr… | keep-internal |  | test code |
| 3832 | describe("Databricks reconnect overlay… | keep-internal |  | test code |
| 3833 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 3844 | databricksMode: "browser", | keep-internal |  | test code |
| 3943 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 3959 | …({ server: "databricks" }) }; | keep-internal |  | test code |
| 3966 | …lpers.expandDatabricksWorkspaceUrl, | keep-internal |  | test code |
| 3981 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 4003 | …rlay.hint, "Databricks isn't respondin… | keep-internal |  | test code |
| 4012 | … blocked = "Databricks blocked this ne… | keep-internal |  | test code |
| 4113 | …ldn't reach Databricks. Check your net… | keep-internal |  | test code |
| 4123 | "Databricks blocked this network. Conn… | keep-internal |  | test code |
| 4146 | …ed.ipc.get("omnigent:set-server-url")( | keep-internal |  | test code |
| 4184 | databricksMode: "embedded", | keep-internal |  | test code |
| 4214 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 4216 | … blocked = "Databricks blocked this ne… | keep-internal |  | test code |
| 4224 | databricksMode: "browser", | keep-internal |  | test code |
| 4239 | …next_url=%2Fomnigentˋ, | keep-internal |  | test code |
| 4342 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 4371 | …/spog.cloud.databricks.com/?o=123"; | keep-internal |  | test code |
| 4384 | databricksMode: "browser", | keep-internal |  | test code |
| 4393 | h.ipc.get("omnigent:set-server-url")( | keep-internal |  | test code |
| 4427 | …/spog.cloud.databricks.com/"; | keep-internal |  | test code |
| 4447 | …accountUrl, databricksMode: "browser",… | keep-internal |  | test code |
| 4456 | …ldn't reach Databricks. Check your net… | keep-internal |  | test code |
| 4470 | … sign in to Databricks. Please try aga… | keep-internal |  | test code |
| 4487 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4495 | … h.ipc.get("omnigent:get-desktop-featu… | keep-internal |  | test code |
| 4502 | databricksInternalFeatures: true, | keep-internal |  | test code |
| 4514 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4515 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4538 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4585 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4634 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4674 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4699 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4737 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4767 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4772 | databricksMode: "browser", | keep-internal |  | test code |
| 4798 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4826 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4861 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 4920 | ….example/ml/omnigents"; | keep-internal |  | test code |
| 4948 | … h.ipc.get("omnigent:connect-runner"); | keep-internal |  | test code |
| 4960 | … h.ipc.get("omnigent:get-runner-option… | keep-internal |  | test code |
| 4968 | …(h.ipc.get("omnigent:get-runner-option… | keep-internal |  | test code |
| 4972 | … h.ipc.get("omnigent:connect-runner")(… | keep-internal |  | test code |
| 4980 | … h.ipc.get("omnigent:connect-runner")(… | keep-internal |  | test code |
| 4982 | …ssage, "The omnigent CLI was not found… | keep-internal |  | test code |
| 4988 | ….example/ml/omnigents didn't complete.… | keep-internal |  | test code |
| 4992 | cliPath: "/usr/local/bin/omnigent", | keep-internal |  | test code |
| 4997 | … h.ipc.get("omnigent:connect-runner")(… | keep-internal |  | test code |
| 5003 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 5014 | …r/local/bin/omnigent" }, | keep-internal |  | test code |
| 5024 | …ed.ipc.get("omnigent:connect-runner")(… | keep-internal |  | test code |
| 5030 | …ed.ipc.get("omnigent:connect-runner")(… | keep-internal |  | test code |
| 5048 | … h.ipc.get("omnigent:connect-runner")( | keep-internal |  | test code |
| 5068 | … h.ipc.get("omnigent:take-onboarding-r… | keep-internal |  | test code |
| 5076 | … h.ipc.get("omnigent:take-onboarding-r… | keep-internal |  | test code |
| 5104 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 5107 | databricksMode: "browser", | keep-internal |  | test code |
| 5118 | assert.equal(h.calls.loading.at(-1).label, "Opening Omnigent…"); | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 5140 | assert.equal(shown.label, "Opening Omnigent…"); | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 5183 | assert.equal(shown.label, "Opening Omnigent…"); | change | S38,S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 5399 | … h.ipc.get("omnigent:get-server-picker… | keep-internal |  | test code |
| 5400 | … h.ipc.get("omnigent:sign-out-of-serve… | keep-internal |  | test code |
| 5458 | … h.ipc.get("omnigent:get-server-picker… | keep-internal |  | test code |
| 5459 | … h.ipc.get("omnigent:sign-out-of-serve… | keep-internal |  | test code |
| 5523 | it("keeps Databricks detection URL-bas… | keep-internal |  | test code |
| 5526 | …://ws.cloud.databricks.com/omnigent", … | keep-internal |  | test code |
| 5527 | …app-123.aws.databricksapps.com", "brow… | keep-internal |  | test code |
| 5528 | …://ws.cloud.databricks.com/omnigent", … | keep-internal |  | test code |
| 5533 | databricksMode: mode, | keep-internal |  | test code |
| 5577 | …hannel === "omnigent:find-opened"); | keep-internal |  | test code |
| 5618 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 5620 | … h.ipc.get("omnigent:get-server-names"… | keep-internal |  | test code |
| 5624 | … h.ipc.get("omnigent:get-server-picker… | keep-internal |  | test code |
| 5650 | … h.ipc.get("omnigent:forget-recent-ser… | keep-internal |  | test code |
| 5711 | … h.ipc.get("omnigent:notify")(pageEven… | keep-internal |  | test code |
| 5727 | … h.ipc.get("omnigent:set-server-url")(… | keep-internal |  | test code |
| 5735 | … h.ipc.get("omnigent:get-server-names"… | keep-internal |  | test code |
| 5748 | … h.ipc.get("omnigent:get-server-names"… | keep-internal |  | test code |
| 5766 | ….example/ml/omnigents"; | keep-internal |  | test code |
| 5781 | … h.ipc.get("omnigent:ssh-connect"); | keep-internal |  | test code |
| 5795 | … h.ipc.get("omnigent:ssh-connect")(fro… | keep-internal |  | test code |
| 5806 | …space.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 5808 | …laptop on a Databricks server, which o… | keep-internal |  | test code |
| 5809 | …laptop on a Databricks server": [manag… | keep-internal |  | test code |
| 5817 | … h.ipc.get("omnigent:ssh-connect")(eve… | keep-internal |  | test code |
| 5837 | … h.ipc.get("omnigent:ssh-connect")(eve… | keep-internal |  | test code |
| 5844 | …tself, run "omnigent host" there.ˋ, | keep-internal |  | test code |
| 5856 | ["omnigent:ssh-connect"], | keep-internal |  | test code |
| 5940 | h.ipc.get("omnigent:set-desktop-comman… | keep-internal |  | test code |
| 5943 | …hannel === "omnigent:desktop-command")… | keep-internal |  | test code |

### `web/electron/test/managed_preferences.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | DATABRICKS_INTERNAL_FEATURES_KEY, | keep-internal |  | test code |
| 10 | getDatabricksInternalFeaturesEnabled, | keep-internal |  | test code |
| 23 | return ["omnigent.example.com", "https… | keep-internal |  | test code |
| 29 | "https://omnigent.example.com/", | keep-internal |  | test code |
| 30 | …mple.com/ml/omnigents?o=123", | keep-internal |  | test code |
| 40 | …n ["https://omnigent.example.com"]; | keep-internal |  | test code |
| 51 | …mple.com/ml/omnigents", | keep-internal |  | test code |
| 55 | …mple.com/ml/omnigents", "https://other… | keep-internal |  | test code |
| 60 | …ls("https://omnigent.example.com"), []… | keep-internal |  | test code |
| 83 | …("reads the Databricks-internal-featur… | keep-internal |  | test code |
| 85 | …nabled = getDatabricksInternalFeatures… | keep-internal |  | test code |
| 93 | …al(calls, [[DATABRICKS_INTERNAL_FEATUR… | keep-internal |  | test code |
| 101 | getDatabricksInternalFeaturesEnabled({ | keep-internal |  | test code |
| 114 | getDatabricksInternalFeaturesEnabled({ | keep-internal |  | test code |
| 123 | getDatabricksInternalFeaturesEnabled({ | keep-internal |  | test code |
| 133 | …mes from an omnigentServerName query p… | keep-internal |  | test code |
| 138 | ….com/?o=123&omnigentServerName=%20Team… | keep-internal |  | test code |
| 139 | …mple.com/ml?omnigentServerName=", | keep-internal |  | test code |
| 161 | …e.com/other?omnigentServerName=Dropped… | keep-internal |  | test code |
| 167 | …xample.com/?omnigentServerName=Team", … | keep-internal |  | test code |
| 183 | …mple.com/ml/omnigents"], | keep-internal |  | test code |

### `web/electron/test/notarizeDmg.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 43 | …zeDmg("dist/Omnigent.dmg", ["--key", "… | keep-internal |  | test code |
| 47 | …e=2", "dist/Omnigent.dmg"], | keep-internal |  | test code |
| 54 | "dist/Omnigent.dmg", | keep-internal |  | test code |
| 64 | …"-v", "dist/Omnigent.dmg"], | keep-internal |  | test code |
| 68 | …"-v", "dist/Omnigent.dmg"], | keep-internal |  | test code |
| 78 | …zeDmg("dist/Omnigent.dmg", [], run), /… | keep-internal |  | test code |

### `web/electron/test/oidc-credentials.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 43 | …(tmpHome, ".omnigent", "oidc_tokens.js… | keep-internal |  | test code |
| 96 | …ps://h.test/omnigent/?x=1#y", "/v1/me"… | keep-internal |  | test code |
| 97 | "https://h.test/omnigent/v1/me", | keep-internal |  | test code |

### `web/electron/test/omnigent_cli.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …pers in src/omnigent_cli.js, run with … | keep-internal |  | test code |
| 5 | … and "which omnigent binary do we run?… | keep-internal |  | test code |
| 35 | } = require("../src/omnigent_cli"); | keep-internal |  | test code |
| 39 | …Parts("/bin/omnigent"), { | keep-internal |  | test code |
| 40 | executable: "/bin/omnigent", | keep-internal |  | test code |
| 42 | displayName: "omnigent", | keep-internal |  | test code |
| 103 | ….tmpdir(), "omnigent-no-such-cli", "om… | keep-internal |  | test code |
| 114 | …://x.com/ml/omnigents"), "https://x.co… | keep-internal |  | test code |
| 132 | …s://example.databricksapps.com"), fals… | keep-internal |  | test code |
| 168 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | test code |
| 170 | …process.env.OMNIGENT_DATA_DIR; | keep-internal |  | test code |
| 171 | …process.env.OMNIGENT_DATA_DIR = prevDa… | keep-internal |  | test code |
| 176 | ….tmpdir(), "omnigent-pidfile-test-")); | keep-internal |  | test code |
| 178 | process.env.OMNIGENT_DATA_DIR = dir; | keep-internal |  | test code |
| 231 | …es both the omnigent name and the omni… | keep-internal |  | test code |
| 233 | …ributes an ˋomnigentˋ and an ˋomniˋ en… | keep-internal |  | test code |
| 234 | …/.local/bin/omnigent"))); | keep-internal |  | test code |
| 236 | …omebrew/bin/omnigent")); | keep-internal |  | test code |
| 241 | …e canonical omnigent name before the o… | keep-internal |  | test code |
| 243 | …omebrew/bin/omnigent"); | keep-internal |  | test code |
| 253 | whichOmnigent: () => null, | keep-internal |  | test code |
| 254 | …/.local/bin/omnigent", "/home/me/.loca… | keep-internal |  | test code |
| 260 | …th("/custom/omnigent", { | keep-internal |  | test code |
| 261 | …== "/custom/omnigent", | keep-internal |  | test code |
| 262 | whichOmnigent: () => "/usr/bin/omnigen… | keep-internal |  | test code |
| 263 | …/.local/bin/omnigent"], | keep-internal |  | test code |
| 265 | …h: "/custom/omnigent", source: "config… | keep-internal |  | test code |
| 270 | …= "/usr/bin/omnigent", | keep-internal |  | test code |
| 271 | whichOmnigent: () => "/usr/bin/omnigen… | keep-internal |  | test code |
| 272 | …/.local/bin/omnigent"], | keep-internal |  | test code |
| 274 | …: "/usr/bin/omnigent", source: "path" … | keep-internal |  | test code |
| 279 | …/.local/bin/omnigent", | keep-internal |  | test code |
| 280 | whichOmnigent: () => null, | keep-internal |  | test code |
| 281 | …/.local/bin/omnigent", "/opt/homebrew/… | keep-internal |  | test code |
| 283 | …/.local/bin/omnigent", source: "candid… | keep-internal |  | test code |
| 289 | whichOmnigent: () => null, | keep-internal |  | test code |
| 426 | …process.env.OMNIGENT_REMOTE_AUTH_TOKEN… | keep-internal |  | test code |
| 459 | …er attaches OMNIGENT_REMOTE_AUTH_TOKEN… | keep-internal |  | test code |
| 463 | process.env.OMNIGENT_REMOTE_AUTH_TOKEN… | keep-internal |  | test code |
| 508 | …0 statuses (Databricks 302, opaque-red… | keep-internal |  | test code |
| 512 | // Databricks-edge 302 to the workspac… | keep-internal |  | test code |
| 536 | … none for a Databricks pointer", async… | keep-internal |  | test code |
| 552 | // Databricks pointer → no in-process … | keep-internal |  | test code |
| 555 | …auth_type: "databricks", workspace_hos… | keep-internal |  | test code |
| 653 | …ample.cloud.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 654 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 657 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 658 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 673 | ….headers["X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 676 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 683 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 684 | … = "https://omnigent.example.com"; | keep-internal |  | test code |
| 688 | process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 694 | process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 701 | …process.env.OMNIGENT_HOST_SLICE_KEY_EN… | keep-internal |  | test code |
| 704 | …ample.cloud.databricks.com/omnigent"),… | keep-internal |  | test code |

### `web/electron/test/popupPolicy.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …space.cloud.databricks.com"; | keep-internal |  | test code |

### `web/electron/test/preload_update.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | …hannel === "omnigent:get-update-status… | keep-internal |  | test code |
| 40 | …xposed.get("omnigentDesktop"), | keep-internal |  | test code |
| 55 | …{ channel: "omnigent:choose-directory"… | keep-internal |  | test code |
| 59 | channel: "omnigent:dropped-file-path", | keep-internal |  | test code |
| 71 | …l(channel, "omnigent:browser-perform-a… | keep-internal |  | test code |
| 76 | …).channel, "omnigent:browser-execute")… | keep-internal |  | test code |
| 116 | …hannel === "omnigent:browser-cancel-re… | keep-internal |  | test code |
| 128 | …hannel === "omnigent:browser-set-recen… | keep-internal |  | test code |
| 141 | h.emit("omnigent:desktop-command", { | keep-internal |  | test code |
| 146 | h.emit("omnigent:desktop-command", { c… | keep-internal |  | test code |
| 147 | h.emit("omnigent:desktop-command", { | keep-internal |  | test code |
| 151 | h.emit("omnigent:desktop-command", { c… | keep-internal |  | test code |
| 152 | h.emit("omnigent:desktop-command", { c… | keep-internal |  | test code |
| 153 | h.emit("omnigent:desktop-command", nul… | keep-internal |  | test code |
| 172 | …asListener("omnigent:desktop-command")… | keep-internal |  | test code |
| 185 | channel: "omnigent:set-desktop-command… | keep-internal |  | test code |
| 189 | channel: "omnigent:set-desktop-command… | keep-internal |  | test code |
| 195 | …{ channel: "omnigent:close-window", ar… | keep-internal |  | test code |
| 199 | channel: "omnigent:confirm-quit", | keep-internal |  | test code |
| 212 | channel: "omnigent:browser-set-active"… | keep-internal |  | test code |
| 216 | channel: "omnigent:browser-set-active"… | keep-internal |  | test code |
| 225 | …).channel, "omnigent:browser-focused-v… | keep-internal |  | test code |
| 234 | …).channel, "omnigent:get-global-shortc… | keep-internal |  | test code |
| 238 | channel: "omnigent:set-global-shortcut… | keep-internal |  | test code |
| 244 | channel: "omnigent:set-global-shortcut… | keep-internal |  | test code |
| 254 | …).channel, "omnigent:record-global-sho… | keep-internal |  | test code |
| 256 | …).channel, "omnigent:cancel-global-sho… | keep-internal |  | test code |

### `web/electron/test/quitConfirmation.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | appName: () => "Omnigent", | keep-internal |  | test code |
| 59 | "The local Omnigent server will stop.", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 63 | "Sessions running on this computer will go offline, and the local Omnigent server will stop.", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 142 | …abel, "Quit Omnigent"); | keep-internal |  | test code |

### `web/electron/test/reconnect_overlay.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 87 | …ndlers.get("omnigent:reconnect-overlay… | keep-internal |  | test code |
| 187 | dom.window.omnigentReconnectOverlay = … | keep-internal |  | test code |
| 194 | …nnecting to Databricks…"); | keep-internal |  | test code |

### `web/electron/test/server_labels.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …ounts.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 13 | …-1234.cloud.databricks.com"; | keep-internal |  | test code |
| 14 | …-5678.cloud.databricks.com"; | keep-internal |  | test code |
| 33 | …{WORKSPACE}/omnigentˋ), PICKED); | keep-internal |  | test code |
| 42 | …ounts.cloud.databricks.com/?o=456", [W… | keep-internal |  | test code |
| 46 | …ounts.cloud.databricks.com/?o=123"), | keep-internal |  | test code |
| 49 | …ounts.cloud.databricks.com/?o=456"), O… | keep-internal |  | test code |
| 51 | …ounts.cloud.databricks.com/omnigent"),… | keep-internal |  | test code |
| 52 | …ounts.cloud.databricks.com/?o=789"), n… | keep-internal |  | test code |
| 53 | …other.cloud.databricks.com/?o=123"), n… | keep-internal |  | test code |
| 58 | …{WORKSPACE}/omnigentˋ, ˋ${OTHER}/omnig… | keep-internal |  | test code |
| 59 | …{WORKSPACE}/omnigentˋ, recents); | keep-internal |  | test code |
| 61 | …{WORKSPACE}/omnigentˋ, recents), { | keep-internal |  | test code |
| 68 | …{WORKSPACE}/omnigentˋ, [WORKSPACE]), { | keep-internal |  | test code |

### `web/electron/test/server_manager.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …ptures the ˋomnigent_cliˋ module objec… | keep-internal |  | test code |
| 15 | …ire("../src/omnigent_cli"); | keep-internal |  | test code |
| 19 | const CLI_PATH = "/bin/omnigent"; | keep-internal |  | test code |
| 26 | …s://account.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 116 | // ˋomnigent loginˋ stdout on the OIDC… | keep-internal |  | test code |
| 133 | …in (or run ˋomnigent login https://app… | keep-internal |  | test code |
| 137 | …res.error, /omnigent login https:\/\/a… | keep-internal |  | test code |
| 149 | …res.error, /omnigent login https:\/\/a… | keep-internal |  | test code |
| 166 | "Run ˋomnigent login https://app.examp… | keep-internal |  | test code |
| 216 | ….tmpdir(), "omnigent-login-fixture-"))… | keep-internal |  | test code |
| 305 | …ample.com: ˋomnigentˋ couldn't be run … | keep-internal |  | test code |

### `web/electron/test/session-expiry.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …ive expired Databricks SSO session): e… | keep-internal |  | test code |
| 20 | …dbc-x.cloud.databricks.com/login.html?… | keep-internal |  | test code |
| 28 | …"https://ws.databricks.com/login.html"… | keep-internal |  | test code |
| 37 | …://ws.cloud.databricks.com/login" }), | keep-internal |  | test code |
| 44 | …://ws.cloud.databricks.com/login/sso?a… | keep-internal |  | test code |
| 53 | …"https://ws.databricks.com/ajax-api/2.… | keep-internal |  | test code |
| 60 | …"https://ws.databricks.com/login.html"… | keep-internal |  | test code |
| 76 | …"https://ws.databricks.com/x?p=/login.… | keep-internal |  | test code |
| 98 | …"https://ws.databricks.com/ajax-api/2.… | keep-internal |  | test code |
| 100 | …"https://ws.databricks.com/login.html?… | keep-internal |  | test code |
| 108 | …"https://ws.databricks.com", | keep-internal |  | test code |
| 114 | …"https://ws.databricks.com"]); | keep-internal |  | test code |
| 141 | …"https://ws.databricks.com/ajax-api/2.… | keep-internal |  | test code |
| 143 | …"https://ws.databricks.com/ajax-api/2.… | keep-internal |  | test code |

### `web/electron/test/settingsNavigation.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 38 | …utMenuItem("Omnigent", () => { | keep-internal |  | test code |
| 55 | …bel, "About Omnigent"); | keep-internal |  | test code |

### `web/electron/test/setup_connect.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 27 | dom.window.omnigentSetup = { | keep-internal |  | test code |

### `web/electron/test/ssh_askpass.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 57 | …askpass.env.OMNIGENT_SSH_ASKPASS_SOCKE… | keep-internal |  | test code |
| 114 | OMNIGENT_SSH_ASKPASS_TOKEN: token, | keep-internal |  | test code |

### `web/electron/test/ssh_connect.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | …ample.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 40 | …ample.cloud.databricks.com/oidc/v1/aut… | keep-internal |  | test code |
| 77 | …one \$group omnigent login "https:/); | keep-internal |  | test code |
| 82 | /** A fake ˋomnigentˋ in ~/.local/bin … | keep-internal |  | test code |
| 87 | …l", "bin", "omnigent"); | keep-internal |  | test code |
| 184 | …ng 127 when omnigent is missing", asyn… | keep-internal |  | test code |
| 197 | …port from a Databricks sign-in link, t… | keep-internal |  | test code |
| 201 | kind: "databricks", | keep-internal |  | test code |
| 219 | const databricksLink = (origin, port) … | keep-internal |  | test code |
| 222 | …ample.cloud.databricks.com/oidc/v1/aut… | keep-internal |  | test code |
| 225 | "a Databricks workspace calling back o… | keep-internal |  | test code |
| 226 | "an Azure Databricks workspace": [ | keep-internal |  | test code |
| 227 | databricksLink("https://adb-1.azuredat… | keep-internal |  | test code |
| 231 | databricksLink("https://127.0.0.1:8443… | keep-internal |  | test code |
| 233 | …443/api/2.0/omnigent", | keep-internal |  | test code |
| 239 | …posing as a Databricks workspace": [ | keep-internal |  | test code |
| 240 | databricksLink("https://evil.example",… | keep-internal |  | test code |
| 241 | …server or a Databricks workspace/, | keep-internal |  | test code |
| 245 | "a Databricks Apps host, which serves … | keep-internal |  | test code |
| 246 | databricksLink("https://attacker-1.aws… | keep-internal |  | test code |
| 247 | …server or a Databricks workspace/, | keep-internal |  | test code |
| 336 | …t.includes("omnigent login")) { | keep-internal |  | test code |
| 352 | …t.includes("omnigent host")) { | keep-internal |  | test code |
| 462 | …h: 1: exec: omnigent: not found"], cod… | keep-internal |  | test code |
| 493 | "This build doesn't include the Omnigent installer.", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 501 | "Installing Omnigent on my-ec2 failed: uv: no space left", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 506 | "Installing Omnigent on my-ec2 timed out.", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 508 | "omnigent is still missing after insta… | keep-internal |  | test code |
| 516 | "Omnigent still isn't on the PATH on my-ec2.", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 537 | "a Databricks sign-in on another site"… | keep-internal |  | test code |
| 539 | …server or a Databricks workspace/, | keep-internal |  | test code |
| 612 | "a Databricks sign-in, which does, sto… | keep-internal |  | test code |
| 694 | "Starting the Omnigent host on my-ec2 failed: not signed in", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 929 | …e.includes("omnigent login")) master.e… | keep-internal |  | test code |
| 946 | error: "Starting the Omnigent host on my-ec2 failed: the connection closed", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 948 | …e.includes("omnigent login"))); | keep-internal |  | test code |
| 949 | …e.includes("omnigent host")), spawned.… | keep-internal |  | test code |

### `web/electron/test/ssh_connect_window.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …ample.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 49 | …estination} omnigent login '${url}'ˋ], | keep-internal |  | test code |
| 79 | …ˋssh my-ec2 omnigent login '${SERVER}'… | keep-internal |  | test code |
| 273 | …"ssh my-ec2 omnigent login 'x'", "ssh … | keep-internal |  | test code |

### `web/electron/test/token_store.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 43 | …oin(home, ".omnigent", "test_tokens.js… | keep-internal |  | test code |

### `web/electron/test/update-main.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | ….tmpdir(), "omnigent-update-test-")); | keep-internal |  | test code |
| 111 | name: "Omnigent", | keep-internal |  | test code |
| 204 | expandDatabricksWorkspaceUrl: async (u… | keep-internal |  | test code |
| 208 | // databricks-session (transitively) r… | keep-internal |  | test code |
| 209 | … covered in databricks-*.test.js. | keep-internal |  | test code |
| 210 | "./databricks-session": { | keep-internal |  | test code |
| 211 | ensureDatabricksSession: async (_ses, … | keep-internal |  | test code |
| 216 | "./databricks-oauth": { | keep-internal |  | test code |
| 226 | "./omnigent_cli": { | keep-internal |  | test code |
| 271 | OMNIGENT_DESKTOP_VERSION_OVERRIDE: des… | keep-internal |  | test code |
| 272 | // No OMNIGENT_FORCE_DEV_UPDATE_CONFIG… | keep-internal |  | test code |
| 356 | …{ channel: "omnigent:open-path", paylo… | keep-internal |  | test code |
| 365 | channel: "omnigent:open-path", | keep-internal |  | test code |
| 386 | …ndlers.has("omnigent:export-diagnostic… | keep-internal |  | test code |
| 425 | assert.equal(aboutItem.label, "About Omnigent"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 443 | assert.equal(aboutItem.label, "About Omnigent"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 468 | "Omnigent", | keep-internal |  | test code |
| 477 | …uIds(menu, "Omnigent"), [ | keep-internal |  | test code |
| 569 | …teners.get("omnigent:set-desktop-comma… | keep-internal |  | test code |
| 647 | { channel: "omnigent:desktop-command",… | keep-internal |  | test code |
| 648 | { channel: "omnigent:desktop-command",… | keep-internal |  | test code |
| 649 | { channel: "omnigent:desktop-command",… | keep-internal |  | test code |
| 671 | channel: "omnigent:desktop-command", | keep-internal |  | test code |
| 675 | channel: "omnigent:desktop-command", | keep-internal |  | test code |
| 717 | { channel: "omnigent:desktop-command",… | keep-internal |  | test code |
| 755 | { channel: "omnigent:desktop-command",… | keep-internal |  | test code |
| 757 | channel: "omnigent:desktop-command", | keep-internal |  | test code |
| 782 | channel: "omnigent:desktop-command", | keep-internal |  | test code |
| 832 | …teners.get("omnigent:set-desktop-comma… | keep-internal |  | test code |
| 848 | …ndlers.get("omnigent:close-window")(ha… | keep-internal |  | test code |
| 861 | …ndlers.get("omnigent:close-window")(ha… | keep-internal |  | test code |
| 875 | …ndlers.get("omnigent:get-global-shortc… | keep-internal |  | test code |
| 880 | …ndlers.get("omnigent:set-global-shortc… | keep-internal |  | test code |
| 887 | …ndlers.get("omnigent:record-global-sho… | keep-internal |  | test code |
| 891 | …ndlers.get("omnigent:cancel-global-sho… | keep-internal |  | test code |
| 902 | …ndlers.get("omnigent:set-global-shortc… | keep-internal |  | test code |
| 909 | assert.match(options.message, /show Omnigent from any app/); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 923 | …ndlers.get("omnigent:set-global-shortc… | keep-internal |  | test code |
| 937 | …ndlers.get("omnigent:set-global-shortc… | keep-internal |  | test code |
| 966 | …teners.get("omnigent:set-desktop-comma… | keep-internal |  | test code |
| 974 | channel: "omnigent:desktop-command", | keep-internal |  | test code |
| 984 | …ndlers.get("omnigent:confirm-quit"); | keep-internal |  | test code |
| 996 | …teners.get("omnigent:set-desktop-comma… | keep-internal |  | test code |
| 1029 | …teners.get("omnigent:set-desktop-comma… | keep-internal |  | test code |
| 1063 | …space.cloud.databricks.com"; | keep-internal |  | test code |
| 1067 | serverUrl: ˋ${origin}/omnigentˋ, | keep-internal |  | test code |
| 1069 | …space.cloud.databricks.com", path: "/"… | keep-internal |  | test code |
| 1083 | …space.cloud.databricks.com"; | keep-internal |  | test code |
| 1087 | serverUrl: ˋ${origin}/omnigentˋ, | keep-internal |  | test code |
| 1182 | ["omnigent:get-update-config", []], | keep-internal |  | test code |
| 1183 | ["omnigent:get-update-status", []], | keep-internal |  | test code |
| 1184 | ["omnigent:update-check", []], | keep-internal |  | test code |
| 1185 | ["omnigent:update-download", []], | keep-internal |  | test code |
| 1186 | ["omnigent:update-install", []], | keep-internal |  | test code |
| 1187 | ["omnigent:set-update-config", [{ mode… | keep-internal |  | test code |
| 1203 | channel: "omnigent:update-download", | keep-internal |  | test code |
| 1205 | message: "Download an Omnigent update?", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1212 | channel: "omnigent:update-install", | keep-internal |  | test code |
| 1214 | message: "Restart Omnigent to install an update?", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1224 | channel: "omnigent:set-update-config", | keep-internal |  | test code |
| 1226 | message: "Change Omnigent update settings?", | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1250 | assert.equal(harness.calls.showMessageBox[0].options.title, "Omnigent"); | change | S87 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1264 | channel: "omnigent:update-download", | keep-internal |  | test code |
| 1272 | channel: "omnigent:update-install", | keep-internal |  | test code |
| 1283 | channel: "omnigent:set-update-config", | keep-internal |  | test code |
| 1329 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |
| 1363 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |
| 1400 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |
| 1458 | ….g. a hung ˋomnigent server stopˋ, or … | keep-internal |  | test code |
| 1518 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |
| 1550 | …ndlers.get("omnigent:update-check")(ha… | keep-internal |  | test code |
| 1567 | …ndlers.get("omnigent:update-check")(ha… | keep-internal |  | test code |
| 1571 | …ndlers.get("omnigent:update-download")… | keep-internal |  | test code |
| 1575 | …ndlers.get("omnigent:update-install")(… | keep-internal |  | test code |
| 1579 | …ndlers.get("omnigent:set-update-config… | keep-internal |  | test code |
| 1637 | channel: "omnigent:update-status", | keep-internal |  | test code |

### `web/electron/test/update_overlay.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 182 | …ndlers.get("omnigent:overlay-height")(… | keep-internal |  | test code |
| 185 | channel: "omnigent:update-overlay-heig… | keep-internal |  | test code |
| 196 | …ndlers.get("omnigent:get-update-overla… | keep-internal |  | test code |
| 202 | …ndlers.get("omnigent:get-update-overla… | keep-internal |  | test code |
| 210 | channel: "omnigent:update-overlay-heig… | keep-internal |  | test code |
| 230 | …ndlers.get("omnigent:overlay-height")(… | keep-internal |  | test code |
| 233 | channel: "omnigent:update-overlay-heig… | keep-internal |  | test code |
| 248 | …ndlers.get("omnigent:overlay-update-do… | keep-internal |  | test code |
| 257 | channel: "omnigent:update-overlay-heig… | keep-internal |  | test code |
| 266 | …ndlers.get("omnigent:overlay-update-do… | keep-internal |  | test code |
| 281 | …ndlers.get("omnigent:overlay-height")(… | keep-internal |  | test code |
| 290 | channel: "omnigent:update-overlay-heig… | keep-internal |  | test code |

### `web/electron/test/url.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | isDatabricksManagedServerUrl, | keep-internal |  | test code |
| 17 | databricksWorkspaceUiUrl, | keep-internal |  | test code |
| 18 | expandDatabricksWorkspaceUrl, | keep-internal |  | test code |
| 29 | …dbc-x.cloud.databricks.com/omnigent"),… | keep-internal |  | test code |
| 47 | …-49dc.cloud.databricks.com/omnigent"), | keep-internal |  | test code |
| 48 | …-49dc.cloud.databricks.com/", | keep-internal |  | test code |
| 54 | …ample.cloud.databricks.com"), | keep-internal |  | test code |
| 55 | …ample.cloud.databricks.com/", | keep-internal |  | test code |
| 73 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 74 | …space.cloud.databricks.com/?o=123", | keep-internal |  | test code |
| 76 | …p://ws.azuredatabricks.net"), "https:/… | keep-internal |  | test code |
| 77 | …("http://notdatabricks.com"), "http://… | keep-internal |  | test code |
| 82 | … ˋhttp://ws.databricks.com:${port}ˋ; | keep-internal |  | test code |
| 83 | … ˋ${origin}/omnigent?o=123ˋ; | keep-internal |  | test code |
| 86 | …in}/api/2.0/omnigent?o=123ˋ), saved); | keep-internal |  | test code |
| 92 | …space.cloud.databricks.com:80/omnigent… | keep-internal |  | test code |
| 93 | …space.cloud.databricks.com/?o=123"); | keep-internal |  | test code |
| 96 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 101 | …eserves the Databricks organization wh… | keep-internal |  | test code |
| 104 | …space.cloud.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 106 | …space.cloud.databricks.com/?o=123", | keep-internal |  | test code |
| 110 | …ter for non-Databricks hosts", () => { | keep-internal |  | test code |
| 113 | …/my-app.aws.databricksapps.com/?o=123"… | keep-internal |  | test code |
| 114 | …/my-app.aws.databricksapps.com/", | keep-internal |  | test code |
| 143 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 144 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 145 | …space.cloud.databricks.com/c/123?ignor… | keep-internal |  | test code |
| 150 | …space.cloud.databricks.com/?o=123", "h… | keep-internal |  | test code |
| 160 | …nd optional Databricks organization", … | keep-internal |  | test code |
| 162 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 163 | …space.cloud.databricks.com/?o=123", | keep-internal |  | test code |
| 171 | …/my-app.aws.databricksapps.com/?o=123"… | keep-internal |  | test code |
| 172 | "my-app.aws.databricksapps.com", | keep-internal |  | test code |
| 181 | describe("isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 182 | it("accepts Databricks Apps and worksp… | keep-internal |  | test code |
| 184 | isDatabricksManagedServerUrl("https://… | keep-internal |  | test code |
| 188 | isDatabricksManagedServerUrl("https://… | keep-internal |  | test code |
| 191 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 192 | // Not Databricks-hosted, https or not… | keep-internal |  | test code |
| 193 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 194 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 196 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 197 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 199 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 200 | …ert.equal(isDatabricksManagedServerUrl… | keep-internal |  | test code |
| 206 | …te("example.databricks.com"), false); | keep-internal |  | test code |
| 207 | …dbc-x.cloud.databricks.com/omnigent"),… | keep-internal |  | test code |
| 215 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 225 | …s://example.databricks.com"), false); | keep-internal |  | test code |
| 233 | … of ["/", "/omnigent", "/omnigent/c/12… | keep-internal |  | test code |
| 235 | …space.cloud.databricks.com${path}?o=12… | keep-internal |  | test code |
| 236 | …space.cloud.databricks.com${path}?o=12… | keep-internal |  | test code |
| 242 | …the current Databricks API mount to th… | keep-internal |  | test code |
| 244 | …://ws.cloud.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 245 | …://ws.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 251 | …s://ws.azuredatabricks.net/api/2.0/omn… | keep-internal |  | test code |
| 252 | …s://ws.azuredatabricks.net/omnigent", | keep-internal |  | test code |
| 259 | …://ws.cloud.databricks.com:8443/api/2.… | keep-internal |  | test code |
| 261 | …://ws.cloud.databricks.com:8443/omnige… | keep-internal |  | test code |
| 267 | "https://ws.cloud.databricks.com", | keep-internal |  | test code |
| 268 | "https://ws.cloud.databricks.com/", | keep-internal |  | test code |
| 269 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 270 | …://ws.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 278 | …com/api/2.0/omnigent", | keep-internal |  | test code |
| 279 | "https://databricks.com.example.org/ap… | keep-internal |  | test code |
| 280 | …://ws.cloud.databricks.com/prefix/api/… | keep-internal |  | test code |
| 281 | …://ws.cloud.databricks.com/api/2.0/omn… | keep-internal |  | test code |
| 316 | describe("databricksWorkspaceUiUrl", (… | keep-internal |  | test code |
| 317 | …e roots to /omnigent", () => { | keep-internal |  | test code |
| 319 | databricksWorkspaceUiUrl("https://ws.c… | keep-internal |  | test code |
| 320 | …://ws.cloud.databricks.com/omnigent", | keep-internal |  | test code |
| 323 | databricksWorkspaceUiUrl("http://ws.az… | keep-internal |  | test code |
| 324 | …p://ws.azuredatabricks.net/omnigent", | keep-internal |  | test code |
| 330 | databricksWorkspaceUiUrl("https://ws.c… | keep-internal |  | test code |
| 331 | …://ws.cloud.databricks.com:8443/omnige… | keep-internal |  | test code |
| 336 | …ssert.equal(databricksWorkspaceUiUrl("… | keep-internal |  | test code |
| 337 | …ssert.equal(databricksWorkspaceUiUrl("… | keep-internal |  | test code |
| 340 | …oes not map Databricks Apps or deliber… | keep-internal |  | test code |
| 341 | …ssert.equal(databricksWorkspaceUiUrl("… | keep-internal |  | test code |
| 342 | …ssert.equal(databricksWorkspaceUiUrl("… | keep-internal |  | test code |
| 346 | …ssert.equal(databricksWorkspaceUiUrl("… | keep-internal |  | test code |
| 347 | …ssert.equal(databricksWorkspaceUiUrl("… | keep-internal |  | test code |
| 348 | …ssert.equal(databricksWorkspaceUiUrl(n… | keep-internal |  | test code |
| 352 | …ribe("expandDatabricksWorkspaceUrl", (… | keep-internal |  | test code |
| 358 | return fakeResponse("databricks"); | keep-internal |  | test code |
| 362 | …://ws.cloud.databricks.com/some/copied… | keep-internal |  | test code |
| 364 | …://ws.cloud.databricks.com/?o=123"); | keep-internal |  | test code |
| 365 | …_UI_PATH, "/omnigent"); | keep-internal |  | test code |
| 367 | await expandDatabricksWorkspaceUrl(nor… | keep-internal |  | test code |
| 368 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 373 | …://ws.cloud.databricks.com/", method: … | keep-internal |  | test code |
| 376 | …eaves a non-Databricks root unchanged"… | keep-internal |  | test code |
| 381 | await expandDatabricksWorkspaceUrl("ht… | keep-internal |  | test code |
| 393 | return fakeResponse("databricks"); | keep-internal |  | test code |
| 396 | …://ws.cloud.databricks.com/omnigent"; | keep-internal |  | test code |
| 397 | …await expandDatabricksWorkspaceUrl(url… | keep-internal |  | test code |
| 403 | …t("leaves a Databricks Apps host untou… | keep-internal |  | test code |
| 408 | return fakeResponse("databricks"); | keep-internal |  | test code |
| 411 | …app-123.aws.databricksapps.com/"; | keep-internal |  | test code |
| 412 | …await expandDatabricksWorkspaceUrl(url… | keep-internal |  | test code |
| 414 | await expandDatabricksWorkspaceUrl("ht… | keep-internal |  | test code |
| 415 | "https://databricksapps.com/", | keep-internal |  | test code |
| 427 | return fakeResponse("databricks"); | keep-internal |  | test code |
| 431 | await expandDatabricksWorkspaceUrl("ht… | keep-internal |  | test code |
| 446 | …await expandDatabricksWorkspaceUrl(url… | keep-internal |  | test code |
| 452 | …await expandDatabricksWorkspaceUrl("no… | keep-internal |  | test code |
| 472 | ….well-known/omnigent.json"); | keep-internal |  | test code |
| 641 | …d server (…/omnigent) still serves the… | keep-internal |  | test code |
| 645 | ….well-known/omnigent.json"); | keep-internal |  | test code |
| 649 | …example.com/omnigent"); | keep-internal |  | test code |

### `web/electron/test/workspace-chrome.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …ded and the Databricks workspace switc… | keep-internal |  | test code |
| 25 | …ipped (not /omnigent). | keep-internal |  | test code |
| 26 | …dbc-x.cloud.databricks.com/dashboard", | keep-internal |  | test code |
| 40 | … for a non-/omnigent path. A URL/path … | keep-internal |  | test code |
| 42 | "Databricks workspace switcher visible… | keep-internal |  | test code |
| 43 | …ly targets .omnigent-app (workspace-em… | keep-internal |  | test code |
| 104 | …t this, the Databricks workspace top-n… | keep-internal |  | test code |
| 105 | …gate out of Omnigent.", | keep-internal |  | test code |

### `web/electron/test/workspace-root-bounce.test.js`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | …igation to /omnigent", () => { | keep-internal |  | test code |
| 27 | …://ws.cloud.databricks.com"); | keep-internal |  | test code |
| 29 | …://ws.cloud.databricks.com/?o=123#page… | keep-internal |  | test code |
| 31 | …://ws.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 36 | …s://ws.azuredatabricks.net"); | keep-internal |  | test code |
| 38 | …s://ws.azuredatabricks.net/", false); | keep-internal |  | test code |
| 39 | …s://ws.azuredatabricks.net/", true); | keep-internal |  | test code |
| 41 | …s://ws.azuredatabricks.net/omnigent"])… | keep-internal |  | test code |
| 46 | …://ws.cloud.databricks.com"); | keep-internal |  | test code |
| 48 | …other.cloud.databricks.com/"); | keep-internal |  | test code |
| 55 | …://ws.cloud.databricks.com"; | keep-internal |  | test code |
| 61 | …[ˋ${origin}/omnigentˋ]); | keep-internal |  | test code |
| 63 | … ˋ${origin}/omnigentˋ; | keep-internal |  | test code |
| 66 | …[ˋ${origin}/omnigentˋ, ˋ${origin}/omni… | keep-internal |  | test code |

### `web/electron/workspace-picker/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 91 | <h1>Select a Databricks workspace</h1> | keep-origin |  | Heading names the Databricks workspace integration target. |

### `web/index.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | omnigent/server/app.py (_rewrite_web_u… | keep-internal |  | HTML comment naming omnigent/server/app.py; not |
| 20 | <title>Omnigent</title> | change | S89 | Default browser tab title; main.tsx overrides with branding.app_name when set. |
| 64 | <span aria-hidden="true"></span>Loading Omnigent… | change | S89 | Boot loading text shown before the SPA mounts. |

### `web/ios/Omnigent.xcodeproj/project.pbxproj`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …00000001 /* OmnigentApp.swift in Sourc… | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 21 | …0000000B /* OmnigentWebView.swift in S… | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 22 | …000C /* URL+Omnigent.swift in Sources … | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 39 | …in Sources (OmnigentTests) */ = {isa =… | keep-internal |  | Xcode build file/group entry for Omnigent test t |
| 40 | …in Sources (OmnigentUITests) */ = {isa… | keep-internal |  | Xcode build file/group entry for Omnigent test t |
| 42 | …00000001 /* OmnigentUITests.swift in S… | keep-internal |  | Xcode build file/group entry for Omnigent test t |
| 50 | …00000019 /* DatabricksOAuthConfigurati… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 51 | …0000001A /* DatabricksOAuthAttempt.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 52 | …0000001B /* DatabricksOAuthClient.swif… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 53 | …0000001C /* DatabricksLoginManager.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 54 | …00000020 /* DatabricksOAuthTests.swift… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 55 | …0000000B /* DatabricksOAuthClientTests… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 56 | …0000000C /* DatabricksLoginManagerTest… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 57 | …0000001E /* DatabricksCredentialStore.… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 58 | …0000001F /* DatabricksTokenManager.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 59 | …0000000D /* DatabricksCredentialStoreT… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 60 | …0000000E /* DatabricksTokenManagerTest… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 61 | …00000020 /* DatabricksOAuthIssuer.swif… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 62 | …0000000F /* DatabricksOAuthIssuerTests… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 63 | …00000021 /* DatabricksWebContext.swift… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 64 | …00000022 /* DatabricksSessionClient.sw… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 65 | …00000023 /* DatabricksWorkspaceBootstr… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 72 | …00000010 /* DatabricksWebContextTests.… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 73 | …00000011 /* DatabricksSessionClientTes… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 74 | …00000012 /* DatabricksWorkspaceBootstr… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 88 | remoteInfo = Omnigent; | keep-internal |  | Xcode container proxy remoteInfo naming the Omni |
| 95 | remoteInfo = Omnigent; | keep-internal |  | Xcode container proxy remoteInfo naming the Omni |
| 100 | …00000001 /* OmnigentApp.swift */ = {is… | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 112 | …0000000B /* OmnigentWebView.swift */ =… | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 113 | …000C /* URL+Omnigent.swift */ = {isa =… | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 133 | …00000003 /* OmnigentUITests.xctest */ … | keep-internal |  | Test bundle product reference (OmnigentTests/Omn |
| 134 | …00000001 /* OmnigentUITests.swift */ =… | keep-internal |  | Xcode build file/group entry for Omnigent test t |
| 138 | …00000001 /* Omnigent.app */ = {isa = P… | keep-internal |  | Built product file reference (Omnigent.app from |
| 139 | …00000002 /* OmnigentTests.xctest */ = … | keep-internal |  | Test bundle product reference (OmnigentTests/Omn |
| 144 | …00000019 /* DatabricksOAuthConfigurati… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 145 | …0000001A /* DatabricksOAuthAttempt.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 146 | …0000001B /* DatabricksOAuthClient.swif… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 147 | …0000001C /* DatabricksLoginManager.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 148 | …0000001D /* Omnigent.entitlements */ =… | keep-internal |  | Xcode file reference to Omnigent.entitlements; i |
| 149 | …00000020 /* DatabricksOAuthTests.swift… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 150 | …0000000B /* DatabricksOAuthClientTests… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 151 | …0000000C /* DatabricksLoginManagerTest… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 152 | …0000001E /* DatabricksCredentialStore.… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 153 | …0000001F /* DatabricksTokenManager.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 154 | …0000000D /* DatabricksCredentialStoreT… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 155 | …0000000E /* DatabricksTokenManagerTest… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 156 | …00000020 /* DatabricksOAuthIssuer.swif… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 157 | …0000000F /* DatabricksOAuthIssuerTests… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 158 | …00000021 /* DatabricksWebContext.swift… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 159 | …00000022 /* DatabricksSessionClient.sw… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 160 | …00000023 /* DatabricksWorkspaceBootstr… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 167 | …00000010 /* DatabricksWebContextTests.… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 168 | …00000011 /* DatabricksSessionClientTes… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 169 | …00000012 /* DatabricksWorkspaceBootstr… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 205 | …00000003 /* Omnigent */, | keep-internal |  | Xcode group for the Omnigent source folder; inte |
| 206 | …00000004 /* OmnigentTests */, | keep-internal |  | Xcode build file/group entry for Omnigent test t |
| 207 | …00000009 /* OmnigentUITests */, | keep-internal |  | Xcode build file/group entry for Omnigent test t |
| 216 | …00000001 /* Omnigent.app */, | keep-internal |  | Built product file reference (Omnigent.app from |
| 217 | …00000002 /* OmnigentTests.xctest */, | keep-internal |  | Test bundle product reference (OmnigentTests/Omn |
| 218 | …00000003 /* OmnigentUITests.xctest */, | keep-internal |  | Test bundle product reference (OmnigentTests/Omn |
| 223 | …00000003 /* Omnigent */ = { | keep-internal |  | Xcode group for the Omnigent source folder; inte |
| 226 | …00000001 /* OmnigentApp.swift */, | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 238 | …0000000B /* OmnigentWebView.swift */, | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 239 | …000C /* URL+Omnigent.swift */, | keep-internal |  | Xcode build file/file reference for an Omnigent- |
| 245 | …00000019 /* DatabricksOAuthConfigurati… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 246 | …0000001A /* DatabricksOAuthAttempt.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 247 | …0000001B /* DatabricksOAuthClient.swif… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 248 | …0000001C /* DatabricksLoginManager.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 249 | …0000001E /* DatabricksCredentialStore.… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 250 | …0000001F /* DatabricksTokenManager.swi… | keep-internal |  | Xcode file reference for Databricks OAuth/worksp |
| 251 | …00000020 /* DatabricksOAuthIssuer.swif… | keep-internal |  | Xcode file reference for Databricks sign-in inte |
| 252 | …00000021 /* DatabricksWebContext.swift… | keep-internal |  | Xcode file reference for Databricks integration |
| 253 | …00000022 /* DatabricksSessionClient.sw… | keep-internal |  | Xcode file reference for Databricks integration |
| 254 | …00000023 /* DatabricksWorkspaceBootstr… | keep-internal |  | Xcode file reference for Databricks integration |
| 261 | …0000001D /* Omnigent.entitlements */, | keep-internal |  | Xcode file reference to Omnigent.entitlements; p |
| 267 | path = Omnigent; | keep-internal |  | Xcode group folder path Omnigent; project folder |
| 270 | …00000004 /* OmnigentTests */ = { | keep-internal |  | OmnigentTests group name; Xcode test group, not |
| 286 | …00000020 /* DatabricksOAuthTests.swift… | keep-internal |  | Xcode file reference for Databricks OAuth test f |
| 287 | …0000000B /* DatabricksOAuthClientTests… | keep-internal |  | Xcode file reference for Databricks OAuth client |
| 288 | …0000000C /* DatabricksLoginManagerTest… | keep-internal |  | Xcode file reference for Databricks login manage |
| 289 | …0000000D /* DatabricksCredentialStoreT… | keep-internal |  | Xcode file reference for Databricks credential s |
| 290 | …0000000E /* DatabricksTokenManagerTest… | keep-internal |  | Xcode file reference for Databricks token manage |
| 291 | …0000000F /* DatabricksOAuthIssuerTests… | keep-internal |  | Xcode file reference for Databricks OAuth issuer |
| 292 | …00000010 /* DatabricksWebContextTests.… | keep-internal |  | Xcode file reference for Databricks web context |
| 293 | …00000011 /* DatabricksSessionClientTes… | keep-internal |  | Xcode file reference for Databricks session clie |
| 294 | …00000012 /* DatabricksWorkspaceBootstr… | keep-internal |  | Xcode file reference for Databricks workspace bo |
| 301 | path = OmnigentTests; | keep-internal |  | OmnigentTests group folder path; Xcode project f |
| 304 | …00000009 /* OmnigentUITests */ = { | keep-internal |  | OmnigentUITests group name; Xcode test group, no |
| 307 | …00000001 /* OmnigentUITests.swift */, | keep-internal |  | Xcode file reference OmnigentUITests.swift; inte |
| 312 | path = OmnigentUITests; | keep-internal |  | OmnigentUITests group folder path; Xcode project |
| 326 | …00000006 /* Omnigent */ = { | keep-internal |  | Omnigent app native target name; Xcode target/sc |
| 328 | …tiveTarget "Omnigent" */; | keep-internal |  | Build configuration list comment naming the Omni |
| 338 | name = Omnigent; | keep-internal |  | Native target name = Omnigent; Xcode target name |
| 339 | productName = Omnigent; | keep-internal |  | Target productName attribute; PRODUCT_NAME is $( |
| 340 | …00000001 /* Omnigent.app */; | keep-internal |  | Product reference Omnigent.app; build product fi |
| 343 | …00000007 /* OmnigentTests */ = { | keep-internal |  | OmnigentTests native target; Xcode test target n |
| 345 | …tiveTarget "OmnigentTests" */; | keep-internal |  | Build configuration list comment for OmnigentTes |
| 356 | name = OmnigentTests; | keep-internal |  | OmnigentTests target name; Xcode test target. |
| 357 | productName = OmnigentTests; | keep-internal |  | OmnigentTests productName; test bundle name, not |
| 358 | …00000002 /* OmnigentTests.xctest */; | keep-internal |  | OmnigentTests.xctest product reference; test bun |
| 361 | …0000000A /* OmnigentUITests */ = { | keep-internal |  | OmnigentUITests native target; Xcode UI test tar |
| 363 | …tiveTarget "OmnigentUITests" */; | keep-internal |  | Build configuration list comment for OmnigentUIT |
| 374 | name = OmnigentUITests; | keep-internal |  | OmnigentUITests target name; Xcode UI test targe |
| 375 | productName = OmnigentUITests; | keep-internal |  | OmnigentUITests productName; test bundle name, n |
| 376 | …00000003 /* OmnigentUITests.xctest */; | keep-internal |  | OmnigentUITests.xctest product reference; test b |
| 402 | …PBXProject "Omnigent" */; | keep-internal |  | PBXProject "Omnigent" configuration list comment |
| 415 | …00000006 /* Omnigent */, | keep-internal |  | Project targets list entry for Omnigent target; |
| 416 | …00000007 /* OmnigentTests */, | keep-internal |  | Project targets list entry for OmnigentTests; Xc |
| 417 | …0000000A /* OmnigentUITests */, | keep-internal |  | Project targets list entry for OmnigentUITests; |
| 454 | …00000001 /* OmnigentApp.swift in Sourc… | keep-internal |  | Sources build phase entry OmnigentApp.swift; Swi |
| 466 | …0000000B /* OmnigentWebView.swift in S… | keep-internal |  | Sources build phase entry OmnigentWebView.swift; |
| 467 | …000C /* URL+Omnigent.swift in Sources … | keep-internal |  | Sources build phase entry URL+Omnigent.swift; Sw |
| 473 | …00000019 /* DatabricksOAuthConfigurati… | keep-internal |  | Sources build phase entry for Databricks OAuth c |
| 474 | …0000001A /* DatabricksOAuthAttempt.swi… | keep-internal |  | Sources build phase entry for Databricks OAuth a |
| 475 | …0000001B /* DatabricksOAuthClient.swif… | keep-internal |  | Sources build phase entry for Databricks OAuth c |
| 476 | …0000001C /* DatabricksLoginManager.swi… | keep-internal |  | Sources build phase entry for Databricks login m |
| 477 | …0000001E /* DatabricksCredentialStore.… | keep-internal |  | Sources build phase entry for Databricks credent |
| 478 | …0000001F /* DatabricksTokenManager.swi… | keep-internal |  | Sources build phase entry for Databricks token m |
| 479 | …00000020 /* DatabricksOAuthIssuer.swif… | keep-internal |  | Sources build phase entry for Databricks OAuth i |
| 480 | …00000021 /* DatabricksWebContext.swift… | keep-internal |  | Sources build phase entry for Databricks web con |
| 481 | …00000022 /* DatabricksSessionClient.sw… | keep-internal |  | Sources build phase entry for Databricks session |
| 482 | …00000023 /* DatabricksWorkspaceBootstr… | keep-internal |  | Sources build phase entry for Databricks workspa |
| 503 | …in Sources (OmnigentTests) */, | keep-internal |  | Build file comment naming OmnigentTests target f |
| 509 | …00000020 /* DatabricksOAuthTests.swift… | keep-internal |  | Test sources entry for Databricks OAuth tests; i |
| 510 | …0000000B /* DatabricksOAuthClientTests… | keep-internal |  | Test sources entry for Databricks OAuth client t |
| 511 | …0000000C /* DatabricksLoginManagerTest… | keep-internal |  | Test sources entry for Databricks login manager |
| 512 | …0000000D /* DatabricksCredentialStoreT… | keep-internal |  | Test sources entry for Databricks credential sto |
| 513 | …0000000E /* DatabricksTokenManagerTest… | keep-internal |  | Test sources entry for Databricks token manager |
| 514 | …0000000F /* DatabricksOAuthIssuerTests… | keep-internal |  | Test sources entry for Databricks OAuth issuer t |
| 515 | …00000010 /* DatabricksWebContextTests.… | keep-internal |  | Test sources entry for Databricks web context te |
| 516 | …00000011 /* DatabricksSessionClientTes… | keep-internal |  | Test sources entry for Databricks session client |
| 517 | …00000012 /* DatabricksWorkspaceBootstr… | keep-internal |  | Test sources entry for Databricks workspace boot |
| 530 | …00000001 /* OmnigentUITests.swift in S… | keep-internal |  | UI test sources entry OmnigentUITests.swift; int |
| 534 | …in Sources (OmnigentUITests) */, | keep-internal |  | Build file comment naming OmnigentUITests target |
| 543 | …00000006 /* Omnigent */; | keep-internal |  | Target dependency comment naming the Omnigent ta |
| 548 | …00000006 /* Omnigent */; | keep-internal |  | Target dependency comment naming the Omnigent ta |
| 673 | …ITLEMENTS = Omnigent/Omnigent.entitlem… | keep-internal |  | CODE_SIGN_ENTITLEMENTS path Omnigent/Omnigent.en |
| 674 | DATABRICKS_OAUTH_CLIENT_ID = omnigent; | keep-deferred |  | Public OAuth client id 'omnigent' registered with Databricks; renaming needs a new Databricks client registration (OQ-31). |
| 675 | DATABRICKS_OAUTH_REDIRECT_URL = "https://login.databricks.com/mobile-redirect"; | keep-origin |  | Databricks platform OAuth mobile-redirect callback URL; names the third-party Databricks login service the app integrates with. |
| 676 | APP_DISPLAY_NAME = Omnigent; | change | S88 | APP_DISPLAY_NAME feeds CFBundleDisplayName in Info-Debug.plist; the iOS Home-screen app name users see. |
| 685 | …IST_FILE = "Omnigent/Info-Debug.plist"… | keep-internal |  | Info.plist path inside the Omnigent Xcode projec |
| 693 | PRODUCT_BUNDLE_IDENTIFIER = ai.omnigent.ios; | keep-deferred |  | PRODUCT_BUNDLE_IDENTIFIER ai.omnigent.ios (Debug app target); mobile bundle ids wait for OQ-31. |
| 707 | …ITLEMENTS = Omnigent/Omnigent.entitlem… | keep-internal |  | Entitlements file path under the Omnigent projec |
| 708 | DATABRICKS_OAUTH_CLIENT_ID = omnigent; | keep-internal |  | Public OAuth client_id 'omnigent' registered wit |
| 709 | DATABRICKS_OAUTH_REDIRECT_URL = "https://login.databricks.com/mobile-redirect"; | keep-origin |  | Databricks login mobile-redirect callback URL; names the Databricks OAuth integration target, not Coral's publisher. |
| 710 | APP_DISPLAY_NAME = Omnigent; | change | S88 | Release APP_DISPLAY_NAME maps to CFBundleDisplayName (Info-Release.plist:8): the home-screen app name. |
| 719 | …IST_FILE = "Omnigent/Info-Release.plis… | keep-internal |  | Info-Release.plist path inside the Omnigent proj |
| 727 | PRODUCT_BUNDLE_IDENTIFIER = ai.omnigent.ios; | keep-deferred |  | PRODUCT_BUNDLE_IDENTIFIER ai.omnigent.ios (Release app target); mobile bundle ids wait for OQ-31. |
| 752 | PRODUCT_BUNDLE_IDENTIFIER = ai.omnigent.ios.tests; | keep-deferred |  | PRODUCT_BUNDLE_IDENTIFIER ai.omnigent.ios.tests (unit test bundle); bundle ids wait for OQ-31. |
| 758 | …ODUCTS_DIR)/Omnigent.app/$(BUNDLE_EXEC… | keep-internal |  | TEST_HOST path derives from the Omnigent target/ |
| 776 | PRODUCT_BUNDLE_IDENTIFIER = ai.omnigent.ios.tests; | keep-deferred |  | PRODUCT_BUNDLE_IDENTIFIER ai.omnigent.ios.tests (Release); bundle ids wait for OQ-31. |
| 782 | …ODUCTS_DIR)/Omnigent.app/$(BUNDLE_EXEC… | keep-internal |  | TEST_HOST path derives from the Omnigent target/ |
| 799 | PRODUCT_BUNDLE_IDENTIFIER = ai.omnigent.ios.uitests; | keep-deferred |  | PRODUCT_BUNDLE_IDENTIFIER ai.omnigent.ios.uitests (Debug); bundle ids wait for OQ-31. |
| 805 | TEST_TARGET_NAME = Omnigent; | keep-internal |  | TEST_TARGET_NAME names the Omnigent Xcode target |
| 822 | PRODUCT_BUNDLE_IDENTIFIER = ai.omnigent.ios.uitests; | keep-deferred |  | PRODUCT_BUNDLE_IDENTIFIER ai.omnigent.ios.uitests (Release); bundle ids wait for OQ-31. |
| 828 | TEST_TARGET_NAME = Omnigent; | keep-internal |  | TEST_TARGET_NAME names the Omnigent Xcode target |
| 835 | …PBXProject "Omnigent" */ = { | keep-internal |  | pbxproj comment naming the Omnigent PBXProject c |
| 844 | …tiveTarget "Omnigent" */ = { | keep-internal |  | pbxproj comment naming the Omnigent native targe |
| 853 | …tiveTarget "OmnigentTests" */ = { | keep-internal |  | pbxproj comment naming the OmnigentTests target; |
| 862 | …tiveTarget "OmnigentUITests" */ = { | keep-internal |  | pbxproj comment naming the OmnigentUITests targe |

### `web/ios/Omnigent.xcodeproj/xcshareddata/xcschemes/Omnigent.xcscheme`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | BuildableName = "Omnigent.app" | keep-internal |  | Xcode scheme BuildableName Omnigent.app for the |
| 19 | BlueprintName = "Omnigent" | keep-internal |  | Xcode scheme BlueprintName for the Omnigent targ |
| 20 | … "container:Omnigent.xcodeproj"> | keep-internal |  | Scheme reference to the Omnigent.xcodeproj conta |
| 37 | BuildableName = "OmnigentTests.xctest" | keep-internal |  | Scheme BuildableName OmnigentTests.xctest; inter |
| 38 | BlueprintName = "OmnigentTests" | keep-internal |  | Scheme BlueprintName OmnigentTests; internal tes |
| 39 | … "container:Omnigent.xcodeproj"> | keep-internal |  | Scheme reference to the Omnigent.xcodeproj conta |
| 48 | …ableName = "OmnigentUITests.xctest" | keep-internal |  | Scheme BuildableName OmnigentUITests.xctest; int |
| 49 | BlueprintName = "OmnigentUITests" | keep-internal |  | Scheme BlueprintName OmnigentUITests; internal U |
| 50 | … "container:Omnigent.xcodeproj"> | keep-internal |  | Scheme reference to the Omnigent.xcodeproj conta |
| 58 | BuildableName = "Omnigent.app" | keep-internal |  | Scheme BuildableName Omnigent.app for the test a |
| 59 | BlueprintName = "Omnigent" | keep-internal |  | Scheme BlueprintName Omnigent; internal target n |
| 60 | … "container:Omnigent.xcodeproj"> | keep-internal |  | Scheme reference to the Omnigent.xcodeproj conta |
| 79 | BuildableName = "Omnigent.app" | keep-internal |  | Scheme BuildableName Omnigent.app for the launch |
| 80 | BlueprintName = "Omnigent" | keep-internal |  | Scheme BlueprintName Omnigent; internal target n |
| 81 | … "container:Omnigent.xcodeproj"> | keep-internal |  | Scheme reference to the Omnigent.xcodeproj conta |
| 96 | BuildableName = "Omnigent.app" | keep-internal |  | Scheme BuildableName Omnigent.app for the profil |
| 97 | BlueprintName = "Omnigent" | keep-internal |  | Scheme BlueprintName Omnigent; internal target n |
| 98 | … "container:Omnigent.xcodeproj"> | keep-internal |  | Scheme reference to the Omnigent.xcodeproj conta |

### `web/ios/Omnigent/AppRootView.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 56 | (try? DatabricksCredentialScope( | keep-internal |  | code identifier |
| 65 | error: DatabricksSessionError.signOutI… | keep-internal |  | code identifier |
| 77 | .id(DatabricksWebContext.contextIdenti… | keep-internal |  | code identifier |
| 93 | …text = try? DatabricksWebContext.resol… | keep-internal |  | code identifier |
| 94 | DatabricksSignOutManager.shared.isPend… | keep-internal |  | code identifier |
| 99 | …eanup = try DatabricksSignOutManager.s… | keep-internal |  | code identifier |
| 100 | …ext, store: DatabricksWebStore(identif… | keep-internal |  | code identifier |
| 105 | …ved, error: DatabricksSessionError.sig… | keep-internal |  | code identifier |
| 124 | …link (e.g. ˋomnigent://host/c/<id>ˋ), … | keep-internal |  | code comment |
| 128 | …processInfo.omnigentOpenURLArgument el… | keep-internal |  | code identifier |
| 135 | "Open this Omnigent link?", | change | S38 | Deep-link consent alert title shown to users; roadmap ties AppRootView consent copy to the S38 scheme change. |
| 144 | This link will connect Omnigent to \(consentDeepLink.origin.hostLabel) and open a conversation. | change | S38 | Deep-link consent alert copy shown to users. |
| 170 | …nvironment["OMNIGENT_SCREENSHOT_APP_UR… | keep-internal |  | OMNIGENT_SCREENSHOT_APP_URL env var (DEBUG scree |
| 180 | /// The ˋ--omnigent-open-url <url>ˋ DE… | keep-internal |  | code comment |
| 183 | …private var omnigentOpenURLArgument: U… | keep-internal |  | code identifier |
| 184 | …ndex(of: "--omnigent-open-url"), | keep-internal |  | DEBUG-only --omnigent-open-url launch argument u |
| 195 | … Handle an ˋomnigent://ˋ URL the syste… | keep-internal |  | code comment |
| 209 | …nvironment["OMNIGENT_DEEPLINK_TRACE"] … | keep-internal |  | OMNIGENT_DEEPLINK_TRACE DEBUG env var gating NSL |
| 216 | …nvironment["OMNIGENT_DEEPLINK_TRACE"] … | keep-internal |  | OMNIGENT_DEEPLINK_TRACE DEBUG env var gating NSL |
| 268 | …n serverURL.omnigentOrigin } | keep-internal |  | code identifier |
| 282 | …ing: self)?.omnigentHostLabel ?? self | keep-internal |  | code identifier |

### `web/ios/Omnigent/Assets.xcassets/OmnigentLogo.imageset/Contents.json`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | "filename" : "omnigents-logo.svg", | change-asset | S88 | Omnigent imageset kept in place, unused (L5); CoralLogo/CoralLogoReverse imagesets added beside it. Light Omnigent wordmark shown on the iOS |

### `web/ios/Omnigent/Assets.xcassets/OmnigentLogo.imageset/omnigents-logo.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | iOS connect-screen logo (symlink); CoralLogo imageset added for ConnectView. |

### `web/ios/Omnigent/Assets.xcassets/OmnigentLogoReverse.imageset/Contents.json`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | "filename" : "omnigents-logo-reverse.svg", | change-asset | S88 | Omnigent imageset kept in place, unused (L5); CoralLogo/CoralLogoReverse imagesets added beside it. Dark-mode Omnigent wordmark shown on the |

### `web/ios/Omnigent/Assets.xcassets/OmnigentLogoReverse.imageset/omnigents-logo-reverse.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | iOS connect-screen dark logo (symlink); CoralLogoReverse imageset added for ConnectView. |

### `web/ios/Omnigent/ConnectView.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | Image(colorScheme == .dark ? "OmnigentLogoReverse" : "OmnigentLogo") | change-asset | S88 | Connect-screen artwork references the Omnigent wordmark imagesets. |
| 35 | Text("Enter the URL of the Omnigent server.") | change | S88 | Connect-screen subtitle uses 'Omnigent server' product wording. |
| 154 | .accessibilityLabel("About Omnigent") | change | S88 | VoiceOver accessibility label of the info menu names the product. |
| 239 | case .website: URL(string: "https://omnigent.ai")! | change | S89b | Info-menu Website link points at the Omnigent site; becomes CORAL_HOMEPAGE. |
| 240 | case .docs: URL(string: "https://omnigent.ai/docs")! | keep-deferred |  | omnigent.ai/docs documentation link; stays until Coral has its own docs (OPS-09). |
| 241 | case .privacy: URL(string: "https://omnigent.ai/privacy")! | change | S89b | Info-menu Privacy Policy link points at Omnigent; becomes CORAL_PRIVACY_URL. |

### `web/ios/Omnigent/DatabricksCredentialStore.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | struct DatabricksCredentialScope: Hash… | keep-internal |  | code identifier |
| 9 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 12 | …n.host) == .databricksWorkspace, | keep-internal |  | code identifier |
| 15 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 17 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 21 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 32 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 46 | protocol DatabricksCredentialStoring: … | keep-internal |  | code identifier |
| 47 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 48 | …e(_ tokens: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 49 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 52 | struct DatabricksCredentialStore: Data… | keep-internal |  | code identifier |
| 55 | …tring = "ai.omnigent.ios.databricks-oa… | keep-internal |  | Keychain service id for saved Databricks OAuth t |
| 59 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 66 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 70 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 74 | …e(_ tokens: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 75 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 91 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 94 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 97 | throw DatabricksCredentialError.keycha… | keep-internal |  | code identifier |
| 101 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 112 | let tokens: DatabricksOAuthTokens | keep-internal |  | code identifier |
| 116 | enum DatabricksCredentialError: Error,… | keep-internal |  | code identifier |
| 124 | "Could not access saved Databricks credentials. Unlock the device and try again." | keep-origin |  | Error text naming Databricks credentials for the Databricks workspace sign-in integration. |
| 125 | case .invalidData: "The saved Databricks credentials are invalid. Sign in again." | keep-origin |  | Error text naming Databricks credentials for the Databricks workspace sign-in integration. |

### `web/ios/Omnigent/DatabricksLoginManager.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | final class DatabricksLoginManager { | keep-internal |  | code identifier |
| 6 | …let client: DatabricksOAuthClient | keep-internal |  | code identifier |
| 7 | …kenManager: DatabricksTokenManager | keep-internal |  | code identifier |
| 10 | …ation: Task<DatabricksOAuthTokens, Err… | keep-internal |  | code identifier |
| 15 | client: DatabricksOAuthClient = Databr… | keep-internal |  | code identifier |
| 16 | …kenManager: DatabricksTokenManager = .… | keep-internal |  | code identifier |
| 25 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 26 | …c throws -> DatabricksOAuthTokens { | keep-internal |  | code identifier |
| 28 | …lse { throw DatabricksOAuthError.login… | keep-internal |  | code identifier |
| 29 | …tempt = try DatabricksOAuthAttempt( | keep-internal |  | code identifier |
| 68 | …or attempt: DatabricksOAuthAttempt, an… | keep-internal |  | code identifier |
| 79 | …ress: throw DatabricksOAuthError.login… | keep-internal |  | code identifier |
| 80 | …able: throw DatabricksOAuthError.brows… | keep-internal |  | code identifier |
| 81 | …iled: throw DatabricksOAuthError.authe… | keep-internal |  | code identifier |
| 82 | …back: throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DatabricksOAuthAttempt.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | struct DatabricksOAuthAttempt: Sendabl… | keep-internal |  | code identifier |
| 5 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 6 | …ntialScope: DatabricksCredentialScope | keep-internal |  | code identifier |
| 11 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 12 | …Scope = try DatabricksCredentialScope( | keep-internal |  | code identifier |
| 43 | let issuer: DatabricksOAuthIssuer | keep-internal |  | code identifier |
| 53 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 58 | throw DatabricksOAuthError.invalidCall… | keep-internal |  | code identifier |
| 62 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 64 | ? DatabricksOAuthError.authorizationDe… | keep-internal |  | code identifier |
| 67 | throw DatabricksOAuthError.invalidCall… | keep-internal |  | code identifier |
| 76 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 79 | …issuer: try DatabricksOAuthIssuer(issu… | keep-internal |  | code identifier |
| 82 | …ng, issuer: DatabricksOAuthIssuer? = n… | keep-internal |  | code identifier |
| 83 | DatabricksOAuthClient.tokenRequest( | keep-internal |  | code identifier |
| 96 | throw DatabricksOAuthError.randomGener… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DatabricksOAuthClient.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | struct DatabricksOAuthTokens: Codable,… | keep-internal |  | code identifier |
| 7 | let issuer: DatabricksOAuthIssuer? | keep-internal |  | code identifier |
| 10 | …te, issuer: DatabricksOAuthIssuer? = n… | keep-internal |  | code identifier |
| 26 | protocol DatabricksTokenRefreshing: Se… | keep-internal |  | code identifier |
| 28 | … for scope: DatabricksCredentialScope,… | keep-internal |  | code identifier |
| 30 | -> DatabricksOAuthTokens | keep-internal |  | code identifier |
| 33 | struct DatabricksOAuthClient: Databric… | keep-internal |  | code identifier |
| 43 | …or attempt: DatabricksOAuthAttempt, is… | keep-internal |  | code identifier |
| 45 | -> DatabricksOAuthTokens | keep-internal |  | code identifier |
| 48 | …y issuer ?? DatabricksOAuthIssuer(atte… | keep-internal |  | code identifier |
| 53 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 59 | … for scope: DatabricksCredentialScope, | keep-internal |  | code identifier |
| 60 | issuer: DatabricksOAuthIssuer? = nil | keep-internal |  | code identifier |
| 62 | -> DatabricksOAuthTokens | keep-internal |  | code identifier |
| 82 | throw DatabricksOAuthError.networkUnav… | keep-internal |  | code identifier |
| 86 | throw DatabricksOAuthError.tokenExchan… | keep-internal |  | code identifier |
| 92 | …il, issuer: DatabricksOAuthIssuer? = n… | keep-internal |  | code identifier |
| 94 | async throws -> DatabricksOAuthTokens | keep-internal |  | code identifier |
| 101 | throw DatabricksOAuthError.invalidRefr… | keep-internal |  | code identifier |
| 103 | …lse { throw DatabricksOAuthError.token… | keep-internal |  | code identifier |
| 111 | issuer: DatabricksOAuthIssuer? = nil | keep-internal |  | code identifier |
| 113 | -> DatabricksOAuthTokens | keep-internal |  | code identifier |
| 119 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 120 | let tokens = DatabricksOAuthTokens( | keep-internal |  | code identifier |
| 123 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 128 | for scope: DatabricksCredentialScope, … | keep-internal |  | code identifier |
| 129 | issuer: DatabricksOAuthIssuer? = nil | keep-internal |  | code identifier |
| 151 | …, delegate: DatabricksOAuthRedirectBlo… | keep-internal |  | code identifier |
| 184 | final class DatabricksOAuthRedirectBlo… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DatabricksOAuthConfiguration.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | struct DatabricksOAuthConfiguration: S… | keep-internal |  | code identifier |
| 10 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 21 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 28 | …ionaryKey: "DatabricksOAuthClientID") … | keep-internal |  | Info.plist key name read by code for the Databri |
| 29 | …ionaryKey: "DatabricksOAuthRedirectURL… | keep-internal |  | Info.plist key name read by code for the Databri |
| 46 | enum DatabricksOAuthError: Error, Equa… | keep-internal |  | code identifier |
| 66 | case .invalidClientID: "Configure a Databricks OAuth client ID for this build." | keep-origin |  | User-facing error naming Databricks OAuth, the third-party sign-in service the app integrates with. |
| 68 | case .invalidWorkspace: "Databricks OAuth requires an HTTPS workspace URL." | keep-origin |  | Error names Databricks OAuth / workspace URL as integration target, not publisher. |
| 70 | case .invalidCallback: "Databricks returned an invalid sign-in callback." | keep-origin |  | Error describing the Databricks sign-in callback; factual integration reference. |
| 71 | case .invalidIssuer: "Databricks returned an unsupported OAuth issuer." | keep-origin |  | Error describing Databricks OAuth issuer; factual integration reference. |
| 72 | case .invalidDiscovery: "Databricks returned inconsistent OAuth provider metadata." | keep-origin |  | Error describing Databricks OAuth provider metadata; factual integration reference. |
| 73 | case .authorizationDenied: "Databricks sign-in was not authorized." | keep-origin |  | Databricks sign-in error; names third-party integration service. |
| 74 | case .authorizationFailed: "Databricks could not authorize this sign-in." | keep-origin |  | Databricks authorization error; names third-party integration service. |
| 75 | case .loginInProgress: "A Databricks sign-in is already in progress." | keep-origin |  | Databricks sign-in-in-progress message; integration feature name stays. |
| 77 | case .authenticationFailed: "Databricks browser sign-in failed." | keep-origin |  | Databricks browser sign-in failure message; integration feature name stays. |
| 78 | case .networkUnavailable: "Could not reach Databricks. Please try again." | keep-origin |  | Network error naming the Databricks service being contacted; factual. |
| 79 | case .tokenExchangeFailed: "Databricks could not complete sign-in. Please sign in again." | keep-origin |  | Databricks token exchange error; names third-party integration service. |
| 80 | case .invalidRefreshGrant: "The saved Databricks session has expired. Please sign in again." | keep-origin |  | Expired Databricks session message; integration feature name stays. |
| 81 | case .invalidTokenResponse: "Databricks returned an invalid token response." | keep-origin |  | Databricks invalid token response error; factual integration reference. |

### `web/ios/Omnigent/DatabricksOAuthIssuer.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | struct DatabricksOAuthIssuer: Codable,… | keep-internal |  | code identifier |
| 10 | …s.host) == .databricksWorkspace, | keep-internal |  | code identifier |
| 14 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 18 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 23 | throw DatabricksOAuthError.invalidIssu… | keep-internal |  | code identifier |
| 36 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DatabricksSessionClient.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | protocol DatabricksSessionCreating { | keep-internal |  | code identifier |
| 5 | …te(context: DatabricksWebContext, toke… | keep-internal |  | code identifier |
| 6 | -> DatabricksWebSession | keep-internal |  | code identifier |
| 9 | struct DatabricksWebSession { | keep-internal |  | code identifier |
| 13 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 16 | …rl: URL) -> DatabricksCredentialScope?… | keep-internal |  | code identifier |
| 18 | …cope = try? DatabricksCredentialScope(… | keep-internal |  | code identifier |
| 44 | … == pageURL.omnigentOrigin, let worksp… | keep-internal |  | code identifier |
| 61 | enum DatabricksSessionVerdict: Equatab… | keep-internal |  | code identifier |
| 72 | struct DatabricksSessionClient: Databr… | keep-internal |  | code identifier |
| 73 | …transport = DatabricksOAuthClient.make… | keep-internal |  | code identifier |
| 78 | …te(context: DatabricksWebContext, toke… | keep-internal |  | code identifier |
| 79 | -> DatabricksWebSession | keep-internal |  | code identifier |
| 81 | …s.isValid, !DatabricksWebSession.isLog… | keep-internal |  | code identifier |
| 82 | throw DatabricksSessionError.invalidRe… | keep-internal |  | code identifier |
| 87 | throw DatabricksSessionError.workspace… | keep-internal |  | code identifier |
| 100 | …Scope = try DatabricksCredentialScope( | keep-internal |  | code identifier |
| 121 | throw DatabricksSessionError.invalidRe… | keep-internal |  | code identifier |
| 128 | …= error as? DatabricksSessionError { t… | keep-internal |  | code identifier |
| 129 | throw DatabricksSessionError.networkUn… | keep-internal |  | code identifier |
| 150 | …cope = try? DatabricksCredentialScope( | keep-internal |  | code identifier |
| 152 | …lse { throw DatabricksSessionError.uns… | keep-internal |  | code identifier |
| 155 | throw DatabricksSessionError.workspace… | keep-internal |  | code identifier |
| 168 | throw DatabricksSessionError.rejected(… | keep-internal |  | code identifier |
| 171 | currentURL.omnigentOrigin == context.s… | keep-internal |  | code identifier |
| 172 | … currentURL.omnigentOrigin == startOri… | keep-internal |  | code identifier |
| 178 | throw DatabricksSessionError.unexpecte… | keep-internal |  | code identifier |
| 193 | throw DatabricksSessionError.missingCo… | keep-internal |  | code identifier |
| 195 | return DatabricksWebSession( | keep-internal |  | code identifier |
| 198 | …startOrigin.omnigentOrigin!, | keep-internal |  | code identifier |
| 199 | …ext.pageURL.omnigentOrigin!, pageURL.o… | keep-internal |  | code identifier |
| 203 | throw DatabricksSessionError.unsafeRed… | keep-internal |  | code identifier |
| 208 | …e) async -> DatabricksSessionVerdict { | keep-internal |  | code identifier |
| 240 | DatabricksWebSession.isLoginPath(targe… | keep-internal |  | code identifier |
| 248 | …in(context: DatabricksWebContext, toke… | keep-internal |  | code identifier |
| 252 | …cope = try? DatabricksCredentialScope( | keep-internal |  | code identifier |
| 262 | throw DatabricksSessionError.invalidRe… | keep-internal |  | code identifier |
| 270 | …domain) == .databricksWorkspace, | keep-internal |  | code identifier |
| 276 | …lse { throw DatabricksSessionError.uns… | keep-internal |  | code identifier |
| 279 | throw DatabricksSessionError.unsafeCoo… | keep-internal |  | code identifier |
| 304 | enum DatabricksSessionError: Error, Eq… | keep-internal |  | code identifier |
| 314 | case .invalidResponse: "Databricks returned an invalid session response." | keep-origin |  | Error naming Databricks workspace session service; integration target, not publisher. |
| 315 | case .unsafeRedirect: "Databricks returned an unsupported session redirect." | keep-origin |  | Error naming Databricks session redirect; integration target. |
| 318 | "Databricks returned a session cookie with an unsupported scope or security attributes." | keep-origin |  | Error naming Databricks session cookie; integration target. |
| 319 | case .missingCookie: "Databricks did not create a session cookie for this workspace." | keep-origin |  | Error naming Databricks workspace cookie; integration target. |
| 320 | case .unexpectedLanding: "Databricks did not finish loading the workspace session." | keep-origin |  | Error naming Databricks workspace session load; integration target. |
| 321 | case .networkUnavailable: "Could not reach Databricks. Please try again." | keep-origin |  | Network error naming the Databricks service contacted; factual. |
| 322 | case .rejected(let status): "Databricks rejected session creation (HTTP \(status))." | keep-origin |  | Databricks rejected session creation error; integration target. |

### `web/ios/Omnigent/DatabricksTokenManager.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | actor DatabricksTokenManager { | keep-internal |  | code identifier |
| 5 | …et shared = DatabricksTokenManager() | keep-internal |  | code identifier |
| 7 | … store: any DatabricksCredentialStorin… | keep-internal |  | code identifier |
| 8 | …client: any DatabricksTokenRefreshing | keep-internal |  | code identifier |
| 10 | …refreshes: [DatabricksCredentialScope:… | keep-internal |  | code identifier |
| 11 | …nerations: [DatabricksCredentialScope:… | keep-internal |  | code identifier |
| 12 | …r signIns: [DatabricksCredentialScope:… | keep-internal |  | code identifier |
| 14 | …ingWrites: [DatabricksCredentialScope:… | keep-internal |  | code identifier |
| 17 | store: any DatabricksCredentialStoring… | keep-internal |  | code identifier |
| 18 | client: any DatabricksTokenRefreshing … | keep-internal |  | code identifier |
| 27 | … let scope: DatabricksCredentialScope | keep-internal |  | code identifier |
| 31 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 42 | …e(_ tokens: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 47 | …e(_ tokens: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 49 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 56 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 64 | …t(_ tokens: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 72 | …h(rejected: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 73 | -> DatabricksOAuthTokens? | keep-internal |  | code identifier |
| 78 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 83 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 87 | …(for scope: DatabricksCredentialScope,… | keep-internal |  | code identifier |
| 88 | -> DatabricksOAuthTokens? | keep-internal |  | code identifier |
| 94 | …lse { throw DatabricksCredentialError.… | keep-internal |  | code identifier |
| 114 | …sh(_ saved: DatabricksOAuthTokens, for… | keep-internal |  | code identifier |
| 119 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 129 | … for scope: DatabricksCredentialScope,… | keep-internal |  | code identifier |
| 132 | …ion: Result<DatabricksOAuthTokens?, Er… | keep-internal |  | code identifier |
| 139 | …e error as? DatabricksOAuthError == .i… | keep-internal |  | code identifier |
| 155 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 164 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | code identifier |
| 173 | … for scope: DatabricksCredentialScope) | keep-internal |  | code identifier |
| 184 | …ct(_ fault: DatabricksCredentialFault,… | keep-internal |  | code identifier |
| 190 | let faulted: DatabricksOAuthTokens | keep-internal |  | code identifier |
| 193 | faulted = DatabricksOAuthTokens( | keep-internal |  | code identifier |
| 198 | faulted = DatabricksOAuthTokens( | keep-internal |  | code identifier |
| 204 | faulted = DatabricksOAuthTokens( | keep-internal |  | code identifier |
| 214 | case save(DatabricksOAuthTokens) | keep-internal |  | code identifier |
| 221 | …ontinuation<DatabricksOAuthTokens?, Er… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DatabricksWebContext.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | struct DatabricksWebContext: Sendable … | keep-internal |  | code identifier |
| 6 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 7 | let scope: DatabricksCredentialScope | keep-internal |  | code identifier |
| 10 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 12 | !(url.omnigentOrigin == configuration.… | keep-internal |  | code identifier |
| 14 | !DatabricksWebSession.isLoginPath(url.… | keep-internal |  | code identifier |
| 15 | …lse { throw DatabricksOAuthError.inval… | keep-internal |  | code identifier |
| 17 | scope = try DatabricksCredentialScope(… | keep-internal |  | code identifier |
| 22 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 35 | throw DatabricksSessionError.workspace… | keep-internal |  | code identifier |
| 41 | …origin: url.omnigentOrigin) == .databr… | keep-internal |  | code identifier |
| 55 | return url.omnigentHostLabel + " · " +… | keep-internal |  | code identifier |
| 57 | return url.omnigentHostLabel | keep-internal |  | code identifier |
| 72 | …ata: Data(("omnigent.databricks.web.v1… | keep-internal |  | Hash salt deriving persisted WKWebsiteDataStore |
| 84 | protocol DatabricksWebStoring: AnyObje… | keep-internal |  | code identifier |
| 93 | final class DatabricksWebStore: Databr… | keep-internal |  | code identifier |
| 117 | final class DatabricksCookieInstaller … | keep-internal |  | code identifier |
| 118 | …et shared = DatabricksCookieInstaller(… | keep-internal |  | code identifier |
| 122 | … store: any DatabricksWebStoring, rese… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DatabricksWorkspaceBootstrap.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | protocol DatabricksSigningIn { | keep-internal |  | code identifier |
| 7 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | code identifier |
| 8 | …c throws -> DatabricksOAuthTokens | keep-internal |  | code identifier |
| 12 | extension DatabricksLoginManager: Data… | keep-internal |  | code identifier |
| 15 | final class DatabricksWorkspaceBootstr… | keep-internal |  | code identifier |
| 16 | …let tokens: DatabricksTokenManager | keep-internal |  | code identifier |
| 17 | … login: any DatabricksSigningIn | keep-internal |  | code identifier |
| 18 | …ssions: any DatabricksSessionCreating | keep-internal |  | code identifier |
| 19 | … installer: DatabricksCookieInstaller | keep-internal |  | code identifier |
| 20 | …t signOuts: DatabricksSignOutManager | keep-internal |  | code identifier |
| 23 | tokens: DatabricksTokenManager = .shar… | keep-internal |  | code identifier |
| 24 | login: (any DatabricksSigningIn)? = ni… | keep-internal |  | code identifier |
| 25 | …sions: (any DatabricksSessionCreating)… | keep-internal |  | code identifier |
| 26 | installer: DatabricksCookieInstaller? … | keep-internal |  | code identifier |
| 27 | signOuts: DatabricksSignOutManager? = … | keep-internal |  | code identifier |
| 30 | … = login ?? DatabricksLoginManager(tok… | keep-internal |  | code identifier |
| 31 | …sessions ?? DatabricksSessionClient() | keep-internal |  | code identifier |
| 37 | context: DatabricksWebContext, store: … | keep-internal |  | code identifier |
| 38 | intent: DatabricksConnectionIntent = .… | keep-internal |  | code identifier |
| 39 | …c throws -> DatabricksWebSession { | keep-internal |  | code identifier |
| 42 | throw DatabricksSessionError.workspace… | keep-internal |  | code identifier |
| 52 | throw DatabricksSessionError.credentia… | keep-internal |  | code identifier |
| 58 | var credential: DatabricksOAuthTokens | keep-internal |  | code identifier |
| 62 | …lse { throw DatabricksSessionError.rea… | keep-internal |  | code identifier |
| 70 | let session: DatabricksWebSession | keep-internal |  | code identifier |
| 73 | } catch DatabricksSessionError.rejecte… | keep-internal |  | code identifier |
| 77 | throw DatabricksSessionError.reauthent… | keep-internal |  | code identifier |
| 87 | throw DatabricksSessionError.credentia… | keep-internal |  | code identifier |
| 95 | throw DatabricksSessionError.credentia… | keep-internal |  | code identifier |
| 103 | && DatabricksSessionClient.cookie(cook… | keep-internal |  | code identifier |
| 109 | …lse { throw DatabricksSessionError.mis… | keep-internal |  | code identifier |
| 113 | throw DatabricksSessionError.credentia… | keep-internal |  | code identifier |
| 123 | _ fault: DatabricksDebugFault, context… | keep-internal |  | code identifier |
| 126 | throw DatabricksSessionError.workspace… | keep-internal |  | code identifier |
| 137 | …ut(context: DatabricksWebContext, stor… | keep-internal |  | code identifier |
| 147 | enum DatabricksConnectionIntent { | keep-internal |  | code identifier |
| 154 | enum DatabricksDebugFault: String, Cas… | keep-internal |  | code identifier |
| 193 | …credential: DatabricksCredentialFault?… | keep-internal |  | code identifier |
| 203 | enum DatabricksCredentialFault: Sendab… | keep-internal |  | code identifier |
| 208 | struct DatabricksRecoveryPolicy { | keep-internal |  | code identifier |
| 224 | final class DatabricksSignOutManager { | keep-internal |  | code identifier |
| 225 | …et shared = DatabricksSignOutManager() | keep-internal |  | code identifier |
| 226 | …let tokens: DatabricksTokenManager | keep-internal |  | code identifier |
| 227 | … installer: DatabricksCookieInstaller | keep-internal |  | code identifier |
| 231 | …ndingKey = "omnigent.pendingWorkspaceS… | keep-internal |  | UserDefaults key persisting pending sign-out cle |
| 234 | tokens: DatabricksTokenManager = .shar… | keep-internal |  | code identifier |
| 248 | …in(context: DatabricksWebContext, stor… | keep-internal |  | code identifier |
| 252 | throw DatabricksSessionError.workspace… | keep-internal |  | code identifier |
| 266 | throw DatabricksSessionError.signOutIn… | keep-internal |  | code identifier |
| 273 | …ng(context: DatabricksWebContext, stor… | keep-internal |  | code identifier |

### `web/ios/Omnigent/DeepLink.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …/ A parsed ˋomnigent://<hostname>/c/<s… | keep-internal |  | code comment |
| 4 | …ell's ˋparseOmnigentDeepLinkˋ (web/ele… | keep-internal |  | code comment |
| 12 | …scheme. The Databricks workspace mount | keep-internal |  | code comment |
| 18 | /// ˋomnigent://ˋ is a **custom URL sc… | keep-internal |  | code comment |
| 20 | …so declare ˋomnigentˋ and win the laun… | keep-internal |  | code comment |
| 25 | …r **managed Databricks domains** (know… | keep-internal |  | code comment |
| 40 | … a clicked ˋomnigent://ˋ link. The | keep-internal |  | code comment |
| 45 | …space.cloud.databricks.com"ˋ. Built ma… | keep-internal |  | code comment |
| 46 | /// ˋURL.omnigentOriginˋ, which return… | keep-internal |  | code comment |
| 96 | …/ Parse an ˋomnigent://ˋ URL. Returns … | keep-internal |  | code comment |
| 97 | /// ˋomnigent://<host>/c/<id>ˋ link (w… | keep-internal |  | code comment |
| 101 | guard raw.scheme?.lowercased() == "omnigent" else { return nil } | change-identity | S38 | Deep-link scheme check for session links; must follow new URL scheme coral. |
| 105 | … link like ˋomnigent://host/c/id%3Fvie… | keep-internal |  | code comment |

### `web/ios/Omnigent/Info-Debug.plist`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | <string>ai.omnigent.ios.deeplink</string> | keep-deferred |  | CFBundleURLName reverse-DNS label derived from iOS bundle id ai.omnigent.ios; not compared by code; follows mobile bundle ids (OQ-31). |
| 30 | <string>omnigent</string> | change-identity | S38 | CFBundleURLSchemes registration of session deep-link scheme; becomes coral. |
| 34 | <key>DatabricksOAuthClientID</key> | keep-internal |  | Info.plist config key for Databricks OAuth integ |
| 35 | <string>$(DATABRICKS_OAUTH_CLIENT_ID)<… | keep-internal |  | Build-setting reference for the Databricks OAuth |
| 36 | <key>DatabricksOAuthRedirectURL</key> | keep-internal |  | Info.plist config key for Databricks OAuth redir |
| 37 | <string>$(DATABRICKS_OAUTH_REDIRECT_UR… | keep-internal |  | Build-setting reference for the Databricks OAuth |
| 48 | <string>Omnigent uses the camera when you choose to take a photo for an attachment.</string> | change | S88 | NSCameraUsageDescription shown in the iOS camera permission prompt names the product. |
| 50 | <string>Omnigent uses the microphone for voice dictation in the message composer.</string> | change | S88 | NSMicrophoneUsageDescription shown in the iOS microphone permission prompt names the product. |
| 52 | <string>Omnigent uses speech recognition to turn voice dictation into message text.</string> | change | S88 | NSSpeechRecognitionUsageDescription shown in the iOS permission prompt names the product. |

### `web/ios/Omnigent/Info-Release.plist`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | <string>ai.omnigent.ios.deeplink</string> | keep-deferred |  | CFBundleURLName reverse-DNS label derived from iOS bundle id ai.omnigent.ios; not compared by code; follows mobile bundle ids (OQ-31). |
| 30 | <string>omnigent</string> | change-identity | S38 | CFBundleURLSchemes registration of session deep-link scheme; becomes coral. |
| 34 | <key>DatabricksOAuthClientID</key> | keep-internal |  | Info.plist config key for Databricks OAuth integ |
| 35 | <string>$(DATABRICKS_OAUTH_CLIENT_ID)<… | keep-internal |  | Build-setting reference for the Databricks OAuth |
| 36 | <key>DatabricksOAuthRedirectURL</key> | keep-internal |  | Info.plist config key for Databricks OAuth redir |
| 37 | <string>$(DATABRICKS_OAUTH_REDIRECT_UR… | keep-internal |  | Build-setting reference for the Databricks OAuth |
| 43 | <string>Omnigent uses the camera when you choose to take a photo for an attachment.</string> | change | S88 | NSCameraUsageDescription shown in the iOS camera permission prompt names the product. |
| 45 | <string>Omnigent uses the microphone for voice dictation in the message composer.</string> | change | S88 | NSMicrophoneUsageDescription shown in the iOS microphone permission prompt names the product. |
| 47 | <string>Omnigent uses speech recognition to turn voice dictation into message text.</string> | change | S88 | NSSpeechRecognitionUsageDescription shown in the iOS permission prompt names the product. |

### `web/ios/Omnigent/ManagedConfiguration.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | struct OmnigentManagedConfiguration: D… | keep-internal |  | code identifier |
| 18 | …te(set) var databricksInternalFeatures… | keep-internal |  | code identifier |
| 20 | …let empty = OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 28 | case databricksInternalFeaturesEnabled | keep-internal |  | code identifier |
| 31 | …RLs: [URL], databricksInternalFeatures… | keep-internal |  | code identifier |
| 33 | self.databricksInternalFeaturesEnabled… | keep-internal |  | code identifier |
| 39 | databricksInternalFeaturesEnabled = | keep-internal |  | code identifier |
| 40 | …f, forKey: .databricksInternalFeatures… | keep-internal |  | code identifier |
| 71 | …tching ˋURL.omnigentOriginˋ everywhere… | keep-internal |  | code comment |
| 72 | …rigin = url.omnigentOrigin else { thro… | keep-internal |  | code identifier |
| 86 | databricksInternalFeaturesEnabled: (de… | keep-internal |  | code identifier |
| 125 | …efaults) -> OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 161 | …ompactMap(\.omnigentOrigin)) | keep-internal |  | code identifier |
| 163 | …ng: value)?.omnigentOrigin else { retu… | keep-internal |  | code identifier |

### `web/ios/Omnigent/ManagedConfigurationProvider.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | …figuration: OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 19 | var databricksInternalFeaturesEnabled:… | keep-internal |  | code identifier |
| 22 | …figuration: OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 23 | …figuration: OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 29 | …iguration = OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 39 | …processInfo.omnigentManagedServers { | keep-internal |  | code identifier |
| 40 | …iguration = OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 62 | …figurations(OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 93 | …iguration = OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 100 | …iguration = OmnigentManagedConfigurati… | keep-internal |  | code identifier |
| 107 | /// The ˋ--omnigent-managed-servers <u… | keep-internal |  | code comment |
| 112 | …private var omnigentManagedServers: [U… | keep-internal |  | code identifier |
| 113 | …let value = omnigentArgumentValue(afte… | keep-internal |  | DEBUG-only launch argument used by UI tests (Man |

### `web/ios/Omnigent/NativeNotificationManager.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | NSLog("[omnigent] failed to set badge … | keep-internal |  | NSLog debug output tag, not shown in UI. |
| 48 | …dentifier: "omnigent.\(UUID().uuidStri… | keep-internal |  | Internal UNNotificationRequest identifier prefix |
| 56 | NSLog("[omnigent] failed to add notifi… | keep-internal |  | NSLog debug output tag, not shown in UI. |
| 85 | …ocessInfo.isOmnigentScreenshotRun else… | keep-internal |  | code identifier |
| 108 | …ivate var isOmnigentScreenshotRun: Boo… | keep-internal |  | code identifier |
| 109 | …nvironment["OMNIGENT_SCREENSHOT_APP_UR… | keep-internal |  | OMNIGENT_* env var used by screenshot/UI test ru |

### `web/ios/Omnigent/OidcCredentialStore.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …rigin (ˋURL.omnigentOriginˋ). | keep-internal |  | code comment |
| 21 | …tring = "ai.omnigent.ios.oidc") { | keep-internal |  | Keychain service id for stored refresh grants; c |

### `web/ios/Omnigent/OidcCredentials.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 103 | …cheme = "ai.omnigent.ios" | keep-internal |  | OAuth callback scheme ai.omnigent.ios matched ag |
| 104 | …ctURI = "ai.omnigent.ios:/oauth/callba… | keep-internal |  | OAuth redirect URI ai.omnigent.ios:/oauth/callba |
| 280 | …= serverURL.omnigentOrigin else { retu… | keep-internal |  | code identifier |
| 443 | let origin = url.omnigentOrigin | keep-internal |  | code identifier |
| 447 | host = url.omnigentHostLabel | keep-internal |  | code identifier |
| 451 | url.omnigentEndpoint(routePath) | keep-internal |  | code identifier |

### `web/ios/Omnigent/OidcLoginManager.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 60 | loginURL.omnigentOrigin == origin.omni… | keep-internal |  | code identifier |
| 134 | …erField: "X-Omnigent-Code-Verifier") | keep-internal |  | X-Omnigent-Code-Verifier header parsed by omnige |

### `web/ios/Omnigent/OidcWebSession.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …{ serverURL.omnigentOriginIdentity } | keep-internal |  | code identifier |
| 11 | …{ serverURL.omnigentHostLabel } | keep-internal |  | code identifier |
| 15 | … for hosts ˋomnigentOriginˋ can't rebu… | keep-internal |  | code comment |
| 17 | var omnigentOriginIdentity: String { | keep-internal |  | code identifier |
| 18 | …et origin = omnigentOrigin { return or… | keep-internal |  | code identifier |
| 33 | …rigin = url.omnigentOrigin, origin == … | keep-internal |  | code identifier |
| 73 | …rigin = url.omnigentOrigin, origin == … | keep-internal |  | code identifier |
| 91 | …= serverURL.omnigentEndpoint("/v1/me")… | keep-internal |  | code identifier |

### `web/ios/Omnigent/Omnigent.entitlements`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | <string>webcredentials:login.databricks.com</string> | keep-origin |  | Associated domain for Databricks sign-in redirect (login.databricks.com), third-party integration; AASA bundle-id provisioning is OQ-31. |

### `web/ios/Omnigent/OmnigentApp.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | struct OmnigentApp: App { | keep-internal |  | code identifier |
| 33 | /// ˋ__omnigentNativeEmitOpenPathˋ (de… | keep-internal |  | code comment |

### `web/ios/Omnigent/OmnigentWebView.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | struct OmnigentWebView: UIViewRepresen… | keep-internal |  | code identifier |
| 10 | let databricksInternalFeaturesEnabled:… | keep-internal |  | code identifier |
| 21 | …tionIntent: DatabricksConnectionIntent… | keep-internal |  | code identifier |
| 26 | …ignedOut: ((DatabricksWebContext, Task… | keep-internal |  | code identifier |
| 35 | …ror: Error, databricksInternalFeatures… | keep-internal |  | code identifier |
| 38 | if databricksInternalFeaturesEnabled, … | keep-internal |  | code identifier |
| 52 | …tor, name: "omnigentNative") | keep-internal |  | WKScriptMessageHandler bridge name 'omnigentNati |
| 112 | …r(forName: "omnigentNative") | keep-internal |  | Removes the 'omnigentNative' script message hand |
| 119 | if (window.omnigentNative && window.om… | keep-internal |  | code identifier |
| 200 | …fineEmit("__omnigentNativeEmitNotifica… | keep-internal |  | Injected JS global __omnigentNativeEmitNotificat |
| 206 | …fineEmit("__omnigentNativeEmitOpenPath… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitOp |
| 212 | …fineEmit("__omnigentNativeEmitViewMode… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitVi |
| 219 | …fineEmit("__omnigentNativeEmitServerPi… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitSe |
| 236 | …fineEmit("__omnigentNativeEmitSignOutR… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitSi |
| 245 | …fineEmit("__omnigentNativeEmitKeyboard… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitKe |
| 256 | …fineEmit("__omnigentNativeEmitInsets",… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitIn |
| 267 | …(window, "__omnigentNativeEmitSidebarD… | keep-internal |  | Injected JS bridge global __omnigentNativeEmitSi |
| 282 | window.omnigentNative = Object.freeze(… | keep-internal |  | code identifier |
| 286 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 292 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 298 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 325 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 331 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 338 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 358 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 374 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 381 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 388 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | JS posts to window.webkit.messageHandlers.omnige |
| 392 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 398 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 403 | …ageHandlers.omnigentNative.postMessage… | keep-internal |  | code identifier |
| 414 | var parent: OmnigentWebView | keep-internal |  | code identifier |
| 450 | …ult: Result<DatabricksWebContext?, Err… | keep-internal |  | code identifier |
| 451 | …t webStore: DatabricksWebStore? | keep-internal |  | code identifier |
| 452 | …eBootstrap: DatabricksWorkspaceBootstr… | keep-internal |  | code identifier |
| 453 | …ionClient = DatabricksSessionClient() | keep-internal |  | code identifier |
| 454 | …aceSession: DatabricksWebSession? | keep-internal |  | code identifier |
| 463 | _ parent: OmnigentWebView, context: Da… | keep-internal |  | code identifier |
| 464 | bootstrap: DatabricksWorkspaceBootstra… | keep-internal |  | code identifier |
| 467 | … context ?? DatabricksWebContext.resol… | keep-internal |  | code identifier |
| 469 | …ootstrap ?? DatabricksWorkspaceBootstr… | keep-internal |  | code identifier |
| 472 | let store = DatabricksWebStore(identif… | keep-internal |  | code identifier |
| 511 | …paceFailure(DatabricksSessionError.wor… | keep-internal |  | code identifier |
| 561 | …on the bare Databricks workspace root … | keep-internal |  | code comment |
| 562 | … serves the Databricks landing page, s… | keep-internal |  | code comment |
| 565 | …ew.url, url.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 573 | …ˋ is a bare Databricks workspace root,… | keep-internal |  | code comment |
| 648 | …ebView.url?.omnigentOrigin.map { $0 !=… | keep-internal |  | code identifier |
| 673 | …paceFailure(DatabricksSessionError.can… | keep-internal |  | code identifier |
| 683 | effectiveOrigin = url.omnigentOrigin | keep-internal |  | code identifier |
| 689 | …rent = try? DatabricksWebContext(url: … | keep-internal |  | code identifier |
| 692 | …paceFailure(DatabricksSessionError.wor… | keep-internal |  | code identifier |
| 703 | …paceFailure(DatabricksSessionError.pre… | keep-internal |  | code identifier |
| 709 | _ context: DatabricksWebContext, in we… | keep-internal |  | code identifier |
| 725 | …ion.pageURL.omnigentOrigin | keep-internal |  | code identifier |
| 732 | …f error as? DatabricksSessionError == … | keep-internal |  | code identifier |
| 741 | …tionError ? DatabricksSessionError.can… | keep-internal |  | code identifier |
| 751 | …paceFailure(DatabricksSessionError.rec… | keep-internal |  | code identifier |
| 777 | && DatabricksSessionClient.cookie($0, … | keep-internal |  | code identifier |
| 790 | …paceFailure(DatabricksSessionError.rej… | keep-internal |  | code identifier |
| 818 | …latMap { $0.omnigentOrigin == pageURL.… | keep-internal |  | code identifier |
| 831 | …n = pageURL.omnigentOrigin | keep-internal |  | code identifier |
| 1218 | …lt(_ fault: DatabricksDebugFault) asyn… | keep-internal |  | code identifier |
| 1234 | …ror: Error, databricksInternalFeatures… | keep-internal |  | code identifier |
| 1236 | …\| error as? DatabricksSessionError == … | keep-internal |  | code identifier |
| 1237 | return OmnigentWebView.connectionError… | keep-internal |  | code identifier |
| 1238 | for: error, databricksInternalFeatures… | keep-internal |  | code identifier |
| 1264 | databricksInternalFeaturesEnabled: par… | keep-internal |  | code identifier |
| 1368 | …url) \|\| url.omnigentOrigin != pinnedOr… | keep-internal |  | code identifier |
| 1371 | …paceFailure(DatabricksSessionError.wor… | keep-internal |  | code identifier |
| 1382 | url.omnigentOrigin != pinnedOrigin, | keep-internal |  | code identifier |
| 1414 | effectiveOrigin = url.omnigentOrigin | keep-internal |  | code identifier |
| 1421 | …lf, and the Databricks | keep-internal |  | code comment |
| 1435 | …ew.url, url.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1440 | // Databricks workspace-hosted Omnigen… | keep-internal |  | code comment |
| 1442 | // Omnigent's own root — see Workspace… | keep-internal |  | code comment |
| 1447 | …ebView.url?.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1507 | …!= nil, url.omnigentOrigin != pinnedOr… | keep-internal |  | code identifier |
| 1510 | …paceFailure(DatabricksSessionError.wor… | keep-internal |  | code identifier |
| 1525 | … belongs to Databricks | keep-internal |  | code comment |
| 1527 | …= true, url.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1550 | url.omnigentOrigin != pinnedOrigin | keep-internal |  | code identifier |
| 1554 | …ebView.url?.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1616 | …paceFailure(DatabricksSessionError.rej… | keep-internal |  | code identifier |
| 1643 | origin.omnigentOrigin == pinnedOrigin, | keep-internal |  | code identifier |
| 1644 | …ebView.url?.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1663 | …urityOrigin.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1664 | …bView?.url?.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1697 | …bView?.url?.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1706 | …bView?.url?.omnigentOrigin ?? "This pa… | keep-internal |  | code identifier |
| 1737 | …paceFailure(DatabricksSessionError.net… | keep-internal |  | code identifier |
| 1745 | …d failedURL.omnigentOrigin == pinnedOr… | keep-internal |  | code identifier |
| 1748 | OmnigentWebView.connectionErrorMessage… | keep-internal |  | code identifier |
| 1749 | for: error, databricksInternalFeatures… | keep-internal |  | code identifier |
| 1774 | return root?.omnigentTopViewController | keep-internal |  | code identifier |
| 1779 | … Success == DatabricksWebContext?, Fai… | keep-internal |  | code identifier |
| 1780 | …hat isn't a Databricks host, so its ma… | keep-internal |  | code comment |
| 1783 | …origin: url.omnigentOrigin) == .oidc | keep-internal |  | code identifier |
| 1844 | "window.__omnigentNativeEmitKeyboardVi… | keep-internal |  | evaluateJavaScript calls window.__omnigentNative |
| 1887 | …private var omnigentTopViewController:… | keep-internal |  | code identifier |
| 1889 | …wController.omnigentTopViewController | keep-internal |  | code identifier |
| 1894 | …urn visible.omnigentTopViewController | keep-internal |  | code identifier |
| 1899 | …rn selected.omnigentTopViewController | keep-internal |  | code identifier |

### `web/ios/Omnigent/SafariView.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …out leaving Omnigent. | keep-internal |  | code comment |

### `web/ios/Omnigent/ServerManifest.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | ….well-known/omnigent.jsonˋ, read befor… | keep-internal |  | code comment |
| 33 | ….well-known/omnigent.json" | keep-internal |  | API path /.well-known/omnigent.json served by om |
| 59 | …= serverURL.omnigentOrigin, let url = … | keep-internal |  | code identifier |

### `web/ios/Omnigent/SettingsStore.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 32 | …sts pass ˋ--omnigent-reset-stateˋ to s… | keep-internal |  | code comment |
| 35 | …contains("--omnigent-reset-state") { | keep-internal |  | DEBUG-only UI-test launch argument --omnigent-re |
| 43 | …processInfo.omnigentArgumentValue(afte… | keep-internal |  | DEBUG-only launch argument --omnigent-server-url |
| 44 | …nvironment["OMNIGENT_SCREENSHOT_APP_UR… | keep-internal |  | OMNIGENT_SCREENSHOT_APP_URL env var (OMNIGENT_* |
| 52 | …(_ context: DatabricksWebContext) { | keep-internal |  | code identifier |
| 54 | …cope = try? DatabricksCredentialScope( | keep-internal |  | code identifier |
| 65 | …ng: saved)?.omnigentOriginIdentity == … | keep-internal |  | code identifier |
| 74 | …ng: saved)?.omnigentOriginIdentity == … | keep-internal |  | code identifier |
| 104 | …value), url.omnigentOrigin == origin e… | keep-internal |  | code identifier |
| 130 | …erverURL = "omnigent.serverURL" | keep-internal |  | UserDefaults key omnigent.serverURL; persisted s |
| 131 | …tServers = "omnigent.recentServers" | keep-internal |  | UserDefaults key omnigent.recentServers; persist |
| 132 | …rotocols = "omnigent.allowedProtocols" | keep-internal |  | UserDefaults key omnigent.allowedProtocols; pers |
| 133 | …edServer = "omnigent.autoOpenSuppresse… | keep-internal |  | UserDefaults key omnigent.autoOpenSuppressedServ |
| 139 | func omnigentArgumentValue(after argum… | keep-internal |  | code identifier |

### `web/ios/Omnigent/URL+Omnigent.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | case databricksWorkspace | keep-internal |  | code identifier |
| 7 | case databricksApp | keep-internal |  | code identifier |
| 20 | self = .databricksWorkspace | keep-internal |  | code identifier |
| 22 | self = .databricksApp | keep-internal |  | code identifier |
| 28 | /// Databricks Apps retain inline SSO;… | keep-internal |  | code comment |
| 31 | case .databricksApp: true | keep-internal |  | code identifier |
| 32 | case .databricksWorkspace, .oidc: fals… | keep-internal |  | code identifier |
| 36 | private static let workspaceDomains = ["databricks.com", "azuredatabricks.net"] | keep-origin |  | Databricks workspace host domains used to detect the Databricks integration target for native sign-in; factual third-party service. |
| 37 | private static let appsDomain = "databricksapps.com" | keep-origin |  | databricksapps.com domain detects Databricks Apps hosting (integration target); factual third-party service. |
| 45 | var omnigentOrigin: String? { | keep-internal |  | code identifier |
| 55 | … ˋhttps://h/omnigent/ˋ + ˋ/v1/meˋ is ˋ… | keep-internal |  | code comment |
| 56 | func omnigentEndpoint(_ routePath: Str… | keep-internal |  | code identifier |
| 69 | var omnigentHostLabel: String { | keep-internal |  | code identifier |
| 79 | var omnigentOrigin: String? { | keep-internal |  | code identifier |

### `web/ios/Omnigent/WebShellView.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …ignedOut: ((DatabricksWebContext, Task… | keep-internal |  | code identifier |
| 30 | …eryPolicy = DatabricksRecoveryPolicy() | keep-internal |  | code identifier |
| 37 | … initialURL.omnigentOrigin) == .databr… | keep-internal |  | code identifier |
| 45 | OmnigentWebView( | keep-internal |  | code identifier |
| 49 | databricksInternalFeaturesEnabled: man… | keep-internal |  | code identifier |
| 76 | .id(DatabricksWebContext.viewIdentity(… | keep-internal |  | code identifier |
| 115 | …t for it (ˋ.omnigent-native-bottom- | keep-internal |  | code comment |
| 136 | …: { (fault: DatabricksDebugFault) in | keep-internal |  | code identifier |
| 161 | ?? DatabricksSessionError.reauthentica… | keep-internal |  | code identifier |
| 215 | …initialURL, DatabricksSessionError.rec… | keep-internal |  | code identifier |
| 230 | …eryPolicy = DatabricksRecoveryPolicy() | keep-internal |  | code identifier |
| 245 | …initialURL).omnigentOrigin, | keep-internal |  | code identifier |
| 283 | …RL: URL) -> DatabricksConnectionIntent… | keep-internal |  | code identifier |
| 304 | Label(DatabricksWebContext.serverLabel… | keep-internal |  | code identifier |
| 310 | … currentURL.omnigentOrigin) == .databr… | keep-internal |  | code identifier |
| 311 | return DatabricksWebContext.contextIde… | keep-internal |  | code identifier |
| 312 | != DatabricksWebContext.contextIdentit… | keep-internal |  | code identifier |
| 314 | return url.omnigentOrigin != currentUR… | keep-internal |  | code identifier |
| 322 | …cent).map { DatabricksWebContext.serve… | keep-internal |  | code identifier |
| 342 | … currentURL.omnigentOrigin) == .databr… | keep-internal |  | code identifier |
| 349 | Text(DatabricksWebContext.serverLabel(… | keep-internal |  | code identifier |
| 394 | extension DatabricksDebugFault: Sessio… | keep-internal |  | code identifier |

### `web/ios/Omnigent/WebViewModel.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | …bugFault: ((DatabricksDebugFault) asyn… | keep-internal |  | code identifier |
| 74 | "window.__omnigentNativeEmitNotificati… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitNot |
| 86 | …= "window.__omnigentNativeEmitOpenPath… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitOpe |
| 92 | …into its ˋ--omnigent-inset-*ˋ variable… | keep-internal |  | code comment |
| 97 | "window.__omnigentNativeEmitInsets?.(\… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitIns |
| 113 | …t("window.__omnigentNativeEmitServerPi… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitSer |
| 139 | …t("window.__omnigentNativeEmitSignOutR… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitSig |
| 145 | "window.__omnigentNativeEmitViewModeCh… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitVie |
| 152 | "window.__omnigentNativeEmitSidebarDra… | keep-internal |  | Calls injected JS bridge __omnigentNativeEmitSid |

### `web/ios/Omnigent/WorkspaceChromeScript.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | … Hiding the Databricks workspace navig… | keep-internal |  | code comment |
| 4 | /// Omnigent SPA. Kept in its own WebK… | keep-internal |  | code comment |
| 5 | /// (ˋOmnigentTests/WorkspaceChromeScr… | keep-internal |  | code comment |
| 11 | …t hides the Databricks workspace navig… | keep-internal |  | code comment |
| 13 | … *page*, so Databricks wraps | keep-internal |  | code comment |
| 15 | … We promote Omnigent's own | keep-internal |  | code comment |
| 16 | …// root — ˋ.omnigent-appˋ, which the e… | keep-internal |  | code comment |
| 18 | /// Omnigent's wrapper (defined in THI… | keep-internal |  | code comment |
| 20 | /// Databricks reshuffles its chrome; … | keep-internal |  | code comment |
| 21 | /// no ˋ.omnigent-appˋ, so the rule is… | keep-internal |  | code comment |
| 23 | .omnigent-app { | keep-internal |  | code identifier |
| 34 | … than the ˋ/omnigentˋ mount, so a path… | keep-internal |  | code comment |
| 41 | …"style[data-omnigent-workspace-chrome]… | keep-internal |  | data-omnigent-workspace-chrome attribute on an i |
| 43 | …yle.dataset.omnigentWorkspaceChrome = … | keep-internal |  | code identifier |

### `web/ios/Omnigent/WorkspaceURLExpander.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …// Path the Omnigent SPA is mounted at… | keep-internal |  | code comment |
| 6 | …eUIPath = "/omnigent" | keep-internal |  | /omnigent SPA mount path inside a Databricks wor |
| 14 | …l.host) != .databricksApp, | keep-internal |  | code identifier |
| 39 | guard (http.value(forHTTPHeaderField: "server") ?? "").lowercased() == "databricks" else { | keep-origin |  | Compares HTTP Server header to 'databricks' to detect a Databricks workspace (integration target); value set by Databricks. |
| 48 | … a **bare** Databricks workspace root,… | keep-internal |  | code comment |
| 52 | …t shows the Databricks landing page, n… | keep-internal |  | code comment |
| 54 | /// ˋdatabricksWorkspaceUiUrlˋ; query … | keep-internal |  | code comment |
| 58 | …l.host) == .databricksWorkspace, isBar… | keep-internal |  | code identifier |

### `web/ios/OmnigentTests/ConnectionErrorTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 39 | domain: "OmnigentTests", code: code, | keep-internal |  | test code |
| 53 | let view = OmnigentWebView( | keep-internal |  | test code |
| 55 | databricksInternalFeaturesEnabled: fal… | keep-internal |  | test code |
| 71 | coordinator.parent = OmnigentWebView( | keep-internal |  | test code |
| 73 | databricksInternalFeaturesEnabled: ena… | keep-internal |  | test code |
| 95 | OmnigentWebView.connectionErrorMessage… | keep-internal |  | test code |
| 96 | for: error, databricksInternalFeatures… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksCredentialStoreTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 6 | final class DatabricksCredentialStoreT… | keep-internal |  | test code |
| 9 | …C-123.cloud.databricks.com:443/omnigen… | keep-internal |  | test code |
| 15 | …db-123.azuredatabricks.net")) | keep-internal |  | test code |
| 19 | …c-123.cloud.databricks.com" | keep-internal |  | test code |
| 22 | …e: base + "/omnigent?o=123") | keep-internal |  | test code |
| 23 | …e: base + "/omnigent/c/abc?view=chat&o… | keep-internal |  | test code |
| 24 | …e: base + "/omnigent?o=456") | keep-internal |  | test code |
| 31 | …e: base + "/omnigent?" + query)) { | keep-internal |  | test code |
| 32 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 38 | …rvice = "ai.omnigent.ios.tests.oauth.\… | keep-internal |  | test code |
| 39 | let store = DatabricksCredentialStore(… | keep-internal |  | test code |
| 42 | …db-123.azuredatabricks.net") | keep-internal |  | test code |
| 43 | …c-123.cloud.databricks.com?o=123") | keep-internal |  | test code |
| 56 | … reloaded = DatabricksCredentialStore(… | keep-internal |  | test code |
| 84 | …rvice = "ai.omnigent.ios.tests.oauth.\… | keep-internal |  | test code |
| 86 | let store = DatabricksCredentialStore(… | keep-internal |  | test code |
| 90 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 91 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 94 | …tored = try DatabricksCredentialStore(… | keep-internal |  | test code |
| 109 | …rvice = "ai.omnigent.ios.tests.oauth.\… | keep-internal |  | test code |
| 110 | let store = DatabricksCredentialStore(… | keep-internal |  | test code |
| 127 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 134 | …qual($0 as? DatabricksCredentialError,… | keep-internal |  | test code |
| 142 | …c-123.cloud.databricks.com", clientID:… | keep-internal |  | test code |
| 143 | ) throws -> DatabricksCredentialScope … | keep-internal |  | test code |
| 144 | try DatabricksCredentialScope( | keep-internal |  | test code |
| 146 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 147 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 152 | issuer: DatabricksOAuthIssuer? = nil | keep-internal |  | test code |
| 153 | ) -> DatabricksOAuthTokens { | keep-internal |  | test code |
| 154 | DatabricksOAuthTokens( | keep-internal |  | test code |
| 160 | …class MemoryDatabricksCredentialStore:… | keep-internal |  | test code |
| 163 | …ar values: [DatabricksCredentialScope:… | keep-internal |  | test code |
| 172 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 178 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 181 | …oad { throw DatabricksCredentialError.… | keep-internal |  | test code |
| 185 | …e(_ tokens: DatabricksOAuthTokens, for… | keep-internal |  | test code |
| 188 | …ave { throw DatabricksCredentialError.… | keep-internal |  | test code |
| 192 | …(for scope: DatabricksCredentialScope)… | keep-internal |  | test code |
| 195 | …ete { throw DatabricksCredentialError.… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksLoginManagerTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | @testable import Omnigent | keep-internal |  | test code |
| 9 | final class DatabricksLoginManagerTest… | keep-internal |  | test code |
| 32 | …scope = try DatabricksCredentialScope( | keep-internal |  | test code |
| 48 | …l(error as? DatabricksOAuthError, .log… | keep-internal |  | test code |
| 61 | …l(error as? DatabricksOAuthError, .bro… | keep-internal |  | test code |
| 148 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 154 | error as? DatabricksOAuthError, browse… | keep-internal |  | test code |
| 181 | …l(error as? DatabricksCredentialError,… | keep-internal |  | test code |
| 189 | …scope = try DatabricksCredentialScope( | keep-internal |  | test code |
| 210 | …scope = try DatabricksCredentialScope( | keep-internal |  | test code |
| 225 | …ssuer = try DatabricksOAuthIssuer(auth… | keep-internal |  | test code |
| 231 | …eString + "/omnigent?o=123")! | keep-internal |  | test code |
| 232 | …scope = try DatabricksCredentialScope( | keep-internal |  | test code |
| 247 | …Scope = try DatabricksCredentialScope( | keep-internal |  | test code |
| 268 | …l(error as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 270 | …scope = try DatabricksCredentialScope( | keep-internal |  | test code |
| 275 | … task: Task<DatabricksOAuthTokens, Err… | keep-internal |  | test code |
| 288 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 290 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 294 | …enManager = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 295 | …r manager = DatabricksLoginManager( | keep-internal |  | test code |
| 296 | client: DatabricksOAuthClient(session:… | keep-internal |  | test code |
| 309 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 315 | …ation = try DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 319 | …il) -> Task<DatabricksOAuthTokens, Err… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksOAuthClientTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 5 | final class DatabricksOAuthClientTests… | keep-internal |  | test code |
| 8 | …okens = try DatabricksOAuthClient.toke… | keep-internal |  | test code |
| 53 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 64 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 68 | …l(error as? DatabricksOAuthError, .tok… | keep-internal |  | test code |
| 76 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 80 | …l(error as? DatabricksOAuthError, .tok… | keep-internal |  | test code |
| 87 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 91 | …l(error as? DatabricksOAuthError, .net… | keep-internal |  | test code |
| 108 | …t session = DatabricksOAuthClient.make… | keep-internal |  | test code |
| 136 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 143 | …okens = try DatabricksOAuthClient.toke… | keep-internal |  | test code |
| 154 | try DatabricksOAuthClient.tokens( | keep-internal |  | test code |
| 157 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 163 | …nt, String, DatabricksOAuthError) in [ | keep-internal |  | test code |
| 174 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 178 | …l(error as? DatabricksOAuthError, expe… | keep-internal |  | test code |
| 206 | try DatabricksOAuthClient.tokens(from:… | keep-internal |  | test code |
| 208 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 232 | …ed()).cloud.databricks.com")! | keep-internal |  | test code |
| 250 | session = DatabricksOAuthClient.makeSe… | keep-internal |  | test code |
| 258 | …) throws -> DatabricksOAuthAttempt { | keep-internal |  | test code |
| 259 | try DatabricksOAuthAttempt( | keep-internal |  | test code |
| 261 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 262 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksOAuthIssuerTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 5 | final class DatabricksOAuthIssuerTests… | keep-internal |  | test code |
| 8 | …space.cloud.databricks.com/oidc", | keep-internal |  | test code |
| 9 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 10 | …counts.azuredatabricks.net/oidc/accoun… | keep-internal |  | test code |
| 12 | …ssuer = try DatabricksOAuthIssuer(URL(… | keep-internal |  | test code |
| 17 | …er().decode(DatabricksOAuthIssuer.self… | keep-internal |  | test code |
| 24 | …space.cloud.databricks.com/oidc", | keep-internal |  | test code |
| 25 | …", "https://databricks.com.example.org… | keep-internal |  | test code |
| 26 | …ps://my-app.databricksapps.com/oidc", | keep-internal |  | test code |
| 27 | …space.cloud.databricks.com/oidc", | keep-internal |  | test code |
| 28 | …space.cloud.databricks.com:8443/oidc", | keep-internal |  | test code |
| 29 | …space.cloud.databricks.com/oidc?next=f… | keep-internal |  | test code |
| 30 | …space.cloud.databricks.com/oidc#fragme… | keep-internal |  | test code |
| 31 | …space.cloud.databricks.com", "https://… | keep-internal |  | test code |
| 32 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 33 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 34 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 35 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 37 | …wsError(try DatabricksOAuthIssuer(URL(… | keep-internal |  | test code |
| 38 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 44 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 45 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 56 | …ounts.cloud.databricks.com/oidc/v1/tok… | keep-internal |  | test code |
| 64 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 72 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 79 | …ounts.cloud.databricks.com/oidc"] { | keep-internal |  | test code |
| 83 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 89 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 96 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 114 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 117 | …et client = DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 142 | …= try await DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 146 | …l(error as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 151 | …(_ attempt: DatabricksOAuthAttempt, is… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksOAuthTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 5 | final class DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 7 | …ation = try DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 15 | …nvalue", "$(DATABRICKS_OAUTH_CLIENT_ID… | keep-internal |  | test code |
| 17 | try DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 18 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 20 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 27 | "", "$(DATABRICKS_OAUTH_REDIRECT_URL)"… | keep-internal |  | test code |
| 28 | "omnigent://auth/callback", "https://e… | keep-internal |  | test code |
| 33 | try DatabricksOAuthConfiguration(clien… | keep-internal |  | test code |
| 35 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 42 | …nwrap(info["DatabricksOAuthClientID"] … | keep-internal |  | test code |
| 43 | …nwrap(info["DatabricksOAuthRedirectURL… | keep-internal |  | test code |
| 47 | …wsError(try DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 48 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 51 | …onfig = try DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 58 | final class DatabricksOAuthAttemptTest… | keep-internal |  | test code |
| 61 | …tempt = try DatabricksOAuthAttempt( | keep-internal |  | test code |
| 63 | …C-123.cloud.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 67 | …c-123.cloud.databricks.com") | keep-internal |  | test code |
| 107 | …c-123.cloud.databricks.com", "https://… | keep-internal |  | test code |
| 108 | …", "https://databricks.com.example.org… | keep-internal |  | test code |
| 109 | …c-123.cloud.databricks.com", "https://… | keep-internal |  | test code |
| 112 | try DatabricksOAuthAttempt(workspaceUR… | keep-internal |  | test code |
| 114 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 123 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 127 | …ttp://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 128 | …tps://login.databricks.com:8443/mobile… | keep-internal |  | test code |
| 129 | …/user@login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 130 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 131 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 132 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 135 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 149 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 151 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 159 | …ss_denied", DatabricksOAuthError.autho… | keep-internal |  | test code |
| 164 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 167 | …qual($0 as? DatabricksOAuthError, expe… | keep-internal |  | test code |
| 173 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 175 | …qual($0 as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 180 | …tempt = try DatabricksOAuthAttempt( | keep-internal |  | test code |
| 181 | …db-123.azuredatabricks.net/omnigent")!… | keep-internal |  | test code |
| 184 | …db-123.azuredatabricks.net/oidc/v1/tok… | keep-internal |  | test code |
| 206 | -> DatabricksOAuthConfiguration | keep-internal |  | test code |
| 208 | try DatabricksOAuthConfiguration( | keep-internal |  | test code |
| 209 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 212 | …) throws -> DatabricksOAuthAttempt { | keep-internal |  | test code |
| 213 | try DatabricksOAuthAttempt( | keep-internal |  | test code |
| 214 | …c-123.cloud.databricks.com")!, | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksSessionClientTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 6 | final class DatabricksSessionClientTes… | keep-internal |  | test code |
| 13 | …}?.value, "/omnigent/c/abc?o=123") | keep-internal |  | test code |
| 16 | …ocation": "/omnigent/c/abc?o=123", "Se… | keep-internal |  | test code |
| 18 | …rl!.path, "/omnigent/c/abc") | keep-internal |  | test code |
| 24 | …eString + "/omnigent/c/abc?o=123#messa… | keep-internal |  | test code |
| 25 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 45 | …eString + "/omnigent?o=123"]) | keep-internal |  | test code |
| 47 | …eString + "/omnigent/c/abc#message") | keep-internal |  | test code |
| 48 | …ssuer = try DatabricksOAuthIssuer(auth… | keep-internal |  | test code |
| 49 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 53 | …eString + "/omnigent/c/abc?o=123#messa… | keep-internal |  | test code |
| 65 | …eString + "/omnigent?o=123"] | keep-internal |  | test code |
| 68 | …eString + "/omnigent?o=123") | keep-internal |  | test code |
| 69 | …et client = DatabricksSessionClient(se… | keep-internal |  | test code |
| 70 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 75 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 87 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 88 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 90 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 94 | …l(error as? DatabricksSessionError, .w… | keep-internal |  | test code |
| 99 | …example.org/omnigent", DatabricksSessi… | keep-internal |  | test code |
| 100 | …//workspace.databricks.com/omnigent", … | keep-internal |  | test code |
| 101 | ("/omnigent?o=456", .workspaceChanged)… | keep-internal |  | test code |
| 102 | …r@workspace.databricks.com/omnigent", … | keep-internal |  | test code |
| 106 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 107 | …eString + "/omnigent?o=123"), | keep-internal |  | test code |
| 110 | …l(error as? DatabricksSessionError, ex… | keep-internal |  | test code |
| 123 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 126 | …l(error as? DatabricksSessionError, .u… | keep-internal |  | test code |
| 138 | …ocation": "/omnigent"]) | keep-internal |  | test code |
| 143 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 148 | [DatabricksSessionError.missingCookie,… | keep-internal |  | test code |
| 149 | error as? DatabricksSessionError ?? .i… | keep-internal |  | test code |
| 159 | …ocation": "/omnigent", "Set-Cookie": "… | keep-internal |  | test code |
| 163 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 170 | …space.cloud.databricks.com/omnigent")! | keep-internal |  | test code |
| 172 | …bling.cloud.databricks.com", ".com", "… | keep-internal |  | test code |
| 177 | …wsError(try DatabricksSessionClient.co… | keep-internal |  | test code |
| 178 | …qual($0 as? DatabricksSessionError, .u… | keep-internal |  | test code |
| 181 | …rl, path: "/omnigent") | keep-internal |  | test code |
| 183 | DatabricksSessionClient.cookie(cookie,… | keep-internal |  | test code |
| 185 | DatabricksSessionClient.cookie( | keep-internal |  | test code |
| 186 | …space.cloud.databricks.com/omnigent-ot… | keep-internal |  | test code |
| 188 | DatabricksSessionClient.cookie( | keep-internal |  | test code |
| 189 | …bling.cloud.databricks.com/omnigent")!… | keep-internal |  | test code |
| 196 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 199 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 208 | …= try await DatabricksSessionClient(se… | keep-internal |  | test code |
| 211 | …l(error as? DatabricksSessionError, .u… | keep-internal |  | test code |
| 216 | …rl!.path, "/omnigent/v1/me") | keep-internal |  | test code |
| 223 | …eString + "/omnigent/c/abc?o=123#messa… | keep-internal |  | test code |
| 225 | …ict = await DatabricksSessionClient(se… | keep-internal |  | test code |
| 234 | …next_url=%2Fomnigent"]) }, | keep-internal |  | test code |
| 240 | …ocation": "/omnigent/elsewhere"]) }, .… | keep-internal |  | test code |
| 246 | …_ expected: DatabricksSessionVerdict | keep-internal |  | test code |
| 250 | …ict = await DatabricksSessionClient(se… | keep-internal |  | test code |
| 251 | …hComponent("omnigent"), cookie: cookie… | keep-internal |  | test code |
| 256 | …) throws -> DatabricksWebContext { | keep-internal |  | test code |
| 257 | try DatabricksWebContext( | keep-internal |  | test code |
| 259 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 260 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 277 | …y XCTUnwrap(DatabricksSessionClient.co… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksTokenManagerTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 6 | final class DatabricksTokenManagerTest… | keep-internal |  | test code |
| 8 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 10 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 17 | let restored = DatabricksTokenManager( | keep-internal |  | test code |
| 26 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 31 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 45 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 48 | …t manager = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 68 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 71 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 92 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 94 | …db-123.azuredatabricks.net") | keep-internal |  | test code |
| 97 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 116 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 122 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 124 | …e: .failure(DatabricksOAuthError.inval… | keep-internal |  | test code |
| 133 | DatabricksOAuthError.networkUnavailabl… | keep-internal |  | test code |
| 135 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 139 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 145 | …(actual as? DatabricksOAuthError, erro… | keep-internal |  | test code |
| 152 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 155 | …t manager = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 160 | …l(error as? DatabricksCredentialError,… | keep-internal |  | test code |
| 167 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 169 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 170 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 177 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 183 | …l(error as? DatabricksCredentialError,… | keep-internal |  | test code |
| 196 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 198 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 199 | …space.cloud.databricks.com/oidc")!) | keep-internal |  | test code |
| 202 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 208 | …l(error as? DatabricksOAuthError, .inv… | keep-internal |  | test code |
| 214 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 215 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 216 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 219 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 233 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 238 | …t manager = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 243 | …l(error as? DatabricksCredentialError,… | keep-internal |  | test code |
| 254 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 255 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 256 | …ssuer = try DatabricksOAuthIssuer( | keep-internal |  | test code |
| 257 | …ounts.cloud.databricks.com/oidc/accoun… | keep-internal |  | test code |
| 259 | …ult: Result<DatabricksOAuthTokens, Err… | keep-internal |  | test code |
| 261 | .failure(DatabricksOAuthError.invalidR… | keep-internal |  | test code |
| 265 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 268 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 289 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 295 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 305 | …ore = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 310 | …t manager = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 314 | …l(error as? DatabricksCredentialError,… | keep-internal |  | test code |
| 320 | … task: Task<DatabricksOAuthTokens?, Er… | keep-internal |  | test code |
| 328 | …efreshStub: DatabricksTokenRefreshing … | keep-internal |  | test code |
| 331 | let scope: DatabricksCredentialScope | keep-internal |  | test code |
| 332 | let issuer: DatabricksOAuthIssuer? | keep-internal |  | test code |
| 336 | …nse: Result<DatabricksOAuthTokens, Err… | keep-internal |  | test code |
| 338 | …ontinuation<DatabricksOAuthTokens, Err… | keep-internal |  | test code |
| 341 | …nse: Result<DatabricksOAuthTokens, Err… | keep-internal |  | test code |
| 342 | DatabricksOAuthError.networkUnavailabl… | keep-internal |  | test code |
| 354 | … for scope: DatabricksCredentialScope,… | keep-internal |  | test code |
| 356 | -> DatabricksOAuthTokens | keep-internal |  | test code |
| 361 | let tokens: DatabricksOAuthTokens = tr… | keep-internal |  | test code |
| 370 | …ult: Result<DatabricksOAuthTokens, Err… | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksWebContextTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 7 | final class DatabricksWebContextTests:… | keep-internal |  | test code |
| 9 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 11 | …//WORKSPACE.DATABRICKS.COM:443/omnigen… | keep-internal |  | test code |
| 15 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 18 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 21 | …//workspace.databricks.com?o=123").pag… | keep-internal |  | test code |
| 22 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 26 | …sertNil(try DatabricksWebContext.resol… | keep-internal |  | test code |
| 27 | …sertNil(try DatabricksWebContext.resol… | keep-internal |  | test code |
| 29 | DatabricksWebContext.viewIdentity(for:… | keep-internal |  | test code |
| 31 | …tps://login.databricks.com/mobile-redi… | keep-internal |  | test code |
| 32 | …//workspace.databricks.com/oidc/v1/aut… | keep-internal |  | test code |
| 36 | …ed()).cloud.databricks.com" | keep-internal |  | test code |
| 37 | …s://\(host)/omnigent?o=123") | keep-internal |  | test code |
| 38 | …s://\(host)/omnigent?o=456") | keep-internal |  | test code |
| 39 | let first = DatabricksWebStore(identif… | keep-internal |  | test code |
| 40 | …et second = DatabricksWebStore(identif… | keep-internal |  | test code |
| 46 | … reopened = DatabricksWebStore(identif… | keep-internal |  | test code |
| 62 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 64 | …installer = DatabricksCookieInstaller(… | keep-internal |  | test code |
| 88 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 93 | try await DatabricksCookieInstaller().… | keep-internal |  | test code |
| 94 | throw DatabricksSessionError.credentia… | keep-internal |  | test code |
| 97 | …l(error as? DatabricksSessionError, .c… | keep-internal |  | test code |
| 103 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 106 | …//workspace.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 108 | …//workspace.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 110 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 112 | …//different.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 113 | …//workspace.databricks.com/login")!)) | keep-internal |  | test code |
| 115 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 120 | …keWebStore: DatabricksWebStoring { | keep-internal |  | test code |
| 163 | …on(context: DatabricksWebContext, cook… | keep-internal |  | test code |
| 164 | DatabricksWebSession( | keep-internal |  | test code |

### `web/ios/OmnigentTests/DatabricksWorkspaceBootstrapTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | @testable import Omnigent | keep-internal |  | test code |
| 9 | final class DatabricksWorkspaceBootstr… | keep-internal |  | test code |
| 11 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 12 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 36 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 40 | MemoryDatabricksCredentialStore(), log… | keep-internal |  | test code |
| 53 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 54 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 67 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 77 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 78 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 87 | …ue(error is DatabricksCredentialError)… | keep-internal |  | test code |
| 97 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 104 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 105 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 127 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 131 | MemoryDatabricksCredentialStore(), log… | keep-internal |  | test code |
| 136 | …l(error as? DatabricksSessionError, .w… | keep-internal |  | test code |
| 143 | …ed()).cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 144 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 153 | …et suite = "omnigent-test-\(UUID().uui… | keep-internal |  | test code |
| 156 | let parent = OmnigentWebView( | keep-internal |  | test code |
| 158 | databricksInternalFeaturesEnabled: fal… | keep-internal |  | test code |
| 161 | …ordinator = OmnigentWebView.Coordinato… | keep-internal |  | test code |
| 201 | …et suite = "omnigent-test-\(UUID().uui… | keep-internal |  | test code |
| 204 | let parent = OmnigentWebView( | keep-internal |  | test code |
| 206 | databricksInternalFeaturesEnabled: fal… | keep-internal |  | test code |
| 225 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 226 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 235 | …l(error as? DatabricksSessionError, .c… | keep-internal |  | test code |
| 240 | …CTAssertNil(OmnigentWebView.Coordinato… | keep-internal |  | test code |
| 242 | OmnigentWebView.Coordinator.workspaceE… | keep-internal |  | test code |
| 247 | DatabricksOAuthError.invalidClientID, … | keep-internal |  | test code |
| 248 | DatabricksSessionError.networkUnavaila… | keep-internal |  | test code |
| 251 | OmnigentWebView.Coordinator.workspaceE… | keep-internal |  | test code |
| 257 | … guidance = OmnigentWebView.connection… | keep-internal |  | test code |
| 258 | …nreachable, databricksInternalFeatures… | keep-internal |  | test code |
| 260 | OmnigentWebView.Coordinator.workspaceE… | keep-internal |  | test code |
| 261 | …nreachable, databricksInternalFeatures… | keep-internal |  | test code |
| 263 | OmnigentWebView.Coordinator.workspaceE… | keep-internal |  | test code |
| 264 | …nreachable, databricksInternalFeatures… | keep-internal |  | test code |
| 267 | OmnigentWebView.Coordinator.workspaceE… | keep-internal |  | test code |
| 268 | DatabricksSessionError.cancelled, data… | keep-internal |  | test code |
| 272 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 276 | MemoryDatabricksCredentialStore(), log… | keep-internal |  | test code |
| 282 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 289 | …space.cloud.databricks.com/omnigent") | keep-internal |  | test code |
| 290 | …//workspace.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 291 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 301 | …alias = try DatabricksCredentialScope( | keep-internal |  | test code |
| 314 | …eString + "/omnigent?o=123") | keep-internal |  | test code |
| 315 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 317 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 318 | …ls, client: DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 340 | …eString + "/omnigent?o=123") | keep-internal |  | test code |
| 341 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 343 | let manager = DatabricksTokenManager( | keep-internal |  | test code |
| 344 | …ls, client: DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 355 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 364 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 365 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 373 | .name: "omnigent-theme", .value: "dark… | keep-internal |  | test code |
| 379 | …(\.name), ["omnigent-theme"]) | keep-internal |  | test code |
| 385 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 386 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 391 | tokens: DatabricksTokenManager(store: … | keep-internal |  | test code |
| 419 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 420 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 430 | …l(error as? DatabricksSessionError, .w… | keep-internal |  | test code |
| 440 | …eString + "/omnigent?o=123") | keep-internal |  | test code |
| 441 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 447 | tokens: DatabricksTokenManager( | keep-internal |  | test code |
| 448 | …ls, client: DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 464 | …eString + "/omnigent?o=123") | keep-internal |  | test code |
| 465 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 470 | tokens: DatabricksTokenManager( | keep-internal |  | test code |
| 471 | …ls, client: DatabricksOAuthClient(sess… | keep-internal |  | test code |
| 481 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 495 | …ials: MemoryDatabricksCredentialStore,… | keep-internal |  | test code |
| 496 | …ns, tokens: DatabricksTokenManager? = … | keep-internal |  | test code |
| 497 | ) -> DatabricksWorkspaceBootstrap { | keep-internal |  | test code |
| 500 | …okens, for: DatabricksCredentialScope(… | keep-internal |  | test code |
| 504 | ?? DatabricksTokenManager(store: crede… | keep-internal |  | test code |
| 505 | …et suite = "omnigent-signout-tests-\(U… | keep-internal |  | test code |
| 508 | …installer = DatabricksCookieInstaller(… | keep-internal |  | test code |
| 509 | return DatabricksWorkspaceBootstrap( | keep-internal |  | test code |
| 511 | signOuts: DatabricksSignOutManager(tok… | keep-internal |  | test code |
| 516 | final class DatabricksLifecycleTests: … | keep-internal |  | test code |
| 518 | …ar policy = DatabricksRecoveryPolicy() | keep-internal |  | test code |
| 529 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 530 | …//workspace.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 536 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 541 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 568 | …l(error as? DatabricksSessionError, .s… | keep-internal |  | test code |
| 571 | …et tokens = DatabricksTokenManager(sto… | keep-internal |  | test code |
| 572 | … restored = DatabricksSignOutManager( | keep-internal |  | test code |
| 575 | …bootstrap = DatabricksWorkspaceBootstr… | keep-internal |  | test code |
| 582 | …l(error as? DatabricksSessionError, .r… | keep-internal |  | test code |
| 613 | …bootstrap = DatabricksWorkspaceBootstr… | keep-internal |  | test code |
| 626 | …l(error as? DatabricksSessionError, .c… | keep-internal |  | test code |
| 640 | …bootstrap = DatabricksWorkspaceBootstr… | keep-internal |  | test code |
| 654 | …l(error as? DatabricksSessionError, .c… | keep-internal |  | test code |
| 660 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 667 | …//workspace.databricks.com/auth/logout… | keep-internal |  | test code |
| 668 | …tps://other.databricks.com/auth/logout… | keep-internal |  | test code |
| 670 | …//workspace.databricks.com/login.html"… | keep-internal |  | test code |
| 672 | …//workspace.databricks.com/omnigent")!… | keep-internal |  | test code |
| 679 | …getPath = "/omnigent/c/abc?o=123#messa… | keep-internal |  | test code |
| 682 | …url.path, "/omnigent/c/abc") | keep-internal |  | test code |
| 689 | …al(message, DatabricksSessionError.rej… | keep-internal |  | test code |
| 741 | let context: DatabricksWebContext | keep-internal |  | test code |
| 742 | …ials: MemoryDatabricksCredentialStore | keep-internal |  | test code |
| 744 | …oordinator: OmnigentWebView.Coordinato… | keep-internal |  | test code |
| 751 | …ignedOut: ((DatabricksWebContext, Task… | keep-internal |  | test code |
| 754 | …ed()).cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 755 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 756 | let tokens = DatabricksTokenManager( | keep-internal |  | test code |
| 759 | …et suite = "omnigent-coordinator-tests… | keep-internal |  | test code |
| 762 | …installer = DatabricksCookieInstaller(… | keep-internal |  | test code |
| 763 | …bootstrap = DatabricksWorkspaceBootstr… | keep-internal |  | test code |
| 766 | signOuts: DatabricksSignOutManager(tok… | keep-internal |  | test code |
| 768 | let parent = OmnigentWebView( | keep-internal |  | test code |
| 770 | databricksInternalFeaturesEnabled: fal… | keep-internal |  | test code |
| 774 | …ordinator = OmnigentWebView.Coordinato… | keep-internal |  | test code |
| 792 | let context: DatabricksWebContext | keep-internal |  | test code |
| 793 | …ials: MemoryDatabricksCredentialStore | keep-internal |  | test code |
| 794 | let tokens: DatabricksTokenManager | keep-internal |  | test code |
| 795 | … installer: DatabricksCookieInstaller | keep-internal |  | test code |
| 798 | let signOuts: DatabricksSignOutManager | keep-internal |  | test code |
| 802 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 803 | …als = MemoryDatabricksCredentialStore(… | keep-internal |  | test code |
| 804 | let tokens = DatabricksTokenManager( | keep-internal |  | test code |
| 806 | …installer = DatabricksCookieInstaller(… | keep-internal |  | test code |
| 807 | …et suite = "omnigent-lifecycle-tests-\… | keep-internal |  | test code |
| 814 | signOuts: DatabricksSignOutManager(tok… | keep-internal |  | test code |
| 825 | …spaceLogin: DatabricksSigningIn { | keep-internal |  | test code |
| 829 | …ist: ((URL, DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 831 | …figuration: DatabricksOAuthConfigurati… | keep-internal |  | test code |
| 832 | …c throws -> DatabricksOAuthTokens { | keep-internal |  | test code |
| 844 | …ceSessions: DatabricksSessionCreating … | keep-internal |  | test code |
| 846 | var failure: DatabricksSessionError? | keep-internal |  | test code |
| 847 | … failures: [DatabricksSessionError] = … | keep-internal |  | test code |
| 853 | …te(context: DatabricksWebContext, toke… | keep-internal |  | test code |
| 854 | -> DatabricksWebSession | keep-internal |  | test code |

### `web/ios/OmnigentTests/DeepLinkTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 12 | let dl = DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 16 | let dl2 = DeepLink.parse(URL(string: "omnigent://127.0.0.1:8000/c/\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 22 | let dl = DeepLink.parse(URL(string: "omnigent://my-workspace.cloud.databricks.com/c/\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 23 | …space.cloud.databricks.com") | keep-internal |  | test code |
| 28 | let dl = DeepLink.parse(URL(string: "omnigent://example.com:8443/c/\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 34 | let dl = DeepLink.parse(URL(string: "omnigent://[::1]:8000/c/\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 42 | let dl = DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)/")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 49 | let dl = DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(dashed)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 57 | let dl = DeepLink.parse(URL(string: "omnigent://localhost:8000/c/conv_\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 62 | let dl = DeepLink.parse(URL(string: "omnigent://localhost:8000/c/ag_\(hex)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 69 | let dl = DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(upper)")!) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 73 | func testRejectsNonOmnigentScheme() { | keep-internal |  | test code |
| 79 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 80 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent:///c/\(hex)")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 84 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/inbox")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 85 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/settings/appearance")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 86 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 87 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)/extra")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 88 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 98 | let url = URL(string: "omnigent://localhost:8000/c/\(hex)%3Fview=terminal")! | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 105 | let url = URL(string: "omnigent://localhost:8000/c/\(hex)%23frag")! | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 113 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)%2Fextra")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 119 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)%2E.")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 120 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/%2e%2e")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 121 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/..")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 127 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)%00x")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 128 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)%0Ax")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 129 | XCTAssertNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)%7Fx")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 135 | let url = URL(string: "omnigent://localhost:8000/c/\(hex)%zz")! | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 147 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/conv_abc")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 148 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/x")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 149 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/not-a-uuid")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 150 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex.dropLast())")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 152 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/\(hex)g")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 154 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/host_\(hex)")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 156 | XCTAssertNotNil(DeepLink.parse(URL(string: "omnigent://localhost:8000/c/conv_\(hex)")!)) | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 163 | …//workspace.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 164 | …//workspace.databricks.com/omnigent/c/… | keep-internal |  | test code |
| 167 | …//workspace.databricks.com/omnigent/?o… | keep-internal |  | test code |
| 168 | …//workspace.databricks.com/omnigent/c/… | keep-internal |  | test code |

### `web/ios/OmnigentTests/KeyboardViewportTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | @testable import Omnigent | keep-internal |  | test code |
| 72 | let view = OmnigentWebView( | keep-internal |  | test code |
| 74 | databricksInternalFeaturesEnabled: fal… | keep-internal |  | test code |
| 79 | …tor, name: "omnigentNative") | keep-internal |  | test code |
| 82 | source: OmnigentWebView.nativeBridgeSc… | keep-internal |  | test code |
| 95 | …r(forName: "omnigentNative") | keep-internal |  | test code |
| 126 | let view = OmnigentWebView( | keep-internal |  | test code |
| 128 | … defaults), databricksInternalFeatures… | keep-internal |  | test code |
| 181 | …ze = window.omnigentNative.getKeyboard… | keep-internal |  | test code |
| 184 | window.omnigentNative.onKeyboardViewpo… | keep-internal |  | test code |

### `web/ios/OmnigentTests/ManagedConfigurationTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 33 | …verUrls": ["omnigent.corp.example.com"… | keep-internal |  | test code |
| 35 | …, ["https://omnigent.corp.example.com"… | keep-internal |  | test code |
| 39 | // The Databricks mount must survive d… | keep-internal |  | test code |
| 43 | …://ws.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 48 | …://ws.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 64 | …ries = (1...OmnigentManagedConfigurati… | keep-internal |  | test code |
| 71 | // MARK: Databricks-internal features | keep-internal |  | test code |
| 74 | …decode([:]).databricksInternalFeatures… | keep-internal |  | test code |
| 76 | …ple.com"]]).databricksInternalFeatures… | keep-internal |  | test code |
| 81 | …ry decode(["databricksInternalFeatures… | keep-internal |  | test code |
| 82 | …qual(config.databricksInternalFeatures… | keep-internal |  | test code |
| 91 | "databricksInternalFeaturesEnabled": v… | keep-internal |  | test code |
| 93 | …alse(config.databricksInternalFeatures… | keep-internal |  | test code |
| 100 | let key = OmnigentManagedConfiguration… | keep-internal |  | test code |
| 102 | …aults.set(["databricksInternalFeatures… | keep-internal |  | test code |
| 103 | …et config = OmnigentManagedConfigurati… | keep-internal |  | test code |
| 104 | …qual(config.databricksInternalFeatures… | keep-internal |  | test code |
| 108 | OmnigentManagedConfiguration.read(lega… | keep-internal |  | test code |
| 112 | …ry decode(["databricksInternalFeatures… | keep-internal |  | test code |
| 115 | …ry decode(["databricksInternalFeatures… | keep-internal |  | test code |
| 116 | …ry decode(["databricksInternalFeatures… | keep-internal |  | test code |
| 119 | OmnigentManagedConfiguration.resolve(d… | keep-internal |  | test code |
| 120 | .databricksInternalFeaturesEnabled) | keep-internal |  | test code |
| 125 | …ry decode(["databricksInternalFeatures… | keep-internal |  | test code |
| 127 | … resolved = OmnigentManagedConfigurati… | keep-internal |  | test code |
| 128 | …ue(resolved.databricksInternalFeatures… | keep-internal |  | test code |
| 133 | …ry decode(["databricksInternalFeatures… | keep-internal |  | test code |
| 135 | OmnigentManagedConfiguration.resolve(d… | keep-internal |  | test code |
| 136 | .databricksInternalFeaturesEnabled) | keep-internal |  | test code |
| 137 | …AssertEqual(OmnigentManagedConfigurati… | keep-internal |  | test code |
| 147 | …/"]], with: OmnigentManagedConfigurati… | keep-internal |  | test code |
| 151 | … "]], with: OmnigentManagedConfigurati… | keep-internal |  | test code |
| 156 | …": ["http://omnigent.corp.example.com"… | keep-internal |  | test code |
| 157 | with: OmnigentManagedConfiguration.not… | keep-internal |  | test code |
| 162 | …s": ["ftp://omnigent.corp.example.com"… | keep-internal |  | test code |
| 163 | with: OmnigentManagedConfiguration.not… | keep-internal |  | test code |
| 167 | …ries = (0...OmnigentManagedConfigurati… | keep-internal |  | test code |
| 172 | …ies], with: OmnigentManagedConfigurati… | keep-internal |  | test code |
| 177 | …": "https://omnigent.corp.example.com"… | keep-internal |  | test code |
| 178 | with: OmnigentManagedConfiguration.wro… | keep-internal |  | test code |
| 186 | with: OmnigentManagedConfiguration.not… | keep-internal |  | test code |
| 194 | OmnigentManagedConfiguration.invalidUR… | keep-internal |  | test code |
| 195 | OmnigentManagedConfiguration.notHTTPSC… | keep-internal |  | test code |
| 196 | OmnigentManagedConfiguration.tooManyEn… | keep-internal |  | test code |
| 197 | OmnigentManagedConfiguration.wrongType… | keep-internal |  | test code |
| 215 | forKey: OmnigentManagedConfiguration.l… | keep-internal |  | test code |
| 218 | OmnigentManagedConfiguration.read(lega… | keep-internal |  | test code |
| 223 | …AssertEqual(OmnigentManagedConfigurati… | keep-internal |  | test code |
| 230 | forKey: OmnigentManagedConfiguration.l… | keep-internal |  | test code |
| 232 | …AssertEqual(OmnigentManagedConfigurati… | keep-internal |  | test code |
| 241 | forKey: OmnigentManagedConfiguration.l… | keep-internal |  | test code |
| 243 | …AssertEqual(OmnigentManagedConfigurati… | keep-internal |  | test code |
| 274 | …) throws -> OmnigentManagedConfigurati… | keep-internal |  | test code |
| 276 | …er().decode(OmnigentManagedConfigurati… | keep-internal |  | test code |
| 289 | … failure as OmnigentManagedConfigurati… | keep-internal |  | test code |

### `web/ios/OmnigentTests/MockHTTPServer.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …ion tests (ˋOmnigentTestsˋ) and the UI… | keep-internal |  | test code |
| 8 | /// (ˋOmnigentUITestsˋ) — compiled int… | keep-internal |  | test code |
| 25 | …eue(label: "omnigent.mock-http-server"… | keep-internal |  | test code |

### `web/ios/OmnigentTests/OidcCredentialStoreTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 7 | … = "https://omnigent.example.com" | keep-internal |  | test code |
| 8 | … = "https://omnigent.example.com:8443" | keep-internal |  | test code |
| 11 | …rvice = "ai.omnigent.ios.tests.oidc.\(… | keep-internal |  | test code |
| 54 | …rvice = "ai.omnigent.ios.tests.oidc.\(… | keep-internal |  | test code |

### `web/ios/OmnigentTests/OidcCredentialsTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | @testable import Omnigent | keep-internal |  | test code |
| 16 | "/omnigent/auth/native-token", | keep-internal |  | test code |
| 23 | …gin.path, "/omnigent/auth/login") | keep-internal |  | test code |
| 29 | …_uri"], "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 35 | …string: "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 36 | …RL(string: "omnigent:/oauth/callback")… | keep-internal |  | test code |
| 45 | …nge.path, "/omnigent/auth/native-token… | keep-internal |  | test code |
| 49 | …_uri"], "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 58 | …r.respond("/omnigent/auth/native-token… | keep-internal |  | test code |
| 125 | let host = "omnigent.example.com" | keep-internal |  | test code |
| 128 | …string: "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 193 | "/omnigent/auth/native-token", json: [… | keep-internal |  | test code |
| 205 | "/omnigent/auth/native-token", json: [… | keep-internal |  | test code |
| 220 | …r.respond("/omnigent/auth/native-token… | keep-internal |  | test code |
| 233 | "/omnigent/auth/native-token", json: [… | keep-internal |  | test code |
| 247 | …r.respond("/omnigent/oauth/token", jso… | keep-internal |  | test code |
| 262 | …r.respond("/omnigent/auth/native-token… | keep-internal |  | test code |
| 280 | "/omnigent/auth/native-token", status:… | keep-internal |  | test code |
| 297 | "/omnigent/auth/native-token", json: [… | keep-internal |  | test code |
| 301 | …orRequest("/omnigent/auth/native-token… | keep-internal |  | test code |
| 317 | "/omnigent/auth/native-token", json: [… | keep-internal |  | test code |
| 318 | …r.respond("/omnigent/oauth/revoke", js… | keep-internal |  | test code |
| 328 | …orRequest("/omnigent/oauth/revoke") | keep-internal |  | test code |
| 336 | "/omnigent/auth/native-token", status:… | keep-internal |  | test code |
| 338 | …r.respond("/omnigent/leak", json: ["to… | keep-internal |  | test code |
| 348 | …\.path), ["/omnigent/auth/native-token… | keep-internal |  | test code |
| 359 | "/omnigent/oauth/token", status: 302, … | keep-internal |  | test code |
| 360 | …r.respond("/omnigent/leak", json: ["ac… | keep-internal |  | test code |
| 367 | …\.path), ["/omnigent/oauth/token"]) | keep-internal |  | test code |
| 376 | "/omnigent/oauth/token", | keep-internal |  | test code |
| 383 | …est.path, "/omnigent/oauth/token") | keep-internal |  | test code |
| 399 | …r.respond("/omnigent/oauth/token", sta… | keep-internal |  | test code |
| 424 | …r.respond("/omnigent/oauth/token", sta… | keep-internal |  | test code |
| 434 | …localhost:1/omnigent/")! | keep-internal |  | test code |
| 435 | …unreachable.omnigentOrigin) | keep-internal |  | test code |
| 462 | …r.respond("/omnigent/oauth/token", jso… | keep-internal |  | test code |
| 485 | …r.respond("/omnigent/oauth/revoke", js… | keep-internal |  | test code |
| 492 | …est.path, "/omnigent/oauth/revoke") | keep-internal |  | test code |
| 499 | …r.respond("/omnigent/oauth/token", jso… | keep-internal |  | test code |
| 500 | …r.respond("/omnigent/oauth/revoke", js… | keep-internal |  | test code |
| 505 | …orRequest("/omnigent/oauth/token") | keep-internal |  | test code |
| 522 | …0.path == "/omnigent/oauth/token" }.co… | keep-internal |  | test code |
| 528 | …r.respond("/omnigent/oauth/revoke", st… | keep-internal |  | test code |
| 535 | …unreachable.omnigentOrigin!) | keep-internal |  | test code |
| 537 | …unreachable.omnigentOrigin!)) | keep-internal |  | test code |
| 550 | "/omnigent/v1/me", status: status, hea… | keep-internal |  | test code |
| 558 | …est.path, "/omnigent/v1/me") | keep-internal |  | test code |
| 563 | …r.respond("/omnigent/v1/me", status: 5… | keep-internal |  | test code |
| 587 | …g: "https://Omnigent.Example.com/omnig… | keep-internal |  | test code |
| 591 | …re.domain, "omnigent.example.com") | keep-internal |  | test code |
| 632 | …ost:\(port)/omnigent/")! } | keep-internal |  | test code |
| 633 | …{ serverURL.omnigentOrigin! } | keep-internal |  | test code |
| 634 | …{ serverURL.omnigentHostLabel } | keep-internal |  | test code |
| 791 | components.scheme = "ai.omnigent.ios" | keep-internal |  | test code |

### `web/ios/OmnigentTests/OidcLoginManagerTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 22 | ….headers["x-omnigent-code-verifier"], … | keep-internal |  | test code |

### `web/ios/OmnigentTests/OidcWebSessionTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 7 | …g: "https://omnigent.example.com")! | keep-internal |  | test code |
| 8 | …te("https://omnigent.example.com/auth/… | keep-internal |  | test code |
| 9 | …te("https://omnigent.example.com/auth/… | keep-internal |  | test code |
| 10 | …te("https://omnigent.example.com/auth/… | keep-internal |  | test code |
| 11 | …te("https://OMNIGENT.example.com/auth/… | keep-internal |  | test code |
| 15 | …example.com/omnigent/")! | keep-internal |  | test code |
| 16 | …example.com/omnigent/auth/login", serv… | keep-internal |  | test code |
| 17 | …example.com/omnigent/auth/logout", ser… | keep-internal |  | test code |
| 23 | …g: "https://omnigent.example.com")! | keep-internal |  | test code |
| 25 | "https://omnigent.example.com/", | keep-internal |  | test code |
| 26 | "https://omnigent.example.com/c/conv_1… | keep-internal |  | test code |
| 27 | "https://omnigent.example.com/auth/log… | keep-internal |  | test code |
| 28 | "https://omnigent.example.com/auth/cli… | keep-internal |  | test code |
| 29 | "https://omnigent.example.com/v1/auth/… | keep-internal |  | test code |
| 30 | "http://omnigent.example.com/auth/logi… | keep-internal |  | test code |
| 31 | "https://omnigent.example.com:8443/aut… | keep-internal |  | test code |
| 39 | …example.com/omnigent")! | keep-internal |  | test code |
| 40 | …example.com/omnigent")!, of: server)) | keep-internal |  | test code |
| 42 | …example.com/omnigent/c/conv_1?x=1")!, … | keep-internal |  | test code |
| 45 | …example.com/omnigenty/c/x")!, of: serv… | keep-internal |  | test code |
| 47 | …example.com/omnigent/auth/login")!, of… | keep-internal |  | test code |
| 49 | …example.com/omnigent")!, of: server)) | keep-internal |  | test code |
| 58 | …g: "https://omnigent.example.com")! | keep-internal |  | test code |
| 63 | …uris": ["ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 71 | …callback", "omnigent:/oauth/callback"]… | keep-internal |  | test code |
| 73 | …uris": ["ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 84 | …uris": ["ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 126 | … = "https://omnigent.example.com" | keep-internal |  | test code |
| 138 | …n: "https://omnigent.example.com") | keep-internal |  | test code |
| 144 | …g: "https://omnigent.example.com/")! | keep-internal |  | test code |
| 148 | …ve", host: "omnigent.example.com", exp… | keep-internal |  | test code |
| 149 | …ld", host: "omnigent.example.com", exp… | keep-internal |  | test code |
| 151 | …"y", host: "omnigent.example.com", exp… | keep-internal |  | test code |
| 180 | …g: "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 182 | …pp", host: "omnigent.example.com", exp… | keep-internal |  | test code |
| 184 | …ix", host: "omnigent.example.com", exp… | keep-internal |  | test code |
| 186 | …nt", host: "omnigent.example.com", exp… | keep-internal |  | test code |
| 196 | …okiePath: "/omnigent/", requestPath: "… | keep-internal |  | test code |
| 198 | …okiePath: "/omnigent", requestPath: "/… | keep-internal |  | test code |
| 202 | let host = "omnigent.example.com" | keep-internal |  | test code |
| 221 | let host = "omnigent.example.com" | keep-internal |  | test code |
| 234 | … sign-in to omnigent.example.com has e… | keep-internal |  | test code |
| 264 | let host = "omnigent.example.com" | keep-internal |  | test code |
| 268 | … sign-in to omnigent.example.com has e… | keep-internal |  | test code |
| 272 | "omnigent.example.com ended your sessi… | keep-internal |  | test code |
| 275 | "Sign in to omnigent.example.com to co… | keep-internal |  | test code |
| 280 | …gned out of omnigent.example.com.") | keep-internal |  | test code |
| 284 | let host = "omnigent.example.com" | keep-internal |  | test code |
| 317 | …n: "https://omnigent.example.com", man… | keep-internal |  | test code |
| 322 | …g, "https://omnigent.example.com") | keep-internal |  | test code |
| 333 | …et script = OmnigentWebView.nativeBrid… | keep-internal |  | test code |

### `web/ios/OmnigentTests/ServerManifestTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 11 | ….well-known/omnigent.json") | keep-internal |  | test code |
| 18 | …uris": ["ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 24 | …erver.port)/omnigent/?o=1#chat")!) | keep-internal |  | test code |
| 32 | …tURIs: ["ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 72 | …g: "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 111 | ….well-known/omnigent.json" { | keep-internal |  | test code |

### `web/ios/OmnigentTests/ServerSwitcherVisibilityTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 10 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 23 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 41 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 69 | …g: "https://omnigent.example.com")! | keep-internal |  | test code |
| 71 | …g: "https://omnigent.example.com/c/old… | keep-internal |  | test code |
| 72 | …g: "https://omnigent.example.com/c/old… | keep-internal |  | test code |
| 73 | …g: "https://omnigent.example.com/c/new… | keep-internal |  | test code |
| 80 | …space.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 83 | …g: "https://omnigent.example.com")!), … | keep-internal |  | test code |
| 86 | …space.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |

### `web/ios/OmnigentTests/ServerURLTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 21 | …-ac9f.cloud.databricks.com", allowsIns… | keep-internal |  | test code |
| 22 | …-ac9f.cloud.databricks.com") | keep-internal |  | test code |
| 57 | "https://databricks.com", | keep-internal |  | test code |
| 58 | …c-123.cloud.databricks.com", | keep-internal |  | test code |
| 59 | "https://azuredatabricks.net", | keep-internal |  | test code |
| 60 | "https://adb-123.azuredatabricks.net", | keep-internal |  | test code |
| 61 | …C-123.CLOUD.DATABRICKS.COM", | keep-internal |  | test code |
| 62 | "https://ADB-123.AZUREDATABRICKS.NET", | keep-internal |  | test code |
| 64 | …: origin), .databricksWorkspace, origi… | keep-internal |  | test code |
| 70 | "https://databricksapps.com", | keep-internal |  | test code |
| 71 | …/my-app.aws.databricksapps.com", | keep-internal |  | test code |
| 72 | …Y-APP.AZURE.DATABRICKSAPPS.COM", | keep-internal |  | test code |
| 74 | …: origin), .databricksApp, origin) | keep-internal |  | test code |
| 82 | "https://notdatabricks.com", | keep-internal |  | test code |
| 83 | "https://notazuredatabricks.net", | keep-internal |  | test code |
| 84 | "https://notdatabricksapps.com", | keep-internal |  | test code |
| 85 | "https://databricks.com.example.org", | keep-internal |  | test code |
| 86 | …ttps://azuredatabricks.net.example.org… | keep-internal |  | test code |
| 87 | "https://databricksapps.com.example.or… | keep-internal |  | test code |
| 88 | "https://databricks.com@example.org", | keep-internal |  | test code |
| 89 | "https://example.org/databricks.com", | keep-internal |  | test code |
| 102 | "http://dbc-123.cloud.databricks.com", | keep-internal |  | test code |
| 103 | …c-123.cloud.databricks.com:8443/omnige… | keep-internal |  | test code |
| 105 | …: origin), .databricksWorkspace, origi… | keep-internal |  | test code |
| 108 | …ps://my-app.databricksapps.com:8443/c/… | keep-internal |  | test code |
| 113 | "databricks.com", "DBC-123.CLOUD.DATAB… | keep-internal |  | test code |
| 114 | "databricksapps.com", "MY-APP.AWS.DATA… | keep-internal |  | test code |
| 115 | "notdatabricks.com", "azuredatabricks.… | keep-internal |  | test code |
| 123 | …hentication.databricksWorkspace.usesIn… | keep-internal |  | test code |
| 124 | …hentication.databricksApp.usesInWebVie… | keep-internal |  | test code |
| 153 | final class OmnigentEndpointTests: XCT… | keep-internal |  | test code |
| 156 | ("https://h/omnigent/", "/auth/login",… | keep-internal |  | test code |
| 157 | ("https://h/omnigent", "/auth/login", … | keep-internal |  | test code |
| 158 | ("https://h/omnigent///", "/v1/me", "h… | keep-internal |  | test code |
| 167 | …g: server)!.omnigentEndpoint(route)?.a… | keep-internal |  | test code |
| 172 | … "https://h/omnigent")!.omnigentEndpoi… | keep-internal |  | test code |

### `web/ios/OmnigentTests/SettingsStoreTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 45 | … = "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 46 | …g: "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 49 | …L, "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 51 | …g: "https://OMNIGENT.example.com/omnig… | keep-internal |  | test code |
| 53 | …, ["https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 61 | …/[::1]:6767/omnigent/")!) | keep-internal |  | test code |
| 67 | … = "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 68 | …L, "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 71 | …L, "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 73 | …g: "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 74 | …L, "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 80 | …L, "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 83 | … = "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 86 | …L, "https://omnigent.example.com/omnig… | keep-internal |  | test code |
| 91 | … = "https://omnigent.example.com" | keep-internal |  | test code |
| 92 | …g: "https://omnigent.example.com")!) | keep-internal |  | test code |
| 95 | … = "https://omnigent.example.com" | keep-internal |  | test code |
| 96 | …L, "https://omnigent.example.com") | keep-internal |  | test code |
| 100 | … mount (/ml/omnigents); a deep | keep-internal |  | test code |
| 105 | …space.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 107 | …space.cloud.databricks.com") | keep-internal |  | test code |
| 109 | …space.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |

### `web/ios/OmnigentTests/ThemeBackgroundTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | @testable import Omnigent | keep-internal |  | test code |

### `web/ios/OmnigentTests/WebAuthenticationBrowserTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | @testable import Omnigent | keep-internal |  | test code |
| 9 | …g: "https://omnigent.example.com/auth/… | keep-internal |  | test code |
| 10 | …string: "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 24 | …mScheme("ai.omnigent.ios")) | keep-internal |  | test code |
| 32 | …string: "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 43 | …mScheme("ai.omnigent.ios"), anchor: an… | keep-internal |  | test code |
| 55 | …mScheme("ai.omnigent.ios"), anchor: an… | keep-internal |  | test code |
| 92 | …string: "ai.omnigent.ios:/oauth/callba… | keep-internal |  | test code |
| 111 | …mScheme("ai.omnigent.ios"), anchor: an… | keep-internal |  | test code |
| 119 | …mScheme("ai.omnigent.ios") | keep-internal |  | test code |

### `web/ios/OmnigentTests/WorkspaceChromeScriptTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 6 | …must key on Omnigent's own embed root,… | keep-internal |  | test code |
| 12 | .omnigent-app { | keep-internal |  | test code |
| 31 | …"style[data-omnigent-workspace-chrome]… | keep-internal |  | test code |

### `web/ios/OmnigentTests/WorkspaceURLExpanderRedirectTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | @testable import Omnigent | keep-internal |  | test code |
| 23 | …th ˋserver: databricksˋ — the payload | keep-internal |  | test code |
| 27 | …["server": "databricks", "content-leng… | keep-internal |  | test code |
| 72 | …["server": "databricks", "content-leng… | keep-internal |  | test code |

### `web/ios/OmnigentTests/WorkspaceURLExpanderTests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | @testable import Omnigent | keep-internal |  | test code |
| 12 | …tExpandsBareDatabricksWorkspaceRoot() … | keep-internal |  | test code |
| 18 | headerFields: ["server": "databricks"] | keep-internal |  | test code |
| 28 | …example.com/omnigent") | keep-internal |  | test code |
| 49 | …example.com/omnigent")! | keep-internal |  | test code |
| 56 | …c testLeavesDatabricksAppsHostUnchange… | keep-internal |  | test code |
| 58 | XCTFail("Databricks Apps must not be p… | keep-internal |  | test code |
| 62 | …app-123.aws.databricksapps.com", | keep-internal |  | test code |
| 63 | "https://databricksapps.com", | keep-internal |  | test code |
| 64 | …Y-APP.AZURE.DATABRICKSAPPS.COM", | keep-internal |  | test code |
| 77 | headerFields: ["server": "databricks"] | keep-internal |  | test code |
| 82 | "https://databricksapps.com.example.or… | keep-internal |  | test code |
| 83 | "https://notdatabricksapps.com", | keep-internal |  | test code |
| 87 | …ng, raw + "/omnigent") | keep-internal |  | test code |
| 101 | headerFields: ["server": "databricks"] | keep-internal |  | test code |
| 159 | …-1234.cloud.databricks.com"), | keep-internal |  | test code |
| 160 | …-1234.cloud.databricks.com/omnigent") | keep-internal |  | test code |
| 162 | …-1234.cloud.databricks.com/"), | keep-internal |  | test code |
| 163 | …-1234.cloud.databricks.com/omnigent") | keep-internal |  | test code |
| 165 | …adb-99.azuredatabricks.net/"), "https:… | keep-internal |  | test code |
| 166 | …nt("https://databricks.com/"), "https:… | keep-internal |  | test code |
| 167 | …ttps://azuredatabricks.net/"), "https:… | keep-internal |  | test code |
| 173 | …-1234.cloud.databricks.com/?o=98765432… | keep-internal |  | test code |
| 174 | …-1234.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 176 | …-1234.cloud.databricks.com/?o=1#frag")… | keep-internal |  | test code |
| 177 | …-1234.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 182 | …-1234.cloud.databricks.com:8443/"), | keep-internal |  | test code |
| 183 | …-1234.cloud.databricks.com:8443/omnige… | keep-internal |  | test code |
| 185 | …-1234.Cloud.DataBricks.Com/"), | keep-internal |  | test code |
| 186 | …-1234.Cloud.DataBricks.Com/omnigent") | keep-internal |  | test code |
| 191 | …-1234.cloud.databricks.com/omnigent")) | keep-internal |  | test code |
| 192 | …-1234.cloud.databricks.com/c/abc")) | keep-internal |  | test code |
| 193 | …-1234.cloud.databricks.com/ml/omnigent… | keep-internal |  | test code |
| 197 | …c testLeavesDatabricksAppsAndOtherHost… | keep-internal |  | test code |
| 198 | …ps://my-app.databricksapps.com/")) | keep-internal |  | test code |
| 199 | …nt("https://databricksapps.com/")) | keep-internal |  | test code |
| 200 | …/MY-APP.AWS.DATABRICKSAPPS.COM/")) | keep-internal |  | test code |
| 204 | …nt("https://databricks.com.evil.exampl… | keep-internal |  | test code |
| 205 | …ttps://azuredatabricks.net.example.org… | keep-internal |  | test code |
| 206 | …"https://notdatabricks.com/")) | keep-internal |  | test code |
| 207 | …s://notazuredatabricks.net/")) | keep-internal |  | test code |
| 211 | …tNil(mount("omnigent://dbc-1234.cloud.… | keep-internal |  | test code |

### `web/ios/OmnigentUITests/ManagedServersUITests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …BUG-only ˋ--omnigent-managed-serversˋ … | keep-internal |  | test code |
| 15 | …t marker = "OMNIGENT_MANAGED_SERVER_OK… | keep-internal |  | test code |
| 24 | …tifier: "ai.omnigent.ios") | keep-internal |  | test code |
| 26 | "--omnigent-managed-servers", presetUR… | keep-internal |  | test code |
| 28 | "--omnigent-reset-state", | keep-internal |  | test code |

### `web/ios/OmnigentUITests/OmnigentUITests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | final class OmnigentUITests: XCTestCas… | keep-internal |  | test code |
| 10 | …tifier: "ai.omnigent.ios") | keep-internal |  | test code |
| 14 | "Pass --omnigent-server-url or OMNIGEN… | keep-internal |  | test code |
| 17 | "--omnigent-server-url", | keep-internal |  | test code |
| 20 | NSLog("Omnigent screenshot server URL:… | keep-internal |  | test code |
| 21 | …nvironment["OMNIGENT_SCREENSHOT_APP_UR… | keep-internal |  | test code |
| 26 | "Expected Omnigent to show the server … | keep-internal |  | test code |
| 33 | "Expected Omnigent to connect to \(ser… | keep-internal |  | test code |
| 42 | …BUG-only ˋ--omnigent-open-urlˋ launch … | keep-internal |  | test code |
| 49 | /// ˋ--omnigent-reset-stateˋ (also DEB… | keep-internal |  | test code |
| 54 | …tifier: "ai.omnigent.ios") | keep-internal |  | test code |
| 55 | …ents += ["--omnigent-open-url", link, … | keep-internal |  | test code |
| 60 | …// A valid ˋomnigent://ˋ deep link to … | keep-internal |  | test code |
| 67 | openURL: "omnigent://localhost:8000/c/e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9") | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 69 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 88 | "omnigent://localhost:8000/c/e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9%3Fview=terminal") | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 94 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 104 | openURL: "omnigent://localhost:8000/c/e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9%23evil") | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 107 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 123 | let app = launchApp(openURL: "omnigent://localhost:8000/c/conv_abc") | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 125 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 136 | let app = launchApp(openURL: "omnigent://localhost:8000/c/%2e%2e") | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 139 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 149 | openURL: "omnigent://localhost:8000/c/e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9%00x") | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 152 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 204 | …nvironment["OMNIGENT_SCREENSHOT_APP_UR… | keep-internal |  | test code |
| 205 | …chArguments.omnigentServerURL | keep-internal |  | test code |
| 206 | …Arguments().omnigentServerURL | keep-internal |  | test code |
| 216 | return contents.omnigentShellTokens | keep-internal |  | test code |
| 236 | …private var omnigentServerURL: String?… | keep-internal |  | test code |
| 237 | omnigentArgumentValue(after: "--omnige… | keep-internal |  | test code |
| 239 | …asPrefix("--omnigent-server-url=") els… | keep-internal |  | test code |
| 240 | …ropFirst("--omnigent-server-url=".coun… | keep-internal |  | test code |
| 251 | …rivate func omnigentArgumentValue(afte… | keep-internal |  | test code |
| 267 | …private var omnigentShellTokens: [Stri… | keep-internal |  | test code |

### `web/ios/OmnigentUITests/RedirectConsentUITests.swift`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …BUG-only ˋ--omnigent-open-urlˋ | keep-internal |  | test code |
| 15 | …to-end: an ˋomnigent://ˋ deep link to … | keep-internal |  | test code |
| 22 | …t marker = "OMNIGENT_DEEPLINK_CONSENT_… | keep-internal |  | test code |
| 30 | let deepLink = "omnigent://localhost:\(server.port)/c/conv_smoke" | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 32 | …tifier: "ai.omnigent.ios") | keep-internal |  | test code |
| 34 | "--omnigent-open-url", deepLink, | keep-internal |  | test code |
| 35 | "--omnigent-reset-state", | keep-internal |  | test code |
| 39 | let alert = app.alerts["Open this Omnigent link?"] | change | S38 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/ios/README.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | # Omnigent iOS | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 3 | Thin SwiftUI/WKWebView shell for Omnigent on iPhone and iPad. Like the Electron | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 9 | Open ˋOmnigent.xcodeprojˋ in Xcode 26 or newer and run the ˋOmnigentˋ scheme on | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 25 | ## Databricks OAuth | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 29 | setup are documented in [Databricks OAuth](docs/databricks-oauth.md). Databricks Apps | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 34 | Omnigent servers that sign in with OIDC (ˋOMNIGENT_AUTH_PROVIDER=oidcˋ) open | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 39 | Before loading a server that isn't a Databricks host, the app reads its | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 40 | unauthenticated ˋ/.well-known/omnigent.jsonˋ manifest. Native sign-in applies | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 42 | ˋai.omnigent.ios:/oauth/callbackˋ, and ˋauth.session_cookieˋ is set: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 51 | \| Databricks workspaces and Apps                             \| Unchanged: detected by URL, manifest … | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 57 | The server redirects the sheet to ˋai.omnigent.ios:/oauth/callbackˋ with a | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 87 | ˋai.omnigent.ios.oidcˋ, this device only, never synced). Debug builds add a | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 115 | server (ticket sign-in), and a Databricks workspace behave as before. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 140 | --omnigent-managed-servers https://one.example.com,https://two.example.com | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 152 | xcodebuild build -project Omnigent.xcodeproj -scheme Omnigent -destination "$DEVICE" -quiet | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 153 | APP="$(xcodebuild -project Omnigent.xcodeproj -scheme Omnigent -destination "$DEVICE" \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 154 | -showBuildSettings \| awk -F' = ' '/ BUILT_PRODUCTS_DIR/{print $2; exit}')/Omnigent.app" | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 158 | xcrun simctl launch booted ai.omnigent.ios --omnigent-reset-state \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 159 | --omnigent-managed-servers 'https://omnigent.corp.example.com,https://my-workspace.cloud.databricks.… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 167 | xcrun simctl spawn booted defaults write ai.omnigent.ios com.apple.configuration.managed \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 168 | '{ serverUrls = ("https://omnigent.corp.example.com", "https://my-workspace.cloud.databricks.com/ml/… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 169 | xcrun simctl terminate booted ai.omnigent.ios | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 170 | xcrun simctl launch booted ai.omnigent.ios | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 175 | xcrun simctl spawn booted defaults delete ai.omnigent.ios com.apple.configuration.managed | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 186 | An ˋomnigent://<hostname>/c/<session_id>ˋ URL opens that session on that server | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 192 | omnigent://localhost:8000/c/conv_abc → http://localhost:8000/c/conv_abc | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 193 | omnigent://my-workspace.cloud.databricks.com/c/x → https://…/ml/omnigents/c/x | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 200 | URL never disagree. The Databricks workspace mount (ˋ/ml/omnigentsˋ) is **not** | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 220 | test from the simulator with ˋxcrun simctl openurl booted 'omnigent://...'ˋ. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/ios/RELEASE.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | # Releasing Omnigent iOS | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 18 | for bundle ID ˋai.omnigent.iosˋ (My Apps → +), if it doesn't exist yet. | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 53 | configurations of the **Omnigent** target in Xcode (or via ˋfastlane | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 68 | ˋOMNIGENT_PROD_BUILD_NUMBER=4ˋ to pin a specific processed build. | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 72 | - ˋbundle exec fastlane testsˋ — run the ˋOmnigentTestsˋ unit suite. | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 74 | Store screenshots into ˋfastlane/screenshotsˋ using the ˋOmnigentUITestsˋ | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |
| 76 | Omnigent server via ˋuvˋ on a non-6767 port, and connects each simulator to | keep-deferred |  | release runbook for Omnigent's own pipeline; Coral's runbook comes with BRD-03 step 6 / OPS-05 |

### `web/ios/docs/databricks-oauth.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | # Databricks OAuth on iOS | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 3 | Workspace-hosted Omnigent uses native OAuth, Keychain credentials, and session-cookie | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 5 | persistent WebKit data store. Databricks Apps keep inline platform sign-in. Other | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 7 | sign-in sheet and "Sign in again?" prompt but never reads Databricks credentials. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 16 | Set these user-defined build settings on the **Omnigent** target in Xcode, or | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 22 | \| ˋDATABRICKS_OAUTH_CLIENT_IDˋ    \| ˋomnigentˋ                                     \| Public OAuth cl… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 23 | \| ˋDATABRICKS_OAUTH_REDIRECT_URLˋ \| ˋhttps://login.databricks.com/mobile-redirectˋ \| The exact HTTPS… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 26 | the app or borrow the Databricks CLI client ID. The redirect must have a path, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 32 | xcodebuild build -project Omnigent.xcodeproj -scheme Omnigent \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 34 | -derivedDataPath /tmp/omnigent-oauth-config-check \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 35 | DATABRICKS_OAUTH_CLIENT_ID=your-public-client-id \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 36 | DATABRICKS_OAUTH_REDIRECT_URL=https://login.databricks.com/mobile-redirect | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 38 | plutil -extract DatabricksOAuthClientID raw \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 39 | /tmp/omnigent-oauth-config-check/Build/Products/Debug-iphonesimulator/Omnigent.app/Info.plist | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 40 | plutil -extract DatabricksOAuthRedirectURL raw \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 41 | /tmp/omnigent-oauth-config-check/Build/Products/Debug-iphonesimulator/Omnigent.app/Info.plist | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 52 | ˋcallbackURLScheme: "https"ˋ or the ˋomnigent://ˋ conversation-link handler. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 54 | The app's ˋOmnigent/Omnigent.entitlementsˋ declares | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 55 | ˋwebcredentials:login.databricks.comˋ for the default redirect. Before real | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 63 | 3. Register the exact redirect URL on the Databricks public OAuth client and | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 64 | enable that client for the intended Databricks accounts. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 78 | ˋDatabricksLoginManager.signInˋ takes a workspace URL, validated build | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 100 | are HTTPS Databricks workspace ˋ/oidcˋ and account ˋ/oidc/accounts/<account-id>ˋ URLs | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 101 | on the existing Databricks workspace domain families. Issuers with userinfo, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 121 | Use ˋDatabricksTokenManager.sharedˋ for all production callers. A | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 122 | ˋDatabricksCredentialScopeˋ identifies one account per normalized entered origin, | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 153 | - ˋclear(for:)ˋ is the native credential primitive. Use ˋDatabricksSignOutManagerˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 172 | ˋDatabricksWorkspaceBootstrapˋ first obtains a saved/refreshed grant, or requests | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 186 | HTTPS Databricks workspace-domain families, with no userinfo, nondefault ports, or | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 202 | ˋGET <workspace>/omnigent/v1/meˋ (keeping ˋoˋ, no redirects followed). A 401 or a | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 206 | ˋDatabricksWebStoreˋ uses a stable, named ˋWKWebsiteDataStoreˋ for the credential | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 247 | ˋwindow.omnigentNative.signOut()ˋ. That capability is not exposed for other server | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 271 | - ˋDatabricksOAuthConfigurationTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 272 | - ˋDatabricksOAuthAttemptTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 273 | - ˋDatabricksOAuthClientTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 274 | - ˋDatabricksOAuthIssuerTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 275 | - ˋDatabricksLoginManagerTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 276 | - ˋDatabricksCredentialStoreTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 277 | - ˋDatabricksTokenManagerTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 278 | - ˋDatabricksSessionClientTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 279 | - ˋDatabricksWebContextTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 280 | - ˋDatabricksWorkspaceBootstrapTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 281 | - ˋDatabricksLifecycleTestsˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 298 | auth sheet and confirm the intended Omnigent page and API access work. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 315 | 8. Check a Databricks Apps URL for unchanged behavior, and a generic OIDC server per | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 321 | References: [Databricks U2M OAuth](https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m), | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 324 | [Databricks refresh rotation](https://docs.databricks.com/aws/en/integrations/single-use-tokens), | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/ios/docs/managed-app-configuration.md`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | Administrators can preset the server URLs the Omnigent iOS app offers, so people | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 5 | also enable Databricks-internal features for managed installs. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 26 | as before: no preset servers, the person types a URL, and Databricks-internal | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 34 | \| ˋdatabricksInternalFeaturesEnabledˋ \| Boolean          \| No       \| ˋfalseˋ \| Enables Databricks-s… | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 38 | - A bare host is accepted and read as ˋhttps://ˋ — ˋomnigent.corp.example.comˋ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 39 | becomes ˋhttps://omnigent.corp.example.comˋ. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 41 | ˋhttps://my-workspace.cloud.databricks.com/ml/omnigentsˋ. The app can discover | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 42 | a Databricks workspace mount on its own, but naming it here skips that lookup. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 67 | ## Databricks-internal features | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 69 | Set ˋdatabricksInternalFeaturesEnabledˋ to a **boolean** ˋtrueˋ in either delivery | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 74 | <key>databricksInternalFeaturesEnabled</key> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 101 | ˋ--omnigent-managed-serversˋ test override, set the classic configuration: | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 104 | xcrun simctl spawn booted defaults write ai.omnigent.ios com.apple.configuration.managed \ | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 105 | '<dict><key>databricksInternalFeaturesEnabled</key><true/></dict>' | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 106 | xcrun simctl terminate booted ai.omnigent.ios | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 107 | xcrun simctl launch booted ai.omnigent.ios --omnigent-reset-state | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 114 | 1. Connect to ˋhttps://omnigent-dns-test.invalidˋ. The connect screen should show | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 119 | ˋxcrun simctl spawn booted defaults delete ai.omnigent.ios com.apple.configuration.managedˋ. | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 133 | <string>https://omnigent.corp.example.com</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |
| 134 | <string>https://my-workspace.cloud.databricks.com/ml/omnigents</string> | keep-origin |  | upstream developer documentation in the source tree (L6 c); not a user-visible product surface |

### `web/ios/fastlane/Appfile`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | app_identifier("ai.omnigent.ios")  # The bundle identifier of the app | keep-deferred |  | iOS bundle identifier ai.omnigent.ios for fastlane/App Store; mobile bundle ids and signing deferred to OQ-31. |
| 2 | …ortal team (Databricks, Inc.) | keep-internal |  | code comment |

### `web/ios/fastlane/Fastfile`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | def omnigent_available_port | keep-internal |  | code identifier |
| 16 | def omnigent_start_process(label, env,… | keep-internal |  | code identifier |
| 31 | def omnigent_run_command(label, comman… | keep-internal |  | code identifier |
| 38 | def omnigent_fetch_env(*names) | keep-internal |  | code identifier |
| 47 | def omnigent_stop_process(pid) | keep-internal |  | code identifier |
| 65 | def omnigent_default_simulator | keep-internal |  | code identifier |
| 69 | simulator = OmnigentSimulator.default_… | keep-internal |  | code identifier |
| 74 | def omnigent_wait_for_http(url, timeou… | keep-internal |  | code identifier |
| 103 | BUNDLE_ID = "ai.omnigent.ios" | keep-deferred |  | iOS App Store bundle id used for TestFlight/App Store uploads; mobile bundle ids and store listings deferred to OQ-31. |
| 106 | …sc "Run the OmnigentTests unit tests" | keep-internal |  | Fastlane lane description naming the OmnigentTes |
| 109 | scheme: "Omnigent", | keep-internal |  | Xcode scheme name Omnigent; iOS project/scheme n |
| 113 | skip_testing: ["OmnigentUITests"] | keep-internal |  | OmnigentUITests Xcode test target name. |
| 117 | …and run the Omnigent app in the iOS Si… | keep-internal |  | Fastlane lane description shown only to develope |
| 119 | name = OmnigentSimulator.requested_nam… | keep-internal |  | OmnigentSimulator Ruby helper and OMNIGENT_IOS_S |
| 124 | simulator = omnigent_default_simulator | keep-internal |  | code identifier |
| 133 | project: "Omnigent.xcodeproj", | keep-internal |  | Omnigent.xcodeproj project file name. |
| 134 | scheme: "Omnigent", | keep-internal |  | Xcode scheme name Omnigent. |
| 143 | …nesimulator/Omnigent.app") | keep-internal |  | Build product path Omnigent.app comes from the X |
| 148 | sh("xcrun simctl launch '#{device}' ai.omnigent.ios") | keep-deferred |  | simctl launch by bundle id ai.omnigent.ios; mobile bundle id deferred to OQ-31. |
| 157 | …repo_root, "omnigent/server/static/web… | keep-internal |  | Path into the omnigent Python package (static we |
| 159 | omnigent_run_command( | keep-internal |  | code identifier |
| 165 | omnigent_run_command( | keep-internal |  | code identifier |
| 172 | … ENV.fetch("OMNIGENT_SCREENSHOT_SERVER… | keep-internal |  | OMNIGENT_SCREENSHOT_SERVER_PORT env var and omni |
| 173 | …ser_error!("OMNIGENT_SCREENSHOT_SERVER… | keep-internal |  | Developer error naming the OMNIGENT_SCREENSHOT_S |
| 175 | …ir.tmpdir, "omnigent-ios-screenshots-#… | keep-internal |  | Temporary screenshot directory name. |
| 179 | …n(log_dir, "omnigent-server.log") | keep-internal |  | Temporary server log file name for the screensho |
| 192 | "omnigent", | keep-deferred |  | Invokes the omnigent CLI ('uv run omnigent server'); CLI name changes under OPS-03/FND-01. |
| 208 | server_pid = omnigent_start_process( | keep-internal |  | code identifier |
| 209 | "Omnigent server", | keep-internal |  | Label for the omnigent_start_process UI.message |
| 212 | "OMNIGENT_DATA_DIR" => data_dir, | keep-internal |  | OMNIGENT_DATA_DIR env var. |
| 213 | "OMNIGENT_NO_UPDATE_CHECK" => "1", | keep-internal |  | OMNIGENT_NO_UPDATE_CHECK env var. |
| 219 | omnigent_wait_for_http("#{server_url}/… | keep-internal |  | code identifier |
| 221 | ENV["OMNIGENT_SCREENSHOT_APP_URL"] = s… | keep-internal |  | OMNIGENT_SCREENSHOT_APP_URL env var read by Omni |
| 223 | …_testing: ["OmnigentUITests/OmnigentUI… | keep-internal |  | OmnigentUITests test target/class/method identif |
| 224 | …uments: ["--omnigent-server-url #{serv… | keep-internal |  | --omnigent-server-url launch argument parsed by |
| 225 | test_target_name: "Omnigent", | keep-internal |  | Xcode test target name Omnigent. |
| 232 | omnigent_stop_process(server_pid) | keep-internal |  | code identifier |
| 260 | …mber = ENV["OMNIGENT_PROD_BUILD_NUMBER… | keep-internal |  | OMNIGENT_PROD_BUILD_NUMBER env var for release t |
| 262 | …ir.tmpdir, "omnigent-ios-app-store-scr… | keep-internal |  | Temporary App Store screenshot directory name. |
| 273 | …rsion: ENV["OMNIGENT_PROD_APP_VERSION"… | keep-internal |  | OMNIGENT_PROD_APP_VERSION env var for release to |
| 274 | xcodeproj: "Omnigent.xcodeproj", targe… | keep-internal |  | Omnigent.xcodeproj project and Omnigent target n |
| 299 | scheme: "Omnigent", | keep-internal |  | Xcode scheme name Omnigent for the archive build |
| 320 | …expand_path(omnigent_fetch_env("ASC_KE… | keep-internal |  | code identifier |
| 324 | key_id: omnigent_fetch_env("ASC_KEY_ID… | keep-internal |  | code identifier |
| 325 | issuer_id: omnigent_fetch_env("ASC_ISS… | keep-internal |  | code identifier |

### `web/ios/fastlane/Snapfile`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | project("Omnigent.xcodeproj") | keep-internal |  | Omnigent.xcodeproj project file name. |
| 2 | scheme("Omnigent") | keep-internal |  | Xcode scheme name Omnigent. |
| 3 | test_target_name("Omnigent") | keep-internal |  | Xcode test target name Omnigent. |
| 4 | …y_testing(["OmnigentUITests/OmnigentUI… | keep-internal |  | OmnigentUITests test target/class/method identif |

### `web/ios/fastlane/metadata/copyright.txt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | Databricks Inc. 2026 | keep-deferred |  | App Store listing metadata (OQ-31: store listings out of scope). |

### `web/ios/fastlane/metadata/en-US/description.txt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | Omnigent is the mobile companion for your Omnigent server: an open-source workspace for supervising … | keep-deferred |  | App Store listing metadata (OQ-31). |
| 5 | Use Omnigent to: | keep-deferred |  | App Store listing metadata (OQ-31). |
| 10 | - Reach self-hosted or cloud-hosted Omnigent deployments | keep-deferred |  | App Store listing metadata (OQ-31). |
| 12 | …pp is a native iOS shell for the Omnigent web UI. You need access to an Omnigent server to use it. F… | keep-deferred |  | App Store listing metadata (OQ-31). |

### `web/ios/fastlane/metadata/en-US/promotional_text.txt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | Connect your iPhone or iPad to Omnigent and keep agent sessions, chats, files, and terminals within … | keep-deferred |  | App Store listing metadata (OQ-31). |

### `web/ios/fastlane/metadata/en-US/support_url.txt`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …/github.com/omnigent-ai/omnigent/issue… | keep-internal |  | code identifier |

### `web/ios/fastlane/simulator.rb`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | module OmnigentSimulator | keep-internal |  | code identifier |
| 7 | …n wins over OMNIGENT_IOS_SIMULATOR; bl… | keep-internal |  | code comment |

### `web/ios/fastlane/test/simulator_test.rb`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | class OmnigentSimulatorTest < Minitest… | keep-internal |  | test code |
| 20 | …qual "NEW", OmnigentSimulator.default_… | keep-internal |  | test code |
| 28 | …qual "OLD", OmnigentSimulator.default_… | keep-internal |  | test code |
| 33 | …qual "TEN", OmnigentSimulator.default_… | keep-internal |  | test code |
| 37 | assert_nil OmnigentSimulator.default_i… | keep-internal |  | test code |
| 38 | assert_nil OmnigentSimulator.default_i… | keep-internal |  | test code |
| 42 | …Phone Air", OmnigentSimulator.requeste… | keep-internal |  | test code |
| 43 | …iPhone 17", OmnigentSimulator.requeste… | keep-internal |  | test code |
| 44 | assert_nil OmnigentSimulator.requested… | keep-internal |  | test code |

### `web/platform-assets/AppIcon.icon`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S88 | Starfish Icon Composer source; the iOS project now references platform-assets/coral/AppIcon.icon (unverified without Xcode 26). |

### `web/platform-assets/logos/omnigents-logo-reverse.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S89b | Dark variant of the above; replaced on the setup page. Kept, unused there. |

### `web/platform-assets/logos/omnigents-logo.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S89b | Starfish + wordmark on the Electron setup page; it now shows coral-mark.svg. Kept, unused there. |

### `web/public/apple-touch-icon.png`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S89 | Starfish apple-touch icon; index.html now points at coral-apple-touch-icon.png. Kept, unused. |

### `web/public/favicon.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S89 | Omnigent starfish favicon; index.html now points at web/public/coral-mark.svg. Kept in place, unused (L5). |

### `web/server-selector-v2.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | <title>Omnigents — Connect</title> | change | S89b | Window/tab title of the Electron connect page (loaded by web/electron/src/main.js:154/207); shows the product name. |

### `web/src/App.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | useOmnigentPageView: vi.fn(), | keep-internal |  | test code |
| 10 | useOmnigentAnalytics: () => ({ trackCl… | keep-internal |  | test code |
| 83 | import { useOmnigentPageView } from "@… | keep-internal |  | test code |
| 175 | …i.mocked(useOmnigentPageView).mockClea… | keep-internal |  | test code |
| 196 | …) expect(useOmnigentPageView).not.toHa… | keep-internal |  | test code |

### `web/src/App.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { useOmnigentPageView } from "@… | keep-internal |  | code identifier |
| 18 | …nge (see useOmnigentPageView), so a pa… | keep-internal |  | code comment |
| 26 | useOmnigentPageView(id); | keep-internal |  | code identifier |
| 99 | … (e.g. ˋ/ml/omnigent-embedˋ). The rout… | keep-internal |  | code comment |
| 104 | …ounts via ˋ@databricks/web-shared/rout… | keep-internal |  | code comment |

### `web/src/assets/claude-code-logo.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Third-party Claude Code glyph for the harness pi |
| 2 | …through the Databricks npm | keep-internal |  | SVG source comment about the npm proxy used to f |

### `web/src/assets/claude.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Third-party Claude glyph (MIT, LobeHub) for the |

### `web/src/assets/omnigent-center-glow.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-internal |  | Plain white radial glow behind the dark shell; n |

### `web/src/assets/omnigent-starfish-icon.png`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S89 | Starfish used by onboarding, auth cards and the import dialog; they now import the Coral mark. Kept, unused. |

### `web/src/assets/omnigent-wordmark.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | change-asset | S80 | Omnigent wordmark in the sidebar default branch; replaced by CoralWordmark. Kept, unused. |

### `web/src/assets/otto-no-padding.svg`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| - | (asset) | keep-L7 |  | Otto mascot artwork; not imported by Coral surfaces (the Powered-by credit renders OttoEyes). |

### `web/src/canvas/CanvasWorkspace.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 190 | …ge.getItem("omnigent:canvas-split-rati… | keep-internal |  | test code |
| 210 | …ge.setItem("omnigent:canvas-split-rati… | keep-internal |  | test code |
| 216 | …ge.getItem("omnigent:canvas-split-rati… | keep-internal |  | test code |
| 233 | …ge.setItem("omnigent:canvas-split-rati… | keep-internal |  | test code |

### `web/src/canvas/CanvasWorkspace.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | …ATIO_KEY = "omnigent:canvas-split-rati… | keep-internal |  | localStorage key omnigent:canvas-split-ratio; st |
| 162 | "--omnigent-header-height": "0px", | keep-internal |  | CSS custom property --omnigent-header-height; in |

### `web/src/canvas/canvasNavigation.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …h(["", "/ml/omnigent-embed"])("matches… | keep-internal |  | test code |

### `web/src/canvas/canvasSessions.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | getOmnigentServerIdentity: vi.fn(() =>… | keep-internal |  | test code |
| 79 | …ked(host.getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 354 | …ked(host.getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 443 | "omnigent:canvas-sessions:server-a:me"… | keep-internal |  | test code |

### `web/src/canvas/canvasSessions.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 31 | …Y_PREFIX = "omnigent:canvas-sessions"; | keep-internal |  | Storage cache key prefix omnigent:canvas-session |
| 69 | return getOmnigentServerIdentity() ?? … | keep-internal |  | code identifier |

### `web/src/canvas/canvasStorage.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | ˋomnigent:canvas-layout:${window.locat… | keep-internal |  | test code |
| 25 | ˋomnigent:canvas-layout:${window.locat… | keep-internal |  | test code |
| 83 | ˋomnigent:canvas-active:${window.locat… | keep-internal |  | test code |

### `web/src/canvas/canvasStorage.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 18 | …Y_PREFIX = "omnigent:canvas-layout"; | keep-internal |  | localStorage key prefix omnigent:canvas-layout. |
| 19 | …Y_PREFIX = "omnigent:canvas-active"; | keep-internal |  | localStorage key prefix omnigent:canvas-active. |
| 33 | …REFIX}:${getOmnigentServerIdentity() ?… | keep-internal |  | JS identifier getOmnigentServerIdentity builds a |
| 37 | …REFIX}:${getOmnigentServerIdentity() ?… | keep-internal |  | JS identifier getOmnigentServerIdentity builds a |

### `web/src/components/AgentInfo.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 146 | name: "databricks_coding_agent", | keep-internal |  | test code |
| 147 | …des against Databricks.", | keep-internal |  | test code |
| 189 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |
| 190 | …des against Databricks.")).toBeInTheDo… | keep-internal |  | test code |
| 243 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |
| 446 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |
| 489 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |
| 559 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |
| 567 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |
| 590 | "databricks-gpt-5-5": { | keep-internal |  | test code |
| 610 | …-info-model-databricks-gpt-5-5"); | keep-internal |  | test code |
| 611 | …extContent("databricks-gpt-5-5"); | keep-internal |  | test code |
| 642 | ….getByText("Databricks_coding_agent"))… | keep-internal |  | test code |

### `web/src/components/ArcaShutdownBanner.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 50 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 56 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 81 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 96 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 114 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 135 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 159 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 177 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |

### `web/src/components/ArcaShutdownToast.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 77 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 84 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 112 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 128 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 153 | …ge.setItem("omnigent:arca-shutdown:dis… | keep-internal |  | test code |
| 155 | …e", { key: "omnigent:arca-shutdown:dis… | keep-internal |  | test code |
| 211 | …ge.getItem("omnigent:arca-shutdown:war… | keep-internal |  | test code |

### `web/src/components/BrandLogo.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | const getOmnigentHostConfig = vi.fn(); | keep-internal |  | test code |
| 11 | getOmnigentHostConfig: () => getOmnige… | keep-internal |  | test code |
| 12 | getOmnigentHostGeneration: () => hostG… | keep-internal |  | test code |
| 76 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 88 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 97 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 113 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 124 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 139 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 157 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 170 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 189 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |

### `web/src/components/BrandLogo.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | import { getOmnigentHostConfig, getOmn… | keep-internal |  | code identifier |
| 174 | if (getOmnigentHostConfig().fetcher) { | keep-internal |  | code identifier |
| 175 | …ration = getOmnigentHostGeneration(); | keep-internal |  | code identifier |

### `web/src/components/BrowserPane/BrowserPane.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 43 | …nknown as { omnigentDesktop?: Record<s… | keep-internal |  | test code |
| 44 | .omnigentDesktop; | keep-internal |  | test code |
| 56 | …mal ˋwindow.omnigentDesktopˋ stub. The… | keep-internal |  | test code |
| 84 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 109 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 704 | ˋ4 cookies for ${HOST} and its subdomains. Other sites' cookies stay out of Omnigent entirely.ˋ, | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/BrowserPane/BrowserPane.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 84 | … of ˋwindow.omnigentDesktopˋ the pane … | keep-internal |  | code comment |
| 139 | …nknown as { omnigentDesktop?: BrowserP… | keep-internal |  | code identifier |
| 140 | return w.omnigentDesktop ?? null; | keep-internal |  | code identifier |
| 790 | the copy disappears when Omnigent quits. | change | S89 | Visible browser-pane copy names the product. |
| 838 | {activeCookieScope} and its subdomains. Other sites' cookies stay out of Omnigent | change | S89 | Visible browser-pane copy names the product. |

### `web/src/components/ComposerMicButton.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 417 | databricks_features: false, | keep-internal |  | test code |
| 681 | …, unknown>).omnigentDesktop = { kind: … | keep-internal |  | test code |
| 698 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |

### `web/src/components/CostRoutingControl.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 91 | labels: { "omnigent.wrapper": "cursor-… | keep-internal |  | test code |
| 115 | …tModelName("databricks-claude-haiku-4-… | keep-internal |  | test code |
| 116 | …tModelName("databricks-claude-sonnet-4… | keep-internal |  | test code |
| 120 | …"strips the databricks- prefix from no… | keep-internal |  | test code |
| 121 | …tModelName("databricks-gpt-5-4-mini"))… | keep-internal |  | test code |

### `web/src/components/CostRoutingControl.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | …ABEL_KEY = "omnigent.routing.auto_harn… | keep-internal |  | Session label key persisted server-side and matc |
| 87 | …model ids ("databricks-claude-haiku-4-… | keep-internal |  | code comment |
| 96 | … id, e.g. ˋ"databricks-claude-haiku-4-… | keep-internal |  | code comment |
| 104 | …startsWith("databricks-") ? model.slic… | keep-internal |  | Parses the databricks- model-id prefix; data val |

### `web/src/components/DbcertBanner.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | import { isDatabricksWorkspace } from … | keep-internal |  | test code |
| 43 | isDatabricksWorkspace: vi.fn(), | keep-internal |  | test code |
| 72 | name: "omnigent-arclet-891349936151385… | keep-internal |  | test code |
| 81 | vi.mocked(isDatabricksWorkspace).mockR… | keep-internal |  | test code |
| 89 | …lvedValue({ databricksInternalFeatures… | keep-internal |  | test code |
| 90 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 100 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 105 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 117 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 132 | { databricksInternalFeatures: true, ca… | keep-internal |  | test code |
| 133 | { databricksInternalFeatures: false, c… | keep-internal |  | test code |
| 134 | { databricksInternalFeatures: true }, | keep-internal |  | test code |
| 150 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 164 | …nknown as { omnigentDesktop: unknown }… | keep-internal |  | test code |
| 178 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 206 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 220 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 257 | name: "omnigent-arclet-891349936151385… | keep-internal |  | test code |
| 265 | …e dbcert on omnigent-arclet-8913499361… | keep-internal |  | test code |
| 276 | …s outside a Databricks deployment", as… | keep-internal |  | test code |
| 277 | vi.mocked(isDatabricksWorkspace).mockR… | keep-internal |  | test code |
| 385 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 408 | …e dbcert on omnigent-arclet-8913499361… | keep-internal |  | test code |

### `web/src/components/HarnessConfigControls.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 46 | ["databricks-claude-sonnet-4-6", "Sonn… | keep-internal |  | test code |

### `web/src/components/HostBadge.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 53 | …l({ label: "Databricks Sandbox", statu… | keep-internal |  | test code |
| 131 | ["Databricks Sandbox host", "lakebox"]… | keep-internal |  | test code |
| 138 | …pshot" ? { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 347 | …st({ name: "omnigent-arclet-1234567890… | keep-internal |  | test code |
| 353 | …tent("Name: omnigent-arclet-1234567890… | keep-internal |  | test code |
| 364 | …tent("Host: Databricks Sandbox"); | keep-internal |  | test code |
| 431 | ….toContain("Databricks Sandbox"); | keep-internal |  | test code |
| 571 | …st({ name: "omnigent-arclet-1234", san… | keep-internal |  | test code |

### `web/src/components/HostBadge.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 40 | …der label ("Databricks Sandbox"). | keep-internal |  | code comment |
| 189 | …name, e.g. "omnigent-arclet-1234", | keep-internal |  | code comment |
| 272 | …anding out ˋomnigent hostˋ. | keep-internal |  | code comment |

### `web/src/components/ImageLightbox.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 296 | …rem + var(--omnigent-safe-top, 0px))", | keep-internal |  | CSS custom property --omnigent-safe-top set by n |
| 297 | …rem + var(--omnigent-safe-right, 0px))… | keep-internal |  | CSS custom property --omnigent-safe-right set by |

### `web/src/components/KeyboardShortcutsDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 269 | expect(screen.queryByText("Quit Omnigent")).toBeNull(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 282 | expect(keysFor("Quit Omnigent")).toEqual(["Ctrl", "Q"]); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/KeyboardShortcutsDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 71 | …TS_EVENT = "omnigent:open-keyboard-sho… | keep-internal |  | Custom DOM event name omnigent:open-keyboard-sho |
| 181 | { label: "Quit Omnigent", keys: [...QUIT_KEYS] }, | change | S89 | Shortcut label 'Quit Omnigent' shown in the Keyboard Shortcuts dialog on desktop. |

### `web/src/components/McpRegistry.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | it.each(["github", "databricks"])( | keep-internal |  | test code |
| 218 | …"asks for a Databricks workspace befor… | keep-internal |  | test code |
| 219 | const databricks = { ...service, auth:… | keep-internal |  | test code |
| 220 | …ce({ data: [databricks] }); | keep-internal |  | test code |
| 227 | …yLabelText("Databricks workspace URL")… | keep-internal |  | test code |
| 231 | …data: [{ ...databricks, connected: tru… | keep-internal |  | test code |
| 235 | databricks, | keep-internal |  | test code |

### `web/src/components/McpRegistry.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 110 | …e.auth === "databricks") && ( | keep-internal |  | Compares against API auth value 'databricks'; pr |
| 112 | Uses your shared {service.auth === "github" ? "GitHub" : "Databricks"} connection.{" "} | keep-origin |  | 'Uses your shared Databricks connection' names the Databricks integration the user connects to. |
| 230 | …e.auth === "databricks" && !workspaceU… | keep-internal |  | Compares against API auth value 'databricks'. |
| 312 | aria-label="Databricks workspace URL" | keep-origin |  | aria-label 'Databricks workspace URL' names the Databricks workspace sign-in integration. |
| 313 | placeholder="https://your-workspace.cloud.databricks.com" | keep-origin |  | Placeholder example Databricks workspace URL for the Databricks integration. |

### `web/src/components/ModelValueCombobox.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 9 | "databricks-claude-sonnet-5", | keep-internal |  | test code |
| 10 | "databricks-claude-haiku-4-5", | keep-internal |  | test code |
| 46 | …Selected={["databricks-claude-sonnet-5… | keep-internal |  | test code |
| 53 | …Selected={["databricks-claude-sonnet-5… | keep-internal |  | test code |

### `web/src/components/OttoEyes.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 31 | …ia-label", "Omnigent"); | keep-internal |  | test code |

### `web/src/components/OttoEyes.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 156 | * The Omnigent starfish mascot (Otto) … | keep-internal |  | code comment |
| 360 | aria-label="Omnigent" | keep-L7 |  | Otto mascot component rendered by the PoweredByOmnigent credit (L7); BrandLogo stops using it under S79. |

### `web/src/components/PageLoading.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | export function PageLoading({ label = "Loading Omnigent…" }: { label?: string }) { | change | S89 | Default loading text 'Loading Omnigent…' shown as the App.tsx Suspense fallback inside CapabilitiesProvider. |

### `web/src/components/PageScroll.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | * (ˋ--omnigent-header-heightˋ, ˋ--omni… | keep-internal |  | code comment |
| 60 | …? " + var(--omnigent-header-height)" :… | keep-internal |  | CSS custom property --omnigent-header-height. |
| 61 | …? " + var(--omnigent-inset-top)" : "" | keep-internal |  | CSS custom property --omnigent-inset-top. |
| 63 | …? " + var(--omnigent-inset-bottom)" : … | keep-internal |  | CSS custom property --omnigent-inset-bottom. |

### `web/src/components/PermissionsModal.designs.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | …port type { OmnigentHostConfig } from … | keep-internal |  | test code |
| 46 | … = "https://omnigent.example/c/sharing… | keep-internal |  | test code |
| 66 | … = useState<OmnigentHostConfig>(() => … | keep-internal |  | test code |
| 87 | …h, "https://omnigent.example").pathnam… | keep-internal |  | test code |
| 119 | workspace: "/projects/omnigent", | keep-internal |  | test code |
| 392 | ? "This Omnigent server allows read-only sharing. Invite others to view or comment on this session." | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 393 | : "This Omnigent server allows sharing. Invite others to view or edit this session."} | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 519 | value="omnigent://omnigent.example/c/sharing-design-preview" | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/PermissionsModal.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | getOmnigentUserSearch: vi.fn(() => und… | keep-internal |  | test code |
| 48 | getOmnigentTransformShareLink: vi.fn((… | keep-internal |  | test code |
| 84 | …ked(host.getOmnigentUserSearch); | keep-internal |  | test code |
| 85 | …ked(host.getOmnigentTransformShareLink… | keep-internal |  | test code |
| 107 | databricks_features: false, | keep-internal |  | test code |
| 717 | await screen.findByText("Sharing has been disabled for this Omnigent server."), | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 735 | screen.getByText(/This Omnigent server allows Read and Edit access for added people\./), | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 739 | screen.queryByText("Sharing has been disabled for this Omnigent server."), | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 753 | /This Omnigent server allows read-only sharing\. Invite others to read this session\./, | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 778 | /This Omnigent server allows read-only sharing\. Invite others to read this session\./, | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1061 | // The QR encodes an ˋomnigent://<host>/c/<id>ˋ deep link (the same scheme | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1083 | it("encodes the omnigent:// deep link for the session from the server origin", async () => { | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1096 | expect(qr).toHaveAttribute("data-value", "omnigent://app.example.com/c/conv_abc"); | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1101 | // Mirrors the deep-link convention: ˋomnigent://localhost:8000/c/<id>ˋ. | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1112 | expect(qr).toHaveAttribute("data-value", "omnigent://localhost:8000/c/conv_abc"); | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1129 | expect(qr).toHaveAttribute("data-value", "omnigent://host.example.com/c/conv_xyz"); | change | S38,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/PermissionsModal.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | import { getOmnigentUserSearch } from … | keep-internal |  | code identifier |
| 209 | Sharing has been disabled for this Omnigent server. | change | S89 | Web copy of the server sharing-disabled reason (server copy stays Omnigent). |
| 235 | ? "This Omnigent server allows read-only sharing. Invite others to read this session." | change | S89 | Share dialog copy shown to users; 'this Omnigent server' product wording becomes the app name. |
| 236 | : "This Omnigent server allows Read and Edit access for added people."} | change | S89 | Share dialog copy shown to users; 'this Omnigent server' product wording becomes the app name. |
| 307 | this Omnigent server. | change | S89 | Visible sharing copy: "this Omnigent server". |
| 466 | …hUsers = getOmnigentUserSearch(); | keep-internal |  | code identifier |
| 630 | * The ˋomnigent://<host>/c/<session_id>ˋ deep link encoded into the share QR | change | S38,S89 | Changed with its seam: code comment |
| 641 | return ˋomnigent://${host}/c/${sessionId}ˋ; | change-identity | S38 | Generates the omnigent:// session deep link encoded in the share QR code; must follow the new coral URL scheme. |
| 644 | return ˋomnigent://${window.location.host}/c/${sessionId}ˋ; | change-identity | S38 | Fallback branch of the same QR deep-link generator; must use the coral scheme. |
| 682 | * ˋomnigent://<host>/c/<id>ˋ deep link so a user can scan it with their phone | change | S38,S89 | Changed with its seam: code comment |
| 683 | …sion in the Omnigent app. The code is … | keep-internal |  | code comment |
| 709 | Scan with your phone's camera to open this session in the Omnigent app. | change | S89 | QR caption names the app the coral:// link opens. |
| 722 | aria-label="QR code to open this session in the Omnigent app" | change | S89 | aria-label on the QR code names the product app. |

### `web/src/components/PoweredByOmnigent.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | … { PoweredByOmnigent } from "./Powered… | keep-internal |  | test code |
| 5 | title: "Components/PoweredByOmnigent", | keep-internal |  | test code |
| 6 | component: PoweredByOmnigent, | keep-internal |  | test code |
| 8 | …of PoweredByOmnigent>; | keep-internal |  | test code |

### `web/src/components/PoweredByOmnigent.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …"Powered by Omnigent" mark for the lan… | keep-internal |  | code comment |
| 7 | export function PoweredByOmnigent() { | keep-L7 |  | PoweredByOmnigent component stays as-is (Powered-by credit). |
| 11 | data-testid="powered-by-omnigent" | keep-L7 |  | Test id of the Powered-by credit; the credit stays as-is. |
| 15 | <span>Omnigent</span> | keep-L7 |  | The 'Powered by Omnigent' credit text stays exactly as-is. |

### `web/src/components/ProjectIconPicker.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | workspace: "/workspace/omnigent", | keep-internal |  | test code |

### `web/src/components/SessionImage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | const getOmnigentHostConfig = vi.fn(); | keep-internal |  | test code |
| 19 | getOmnigentHostConfig: () => getOmnige… | keep-internal |  | test code |
| 64 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |
| 109 | getOmnigentHostConfig.mockReturnValue(… | keep-internal |  | test code |

### `web/src/components/SessionImage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | import { getOmnigentHostConfig } from … | keep-internal |  | code identifier |
| 104 | if (!getOmnigentHostConfig().fetcher) … | keep-internal |  | code identifier |

### `web/src/components/StreamBudgetBanner.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | …6px + var(--omnigent-inset-top, 0px))"… | keep-internal |  | CSS custom property name --omnigent-inset-top (i |

### `web/src/components/UpdateBanner.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 41 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 46 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 63 | expect(await screen.findByText("Omnigent Desktop 0.4.0 is available")).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 74 | expect(await screen.findByText("Downloading Omnigent Desktop update… 42%")).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 80 | await screen.findByText("Omnigent Desktop 0.4.0 is ready to install"), | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 101 | await screen.findByText("Omnigent Desktop 0.4.0 is ready to install"), | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 114 | expect(await screen.findByText("Omnigent Desktop 0.4.0 is available")).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 133 | expect(await screen.findByText("Omnigent Desktop 0.4.0 is available")).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 138 | expect(screen.queryByText("Omnigent Desktop 0.4.0 is available")).toBeNull(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/UpdateBanner.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 156 | Omnigent Desktop {visibleStatus.info?.version ?? "update"} is available | change | S89 | Desktop update banner names the product. |
| 171 | Downloading Omnigent Desktop update… {progress}% | change | S89 | Desktop update banner names the product. |
| 183 | Omnigent Desktop {visibleStatus.info?.version ?? "update"} is ready to install | change | S89 | Desktop update banner names the product. |

### `web/src/components/VideoPlayer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 259 | … media (the Databricks workspace) supp… | keep-internal |  | test code |

### `web/src/components/ai-elements/mathMarkdown.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 23 | …API_KEY or $OMNIGENT_LLM_API_KEY in th… | keep-internal |  | test code |
| 28 | …ters("use ${OMNIGENT_LLM_API_KEY} here… | keep-internal |  | test code |
| 29 | "use ${OMNIGENT_LLM_API_KEY} here", | keep-internal |  | test code |

### `web/src/components/ai-elements/message.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 171 | 'before <omnigent-github-image src="ht… | keep-internal |  | test code |
| 269 | root.className = "omnigent-app"; | keep-internal |  | test code |

### `web/src/components/ai-elements/streamdown-security.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | …MAGE_TAG = "omnigent-github-image"; | keep-internal |  | Internal custom tag name used to park GitHub ima |
| 51 | …TTR = "data-omnigent-file"; | keep-internal |  | data-* attribute name (data-omnigent-file) for w |
| 101 | …LE_HREF = "#omnigent-file"; | keep-internal |  | Internal fragment href placeholder (#omnigent-fi |

### `web/src/components/blocks/ApprovalCard.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 99 | cwd: "/workspace/omnigent", | keep-internal |  | test code |

### `web/src/components/blocks/ApprovalCard.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 754 | …{'Allow the omnigent MCP server to run… | keep-internal |  | test code |
| 820 | "Ask Antigravity to save a rule allowing commands starting with “pwd” for this Omnigent session", | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/blocks/ApprovalCard.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 566 | …on.alwaysAllowPattern}” for this Omnigent sessionˋ} | change | S89 | Button tooltip (title) shown to users names the product ('this Omnigent session'). |
| 1018 | Always allow saves a rule for this Omnigent session. New sessions have separate | change | S89 | Approval card copy: "this Omnigent session". |

### `web/src/components/blocks/BlockRenderer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 179 | …ited before Omnigent captured a pane s… | keep-internal |  | test code |

### `web/src/components/blocks/BlockRenderer.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 833 | …els", "mcp__omnigent__sys_advise_model… | keep-internal |  | MCP tool name mcp__omnigent__sys_advise_models m |
| 834 | …end", "mcp__omnigent__sys_session_send… | keep-internal |  | MCP tool name mcp__omnigent__sys_session_send ma |

### `web/src/components/blocks/ChatMarkdown.inAppLinkRouting.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | omnigentDesktop: { kind: "electron", b… | keep-internal |  | test code |
| 33 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |

### `web/src/components/blocks/SmartRoutingCard.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | model: "databricks-claude-haiku-4-5", | keep-internal |  | test code |
| 31 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |

### `web/src/components/blocks/SmartRoutingCard.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | model: "databricks-claude-haiku-4-5", | keep-internal |  | test code |
| 31 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 68 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 83 | …odel).toBe("databricks-claude-opus-4-8… | keep-internal |  | test code |

### `web/src/components/blocks/StatusBlocks.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | "cwd: /workspace/omnigent", | keep-internal |  | test code |
| 111 | …ssage="Your Databricks model credentia… | keep-internal |  | test code |
| 115 | cause="Omnigent could not obtain a mod… | keep-internal |  | test code |
| 156 | model="databricks-claude-opus-4-8" | keep-internal |  | test code |
| 166 | model="databricks-claude-haiku-4-5" | keep-internal |  | test code |
| 169 | …terSource: "databricks-aigw" }} | keep-internal |  | test code |
| 177 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 186 | …dOverride: "databricks-claude-opus-4-8… | keep-internal |  | test code |

### `web/src/components/blocks/StatusBlocks.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 44 | …e limit for databricks-test-model. Wor… | keep-internal |  | test code |
| 45 | "Databricks account team to request a … | keep-internal |  | test code |
| 265 | title="Databricks authentication requi… | keep-internal |  | test code |
| 266 | cause="Databricks authentication is mi… | keep-internal |  | test code |
| 270 | …", { name: /Databricks authentication … | keep-internal |  | test code |
| 279 | ["databricks_sign_in_pending", "The ag… | keep-internal |  | test code |
| 335 | code="databricks_sign_in_pending" | keep-internal |  | test code |
| 336 | … sign in to Databricks" | keep-internal |  | test code |
| 392 | code="databricks_sign_in_completed" | keep-internal |  | test code |
| 393 | title="Signed in to Databricks" | keep-internal |  | test code |
| 397 | …igned in to Databricks"); | keep-internal |  | test code |
| 436 | code="databricks_sign_in_pending" | keep-internal |  | test code |
| 440 | …iting for a Databricks sign-in/i })); | keep-internal |  | test code |
| 807 | …ited before Omnigent captured a pane s… | keep-internal |  | test code |
| 1065 | model="databricks-claude-opus-4-8" | keep-internal |  | test code |
| 1082 | model="databricks-claude-haiku-4-5" | keep-internal |  | test code |
| 1096 | model="databricks-claude-haiku-4-5" | keep-internal |  | test code |
| 1112 | model="databricks-claude-opus-4-8" | keep-internal |  | test code |
| 1137 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1157 | model="databricks-claude-sonnet-4-6" | keep-internal |  | test code |
| 1178 | model="databricks-claude-sonnet-4-6" | keep-internal |  | test code |
| 1199 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1216 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1225 | …dOverride: "databricks-claude-opus-4-8… | keep-internal |  | test code |
| 1246 | ["databricks-claude-opus-4-8", "opus"]… | keep-internal |  | test code |
| 1252 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1254 | …n requested databricks-claude-opus-4-8… | keep-internal |  | test code |
| 1272 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1275 | …dOverride: "databricks-claude-opus-4-8… | keep-internal |  | test code |
| 1287 | …Card model="databricks-claude-opus-4-8… | keep-internal |  | test code |
| 1300 | …sion-source-databricks"; | keep-internal |  | test code |
| 1301 | …uted by the Databricks Unity Gateway"; | keep-internal |  | test code |
| 1303 | …ecision the Databricks Unity Gateway a… | keep-internal |  | test code |
| 1306 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1309 | …terSource: "databricks-aigw" }} | keep-internal |  | test code |
| 1329 | model="databricks-claude-sonnet-5" | keep-internal |  | test code |
| 1340 | …Card model="databricks-claude-sonnet-5… | keep-internal |  | test code |

### `web/src/components/blocks/StatusBlocks.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | import { DatabricksIcon } from "@/components/icons/DatabricksIcon"; | keep-origin |  | Databricks icon for the Databricks Unity Gateway integration (third-party service), not a publisher reference. |
| 75 | …odeˋ table (omnigent/runner/launch_fai… | keep-internal |  | code comment |
| 95 | databricks_sign_in_pending: "The agent is waiting for a Databricks sign-in.", | keep-origin |  | Status copy about a Databricks sign-in (an integration target); the key is a server status code. |
| 97 | databricks_sign_in_completed: "The Databricks sign-in completed and the agent is ready.", | keep-origin |  | Status copy about a completed Databricks sign-in (an integration target). |
| 151 | …ited before Omnigent captured a pane s… | keep-internal |  | Regex matching a server-generated message, which |
| 168 | …= new Set(["databricks_sign_in_pending… | keep-internal |  | Server status code databricks_sign_in_pending, c |
| 170 | …igned in to Databricks") does not say … | keep-internal |  | code comment |
| 171 | …= new Set(["databricks_sign_in_complet… | keep-internal |  | Server status code databricks_sign_in_completed, |
| 1070 | …Source === "databricks-aigw" ? ( | keep-internal |  | Router source id 'databricks-aigw' emitted by th |
| 1073 | title="Routed by the Databricks Unity Gateway" | keep-origin |  | Tooltip names the Databricks Unity Gateway integration (third-party router), a fact. |
| 1074 | aria-label="Routed by the Databricks Unity Gateway" | keep-origin |  | aria-label names the Databricks Unity Gateway integration (third-party router), a fact. |
| 1076 | …sion-source-databricks" | keep-internal |  | data-testid identifier. |
| 1078 | <DatabricksIcon className="size-3 shri… | keep-internal |  | code identifier |

### `web/src/components/blocks/TerminalClipboardPrompt.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 62 | …lvh - var(--omnigent-viewport-height, … | keep-internal |  | CSS custom property --omnigent-viewport-height ( |
| 110 | "calc(var(--omnigent-viewport-height, … | keep-internal |  | CSS custom properties --omnigent-viewport-height |

### `web/src/components/blocks/TerminalQueryReplies.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 46 | …iers from ˋˋomnigent/terminals/query_r… | keep-internal |  | code comment |

### `web/src/components/blocks/TerminalSession.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 88 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 100 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |

### `web/src/components/blocks/TerminalSession.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …l (mirrors ˋomnigent/server/routes/ter… | keep-internal |  | code comment |
| 41 | …ica (the ˋˋ?omnigent_slice_key=ˋˋ does… | keep-internal |  | code comment |
| 197 | * ˋˋomnigent/terminals/ws_common.pyˋˋ)… | keep-internal |  | code comment |
| 214 | …proxy (e.g. Databricks Apps) emits the… | keep-internal |  | code comment |

### `web/src/components/blocks/TerminalView.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 164 | …t("appends ?omnigent_slice_key=host_id… | keep-internal |  | test code |
| 166 | …h_s1/attach?omnigent_slice_key=host_12… | keep-internal |  | test code |
| 179 | ….toContain("omnigent_slice_key=host_78… | keep-internal |  | test code |
| 182 | it("omits ?omnigent_slice_key when no … | keep-internal |  | test code |
| 184 | …h.includes("omnigent_slice_key")).toBe… | keep-internal |  | test code |
| 1002 | …n(host, "getOmnigentServerIdentity").m… | keep-internal |  | test code |
| 1028 | …n(host, "getOmnigentServerIdentity").m… | keep-internal |  | test code |
| 1706 | …ubEnv("VITE_OMNIGENT_HOST_ROUTING", "t… | keep-internal |  | test code |
| 1710 | …Params.get("omnigent_slice_key")).toBe… | keep-internal |  | test code |
| 1840 | …ubEnv("VITE_OMNIGENT_HOST_ROUTING", "t… | keep-internal |  | test code |

### `web/src/components/blocks/TerminalView.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | getOmnigentServerIdentity, | keep-internal |  | code identifier |
| 27 | isDatabricksWorkspace, | keep-internal |  | code identifier |
| 75 | * case — a Databricks Apps redeploy re… | keep-internal |  | code comment |
| 107 | …PLICA && !isDatabricksWorkspace()) | keep-internal |  | code identifier |
| 213 | …entity = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 607 | if (isDatabricksWorkspace() && keyless… | keep-internal |  | code identifier |
| 609 | …rn h && (!isDatabricksWorkspace() \|\| !… | keep-internal |  | code identifier |
| 769 | …EPLICA && isDatabricksWorkspace()) { | keep-internal |  | code identifier |
| 951 | …arded as ˋˋ?omnigent_slice_key=ˋˋ. | keep-internal |  | code comment |
| 969 | // ˋˋomnigent_slice_keyˋˋ pins this We… | keep-internal |  | code comment |
| 975 | …params.set("omnigent_slice_key", hostI… | keep-internal |  | WebSocket query param omnigent_slice_key, parsed |
| 985 | …ed from the Omnigent server itself or … | keep-internal |  | code comment |
| 992 | *     ˋˋ?omnigent_slice_key=ˋˋ. | keep-internal |  | code comment |

### `web/src/components/blocks/ToolCard.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …s --filter @omnigent/web --filter @omn… | keep-internal |  | test code |
| 126 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 131 | …/linear.app/omnigent/issue/OMNI-12243"… | keep-internal |  | test code |
| 155 | owner: "omnigent-ai", | keep-internal |  | test code |
| 156 | repo: "omnigent", | keep-internal |  | test code |
| 163 | "omnigent-ai:shell-card-pinned-selecti… | keep-internal |  | test code |
| 290 | … "/home/dev/omnigent" }, | keep-internal |  | test code |
| 318 | cwd: "/home/dev/omnigent", | keep-internal |  | test code |
| 375 | cwd: "/home/dev/omnigent", | keep-internal |  | test code |
| 446 | cwd: "/home/dev/omnigent", | keep-internal |  | test code |
| 488 | … "/home/dev/omnigent/web/src/component… | keep-internal |  | test code |

### `web/src/components/blocks/ToolCard.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 141 | …: { owner: "omnigent-ai", repo: "omnig… | keep-internal |  | test code |

### `web/src/components/blocks/ToolValueView.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 83 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 88 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |

### `web/src/components/blocks/toolViews.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …t("resolves Omnigent's MCP-prefixed to… | keep-internal |  | test code |
| 13 | …ewFor("mcp__omnigent__manage_todo_list… | keep-internal |  | test code |
| 28 | "mcp__omnigent__sys_os_edit", | keep-internal |  | test code |
| 32 | "mcp__omnigent__sys_os_write", | keep-internal |  | test code |

### `web/src/components/blocks/toolViews.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | …for a tool; Omnigent's ˋmcp__omnigent_… | keep-internal |  | code comment |

### `web/src/components/chat/SideChatPane.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 168 | …ge.getItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 292 | …labels = { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 1397 | …labels = { "omnigent.side_chat": "1" }… | keep-internal |  | test code |
| 1404 | …ge.setItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1453 | …ge.getItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1479 | …ge.getItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1493 | …ge.setItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1507 | …ge.getItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1528 | …ge.getItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1544 | …ge.getItem(ˋomnigent.sideChatInherited… | keep-internal |  | test code |
| 1550 | …labels = { "omnigent.closed": "true" }… | keep-internal |  | test code |
| 1847 | …labels = { "omnigent.side_chat.source_… | keep-internal |  | test code |

### `web/src/components/chat/SideChatPane.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 126 | return ˋomnigent.sideChatInherited:${c… | keep-internal |  | localStorage key prefix omnigent.sideChatInherit |
| 190 | …?.labels?.["omnigent.closed"] === "tru… | keep-internal |  | Server session label key omnigent.closed, compar |

### `web/src/components/chat/SideChatSettings.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 62 | "omnigent.wrapper": "devin-native-ui", | keep-internal |  | test code |
| 63 | "omnigent.side_chat": "1", | keep-internal |  | test code |
| 64 | "omnigent.side_chat.source_id": "paren… | keep-internal |  | test code |
| 152 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 195 | …ld.labels, "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 288 | labels: { "omnigent.wrapper": "cursor-… | keep-internal |  | test code |
| 314 | … === 4 ? { "omnigent.closed": "true" }… | keep-internal |  | test code |
| 328 | labels: { "omnigent.wrapper": "devin-n… | keep-internal |  | test code |
| 353 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 376 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 498 | …labels : { "omnigent.wrapper": "devin-… | keep-internal |  | test code |
| 537 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 538 | … labels: { "omnigent.codex_native.agen… | keep-internal |  | test code |
| 552 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 568 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 597 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 676 | "omnigent.wrapper": "codex-native-ui-s… | keep-internal |  | test code |
| 677 | "omnigent.codex_native.agent_nickname"… | keep-internal |  | test code |
| 700 | "omnigent.wrapper": "codex-native-ui-s… | keep-internal |  | test code |
| 701 | "omnigent.codex_native.agent_nickname"… | keep-internal |  | test code |

### `web/src/components/chat/SideChatSettings.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 56 | …n.labels?.["omnigent.codex_native.agen… | keep-internal |  | Server session label key omnigent.codex_native.a |
| 61 | …n.labels?.["omnigent.wrapper"] === "co… | keep-internal |  | Server session label key omnigent.wrapper, compa |
| 104 | …on.labels, "omnigent.wrapper": "codex-… | keep-internal |  | Session label key omnigent.wrapper, set for the |
| 154 | …n.labels?.["omnigent.closed"] === "tru… | keep-internal |  | Server session label key omnigent.closed, compar |

### `web/src/components/chat/chatBubbleParts.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 820 | …ntListener("omnigent:toast", recordToa… | keep-internal |  | test code |
| 835 | …ntListener("omnigent:toast", recordToa… | keep-internal |  | test code |

### `web/src/components/chat/chatBubbleParts.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2398 | …t, so add --omnigent-inset-top (0px of… | keep-internal |  | code comment |
| 2399 | …0px + var(--omnigent-inset-top))" }} | keep-internal |  | CSS custom property --omnigent-inset-top. |

### `web/src/components/composer/ComposerConfigSections.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 241 | { id: "omnigent-openai/system.ai.glm-5… | keep-internal |  | test code |
| 242 | { id: "omnigent/databricks-kimi-k2-7-c… | keep-internal |  | test code |
| 305 | …D_CATALOG, "omnigent/databricks-kimi-k… | keep-internal |  | test code |
| 335 | …CalledWith("omnigent-openai/system.ai.… | keep-internal |  | test code |

### `web/src/components/composer/ComposerWorkspaceStatus.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …ev/projects/omnigent", | keep-internal |  | test code |
| 38 | …ev/projects/omnigent", | keep-internal |  | test code |
| 39 | …ev/projects/omnigent-worktrees/compose… | keep-internal |  | test code |

### `web/src/components/icons/DatabricksIcon.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | // Databricks brand mark, drawn in cur… | keep-internal |  | code comment |
| 5 | …uted by the Databricks Unity Gateway")… | keep-internal |  | code comment |
| 7 | …rt function DatabricksIcon(props: SVGP… | keep-internal |  | code identifier |

### `web/src/components/icons/OttoIcon.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 53 | …aria-label="Omnigent" aria-hidden={fal… | keep-internal |  | test code |
| 58 | …ia-label", "Omnigent"); | keep-internal |  | test code |

### `web/src/components/onboarding/AnimatedOmnigentPanel.css`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | .omnigent-card { | keep-internal |  | code identifier |
| 18 | --omnigent-resize: 0.5s cubic-bezier(0… | keep-internal |  | code identifier |
| 20 | width var(--omnigent-resize), | keep-internal |  | code identifier |
| 21 | height var(--omnigent-resize); | keep-internal |  | code identifier |
| 25 | .dark .omnigent-card { | keep-internal |  | code identifier |
| 29 | .omnigent-animated-panel { | keep-internal |  | code identifier |
| 38 | …eight var(--omnigent-resize); | keep-internal |  | code identifier |
| 41 | .omnigent-panel-logo { | keep-internal |  | CSS class name .omnigent-panel-logo. |
| 58 | .omnigent-panel-band-content { | keep-internal |  | code identifier |
| 70 | .omnigent-panel-logo--centered { | keep-internal |  | CSS class name .omnigent-panel-logo--centered. |
| 75 | .omnigent-card--auto { | keep-internal |  | code identifier |
| 82 | .omnigent-card--auto .omnigent-animate… | keep-internal |  | code identifier |
| 87 | .omnigent-card--auto .omnigent-card-bo… | keep-internal |  | code identifier |
| 94 | .omnigent-card-body { | keep-internal |  | code identifier |
| 102 | .omnigent-card-body > * { | keep-internal |  | code identifier |
| 103 | animation: omnigent-step-in 0.2s ease-… | keep-internal |  | code identifier |
| 106 | @keyframes omnigent-step-in { | keep-internal |  | code identifier |
| 113 | .omnigent-card, | keep-internal |  | code identifier |
| 114 | .omnigent-animated-panel { | keep-internal |  | code identifier |
| 118 | .omnigent-card-body > * { | keep-internal |  | code identifier |

### `web/src/components/onboarding/AnimatedOmnigentPanel.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …see AnimatedOmnigentPanel.css) so we a… | keep-internal |  | code comment |
| 13 | import omnigentLogo from "@/assets/omnigent-starfish-icon.png"; | change-asset | S89 | Imports the Omnigent starfish icon, shown as the logo on the onboarding and auth card (ServerSelectorV2, AuthCardShell). |
| 14 | import "./AnimatedOmnigentPanel.css"; | keep-internal |  | Stylesheet import of the internal component file |
| 21 | …ace AnimatedOmnigentPanelProps { | keep-internal |  | code identifier |
| 40 | …ion AnimatedOmnigentPanel({ | keep-internal |  | code identifier |
| 48 | }: AnimatedOmnigentPanelProps) { | keep-internal |  | code identifier |
| 55 | className={ˋomnigent-card${autoHeight … | keep-internal |  | CSS class names omnigent-card / omnigent-card--a |
| 57 | aria-label="Omnigent onboarding" | change | S89 | aria-label of the onboarding card names the product. |
| 59 | … className="omnigent-animated-panel" s… | keep-internal |  | CSS class name omnigent-animated-panel. |
| 63 | … className="omnigent-panel-band-conten… | keep-internal |  | CSS class name omnigent-panel-band-content. |
| 66 | src={omnigentLogo} | change-asset | S89 | Renders the Omnigent starfish image on the onboarding card. |
| 67 | alt="Omnigent" | change | S89 | Alt text of the onboarding logo names the product. |
| 68 | className={ˋomnigent-panel-logo${cente… | keep-internal |  | CSS class names omnigent-panel-logo / --centered |
| 74 | … className="omnigent-card-body">{child… | keep-internal |  | CSS class name omnigent-card-body. |
| 79 | export default AnimatedOmnigentPanel; | keep-internal |  | code identifier |

### `web/src/components/onboarding/HostImportReview.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 35 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 110 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 325 | …ge.setItem("omnigent:imports-reviewed:… | keep-internal |  | test code |
| 345 | …ge.getItem("omnigent:imports-reviewed:… | keep-internal |  | test code |
| 424 | …ge.setItem("omnigent:imports-reviewed:… | keep-internal |  | test code |

### `web/src/components/onboarding/ImportContextModal.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 97 | ….getByText("Databricks Unity Gateway")… | keep-internal |  | test code |
| 101 | …).toEqual(["databricks-v2", "jira", "s… | keep-internal |  | test code |
| 116 | ….getByText("Databricks (dbc-a5d4177a-4… | keep-internal |  | test code |
| 189 | ….getByText("Databricks Unity Gateway")… | keep-internal |  | test code |

### `web/src/components/onboarding/ImportContextModal.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | … credential Omnigent adopted and the M… | keep-internal |  | code comment |
| 7 | import omnigentLogo from "@/assets/omnigent-starfish-icon.png"; | change-asset | S89 | Imports the Omnigent starfish icon, shown in the post-setup import modal band. |
| 38 | …ess icons → Omnigent starfish, over th… | keep-internal |  | code comment |
| 53 | <img src={omnigentLogo} alt="" className="size-8 object-contain" /> | change-asset | S89 | Renders the starfish as the harness-to-app arrow target in the import modal. |

### `web/src/components/onboarding/importContextMock.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | "deploy-omnigent-databricks", | keep-internal |  | Sample skill name in mock data used only by Stor |
| 24 | { harness: "claude", source: "Databricks Unity Gateway" }, | keep-origin |  | Mock credential source naming the Databricks Unity Gateway integration (dev/Storybook data only). |
| 25 | { harness: "codex", source: "Databricks (dbc-a5d4177a-49dc)" }, | keep-origin |  | Mock credential source naming a Databricks workspace (an integration target; dev/Storybook data only). |
| 30 | { id: "claude:databricks-v2", name: "databricks-v2", harness: "claude" }, | keep-origin |  | Mock MCP server named databricks-v2 (a third-party integration). ImportContextModal.test.tsx:101 asserts it. |

### `web/src/components/scheduled/AutomationsIntro.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | getOmnigentHostConfig, | keep-internal |  | test code |
| 11 | setOmnigentHostConfig, | keep-internal |  | test code |
| 12 | type OmnigentHostConfig, | keep-internal |  | test code |
| 46 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 52 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 158 | setOmnigentHostConfig({ serverIdentity… | keep-internal |  | test code |
| 172 | …Config = getOmnigentHostConfig(); | keep-internal |  | test code |
| 173 | …ddedConfig: OmnigentHostConfig = { fet… | keep-internal |  | test code |
| 176 | setOmnigentHostConfig(embeddedConfig); | keep-internal |  | test code |
| 187 | setOmnigentHostConfig(embeddedConfig); | keep-internal |  | test code |
| 199 | setOmnigentHostConfig(previousConfig); | keep-internal |  | test code |

### `web/src/components/scheduled/AutomationsIntro.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | import { getOmnigentHostGeneration, ge… | keep-internal |  | code identifier |
| 102 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 107 | : ˋomnigent:automations-intro:v1:${JSO… | keep-internal |  | Persisted storage key prefix omnigent:automation |
| 110 | …ringify([getOmnigentHostGeneration(), … | keep-internal |  | JS identifier getOmnigentHostGeneration used in |

### `web/src/components/scheduled/CreateScheduledTaskDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2438 | …extContent("Omnigent Automation"); | keep-internal |  | test code |
| 2441 | …CalledWith("Omnigent Automation"); | keep-internal |  | test code |
| 2865 | … starts one Omnigent session for each … | keep-internal |  | test code |
| 3339 | …t run · Posts include "Sent with Omnigent".', | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3362 | expect(note).toHaveTextContent('Posts include "Sent with Omnigent".'); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3384 | expect(note).toHaveTextContent("Sent with Omnigent"); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3458 | …-0-value", "omnigent"); | keep-internal |  | test code |
| 3477 | …-0-value", "omnigent"); | keep-internal |  | test code |
| 3498 | …D labels = "omnigent" AND issuetype !=… | keep-internal |  | test code |
| 3502 | 'Comment "Omnigent session: https://host.example.com/embed#/c/CONVERSATION_ID?o=42" on each ticket', | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3557 | expect(prompt).not.toContain("Omnigent session:"); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 3621 | 'Comment "Omnigent session: https://omni.example.com/c/CONVERSATION_ID" on each issue', | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/components/scheduled/CreateScheduledTaskDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 96 | const DEFAULT_AUTOMATION_PROJECT = "Omnigent Automation"; | keep-deferred |  | DEFAULT_AUTOMATION_PROJECT is resolved by project name (existing projects match 'Omnigent Automation'); deferred by rule. |

### `web/src/components/scheduled/ScheduledTaskRow.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 205 | … starts one Omnigent session", | keep-internal |  | test code |

### `web/src/components/scheduled/ScheduledTaskRow.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 254 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/scheduled/TriggerTemplateFields.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | OMNIGENT_ATTRIBUTION, | keep-internal |  | code identifier |
| 383 | {OMNIGENT_ATTRIBUTION}&quot;. | keep-internal |  | code identifier |

### `web/src/components/scheduled/triggerTemplates.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 32 | const LABEL_OMNIGENT: TriggerCondition… | keep-internal |  | test code |
| 34 | … ES labeled omnigent, unless overridde… | keep-internal |  | test code |
| 39 | conditions: [LABEL_OMNIGENT], | keep-internal |  | test code |
| 46 | …D labels = "omnigent"'; | keep-internal |  | test code |
| 161 | ? posting.replace("Sent with Omnigent", "Automated reply") | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 186 | … "Sent with Omnigent", since it posts … | keep-internal |  | test code |
| 188 | … "Sent with Omnigent", since it posts … | keep-internal |  | test code |
| 237 | …[{ ...LABEL_OMNIGENT, value: " " }] },… | keep-internal |  | test code |
| 384 | …s", value: "omnigent" }, | keep-internal |  | test code |
| 390 | …D labels = "omnigent" AND issuetype !=… | keep-internal |  | test code |
| 551 | "starts one Omnigent session for each … | keep-internal |  | test code |
| 567 | 'Comment "Omnigent session: https://omni.example.com/c/CONVERSATION_ID" on each ticket', | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 598 | expect(manager).not.toContain('Reply "Omnigent session:'); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 616 | … each one with a line "Sent with Omnigent", since it posts with the owner\'s account.', | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 620 | …est, ends with a line "Sent with Omnigent", since it posts with the owner\'s account.', | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 638 | expect(noLink).toContain('ends with a line "Sent with Omnigent"'); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 743 | expect(prompt).not.toContain("Omnigent session:"); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 802 | … starts one Omnigent session for each … | keep-internal |  | test code |
| 818 | 'Comment "Omnigent session: https://omni.example.com/c/CONVERSATION_ID" on each issue you started a … | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 878 | "starts one Omnigent session for each … | keep-internal |  | test code |

### `web/src/components/scheduled/triggerTemplates.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 64 | …g. ˋhttps://omnigent.example.com/c/CON… | keep-internal |  | code comment |
| 149 | { id: "label", label: "Label", operators: ["is", "is_not"], placeholder: "omnigent" }, | change | S89 | Jira Label input placeholder shows the product name "omnigent" as the example label value in the trigger builder UI. |
| 399 | export const OMNIGENT_ATTRIBUTION = "Sent with Omnigent"; | change | S89 | Attribution line agents append to posts and the form shows (TriggerTemplateFields.tsx:383); product name in user-visible text. |
| 403 | …h a line "${OMNIGENT_ATTRIBUTION}", si… | keep-internal |  | The hit is only the JS identifier OMNIGENT_ATTRI |
| 548 | return ˋThis automation watches ${triggerServiceName(source)} and starts one Omnigent sessionˋ; | keep-deferred |  | Persisted prompt opening, matched by prefix in the server's fire.py; the needed server change is outside the rebrand seams. Deferred to the |
| 983 | text.linkBack(ˋOmnigent session: ${ctx.sessionLink}ˋ) + | change | S89 | Link-back text that agents post on tickets and that the Preview prompt shows. Uses Omnigent as the product name. |
| 984 | …h a line "${OMNIGENT_ATTRIBUTION}", si… | keep-internal |  | The hit is only the JS identifier OMNIGENT_ATTRI |

### `web/src/components/theme/CardRadioGroup.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 32 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/theme/IconSegmentedControl.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 28 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/button.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 22 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 216 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 234 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/components/ui/button.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 93 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/checkbox.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 18 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/dialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …rd-aware ˋ--omnigent-viewport-heightˋ … | keep-internal |  | test code |
| 14 | …, unknown>).omnigentNative = { kind: "… | keep-internal |  | test code |
| 16 | …, unknown>).omnigentNative; | keep-internal |  | test code |
| 41 | …oContain("--omnigent-viewport-height")… | keep-internal |  | test code |
| 42 | …oContain("--omnigent-viewport-height")… | keep-internal |  | test code |

### `web/src/components/ui/dialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 63 | …eight as ˋ--omnigent-viewport-heightˋ … | keep-internal |  | code comment |
| 70 | …"calc(var(--omnigent-viewport-height, … | keep-internal |  | CSS custom property --omnigent-viewport-height. |
| 74 | "calc(var(--omnigent-viewport-height, … | keep-internal |  | CSS custom properties --omnigent-viewport-height |

### `web/src/components/ui/input.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 15 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/select.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 9 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 38 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 53 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 66 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/components/ui/select.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 24 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/switch.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 9 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 15 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 37 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/components/ui/switch.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 19 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/tabs.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 9 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 28 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 48 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/components/ui/tabs.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 20 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/textarea.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 9 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 15 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 31 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/components/ui/textarea.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 17 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/components/ui/toast.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …ustomEvent("omnigent:toast", { detail:… | keep-internal |  | Custom DOM event name "omnigent:toast". |

### `web/src/embed.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | import { OmnigentApp } from "./embed"; | keep-internal |  | test code |
| 83 | …stubGlobal("omnigentDesktop", electron… | keep-internal |  | test code |
| 86 | <OmnigentApp fetcher={fetcher} /> | keep-internal |  | test code |
| 89 | …ySelector(".omnigent-app")!; | keep-internal |  | test code |
| 145 | <OmnigentApp fetcher={fetcher} isDarkM… | keep-internal |  | test code |
| 159 | <OmnigentApp fetcher={fetcher} isDarkM… | keep-internal |  | test code |
| 205 | …stubGlobal("omnigentDesktop", { kind: … | keep-internal |  | test code |
| 245 | …stubGlobal("omnigentNative", kind === … | keep-internal |  | test code |
| 246 | …stubGlobal("omnigentDesktop", kind ===… | keep-internal |  | test code |
| 249 | <OmnigentApp fetcher={fetcher} /> | keep-internal |  | test code |

### `web/src/embed.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | // Exposes ˋOmnigentAppˋ — a plain Rea… | keep-internal |  | code comment |
| 7 | …t (e.g. the Databricks monolith) | keep-internal |  | code comment |
| 15 | …ment with ˋ.omnigent-appˋ so the scope… | keep-internal |  | code comment |
| 41 | type OmnigentHostConfig, | keep-internal |  | code identifier |
| 44 | setOmnigentHostConfig, | keep-internal |  | code identifier |
| 71 | …FrameProps, OmnigentHostConfig } from … | keep-internal |  | code identifier |
| 77 | export { setOmnigentHostConfig } from … | keep-internal |  | code identifier |
| 91 | …t interface OmnigentAppProps extends O… | keep-internal |  | code identifier |
| 95 | …, e.g. ˋ/ml/omnigent-embedˋ. web's rou… | keep-internal |  | code comment |
| 122 | …s its own ˋ.omnigent-appˋ scope wrappe… | keep-internal |  | code comment |
| 136 | …tly blank ˋ.omnigent-appˋ div. | keep-internal |  | code comment |
| 156 | function OmnigentProviders({ | keep-internal |  | code identifier |
| 184 | …/ not the ˋ.omnigent-appˋ scope root —… | keep-internal |  | code comment |
| 190 | …The outer ˋ.omnigent-appˋ scope root i… | keep-internal |  | code comment |
| 209 | //   - ˋ.omnigent-appˋ (outer) is the … | keep-internal |  | code comment |
| 210 | …ˋ:rootˋ → ˋ.omnigent-appˋ (light token… | keep-internal |  | code comment |
| 211 | //     ˋ.omnigent-app .darkˋ, so the d… | keep-internal |  | code comment |
| 221 | className="omnigent-app" | keep-internal |  | CSS class name omnigent-app. |
| 256 | * The Omnigent app for the SAME-ROOT p… | keep-internal |  | code comment |
| 267 | export function OmnigentApp({ | keep-internal |  | code identifier |
| 273 | }: OmnigentAppProps = {}) { | keep-internal |  | code identifier |
| 277 | …d (see ˋloadOmnigentAppˋ); this is a | keep-internal |  | code comment |
| 280 | setOmnigentHostConfig(hostConfig); | keep-internal |  | code identifier |
| 296 | …ct-query); ˋOmnigentProvidersˋ | keep-internal |  | code comment |
| 303 | <OmnigentProviders | keep-internal |  | code identifier |

### `web/src/extensions/rpc/host.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 81 | …lobalThis.__OMNIGENT_EXTENSION__=${ser… | keep-internal |  | globalThis.__OMNIGENT_EXTENSION__ global, read b |

### `web/src/extensions/rpc/protocol.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …C_SOURCE = "omnigent-extension"; | keep-internal |  | Extension RPC source tag "omnigent-extension", w |

### `web/src/extensions/services/storage.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 34 | …ge.setItem("omnigent:theme", "dark"); | keep-internal |  | test code |
| 39 | …ge.getItem("omnigent:theme")).toBe("da… | keep-internal |  | test code |
| 78 | …ge.setItem("omnigent:after-extension-q… | keep-internal |  | test code |
| 79 | …ge.getItem("omnigent:after-extension-q… | keep-internal |  | test code |

### `web/src/extensions/services/storage.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …DATABASE = "omnigent-extensions"; | keep-internal |  | IndexedDB database name omnigent-extensions. Sto |

### `web/src/extensions/services/useExtensionHostServices.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 24 | …() => ({ getOmnigentServerIdentity: ()… | keep-internal |  | test code |

### `web/src/extensions/services/useExtensionHostServices.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 57 | ….resolve(getOmnigentServerIdentity()), | keep-internal |  | code identifier |

### `web/src/grid/GridSessionPane.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 293 | …labels = { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 349 | …labels = { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 416 | …labels = { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 486 | …ge.setItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 487 | …labels = { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 509 | …labels = { "omnigent.ui": "terminal" }… | keep-internal |  | test code |

### `web/src/grid/GridSessionPane.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 126 | …?.labels?.["omnigent.wrapper"]; | keep-internal |  | Session label key omnigent.wrapper, stamped by t |
| 127 | …?.labels?.["omnigent.ui"] === "termina… | keep-internal |  | Session label key omnigent.ui, set by the server |
| 148 | …ge.getItem(ˋomnigent.web.panel-key:${s… | keep-internal |  | sessionStorage key omnigent.web.panel-key. |
| 160 | ˋomnigent.web.panel-key:${sessionId}ˋ, | keep-internal |  | sessionStorage key omnigent.web.panel-key. |

### `web/src/grid/GridSessionsContext.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | …() => ({ getOmnigentServerIdentity: ()… | keep-internal |  | test code |
| 102 | …onst key = "omnigent:session-grids:one… | keep-internal |  | test code |
| 156 | key: "omnigent:session-grids:one:alice… | keep-internal |  | test code |
| 160 | …CalledWith("omnigent:session-grids:one… | keep-internal |  | test code |
| 180 | …onst key = "omnigent:session-grids:one… | keep-internal |  | test code |
| 239 | …onst key = "omnigent:session-grids:one… | keep-internal |  | test code |

### `web/src/grid/GridSessionsContext.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 73 | : ˋomnigent:session-grids:${getOmnigen… | keep-internal |  | Storage key omnigent:session-grids and the JS id |

### `web/src/hooks/SessionUpdatesProvider.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1168 | …" ? {} : { "omnigent.pinned": "123" }, | keep-internal |  | test code |
| 1186 | labels: { "omnigent.pinned": "456" }, | keep-internal |  | test code |
| 1197 | labels: { "omnigent.pinned": kind === … | keep-internal |  | test code |

### `web/src/hooks/SessionUpdatesProvider.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 173 | ["omnigent.pinned"]: row.labels["omnig… | keep-internal |  | Session label key omnigent.pinned, an API data f |
| 178 | …row.labels["omnigent.pinned"] != null)… | keep-internal |  | Session label key omnigent.pinned, an API data f |
| 311 | // its ˋ?omnigent_slice_key=ˋ off that… | keep-internal |  | code comment |

### `web/src/hooks/useActiveConversationId.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | … "/embedded/omnigent"])("useActiveConv… | keep-internal |  | test code |

### `web/src/hooks/useAgents.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 117 | …created by ˋomnigent run --serverˋ whi… | keep-internal |  | code comment |

### `web/src/hooks/useArcaShutdownBanner.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 67 | …ge.setItem("omnigent:arca-shutdown:opt… | keep-internal |  | test code |

### `web/src/hooks/useAutomationInbox.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 39 | setOmnigentHostConfig({ serverIdentity… | keep-internal |  | test code |
| 45 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 88 | …ackend") setOmnigentHostConfig({ serve… | keep-internal |  | test code |

### `web/src/hooks/useAutomationInbox.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { getOmnigentHostGeneration, ge… | keep-internal |  | code identifier |
| 14 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 16 | …ˋmount:${getOmnigentHostGeneration()}ˋ… | keep-internal |  | JS identifier getOmnigentHostGeneration in an in |

### `web/src/hooks/useAvailableAgents.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 338 | name: "databricks_coding_agent", | keep-internal |  | test code |
| 423 | name: "databricks_coding_agent", | keep-internal |  | test code |
| 424 | …play_name: "Databricks_coding_agent", | keep-internal |  | test code |
| 439 | … Seeded via OMNIGENT_BUILTIN_AGENT_DIR… | keep-internal |  | test code |
| 441 | …tered with ˋomnigent server --agentˋ (… | keep-internal |  | test code |
| 827 | // (e.g. ˋomnigent server --agentˋ, bu… | keep-internal |  | test code |
| 853 | … The newer ˋomnigent runˋ upload: dist… | keep-internal |  | test code |
| 1407 | …d polly via OMNIGENT_SEEDED_AGENTS aft… | keep-internal |  | test code |
| 1558 | … a row per ˋomnigent run --harness cod… | keep-internal |  | test code |

### `web/src/hooks/useAvailableAgents.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 33 | …same-named ˋomnigent runˋ upload, but … | keep-internal |  | code comment |
| 146 | …trimmed via OMNIGENT_SEEDED_AGENTS. | keep-internal |  | code comment |
| 204 | * ˋomnigent agent addˋ or uploaded). F… | keep-internal |  | code comment |

### `web/src/hooks/useBrowserAgentRelay.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 60 | …l a ˋwindow.omnigentDesktopˋ bridge; r… | keep-internal |  | test code |
| 72 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 129 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 754 | …sters), but omnigentDesktop is | keep-internal |  | test code |
| 756 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |

### `web/src/hooks/useBrowserAgentRelay.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | … to ˋwindow.omnigentDesktop.browser*ˋ … | keep-internal |  | code comment |
| 27 | … of ˋwindow.omnigentDesktopˋ the relay… | keep-internal |  | code comment |
| 79 | …nknown as { omnigentDesktop?: BrowserD… | keep-internal |  | code identifier |
| 80 | return w.omnigentDesktop ?? null; | keep-internal |  | code identifier |

### `web/src/hooks/useBrowserTabs.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 31 | …ty(window, "omnigentDesktop"); | keep-internal |  | test code |
| 70 | omnigentDesktop: page ? { browserHasVi… | keep-internal |  | test code |
| 88 | omnigentDesktop: { browserHasView, onB… | keep-internal |  | test code |
| 133 | omnigentDesktop: { | keep-internal |  | test code |
| 192 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 212 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 270 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 288 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 321 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 368 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 406 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 436 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 463 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 489 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 505 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 520 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 537 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 561 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 577 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 616 | omnigentDesktop: { kind: "electron", b… | keep-internal |  | test code |
| 655 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 677 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 712 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |
| 740 | omnigentDesktop: { | keep-internal |  | test code |
| 768 | …n(window, { omnigentDesktop: { browser… | keep-internal |  | test code |

### `web/src/hooks/useBrowserTabs.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 125 | …nknown as { omnigentDesktop?: BrowserT… | keep-internal |  | code identifier |
| 228 | …nknown as { omnigentDesktop?: BrowserT… | keep-internal |  | code identifier |
| 255 | …nknown as { omnigentDesktop?: BrowserT… | keep-internal |  | code identifier |
| 288 | …nknown as { omnigentDesktop?: BrowserT… | keep-internal |  | code identifier |
| 311 | omnigentDesktop?: { | keep-internal |  | code identifier |
| 315 | ).omnigentDesktop; | keep-internal |  | code identifier |

### `web/src/hooks/useChildSessions.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 61 | * ˋˋ"databricks-claude-sonnet-5"ˋˋ. ˋˋ… | keep-internal |  | code comment |

### `web/src/hooks/useConversationRedirect.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | … "/embedded/omnigent"])("session repla… | keep-internal |  | test code |

### `web/src/hooks/useConversations.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1062 | …ntListener("omnigent:toast", (e) => { | keep-internal |  | test code |
| 1105 | …ntListener("omnigent:toast", (e) => { | keep-internal |  | test code |
| 1571 | …ntListener("omnigent:toast", (e) => { | keep-internal |  | test code |
| 2049 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 2062 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 2132 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 2191 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 2199 | // ˋomnigent.pinnedˋ key the upgraded … | keep-internal |  | test code |
| 2308 | …s carrying ˋomnigent.pinnedˋ. | keep-internal |  | test code |
| 2343 | …== "a" ? { "omnigent.pinned": "1" } : … | keep-internal |  | test code |

### `web/src/hooks/useConversations.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 860 | …nously (the Databricks deployment list… | keep-internal |  | code comment |
| 1113 | * (the Databricks deployment lists via… | keep-internal |  | code comment |
| 1721 | …s carry no ˋomnigent.pinnedˋ | keep-internal |  | code comment |
| 1731 | …ssion (the ˋomnigent.pinnedˋ label) vi… | keep-internal |  | code comment |
| 1741 | * ˋomnigent.pinnedˋ label and reportin… | keep-internal |  | code comment |
| 2015 | …{id}ˋ (the ˋomnigent.pinnedˋ | keep-internal |  | code comment |
| 2035 | …ist a bare ˋomnigent.pinnedˋ key that … | keep-internal |  | code comment |
| 2036 | …s per-user ˋomnigent.pinned.<user>ˋ ke… | keep-internal |  | code comment |

### `web/src/hooks/useFileContent.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …g ˋwindow.__OMNIGENT_BASE_PATH__ˋ. | keep-internal |  | test code |
| 15 | const isDatabricksWorkspace = vi.fn(); | keep-internal |  | test code |
| 22 | isDatabricksWorkspace: () => isDatabri… | keep-internal |  | test code |
| 44 | isDatabricksWorkspace.mockReset(); | keep-internal |  | test code |
| 55 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |
| 60 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 61 | isDatabricksWorkspace.mockReturnValue(… | keep-internal |  | test code |
| 73 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 74 | isDatabricksWorkspace.mockReturnValue(… | keep-internal |  | test code |
| 108 | …{MEDIA_URL}&omnigent_slice_key=host_1ˋ… | keep-internal |  | test code |

### `web/src/hooks/useFileContent.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | isDatabricksWorkspace: vi.fn(() => fal… | keep-internal |  | test code |
| 26 | import { isDatabricksWorkspace } from … | keep-internal |  | test code |
| 276 | …d embed", isDatabricksWorkspace], | keep-internal |  | test code |
| 320 | vi.mocked(isDatabricksWorkspace).mockR… | keep-internal |  | test code |
| 374 | // as the Databricks Apps front door w… | keep-internal |  | test code |

### `web/src/hooks/useFileContent.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | import { isDatabricksWorkspace, resolv… | keep-internal |  | code identifier |
| 70 | …key rides ˋ?omnigent_slice_key=ˋ, as t… | keep-internal |  | code comment |
| 80 | …tId)) query.omnigent_slice_key = hostI… | keep-internal |  | code identifier |
| 177 | if (!isDatabricksWorkspace() && !isIOS… | keep-internal |  | code identifier |

### `web/src/hooks/useHarnessInventory.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 108 | …", source: "Databricks Unity Gateway" … | keep-internal |  | test code |

### `web/src/hooks/useHarnessInventory.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …y brings to Omnigent: login | keep-internal |  | code comment |
| 175 | source: gateway ? "Databricks Unity Gateway" : "Signed in", | keep-origin |  | "Databricks Unity Gateway" is the third-party Databricks inference gateway that supplies a harness credential. It is an integration-target n |
| 253 | …arries into Omnigent sessions. */ | keep-internal |  | code comment |

### `web/src/hooks/useHistoryNavigation.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | omnigentDesktop: { | keep-internal |  | test code |
| 53 | …ty(window, "omnigentDesktop"); | keep-internal |  | test code |
| 112 | …ty(window, "omnigentDesktop"); | keep-internal |  | test code |

### `web/src/hooks/useHostDbcert.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { isDatabricksWorkspace } from … | keep-internal |  | code identifier |
| 37 | …/ dbcert is Databricks-internal, so on… | keep-internal |  | code comment |
| 38 | const onDatabricks = isDatabricksWorks… | keep-internal |  | code identifier |
| 42 | enabled: onDatabricks && Boolean(conve… | keep-internal |  | code identifier |
| 46 | onDatabricks && conversationId && host… | keep-internal |  | code identifier |
| 113 | features?.databricksInternalFeatures =… | keep-internal |  | code identifier |

### `web/src/hooks/useHosts.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 301 | …abel them ("Databricks Sandbox"); the … | keep-internal |  | test code |
| 607 | …n(host, "getOmnigentServerIdentity").m… | keep-internal |  | test code |

### `web/src/hooks/useHosts.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 159 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |

### `web/src/hooks/useIOSKeyboardLayout.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …HT_VAR = "--omnigent-viewport-height"; | keep-internal |  | test code |
| 41 | vi.stubGlobal("omnigentNative", { | keep-internal |  | test code |
| 108 | …stubGlobal("omnigentNative", { kind: "… | keep-internal |  | test code |
| 123 | …stubGlobal("omnigentNative", { kind: "… | keep-internal |  | test code |
| 169 | …stubGlobal("omnigentNative", kind ? { … | keep-internal |  | test code |

### `web/src/hooks/useIOSViewportLock.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 33 | "--omnigent-viewport-height", | keep-internal |  | CSS custom property --omnigent-viewport-height. |
| 62 | …Property("--omnigent-viewport-height")… | keep-internal |  | CSS custom property --omnigent-viewport-height. |

### `web/src/hooks/useIdleNotifications.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 180 | tag: "omnigent:session:a", | keep-internal |  | test code |
| 309 | tag: "omnigent:session:a", | keep-internal |  | test code |

### `web/src/hooks/useIdleNotifications.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 435 | tag: ˋomnigent:session:${conversation.… | keep-internal |  | Notification dedupe tag omnigent:session:<id>. I |

### `web/src/hooks/useNativeServerSwitcher.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 110 | …, unknown>).omnigentNative = { | keep-internal |  | test code |
| 126 | …, unknown>).omnigentNative; | keep-internal |  | test code |

### `web/src/hooks/usePromptHistory.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …E_PREFIX = "omnigent:prompt-history"; | keep-internal |  | test code |

### `web/src/hooks/usePromptHistory.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | … against ~/.omnigent_history). Web-sid… | keep-internal |  | code comment |
| 16 | …E_PREFIX = "omnigent:prompt-history"; | keep-internal |  | localStorage key prefix omnigent:prompt-history. |
| 25 | …ey, e.g. ˋˋ"omnigent:prompt-history:co… | keep-internal |  | code comment |

### `web/src/hooks/useRecentHarnesses.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …onst KEY = "omnigent:recent-harnesses"… | keep-internal |  | test code |

### `web/src/hooks/useRecentHarnesses.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …RAGE_KEY = "omnigent:recent-harnesses"… | keep-internal |  | localStorage key omnigent:recent-harnesses. |

### `web/src/hooks/useRecentWorkspaces.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …CENT_KEY = "omnigent:recent-workspaces… | keep-internal |  | test code |

### `web/src/hooks/useRecentWorkspaces.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …RAGE_KEY = "omnigent:recent-workspaces… | keep-internal |  | localStorage key omnigent:recent-workspaces. |

### `web/src/hooks/useSandboxModelOptions.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 56 | …n(host, "getOmnigentServerIdentity").m… | keep-internal |  | test code |

### `web/src/hooks/useSandboxModelOptions.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 36 | getOmnigentServerIdentity(), | keep-internal |  | code identifier |

### `web/src/hooks/useSeenAutomationFailures.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | …ge.getItem("omnigent:seen-automation-f… | keep-internal |  | test code |
| 31 | …onst key = "omnigent:seen-automation-f… | keep-internal |  | test code |
| 46 | …ge.setItem("omnigent:seen-automation-f… | keep-internal |  | test code |

### `web/src/hooks/useSeenAutomationFailures.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 60 | …onst key = ˋomnigent:seen-automation-f… | keep-internal |  | localStorage key omnigent:seen-automation-failur |

### `web/src/hooks/useSeenComments.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:seen-comment-ids"… | keep-internal |  | test code |

### `web/src/hooks/useSeenComments.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 19 | …RAGE_KEY = "omnigent:seen-comment-ids"… | keep-internal |  | localStorage key omnigent:seen-comment-ids. |

### `web/src/hooks/useSession.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 216 | labels: { "omnigent.side_chat": "1", "… | keep-internal |  | test code |
| 220 | labels: { "omnigent.side_chat": "1", "… | keep-internal |  | test code |
| 238 | "omnigent.side_chat": "1", | keep-internal |  | test code |
| 239 | "omnigent.side_chat.source_id": "routi… | keep-internal |  | test code |
| 240 | "omnigent.fork.source_id": "workspace_… | keep-internal |  | test code |

### `web/src/hooks/useSessionActionRestrictions.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 92 | …arclet", { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 94 | …akebox", { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 107 | labels: { "omnigent.host_type": "manag… | keep-internal |  | test code |
| 127 | …(session({ "omnigent.host_type": "mana… | keep-internal |  | test code |
| 179 | …anaged ? { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 204 | …anaged ? { "omnigent.host_type": "mana… | keep-internal |  | test code |

### `web/src/hooks/useSessionLiveness.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 52 | * ˋomnigent.import.sourceˋ label). An … | keep-internal |  | code comment |
| 61 | …ABEL_KEY = "omnigent.import.source"; | keep-internal |  | Session label key omnigent.import.source, mirror |

### `web/src/hooks/useSessionModelLabel.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | import { getOmnigentServerIdentity } f… | keep-internal |  | test code |
| 14 | …() => ({ getOmnigentServerIdentity: vi… | keep-internal |  | test code |
| 60 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 232 | …i-native", "omnigent-openai/system.ai.… | keep-internal |  | test code |
| 248 | …-6-astra", "omnigent-openai/system.ai.… | keep-internal |  | test code |
| 263 | …reported = "omnigent-openai/system.ai.… | keep-internal |  | test code |
| 368 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |

### `web/src/hooks/useSidebarData.policy.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 493 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 529 | …ge.getItem("omnigent:sidebar-view")!).… | keep-internal |  | test code |
| 683 | …ge.getItem("omnigent:sidebar-view")!).… | keep-internal |  | test code |

### `web/src/hooks/useSidebarToggleHotkeys.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 204 | …stubGlobal("omnigentDesktop", { kind: … | keep-internal |  | test code |

### `web/src/hooks/useSuppressBrowserView.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …l a ˋwindow.omnigentDesktopˋ with a sp… | keep-internal |  | test code |
| 9 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 14 | …nknown as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 41 | …/ No window.omnigentDesktop installed … | keep-internal |  | test code |

### `web/src/hooks/useSuppressBrowserView.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | …off ˋwindow.omnigentDesktopˋ (the same… | keep-internal |  | code comment |
| 25 | omnigentDesktop?: { browserSetSuppress… | keep-internal |  | code identifier |
| 27 | return w.omnigentDesktop?.browserSetSu… | keep-internal |  | code identifier |

### `web/src/hooks/useTerminals.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 46 | …he embedded Omnigent REPL (ˋˋtuiˋˋ/ˋˋm… | keep-internal |  | code comment |

### `web/src/hooks/useUnseenConversations.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | …RAGE_KEY = "omnigent.readState.v1"; | keep-internal |  | localStorage key omnigent.readState.v1. |

### `web/src/hooks/useUserSearch.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | * ˋOmnigentHostConfig.searchUsersˋ (se… | keep-internal |  | code comment |
| 13 | import { getOmnigentUserSearch, type U… | keep-internal |  | code identifier |
| 25 | …hUsers = getOmnigentUserSearch(); | keep-internal |  | code identifier |
| 38 | queryKey: ["omnigentUserSearch", trimm… | keep-internal |  | React Query cache key omnigentUserSearch. Intern |

### `web/src/hooks/useWorkspaceChangedFiles.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 865 | // The Databricks Apps front door retu… | keep-internal |  | test code |
| 1721 | …roxies (the Databricks Apps | keep-internal |  | test code |

### `web/src/hooks/useWorkspaceChangedFiles.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 500 | …oxies — the Databricks Apps | keep-internal |  | code comment |

### `web/src/index.css`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 205 | *      ˋ--omnigent-android-safe-area-*… | keep-internal |  | code comment |
| 217 | …atHeader, --omnigent-header-height) an… | keep-internal |  | code comment |
| 221 | --omnigent-header-height: 3.5rem; /* D… | keep-internal |  | code identifier |
| 222 | --omnigent-safe-top: max( | keep-internal |  | code identifier |
| 224 | var(--omnigent-android-safe-area-top, … | keep-internal |  | code identifier |
| 226 | --omnigent-safe-bottom: max( | keep-internal |  | CSS custom property --omnigent-safe-bottom. |
| 228 | var(--omnigent-android-safe-area-botto… | keep-internal |  | CSS custom property --omnigent-android-safe-area |
| 230 | --omnigent-safe-left: max( | keep-internal |  | code identifier |
| 232 | var(--omnigent-android-safe-area-left,… | keep-internal |  | code identifier |
| 234 | --omnigent-safe-right: max( | keep-internal |  | code identifier |
| 236 | var(--omnigent-android-safe-area-right… | keep-internal |  | code identifier |
| 238 | --omnigent-native-top-bar: 0px; /* set… | keep-internal |  | code identifier |
| 239 | --omnigent-native-bottom-bar: 0px; /* … | keep-internal |  | CSS custom property --omnigent-native-bottom-bar |
| 240 | --omnigent-top-bar-visible: 0; /* web-… | keep-internal |  | code identifier |
| 241 | --omnigent-bottom-bar-visible: 0; /* w… | keep-internal |  | CSS custom property --omnigent-bottom-bar-visibl |
| 245 | --omnigent-android-switcher-margin: 8p… | keep-internal |  | code identifier |
| 246 | --omnigent-android-switcher-height: 25… | keep-internal |  | code identifier |
| 247 | --omnigent-inset-top: var(--omnigent-s… | keep-internal |  | code identifier |
| 248 | --omnigent-inset-bottom: calc( | keep-internal |  | CSS custom property --omnigent-inset-bottom. |
| 249 | var(--omnigent-safe-bottom) + var(--om… | keep-internal |  | CSS custom properties --omnigent-safe-bottom and |
| 250 | var(--omnigent-bottom-bar-visible) | keep-internal |  | CSS custom property --omnigent-bottom-bar-visibl |
| 1020 | …l("./assets/omnigent-center-glow.svg")… | keep-internal |  | omnigent-center-glow.svg is a plain white radial |
| 1026 | .dark .omnigent-native-sidebar-surface… | keep-internal |  | code identifier |
| 1027 | .dark .omnigent-sidebar-panel { | keep-internal |  | code identifier |
| 1103 | …64px, var(--omnigent-safe-top)), | keep-internal |  | code identifier |
| 1104 | …64px, var(--omnigent-safe-bottom))), | keep-internal |  | CSS custom property --omnigent-safe-bottom. |
| 1262 | …s onto the .omnigent-app scope root. *… | keep-internal |  | code comment |
| 1264 | …8px / var(--omnigent-electron-zoom, 1)… | keep-internal |  | code identifier |
| 1265 | …8px / var(--omnigent-electron-zoom, 1)… | keep-internal |  | code identifier |
| 1450 | …ight: var(--omnigent-viewport-height, … | keep-internal |  | code identifier |
| 1452 | …ight: var(--omnigent-viewport-height, … | keep-internal |  | code identifier |
| 1454 | …ight: var(--omnigent-viewport-height, … | keep-internal |  | code identifier |
| 1462 | … calc(var(--omnigent-safe-top) - var(-… | keep-internal |  | code identifier |
| 1465 | … calc(var(--omnigent-header-height) + … | keep-internal |  | code identifier |
| 1487 | height: var(--omnigent-header-height); | keep-internal |  | code identifier |
| 1491 | …ight: var(--omnigent-header-height); | keep-internal |  | code identifier |
| 1499 | … calc(var(--omnigent-safe-top) - 0.5re… | keep-internal |  | code identifier |
| 1506 | --omnigent-header-top-overlap: 0.5rem; | keep-internal |  | code identifier |
| 1552 | … calc(var(--omnigent-header-height) + … | keep-internal |  | code identifier |
| 1562 | …rem + var(--omnigent-inset-top)); | keep-internal |  | code identifier |
| 1568 | …8px + var(--omnigent-inset-top)), | keep-internal |  | code identifier |
| 1569 | …0px + var(--omnigent-inset-top)), | keep-internal |  | code identifier |
| 1575 | …8px + var(--omnigent-inset-top)), | keep-internal |  | code identifier |
| 1576 | …0px + var(--omnigent-inset-top)), | keep-internal |  | code identifier |
| 1583 | …8px + var(--omnigent-inset-top)); | keep-internal |  | code identifier |
| 1591 | var(--omnigent-safe-top) + var(--omnig… | keep-internal |  | code identifier |
| 1592 | var(--omnigent-android-switcher-height… | keep-internal |  | code identifier |
| 1612 | …16px, var(--omnigent-safe-bottom)); | keep-internal |  | CSS custom property --omnigent-safe-bottom. |
| 1631 | * --omnigent-reserved-width) — without… | keep-internal |  | code comment |
| 1632 | --omnigent-lateral-inset-cap: calc(var… | keep-internal |  | code identifier |
| 1633 | padding-top: var(--omnigent-safe-top); | keep-internal |  | code identifier |
| 1634 | …ttom: var(--omnigent-safe-bottom); | keep-internal |  | CSS custom property --omnigent-safe-bottom. |
| 1635 | …: min(var(--omnigent-safe-left), var(-… | keep-internal |  | code identifier |
| 1636 | …: min(var(--omnigent-safe-right), var(… | keep-internal |  | code identifier |
| 1649 | … calc(var(--omnigent-safe-top) - 0.5re… | keep-internal |  | code identifier |
| 1775 | --omnigent-header-height: 76px; | keep-internal |  | code identifier |

### `web/src/index.css.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 43 | …"src/assets/omnigent-center-glow.svg",… | keep-internal |  | test code |
| 188 | /\.dark \.omnigent-native-sidebar-surf… | keep-internal |  | test code |
| 210 | …l("./assets/omnigent-center-glow.svg")… | keep-internal |  | test code |
| 371 | …-shell", "--omnigent-viewport-height"]… | keep-internal |  | test code |
| 372 | …header", "--omnigent-safe-top"], | keep-internal |  | test code |
| 373 | …ordion", "--omnigent-safe-top"], | keep-internal |  | test code |
| 401 | …includes("--omnigent-safe-top")) | keep-internal |  | test code |
| 406 | …includes("--omnigent-safe-top"), | keep-internal |  | test code |
| 448 | …toBe("var(--omnigent-safe-top)"); | keep-internal |  | test code |
| 449 | …toBe("var(--omnigent-safe-bottom)"); | keep-internal |  | test code |
| 451 | "min(var(--omnigent-safe-left), var(--… | keep-internal |  | test code |
| 454 | "min(var(--omnigent-safe-right), var(-… | keep-internal |  | test code |
| 516 | …rtyValue("--omnigent-safe-left")).toCo… | keep-internal |  | test code |
| 517 | "--omnigent-android-safe-area-left", | keep-internal |  | test code |
| 519 | …rtyValue("--omnigent-safe-right")).toC… | keep-internal |  | test code |
| 520 | "--omnigent-android-safe-area-right", | keep-internal |  | test code |
| 626 | ….toMatch(/--omnigent-(?:inset\|native)-… | keep-internal |  | test code |
| 717 | …rtyValue("--omnigent-reserved-width"))… | keep-internal |  | test code |
| 720 | …rtyValue("--omnigent-lateral-inset-cap… | keep-internal |  | test code |
| 721 | "calc(var(--omnigent-reserved-width,10… | keep-internal |  | test code |
| 832 | /\.dark \.omnigent-native-sidebar-surf… | keep-internal |  | test code |
| 1075 | …xOf(".dark .omnigent-native-sidebar-su… | keep-internal |  | test code |
| 1111 | …ight: var(--omnigent-header-height)"); | keep-internal |  | test code |
| 1542 | …-top: var(--omnigent-safe-top)"); | keep-internal |  | test code |
| 1543 | …ttom: var(--omnigent-safe-bottom)"); | keep-internal |  | test code |

### `web/src/lib/__fixtures__/routingDecision.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 36 | model: "databricks-claude-opus-4-8", | keep-internal |  | Test fixture model id databricks-claude-opus-4-8 |
| 57 | model: "databricks-claude-opus-4-8", | keep-internal |  | Test fixture model id databricks-claude-opus-4-8 |

### `web/src/lib/accountsApi.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 15 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |

### `web/src/lib/agentBundle.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 32 | …ired by the omnigent executor. */ | keep-internal |  | code comment |
| 55 | lines.push("  type: omnigent"); | keep-internal |  | Agent config.yaml executor type value "omnigent" |

### `web/src/lib/agentLabels.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …cutor.type: omnigent — polly, debby, a… | keep-internal |  | code comment |
| 187 | * ˋˋomnigent/acp_cli_harnesses.pyˋˋ, a… | keep-internal |  | code comment |

### `web/src/lib/agentPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:last-agent-id"; | keep-internal |  | localStorage key omnigent:last-agent-id. |

### `web/src/lib/agentsApi.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …same shape ˋomnigent agent addˋ upload… | keep-internal |  | code comment |

### `web/src/lib/alwaysSteerPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 28 | …ge.setItem("omnigent:always-steer", "1… | keep-internal |  | test code |
| 31 | …ge.setItem("omnigent:always-steer", "n… | keep-internal |  | test code |
| 34 | …ge.setItem("omnigent:always-steer", "f… | keep-internal |  | test code |

### `web/src/lib/alwaysSteerPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:always-steer"; | keep-internal |  | localStorage key omnigent:always-steer. |

### `web/src/lib/analytics.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | import { setOmnigentHostConfig, type O… | keep-internal |  | test code |
| 8 | emitOmnigentAnalytics, | keep-internal |  | test code |
| 10 | useOmnigentAnalytics, | keep-internal |  | test code |
| 11 | useOmnigentPageView, | keep-internal |  | test code |
| 18 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 21 | …scribe("emitOmnigentAnalytics", () => … | keep-internal |  | test code |
| 24 | …t(() => emitOmnigentAnalytics({ type: … | keep-internal |  | test code |
| 29 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 30 | …onst event: OmnigentAnalyticsEvent = { | keep-internal |  | test code |
| 35 | emitOmnigentAnalytics(event); | keep-internal |  | test code |
| 42 | setOmnigentHostConfig({ | keep-internal |  | test code |
| 47 | …t(() => emitOmnigentAnalytics({ type: … | keep-internal |  | test code |
| 64 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 95 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 118 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 134 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 150 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 162 | setOmnigentHostConfig({ | keep-internal |  | test code |
| 172 | …escribe("useOmnigentAnalytics", () => … | keep-internal |  | test code |
| 175 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 176 | …ok(() => useOmnigentAnalytics()); | keep-internal |  | test code |
| 197 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 198 | …ok(() => useOmnigentAnalytics()); | keep-internal |  | test code |
| 218 | …escribe("useOmnigentPageView", () => { | keep-internal |  | test code |
| 219 | // useOmnigentPageView reads useLocati… | keep-internal |  | test code |
| 230 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 231 | …ok(() => useOmnigentPageView("chat"), … | keep-internal |  | test code |
| 237 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 238 | …ok(() => useOmnigentPageView("chat"), … | keep-internal |  | test code |
| 245 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 251 | useOmnigentPageView("chat"); | keep-internal |  | test code |

### `web/src/lib/analytics.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | * ˋOmnigentHostConfig.analyticsˋ (see … | keep-internal |  | code comment |
| 26 | emitOmnigentAnalytics, | keep-internal |  | code identifier |
| 28 | useOmnigentAnalytics, | keep-internal |  | code identifier |
| 29 | type OmnigentAnalytics, | keep-internal |  | code identifier |
| 33 | …mport { emitOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 37 | …d (e.g. ˋuseOmnigentPageView("chat")ˋ) | keep-internal |  | code comment |
| 42 | …atching the Databricks unified router,… | keep-internal |  | code comment |
| 47 | …function useOmnigentPageView(pageId: s… | keep-internal |  | code identifier |
| 56 | emitOmnigentAnalytics({ type: "page_vi… | keep-internal |  | code identifier |

### `web/src/lib/analyticsEmit.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | * ˋuseOmnigentPageViewˋ, which imports… | keep-internal |  | code comment |
| 16 | getOmnigentAnalytics, | keep-internal |  | code identifier |
| 17 | type OmnigentAnalyticsEvent, | keep-internal |  | code identifier |
| 18 | type OmnigentComponentKind, | keep-internal |  | code identifier |
| 19 | type OmnigentInteractionKind, | keep-internal |  | code identifier |
| 20 | type OmnigentInteractionStatus, | keep-internal |  | code identifier |
| 28 | …unction emitOmnigentAnalytics(event: O… | keep-internal |  | code identifier |
| 32 | getOmnigentAnalytics()?.(event); | keep-internal |  | code identifier |
| 41 | …actionKind: OmnigentInteractionKind; | keep-internal |  | code identifier |
| 44 | status?: OmnigentInteractionStatus; | keep-internal |  | code identifier |
| 58 | emitOmnigentAnalytics({ type: "interac… | keep-internal |  | code identifier |
| 78 | …: (status?: OmnigentInteractionStatus … | keep-internal |  | code identifier |
| 99 | …actionKind: OmnigentInteractionKind, | keep-internal |  | code identifier |
| 107 | … = (status: OmnigentInteractionStatus … | keep-internal |  | code identifier |
| 133 | export interface OmnigentAnalytics { | keep-internal |  | code identifier |
| 134 | …onentKind?: OmnigentComponentKind) => … | keep-internal |  | code identifier |
| 137 | componentKind?: OmnigentComponentKind, | keep-internal |  | code identifier |
| 150 | …function useOmnigentAnalytics(): Omnig… | keep-internal |  | code identifier |
| 151 | return useMemo<OmnigentAnalytics>( | keep-internal |  | code identifier |
| 154 | emitOmnigentAnalytics({ type: "click",… | keep-internal |  | code identifier |
| 156 | emitOmnigentAnalytics({ | keep-internal |  | code identifier |

### `web/src/lib/arcaHost.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:arca-host-id"; | keep-internal |  | localStorage key omnigent:arca-host-id. |

### `web/src/lib/arcaShutdownWarning.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 28 | …StorageKey("omnigent:arca-shutdown:war… | keep-internal |  | test code |
| 29 | …StorageKey("omnigent:arca-host-id")).t… | keep-internal |  | test code |
| 31 | …StorageKey("omnigent:arca-shutdown:opt… | keep-internal |  | test code |
| 83 | …ge.setItem("omnigent:arca-shutdown:war… | keep-internal |  | test code |

### `web/src/lib/arcaShutdownWarning.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …SSED_KEY = "omnigent:arca-shutdown:dis… | keep-internal |  | localStorage key omnigent:arca-shutdown:dismisse |
| 4 | …RNED_KEY = "omnigent:arca-shutdown:war… | keep-internal |  | localStorage key omnigent:arca-shutdown:warned. |
| 5 | …_CHANGED = "omnigent:arca-shutdown:pre… | keep-internal |  | Custom DOM event name omnigent:arca-shutdown:pre |

### `web/src/lib/archiveWorktreePreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:delete-worktrees-… | keep-internal |  | localStorage key omnigent:delete-worktrees-on-ar |

### `web/src/lib/attachments.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | * omnigent/runtime/content_resolver.py… | keep-internal |  | code comment |
| 156 | // in omnigent/inner/native_attachment… | keep-internal |  | code comment |

### `web/src/lib/backgroundSessionTitlesPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …RAGE_KEY = "omnigent:background-sessio… | keep-internal |  | localStorage key omnigent:background-session-tit |
| 2 | …HEADER = "X-Omnigent-Background-Sessio… | keep-internal |  | HTTP header X-Omnigent-Background-Session-Titles |

### `web/src/lib/baseBranchPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 31 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 34 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |

### `web/src/lib/baseBranchPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …RAGE_KEY = "omnigent:default-base-bran… | keep-internal |  | localStorage key omnigent:default-base-branch. |

### `web/src/lib/basePath.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |
| 9 | window.__OMNIGENT_BASE_PATH__ = value; | keep-internal |  | test code |
| 14 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |

### `web/src/lib/basePath.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | * ˋwindow.__OMNIGENT_BASE_PATH__ˋ (see… | keep-internal |  | code comment |
| 10 | * ˋomnigent/server/app.pyˋ); this modu… | keep-internal |  | code comment |
| 24 | __OMNIGENT_BASE_PATH__?: string; | keep-internal |  | code identifier |
| 34 | … = window.__OMNIGENT_BASE_PATH__; | keep-internal |  | code identifier |

### `web/src/lib/blockStream.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1686 | …h", query: "omnigent framework" } }, | keep-internal |  | test code |
| 1697 | …web search: omnigent framework"); | keep-internal |  | test code |

### `web/src/lib/blockStream.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …thon-client/omnigent_client/_stream.py… | keep-internal |  | code comment |
| 166 | …ˋ_translate_omnigent_eventˋ. Without t… | keep-internal |  | code comment |
| 525 | // (omnigent/runtime/harnesses/_execut… | keep-internal |  | code comment |
| 529 | …designs/RUN_OMNIGENT_REPL_PARITY.md. | keep-internal |  | code comment |
| 1029 | * Mirrors ˋomnigent_client._stream.Blo… | keep-internal |  | code comment |

### `web/src/lib/blocks.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …thon-client/omnigent_client/_blocks.py… | keep-internal |  | code comment |
| 346 | …hose, e.g. ˋdatabricks-claude-opus-4-8… | keep-internal |  | code comment |

### `web/src/lib/bootCapabilities.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | databricks_features: false, | keep-internal |  | code identifier |

### `web/src/lib/branding.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | export const DEFAULT_APP_NAME = "Omnigent"; | change | S79 | Built-in default app name that useAppName() returns everywhere when no operator branding.app_name is set. |
| 36 | …"Powered by Omnigent" only when custom… | keep-internal |  | code comment |

### `web/src/lib/browserNotifications.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 155 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 170 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |

### `web/src/lib/capabilities.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | databricks_features: false, | keep-internal |  | test code |

### `web/src/lib/capabilities.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 38 | …alˋˋ is the Databricks AI-Gateway ˋˋta… | keep-internal |  | code comment |
| 95 | * (ˋˋOMNIGENT_LOCAL_SINGLE_USER=1ˋˋ). … | keep-internal |  | code comment |
| 112 | * True on Databricks/internal deployme… | keep-internal |  | code comment |
| 113 | …ent). Gates Databricks-only UI hints —… | keep-internal |  | code comment |
| 118 | databricks_features: boolean; | keep-internal |  | code identifier |
| 131 | …Sandbox" / "Databricks Sandbox"). ˋˋnu… | keep-internal |  | code comment |
| 161 | …["github", "databricks"]ˋˋ. Non-empty … | keep-internal |  | code comment |
| 182 | * Installed omnigent server version (s… | keep-internal |  | code comment |
| 194 | …he external Databricks | keep-internal |  | code comment |
| 212 | …tallˋˋ in ˋˋOMNIGENT_FEATURESˋˋ). Gate… | keep-internal |  | code comment |
| 268 | …r agents (ˋˋomnigent agent addˋˋ, | keep-internal |  | code comment |
| 416 | databricks_features: false, | keep-internal |  | code identifier |
| 551 | // proxied omnigent API; standalone ˋh… | keep-internal |  | code comment |
| 568 | databricks_features: data.databricks_f… | keep-internal |  | code identifier |
| 656 | …ˋ signal (ˋˋOMNIGENT_LOCAL_SINGLE_USER… | keep-internal |  | code comment |
| 674 | lakebox: "Databricks", | keep-origin |  | Sandbox provider display name for lakebox, which is the Databricks platform sandbox. A third-party integration-target name. |
| 682 | …andbox" or "Databricks Sandbox" when t… | keep-internal |  | code comment |

### `web/src/lib/chunkLoadRecovery.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 51 | …ge.getItem("omnigent:chunk-reload-at")… | keep-internal |  | test code |
| 86 | …ge.getItem("omnigent:chunk-reload-at")… | keep-internal |  | test code |

### `web/src/lib/chunkLoadRecovery.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …LOAD_KEY = "omnigent:chunk-reload-at"; | keep-internal |  | sessionStorage key omnigent:chunk-reload-at. |

### `web/src/lib/claudePermissionMode.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 55 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 57 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 76 | labels: { "omnigent.claude_native.perm… | keep-internal |  | test code |

### `web/src/lib/claudePermissionMode.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …ABEL_KEY = "omnigent.claude_native.per… | keep-internal |  | Session label key omnigent.claude_native.permiss |

### `web/src/lib/codeFontPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | …RAGE_KEY = "omnigent:code-font-size"; | keep-internal |  | test code |
| 23 | …RAGE_KEY = "omnigent:code-font-family"… | keep-internal |  | test code |
| 24 | …RAGE_KEY = "omnigent:code-font-weight"… | keep-internal |  | test code |

### `web/src/lib/codeFontPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | …RAGE_KEY = "omnigent:code-font-size"; | keep-internal |  | localStorage key omnigent:code-font-size; storag |
| 16 | …RAGE_KEY = "omnigent:code-font-family"… | keep-internal |  | localStorage key omnigent:code-font-family; stor |
| 17 | …RAGE_KEY = "omnigent:code-font-weight"… | keep-internal |  | localStorage key omnigent:code-font-weight; stor |

### `web/src/lib/codexApprovalMode.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 57 | labels: { "omnigent.codex_native.bypas… | keep-internal |  | test code |

### `web/src/lib/codexApprovalMode.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | …ABEL_KEY = "omnigent.codex_native.appr… | keep-internal |  | Session label key omnigent.codex_native.approval |

### `web/src/lib/codexGoalApi.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 93 | …dard nested Omnigent error envelopes",… | keep-internal |  | test code |

### `web/src/lib/codexNativeModels.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …REFIXES = ["databricks-", "system.ai."… | keep-internal |  | Model-id catalog prefix 'databricks-' used only |
| 11 | * (ˋˋdatabricks-gpt-5-6-lunaˋˋ), and C… | keep-internal |  | code comment |

### `web/src/lib/codexPlanMode.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …ABEL_KEY = "omnigent.codex_native.coll… | keep-internal |  | Session label key omnigent.codex_native.collabor |
| 8 | …?.labels?.["omnigent.wrapper"] === COD… | keep-internal |  | Reads omnigent.wrapper session label key for com |

### `web/src/lib/composerCapabilities.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 59 | …?.labels?.["omnigent.wrapper"]; | keep-internal |  | Reads omnigent.wrapper session label key; intern |
| 105 | …label, not ˋomnigent.ui === "terminal"… | keep-internal |  | code comment |

### `web/src/lib/composerContext.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 40 | "omnigent.composer_context.v1": compos… | keep-internal |  | test code |
| 44 | …omLabels({ "omnigent.composer_context.… | keep-internal |  | test code |

### `web/src/lib/composerContextAdapters.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | …ABEL_KEY = "omnigent.composer_context.… | keep-internal |  | Persisted session label key omnigent.composer_co |

### `web/src/lib/composerModelLabel.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 59 | …-6-astra", "databricks-gpt-6-astra"])( | keep-internal |  | test code |
| 80 | …-6-astra", "databricks-gpt-6-astra"])( | keep-internal |  | test code |
| 83 | const id = ˋomnigent-openai/${displayN… | keep-internal |  | test code |
| 120 | ["databricks-claude-sonnet-5", "claude… | keep-internal |  | test code |
| 153 | …ModelLabel("databricks-claude-opus-4-8… | keep-internal |  | test code |

### `web/src/lib/composerModelLabel.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 13 | …REFIXES = ["databricks-", "system.ai."… | keep-internal |  | Model-id prefix 'databricks-' stripped from tran |

### `web/src/lib/composerSendShortcutPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …RAGE_KEY = "omnigent:composer-submit-w… | keep-internal |  | localStorage key omnigent:composer-submit-with-m |

### `web/src/lib/conversationItems.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …the shape: ˋomnigent/entities/conversa… | keep-internal |  | code comment |
| 9 | // + ˋomnigent/server/routes/conversat… | keep-internal |  | code comment |
| 180 | …hose, e.g. ˋdatabricks-claude-opus-4-8… | keep-internal |  | code comment |

### `web/src/lib/customTheme.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …RAGE_KEY = "omnigent:custom-theme"; | keep-internal |  | test code |
| 139 | it("keeps Omnigent's selection tint after contrast changes", () => { | change | S82 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 159 | it("keeps Omnigent's selected-session … | keep-internal |  | test code |

### `web/src/lib/customTheme.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:custom-theme"; | keep-internal |  | localStorage key omnigent:custom-theme; storage |

### `web/src/lib/databricksIntegration.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …ent for the Databricks integration end… | keep-internal |  | code comment |
| 3 | * (ˋˋ/v1/connections/databricks/*ˋˋ). | keep-internal |  | code comment |
| 5 | …nnect their Databricks workspace so th… | keep-internal |  | code comment |
| 6 | …s reach the Databricks Unity Gateway (… | keep-internal |  | code comment |
| 15 | …connections/databricks/statusˋˋ. */ | keep-internal |  | code comment |
| 16 | …t interface DatabricksConnectionStatus… | keep-internal |  | code identifier |
| 17 | /** Whether Databricks Connect is conf… | keep-internal |  | code comment |
| 23 | …* Connected Databricks user (email), o… | keep-internal |  | code comment |
| 24 | databricks_user: string \| null; | keep-internal |  | code identifier |
| 29 | …rent user's Databricks connection stat… | keep-internal |  | code comment |
| 30 | …nction fetchDatabricksStatus(): Promis… | keep-internal |  | code identifier |
| 31 | …connections/databricks/status"); | keep-internal |  | API path /v1/connections/databricks/status for t |
| 33 | throw new Error(ˋDatabricks status failed: ${res.status}ˋ); | keep-origin |  | Error names the Databricks workspace integration (third-party service), not Coral's publisher. |
| 35 | ….json()) as DatabricksConnectionStatus… | keep-internal |  | code identifier |
| 40 | …th consent. Databricks is | keep-internal |  | code comment |
| 44 | …rt function databricksConnectUrl(works… | keep-internal |  | code identifier |
| 46 | …connections/databricks/connect?${param… | keep-internal |  | API path /v1/connections/databricks/connect for |
| 49 | …nction beginDatabricksConnect(workspac… | keep-internal |  | code identifier |
| 50 | …tion.href = databricksConnectUrl(works… | keep-internal |  | code identifier |
| 53 | …rent user's Databricks workspace. */ | keep-internal |  | code comment |
| 54 | …n disconnectDatabricks(): Promise<void… | keep-internal |  | code identifier |
| 55 | …connections/databricks/disconnect", { | keep-internal |  | API path /v1/connections/databricks/disconnect. |
| 59 | throw new Error(ˋDatabricks disconnect failed: ${res.status}ˋ); | keep-origin |  | Error names the Databricks workspace integration (third-party service). |

### `web/src/lib/desktopCommands.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 51 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 200 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 201 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |

### `web/src/lib/dictation.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …cumented in omnigent/server/routes/dic… | keep-internal |  | code comment |
| 17 | import { getOmnigentHostConfig, resolv… | keep-internal |  | code identifier |
| 23 | …d, append ˋ?omnigent_slice_key=<modal … | keep-internal |  | code comment |
| 30 | …syError} / ˋOMNIGENT_DICTATION_MAX_STR… | keep-internal |  | code comment |
| 38 | if (!getOmnigentHostConfig().fetcher) … | keep-internal |  | code identifier |
| 41 | … ? ˋ${path}?omnigent_slice_key=${encod… | keep-internal |  | Query parameter omnigent_slice_key parsed by ser |
| 102 | …IMEOUT_S in omnigent/server/dictation.… | keep-internal |  | code comment |
| 170 | …rProcessor("omnigent-pcm16-downsampler… | keep-internal |  | AudioWorklet processor registration name; intern |
| 277 | …ioContext, "omnigent-pcm16-downsampler… | keep-internal |  | AudioWorkletNode processor name matching registr |

### `web/src/lib/editorLinks.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 44 | …_provider: "databricks-arca" }, "arca.… | keep-internal |  | test code |
| 47 | { name: "omnigent-arclet-session", san… | keep-internal |  | test code |
| 48 | "arclet_omnigent-arclet-session.ssh", | keep-internal |  | test code |
| 51 | …he standard Databricks SSH target from… | keep-internal |  | test code |
| 70 | …_provider: "databricks-lakebox" }, | keep-internal |  | test code |
| 71 | …_provider: "databricks-lakebox" }, | keep-internal |  | test code |
| 132 | …stubGlobal("omnigentDesktop", { kind: … | keep-internal |  | test code |
| 145 | …stubGlobal("omnigentDesktop", undefine… | keep-internal |  | test code |

### `web/src/lib/editorLinks.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | …isioned for Databricks hosts. */ | keep-internal |  | code comment |
| 27 | …ovider === "databricks-arca") return "… | keep-internal |  | Sandbox provider id 'databricks-arca' compared a |

### `web/src/lib/events.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …thon-client/omnigent_client/_events.py… | keep-internal |  | code comment |
| 398 | …hose, e.g. ˋdatabricks-claude-opus-4-8… | keep-internal |  | code comment |
| 510 | // see ˋomnigent/server/schemas.pyˋ fo… | keep-internal |  | code comment |
| 593 | …tted by the Omnigent server when the c… | keep-internal |  | code comment |
| 608 | …tted by the Omnigent server when the c… | keep-internal |  | code comment |
| 622 | …tted by the Omnigent server after a na… | keep-internal |  | code comment |
| 701 | …tted by the Omnigent server when the c… | keep-internal |  | code comment |

### `web/src/lib/fileViewPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …RAGE_KEY = "omnigent:file-view-prefere… | keep-internal |  | test code |

### `web/src/lib/fileViewPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 28 | …RAGE_KEY = "omnigent:file-view-prefere… | keep-internal |  | localStorage key omnigent:file-view-preferences; |

### `web/src/lib/filesPanelPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …RAGE_KEY = "omnigent:files-panel-prefe… | keep-internal |  | test code |

### `web/src/lib/filesPanelPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | …RAGE_KEY = "omnigent:files-panel-prefe… | keep-internal |  | localStorage key omnigent:files-panel-preference |

### `web/src/lib/foldNarrationPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …RAGE_KEY = "omnigent:fold-assistant-na… | keep-internal |  | localStorage key omnigent:fold-assistant-narrati |

### `web/src/lib/forkHarness.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 56 | // Omnigent items, so it carries fork/… | keep-internal |  | test code |
| 93 | … the copied Omnigent items. The | keep-internal |  | test code |

### `web/src/lib/forkHarness.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …the server (omnigent/server/routes/ses… | keep-internal |  | code comment |
| 6 | … replay the Omnigent transcript as LLM | keep-internal |  | code comment |
| 10 | …     copied Omnigent items (a same-fam… | keep-internal |  | code comment |
| 58 | …ARNESSESˋ (ˋomnigent/harness_aliases.p… | keep-internal |  | code comment |
| 65 | * Omnigent items (see ˋwrite_qwen_sess… | keep-internal |  | code comment |
| 90 | … the copied Omnigent items, so they ca… | keep-internal |  | code comment |
| 92 | * (ˋomnigent/server/routes/sessions.py… | keep-internal |  | code comment |
| 116 | …ead-only to Omnigent, so a fork replay… | keep-internal |  | code comment |

### `web/src/lib/harnessPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:last-harness-by-a… | keep-internal |  | localStorage key omnigent:last-harness-by-agent; |

### `web/src/lib/harnessSetup.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 42 | …ERSIONˋ in ˋomnigent/util/tmux_compat.… | keep-internal |  | code comment |
| 67 | description: "Databricks-managed credential via the Unity Gateway", | keep-origin |  | Isaac credential copy names the Databricks Unity Gateway integration (third-party service); asserted in SettingsHarnessesSection.test.tsx. |
| 195 | *  ˋomnigent/onboarding/harness_readin… | keep-internal |  | code comment |
| 377 | … credential omnigent owns (Claude / | keep-internal |  | code comment |
| 454 | "If Omnigent still can't find tmux after you install it, quit and reopen the Omnigent app.", | change | S89 | tmux setup-step detail shown in HarnessSetupDialog names Omnigent as the app. |

### `web/src/lib/harnessVisibilityPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 32 | …ge.setItem("omnigent:hide-unconfigured… | keep-internal |  | test code |
| 35 | …ge.setItem("omnigent:hide-unconfigured… | keep-internal |  | test code |
| 38 | …ge.setItem("omnigent:hide-unconfigured… | keep-internal |  | test code |

### `web/src/lib/harnessVisibilityPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:hide-unconfigured… | keep-internal |  | localStorage key omnigent:hide-unconfigured-harn |

### `web/src/lib/host.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | setOmnigentHostConfig, | keep-internal |  | test code |
| 12 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 13 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |
| 19 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 25 | setOmnigentHostConfig({ cliServerUrlSu… | keep-internal |  | test code |
| 27 | …in}/api/2.0/omnigentˋ); | keep-internal |  | test code |
| 31 | setOmnigentHostConfig({ cliServerUrlSu… | keep-internal |  | test code |
| 36 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 37 | setOmnigentHostConfig({ cliServerUrlSu… | keep-internal |  | test code |
| 44 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 53 | …ared by ˋsetOmnigentHostConfig({})ˋ (t… | keep-internal |  | test code |
| 58 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 60 | …stFetch, setOmnigentHostConfig: setCon… | keep-internal |  | test code |
| 71 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 85 | setOmnigentHostConfig({ resolveMediaUr… | keep-internal |  | test code |
| 92 | describe("isDatabricksWorkspace", () =… | keep-internal |  | test code |
| 94 | …te (the ˋsetOmnigentHostConfigˋ | keep-internal |  | test code |
| 102 | const { isDatabricksWorkspace } = awai… | keep-internal |  | test code |
| 103 | expect(isDatabricksWorkspace()).toBe(f… | keep-internal |  | test code |
| 107 | const { isDatabricksWorkspace, setOmni… | keep-internal |  | test code |
| 109 | expect(isDatabricksWorkspace()).toBe(t… | keep-internal |  | test code |
| 112 | …space (VITE_DATABRICKS_WORKSPACE)", as… | keep-internal |  | test code |
| 114 | …server is a Databricks workspace. | keep-internal |  | test code |
| 115 | …ubEnv("VITE_DATABRICKS_WORKSPACE", "tr… | keep-internal |  | test code |
| 116 | const { isDatabricksWorkspace } = awai… | keep-internal |  | test code |
| 117 | expect(isDatabricksWorkspace()).toBe(t… | keep-internal |  | test code |
| 132 | …ut enabling Databricks behavior", asyn… | keep-internal |  | test code |
| 133 | …ubEnv("VITE_OMNIGENT_HOST_ROUTING", "t… | keep-internal |  | test code |
| 134 | …gEnabled, isDatabricksWorkspace } = aw… | keep-internal |  | test code |
| 136 | expect(isDatabricksWorkspace()).toBe(f… | keep-internal |  | test code |
| 139 | …enabled for Databricks", async () => { | keep-internal |  | test code |
| 140 | …ubEnv("VITE_DATABRICKS_WORKSPACE", "tr… | keep-internal |  | test code |

### `web/src/lib/host.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …p (e.g. the Databricks monolith), the … | keep-internal |  | code comment |
| 15 | …p until ˋsetOmnigentHostConfigˋ is cal… | keep-internal |  | code comment |
| 34 | export type OmnigentComponentKind = | keep-internal |  | code identifier |
| 50 | export type OmnigentInteractionKind = | keep-internal |  | code identifier |
| 61 | export type OmnigentInteractionStatus … | keep-internal |  | code identifier |
| 68 | …ee (see ˋuseOmnigentAnalyticsˋ in | keep-internal |  | code comment |
| 73 | export type OmnigentAnalyticsEvent = | keep-internal |  | code identifier |
| 74 | …onentKind?: OmnigentComponentKind } | keep-internal |  | code identifier |
| 78 | componentKind?: OmnigentComponentKind; | keep-internal |  | code identifier |
| 85 | * (see ˋOmnigentInteractionKindˋ). ˋin… | keep-internal |  | code comment |
| 91 | …actionKind: OmnigentInteractionKind; | keep-internal |  | code identifier |
| 93 | status?: OmnigentInteractionStatus; | keep-internal |  | code identifier |
| 110 | export interface OmnigentHostConfig { | keep-internal |  | code identifier |
| 122 | …jax-api/2.0/omnigentˋ). When omitted, … | keep-internal |  | code comment |
| 142 | …s?: (event: OmnigentAnalyticsEvent) =>… | keep-internal |  | code identifier |
| 167 | … ˋ"/api/2.0/omnigent"ˋ). When the host… | keep-internal |  | code comment |
| 168 | * Omnigent API behind a path prefix, C… | keep-internal |  | code comment |
| 169 | …ost/api/2.0/omnigentˋ) — this suffix s… | keep-internal |  | code comment |
| 190 | …own for the Databricks git-credentials… | keep-internal |  | code comment |
| 193 | databricksGitCredentials?: ReactNode; | keep-internal |  | code identifier |
| 197 | …hostConfig: OmnigentHostConfig = {}; | keep-internal |  | code identifier |
| 202 | …function getOmnigentHtmlPreviewFrame()… | keep-internal |  | code identifier |
| 206 | …function getOmnigentServerIdentity(): … | keep-internal |  | code identifier |
| 214 | …function setOmnigentHostConfig(config:… | keep-internal |  | code identifier |
| 216 | // ˋOmnigentAppˋ installs config durin… | keep-internal |  | code comment |
| 225 | …function getOmnigentHostConfig(): Omni… | keep-internal |  | code identifier |
| 229 | …function getOmnigentHostGeneration(): … | keep-internal |  | code identifier |
| 236 | …ointed at a Databricks workspace via ˋ… | keep-internal |  | code comment |
| 237 | * ˋVITE_DATABRICKS_WORKSPACE=trueˋ). N… | keep-internal |  | code comment |
| 241 | … function isDatabricksWorkspace(): boo… | keep-internal |  | code identifier |
| 242 | …ta.env.VITE_DATABRICKS_WORKSPACE === "… | keep-internal |  | code identifier |
| 247 | return isDatabricksWorkspace() \|\| impo… | keep-internal |  | code identifier |
| 254 | …function getOmnigentUserSearch(): Omni… | keep-internal |  | code identifier |
| 262 | …function getOmnigentAnalytics(): Omnig… | keep-internal |  | code identifier |
| 270 | …function getOmnigentTransformShareLink… | keep-internal |  | code identifier |
| 278 | …function getOmnigentThemeSettingsUrl()… | keep-internal |  | code identifier |
| 285 | …he scoped ˋ.omnigent-appˋ subtree and … | keep-internal |  | code comment |
| 297 | … element (ˋ.omnigent-appˋ) — the outer… | keep-internal |  | code comment |
| 301 | …he scoped ˋ.omnigent-appˋ tokens shado… | keep-internal |  | code comment |
| 366 | …onal {@link OmnigentHostConfig.cliServ… | keep-internal |  | code comment |

### `web/src/lib/hostDbcert.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …ion's host (Databricks-internal). Arca… | keep-internal |  | code comment |
| 25 | …PDIR:-/tmp}/omnigent-dbcert-refresh.lo… | keep-internal |  | Host shell command: lock-file name and dbcert -- |

### `web/src/lib/hostPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | …RAGE_KEY = "omnigent:last-host-choice"… | keep-internal |  | localStorage key omnigent:last-host-choice; stor |
| 23 | …IDER_KEY = "omnigent:last-sandbox-prov… | keep-internal |  | localStorage key omnigent:last-sandbox-provider; |

### `web/src/lib/identity.managedRouting.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …port type { OmnigentHostConfig } from … | keep-internal |  | test code |
| 5 | …vi.fn<() => OmnigentHostConfig>(); | keep-internal |  | test code |
| 7 | …CE_KEY = "X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 26 | getOmnigentHostConfig: getHostConfig, | keep-internal |  | test code |
| 28 | isDatabricksWorkspace: isWorkspace, | keep-internal |  | test code |
| 273 | …labels = { "omnigent.sandbox.requested… | keep-internal |  | test code |

### `web/src/lib/identity.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 269 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |
| 287 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 302 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 422 | getOmnigentHostConfig: vi.fn(() => ({ … | keep-internal |  | test code |
| 424 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 433 | …h(ˋ/api/2.0/omnigent/v1/skills?${query… | keep-internal |  | test code |
| 435 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 444 | …t("stamps X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 457 | getOmnigentHostConfig: vi.fn(() => ({ … | keep-internal |  | test code |
| 459 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 470 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 475 | // still a Databricks workspace (shard… | keep-internal |  | test code |
| 478 | …ubEnv("VITE_DATABRICKS_WORKSPACE", "tr… | keep-internal |  | test code |
| 490 | getOmnigentHostConfig: vi.fn(() => ({}… | keep-internal |  | test code |
| 492 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 502 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 517 | getOmnigentHostConfig: vi.fn(() => ({ … | keep-internal |  | test code |
| 519 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 544 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 548 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 560 | getOmnigentHostConfig: vi.fn(() => ({ … | keep-internal |  | test code |
| 562 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 599 | …ers).get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 620 | getOmnigentHostConfig: vi.fn(() => ({ … | keep-internal |  | test code |
| 622 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 639 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 664 | getOmnigentHostConfig: vi.fn(() => ({ … | keep-internal |  | test code |
| 666 | isDatabricksWorkspace: vi.fn(() => tru… | keep-internal |  | test code |
| 680 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 687 | …ubEnv("VITE_OMNIGENT_HOST_ROUTING", "t… | keep-internal |  | test code |
| 705 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 717 | …ers).get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 756 | …ders.get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |

### `web/src/lib/identity.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | getOmnigentHostConfig, | keep-internal |  | code identifier |
| 23 | isDatabricksWorkspace, | keep-internal |  | code identifier |
| 44 | …HEADER = "X-Databricks-Omnigent-Slice-… | keep-internal |  | Header X-Databricks-Omnigent-Slice-Key parsed by |
| 180 | getOmnigentHostConfig().fetcher != nul… | keep-internal |  | code identifier |
| 181 | (isDatabricksWorkspace() ? options.for… | keep-internal |  | code identifier |
| 205 | if (isDatabricksWorkspace()) { | keep-internal |  | code identifier |
| 607 | …stId && (!isDatabricksWorkspace() \|\| !… | keep-internal |  | code identifier |
| 630 | if (isDatabricksWorkspace() && stamped… | keep-internal |  | code identifier |
| 649 | isDatabricksWorkspace() && | keep-internal |  | code identifier |
| 672 | isDatabricksWorkspace() && | keep-internal |  | code identifier |
| 689 | !getOmnigentHostConfig().fetcher && | keep-internal |  | code identifier |

### `web/src/lib/importReviewState.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …Y_PREFIX = "omnigent:imports-reviewed:… | keep-internal |  | localStorage key prefix omnigent:imports-reviewe |

### `web/src/lib/inboxFilterPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 24 | …ge.setItem("omnigent:inbox-filter", "m… | keep-internal |  | test code |

### `web/src/lib/inboxFilterPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:inbox-filter"; | keep-internal |  | localStorage key omnigent:inbox-filter; storage |

### `web/src/lib/itemsToBlocks.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 375 | code: "databricks_sign_in_pending", | keep-internal |  | test code |
| 377 | … sign in to Databricks", | keep-internal |  | test code |
| 382 | … sign in to Databricks"); | keep-internal |  | test code |
| 736 | …h", query: "omnigent framework" }, | keep-internal |  | test code |
| 744 | …web search: omnigent framework"); | keep-internal |  | test code |

### `web/src/lib/lastAssistantText.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 193 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 200 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |

### `web/src/lib/linkOpenPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …RAGE_KEY = "omnigent:open-links-in-app… | keep-internal |  | localStorage key omnigent:open-links-in-app; sto |

### `web/src/lib/mcpPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 32 | …ge.setItem("omnigent:last-mcp-services… | keep-internal |  | test code |
| 37 | …ge.setItem("omnigent:last-mcp-services… | keep-internal |  | test code |
| 43 | "omnigent:last-mcp-services", | keep-internal |  | test code |

### `web/src/lib/mcpPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …RAGE_KEY = "omnigent:last-mcp-services… | keep-internal |  | localStorage key omnigent:last-mcp-services; sto |

### `web/src/lib/mcpRegistry.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |
| 31 | window.__OMNIGENT_BASE_PATH__ = "/omni… | keep-internal |  | test code |
| 88 | …"requires a Databricks workspace and i… | keep-internal |  | test code |
| 89 | const databricks = { ...service, auth:… | keep-internal |  | test code |
| 91 | …stryService(databricks, controller.sig… | keep-internal |  | test code |
| 96 | databricks, | keep-internal |  | test code |
| 101 | …connections/databricks/connect"); | keep-internal |  | test code |

### `web/src/lib/mcpRegistry.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | import { databricksConnectUrl } from "… | keep-internal |  | Import of databricksConnectUrl from databricksIn |
| 9 | …"github" \| "databricks"; | keep-internal |  | Wire auth enum value 'databricks' from server re |
| 29 | …e.auth === "databricks" && !workspace?… | keep-internal |  | Comparison against wire auth value 'databricks'. |
| 30 | return Promise.reject(new Error("Enter your Databricks workspace URL.")); | keep-origin |  | User prompt for Databricks workspace URL; names the Databricks integration target. |
| 34 | service.auth === "databricks" | keep-internal |  | Comparison against wire auth value 'databricks'. |
| 35 | ? databricksConnectUrl(workspace!.trim… | keep-internal |  | code identifier |

### `web/src/lib/mcpServerName.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 19 | ["Databricks", "Databricks"], | keep-internal |  | test code |
| 25 | ["databricks-v2", "databricks-v2"], | keep-internal |  | test code |

### `web/src/lib/mcpServerName.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | "Databricks", | keep-origin |  | Brand spelling for third-party Databricks MCP server name; integration target, not publisher. |

### `web/src/lib/mobileAppTargets.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | …stubGlobal("omnigentNative", kind === … | keep-internal |  | test code |
| 16 | …stubGlobal("omnigentDesktop", kind ===… | keep-internal |  | test code |

### `web/src/lib/modePreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …onst KEY = "omnigent:last-mode-by-harn… | keep-internal |  | test code |

### `web/src/lib/modePreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | …RAGE_KEY = "omnigent:last-mode-by-harn… | keep-internal |  | localStorage key omnigent:last-mode-by-harness; |

### `web/src/lib/modelCatalogCache.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | import { getOmnigentServerIdentity } f… | keep-internal |  | test code |
| 10 | …() => ({ getOmnigentServerIdentity: vi… | keep-internal |  | test code |
| 24 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 52 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 98 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |

### `web/src/lib/modelCatalogCache.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 38 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 41 | return ˋomnigent:model-catalog:v1:${JS… | keep-internal |  | Cache storage key prefix omnigent:model-catalog: |

### `web/src/lib/modelConfigurationSource.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | { kind: "databricks", label: "Workspac… | keep-internal |  | test code |
| 9 | "Databricks · production-west", | keep-internal |  | test code |

### `web/src/lib/modelConfigurationSource.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | : source.kind === "databricks" | keep-internal |  | Comparison against server source.kind value 'dat |
| 23 | ? ["Databricks", source.name ?? source.host].filter(Boolean).join(" · ") | keep-origin |  | UI label naming Databricks as model provider integration (third-party service). |

### `web/src/lib/modelCreators.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | ["omnigent/databricks-claude-sonnet-4-… | keep-internal |  | test code |
| 17 | ["omnigent-openai/system.ai.gpt-5-6-so… | keep-internal |  | test code |
| 18 | ["omnigent-openai/system.ai.glm-5-2", … | keep-internal |  | test code |
| 19 | ["databricks-glm-5-2", undefined, "Z.a… | keep-internal |  | test code |
| 22 | ["databricks-kimi-k2-7-code", undefine… | keep-internal |  | test code |
| 69 | …mi = { id: "omnigent/databricks-kimi-k… | keep-internal |  | test code |
| 71 | …imi code", "databricks-kimi", "K2.7"])… | keep-internal |  | test code |

### `web/src/lib/modelCreators.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …imi through Databricks is Moonshot AI.… | keep-internal |  | code comment |
| 25 | … prefixes (ˋdatabricks-ˋ, ˋsystem.ai.ˋ… | keep-internal |  | code comment |
| 116 | …EFIX = /^(?:databricks-\|system\.ai\.)/… | keep-internal |  | code identifier |

### `web/src/lib/nativeBridge.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 35 | …d on window.omnigentDesktop. | keep-internal |  | test code |
| 42 | …d on window.omnigentNative. | keep-internal |  | test code |
| 54 | …d on window.omnigentNative. The MVP | keep-internal |  | test code |
| 73 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 87 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 99 | …, unknown>).omnigentNative = { | keep-internal |  | test code |
| 120 | …, unknown>).omnigentNative; | keep-internal |  | test code |
| 127 | …, unknown>).omnigentNative = { | keep-internal |  | test code |
| 140 | …, unknown>).omnigentNative; | keep-internal |  | test code |
| 160 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 182 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 192 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 217 | …nknown as { omnigentDesktop: Record<st… | keep-internal |  | test code |
| 218 | ).omnigentDesktop.connectArcaHost = ()… | keep-internal |  | test code |
| 230 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 268 | …, unknown>).omnigentDesktop = { kind: … | keep-internal |  | test code |
| 320 | …, unknown>).omnigentDesktop = { kind: … | keep-internal |  | test code |
| 321 | …, unknown>).omnigentNative = { kind: "… | keep-internal |  | test code |
| 326 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 327 | …, unknown>).omnigentNative; | keep-internal |  | test code |
| 470 | …nknown as { omnigentNative?: { kind: s… | keep-internal |  | test code |
| 471 | ).omnigentNative = undefined; | keep-internal |  | test code |
| 600 | …nknown as { omnigentNative: Record<str… | keep-internal |  | test code |
| 690 | …nknown as { omnigentNative: Record<str… | keep-internal |  | test code |
| 722 | …nknown as { omnigentNative: Record<str… | keep-internal |  | test code |
| 769 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 778 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |

### `web/src/lib/nativeBridge.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …rved by the Omnigent server). | keep-internal |  | code comment |
| 17 | …ted ˋwindow.omnigentNativeˋ or the | keep-internal |  | code comment |
| 18 | …ron ˋwindow.omnigentDesktopˋ object), … | keep-internal |  | code comment |
| 71 | * ˋwindow.omnigentDesktopˋ; newer shel… | keep-internal |  | code comment |
| 300 | …* The "Show Omnigent from anywhere" sh… | keep-internal |  | code comment |
| 454 | * Databricks-internal features (e.g. t… | keep-internal |  | code comment |
| 456 | …s server is Databricks-managed. | keep-internal |  | code comment |
| 458 | databricksInternalFeatures?: boolean; | keep-internal |  | code identifier |
| 489 | …hether the ˋomnigentˋ CLI was found an… | keep-internal |  | code comment |
| 501 | …ver needs a Databricks/OIDC login the … | keep-internal |  | code comment |
| 503 | … desktop's ˋomnigent:host-controlˋ han… | keep-internal |  | code comment |
| 508 | …* The "Show Omnigent from anywhere" sh… | keep-internal |  | code comment |
| 600 | …'s sign-in (Databricks or OIDC browser | keep-internal |  | code comment |
| 613 | ….well-known/omnigent.jsonˋ), | keep-internal |  | code comment |
| 623 | * ˋGET /.well-known/omnigent.jsonˋ. | keep-internal |  | code comment |
| 636 | …* Installed omnigent package version. … | keep-internal |  | code comment |
| 683 | …nknown as { omnigentDesktop?: Electron… | keep-internal |  | code identifier |
| 690 | …nknown as { omnigentNative?: NativeShe… | keep-internal |  | code identifier |
| 719 | …lds expose ˋomnigentDesktopˋ but preda… | keep-internal |  | code comment |
| 834 | …ll can show Omnigent from anywhere. Ne… | keep-internal |  | code comment |
| 845 | …saved "Show Omnigent from anywhere" sh… | keep-internal |  | code comment |
| 964 | …ses ˋwindow.omnigentDesktopˋ — never a… | keep-internal |  | code comment |
| 1128 | … it into ˋ--omnigent-*-bar-visibleˋ; t… | keep-internal |  | code comment |
| 1130 | …mbine in ˋ--omnigent-inset-*ˋ (index.c… | keep-internal |  | code comment |
| 1143 | …InsetVar("--omnigent-top-bar-visible",… | keep-internal |  | CSS custom property --omnigent-top-bar-visible d |
| 1166 | …InsetVar("--omnigent-bottom-bar-visibl… | keep-internal |  | CSS custom property --omnigent-bottom-bar-visibl |
| 1395 | …a instance (Databricks-internal sandbo… | keep-internal |  | code comment |

### `web/src/lib/nativeChatTerminalBar.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 19 | …, unknown>).omnigentNative = { | keep-internal |  | test code |
| 27 | …, unknown>).omnigentNative; | keep-internal |  | test code |

### `web/src/lib/nativeCodingAgents.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …ABEL_KEY = "omnigent.wrapper"; | keep-internal |  | Session label key omnigent.wrapper shared with s |
| 4 | …ABEL_KEY = "omnigent.ui"; | keep-internal |  | Session label key omnigent.ui shared with server |
| 10 | …ABEL_KEY = "omnigent.claude_native.des… | keep-internal |  | Session label key omnigent.claude_native.descrip |
| 41 | …ABEL_KEY = "omnigent.codex_native.agen… | keep-internal |  | Session label key omnigent.codex_native.agent_ni |
| 93 | * ˋomnigent.wrapperˋ value stamped on … | keep-internal |  | code comment |
| 295 | // Mirrors omnigent.harness_aliases.NA… | keep-internal |  | code comment |
| 322 | // stamp: ˋomnigent/server/routes/sess… | keep-internal |  | code comment |
| 324 | …per-vendor ˋomnigent/<vendor>_native_p… | keep-internal |  | code comment |
| 406 | * ˋomnigent.wrapperˋ label (e.g. ˋ"cla… | keep-internal |  | code comment |
| 461 | …s — by its ˋomnigent.wrapperˋ | keep-internal |  | code comment |

### `web/src/lib/nativeHarnessModes.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 191 | …onsˋ popup (omnigent/codex_approval_mo… | keep-internal |  | code comment |
| 245 | …dbox) — see omnigent.stores.conversati… | keep-internal |  | code comment |
| 250 | …ABEL_KEY = "omnigent.codex_native.bypa… | keep-internal |  | Session label key omnigent.codex_native.bypass_s |
| 266 | * in omnigent/native/permission_modes.… | keep-internal |  | code comment |

### `web/src/lib/nativeInsets.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | // ˋ--omnigent-native-top-barˋ / ˋ--om… | keep-internal |  | code comment |
| 9 | // into ˋ--omnigent-inset-topˋ / ˋ--om… | keep-internal |  | code comment |
| 24 | …Property("--omnigent-native-top-bar", … | keep-internal |  | CSS custom property --omnigent-native-top-bar co |
| 25 | …Property("--omnigent-native-bottom-bar… | keep-internal |  | CSS custom property --omnigent-native-bottom-bar |

### `web/src/lib/newChatPickerCache.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | import { getOmnigentServerIdentity } f… | keep-internal |  | test code |
| 22 | …() => ({ getOmnigentServerIdentity: vi… | keep-internal |  | test code |
| 72 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 119 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 213 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 218 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 231 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 234 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 260 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 292 | …removeItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 313 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 432 | …ge.setItem("omnigent:recent-workspaces… | keep-internal |  | test code |
| 434 | …ge.setItem("omnigent:recent-workspaces… | keep-internal |  | test code |
| 457 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |

### `web/src/lib/newChatPickerCache.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 67 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 70 | return ˋomnigent:new-chat-picker:v2:${… | keep-internal |  | Cache storage key prefix omnigent:new-chat-picke |

### `web/src/lib/openLinkInApp.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 34 | omnigentDesktop: { | keep-internal |  | test code |
| 55 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 186 | omnigentDesktop: { kind: "electron", b… | keep-internal |  | test code |
| 242 | …ty(window, "omnigentDesktop"), | keep-internal |  | test code |

### `web/src/lib/openLinkInApp.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | …nknown as { omnigentDesktop: BrowserBr… | keep-internal |  | code identifier |

### `web/src/lib/optimisticTitles.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …ARKER_RE in omnigent/entities/conversa… | keep-internal |  | code comment |

### `web/src/lib/panelSizePreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …RAGE_KEY = "omnigent:panel-size-prefer… | keep-internal |  | test code |

### `web/src/lib/panelSizePreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | …RAGE_KEY = "omnigent:panel-size-prefer… | keep-internal |  | localStorage key omnigent:panel-size-preferences |

### `web/src/lib/permissionsApi.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 61 | "/workspaces/omnigent", | keep-internal |  | test code |
| 151 | // The server returns OmnigentError as | keep-internal |  | test code |
| 208 | …emails post-Databricks-Apps integratio… | keep-internal |  | test code |
| 322 | …d, e.g. the Databricks-managed server)… | keep-internal |  | test code |

### `web/src/lib/permissionsApi.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | * Mirrors ˋomnigent/server/routes/sess… | keep-internal |  | code comment |
| 12 | …WNERˋˋ in ˋˋomnigent/server/auth.pyˋˋ … | keep-internal |  | code comment |
| 49 | …EDITˋˋ in ˋˋomnigent/server/auth.pyˋˋ. | keep-internal |  | code comment |
| 78 | …l, e.g. the Databricks-managed server)… | keep-internal |  | code comment |

### `web/src/lib/pickerEntryVisibility.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 105 | …e", { key: "omnigent:ui-font-size" }))… | keep-internal |  | test code |

### `web/src/lib/pickerEntryVisibility.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …RAGE_KEY = "omnigent:hidden-picker-age… | keep-internal |  | localStorage key omnigent:hidden-picker-agents; |

### `web/src/lib/projectFolderPaginationPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …RAGE_KEY = "omnigent:project-folder-pa… | keep-internal |  | test code |

### `web/src/lib/projectFolderPaginationPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …RAGE_KEY = "omnigent:project-folder-co… | keep-internal |  | localStorage key omnigent:project-folder-collaps |
| 7 | …RAGE_KEY = "omnigent:project-folder-pa… | keep-internal |  | localStorage key omnigent:project-folder-page-si |
| 9 | …RAGE_KEY = "omnigent:project-folder-pa… | keep-internal |  | Legacy localStorage key read for migration; must |

### `web/src/lib/projectLaunchPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …RAGE_KEY = "omnigent:project-launch-de… | keep-internal |  | test code |

### `web/src/lib/projectLaunchPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …RAGE_KEY = "omnigent:project-launch-de… | keep-internal |  | localStorage key omnigent:project-launch-default |
| 125 | …ED_EVENT = "omnigent:project-launch-de… | keep-internal |  | Custom DOM event name for in-app change notifica |

### `web/src/lib/projectsApi.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | // (ˋomnigent/server/routes/projects.p… | keep-internal |  | code comment |

### `web/src/lib/pullRequestViewed.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …() => ({ getOmnigentServerIdentity: ()… | keep-internal |  | test code |
| 22 | …Y_PREFIX = "omnigent:pr-viewed:v2:"; | keep-internal |  | test code |
| 23 | …Y_PREFIX = "omnigent:pr-viewed:v1:"; | keep-internal |  | test code |
| 531 | …ge.setItem("omnigent:unrelated", "keep… | keep-internal |  | test code |
| 540 | …ge.getItem("omnigent:unrelated")).toBe… | keep-internal |  | test code |

### `web/src/lib/pullRequestViewed.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 21 | …Y_PREFIX = "omnigent:pr-viewed:v2:"; | keep-internal |  | Storage key prefix omnigent:pr-viewed:v2: for pe |
| 23 | …Y_PREFIX = "omnigent:pr-viewed:v1:"; | keep-internal |  | Legacy storage key prefix read for migration; mu |
| 340 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |

### `web/src/lib/randomUUID.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | // Omnigent served over plain ˋhttpˋ o… | keep-internal |  | code comment |

### `web/src/lib/renderItems.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2554 | …odel).toBe("databricks-claude-opus-4-8… | keep-internal |  | test code |
| 2562 | model: "databricks-claude-haiku-4-5", | keep-internal |  | test code |
| 2571 | …odel).toBe("databricks-claude-haiku-4-… | keep-internal |  | test code |
| 2579 | model: "databricks-claude-sonnet-4-6", | keep-internal |  | test code |
| 2591 | …odel).toBe("databricks-claude-sonnet-4… | keep-internal |  | test code |
| 2598 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 2614 | …odel).toBe("databricks-claude-opus-4-8… | keep-internal |  | test code |
| 2876 | { model: "databricks-claude-sonnet-5" … | keep-internal |  | test code |
| 2932 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 2941 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 2959 | model: "databricks-gpt-5-6-sol", | keep-internal |  | test code |
| 2976 | …nst luna = "databricks-gpt-5-6-luna"; | keep-internal |  | test code |
| 3056 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 3071 | model: "databricks-claude-opus-5", | keep-internal |  | test code |
| 3090 | model: "databricks-gpt-5-6-sol", | keep-internal |  | test code |
| 3100 | model: "databricks-gpt-5-6-sol", | keep-internal |  | test code |
| 3118 | model: "databricks-gpt-5-6-luna", | keep-internal |  | test code |
| 3137 | …odel).toBe("databricks-claude-opus-5")… | keep-internal |  | test code |
| 3177 | model: "databricks-gpt-5-6-luna", | keep-internal |  | test code |
| 3192 | { model: "databricks-claude-sonnet-5",… | keep-internal |  | test code |
| 3288 | model: "databricks-gpt-5-6-luna", | keep-internal |  | test code |
| 3299 | model: "databricks-gpt-5-6-luna", | keep-internal |  | test code |
| 3315 | …s({ model: "databricks-gpt-5-6-sol" })… | keep-internal |  | test code |
| 3328 | …s({ model: "databricks-gpt-5-6-sol" })… | keep-internal |  | test code |
| 3342 | model: "databricks-gpt-5-6-sol", | keep-internal |  | test code |
| 3366 | model: "databricks-claude-sonnet-5", | keep-internal |  | test code |
| 3418 | model: "databricks-claude-sonnet-4-6", | keep-internal |  | test code |
| 3575 | model: "databricks-claude-sonnet-5", | keep-internal |  | test code |

### `web/src/lib/renderItems.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1351 | * (ˋ"databricks-claude-opus-4-8"ˋ and … | keep-internal |  | code comment |
| 1355 | …startsWith("databricks-") ? lower.slic… | keep-internal |  | Code strips the Databricks catalog model-id pref |

### `web/src/lib/repoPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …onst KEY = "omnigent:last-sandbox-repo… | keep-internal |  | test code |
| 5 | …GACY_KEY = "omnigent:last-sandbox-repo… | keep-internal |  | test code |

### `web/src/lib/repoPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …RAGE_KEY = "omnigent:last-sandbox-repo… | keep-internal |  | localStorage key omnigent:last-sandbox-repos; pe |
| 13 | …RAGE_KEY = "omnigent:last-sandbox-repo… | keep-internal |  | Legacy localStorage key read for migration. |

### `web/src/lib/retentionPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …RAGE_KEY = "omnigent:archived-retentio… | keep-internal |  | localStorage key omnigent:archived-retention-day |
| 33 | …er-written ˋomnigent.archived_atˋ labe… | keep-internal |  | code comment |

### `web/src/lib/routing.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 121 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 136 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 149 | setOmnigentHostConfig({ analytics: vi.… | keep-internal |  | test code |
| 157 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/lib/routing.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | ….tsˋ), and ˋOmnigentAppˋ renders WITHO… | keep-internal |  | code comment |
| 46 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 56 | * Databricks host maps it to a namespa… | keep-internal |  | code comment |
| 59 | export type OmnigentLinkProps = Compon… | keep-internal |  | code identifier |
| 66 | …mponentType<OmnigentLinkProps & RefAtt… | keep-internal |  | code identifier |
| 81 | …horElement, OmnigentLinkProps>(functio… | keep-internal |  | code identifier |
| 85 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 169 | …horElement, OmnigentLinkProps>((props,… | keep-internal |  | code identifier |
| 212 | …horElement, OmnigentLinkProps>((props,… | keep-internal |  | code identifier |

### `web/src/lib/routingDecision.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | model: "databricks-claude-sonnet-5", | keep-internal |  | test code |
| 20 | …_override: "databricks-claude-opus-4-8… | keep-internal |  | test code |
| 21 | router_source: "databricks-aigw", | keep-internal |  | test code |
| 29 | …dOverride: "databricks-claude-opus-4-8… | keep-internal |  | test code |
| 30 | routerSource: "databricks-aigw", | keep-internal |  | test code |

### `web/src/lib/routingDecision.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | …nswered — ˋ"databricks-aigw"ˋ or ˋ"oss… | keep-internal |  | code comment |

### `web/src/lib/sandboxRepositories.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …ABEL_KEY = "omnigent.sandbox.repo"; | keep-internal |  | Session label key omnigent.sandbox.repo shared w |

### `web/src/lib/scheduleText.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 210 | …er record (ˋomnigent/server/scheduled/… | keep-internal |  | code comment |

### `web/src/lib/scheduledTasksApi.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 58 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 64 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 209 | …ers).get("x-omnigent-automation-templa… | keep-internal |  | test code |
| 242 | …ers).get("x-omnigent-automation-source… | keep-internal |  | test code |
| 243 | …ers).get("x-omnigent-automation-templa… | keep-internal |  | test code |

### `web/src/lib/scheduledTasksApi.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | // ˋomnigent/server/routes/scheduled_t… | keep-internal |  | code comment |
| 129 | …n sync with omnigent/server/scheduled/… | keep-internal |  | code comment |
| 276 | …codeˋ (the ˋOmnigentErrorˋ shape) over… | keep-internal |  | code comment |
| 395 | "x-omnigent-automation-source": "ui", | keep-internal |  | HTTP header x-omnigent-automation-source parsed |
| 396 | "x-omnigent-automation-template": temp… | keep-internal |  | HTTP header x-omnigent-automation-template parse |

### `web/src/lib/sendFailure.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …NAVAILABLE (omnigent/errors.py) — | keep-internal |  | code comment |

### `web/src/lib/sessionCapabilities.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | … labels: { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 29 | … labels: { "omnigent.sandbox.repo": "h… | keep-internal |  | test code |
| 98 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 101 | … labels: { "omnigent.wrapper": "cursor… | keep-internal |  | test code |
| 106 | … labels: { "omnigent.wrapper": "cursor… | keep-internal |  | test code |

### `web/src/lib/sessionCapabilities.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 23 | …?.labels?.["omnigent.host_type"] === "… | keep-internal |  | Server session label key omnigent.host_type; pro |
| 36 | …. Mirrors ˋˋomnigent/util/reasoning_ef… | keep-internal |  | code comment |
| 87 | …?.labels?.["omnigent.wrapper"]; | keep-internal |  | Server session label key omnigent.wrapper; proto |
| 117 | * ˋˋomnigent.closed=trueˋˋ). The sideb… | keep-internal |  | code comment |
| 129 | …?.labels?.["omnigent.closed"] ?? activ… | keep-internal |  | Server session/conversation label key omnigent.c |
| 136 | …?.labels?.["omnigent.wrapper"] ?? acti… | keep-internal |  | Server label key omnigent.wrapper; protocol iden |
| 138 | …?.labels?.["omnigent.codex_native.agen… | keep-internal |  | Server label key omnigent.codex_native.agent_nic |
| 139 | …?.labels?.["omnigent.codex_native.agen… | keep-internal |  | Server label key omnigent.codex_native.agent_nic |
| 146 | …?.labels?.["omnigent.wrapper"] ?? acti… | keep-internal |  | Server label key omnigent.wrapper; protocol iden |

### `web/src/lib/sessionDrafts.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | const key = "omnigent.sessionDrafts"; | keep-internal |  | test code |

### `web/src/lib/sessionDrafts.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …AFTS_KEY = "omnigent.sessionDrafts"; | keep-internal |  | localStorage key omnigent.sessionDrafts holding |

### `web/src/lib/sessionEvents.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …h event in ˋomnigent/server/schemas.py… | keep-internal |  | test code |
| 598 | model: "databricks-claude-opus-4-8", | keep-internal |  | test code |
| 606 | …odel).toBe("databricks-claude-opus-4-8… | keep-internal |  | test code |
| 623 | model: "databricks-claude-haiku-4-5", | keep-internal |  | test code |
| 952 | … 'Allow the omnigent MCP server to run… | keep-internal |  | test code |
| 1165 | // The Omnigent relay path emits a ses… | keep-internal |  | test code |

### `web/src/lib/sessionFamilies.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 35 | … labels: { "omnigent.pinned": "1" } }; | keep-internal |  | test code |

### `web/src/lib/sessionFilterPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | …ge.setItem("omnigent:session-filter", … | keep-internal |  | test code |
| 33 | …ge.setItem("omnigent:session-filter", … | keep-internal |  | test code |

### `web/src/lib/sessionFilterPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:session-filter"; | keep-internal |  | localStorage key omnigent:session-filter; persis |

### `web/src/lib/sessionHost.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | "omnigent.side_chat": "1", | keep-internal |  | test code |
| 10 | "omnigent.side_chat.source_id": "paren… | keep-internal |  | test code |
| 17 | …omLabels({ "omnigent.side_chat": "1", … | keep-internal |  | test code |
| 22 | …omLabels({ "omnigent.fork.source_id": … | keep-internal |  | test code |

### `web/src/lib/sessionHost.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 49 | …ID_LABEL = "omnigent.sandbox.requested… | keep-internal |  | Server label key omnigent.sandbox.requested_host |
| 71 | labels?.["omnigent.side_chat.source_id… | keep-internal |  | Server label key omnigent.side_chat.source_id; p |
| 72 | (labels?.["omnigent.side_chat"] === "1… | keep-internal |  | Server label keys omnigent.side_chat / omnigent. |

### `web/src/lib/sessionListCache.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 40 | …ABEL_KEY = "omnigent.pinned"; | keep-internal |  | Server label key omnigent.pinned; persisted prot |
| 53 | …ABEL_KEY = "omnigent.archived_at"; | keep-internal |  | Server label key omnigent.archived_at; persisted |

### `web/src/lib/sessionModelLabelCache.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | import { getOmnigentServerIdentity } f… | keep-internal |  | test code |
| 11 | …() => ({ getOmnigentServerIdentity: vi… | keep-internal |  | test code |
| 28 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 70 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 72 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 83 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |

### `web/src/lib/sessionModelLabelCache.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 19 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 22 | return ˋomnigent:session-model-label:v… | keep-internal |  | code identifier |

### `web/src/lib/sessionStop.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 34 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 65 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 82 | labels: { "omnigent.wrapper": "devin-n… | keep-internal |  | test code |
| 92 | labels: { "omnigent.wrapper": "devin-n… | keep-internal |  | test code |

### `web/src/lib/sessionStop.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …ABEL_KEY = "omnigent.wrapper"; | keep-internal |  | Server label key omnigent.wrapper; protocol iden |
| 9 | …M_STOPˋ in ˋomnigent/runner/native/int… | keep-internal |  | code comment |

### `web/src/lib/sessionUpdatesSocket.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 87 | …ubEnv("VITE_OMNIGENT_HOST_ROUTING", "t… | keep-internal |  | test code |
| 95 | …Params.get("omnigent_slice_key")).toBe… | keep-internal |  | test code |

### `web/src/lib/sessionUpdatesSocket.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | // ˋomnigent/server/routes/sessions.py… | keep-internal |  | code comment |
| 60 | …rved by the Omnigent server directly o… | keep-internal |  | code comment |
| 63 | …d, append ˋ?omnigent_slice_key=<frozen… | keep-internal |  | code comment |
| 87 | … ? ˋ${path}?omnigent_slice_key=${encod… | keep-internal |  | Query parameter omnigent_slice_key on the update |

### `web/src/lib/sessionWorkspaceState.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …RAGE_KEY = "omnigent:session-workspace… | keep-internal |  | test code |

### `web/src/lib/sessionWorkspaceState.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 57 | …TATE_KEY = "omnigent:session-workspace… | keep-internal |  | localStorage key omnigent:session-workspace-stat |

### `web/src/lib/sessionsApi.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 303 | …ers).get("X-Omnigent-Background-Sessio… | keep-internal |  | test code |
| 486 | …ers).get("X-Omnigent-Background-Sessio… | keep-internal |  | test code |
| 744 | labels: { "omnigent.side_chat": "1", "… | keep-internal |  | test code |
| 832 | it.each(["omnigent.side_chat.source_id… | keep-internal |  | test code |
| 835 | …ubEnv("VITE_DATABRICKS_WORKSPACE", "tr… | keep-internal |  | test code |
| 838 | labels: { "omnigent.side_chat": "1", [… | keep-internal |  | test code |
| 848 | …ers).get("X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 1045 | labels: { "omnigent.codex_native.colla… | keep-internal |  | test code |
| 1053 | …n.labels?.["omnigent.codex_native.coll… | keep-internal |  | test code |
| 1751 | …ers).get("X-Omnigent-Background-Sessio… | keep-internal |  | test code |

### `web/src/lib/sessionsApi.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …). Mirrors ˋomnigent/server/routes/ses… | keep-internal |  | code comment |
| 37 | …l for the X-Omnigent-Client telemetry … | keep-internal |  | code comment |
| 92 | …sageˋ from ˋomnigent/server/schemas.py… | keep-internal |  | code comment |
| 108 | * ˋomnigent/server/schemas.pyˋ. Snake-… | keep-internal |  | code comment |
| 179 | …umented in ˋomnigent/server/API.mdˋ bu… | keep-internal |  | code comment |
| 275 | * ˋomnigent.server.schemas.SandboxStat… | keep-internal |  | code comment |
| 423 | …r's :class:ˋOmnigentErrorˋ serializes … | keep-internal |  | code comment |
| 481 | * Databricks-backed stores propagate r… | keep-internal |  | code comment |
| 589 | "X-Omnigent-Client": getClientSurface(… | keep-internal |  | HTTP header X-Omnigent-Client parsed by the serv |
| 664 | …n/json", "X-Omnigent-Client": getClien… | keep-internal |  | HTTP header X-Omnigent-Client parsed by the serv |
| 754 | …n/json", "X-Omnigent-Client": getClien… | keep-internal |  | HTTP header X-Omnigent-Client parsed by the serv |
| 829 | "X-Omnigent-Client": getClientSurface(… | keep-internal |  | HTTP header X-Omnigent-Client parsed by the serv |
| 984 | …n/json", "X-Omnigent-Client": getClien… | keep-internal |  | HTTP header X-Omnigent-Client parsed by the serv |
| 1247 | * (ˋomnigent/server/API.mdˋ §Reconnect… | keep-internal |  | code comment |
| 1418 | … format as ˋomnigent session exportˋ (… | keep-internal |  | code comment |
| 1419 | * ˋomnigent/cli.pyˋ): the first line i… | keep-internal |  | code comment |
| 1422 | …ps through ˋomnigent session importˋ. … | keep-internal |  | code comment |
| 1507 | …HEADER = "x-omnigent-hold-when-host-of… | keep-internal |  | HTTP header x-omnigent-hold-when-host-offline pa |

### `web/src/lib/settingsPortability.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 72 | "omnigent:default-workspace-tab": "fil… | keep-internal |  | test code |
| 86 | "omnigent:default-workspace-tab": "fil… | keep-internal |  | test code |
| 96 | "omnigent:default-workspace-tab": "sub… | keep-internal |  | test code |
| 118 | "omnigent:default-workspace-tab": defa… | keep-internal |  | test code |

### `web/src/lib/settingsPortability.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 36 | "omnigent:ui-font-size", | keep-internal |  | localStorage key in the exportable allowlist; ex |
| 37 | "omnigent:ui-font-family", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 38 | "omnigent:code-font-size", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 39 | "omnigent:code-font-family", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 40 | "omnigent:code-font-weight", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 41 | "omnigent:terminal-theme", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 42 | "omnigent:ui-theme-palette", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 43 | "omnigent:custom-theme", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 44 | "omnigent:default-workspace-panel", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 45 | "omnigent:default-workspace-tab", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 47 | "omnigent:default-transcript-view", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 48 | "omnigent:hide-unconfigured-harnesses"… | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 53 | "omnigent:default-base-branch", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 54 | "omnigent:always-use-worktree", | keep-internal |  | localStorage key in the exportable allowlist; pe |
| 107 | a.download = "omnigent-settings.json"; | change | S89 | Downloaded export file name is shown to the user in the browser's download UI and file system. |
| 129 | reject(new Error("The file doesn't contain valid Omnigent settings.")); | change | S89 | Error text shown in the Settings import alert names the product. |

### `web/src/lib/shareLink.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | getOmnigentTransformShareLink: vi.fn((… | keep-internal |  | test code |
| 12 | …outing("/ml/omnigent-embed").rebasePat… | keep-internal |  | test code |
| 15 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |
| 16 | …ked(host.getOmnigentTransformShareLink… | keep-internal |  | test code |
| 24 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 32 | ….origin}/ml/omnigent-embed/c/conv_1ˋ, | keep-internal |  | test code |
| 38 | …ked(host.getOmnigentTransformShareLink… | keep-internal |  | test code |
| 42 | …m/embed#/ml/omnigent-embed/c/conv_1?o=… | keep-internal |  | test code |

### `web/src/lib/shareLink.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | import { getOmnigentTransformShareLink… | keep-internal |  | code identifier |
| 5 | …ple outside Omnigent use to open a ses… | keep-internal |  | code comment |
| 20 | …nsform = getOmnigentTransformShareLink… | keep-internal |  | code identifier |

### `web/src/lib/sideChat.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 64 | * ˋomnigent/harnesses/codex_native/sid… | keep-internal |  | code comment |

### `web/src/lib/sidebarViewPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 41 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 50 | …ge.setItem("omnigent:sidebar-view", "{… | keep-internal |  | test code |
| 60 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 65 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 79 | …CalledWith("omnigent:sidebar-view"); | keep-internal |  | test code |
| 88 | "omnigent:sidebar-view", | keep-internal |  | test code |

### `web/src/lib/sidebarViewPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …RAGE_KEY = "omnigent:sidebar-view"; | keep-internal |  | localStorage key omnigent:sidebar-view; persiste |

### `web/src/lib/smartRoutingAvailability.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 179 | [true, true, true, "databricks-aigw"], | keep-internal |  | test code |
| 180 | …lse, true, "databricks-aigw"], | keep-internal |  | test code |

### `web/src/lib/smartRoutingAvailability.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 44 | …erSource = "databricks-aigw" \| "oss-ll… | keep-internal |  | RouterSource id databricks-aigw mirrors server r |
| 63 | …ed) return "databricks-aigw"; | keep-internal |  | Returns the databricks-aigw router-source id sha |

### `web/src/lib/sse.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …thon-client/omnigent_client/_sse.py. | keep-internal |  | code comment |

### `web/src/lib/storedChoicePreference.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:test-choice-prefe… | keep-internal |  | test code |
| 79 | …e", { key: "omnigent:another-preferenc… | keep-internal |  | test code |

### `web/src/lib/subagentPanelPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:open-subagents-in… | keep-internal |  | localStorage key omnigent:open-subagents-in-pane |

### `web/src/lib/systemMessage.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 309 | "Note: an Omnigent automation sent thi… | keep-internal |  | test code |
| 310 | "Explain <omnigent-automation-context>… | keep-internal |  | test code |
| 311 | …xample:\n\n<omnigent-automation-contex… | keep-internal |  | test code |
| 312 | … today.\n\n<omnigent-automation-contex… | keep-internal |  | test code |
| 315 | "Task\n\n<omnigent-automation-context>… | keep-internal |  | test code |
| 316 | "Task\n\n<omnigent-automation-context>… | keep-internal |  | test code |
| 317 | …xample:\n\n<omnigent-automation-contex… | keep-internal |  | test code |

### `web/src/lib/systemMessage.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 275 | "<omnigent-automation-context>\nNote: an Omnigent automation sent this message, and no one is watchi… | keep-deferred |  | Server-generated automation note (fire.py UNATTENDED_RUN_NOTE); web copy must match byte-for-byte to strip it, and the UI hides it. |

### `web/src/lib/telemetry.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …ing for the Omnigent web UI. | keep-internal |  | code comment |

### `web/src/lib/tempConversationId.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 13 | …ABEL).toBe("omnigent.client_create_tok… | keep-internal |  | test code |

### `web/src/lib/tempConversationId.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …EN_LABEL = "omnigent.client_create_tok… | keep-internal |  | Server label key omnigent.client_create_token; p |

### `web/src/lib/terminalClipboardPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | import { getOmnigentServerIdentity } f… | keep-internal |  | test code |
| 12 | …() => ({ getOmnigentServerIdentity: vi… | keep-internal |  | test code |
| 14 | …onst KEY = 'omnigent:terminal-clipboar… | keep-internal |  | test code |
| 15 | …THER_KEY = 'omnigent:terminal-clipboar… | keep-internal |  | test code |
| 30 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 63 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 67 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 72 | …i.mocked(getOmnigentServerIdentity).mo… | keep-internal |  | test code |
| 124 | storageChange("omnigent:unrelated"); | keep-internal |  | test code |
| 195 | ).rejects.toThrow("valid Omnigent settings"); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/lib/terminalClipboardPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | import { getOmnigentServerIdentity } f… | keep-internal |  | code identifier |
| 5 | …E_PREFIX = "omnigent:terminal-clipboar… | keep-internal |  | localStorage key prefix for per-server terminal |
| 6 | …GE_EVENT = "omnigent:terminal-clipboar… | keep-internal |  | Custom DOM event name used internally for clipbo |
| 10 | …server = getOmnigentServerIdentity(); | keep-internal |  | code identifier |
| 23 | …ser/app and Omnigent server. */ | keep-internal |  | code comment |

### `web/src/lib/terminalThemePreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …RAGE_KEY = "omnigent:terminal-theme"; | keep-internal |  | test code |

### `web/src/lib/terminalThemePreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …RAGE_KEY = "omnigent:terminal-theme"; | keep-internal |  | localStorage key for terminal theme preference |

### `web/src/lib/themePalette.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | …RAGE_KEY = "omnigent:ui-theme-palette"… | keep-internal |  | test code |
| 190 | …he base for Omnigent dark form control… | keep-internal |  | test code |
| 195 | it("uses the Omnigent brand pink as the primary accent in both modes", () => { | change | S82 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 201 | it("uses magenta links with neutral support controls in Omnigent", () => { | change | S82 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/lib/themePalette.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | …RAGE_KEY = "omnigent:ui-theme-palette"… | keep-internal |  | localStorage key for UI palette preference; asse |
| 218 | label: "Omnigent", | change | S82 | Display name of default brand palette shown under swatch/in Appearance color-theme dropdown |

### `web/src/lib/toolEditDiff.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 56 | const omnigentEdits = [{ oldText: "x =… | keep-internal |  | test code |
| 58 | …tDiff("mcp__omnigent__sys_os_edit", { … | keep-internal |  | test code |
| 304 | "mcp__omnigent__sys_os_write", | keep-internal |  | test code |

### `web/src/lib/toolEditDiff.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …port { stripOmnigentPrefix } from "@/l… | keep-internal |  | code identifier |
| 59 | …MultiEditˋ, Omnigent ˋsys_os_editˋ, Pi… | keep-internal |  | code comment |
| 62 | …de ˋWriteˋ, Omnigent ˋsys_os_writeˋ, P… | keep-internal |  | code comment |
| 95 | …tool = stripOmnigentPrefix(name); | keep-internal |  | code identifier |

### `web/src/lib/toolIcon.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …ell", "mcp__omnigent__sys_os_shell"])( | keep-internal |  | test code |
| 19 | ["mcp__omnigent__sys_os_read", FileTex… | keep-internal |  | test code |

### `web/src/lib/toolResultSummary.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 61 | …name: "mcp__omnigent__apply_patch", ar… | keep-internal |  | test code |
| 165 | ["mcp__omnigent__sys_os_edit", '{"path… | keep-internal |  | test code |
| 168 | ["mcp__omnigent__sys_os_write", '{"pat… | keep-internal |  | test code |

### `web/src/lib/toolResultSummary.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …port { stripOmnigentPrefix } from "@/l… | keep-internal |  | code identifier |
| 35 | … MultiEdit, Omnigent's built-in Edit, … | keep-internal |  | code comment |
| 62 | …tool = stripOmnigentPrefix(name); | keep-internal |  | code identifier |

### `web/src/lib/toolTitle.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 22 | … a prefixed omnigent tool the same tit… | keep-internal |  | test code |
| 23 | …ssions call Omnigent's tools through i… | keep-internal |  | test code |
| 24 | …Title("mcp__omnigent__sys_os_shell", {… | keep-internal |  | test code |
| 29 | …Title("mcp__omnigent__sys_os_read", { … | keep-internal |  | test code |
| 181 | …, { owner: "omnigent-ai" })).toEqual({ | keep-internal |  | test code |
| 183 | body: "omnigent-ai", | keep-internal |  | test code |
| 372 | …ps the mcp__omnigent__ prefix before c… | keep-internal |  | test code |
| 373 | …[call("mcp__omnigent__sys_os_read")]))… | keep-internal |  | test code |
| 389 | …andOf("mcp__omnigent__sys_os_shell", {… | keep-internal |  | test code |
| 414 | ["mcp__omnigent__sys_os_shell", "sys-o… | keep-internal |  | test code |
| 482 | ["mcp__databricks-v2__list_files", { s… | keep-internal |  | test code |
| 483 | ["mcp__omnigent__sys_os_read", { tool:… | keep-internal |  | test code |
| 485 | …ied through Omnigent's MCP server. | keep-internal |  | test code |
| 487 | ["mcp__omnigent__linear__get_issue", {… | keep-internal |  | test code |
| 508 | ["databricks_jobs", "databricks-v2", "… | keep-internal |  | test code |
| 523 | owner: "omnigent-ai", | keep-internal |  | test code |
| 528 | ).toBe("omnigent-ai · 11532 · bug, web… | keep-internal |  | test code |

### `web/src/lib/toolTitle.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 239 | * Omnigent's MCP server carries the bu… | keep-internal |  | code comment |
| 240 | …s, so ˋmcp__omnigent__xˋ resolves as ˋ… | keep-internal |  | code comment |
| 247 | …server === "omnigent") return splitToo… | keep-internal |  | Compares the built-in MCP server name 'omnigent' |
| 298 | …ist". Drops Omnigent's ˋsys_ˋ prefix a… | keep-internal |  | code comment |
| 400 | * the omnigent sys_* tools plus the na… | keep-internal |  | code comment |
| 459 | …ame without Omnigent's ˋmcp__omnigent_… | keep-internal |  | code comment |
| 460 | …nction stripOmnigentPrefix(name: strin… | keep-internal |  | code identifier |
| 461 | …sWith("mcp__omnigent__") ? name.slice(… | keep-internal |  | Strips server-generated mcp__omnigent__ tool-nam |
| 500 | …ORIES, stripOmnigentPrefix(name)) === … | keep-internal |  | code identifier |
| 523 | …Name = stripOmnigentPrefix(name); | keep-internal |  | code identifier |
| 568 | …name = stripOmnigentPrefix(call.name); | keep-internal |  | code identifier |
| 629 | …awn schema (omnigent/tools/builtins/sp… | keep-internal |  | code comment |

### `web/src/lib/toolValue.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 70 | it("unwraps Omnigent's result wrapper … | keep-internal |  | test code |

### `web/src/lib/toolValue.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 72 | ….."}]ˋ) and Omnigent's | keep-internal |  | code comment |

### `web/src/lib/transcriptViewPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …RAGE_KEY = "omnigent:default-transcrip… | keep-internal |  | test code |

### `web/src/lib/transcriptViewPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …RAGE_KEY = "omnigent:default-transcrip… | keep-internal |  | localStorage key for default transcript view pre |

### `web/src/lib/types.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | …thon-client/omnigent_client/_types.py. | keep-internal |  | code comment |
| 11 | // mirror ˋomnigent/server/schemas.pyˋ… | keep-internal |  | code comment |
| 169 | * ˋomnigent/server/schemas.py:SessionS… | keep-internal |  | code comment |
| 193 | * Mirrors ˋomnigent.server.schemas.Ses… | keep-internal |  | code comment |
| 241 | …umented in ˋomnigent/server/API.mdˋ bu… | keep-internal |  | code comment |
| 246 | * Mirrors ˋomnigent.server.schemas.Ses… | keep-internal |  | code comment |
| 253 | * ˋomnigent.server.schemas.ModelUsageˋ… | keep-internal |  | code comment |
| 363 | … (includes ˋomnigent.wrapperˋ / | keep-internal |  | code comment |
| 364 | * ˋomnigent.uiˋ markers the picker rea… | keep-internal |  | code comment |
| 365 | * ˋomnigent.fork.source_idˋ on an unbo… | keep-internal |  | code comment |
| 594 | * ˋomnigent.server.schemas.SandboxStat… | keep-internal |  | code comment |
| 638 | …criptionˋ, ˋdatabricksˋ, or ˋgatewayˋ.… | keep-internal |  | code comment |
| 642 | …der name or Databricks profile. */ | keep-internal |  | code comment |

### `web/src/lib/uiFontPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | …RAGE_KEY = "omnigent:ui-font-size"; | keep-internal |  | test code |
| 21 | …RAGE_KEY = "omnigent:ui-font-family"; | keep-internal |  | test code |
| 126 | …he scoped ˋ.omnigent-appˋ redefines th… | keep-internal |  | test code |

### `web/src/lib/uiFontPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 17 | …he scoped ˋ.omnigent-appˋ redefines th… | keep-internal |  | code comment |
| 24 | …RAGE_KEY = "omnigent:ui-font-size"; | keep-internal |  | localStorage key for UI font size preference |
| 127 | …RAGE_KEY = "omnigent:ui-font-family"; | keep-internal |  | localStorage key for UI font family preference |

### `web/src/lib/unsentSends.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …ENDS_KEY = "omnigent.unsentSends"; | keep-internal |  | sessionStorage key holding unsent sends across r |
| 15 | …ENDS_KEY = "omnigent.queuedSends"; | keep-internal |  | sessionStorage key holding queued sends across r |

### `web/src/lib/updateOverlayInset.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …rem + var(--omnigent-inset-bottom) + 0… | keep-internal |  | test code |
| 11 | …rem + var(--omnigent-inset-bottom) + 1… | keep-internal |  | test code |

### `web/src/lib/updateOverlayInset.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …rem + var(--omnigent-inset-bottom) + $… | keep-internal |  | References CSS custom property --omnigent-inset- |

### `web/src/lib/useLoginV2.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …RAGE_KEY = "omnigent.loginV2"; | keep-internal |  | localStorage key for sticky login-v2 flag |

### `web/src/lib/userBadge.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …corey-zumar@databricks.com")).toBe("CZ… | keep-internal |  | test code |

### `web/src/lib/viteProxy.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | vi.stubEnv("OMNIGENT_URL", origin); | keep-internal |  | test code |
| 28 | vi.stubEnv("OMNIGENT_AUTH_TOKEN", ""); | keep-internal |  | test code |
| 29 | vi.stubEnv("OMNIGENT_PROXY_HEADERS", s… | keep-internal |  | test code |

### `web/src/lib/workspacePanelPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | …RAGE_KEY = "omnigent:default-workspace… | keep-internal |  | test code |

### `web/src/lib/workspacePanelPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …RAGE_KEY = "omnigent:default-workspace… | keep-internal |  | localStorage key for default workspace panel pre |

### `web/src/lib/workspacePickerPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …RAGE_KEY = "omnigent:workspace-picker-… | keep-internal |  | test code |

### `web/src/lib/workspacePickerPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …RAGE_KEY = "omnigent:workspace-picker-… | keep-internal |  | localStorage key for workspace picker preference |

### `web/src/lib/workspaceTabPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | …RAGE_KEY = "omnigent:default-workspace… | keep-internal |  | test code |

### `web/src/lib/workspaceTabPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …RAGE_KEY = "omnigent:default-workspace… | keep-internal |  | localStorage key for default workspace tab |
| 10 | …RAGE_KEY = "omnigent:pinned-workspace-… | keep-internal |  | Exported localStorage key for pinned workspace t |

### `web/src/lib/worktreeDefaultPreferences.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 25 | …ge.getItem("omnigent:always-use-worktr… | keep-internal |  | test code |
| 30 | …ge.setItem("omnigent:always-use-worktr… | keep-internal |  | test code |
| 33 | …ge.setItem("omnigent:always-use-worktr… | keep-internal |  | test code |

### `web/src/lib/worktreeDefaultPreferences.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …RAGE_KEY = "omnigent:always-use-worktr… | keep-internal |  | localStorage key for always-use-worktree prefere |

### `web/src/main.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 107 | …removeItem("omnigent:sidebar-font-size… | keep-internal |  | Removes legacy localStorage key omnigent:sidebar |

### `web/src/pages/CanvasPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 76 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 155 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 585 | …"calc(var(--omnigent-header-height) + … | keep-internal |  | Inline style using CSS custom properties --omnig |
| 586 | …tom: "var(--omnigent-inset-bottom)", | keep-internal |  | Inline style using CSS custom property --omnigen |

### `web/src/pages/ChatPage.capabilities.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 82 | … labels: { "omnigent.wrapper": NATIVE … | keep-internal |  | test code |
| 96 | … labels: { "omnigent.wrapper": "devin-… | keep-internal |  | test code |
| 115 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 136 | … labels: { "omnigent.wrapper": NATIVE … | keep-internal |  | test code |
| 137 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 138 | … labels: { "omnigent.wrapper": "cursor… | keep-internal |  | test code |
| 143 | … labels: { "omnigent.wrapper": "openco… | keep-internal |  | test code |
| 147 | … labels: { "omnigent.wrapper": "kiro-n… | keep-internal |  | test code |
| 150 | … labels: { "omnigent.wrapper": "pi-nat… | keep-internal |  | test code |
| 153 | … labels: { "omnigent.wrapper": "devin-… | keep-internal |  | test code |
| 186 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 197 | … labels: { "omnigent.wrapper": NATIVE … | keep-internal |  | test code |
| 203 | … labels: { "omnigent.wrapper": "devin-… | keep-internal |  | test code |
| 210 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 219 | … labels: { "omnigent.wrapper": "cursor… | keep-internal |  | test code |
| 227 | … labels: { "omnigent.wrapper": "openco… | keep-internal |  | test code |
| 235 | … labels: { "omnigent.wrapper": "kiro-n… | keep-internal |  | test code |
| 242 | …e case: no ˋomnigent.wrapperˋ label, w… | keep-internal |  | test code |
| 281 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |

### `web/src/pages/ChatPage.composer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 34 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 89 | …WithOwner: "omnigent-ai/omnigent" as s… | keep-internal |  | test code |
| 119 | …WithOwner: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 981 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 1252 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 1270 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 1299 | …: { value: "omnigent" } }); | keep-internal |  | test code |
| 1305 | …CalledWith("omnigent", undefined); | keep-internal |  | test code |
| 1613 | …ue: "/model databricks-gpt-5-4" } }); | keep-internal |  | test code |
| 1616 | …CalledWith("databricks-gpt-5-4", { | keep-internal |  | test code |
| 1702 | …s (embedded Omnigent REPL terminal) ke… | keep-internal |  | test code |
| 1711 | …ue: "/model databricks-gpt-5-4" } }); | keep-internal |  | test code |
| 1715 | …ith("/model databricks-gpt-5-4", undef… | keep-internal |  | test code |
| 1753 | kind: "databricks", | keep-internal |  | test code |
| 1756 | host: "acme.cloud.databricks.com", | keep-internal |  | test code |
| 1774 | …Connection: Databricks · production-we… | keep-internal |  | test code |
| 1775 | …"acme.cloud.databricks.com"); | keep-internal |  | test code |
| 1880 | kind: "databricks", | keep-internal |  | test code |
| 1883 | host: "acme.cloud.databricks.com", | keep-internal |  | test code |
| 2094 | …n(host, "getOmnigentServerIdentity").m… | keep-internal |  | test code |
| 2830 | …WithOwner: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 2844 | …WithOwner: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 2889 | …WithOwner: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 3689 | …n (embedded Omnigent REPL terminal, no | keep-internal |  | test code |
| 3900 | …["bearer", "databricks"] as const)( | keep-internal |  | test code |
| 5693 | "omnigent:prompt-history:conv_test", | keep-internal |  | test code |
| 5708 | …ge.setItem("omnigent:prompt-history:co… | keep-internal |  | test code |
| 6789 | …startsWith("omnigent:prompt-history"))… | keep-internal |  | test code |
| 8124 | …t ROUTED = "databricks-claude-opus-4-8… | keep-internal |  | test code |

### `web/src/pages/ChatPage.statusLine.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 64 | …WithOwner: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 539 | model: "databricks-gpt-5-5", | keep-internal |  | test code |
| 556 | …tatusLabel("databricks-gpt-5-5", "xhig… | keep-internal |  | test code |
| 557 | "databricks-gpt-5-5 xHigh", | keep-internal |  | test code |

### `web/src/pages/ChatPage.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 117 | … labels: { "omnigent.closed": "true" }… | keep-internal |  | test code |
| 118 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 126 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 132 | …e chat with omnigent.closed; the "Side… | keep-internal |  | test code |
| 138 | "omnigent.closed": "true", | keep-internal |  | test code |
| 139 | "omnigent.wrapper": "codex-native-ui-s… | keep-internal |  | test code |
| 140 | "omnigent.codex_native.agent_nickname"… | keep-internal |  | test code |
| 153 | "omnigent.closed": "true", | keep-internal |  | test code |
| 154 | "omnigent.wrapper": "codex-native-ui-s… | keep-internal |  | test code |
| 155 | "omnigent.codex_native.agent_nickname"… | keep-internal |  | test code |
| 589 | model: "databricks-claude-sonnet-5", | keep-internal |  | test code |
| 844 | model: "databricks-claude-haiku-4-5", | keep-internal |  | test code |
| 1295 | "omnigent.wrapper": "codex-native-ui-s… | keep-internal |  | test code |
| 1296 | "omnigent.codex_native.agent_nickname"… | keep-internal |  | test code |
| 1333 | "omnigent.wrapper": "claude-code-nativ… | keep-internal |  | test code |
| 1334 | "omnigent.claude_native.description": … | keep-internal |  | test code |
| 1349 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 2024 | databricks_features: false, | keep-internal |  | test code |
| 2051 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 2153 | labels: { "omnigent.wrapper": "codex-c… | keep-internal |  | test code |
| 2158 | …ex.labels, "omnigent.routing.auto_harn… | keep-internal |  | test code |

### `web/src/pages/ChatPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 312 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 579 | …created by ˋomnigent run --serverˋ): | keep-internal |  | code comment |
| 599 | …by a fresh ˋomnigent runˋ after load), | keep-internal |  | code comment |
| 776 | …?.labels?.["omnigent.fork.source_id"] … | keep-internal |  | Server-set session label key omnigent.fork.sourc |
| 777 | …?.labels?.["omnigent.fork.source_id"] … | keep-internal |  | Server-set conversation label key omnigent.fork. |
| 793 | …xt from the omnigent transcript carry | keep-internal |  | code comment |
| 850 | …d, e.g. the Databricks-managed server)… | keep-internal |  | code comment |
| 1306 | // ˋomnigent hostˋ; only an unbound on… | keep-internal |  | code comment |
| 1322 | …?.labels?.["omnigent.wrapper"]} | keep-internal |  | Server-set conversation label key omnigent.wrapp |
| 1348 | …?.labels?.["omnigent.wrapper"]} | keep-internal |  | Server-set conversation label key omnigent.wrapp |
| 1471 | …session's ˋˋomnigent.wrapperˋˋ label; … | keep-internal |  | code comment |
| 1750 | …n (embedded Omnigent REPL terminal) ru… | keep-internal |  | code comment |
| 2109 | …s (embedded Omnigent REPL | keep-internal |  | code comment |
| 2148 | …session's ˋˋomnigent.wrapperˋˋ label, … | keep-internal |  | code comment |
| 2279 | …ˋˋ — not an Omnigent agent, so | keep-internal |  | code comment |
| 2288 | …session's ˋˋomnigent.wrapperˋˋ label, … | keep-internal |  | code comment |
| 2527 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 2577 | …ide, not an Omnigent head, so the | keep-internal |  | code comment |
| 3355 | …teway ids ("databricks-gpt-5-4") and p… | keep-internal |  | code comment |
| 3568 | …e.auth === "databricks" | keep-internal |  | Compares registry service auth-type enum "databr |
| 4831 | * The ˋˋomnigent.fork.source_idˋˋ labe… | keep-internal |  | code comment |
| 4841 | …ceId - The ˋomnigent.fork.source_idˋ l… | keep-internal |  | code comment |
| 4853 | // omnigent-stored transcript, so it c… | keep-internal |  | code comment |
| 4869 | …rtSource - ˋomnigent.import.sourceˋ la… | keep-internal |  | code comment |
| 5574 | …launch-time Databricks catalog; Codex … | keep-internal |  | code comment |

### `web/src/pages/ChatPage.userBubble.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 520 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 527 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 653 | …r/folders/x/omnigent-1/claude-native/a… | keep-internal |  | test code |
| 668 | …ocal\\Temp\\omnigent\\uploads\\image.p… | keep-internal |  | test code |
| 669 | …/Local/Temp/omnigent/uploads/image.png… | keep-internal |  | test code |
| 670 | …ost\\share\\omnigent\\uploads\\image.p… | keep-internal |  | test code |
| 680 | …ached: /tmp/omnigent/claude-native/abc… | keep-internal |  | test code |

### `web/src/pages/InboxPage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 875 | …ntListener("omnigent:toast", onToast); | keep-internal |  | test code |
| 876 | …ntListener("omnigent:toast", onToast))… | keep-internal |  | test code |
| 1481 | …ge.getItem("omnigent:inbox-filter")).t… | keep-internal |  | test code |

### `web/src/pages/InboxPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 120 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 209 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/pages/LoginPage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 120 | window.__OMNIGENT_BASE_PATH__ = "/prox… | keep-internal |  | test code |
| 123 | delete window.__OMNIGENT_BASE_PATH__; | keep-internal |  | test code |

### `web/src/pages/LoginPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 39 | …NAME_KEY = "omnigent.lastLoginUsername… | keep-internal |  | localStorage key remembering last login username |
| 209 | OMNIGENT_ACCOUNTS_INIT_ADMIN_PASSWORD | keep-internal |  | code identifier |
| 230 | …Top: "var(--omnigent-safe-top)", | keep-internal |  | Inline style using CSS custom property --omnigen |
| 231 | …tom: "var(--omnigent-safe-bottom)", | keep-internal |  | Inline style using CSS custom property --omnigen |

### `web/src/pages/MembersPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 485 | // OMNIGENT_ACCOUNTS_BASE_URL) is left… | keep-internal |  | code comment |

### `web/src/pages/PoliciesPage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 58 | handler: "omnigent.policies.block_cana… | keep-internal |  | test code |
| 153 | handler: "omnigent.policies.rate_limit… | keep-internal |  | test code |
| 160 | ….getByText("omnigent.policies.block_ca… | keep-internal |  | test code |
| 200 | handler: "omnigent.policies.budget", | keep-internal |  | test code |
| 235 | …dler).toBe("omnigent.policies.budget")… | keep-internal |  | test code |
| 245 | handler: "omnigent.policies.block_cana… | keep-internal |  | test code |
| 262 | …, handler: "omnigent.policies.block_ca… | keep-internal |  | test code |
| 273 | handler: "omnigent.policies.block_cana… | keep-internal |  | test code |
| 280 | handler: "omnigent.policies.rate_limit… | keep-internal |  | test code |
| 308 | handler: "omnigent.policies.block_cana… | keep-internal |  | test code |

### `web/src/pages/RegisterPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 83 | You were invited to join this Omnigent server. | change | S89 | Register page copy (BRD-01 S89). |
| 193 | …Top: "var(--omnigent-safe-top)", | keep-internal |  | Inline style using CSS custom property --omnigen |
| 194 | …tom: "var(--omnigent-safe-bottom)", | keep-internal |  | Inline style using CSS custom property --omnigen |

### `web/src/pages/SettingsPage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 287 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 303 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 357 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 379 | expect(screen.getByText("Configure general Omnigent behavior.")).toHaveClass("max-md:hidden"); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 405 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 415 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 424 | await screen.findByRole("switch", { name: "Show Omnigent from anywhere" }), | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 514 | …onst key = ˋomnigent:terminal-clipboar… | keep-internal |  | test code |
| 521 | …n(host, "getOmnigentServerIdentity").m… | keep-internal |  | test code |
| 590 | expect(screen.getByText("Choose how Omnigent looks on this device.")).toHaveClass( | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 618 | …ser mode to Databricks settings", () =… | keep-internal |  | test code |
| 621 | …n(host, "getOmnigentThemeSettingsUrl")… | keep-internal |  | test code |
| 627 | ["Use Databricks setting", "system"], | keep-internal |  | test code |
| 636 | …", { name: "Databricks appearance sett… | keep-internal |  | test code |
| 644 | …ty(window, "omnigentDesktop", { | keep-internal |  | test code |
| 666 | …", { name: "Databricks appearance sett… | keep-internal |  | test code |
| 682 | …ge.getItem("omnigent:terminal-theme"))… | keep-internal |  | test code |
| 715 | …ge.getItem("omnigent:terminal-theme"))… | keep-internal |  | test code |
| 720 | …ge.getItem("omnigent:terminal-theme"))… | keep-internal |  | test code |
| 726 | …ge.setItem("omnigent:terminal-theme", … | keep-internal |  | test code |
| 740 | …ge.getItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 747 | …ge.getItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 763 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 775 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 779 | …ge.setItem("omnigent:default-workspace… | keep-internal |  | test code |
| 796 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 827 | …ge.getItem("omnigent:pinned-workspace-… | keep-internal |  | test code |
| 843 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 855 | …defaults to Omnigent, and applies a pa… | keep-internal |  | test code |
| 860 | …he default (Omnigent) palette is selec… | keep-internal |  | test code |
| 869 | …ge.getItem("omnigent:ui-theme-palette"… | keep-internal |  | test code |
| 884 | …ge.getItem("omnigent:ui-theme-palette"… | keep-internal |  | test code |
| 885 | …ge.getItem("omnigent:custom-theme") ??… | keep-internal |  | test code |
| 921 | …ge.getItem("omnigent:custom-theme") ??… | keep-internal |  | test code |
| 998 | …ge.getItem("omnigent:custom-theme") ??… | keep-internal |  | test code |
| 1033 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1067 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1084 | …ge.setItem("omnigent:ui-font-size", "1… | keep-internal |  | test code |
| 1113 | …ge.setItem("omnigent:ui-font-size", "1… | keep-internal |  | test code |
| 1120 | …ge.setItem("omnigent:ui-font-size", "1… | keep-internal |  | test code |
| 1142 | …ge.getItem("omnigent:ui-font-family"))… | keep-internal |  | test code |
| 1152 | …ge.setItem("omnigent:ui-font-family", … | keep-internal |  | test code |
| 1162 | …ge.getItem("omnigent:ui-font-family"))… | keep-internal |  | test code |
| 1202 | …ge.setItem("omnigent:hidden-picker-age… | keep-internal |  | test code |
| 1205 | …ge.getItem("omnigent:terminal-theme"))… | keep-internal |  | test code |
| 1206 | …ge.getItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 1207 | …ge.getItem("omnigent:ui-theme-palette"… | keep-internal |  | test code |
| 1208 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 1209 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 1210 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1211 | …ge.getItem("omnigent:code-font-size"))… | keep-internal |  | test code |
| 1212 | …ge.getItem("omnigent:code-font-weight"… | keep-internal |  | test code |
| 1213 | …ge.getItem("omnigent:fold-assistant-na… | keep-internal |  | test code |
| 1233 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1234 | …ge.getItem("omnigent:code-font-size"))… | keep-internal |  | test code |
| 1235 | …ge.getItem("omnigent:code-font-weight"… | keep-internal |  | test code |
| 1237 | // Color theme is back to Omnigent. | keep-internal |  | test code |
| 1255 | …ge.getItem("omnigent:default-workspace… | keep-internal |  | test code |
| 1256 | …ge.getItem("omnigent:pinned-workspace-… | keep-internal |  | test code |
| 1269 | …ge.getItem("omnigent:fold-assistant-na… | keep-internal |  | test code |
| 1270 | …ge.getItem("omnigent:project-folder-co… | keep-internal |  | test code |
| 1271 | …ge.getItem("omnigent:project-folder-pa… | keep-internal |  | test code |
| 1273 | …ge.getItem("omnigent:hidden-picker-age… | keep-internal |  | test code |
| 1277 | …ge.setItem("omnigent:ui-font-size", "1… | keep-internal |  | test code |
| 1286 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1292 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1297 | …ge.setItem("omnigent:ui-font-size", "1… | keep-internal |  | test code |
| 1305 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1309 | …ge.setItem("omnigent:ui-font-size", "1… | keep-internal |  | test code |
| 1318 | …ge.getItem("omnigent:ui-font-size")).t… | keep-internal |  | test code |
| 1333 | …ge.getItem("omnigent:project-folder-co… | keep-internal |  | test code |
| 1334 | …ge.getItem("omnigent:project-folder-pa… | keep-internal |  | test code |
| 1338 | …ge.setItem("omnigent:project-folder-pa… | keep-internal |  | test code |
| 1344 | …ge.getItem("omnigent:project-folder-co… | keep-internal |  | test code |
| 1348 | …ge.getItem("omnigent:project-folder-co… | keep-internal |  | test code |
| 1358 | …ge.getItem("omnigent:project-folder-pa… | keep-internal |  | test code |
| 1367 | …ge.setItem("omnigent:project-folder-pa… | keep-internal |  | test code |
| 1372 | …ge.getItem("omnigent:project-folder-pa… | keep-internal |  | test code |
| 1389 | …ge.getItem("omnigent:code-font-size"))… | keep-internal |  | test code |
| 1393 | …ge.setItem("omnigent:code-font-size", … | keep-internal |  | test code |
| 1400 | …ge.setItem("omnigent:code-font-size", … | keep-internal |  | test code |
| 1408 | …ge.setItem("omnigent:code-font-size", … | keep-internal |  | test code |
| 1417 | …ge.getItem("omnigent:code-font-size"))… | keep-internal |  | test code |
| 1422 | …ge.getItem("omnigent:code-font-size"))… | keep-internal |  | test code |
| 1428 | …ge.getItem("omnigent:code-font-size"))… | keep-internal |  | test code |
| 1444 | …ge.getItem("omnigent:code-font-family"… | keep-internal |  | test code |
| 1449 | …ge.setItem("omnigent:code-font-family"… | keep-internal |  | test code |
| 1458 | …ge.getItem("omnigent:code-font-family"… | keep-internal |  | test code |
| 1469 | …ge.getItem("omnigent:code-font-weight"… | keep-internal |  | test code |
| 1473 | …ge.setItem("omnigent:code-font-weight"… | keep-internal |  | test code |
| 1478 | …ge.setItem("omnigent:code-font-weight"… | keep-internal |  | test code |
| 1620 | …ge.getItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 1624 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 1631 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 1639 | …ge.getItem("omnigent:default-base-bran… | keep-internal |  | test code |

### `web/src/pages/SettingsPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 116 | beginDatabricksConnect, | keep-internal |  | code identifier |
| 117 | disconnectDatabricks, | keep-internal |  | code identifier |
| 118 | fetchDatabricksStatus, | keep-internal |  | code identifier |
| 119 | type DatabricksConnectionStatus, | keep-internal |  | code identifier |
| 120 | } from "@/lib/databricksIntegration"; | keep-internal |  | Module import path @/lib/databricksIntegration; |
| 123 | import { useOmnigentAnalytics, useOmni… | keep-internal |  | code identifier |
| 274 | import { getOmnigentThemeSettingsUrl }… | keep-internal |  | code identifier |
| 335 | useOmnigentPageView(ˋsettings.${sectio… | keep-internal |  | code identifier |
| 500 | …wsHost ? getOmnigentThemeSettingsUrl()… | keep-internal |  | code identifier |
| 510 | ? "Follow Databricks, or force light or dark." | keep-origin |  | Names the Databricks host the app is embedded in (host theme follow); third-party integration, not publisher. |
| 521 | Databricks appearance settings | keep-origin |  | Databricks appearance-settings link (Databricks integration). |
| 533 | label: card.mode === "system" && followsHost ? "Use Databricks setting" : card.label, | keep-origin |  | "Use Databricks setting" refers to Databricks host appearance integration; integration feature name stays. |
| 808 | …tomTheme.basePalette)?.label ?? "Omnigent"}ˋ | change | S89 | Visible 'Based on Omnigent' fallback mirrors the omni palette label, which becomes Coral. |
| 1082 | "omnigent:ui-font-size", | keep-internal |  | omnigent:* localStorage key cleared on reset; st |
| 1083 | "omnigent:ui-font-family", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1084 | "omnigent:code-font-size", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1085 | "omnigent:code-font-family", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1086 | "omnigent:code-font-weight", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1087 | "omnigent:terminal-theme", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1088 | "omnigent:ui-theme-palette", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1089 | "omnigent:custom-theme", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1090 | "omnigent:default-transcript-view", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1091 | "omnigent:default-workspace-panel", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1092 | "omnigent:default-workspace-tab", | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1094 | "omnigent:hide-unconfigured-harnesses"… | keep-internal |  | omnigent:* localStorage key; storage key must st |
| 1148 | <Section title="Appearance" description="Choose how Omnigent looks on this device."> | change | S89 | Appearance section description shows Omnigent as the product name. |
| 1280 | Choose an exported Omnigent settings file to apply. This will overwrite your current | change | S89 | Import dialog copy names the product. |
| 1315 | <Section title="Git" description="Configure how Omnigent works with Git."> | change | S89 | Git section description shows Omnigent as the product name. |
| 1347 | databricks: DatabricksIntegrationContr… | keep-internal |  | code identifier |
| 1570 | …isconnect a Databricks workspace. Once… | keep-internal |  | code comment |
| 1571 | …reaches the Databricks Unity Gateway (… | keep-internal |  | code comment |
| 1572 | …Auth token. Databricks is | keep-internal |  | code comment |
| 1575 | …ere with ˋˋ?databricks=connected\|error… | keep-internal |  | code comment |
| 1577 | function DatabricksIntegrationControl(… | keep-internal |  | code identifier |
| 1578 | … = useState<DatabricksConnectionStatus… | keep-internal |  | code identifier |
| 1585 | …(await fetchDatabricksStatus()); | keep-internal |  | code identifier |
| 1594 | …params.get("databricks"); | keep-internal |  | 'databricks' query param from the OAuth connect |
| 1597 | params.delete("databricks"); | keep-internal |  | Deletes the 'databricks' redirect query param; p |
| 1606 | await disconnectDatabricks(); | keep-internal |  | code identifier |
| 1623 | return <p className="text-sm text-muted-foreground">Databricks status is unavailable.</p>; | keep-origin |  | Databricks workspace connection status text; names the third-party integration target. |
| 1633 | Databricks workspace connected. | keep-origin |  | Databricks workspace integration status. |
| 1641 | Couldn't connect your Databricks workspace. Please try again. | keep-origin |  | Databricks workspace integration error. |
| 1647 | label="Databricks" | keep-origin |  | "Databricks" label for the workspace connection integration. |
| 1652 | …${status.workspace_host}${status.databricks_user ? ˋ as ${status.databricks_user}ˋ : ""}. New sandbo… | keep-origin |  | Describes the connected Databricks workspace/user (Unity Gateway); integration feature text. |
| 1653 | : "Connect a Databricks workspace to access Unity Gateway (MCP and model serving) as you in new sand… | keep-origin |  | Prompt to connect a Databricks workspace; integration feature text. |
| 1663 | data-testid="databricks-disconnect" | keep-internal |  | data-testid attribute. |
| 1673 | placeholder="workspace-host.cloud.databricks.com" | keep-origin |  | Example Databricks workspace host placeholder; integration target URL. |
| 1677 | data-testid="databricks-workspace" | keep-internal |  | data-testid attribute. |
| 1683 | data-testid="databricks-connect" | keep-internal |  | data-testid attribute. |
| 1684 | …{() => beginDatabricksConnect(workspac… | keep-internal |  | code identifier |
| 1686 | Connect Databricks | keep-origin |  | Connect Databricks integration button. |
| 1938 | <Section title="General" description="Configure general Omnigent behavior."> | change | S89 | General section description shows Omnigent as the product name. |
| 2384 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 2415 | …shows which Omnigent CLI binary the sh… | keep-internal |  | code comment |
| 2449 | description="Run a local server and connect this machine as a runner with the Omnigent CLI." | keep-deferred |  | Names the omnigent CLI tool; deferred to OPS-03/FND-01 CLI naming. |
| 2483 | Install the Omnigent CLI, then set its path from the connect screen: | keep-deferred |  | Names the omnigent CLI; CLI name changes with OPS-03/FND-01. |
| 2527 | start: "Check when Omnigent starts", | change | S89 | Update-mode label shows Omnigent as the app name ('Check when Omnigent starts'). |

### `web/src/pages/TaskDetailPage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1242 | … starts one Omnigent session", | keep-internal |  | test code |

### `web/src/pages/TasksPage.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 128 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 154 | setOmnigentHostConfig({}); | keep-internal |  | test code |

### `web/src/pages/TasksPage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | import { useOmnigentAnalytics, useOmni… | keep-internal |  | code identifier |
| 56 | …ange } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 74 | useOmnigentPageView(view === "template… | keep-internal |  | code identifier |
| 89 | …ted outside Omnigent, so they go throu… | keep-internal |  | code comment |

### `web/src/pages/UsagePage.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 77 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/pages/effortLevels.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | model: "databricks-gpt-5-5", | keep-internal |  | test code |
| 33 | model: "databricks-gpt-5-4-mini", | keep-internal |  | test code |
| 47 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 60 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 81 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 100 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 111 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 118 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 123 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 134 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 146 | … gated on ˋˋomnigent.ui === "terminal"… | keep-internal |  | test code |
| 149 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 161 | … labels: { "omnigent.wrapper": "some-o… | keep-internal |  | test code |
| 168 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 174 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 181 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 187 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 188 | "omnigent.wrapper": "codex-native-ui", | keep-internal |  | test code |
| 201 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 220 | … labels: { "omnigent.wrapper": "nessie… | keep-internal |  | test code |
| 228 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 232 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 235 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 243 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 247 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 250 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 259 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 260 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 357 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |

### `web/src/pages/modelPicker.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | model: "databricks-gpt-5-5", | keep-internal |  | test code |
| 27 | model: "databricks-gpt-5-4-mini", | keep-internal |  | test code |
| 40 | …ame models ˋdatabricks-gpt-5-6-…ˋ. | keep-internal |  | test code |
| 105 | …L_OPTIONS, "databricks-gpt-5-5")?.id).… | keep-internal |  | test code |
| 107 | …L_OPTIONS, "databricks-gpt-5-4-mini"))… | keep-internal |  | test code |
| 120 | // A Databricks launch records ˋdatabr… | keep-internal |  | test code |
| 123 | …D_OPTIONS, "databricks-gpt-5-6-luna")?… | keep-internal |  | test code |
| 126 | …D_OPTIONS, "databricks-gpt-5-6-luna"))… | keep-internal |  | test code |

### `web/src/pages/onboarding/AuthCardShell.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …ing AnimatedOmnigentPanel with | keep-internal |  | code comment |
| 6 | …t { AnimatedOmnigentPanel } from "@/co… | keep-internal |  | Import of AnimatedOmnigentPanel component; JS id |
| 8 | import omnigentLogo from "@/assets/omnigent-starfish-icon.png"; | change-asset | S89 | Imports the Omnigent starfish icon shown on the mobile login/register pages. |
| 26 | …"calc(var(--omnigent-safe-top) + 3rem)… | keep-internal |  | CSS custom property --omnigent-safe-top. |
| 27 | …"calc(var(--omnigent-safe-bottom) + 3r… | keep-internal |  | CSS custom property --omnigent-safe-bottom. |
| 33 | src={omnigentLogo} | change-asset | S89 | Renders the starfish icon image on the mobile auth page. |
| 34 | alt="Omnigent" | change | S89 | alt text names the product Omnigent. |
| 45 | …Top: "var(--omnigent-safe-top)", | keep-internal |  | CSS custom property --omnigent-safe-top. |
| 46 | …tom: "var(--omnigent-safe-bottom)", | keep-internal |  | CSS custom property --omnigent-safe-bottom. |
| 55 | <AnimatedOmnigentPanel | keep-internal |  | code identifier |
| 61 | </AnimatedOmnigentPanel> | keep-internal |  | code identifier |

### `web/src/pages/onboarding/CliInstallStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 21 | setError("Omnigent CLI not found. Make sure omnigent is on your PATH, then check again."); | keep-deferred |  | Error names the omnigent CLI binary on PATH; deferred to OPS-03/FND-01. |
| 24 | setError("Could not check for the Omnigent CLI. Please try again."); | keep-deferred |  | Names the Omnigent CLI; deferred to OPS-03/FND-01. |
| 32 | <OnboardingHeading>Install the Omnigent CLI</OnboardingHeading> | keep-deferred |  | Install-the-CLI heading; CLI name and distribution deferred to OPS-03/FND-01 and OPS-09. |
| 39 | href="https://omnigent.ai/quickstart/install#install-omnigent" | keep-deferred |  | omnigent.ai install documentation link; deferred to OPS-09 (Coral has no distribution yet). |
| 47 | Check that <code>omnigent --version</code> works in a new terminal. | keep-deferred |  | Refers to the omnigent --version CLI command; deferred to OPS-03/FND-01. |

### `web/src/pages/onboarding/JoinTeamStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | Connect to their Omnigent server to start collaborating. | change | S89 | Join-team copy (BRD-01 S89). |

### `web/src/pages/onboarding/LandingFooter.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | href: "https://apps.apple.com/us/app/omnigent/id6783102694", | change | S89b | iOS App button removed until Coral has its own app (listed in the report). |
| 21 | href: "https://omnigent.ai/docs/interact/mobile#android-app", | change | S89b | Android App button removed until Coral has its own app (listed in the report). |
| 27 | href: "https://github.com/omnigent-ai/omnigent", | change | S89b | GitHub link points at the Omnigent repository; becomes Coral's. |
| 33 | href: "https://discord.gg/omnigent", | change | S89b | Community/support link points at the Omnigent Discord; Coral has no Discord. |
| 56 | Maintained by Databricks and the Omnigent community | change | S89b | Maintained-by line becomes "Built on Omnigent". |

### `web/src/pages/onboarding/LandingStep.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 37 | …example.com/omnigent?o=1"] }); | keep-internal |  | test code |
| 41 | …example.com/omnigent?o=1"); | keep-internal |  | test code |

### `web/src/pages/onboarding/LandingStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 102 | Meet Omnigent | change | S89b | Onboarding landing heading names the product. |
| 204 | placeholder="Enter Omnigent server URL" | change | S89b | Placeholder names the product's server ('Omnigent server URL'). |

### `web/src/pages/onboarding/LocalIntroStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 41 | /** CLI installed → "Start"/"Open Omnigent"; missing → "Install Omnigent". */ | change | S89b | Changed with its seam: code comment |
| 43 | /** The local server is stopped, so the action boots it ("Start Omnigent"). */ | change | S89b | Changed with its seam: code comment |
| 50 | <OnboardingHeading>Set up Omnigent locally</OnboardingHeading> | change | S89b | Onboarding heading uses Omnigent as the product name. |

### `web/src/pages/onboarding/RunnerStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 31 | …ed) → "Open Omnigent"; new → "Install … | keep-internal |  | code comment |

### `web/src/pages/onboarding/ServerSelectStep.render.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | fireEvent.click(screen.getByRole("button", { name: /open omnigent/i })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 78 | expect(screen.getByRole("button", { name: /open omnigent/i })).toBeEnabled(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 98 | expect(screen.getByRole("button", { name: /open omnigent/i })).toBeEnabled(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 100 | await waitFor(() => expect(screen.getByText("Omnigent server")).toBeInTheDocument()); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 123 | fireEvent.click(screen.getByRole("button", { name: /open omnigent/i })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/pages/onboarding/ServerSelectStep.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 34 | …ization and Databricks organization ha… | keep-internal |  | test code |
| 38 | …space.cloud.databricks.com/omnigent?o=… | keep-internal |  | test code |
| 39 | …space.cloud.databricks.com/?o=123", | keep-internal |  | test code |
| 41 | …space.cloud.databricks.com:8080/?o=123… | keep-internal |  | test code |
| 42 | …space.cloud.databricks.com:8080/?o=123… | keep-internal |  | test code |

### `web/src/pages/onboarding/ServerSelectStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 2 | …rs from the omnigentSetup bridge as se… | keep-internal |  | code comment |
| 48 | const CREATE_SERVER_URL = "https://omnigent.ai/"; | change | S89b | 'Create server' link opens the Omnigent website; website links become Coral's. |
| 63 | …erver port (omnigent/host/local_server… | keep-internal |  | code comment |
| 67 | *  "Start Omnigent" boots. Any other l… | keep-internal |  | code comment |
| 86 | … globalThis.omnigentUrl.normalizeUrl(r… | keep-internal |  | code identifier |
| 154 | /** CLI status for local setup; remote servers always offer "Open Omnigent". */ | change | S89b | Changed with its seam: code comment |
| 348 | ? "Omnigent server" | change | S89b | Reachability label 'Omnigent server' is product-server wording shown in the server list. |
| 441 | placeholder="Enter Omnigent server URL" | change | S89b | Placeholder names the product's server ('Omnigent server URL'). |

### `web/src/pages/onboarding/ServerSelectorV2.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | expect(screen.getByRole("heading", { name: "Meet Omnigent" })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 36 | // only after clicking Install Omnigent. | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 37 | expect(screen.getByRole("heading", { name: /set up omnigent locally/i })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 41 | it("Install Omnigent from the local intro starts the install", () => { | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 44 | fireEvent.click(screen.getByRole("button", { name: /install omnigent/i })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 53 | expect(screen.queryByRole("heading", { name: "Meet Omnigent" })).not.toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 58 | expect(screen.getByRole("heading", { name: "Meet Omnigent" })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 101 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 135 | expect(screen.getByRole("heading", { name: "Meet Omnigent" })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 141 | expect(screen.getByRole("heading", { name: "Meet Omnigent" })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 150 | it("a local install that's down reads 'Start Omnigent' and boots it", async () => { | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 166 | fireEvent.click(screen.getByRole("button", { name: "Start Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 172 | it("a local install that's up reads 'Open Omnigent' and opens the exact URL", async () => { | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 185 | expect(await screen.findByText("Omnigent server")).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 186 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 207 | fireEvent.click(screen.getByRole("button", { name: "Install Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 230 | expect(await screen.findByText("Omnigent server")).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 231 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 252 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 261 | expect(screen.getByRole("button", { name: "Start Omnigent" })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 265 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 339 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 370 | fireEvent.click(await screen.findByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 401 | fireEvent.click(await screen.findByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 412 | expect(screen.getByRole("heading", { name: "Meet Omnigent" })).toBeInTheDocument(); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 418 | action: string \| RegExp = /(install\|open) omnigent/i, | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 577 | return screen.getByRole("button", { name: /open omnigent/i }); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 681 | "Open Omnigent", | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 705 | "Install Omnigent", | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 858 | fireEvent.click(screen.getByRole("button", { name: "Install Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 874 | fireEvent.click(screen.getByRole("button", { name: "Install Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 886 | await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" }))); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 889 | await act(async () => fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" }))); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 905 | fireEvent.click(await screen.findByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 921 | fireEvent.click(screen.getByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 934 | fireEvent.click(screen.getByRole("button", { name: "Install Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/pages/onboarding/ServerSelectorV2.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | * ˋomnigentSetupˋ bridge via the ˋsetu… | keep-internal |  | code comment |
| 10 | …t { AnimatedOmnigentPanel } from "@/co… | keep-internal |  | Import of AnimatedOmnigentPanel component; JS id |
| 80 | …hether the ˋomnigentˋ CLI is already i… | keep-internal |  | code comment |
| 112 | …Install the omnigent CLI (macOS). Pres… | keep-internal |  | code comment |
| 230 | …!globalThis.omnigentUrl.isPlainHttpRem… | keep-internal |  | code identifier |
| 424 | <AnimatedOmnigentPanel | keep-internal |  | code identifier |
| 526 | </AnimatedOmnigentPanel> | keep-internal |  | code identifier |
| 550 | ? { label: "Opening Omnigent", hint: "Connecting to the local server…" } | change | S89b | Setup terminal heading 'Opening Omnigent' uses Omnigent as the product name. |
| 551 | : { label: "Starting Omnigent", hint: "Starting the local server…" }; | change | S89b | Setup terminal heading 'Starting Omnigent' uses Omnigent as the product name. |

### `web/src/pages/onboarding/SetupTerminalStep.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | …se, error: "omnigent CLI not found" }) | keep-internal |  | test code |
| 24 | …findByText("omnigent CLI not found")).… | keep-internal |  | test code |
| 183 | ….("Starting omnigent server on 127.0.0… | keep-internal |  | test code |
| 186 | …t("Starting omnigent server on 127.0.0… | keep-internal |  | test code |
| 205 | … => emit("$ omnigent host --server htt… | keep-internal |  | test code |

### `web/src/pages/onboarding/SetupTerminalStep.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 4 | …cal server (omnigent server | keep-internal |  | code comment |
| 29 | runningLabel = "Starting Omnigent", | change | S89b | Default run-phase heading shown in desktop onboarding terminal step uses product name. |
| 45 | … ("Starting Omnigent" / "Connecting…")… | keep-internal |  | code comment |
| 120 | setError(res.errorMessage ?? res.error ?? "Couldn't install the Omnigent CLI."); | keep-deferred |  | Error names the omnigent CLI being installed by the Omnigent installer (cli_install.js); changes with OPS-09 distribution / FND-01 CLI name. |
| 155 | ? "Omnigent is ready" | change | S89b | Onboarding ready heading shows product name to user. |
| 157 | ? "Couldn't set up Omnigent" | change | S89b | Onboarding failure heading shows product name to user. |
| 159 | ? "Installing the Omnigent CLI" | keep-deferred |  | Heading describes installing the omnigent CLI package via Omnigent installer; changes with OPS-09 / FND-01 CLI name. |
| 215 | {error ?? "Could not set up Omnigent."} | change | S89b | Fallback error text shown in onboarding alert uses product name. |

### `web/src/pages/onboarding/mockSetup.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1 | …e Electron ˋomnigentSetupˋ bridge, so … | keep-internal |  | code comment |
| 14 | …            omnigent CLI already insta… | keep-internal |  | code comment |
| 97 | "Installing uv (required by the Omnigent installer)…", | keep-deferred |  | Dev-only mock mirroring cli_install.js installer output (Omnigent installer); changes with OPS-09. |
| 98 | "Installing the Omnigent CLI…", | keep-deferred |  | Dev-only mock mirroring cli_install.js 'Installing the Omnigent CLI' output; changes with OPS-09 / FND-01. |
| 99 | "uv tool install --force --python 3.12 omnigent", | keep-deferred |  | Install command (uv tool install omnigent) in dev-only mock; OPS-09. |
| 100 | "Installed omnigent", | keep-deferred |  | Mock installer output naming omnigent package; OPS-09. |
| 132 | ˋ$ omnigent host --server ${url}ˋ, | keep-deferred |  | omnigent host CLI command in dev-only mock runner log; OPS-03/FND-01. |

### `web/src/pages/onboarding/primitives.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | if (!installed) return "Install Omnigent"; | change | S89b | Onboarding primary button label uses product name (primitives copy). |
| 30 | return startsLocal ? "Start Omnigent" : "Open Omnigent"; | change | S89b | Onboarding primary button labels Start/Open use product name. |

### `web/src/pages/settings/GlobalShortcutControl.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | const SWITCH_NAME = "Show Omnigent from anywhere"; | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 22 | …, unknown>).omnigentDesktop = bridge; | keep-internal |  | test code |
| 28 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |

### `web/src/pages/settings/GlobalShortcutControl.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 146 | label="Show Omnigent from anywhere" | change | S89 | Settings switch label shows product name. |
| 150 | description="Brings Omnigent to the front from any app." | change | S89 | Settings description text shows product name. |

### `web/src/pages/settings/HarnessFixDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | databricks_features: false, | keep-internal |  | test code |
| 102 | [{ family: "databricks", source: "isaa… | keep-internal |  | test code |
| 122 | …[{ family: "databricks", source: "isaa… | keep-internal |  | test code |
| 187 | …x, then the Databricks Unity Gateway c… | keep-internal |  | test code |
| 319 | expect(screen.getByText(/quit and reopen the Omnigent app/)).toBeVisible(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 1264 | …for %s when Databricks is detected", (… | keep-internal |  | test code |
| 1274 | ["without a Databricks entry", [], "Pe… | keep-internal |  | test code |
| 1276 | "with a Databricks entry", | keep-internal |  | test code |
| 1277 | [{ family: "databricks", source: "isaa… | keep-internal |  | test code |
| 1363 | …[{ family: "databricks", source: "isaa… | keep-internal |  | test code |
| 1429 | …iption when Databricks is not detected… | keep-internal |  | test code |

### `web/src/pages/settings/HarnessFixDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 129 | …family === "databricks") === true); | keep-internal |  | Credential family identifier 'databricks' compar |
| 1140 | Choose {harnessLabel}, then the Databricks Unity Gateway credential. | keep-origin |  | Databricks Unity Gateway credential (Databricks integration). |
| 1196 | <code className="font-mono text-foreground">tmux -V</code> works in a terminal. If Omnigent | change | S89 | Help copy names the product. |
| 1197 | still can&apos;t find it, quit and reopen the Omnigent app. | change | S89 | Help copy names the product app. |

### `web/src/pages/settings/SettingsHarnessesSection.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 151 | let databricksFeatures = true; | keep-internal |  | test code |
| 154 | databricks_features: databricksFeature… | keep-internal |  | test code |
| 260 | databricksFeatures = true; | keep-internal |  | test code |
| 460 | ….getByText("Databricks-managed credent… | keep-internal |  | test code |
| 464 | …tive in ~\/.omnigent\/config.yaml/)).t… | keep-internal |  | test code |
| 467 | … label when databricks_features is fal… | keep-internal |  | test code |
| 468 | databricksFeatures = false; | keep-internal |  | test code |
| 475 | ….getByText("Databricks-managed credent… | keep-internal |  | test code |

### `web/src/pages/settings/SettingsHarnessesSection.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 657 | description: "Managed credential via the Databricks Unity Gateway", | keep-origin |  | Names Databricks Unity Gateway, a third-party integration target for managed credentials. |
| 908 | env: ˋFrom OMNIGENT_${harness.replace(… | keep-internal |  | Shows OMNIGENT_*_PATH env var name, which stays |
| 909 | …ness} in ~/.omnigent/config.yaml on ${… | keep-internal |  | Shows ~/.omnigent/config.yaml path, internal con |

### `web/src/server-selector-v2.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …window as { omnigentSetup?: unknown })… | keep-internal |  | test code |
| 11 | … a minimal ˋomnigentSetupˋ bridge; ˋov… | keep-internal |  | test code |
| 13 | …window as { omnigentSetup?: unknown })… | keep-internal |  | test code |
| 27 | await screen.findByRole("button", { name: /open omnigent/i }); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 63 | const openButton = await screen.findByRole("button", { name: /open omnigent/i }); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 93 | fireEvent.click(await screen.findByRole("button", { name: /open omnigent/i })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 117 | fireEvent.click(screen.getByRole("button", { name: "Install Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 120 | "https://omnigent.ai/quickstart/instal… | keep-internal |  | test code |
| 145 | fireEvent.click(await screen.findByRole("button", { name: "Open Omnigent" })); | change | S89b | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/server-selector-v2.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | …he shell's ˋomnigentSetupˋ preload bri… | keep-internal |  | code comment |
| 22 | const CLOUD_DOCS_URL = "https://omnigent.ai/docs/deploy/overview"; | keep-deferred |  | omnigent.ai documentation link (cloud deploy docs); OPS-09. |
| 24 | /** The ˋomnigentSetupˋ preload bridge… | keep-internal |  | code comment |
| 25 | interface OmnigentSetup { | keep-internal |  | code identifier |
| 56 | …upBridge(): OmnigentSetup \| undefined … | keep-internal |  | code identifier |
| 57 | …nknown as { omnigentSetup?: OmnigentSe… | keep-internal |  | code identifier |
| 88 | …hether the ˋomnigentˋ CLI is installed… | keep-internal |  | code comment |
| 274 | "The installer finished but the omnigent CLI still isn't detected."; | keep-deferred |  | Error names the omnigent CLI binary detection; OPS-03/FND-01. |
| 276 | "Try opening a new terminal, or install it from https://omnigent.ai/."; | keep-deferred |  | Points to omnigent.ai for install; OPS-09 (Coral has no distribution yet). |

### `web/src/shell/AddAgentDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | …PREFIXˋˋ in omnigent/server/routes/ses… | keep-internal |  | code comment |
| 125 | <code className="font-mono">omnigent server --agent</code>. | keep-deferred |  | References omnigent server CLI command; OPS-03/FND-01. |

### `web/src/shell/AppShell.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 512 | databricks_features: false, | keep-internal |  | test code |
| 917 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 944 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 972 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 987 | …ge.setItem("omnigent.web.panel-key:con… | keep-internal |  | test code |
| 1020 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1034 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 1051 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 1067 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 1105 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1130 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1150 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1169 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1202 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1208 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1246 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1264 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1299 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 1300 | "omnigent.wrapper": "claude-code-nativ… | keep-internal |  | test code |
| 1343 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 1344 | "omnigent.wrapper": "codex-native-ui", | keep-internal |  | test code |
| 1374 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1411 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 1412 | "omnigent.wrapper": "claude-code-nativ… | keep-internal |  | test code |
| 1451 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1495 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1523 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 1553 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 1594 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1636 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1651 | …ge.setItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 1656 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1671 | …ge.setItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 1676 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1696 | …ge.setItem("omnigent:default-transcrip… | keep-internal |  | test code |
| 1719 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 1758 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 2252 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 2424 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 3067 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3109 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3120 | "omnigent.web.panel-key:conv_browser_t… | keep-internal |  | test code |
| 3154 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3204 | "omnigent.web.panel-key:conv_workspace… | keep-internal |  | test code |
| 3450 | …ge.setItem("omnigent:default-workspace… | keep-internal |  | test code |
| 3465 | …ge.setItem("omnigent:default-workspace… | keep-internal |  | test code |
| 3605 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3672 | …ge.setItem("omnigent:default-workspace… | keep-internal |  | test code |
| 3709 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3738 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3788 | …ge.setItem("omnigent:default-workspace… | keep-internal |  | test code |
| 3803 | …ge.setItem("omnigent.web.panel-key:con… | keep-internal |  | test code |
| 3965 | …he embedded Omnigent | keep-internal |  | test code |
| 3983 | …DK session: omnigent.ui stamped by the | keep-internal |  | test code |
| 3985 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 4019 | …ge.setItem("omnigent:default-workspace… | keep-internal |  | test code |
| 4343 | "omnigent.wrapper": "claude-code-nativ… | keep-internal |  | test code |
| 4344 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 4386 | …s (embedded Omnigent REPL, ˋomnigent.u… | keep-internal |  | test code |
| 4398 | labels: { "omnigent.ui": "terminal" }, | keep-internal |  | test code |
| 4569 | labels: { "omnigent.host_type": "manag… | keep-internal |  | test code |
| 4575 | …anaged ? { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 4644 | labels: { "omnigent.host_type": "manag… | keep-internal |  | test code |
| 4662 | labels: { "omnigent.host_type": "manag… | keep-internal |  | test code |
| 4801 | labels: { "omnigent.side_chat": "1" }, | keep-internal |  | test code |
| 4832 | …", null, { "omnigent.side_chat": "1" }… | keep-internal |  | test code |
| 4894 | labels: { "omnigent.side_chat": "1" }, | keep-internal |  | test code |
| 5269 | expect(screen.getByText(/This Omnigent server allows read-only sharing/)).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 5318 | "Sharing has been disabled for this Omnigent server.", | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 5571 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 5608 | … labels: { "omnigent.ui": "terminal" }… | keep-internal |  | test code |
| 5822 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 5876 | …ge.setItem("omnigent:always-steer", te… | keep-internal |  | test code |
| 5907 | …ge.setItem("omnigent:always-steer", "t… | keep-internal |  | test code |
| 5928 | …ge.setItem("omnigent:always-steer", "t… | keep-internal |  | test code |
| 5933 | …ge.setItem("omnigent:always-steer", "f… | keep-internal |  | test code |
| 5941 | …ge.setItem("omnigent:always-steer", "f… | keep-internal |  | test code |
| 5944 | …ge.setItem("omnigent:always-steer", "t… | keep-internal |  | test code |
| 5956 | …ge.setItem("omnigent:always-steer", "f… | keep-internal |  | test code |
| 5971 | …ge.setItem("omnigent:always-steer", "t… | keep-internal |  | test code |
| 5997 | …ge.setItem("omnigent:always-steer", "f… | keep-internal |  | test code |
| 6066 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |

### `web/src/shell/AppShell.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 744 | …t carries ˋˋomnigent.uiˋˋ/ˋˋomnigent.w… | keep-internal |  | code comment |
| 751 | …sionLabels["omnigent.ui"] === "termina… | keep-internal |  | Session label key omnigent.ui set/parsed by serv |
| 767 | …sionLabels["omnigent.wrapper"] === "cl… | keep-internal |  | Session label key omnigent.wrapper; internal pro |
| 770 | …/ (embedded Omnigent REPL terminal) ha… | keep-internal |  | code comment |
| 772 | …sionLabels["omnigent.wrapper"]); | keep-internal |  | Session label key omnigent.wrapper; internal pro |
| 882 | …/ admin set OMNIGENT_SHARING_MODE=off … | keep-internal |  | code comment |
| 890 | : "Sharing has been disabled for this Omnigent server."; | change | S89 | Web copy of sharing-disabled reason shown in Share tooltip; 'Omnigent server' product wording. |
| 1134 | omnigentDesktop?: { | keep-internal |  | code identifier |
| 1155 | const desktop = w.omnigentDesktop; | keep-internal |  | code identifier |
| 1241 | …orageKey = ˋomnigent.web.panel-key:${c… | keep-internal |  | sessionStorage key omnigent.web.panel-key; stora |
| 1296 | …orageKey = ˋomnigent.web.panel-key:${c… | keep-internal |  | sessionStorage key omnigent.web.panel-key; stora |
| 1403 | …ge.getItem(ˋomnigent.web.panel-key:${c… | keep-internal |  | sessionStorage key omnigent.web.panel-key; stora |
| 1462 | …ge.setItem(ˋomnigent.web.panel-key:${c… | keep-internal |  | sessionStorage key omnigent.web.panel-key; stora |

### `web/src/shell/ChatHeader.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 152 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 542 | … agent — an Omnigent internal the serv… | keep-internal |  | test code |
| 959 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |

### `web/src/shell/ChatHeader.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 50 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 182 | …session's ˋˋomnigent.wrapperˋˋ label, … | keep-internal |  | code comment |
| 184 | … name is an Omnigent | keep-internal |  | code comment |
| 373 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/shell/CliCommandBlock.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 13 | "Run ˋomnigent login https://xˋ and re… | keep-internal |  | test code |
| 19 | ….getByText("omnigent login https://x")… | keep-internal |  | test code |
| 20 | ….getByText("omnigent setup").tagName).… | keep-internal |  | test code |
| 26 | …CalledWith("omnigent setup"); | keep-internal |  | test code |

### `web/src/shell/CloseWindowDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 26 | expect(screen.getByRole("heading", { name: "Quit Omnigent?" })).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 28 | screen.getByText("This is the only open window, so closing it quits Omnigent."), | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/shell/CloseWindowDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 40 | <DialogTitle>{quits ? "Quit Omnigent?" : "Close this window?"}</DialogTitle> | change | S89 | Dialog title 'Quit Omnigent?' shows product name. |
| 43 | ? "This is the only open window, so closing it quits Omnigent." | change | S89 | Dialog description shows product name. |

### `web/src/shell/CodeViewer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 520 | // Databricks browser sign-in treats t… | keep-internal |  | test code |

### `web/src/shell/CommandPalette.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 448 | … sized to --omnigent-viewport-height, | keep-internal |  | code comment |
| 461 | …ght: "var(--omnigent-viewport-height, … | keep-internal |  | CSS custom property --omnigent-viewport-height; |
| 462 | …ght: "var(--omnigent-viewport-height, … | keep-internal |  | CSS custom property --omnigent-viewport-height; |
| 466 | …ight, var(--omnigent-safe-top, 0px))", | keep-internal |  | CSS custom property --omnigent-safe-top; interna |
| 467 | …tom: "var(--omnigent-safe-bottom, 0px)… | keep-internal |  | CSS custom property --omnigent-safe-bottom; inte |

### `web/src/shell/ConnectHostInstructions.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 37 | …xport const DatabricksLakeboxTab: Stor… | keep-internal |  | test code |
| 41 | …ERVER_INFO, databricks_features: true … | keep-internal |  | test code |
| 47 | …", { name: "Databricks Lakebox" })); | keep-internal |  | test code |

### `web/src/shell/ConversationBreadcrumb.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 78 | … session's ˋomnigent.wrapperˋ label — … | keep-internal |  | code comment |

### `web/src/shell/CreateAgentDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | …ent names (ˋomnigent/spec/validator.py… | keep-internal |  | code comment |

### `web/src/shell/CreatedBySession.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | …ABEL_KEY = "omnigent.created_by_sessio… | keep-internal |  | Session label key omnigent.created_by_session_id |

### `web/src/shell/FileViewer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 433 | …, unknown>).omnigentNative = { kind: "… | keep-internal |  | test code |
| 444 | …, unknown>).omnigentNative; | keep-internal |  | test code |
| 2082 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 2102 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |

### `web/src/shell/FileViewer.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 386 | // ˋomnigent run --serverˋ. | keep-internal |  | code comment |

### `web/src/shell/ForkSessionDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 86 | …Users/a/git/omnigent")} | keep-internal |  | test code |
| 341 | ["Databricks Sandbox host", "lakebox",… | keep-internal |  | test code |
| 344 | ["Databricks Sandbox host", "lakebox",… | keep-internal |  | test code |
| 349 | …pshot" ? { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 781 | … the copied Omnigent items — the codex… | keep-internal |  | test code |
| 823 | …rce here is databricks_coding_agent (o… | keep-internal |  | test code |
| 826 | …("ag_dbx", "databricks_coding_agent", … | keep-internal |  | test code |
| 827 | …play_name: "databricks_coding_agent", | keep-internal |  | test code |
| 835 | name: "databricks_coding_agent (fork a… | keep-internal |  | test code |
| 847 | … the copied Omnigent items. | keep-internal |  | test code |
| 1168 | …Users/a/git/omnigent"); | keep-internal |  | test code |
| 1175 | "/Users/a/git/omnigent", | keep-internal |  | test code |
| 1569 | …type "~/git/omnigent" into the field a… | keep-internal |  | test code |
| 1580 | …, so "~/git/omnigent" expands to "/Use… | keep-internal |  | test code |
| 1591 | …lue: "~/git/omnigent" } }); | keep-internal |  | test code |
| 1605 | "/Users/a/git/omnigent", | keep-internal |  | test code |
| 1624 | …lue: "~/git/omnigent" } }); | keep-internal |  | test code |
| 1633 | …Users/a/git/omnigent"); | keep-internal |  | test code |
| 1641 | "/Users/a/git/omnigent", | keep-internal |  | test code |
| 1757 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 1772 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 2153 | "omnigent.host_type": "managed", | keep-internal |  | test code |
| 2154 | …/github.com/databricks-eng/universe", | keep-internal |  | test code |
| 2202 | …/github.com/databricks-eng/universe"] … | keep-internal |  | test code |
| 2221 | it("forks a Databricks Sandbox source … | keep-internal |  | test code |
| 2223 | … labels: { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 2242 | "Databricks Sandbox", | keep-internal |  | test code |

### `web/src/shell/ForkSessionDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 401 | …?.labels?.["omnigent.codex_native.bypa… | keep-internal |  | Session label key omnigent.codex_native.bypass_s |
| 990 | // "databricks_coding_agent (fork ag_a… | keep-internal |  | code comment |
| 1031 | //      Omnigent transcript and native… | keep-internal |  | code comment |

### `web/src/shell/HarnessCredentialForm.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 105 | …er offers a Databricks detection resul… | keep-internal |  | test code |
| 107 | { family: "databricks", source: "isaac… | keep-internal |  | test code |
| 108 | { family: "databricks", source: "Datab… | keep-internal |  | test code |
| 113 | …(/isaac CLI\|Databricks profile/)).toBe… | keep-internal |  | test code |

### `web/src/shell/HarnessCredentialForm.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | … credential omnigent detected on the h… | keep-internal |  | code comment |
| 63 | credential.family !== "databricks" && | keep-internal |  | Credential family identifier 'databricks' compar |

### `web/src/shell/HarnessSetupDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 13 | …single "run omnigent | keep-internal |  | code comment |

### `web/src/shell/HeaderConversationMenu.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 154 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 718 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 745 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 755 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 770 | labels: { "omnigent.pinned": "17000000… | keep-internal |  | test code |
| 791 | omnigentDesktop: { | keep-internal |  | test code |
| 804 | …ty(window, "omnigentDesktop"); | keep-internal |  | test code |

### `web/src/shell/HeaderConversationMenu.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 72 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 134 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |

### `web/src/shell/HtmlCommentViewer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { setOmnigentHostConfig, type H… | keep-internal |  | test code |
| 18 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 73 | setOmnigentHostConfig({ htmlPreviewFra… | keep-internal |  | test code |
| 85 | setOmnigentHostConfig({ htmlPreviewFra… | keep-internal |  | test code |

### `web/src/shell/HtmlCommentViewer.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 19 | …bedRoot, getOmnigentHtmlPreviewFrame }… | keep-internal |  | code identifier |
| 106 | …wFrame = getOmnigentHtmlPreviewFrame()… | keep-internal |  | code identifier |

### `web/src/shell/ImportSessionsPanel.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 89 | <code className="rounded bg-muted px-1 py-0.5 font-mono">omnigent host</code> from your | keep-deferred |  | Instructs running omnigent host CLI command; OPS-03/FND-01. |

### `web/src/shell/MarkdownRichTextViewer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 326 | expect(screen.getByText(/Omnigent is still working/)).toBeDefined(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 333 | expect(screen.queryByText(/Omnigent is still working/)).toBeNull(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 349 | expect(screen.queryByText(/Omnigent is still working/)).toBeNull(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 357 | expect(screen.queryByText(/Omnigent is still working/)).toBeNull(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 367 | expect(screen.queryByText(/Omnigent is still working/)).toBeNull(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 375 | … = "https://omnigent.ai/docs/build/har… | keep-internal |  | test code |

### `web/src/shell/MarkdownRichTextViewer.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 562 | Omnigent is still working — edits you make now may be overwritten when it saves this file. | change | S89 | Editor warning names the product. |

### `web/src/shell/MobilePanelDrawer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 27 | vi.stubGlobal("omnigentNative", { | keep-internal |  | test code |

### `web/src/shell/MonacoCodeEditor.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 296 | …ge.setItem("omnigent:code-font-weight"… | keep-internal |  | test code |

### `web/src/shell/NewChatDialog.flow.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 81 | …CENT_KEY = "omnigent:recent-workspaces… | keep-internal |  | test code |
| 85 | …TORY_KEY = "omnigent:prompt-history:co… | keep-internal |  | test code |
| 294 | databricks_features: false, | keep-internal |  | test code |
| 849 | "omnigent.client_create_token": expect… | keep-internal |  | test code |
| 887 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 894 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 902 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 910 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 1143 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 1148 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 1192 | …hygiene for omnigent:recent-workspaces… | keep-internal |  | test code |
| 1243 | …ng).labels["omnigent.client_create_tok… | keep-internal |  | test code |
| 1248 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 1275 | …ng).labels["omnigent.client_create_tok… | keep-internal |  | test code |
| 1279 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 1286 | labels: { "omnigent.client_create_toke… | keep-internal |  | test code |
| 1404 | …: { value: "omnigent" } }); | keep-internal |  | test code |
| 1664 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 1665 | "omnigent.wrapper": "claude-code-nativ… | keep-internal |  | test code |
| 1666 | "omnigent.client_create_token": expect… | keep-internal |  | test code |
| 1696 | "omnigent.ui": "terminal", | keep-internal |  | test code |
| 1697 | "omnigent.wrapper": "antigravity-nativ… | keep-internal |  | test code |
| 1698 | "omnigent.client_create_token": expect… | keep-internal |  | test code |
| 1730 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 1740 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 1786 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 1828 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 1849 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 1866 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 1913 | …y.labels?.["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 1932 | …ge.getItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 1940 | …ge.getItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 1962 | …ge.getItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 1985 | …y.labels?.["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 2014 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 2036 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 2060 | …y.labels?.["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 2071 | …ol hook, so Omnigent cannot re-gate to… | keep-internal |  | test code |
| 2141 | id: "omnigent-openai/system.ai.gpt-5-6… | keep-internal |  | test code |
| 2142 | model: "omnigent-openai/system.ai.gpt-… | keep-internal |  | test code |
| 2146 | id: "omnigent/databricks-claude-sonnet… | keep-internal |  | test code |
| 2147 | model: "omnigent/databricks-claude-son… | keep-internal |  | test code |
| 2162 | …agent-model-omnigent-openai/system.ai.… | keep-internal |  | test code |
| 2166 | …e("title", "omnigent-openai/system.ai.… | keep-internal |  | test code |
| 2175 | …ride).toBe("omnigent-openai/system.ai.… | keep-internal |  | test code |
| 2177 | …y.labels?.["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 2179 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 2180 | ).toBe("omnigent-openai/system.ai.gpt-… | keep-internal |  | test code |
| 2188 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 2211 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 2234 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 2255 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 2275 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 2288 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 2354 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 2375 | …y.labels?.["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 2537 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2553 | …ge.getItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2559 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2573 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2585 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2601 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2616 | …ge.setItem("omnigent:default-base-bran… | keep-internal |  | test code |
| 2719 | …ge.getItem("omnigent:last-agent-id")).… | keep-internal |  | test code |
| 2743 | …ge.setItem("omnigent:last-agent-id", "… | keep-internal |  | test code |

### `web/src/shell/NewChatDialog.projectCreate.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 66 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 75 | …CENT_KEY = "omnigent:recent-workspaces… | keep-internal |  | test code |
| 262 | databricks_features: false, | keep-internal |  | test code |
| 334 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 426 | …ge.setItem("omnigent:last-agent-id", "… | keep-internal |  | test code |
| 438 | "omnigent.client_create_token": expect… | keep-internal |  | test code |
| 813 | setOmnigentHostConfig({ docsLinks: { n… | keep-internal |  | test code |

### `web/src/shell/NewChatDialog.projectPrefill.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 68 | …CENT_KEY = "omnigent:recent-workspaces… | keep-internal |  | test code |
| 199 | databricks_features: false, | keep-internal |  | test code |
| 234 | databricks_features: false, | keep-internal |  | test code |
| 269 | databricks_features: false, | keep-internal |  | test code |
| 427 | …ge.setItem("omnigent:last-agent-id", "… | keep-internal |  | test code |
| 464 | …ge.setItem("omnigent:last-agent-id", "… | keep-internal |  | test code |
| 865 | …IONS_KEY = "omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 1447 | …ge.setItem("omnigent:last-agent-id", "… | keep-internal |  | test code |
| 1549 | …TREE_KEY = "omnigent:always-use-worktr… | keep-internal |  | test code |

### `web/src/shell/NewChatDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 139 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 437 | id: "databricks-gpt-5-5", | keep-internal |  | test code |
| 449 | id: "databricks-gpt-5-6", | keep-internal |  | test code |
| 474 | …CENT_KEY = "omnigent:recent-workspaces… | keep-internal |  | test code |
| 476 | …IONS_KEY = "omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 478 | …NESS_KEY = "omnigent:last-harness-by-a… | keep-internal |  | test code |
| 480 | …GENT_KEY = "omnigent:last-agent-id"; | keep-internal |  | test code |
| 1312 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 1458 | databricks_features: false, | keep-internal |  | test code |
| 1491 | it.each(["/omnigent", "/omnigent/", "/… | keep-internal |  | test code |
| 1599 | …nding({}, "/omnigent/?project=docs&pro… | keep-internal |  | test code |
| 1602 | "/omnigent/?project=docs&o=123#compose… | keep-internal |  | test code |
| 1665 | …agent-model-databricks-gpt-5-6"), | keep-internal |  | test code |
| 1686 | model_override: "databricks-gpt-5-6", | keep-internal |  | test code |
| 1952 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 2102 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 2252 | setOmnigentHostConfig({ serverIdentity… | keep-internal |  | test code |
| 2254 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 2264 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 2642 | …agent-model-databricks-gpt-5-6")); | keep-internal |  | test code |
| 2667 | model_override: "databricks-gpt-5-6", | keep-internal |  | test code |
| 2669 | labels: { "omnigent.codex_native.bypas… | keep-internal |  | test code |
| 3294 | …ired — run ˋomnigent login https://app… | keep-internal |  | test code |
| 3331 | databricksInternalFeatures: true, | keep-internal |  | test code |
| 3334 | …ty(window, "omnigentDesktop", { | keep-internal |  | test code |
| 3348 | …ty(window, "omnigentDesktop"); | keep-internal |  | test code |
| 3404 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 3480 | …hFeatures({ databricksInternalFeatures… | keep-internal |  | test code |
| 3650 | …ty(window, "omnigentDesktop", { | keep-internal |  | test code |
| 3656 | …ty(window, "omnigentDesktop", { | keep-internal |  | test code |
| 3666 | …lvedValue({ databricksInternalFeatures… | keep-internal |  | test code |
| 3667 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3681 | …un on Arca (Databricks-internal, MDM-g… | keep-internal |  | test code |
| 3689 | databricksInternalFeatures: true, | keep-internal |  | test code |
| 3729 | …ge.setItem("omnigent:arca-host-id", "a… | keep-internal |  | test code |
| 3747 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3751 | …lvedValue({ databricksInternalFeatures… | keep-internal |  | test code |
| 3752 | …ge.setItem("omnigent:arca-host-id", "a… | keep-internal |  | test code |
| 3769 | …ge.setItem("omnigent:arca-host-id", "a… | keep-internal |  | test code |
| 3774 | …ps://server.databricks.com/omnigent", … | keep-internal |  | test code |
| 3780 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3787 | …ge.setItem("omnigent:arca-host-id", "a… | keep-internal |  | test code |
| 3788 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3802 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3808 | …ge.setItem("omnigent:arca-host-id", "a… | keep-internal |  | test code |
| 3900 | …ps://server.databricks.com/omnigent", … | keep-internal |  | test code |
| 3909 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3911 | …ge.getItem("omnigent:arca-host-id")).t… | keep-internal |  | test code |
| 3925 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3948 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3970 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3982 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 3996 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4015 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4034 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4144 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4157 | …ge.getItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4193 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4213 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 4595 | …ge.setItem("omnigent:always-use-worktr… | keep-internal |  | test code |
| 5076 | …agent-model-databricks-gpt-5-6")); | keep-internal |  | test code |
| 5086 | …ride).toBe("databricks-gpt-5-6"); | keep-internal |  | test code |
| 5097 | …agent-model-databricks-gpt-5-6")); | keep-internal |  | test code |
| 5101 | …agent-model-databricks-gpt-5-5")); | keep-internal |  | test code |
| 5777 | …/github.com/omnigent-ai/omnigent.git" … | keep-internal |  | test code |
| 5781 | …positories: omnigent"); | keep-internal |  | test code |
| 5822 | …agent-model-databricks-gpt-5-5")).toBe… | keep-internal |  | test code |
| 5823 | …agent-model-databricks-gpt-5-6")).toBe… | keep-internal |  | test code |
| 5907 | id: "omnigent/system.ai.claude-opus-5"… | keep-internal |  | test code |
| 5908 | model: "omnigent/system.ai.claude-opus… | keep-internal |  | test code |
| 5913 | id: "omnigent-openai/system.ai.gpt-5-5… | keep-internal |  | test code |
| 5914 | model: "omnigent-openai/system.ai.gpt-… | keep-internal |  | test code |
| 6182 | …ge.setItem("omnigent:always-use-worktr… | keep-internal |  | test code |
| 6579 | …ge.setItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 6601 | …ge.setItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 6613 | …ge.setItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 6624 | …ge.setItem("omnigent:recent-harnesses"… | keep-internal |  | test code |
| 6667 | setOmnigentHostConfig({ cliServerUrlSu… | keep-internal |  | test code |
| 6668 | …erLanding({ databricks_features: true … | keep-internal |  | test code |
| 6678 | …", { name: "Databricks Lakebox" }); | keep-internal |  | test code |
| 6690 | …hDesktop, { databricksInternalFeatures… | keep-internal |  | test code |
| 6693 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 6705 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 6710 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |
| 6721 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 6737 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 6941 | …ride).toBe("databricks-gpt-5-6"); | keep-internal |  | test code |
| 6957 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 7135 | …ect(labels["omnigent.codex_native.bypa… | keep-internal |  | test code |
| 7137 | …ect(labels["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 7173 | …ect(labels["omnigent.codex_native.coll… | keep-internal |  | test code |
| 7174 | …ect(labels["omnigent.wrapper"]).toBe("… | keep-internal |  | test code |
| 7225 | …, string>)["omnigent.codex_native.bypa… | keep-internal |  | test code |
| 7483 | "then check again. If Omnigent still can't find it, quit and reopen the Omnigent app.", | change | S81,S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 8281 | setOmnigentHostConfig({ | keep-internal |  | test code |
| 8573 | …ers).get("X-Omnigent-Background-Sessio… | keep-internal |  | test code |
| 8677 | name: "not-configured OmnigentError", | keep-internal |  | test code |
| 8817 | "omnigent:last-sandbox-repos", | keep-internal |  | test code |
| 9222 | setOmnigentHostConfig({ | keep-internal |  | test code |
| 9223 | …ocsLinks: { databricksGitCredentials: … | keep-internal |  | test code |
| 9232 | …w to set up Databricks git credentials… | keep-internal |  | test code |
| 9237 | …ByText("Use Databricks Git credentials… | keep-internal |  | test code |
| 10390 | …t holds an "omnigent" folder + a | keep-internal |  | test code |
| 10391 | …lling into "omnigent" reveals a nested… | keep-internal |  | test code |
| 10397 | …ir(ˋ${ROOT}/omnigentˋ), file(ˋ${ROOT}/… | keep-internal |  | test code |
| 10398 | else if (path === ˋ${ROOT}/omnigentˋ) | keep-internal |  | test code |
| 10399 | …ir(ˋ${ROOT}/omnigent/innerˋ), file(ˋ${… | keep-internal |  | test code |
| 10430 | …Title("Open omnigent")).toBeInTheDocum… | keep-internal |  | test code |
| 10462 | …Title("Open omnigent")).not.toBeInTheD… | keep-internal |  | test code |
| 10478 | …Title("Open omnigent")); | keep-internal |  | test code |
| 10481 | …getByText("@omnigent/cli.py")).toBeInT… | keep-internal |  | test code |
| 10491 | …"[Attached: omnigent/cli.py]\n\nexplai… | keep-internal |  | test code |
| 10502 | …ir(ˋ${ROOT}/omnigentˋ), file(ˋ${ROOT}/… | keep-internal |  | test code |
| 10522 | …Title("Open omnigent")).toBeInTheDocum… | keep-internal |  | test code |
| 10523 | …Title("Open omnigent")); | keep-internal |  | test code |
| 10529 | …Title("Open omnigent")).not.toBeInTheD… | keep-internal |  | test code |
| 10544 | …hole folder omnigent")); | keep-internal |  | test code |
| 10545 | …getByText("@omnigent/")).toBeInTheDocu… | keep-internal |  | test code |
| 10552 | …"[Attached: omnigent/]\n\nreview it"); | keep-internal |  | test code |
| 11502 | …: { model: "databricks-gpt-5-5", effor… | keep-internal |  | test code |
| 12000 | "omnigent.client_create_token": expect… | keep-internal |  | test code |
| 12538 | "omnigent.client_create_token": expect… | keep-internal |  | test code |
| 12542 | …ect(labels["omnigent.composer_context.… | keep-internal |  | test code |
| 12545 | …startsWith("omnigent.composer_context.… | keep-internal |  | test code |
| 12965 | …r: "Connect Databricks before using th… | keep-internal |  | test code |
| 12969 | …nt("Connect Databricks"); | keep-internal |  | test code |
| 13459 | …ge.setItem("omnigent:last-host-choice"… | keep-internal |  | test code |

### `web/src/shell/NewChatDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 209 | …rverUrl, getOmnigentHostConfig } from … | keep-internal |  | code identifier |
| 277 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 382 | import { PoweredByOmnigent } from "@/components/PoweredByOmnigent"; | keep-L7 |  | Import of PoweredByOmnigent credit component; stays as-is. |
| 574 | // Databricks/internal deployments add… | keep-internal |  | code comment |
| 578 | … as OSS (no Databricks | keep-internal |  | code comment |
| 580 | const databricksFeatures = info !== "l… | keep-internal |  | code identifier |
| 586 | {databricksFeatures ? ( | keep-internal |  | code identifier |
| 593 | Databricks Lakebox | keep-origin |  | Databricks Lakebox sandbox option (Databricks integration). |
| 814 | …ognizes the OmnigentError shape (ˋˋ{er… | keep-internal |  | code comment |
| 865 | …gin" / "set OMNIGENT_CODEX_PATH"), so … | keep-internal |  | code comment |
| 910 | <code>brew install tmux</code>), then check again. If Omnigent still can&apos;t find it, | change | S89 | Help copy names the product. |
| 911 | quit and reopen the Omnigent app. | change | S89 | Help copy names the product app. |
| 937 | …iginal "run omnigent | keep-internal |  | code comment |
| 957 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 1142 | …e of these (OMNIGENT_SEEDED_AGENTS) ba… | keep-internal |  | code comment |
| 2126 | …RAGE_KEY = "omnigent:landing-import-di… | keep-internal |  | localStorage key omnigent:landing-import-dismiss |
| 2241 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 2381 | // Omnigent sessions can pull in their… | keep-internal |  | code comment |
| 2587 | …sLinks = getOmnigentHostConfig().docsL… | keep-internal |  | code identifier |
| 2589 | …cs seam for Databricks git auth setup.… | keep-internal |  | code comment |
| 2591 | const databricksGitCredentialsTooltipC… | keep-internal |  | code identifier |
| 2662 | // Arca (Databricks-internal): the des… | keep-internal |  | code comment |
| 2982 | …d(features?.databricksInternalFeatures… | keep-internal |  | code identifier |
| 3564 | // axis Omnigent carries as reasoning_… | keep-internal |  | code comment |
| 5709 | …v instance (Databricks-internal sandbo… | keep-internal |  | code comment |
| 5867 | features?.databricksInternalFeatures =… | keep-internal |  | code identifier |
| 5991 | …nal-first: ˋomnigent.ui: terminalˋ | keep-internal |  | code comment |
| 5992 | …apper, and ˋomnigent.wrapperˋ | keep-internal |  | code comment |
| 6698 | {databricksGitCredentialsTooltipConten… | keep-internal |  | code identifier |
| 6704 | aria-label="How to set up Databricks git credentials" | keep-origin |  | aria-label names Databricks git credentials, a Databricks integration feature. |
| 6710 | {databricksGitCredentialsTooltipConten… | keep-internal |  | code identifier |
| 6953 | name="omnigent-worktree-branch" | keep-internal |  | Input name attribute omnigent-worktree-branch us |
| 7840 | {sandboxCatalogError.includes("Connect Databricks") && ( | keep-origin |  | Matches server 'Connect Databricks' sandbox error; Databricks integration naming, compared against server text. |
| 7963 | <PoweredByOmnigent /> | keep-L7 |  | Usage of PoweredByOmnigent credit; stays as-is. |

### `web/src/shell/OpenInMenu.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 67 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 153 | …"desktop", "databricks-arca", "my-arca… | keep-internal |  | test code |
| 154 | …"browser", "databricks-arca", "my-arca… | keep-internal |  | test code |
| 162 | …stubGlobal("omnigentDesktop", undefine… | keep-internal |  | test code |
| 312 | …ge.getItem("omnigent:default-code-edit… | keep-internal |  | test code |
| 352 | …"lakebox", "databricks-lakebox")]], | keep-internal |  | test code |
| 383 | …"my-arca", "databricks-arca"), | keep-internal |  | test code |
| 400 | …stubGlobal("omnigentDesktop", undefine… | keep-internal |  | test code |
| 401 | …stubGlobal("omnigentNative", { kind })… | keep-internal |  | test code |

### `web/src/shell/OpenInMenu.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 24 | …CE_EVENT = "omnigent:open-in-app-chang… | keep-internal |  | Custom DOM event name omnigent:open-in-app-chang |
| 25 | …ENCE_KEY = "omnigent:default-code-edit… | keep-internal |  | localStorage key omnigent:default-code-editor. |

### `web/src/shell/PdfViewer.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 47 | // managed omnigent failed to render P… | keep-internal |  | code comment |

### `web/src/shell/PullRequestChangesTab.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 91 | // omnigent/runner/x.py shows an "omni… | keep-internal |  | code comment |

### `web/src/shell/PullRequestPanel.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1623 | file("omnigent/runner/app.py", "modifi… | keep-internal |  | test code |
| 1624 | file("omnigent/runner/util.py", "creat… | keep-internal |  | test code |
| 1632 | // The lone omnigent → runner chain co… | keep-internal |  | test code |
| 1634 | …", { name: "omnigent/runner" })).toBeI… | keep-internal |  | test code |
| 1644 | …ata: [file("omnigent/runner/app.py", "… | keep-internal |  | test code |
| 1651 | …", { name: "omnigent/runner" }); | keep-internal |  | test code |
| 1661 | …ata: [file("omnigent/new_name.py", "re… | keep-internal |  | test code |
| 1667 | { name: "omnigent/new_name.py", prevNa… | keep-internal |  | test code |
| 1676 | name: /omnigent\/old_name\.py\s*→\s*om… | keep-internal |  | test code |

### `web/src/shell/PullRequestPanel.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 1630 | …uests tab needs the host running Omnigent 0.13.0 or later. Update the host, then reconnect the sessi… | keep-origin |  | Version gate names the omnigent package release (0.13.0) the host runs; factual upstream package reference. |

### `web/src/shell/QuitDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 18 | expect(screen.getByRole("heading", { name: "Quit Omnigent?" })).toBeInTheDocument(); | change | S89 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/shell/QuitDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 46 | <DialogTitle>Quit Omnigent?</DialogTitle> | change | S89 | Quit confirmation dialog title shows product name. |

### `web/src/shell/RecentSessionsSwitcher.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 14 | …, unknown>).omnigentDesktop; | keep-internal |  | test code |
| 149 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |
| 202 | …, unknown>).omnigentDesktop = { | keep-internal |  | test code |

### `web/src/shell/ReconnectSessionDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 7 | …ne owner → ˋomnigent hostˋ (no --resum… | keep-internal |  | test code |
| 13 | …stranded → ˋomnigent claude --resumeˋ. | keep-internal |  | test code |
| 84 | it("emits ˋomnigent hostˋ for host_off… | keep-internal |  | test code |
| 87 | …s://example.databricksapps.com", | keep-internal |  | test code |
| 90 | ….toContain("omnigent host"); | keep-internal |  | test code |
| 91 | …s://example.databricksapps.com'"); | keep-internal |  | test code |
| 101 | …t("prefers ˋomnigent hostˋ for a host_… | keep-internal |  | test code |
| 106 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 110 | ….toContain("omnigent host"); | keep-internal |  | test code |
| 111 | ….toContain("omnigent claude"); | keep-internal |  | test code |
| 117 | …s://example.databricksapps.com", | keep-internal |  | test code |
| 120 | ….toContain("omnigent run path/to/agent… | keep-internal |  | test code |
| 122 | …s://example.databricksapps.com'"); | keep-internal |  | test code |
| 135 | it("emits ˋomnigent devin --resumeˋ fo… | keep-internal |  | test code |
| 136 | … own verb; ˋomnigent runˋ cannot | keep-internal |  | test code |
| 140 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 144 | ….toContain("omnigent devin"); | keep-internal |  | test code |
| 146 | ….toContain("omnigent run"); | keep-internal |  | test code |
| 150 | it("emits ˋomnigent claude --resumeˋ f… | keep-internal |  | test code |
| 153 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 157 | ….toContain("omnigent claude"); | keep-internal |  | test code |
| 161 | ….toContain("omnigent run"); | keep-internal |  | test code |
| 167 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 171 | ….toContain("omnigent run path/to/agent… | keep-internal |  | test code |
| 172 | ….toContain("omnigent claude"); | keep-internal |  | test code |
| 182 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 187 | ….toContain("omnigent devin"); | keep-internal |  | test code |
| 189 | ….toContain("omnigent run"); | keep-internal |  | test code |
| 195 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 200 | ….toContain("omnigent claude"); | keep-internal |  | test code |
| 201 | ….toContain("omnigent devin"); | keep-internal |  | test code |
| 207 | … "https://x.databricksapps.com", | keep-internal |  | test code |
| 212 | ….toContain("omnigent run path/to/agent… | keep-internal |  | test code |
| 258 | …s://example.databricksapps.com" | keep-internal |  | test code |
| 295 | ….toContain("omnigent host"); | keep-internal |  | test code |
| 440 | ….toContain("omnigent run path/to/agent… | keep-internal |  | test code |
| 456 | ….toContain("omnigent claude"); | keep-internal |  | test code |
| 505 | …s://example.databricksapps.com" | keep-internal |  | test code |
| 523 | …extContent("omnigent host"); | keep-internal |  | test code |

### `web/src/shell/ReconnectSessionDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 42 | … the host (ˋomnigent hostˋ); a | keep-internal |  | code comment |
| 54 | …offlineˋ — ˋomnigent hostˋ re-register… | keep-internal |  | code comment |
| 60 | …-ui"ˋ) use ˋomnigent claude | keep-internal |  | code comment |
| 61 | …he generic ˋomnigent run | keep-internal |  | code comment |
| 64 | …d from the ˋomnigent.wrapperˋ label, t… | keep-internal |  | code comment |
| 67 | * generic ˋomnigent runˋ form cannot r… | keep-internal |  | code comment |
| 69 | * The Databricks profile stays a place… | keep-internal |  | code comment |
| 89 | return ["omnigent host \\", ˋ  --server ${quotedServerUrl}ˋ].join("\n"); | keep-deferred |  | Generated omnigent host CLI command; OPS-03/FND-01. |
| 91 | … own verb (ˋomnigent devin | keep-internal |  | code comment |
| 93 | // ˋomnigent run <agent.yaml>ˋ below c… | keep-internal |  | code comment |
| 99 | ˋomnigent ${nativeAgent.key} \\ˋ, | keep-deferred |  | Generated omnigent <agent> --resume CLI command; OPS-03/FND-01. |
| 105 | "omnigent run path/to/agent.yaml \\", | keep-deferred |  | Generated omnigent run CLI command; OPS-03/FND-01. |
| 131 | …ersation's ˋomnigent.wrapperˋ label | keep-internal |  | code comment |
| 132 | …e-ui"ˋ for ˋomnigent claudeˋ sessions)… | keep-internal |  | code comment |

### `web/src/shell/ResumeWithDirectoryDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 51 | …s/alice/git/omnigent")} | keep-internal |  | test code |
| 279 | …type "~/git/omnigent" into the field a… | keep-internal |  | test code |
| 295 | …lue: "~/git/omnigent" } }); | keep-internal |  | test code |
| 307 | "/Users/alice/git/omnigent", | keep-internal |  | test code |
| 329 | …lue: "~/git/omnigent" } }); | keep-internal |  | test code |
| 338 | …s/alice/git/omnigent"); | keep-internal |  | test code |
| 346 | "/Users/alice/git/omnigent", | keep-internal |  | test code |

### `web/src/shell/ResumeWithDirectoryDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 41 | …irectory (ˋˋomnigent.fork.source_idˋˋ … | keep-internal |  | code comment |
| 56 | …k source (ˋˋomnigent.fork.source_idˋˋ)… | keep-internal |  | code comment |
| 61 | …session's ˋˋomnigent.wrapperˋˋ label (… | keep-internal |  | code comment |
| 281 | <code className="rounded bg-muted px-1 py-0.5 font-mono">omnigent host</code> from your | keep-deferred |  | Instructs running omnigent host CLI command; OPS-03/FND-01. |
| 297 | … the host (ˋomnigent hostˋ); without o… | keep-internal |  | code comment |

### `web/src/shell/RevealInFileManager.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 68 | omnigentDesktop: { | keep-internal |  | test code |
| 83 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |
| 151 | …window as { omnigentDesktop?: unknown … | keep-internal |  | test code |

### `web/src/shell/ShellPrimitives.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 34 | command="omnigent host --server https:… | keep-internal |  | test code |

### `web/src/shell/Sidebar.archive.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 48 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 176 | …PREF_KEY = "omnigent:delete-worktrees-… | keep-internal |  | test code |

### `web/src/shell/Sidebar.bulkActionLayout.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 40 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |

### `web/src/shell/Sidebar.mobileDrawer.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 154 | …, unknown>).omnigentNative = { kind: "… | keep-internal |  | test code |
| 171 | …, unknown>).omnigentNative; | keep-internal |  | test code |

### `web/src/shell/Sidebar.peekClickThrough.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 94 | …oHaveClass("omnigent-sidebar-panel"); | keep-internal |  | test code |

### `web/src/shell/Sidebar.pinBackwardsCompat.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 29 | …arries the ˋomnigent.pinnedˋ label (pr… | keep-internal |  | test code |
| 31 | …o the bare ˋomnigent.pinnedˋ key, and … | keep-internal |  | test code |
| 35 | …+ surfaces (omnigent.pinned.<user>). | keep-internal |  | test code |
| 38 | …s any bare ˋomnigent.pinnedˋ key on re… | keep-internal |  | test code |
| 78 | …surfaced as omnigent.pinned | keep-internal |  | test code |

### `web/src/shell/Sidebar.pinMigration.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …erver-side ˋomnigent.pinnedˋ label. Th… | keep-internal |  | test code |
| 30 | … labels: { "omnigent.pinned": "1" } })… | keep-internal |  | test code |

### `web/src/shell/Sidebar.pinReorder.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 91 | … labels: { "omnigent.pinned": "1000" }… | keep-internal |  | test code |
| 92 | … labels: { "omnigent.pinned": "1000" }… | keep-internal |  | test code |
| 295 | …ge.getItem("omnigent:sidebar-view") ??… | keep-internal |  | test code |
| 312 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 337 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 404 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 407 | …ge.setItem("omnigent:session-filter", … | keep-internal |  | test code |

### `web/src/shell/Sidebar.rowActions.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 206 | databricks_features: false, | keep-internal |  | test code |
| 443 | …-side (the ˋomnigent.pinnedˋ label) so… | keep-internal |  | test code |
| 817 | vi.stubGlobal("omnigentNative", { | keep-internal |  | test code |
| 1341 | … labels: { "omnigent.host_type": "mana… | keep-internal |  | test code |

### `web/src/shell/Sidebar.selectionActiveHighlight.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 20 | …port { type OmnigentLinkProps, reactRo… | keep-internal |  | test code |
| 76 | …horElement, OmnigentLinkProps>( | keep-internal |  | test code |

### `web/src/shell/Sidebar.sessionShortcutHints.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 138 | …stubGlobal("omnigentDesktop", { kind: … | keep-internal |  | test code |

### `web/src/shell/Sidebar.shiftSelect.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 239 | …ge.setItem("omnigent:expanded-project-… | keep-internal |  | test code |
| 274 | …ge.setItem("omnigent:expanded-project-… | keep-internal |  | test code |
| 315 | …ge.setItem("omnigent:expanded-project-… | keep-internal |  | test code |

### `web/src/shell/Sidebar.stop.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 132 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |

### `web/src/shell/Sidebar.subagentHighlight.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 118 | it("renders the official Omnigent wordmark instead of styled text", () => { | change | S80 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 123 | expect(wordmark).toHaveAttribute("alt", "Omnigent"); | change | S80 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |
| 125 | expect(wordmark.getAttribute("src")).toContain("omnigent-wordmark"); | change | S80 | Test updated with its seam: it pinned changed text or used a changed id or scheme. |

### `web/src/shell/Sidebar.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 30 | import { getOmnigentServerIdentity } f… | keep-internal |  | test code |
| 228 | // (databricks_coding_agent / Claude C… | keep-internal |  | test code |
| 230 | …("conv_a", "databricks_coding_agent"), | keep-internal |  | test code |
| 231 | …("conv_b", "databricks_coding_agent"), | keep-internal |  | test code |
| 612 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 922 | …ge.setItem("omnigent:session-filter", … | keep-internal |  | test code |
| 948 | …ge.getItem("omnigent:session-filter"))… | keep-internal |  | test code |
| 962 | …ge.setItem("omnigent:session-filter", … | keep-internal |  | test code |
| 1745 | …onst key = ˋomnigent:session-grids:${g… | keep-internal |  | test code |
| 2073 | …ectLabels, "omnigent.pinned": "1" }, | keep-internal |  | test code |
| 2104 | …ectLabels, "omnigent.pinned": "1" }, | keep-internal |  | test code |
| 2439 | …ge.setItem("omnigent:session-filter", … | keep-internal |  | test code |
| 2964 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 2986 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 3196 | vi.stubGlobal("omnigentDesktop", { | keep-internal |  | test code |
| 3527 | …ge.setItem("omnigent:collapsed-sidebar… | keep-internal |  | test code |
| 3543 | …ge.setItem("omnigent:collapsed-sidebar… | keep-internal |  | test code |
| 3580 | …ge.getItem("omnigent:collapsed-sidebar… | keep-internal |  | test code |
| 3895 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 3932 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 3956 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 3997 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4032 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4054 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4070 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4096 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4107 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4161 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4204 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4206 | "omnigent:collapsed-sidebar-sections", | keep-internal |  | test code |
| 4243 | …ge.getItem("omnigent:sidebar-view")!).… | keep-internal |  | test code |
| 4271 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 4335 | …ge.getItem("omnigent:sidebar-view")!).… | keep-internal |  | test code |
| 4345 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 4364 | …ge.getItem("omnigent:sidebar-view")!).… | keep-internal |  | test code |
| 4414 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4422 | …ge.setItem("omnigent:sidebar-view", JS… | keep-internal |  | test code |
| 4442 | labels: { "omnigent.sandbox.repo.0": "… | keep-internal |  | test code |
| 4452 | …xtContent(/^omnigent$/); | keep-internal |  | test code |
| 4464 | …ith_owner: "omnigent-ai/omnigent" }, | keep-internal |  | test code |
| 4470 | workspace: "/Users/me/omnigent", | keep-internal |  | test code |
| 4471 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 4483 | …ontent("Repoomnigent"); | keep-internal |  | test code |
| 4520 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4532 | workspace: "/Users/me/omnigent", | keep-internal |  | test code |
| 4536 | repository: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 4566 | … "/Users/me/omnigent" })]); | keep-internal |  | test code |
| 4615 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4625 | workspace: "/Users/me/omnigent", | keep-internal |  | test code |
| 4627 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4629 | repository: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 4655 | …ith_owner: "omnigent-ai/omnigent" }, | keep-internal |  | test code |
| 4657 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4660 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4662 | repository: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 4669 | … "/Users/me/omnigent" })]); | keep-internal |  | test code |
| 4685 | workspace: "/Users/me/omnigent", | keep-internal |  | test code |
| 4687 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4689 | repository: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 4703 | …ontent("Repoomnigent"); | keep-internal |  | test code |
| 4712 | workspace: "/Users/me/omnigent", | keep-internal |  | test code |
| 4714 | …/github.com/omnigent-ai/omnigent/pull/… | keep-internal |  | test code |
| 4716 | repository: "omnigent-ai/omnigent", | keep-internal |  | test code |
| 4795 | "omnigent:sidebar-view", | keep-internal |  | test code |
| 5129 | "omnigent:sidebar-view", | keep-internal |  | test code |

### `web/src/shell/Sidebar.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 132 | import omnigentWordmark from "@/assets/omnigent-wordmark.svg"; | change-asset | S80 | Imports Omnigent wordmark SVG shown as default sidebar brand. |
| 231 | import { useOmnigentAnalytics } from "… | keep-internal |  | code identifier |
| 662 | …they're an ˋomnigent.pinnedˋ | keep-internal |  | code comment |
| 915 | …rver as an ˋomnigent.pinnedˋ session l… | keep-internal |  | code comment |
| 987 | …er (as the ˋomnigent.pinnedˋ label) th… | keep-internal |  | code comment |
| 1157 | …rSurface ? "omnigent-native-sidebar-su… | keep-internal |  | CSS class names omnigent-native-sidebar-surface |
| 1272 | src={omnigentWordmark} | change-asset | S80 | Default sidebar wordmark image renders Omnigent wordmark when no operator app_name. |
| 1273 | alt="Omnigent" | change | S80 | alt text of default sidebar wordmark names product. |
| 2279 | // by the ˋomnigent.pinnedˋ label valu… | keep-internal |  | code comment |
| 2937 | …ative (the ˋomnigent.pinnedˋ label), | keep-internal |  | code comment |
| 4492 | …ill switch (OMNIGENT_SHARING_MODE=off)… | keep-internal |  | code comment |
| 4546 | …lick } = useOmnigentAnalytics(); | keep-internal |  | code identifier |
| 4666 | ? "Sharing has been disabled for this Omnigent server." | change | S89 | Web copy of sharing-disabled reason in Share tooltip; 'Omnigent server' wording. |
| 4953 | … its first ˋomnigent.sandbox.repoˋ lab… | keep-internal |  | code comment |
| 5394 | …ill switch (OMNIGENT_SHARING_MODE=off)… | keep-internal |  | code comment |

### `web/src/shell/SidebarServerPicker.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 65 | "https://omnigents-3272836215725701.aw… | keep-internal |  | test code |
| 66 | "https://omnigents-9147263058412098.aw… | keep-internal |  | test code |
| 80 | ….getByText("omnigents-3272836215725701… | keep-internal |  | test code |
| 83 | ….getByText("omnigents-9147263058412098… | keep-internal |  | test code |
| 90 | …mple.com/ml/omnigents"], | keep-internal |  | test code |
| 103 | …mple.com/ml/omnigents"), | keep-internal |  | test code |
| 110 | …mple.com/ml/omnigents"], | keep-internal |  | test code |
| 179 | …dbc-1.cloud.databricks.com", | keep-internal |  | test code |
| 180 | …example.com/omnigent?o=1", | keep-internal |  | test code |
| 204 | …dbc-1.cloud.databricks.com/omnigent"], | keep-internal |  | test code |
| 206 | …dbc-1.cloud.databricks.com/omnigent": … | keep-internal |  | test code |
| 211 | …dbc-1.cloud.databricks.com")).toBeNull… | keep-internal |  | test code |
| 215 | …dbc-1.cloud.databricks.com/omnigent"), | keep-internal |  | test code |
| 222 | …example.com/omnigent?o=1"], | keep-internal |  | test code |
| 223 | …dbc-1.cloud.databricks.com/omnigent"], | keep-internal |  | test code |
| 225 | …dbc-1.cloud.databricks.com/omnigent": … | keep-internal |  | test code |
| 234 | …dbc-1.cloud.databricks.com/omnigent"), | keep-internal |  | test code |
| 240 | …dbc-1.cloud.databricks.com", | keep-internal |  | test code |
| 241 | …dbc-1.cloud.databricks.com/?o=1", "htt… | keep-internal |  | test code |
| 242 | …dbc-1.cloud.databricks.com/?o=1": "Eng… | keep-internal |  | test code |
| 363 | …dbc-1.cloud.databricks.com", | keep-internal |  | test code |
| 364 | …example.com/omnigent?o=1", | keep-internal |  | test code |
| 365 | …dbc-1.cloud.databricks.com/"], | keep-internal |  | test code |
| 372 | …c-1\.cloud\.databricks\.com/.test(item… | keep-internal |  | test code |

### `web/src/shell/SshConnectForm.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 16 | …nknown as { omnigentDesktop?: Desktop … | keep-internal |  | test code |
| 37 | …nknown as { omnigentDesktop?: Desktop … | keep-internal |  | test code |
| 44 | …example.com/omnigent", hostId: "h1" }, | keep-internal |  | test code |

### `web/src/shell/SshConnectForm.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …un on Arca (Databricks-internal) repla… | keep-internal |  | code comment |
| 18 | …e(features?.databricksInternalFeatures… | keep-internal |  | code identifier |

### `web/src/shell/SubagentsGraphView.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 575 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 583 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 591 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 599 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |

### `web/src/shell/SubagentsPanel.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 157 | …ted_model: "databricks-claude-sonnet-5… | keep-internal |  | test code |
| 202 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 216 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 224 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 233 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |

### `web/src/shell/SubagentsPanel.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 236 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 266 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 360 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 365 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 370 | labels: { "omnigent.wrapper": "opencod… | keep-internal |  | test code |
| 375 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 391 | labels: { "omnigent.wrapper": "some-ot… | keep-internal |  | test code |
| 400 | … session's ˋomnigent.wrapperˋ | keep-internal |  | test code |
| 564 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 588 | labels: { "omnigent.wrapper": "antigra… | keep-internal |  | test code |
| 609 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 617 | labels: { "omnigent.wrapper": "opencod… | keep-internal |  | test code |
| 625 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 633 | labels: { "omnigent.wrapper": "kiro-na… | keep-internal |  | test code |
| 664 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 671 | "omnigent.wrapper": "codex-native-ui-s… | keep-internal |  | test code |
| 672 | "omnigent.codex_native.agent_role": "r… | keep-internal |  | test code |
| 757 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 1362 | "omnigent.wrapper": "claude-code-nativ… | keep-internal |  | test code |
| 1363 | "omnigent.claude_native.description": … | keep-internal |  | test code |
| 1371 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 1544 | …ted_model: "databricks-claude-sonnet-5… | keep-internal |  | test code |

### `web/src/shell/SwitchHostDialog.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 51 | …s/alice/git/omnigent")} | keep-internal |  | test code |
| 189 | ["Databricks Sandbox host", "lakebox"]… | keep-internal |  | test code |
| 205 | …pshot" ? { "omnigent.host_type": "mana… | keep-internal |  | test code |
| 319 | …type "~/git/omnigent" into the field a… | keep-internal |  | test code |
| 330 | …lue: "~/git/omnigent" } }); | keep-internal |  | test code |
| 342 | "/Users/alice/git/omnigent", | keep-internal |  | test code |
| 357 | …lue: "~/git/omnigent" } }); | keep-internal |  | test code |
| 366 | …s/alice/git/omnigent"); | keep-internal |  | test code |
| 374 | "/Users/alice/git/omnigent", | keep-internal |  | test code |

### `web/src/shell/SwitchHostDialog.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 270 | No other hosts are online. Connect one with <code>omnigent host</code> and try again. | keep-deferred |  | Names the omnigent CLI command ('omnigent host') shown in the empty-state copy; changes with CLI rename OPS-03/FND-01. |

### `web/src/shell/TerminalFirstContext.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 11 | //   - ˋomnigent.wrapper === "claude-c… | keep-internal |  | code comment |
| 12 | …registered ˋomnigent.wrapperˋ native v… | keep-internal |  | code comment |
| 13 | //   - ˋomnigent.ui === "terminal"ˋ   … | keep-internal |  | code comment |
| 21 | … now stamp ˋomnigent.uiˋ WITHOUT a | keep-internal |  | code comment |
| 22 | …l hosts the Omnigent REPL), so | keep-internal |  | code comment |
| 30 | … True when ˋomnigent.wrapper === "clau… | keep-internal |  | code comment |
| 36 | * Omnigent REPL terminal are terminal-… | keep-internal |  | code comment |
| 39 | … True when ˋomnigent.ui === "terminal"… | keep-internal |  | code comment |

### `web/src/shell/TipTapHtmlPassthrough.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 141 | …"middle" /> Omnigent'; | keep-internal |  | test code |

### `web/src/shell/ViewModeToggle.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 116 | …, unknown>).omnigentNative = { kind: "… | keep-internal |  | test code |
| 121 | …, unknown>).omnigentNative; | keep-internal |  | test code |

### `web/src/shell/WorkspacePanel.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 176 | …ty(window, "omnigentDesktop"); | keep-internal |  | test code |
| 1029 | omnigentDesktop: { | keep-internal |  | test code |
| 1209 | …removeItem("omnigent:preferred-shell")… | keep-internal |  | test code |
| 1238 | …ge.getItem("omnigent:preferred-shell")… | keep-internal |  | test code |
| 1252 | …removeItem("omnigent:preferred-shell")… | keep-internal |  | test code |
| 1416 | omnigentDesktop: { | keep-internal |  | test code |
| 1525 | omnigentDesktop: { browserClose: vi.fn… | keep-internal |  | test code |
| 1889 | { "omnigent.wrapper": "claude-code-nat… | keep-internal |  | test code |
| 1892 | …-agent", { "omnigent.closed": "true" }… | keep-internal |  | test code |
| 2117 | omnigentDesktop: { | keep-internal |  | test code |
| 2351 | …nknown as { omnigentDesktop: object })… | keep-internal |  | test code |
| 2378 | …nknown as { omnigentDesktop: object })… | keep-internal |  | test code |

### `web/src/shell/WorkspacePanel.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 176 | …ser (a CLI ˋomnigent hostˋ / ˋ--resume… | keep-internal |  | code comment |
| 1889 | "--omnigent-reserved-width": ˋ${width}… | keep-internal |  | CSS custom property name (--omnigent-reserved-wi |

### `web/src/shell/WorkspacePicker.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 200 | …rt typed "~/omnigent" | keep-internal |  | test code |
| 203 | …ypedPath("~/omnigent", "/Users/corey")… | keep-internal |  | test code |
| 299 | …Path("~/git/omnigent", "/Users/alice")… | keep-internal |  | test code |
| 300 | "/Users/alice/git/omnigent", | keep-internal |  | test code |
| 322 | …Path("~/git/omnigent", null)).toBeNull… | keep-internal |  | test code |
| 887 | …stubGlobal("omnigentDesktop", { kind: … | keep-internal |  | test code |
| 958 | …stubGlobal("omnigentDesktop", { kind: … | keep-internal |  | test code |

### `web/src/shell/WorkspacePicker.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 776 | …ted outside Omnigent (e.g. ˋgit worktr… | keep-internal |  | code comment |

### `web/src/shell/WorkspacePickerEntry.stories.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …jay/Desktop/omnigent-working-dir/omni-… | keep-internal |  | test code |
| 41 | …jay/Desktop/omnigent-working-dir/READM… | keep-internal |  | test code |

### `web/src/shell/monacoCodeEditor.css`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 28 | … the active Omnigent card tone so the … | keep-internal |  | code comment |

### `web/src/shell/preferredShell.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 8 | …HELL_KEY = "omnigent:preferred-shell"; | keep-internal |  | localStorage key omnigent:preferred-shell; renam |

### `web/src/shell/settingsNav.test.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 480 | …teHook("/ml/omnigent-embed/settings/me… | keep-internal |  | test code |
| 501 | …teHook(ˋ/ml/omnigent-embed/settings/cu… | keep-internal |  | test code |
| 562 | …teHook("/ml/omnigent-embed/settings/cu… | keep-internal |  | test code |

### `web/src/shell/settingsNav.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 295 | …ngs.back_to_omnigent"> | keep-internal |  | Analytics componentId 'settings.back_to_omnigent |

### `web/src/shell/sidebarNav.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 64 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 67 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 70 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 169 | …d ? {} : { "omnigent.pinned": String(p… | keep-internal |  | test code |
| 208 | …ber.labels["omnigent.pinned"]).toBeUnd… | keep-internal |  | test code |
| 224 | …d ? {} : { "omnigent.pinned": String(v… | keep-internal |  | test code |
| 303 | …labels = { "omnigent.pinned": "200" }; | keep-internal |  | test code |
| 315 | … labels: { "omnigent.pinned": String(w… | keep-internal |  | test code |
| 329 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 332 | // via ˋomnigent claudeˋ. Any other la… | keep-internal |  | test code |
| 338 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 341 | // via ˋomnigent codexˋ. It gets its o… | keep-internal |  | test code |
| 347 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 354 | labels: { "omnigent.wrapper": "kiro-na… | keep-internal |  | test code |
| 361 | labels: { "omnigent.wrapper": "antigra… | keep-internal |  | test code |
| 364 | // via ˋomnigent antigravityˋ or the w… | keep-internal |  | test code |
| 372 | agent_name: "databricks_coding_agent", | keep-internal |  | test code |
| 376 | …onv)).toBe("databricks_coding_agent"); | keep-internal |  | test code |
| 391 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 397 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 403 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 427 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 434 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 441 | labels: { "omnigent.wrapper": "opencod… | keep-internal |  | test code |
| 448 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 455 | labels: { "omnigent.wrapper": "kiro-na… | keep-internal |  | test code |
| 462 | labels: { "omnigent.wrapper": "antigra… | keep-internal |  | test code |
| 496 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 506 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 516 | labels: { "omnigent.wrapper": "pi-nati… | keep-internal |  | test code |
| 529 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 541 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 560 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 574 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 590 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |

### `web/src/shell/sidebarNav.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 9 | …RAGE_KEY = "omnigent:pinned-conversati… | keep-internal |  | Legacy localStorage key omnigent:pinned-conversa |
| 95 | …RAGE_KEY = "omnigent:collapsed-sidebar… | keep-internal |  | localStorage key omnigent:collapsed-sidebar-sect |
| 101 | …RAGE_KEY = "omnigent:expanded-project-… | keep-internal |  | localStorage key omnigent:expanded-project-secti |
| 462 | …d_atˋ. The ˋomnigent.pinnedˋ label val… | keep-internal |  | code comment |
| 477 | …e: the new ˋomnigent.pinnedˋ sort valu… | keep-internal |  | code comment |

### `web/src/store/chatStore.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 71 | setOmnigentHostConfig, | keep-internal |  | test code |
| 72 | type OmnigentAnalyticsEvent, | keep-internal |  | test code |
| 73 | type OmnigentInteractionKind, | keep-internal |  | test code |
| 433 | labels["omnigent.codex_native.collabor… | keep-internal |  | test code |
| 437 | labels["omnigent.codex_native.approval… | keep-internal |  | test code |
| 1600 | …native", { "omnigent.startup": "ready"… | keep-internal |  | test code |
| 1692 | …y expose an Omnigent model picker). | keep-internal |  | test code |
| 1714 | …l ? {} : { "omnigent.wrapper": wrapper… | keep-internal |  | test code |
| 2248 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 2490 | labels: { "omnigent.startup": "failed"… | keep-internal |  | test code |
| 3014 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 3391 | …ubEnv("VITE_OMNIGENT_HOST_ROUTING", "t… | keep-internal |  | test code |
| 3622 | …ers).get("x-omnigent-hold-when-host-of… | keep-internal |  | test code |
| 4454 | "omnigent.wrapper": | keep-internal |  | test code |
| 5305 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 6817 | … carries no Omnigent error code: the m… | keep-internal |  | test code |
| 7062 | …red with an Omnigent error", async () … | keep-internal |  | test code |
| 8133 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 8345 | labels: { "omnigent.startup": startup … | keep-internal |  | test code |
| 8398 | labels: { "omnigent.startup": startup … | keep-internal |  | test code |
| 8715 | …nv_abc", { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 9138 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 9175 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12157 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12178 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 12221 | …ge.getItem("omnigent.picker.model")).t… | keep-internal |  | test code |
| 12228 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 12257 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12287 | …ge.setItem("omnigent.picker.model", "o… | keep-internal |  | test code |
| 12302 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12328 | …removeItem("omnigent.picker.model"); | keep-internal |  | test code |
| 12333 | …ge.setItem("omnigent.picker.model", "o… | keep-internal |  | test code |
| 12353 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12383 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12401 | …removeItem("omnigent.picker.model"); | keep-internal |  | test code |
| 12409 | …ge.setItem("omnigent.picker.model", "f… | keep-internal |  | test code |
| 12432 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12462 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12479 | …removeItem("omnigent.picker.model"); | keep-internal |  | test code |
| 12484 | …ge.setItem("omnigent.picker.model", "f… | keep-internal |  | test code |
| 12499 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12519 | …removeItem("omnigent.picker.model"); | keep-internal |  | test code |
| 12529 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12547 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12551 | model: "databricks-gpt-5-4", | keep-internal |  | test code |
| 12583 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12611 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 12623 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12638 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 12650 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12697 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 12701 | "omnigent:last-mode-by-harness", | keep-internal |  | test code |
| 12710 | …ge.getItem("omnigent:last-mode-by-harn… | keep-internal |  | test code |
| 12712 | …ge.getItem("omnigent.picker.effort")).… | keep-internal |  | test code |
| 12717 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 12772 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12793 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12811 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12840 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12867 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12897 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12926 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 12957 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 12980 | labels: { "omnigent.wrapper": "codex-n… | keep-internal |  | test code |
| 13015 | "omnigent.wrapper": "codex-native-ui", | keep-internal |  | test code |
| 13016 | "omnigent.codex_native.collaboration_m… | keep-internal |  | test code |
| 13029 | "omnigent.codex_native.collaboration_m… | keep-internal |  | test code |
| 13040 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 13052 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 13079 | "omnigent.codex_native.collaboration_m… | keep-internal |  | test code |
| 13087 | "omnigent.wrapper": "codex-native-ui", | keep-internal |  | test code |
| 13088 | "omnigent.codex_native.approval_mode":… | keep-internal |  | test code |
| 13101 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 13111 | labels: { "omnigent.codex_native.appro… | keep-internal |  | test code |
| 13121 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 13133 | … labels: { "omnigent.wrapper": "codex-… | keep-internal |  | test code |
| 13162 | "omnigent.codex_native.approval_mode", | keep-internal |  | test code |
| 13169 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 13208 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 13223 | … labels: { "omnigent.wrapper": "claude… | keep-internal |  | test code |
| 14066 | …ders.set("x-omnigent-stream-epoch", ep… | keep-internal |  | test code |
| 14496 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 14554 | labels: { "omnigent.wrapper": "claude-… | keep-internal |  | test code |
| 17772 | …CE_KEY = "X-Databricks-Omnigent-Slice-… | keep-internal |  | test code |
| 17885 | // ˋisDatabricksWorkspace()ˋ gates sli… | keep-internal |  | test code |
| 17888 | …ubEnv("VITE_DATABRICKS_WORKSPACE", "tr… | keep-internal |  | test code |
| 18220 | …t outside a Databricks workspace", asy… | keep-internal |  | test code |
| 18758 | // ˋomnigent piˋ server). The harness … | keep-internal |  | test code |
| 18759 | // Omnigent response the instant it en… | keep-internal |  | test code |
| 22454 | …t = Extract<OmnigentAnalyticsEvent, { … | keep-internal |  | test code |
| 22455 | let events: OmnigentAnalyticsEvent[]; | keep-internal |  | test code |
| 22462 | setOmnigentHostConfig({ analytics: (e)… | keep-internal |  | test code |
| 22467 | setOmnigentHostConfig({}); | keep-internal |  | test code |
| 22470 | …es = (kind: OmnigentInteractionKind): … | keep-internal |  | test code |
| 22810 | code: "databricks_sign_in_pending", | keep-internal |  | test code |

### `web/src/store/chatStore.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 175 | import { isDatabricksWorkspace, isHost… | keep-internal |  | code identifier |
| 787 | …d from the ˋomnigent.wrapperˋ | keep-internal |  | code comment |
| 799 | … through an Omnigent | keep-internal |  | code comment |
| 801 | * these — Omnigent's bound ˋllmModelˋ … | keep-internal |  | code comment |
| 803 | …O expose an Omnigent picker, so they k… | keep-internal |  | code comment |
| 868 | * ˋˋomnigent.codex_native.collaboratio… | keep-internal |  | code comment |
| 874 | …ated from ˋˋomnigent.claude_native.per… | keep-internal |  | code comment |
| 885 | * ˋˋomnigent.codex_native.approval_mod… | keep-internal |  | code comment |
| 1057 | …o list for ˋomnigent claudeˋ sessions. | keep-internal |  | code comment |
| 4595 | …n.labels?.["omnigent.wrapper"]; | keep-internal |  | Server session label key 'omnigent.wrapper' comp |
| 4895 | …dor TUI (no Omnigent picker): | keep-internal |  | code comment |
| 4940 | …n.labels?.["omnigent.startup"] === "pe… | keep-internal |  | Server session label key 'omnigent.startup' that |
| 4941 | …n.labels?.["omnigent.startup"] === "re… | keep-internal |  | Same 'omnigent.startup' server label key compari |
| 5185 | …skills/sync-omnigents/SKILL.md. | keep-internal |  | code comment |
| 6499 | … before the Databricks ingress's ~5-mi… | keep-internal |  | code comment |
| 6539 | …"ˋ end (the Databricks Apps ingress | keep-internal |  | code comment |
| 6646 | …ibeHost = isDatabricksWorkspace() | keep-internal |  | code identifier |
| 6780 | …ders.get("x-omnigent-stream-epoch"); | keep-internal |  | HTTP response header x-omnigent-stream-epoch tha |
| 6983 | …such as the Databricks Apps ~5-min str… | keep-internal |  | code comment |
| 9337 | ….doneˋ. The Omnigent server bypasses | keep-internal |  | code comment |

### `web/src/store/interactionTelemetry.test.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 3 | import { setOmnigentHostConfig } from … | keep-internal |  | test code |
| 24 | setOmnigentHostConfig({ analytics }); | keep-internal |  | test code |
| 29 | setOmnigentHostConfig({}); | keep-internal |  | test code |

### `web/src/store/streamSlots.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 12 | …lot-locks (ˋomnigent:stream-slot:0..N-… | keep-internal |  | code comment |
| 40 | …K_PREFIX = "omnigent:stream-slot:"; | keep-internal |  | Web Locks name prefix omnigent:stream-slot: shar |

### `web/src/storybook/StoryProviders.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 5 | import { getOmnigentHostConfig, setOmn… | keep-internal |  | code identifier |
| 33 | config: OmnigentHostConfig; | keep-internal |  | code identifier |
| 37 | …urrent = getOmnigentHostConfig(); | keep-internal |  | code identifier |
| 38 | setOmnigentHostConfig(config); | keep-internal |  | code identifier |
| 41 | …=> () => setOmnigentHostConfig(previou… | keep-internal |  | code identifier |

### `web/src/update-overlay.tsx`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 10 | …oad (window.omnigentNative.updates), i… | keep-internal |  | code comment |
| 35 | omnigentUpdateOverlay?: { | keep-internal |  | code identifier |
| 40 | ).omnigentUpdateOverlay; | keep-internal |  | code identifier |

### `web/src/vite-env.d.ts`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 15 | …y targets a Databricks workspace-hoste… | keep-internal |  | code comment |
| 17 | * ˋOMNIGENT_URLˋ. Signals the standalo… | keep-internal |  | code comment |
| 18 | …fic; see ˋisDatabricksWorkspaceˋ in ˋh… | keep-internal |  | code comment |
| 20 | …adonly VITE_DATABRICKS_WORKSPACE?: str… | keep-internal |  | code identifier |

### `web/update-overlay.html`

| Line | Text | Class | Seam | Reason |
|---|---|---|---|---|
| 6 | <title>Omnigent Update</title> | change | S89 | Title of the desktop update overlay window; per the e2e notes it appears in window switchers, Mission Control and screen-share pickers. |
