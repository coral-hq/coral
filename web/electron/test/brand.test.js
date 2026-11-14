// CORAL(S87): Coral desktop identity (BRD-03). brand.js and the packaging
// metadata in package.json must name Coral, never Omnigent or Databricks as
// the publisher, and must ship the licence files Apache-2.0 §4 requires.

const { describe, it } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const yaml = require("js-yaml");

const brand = require("../src/brand");
const packageConfig = require("../package.json");

const FORBIDDEN_PUBLISHER = /databricks|omnigent\.ai|ai\.omnigent/i;
const ROOT = path.join(__dirname, "..");

/** Every update-feed URL electron-builder would publish to or read from. */
function publishUrls(build) {
  return [build, build.mac, build.linux, build.win]
    .flatMap((section) => section?.publish ?? [])
    .map((entry) => entry.url);
}

describe("brand.js", () => {
  it("names Coral and Coral's ids, scheme and feed", () => {
    assert.equal(brand.PRODUCT_NAME, "Coral");
    assert.equal(brand.DEV_PRODUCT_NAME, "Coral Dev");
    assert.equal(brand.APP_ID, "io.github.coral-hq.coral");
    assert.equal(brand.DEV_APP_ID, "io.github.coral-hq.coral-dev");
    assert.equal(brand.URL_SCHEME, "coral");
    assert.equal(
      brand.UPDATE_FEED_URL,
      "https://github.com/coral-hq/coral/releases/latest/download/",
    );
    assert.equal(brand.HOMEPAGE, "https://github.com/coral-hq/coral");
    assert.equal(brand.SUPPORT_EMAIL, "coralai.team@gmail.com");
    assert.equal(brand.PRIVACY_URL, "https://github.com/coral-hq/coral/blob/main/PRIVACY.md");
  });

  it("detects the existing CLI names plus coral and keeps the upstream installer", () => {
    assert.deepEqual(brand.CLI_NAMES, ["omnigent", "omni", "coral"]);
    assert.match(brand.INSTALL_COMMAND, /install_oss\.sh \| sh$/);
  });
});

describe("package.json publisher identity", () => {
  it("never names Omnigent or Databricks as author, homepage, app id, signer or maintainer", () => {
    const { build } = packageConfig;
    const fields = {
      author: JSON.stringify(packageConfig.author),
      homepage: packageConfig.homepage,
      "build.appId": build.appId,
      "build.mac.identity": JSON.stringify(build.mac.identity),
      "build.linux.maintainer": build.linux.maintainer,
    };
    for (const [field, value] of Object.entries(fields)) {
      assert.doesNotMatch(String(value), FORBIDDEN_PUBLISHER, field);
    }
  });

  it("publishes and reads updates only from the Coral feed", () => {
    const urls = publishUrls(packageConfig.build);
    assert.equal(urls.length, 4);
    for (const url of urls) {
      assert.doesNotMatch(url, FORBIDDEN_PUBLISHER, url);
      assert.equal(url, brand.UPDATE_FEED_URL);
    }
    const devFeed = yaml.load(fs.readFileSync(path.join(ROOT, "dev-app-update.yml"), "utf8"));
    assert.equal(devFeed.url, brand.UPDATE_FEED_URL);
    assert.equal(devFeed.updaterCacheDirName, "coral-desktop-updater-dev");
  });

  it("mirrors brand.js in the product name, app ids and dev build overrides", () => {
    const { build, scripts } = packageConfig;
    assert.equal(packageConfig.productName, brand.PRODUCT_NAME);
    assert.equal(build.productName, brand.PRODUCT_NAME);
    assert.equal(build.appId, brand.APP_ID);
    assert.equal(packageConfig.homepage, brand.HOMEPAGE);
    assert.equal(packageConfig.author.email, brand.SUPPORT_EMAIL);
    for (const name of ["build", "build:mac", "build:linux", "build:win"]) {
      assert.match(
        scripts[name],
        new RegExp(`-c\\.appId=${brand.DEV_APP_ID.replaceAll(".", "\\.")} `),
      );
      assert.match(scripts[name], /-c\.productName='Coral Dev'/);
    }
  });

  it("credits Databricks for Omnigent in the copyright line", () => {
    assert.match(packageConfig.build.copyright, /The Coral Authors/);
    assert.match(packageConfig.build.copyright, /Portions Copyright \(2026\) Databricks, Inc\./);
  });

  it("ships LICENSE, NOTICE, MODIFICATIONS.md and the font licences in every package", () => {
    const resources = packageConfig.build.extraResources;
    for (const name of ["LICENSE", "NOTICE", "MODIFICATIONS.md"]) {
      const entry = resources.find((resource) => resource.to === `legal/${name}`);
      assert.ok(entry, `missing legal/${name}`);
      assert.ok(fs.existsSync(path.join(ROOT, entry.from)), entry.from);
    }
    for (const font of ["geist-mono", "newsreader"]) {
      const entry = resources.find((resource) => resource.to === `legal/${font}-OFL-1.1.txt`);
      assert.ok(entry, `missing the ${font} OFL text`);
      assert.ok(fs.existsSync(path.join(ROOT, entry.from)), entry.from);
    }
  });
});

describe("desktop sources", () => {
  it("never use the Omnigent app id outside comments", () => {
    const sourceDir = path.join(ROOT, "src");
    for (const file of fs.readdirSync(sourceDir).filter((name) => name.endsWith(".js"))) {
      const lines = fs.readFileSync(path.join(sourceDir, file), "utf8").split("\n");
      lines.forEach((line, index) => {
        const code = line.trim();
        if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*")) return;
        assert.ok(!code.includes("ai.omnigent.desktop"), `${file}:${index + 1}: ${code}`);
      });
    }
  });
});
