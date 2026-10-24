// The website's only script: real service logos (shared with the app, tunesback/web/js/brands.js),
// and download links for the newest release on GitHub, with the right one offered first.

import { brandIcon } from "./assets/brands.js";

const REPO = "mooseses/TunesBack";
const RELEASES = `https://github.com/${REPO}/releases`;

for (const tile of document.querySelectorAll("[data-brand]")) {
  tile.querySelector(".tile-logo").append(brandIcon(tile.dataset.brand, 44));
}

/** "2.0.0b1" or "v2.0.0-beta.1" → "2.0.0 Beta 1" */
function versionName(tag) {
  const m = /^v?(\d+(?:\.\d+)*)(?:[-.]?(alpha|beta|rc|a|b)[-.]?(\d*))?/i.exec(tag || "");
  if (!m) return tag;
  const stage = { a: "Alpha", alpha: "Alpha", b: "Beta", beta: "Beta", rc: "Release Candidate" }[(m[2] || "").toLowerCase()];
  return stage ? `${m[1]} ${stage}${m[3] ? ` ${m[3]}` : ""}` : m[1];
}

const megabytes = (bytes) => `${Math.round(bytes / 1e6)} MB`;

/** Which download suits this visitor: {platform, ext, label} or null (a phone, say). */
async function detect() {
  const ua = navigator.userAgent;
  const platform = navigator.userAgentData?.platform || navigator.platform || "";
  if (/android|iphone|ipad|ipod/i.test(ua)) return null;
  if (/win/i.test(platform) || /windows/i.test(ua)) return { platform: "windows", ext: "x64.exe", label: "Download for Windows" };
  if (/mac/i.test(platform) || /mac os x/i.test(ua)) {
    // Chromium can say which chip; Safari and Firefox can't, and most Macs sold now are Apple silicon.
    let arch = "arm";
    try {
      const hints = await navigator.userAgentData?.getHighEntropyValues?.(["architecture"]);
      if (hints?.architecture === "x86") arch = "x86";
    } catch { /* keep the guess */ }
    return arch === "x86"
      ? { platform: "macos", ext: "x86_64.dmg", label: "Download for Mac (Intel)" }
      : { platform: "macos", ext: "arm64.dmg", label: "Download for Mac", other: "Intel Mac? Choose it below." };
  }
  if (/linux|x11|cros/i.test(platform + ua)) return { platform: "linux", label: "Download for Linux" };
  return null;
}

async function latestRelease() {
  const response = await fetch(`https://api.github.com/repos/${REPO}/releases?per_page=10`, { headers: { Accept: "application/vnd.github+json" } });
  if (!response.ok) throw new Error(`GitHub answered ${response.status}`);
  const releases = await response.json();
  return releases.find((r) => !r.draft && r.assets?.length);
}

async function setUp() {
  const mine = await detect();
  const main = document.getElementById("download-main");
  const label = document.getElementById("download-main-label");
  const detail = document.getElementById("download-detail");
  if (mine) {
    label.textContent = mine.label;
    document.querySelector(`.files[data-platform="${mine.platform}"]`)?.closest(".platform").classList.add("detected");
  } else {
    label.textContent = "See the downloads";
    document.getElementById("download-other").hidden = true; // it would go to the same place
  }

  let release;
  try {
    release = await latestRelease();
  } catch {
    release = null;
  }
  if (!release) {
    detail.textContent = "";
    for (const file of document.querySelectorAll(".file")) file.href = RELEASES;
    return;
  }
  const name = versionName(release.tag_name);
  document.getElementById("release-badge").textContent = release.prerelease ? `New: TunesBack ${name}` : `TunesBack ${name}`;
  document.getElementById("download-lead").textContent =
    `TunesBack ${name}${release.prerelease ? ", a beta" : ""}, free and open source, for Windows, macOS and Linux.`;

  const assetFor = (ext) => release.assets.find((a) => a.name.endsWith(ext));
  for (const file of document.querySelectorAll(".file")) {
    const asset = assetFor(file.dataset.ext);
    if (asset) {
      file.href = asset.browser_download_url;
      file.title = `${asset.name} (${megabytes(asset.size)})`;
    } else {
      file.removeAttribute("href");
    }
  }
  const pick = mine?.ext && assetFor(mine.ext);
  if (pick) {
    main.href = pick.browser_download_url;
    detail.textContent = `${name} · ${pick.name.replace(/^TunesBack-/, "")} · ${megabytes(pick.size)}${mine.other ? ` · ${mine.other}` : ""}`;
  } else {
    main.href = "#download";
    detail.textContent = `${name} · Windows, macOS and Linux`;
  }
}

setUp();
