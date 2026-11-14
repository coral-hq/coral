// CORAL(S87): Coral's desktop identity (BRD-03): names, ids, scheme, update feed
// and contact links shown or registered by the Electron shell. The packaging
// metadata in package.json mirrors these values; test/brand.test.js keeps the
// two in step and refuses Omnigent or Databricks publisher identity.

"use strict";

/** User-visible product name: menus, dialogs, notifications, window titles. */
const PRODUCT_NAME = "Coral";

/** Product name of dev builds, which install beside packaged ones. */
const DEV_PRODUCT_NAME = "Coral Dev";

/** Reverse-DNS id macOS and Windows use to tell apps apart (`build.appId`). */
const APP_ID = "io.github.coral-hq.coral";

/** Id of dev builds (`-c.appId` in the package.json build scripts). */
const DEV_APP_ID = `${APP_ID}-dev`;

/** Session-link scheme: `coral://<host>[:port]/<path>`. */
const URL_SCHEME = "coral";

/** CLI binaries the shell detects: upstream's names first, then `coral`. */
const CLI_NAMES = ["omnigent", "omni", "coral"];

/**
 * Install one-liner shown when no CLI is found. Coral has no distribution of
 * its own yet, so this stays Omnigent's installer until OPS-09.
 */
const INSTALL_COMMAND =
  "curl -fsSL https://raw.githubusercontent.com/omnigent-ai/omnigent/main/scripts/install_oss.sh | sh";

/** electron-updater feed: Coral's GitHub release assets. */
const UPDATE_FEED_URL = "https://github.com/coral-hq/coral/releases/latest/download/";

const SUPPORT_EMAIL = "coralai.team@gmail.com";
const HOMEPAGE = "https://github.com/coral-hq/coral";
const PRIVACY_URL = "https://github.com/coral-hq/coral/blob/main/PRIVACY.md";

module.exports = {
  PRODUCT_NAME,
  DEV_PRODUCT_NAME,
  APP_ID,
  DEV_APP_ID,
  URL_SCHEME,
  CLI_NAMES,
  INSTALL_COMMAND,
  UPDATE_FEED_URL,
  SUPPORT_EMAIL,
  HOMEPAGE,
  PRIVACY_URL,
};
