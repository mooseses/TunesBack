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
      : { platform: "macos", ext: "arm64.dmg", label: "Download for Mac", other: "Intel Macs: see below" };
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

// ---------- the card browser ----------
// A fan of cards (cards/, drawn by the app from a sample library when the site is built):
// arrows, keys, a swipe or a click on a neighbour moves through the deck; each card keeps
// the layout and theme you pick for it, and Shuffle deals every card its own.

const deckEl = document.getElementById("deck-cards");

async function setUpStudio() {
  let manifest;
  try {
    const response = await fetch("cards/cards.json");
    if (!response.ok) throw new Error(String(response.status));
    manifest = await response.json();
  } catch {
    document.querySelector(".studio-body").hidden = true;
    document.querySelector(".studio-fallback").hidden = false;
    return;
  }
  const { cards, themes } = manifest;
  const random = (n) => Math.floor(Math.random() * n);
  // Each card starts in its first layout, with the themes dealt out so neighbours differ.
  const dealt = themes.map((t) => t.id).sort(() => Math.random() - 0.5);
  const choice = cards.map((card, i) => ({ layout: card.layouts[0].id, theme: dealt[i % dealt.length] }));
  let current = 0;
  const src = (i) => `cards/${cards[i].id}-${choice[i].layout}-${choice[i].theme}.webp`;

  const figures = cards.map((card, i) => {
    const img = new Image();
    img.alt = card.name;
    img.decoding = "async";
    img.src = src(i);
    const figure = document.createElement("figure");
    figure.className = "deck-card";
    figure.append(img);
    figure.addEventListener("click", () => { if (i !== current) go(i); });
    deckEl.append(figure);
    return figure;
  });

  /** The fan: the current card in front, two on each side tilting away, the rest hidden. */
  function place() {
    const n = cards.length;
    figures.forEach((figure, i) => {
      let offset = i - current;
      if (offset > n / 2) offset -= n;
      if (offset < -n / 2) offset += n;
      const side = Math.sign(offset);
      const step = Math.abs(offset);
      const visible = step <= 2;
      figure.classList.toggle("current", offset === 0);
      figure.style.zIndex = String(20 - step);
      figure.style.opacity = visible ? "1" : "0";
      figure.style.pointerEvents = visible ? "auto" : "none";
      figure.style.filter = step ? `brightness(${1 - step * 0.2})` : "";
      figure.style.transform = `translate(-50%, -50%) translateX(${side * (step ? 40 + (step - 1) * 26 : 0)}%)
        scale(${1 - step * 0.13}) rotateY(${-side * step * 12}deg) rotateZ(${side * step * 2.5}deg)`;
      figure.setAttribute("aria-hidden", String(offset !== 0));
    });
    // Load the neighbours' pictures ahead of time.
    for (const d of [1, -1, 2, -2]) new Image().src = src((current + d + n) % n);
    renderControls();
  }

  function go(i) {
    current = (i + cards.length) % cards.length;
    place();
  }

  /** Swap one card's picture without a flash: the new one fades in once it has loaded. */
  function repaint(i) {
    const figure = figures[i];
    const next = new Image();
    next.alt = cards[i].name;
    next.src = src(i);
    next.style.opacity = "0";
    next.onload = () => {
      figure.append(next);
      requestAnimationFrame(() => { next.style.opacity = "1"; });
      const old = [...figure.querySelectorAll("img")].filter((img) => img !== next);
      setTimeout(() => old.forEach((img) => img.remove()), 280);
    };
  }

  const chip = (label, pressed, onclick, swatch) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "chip";
    button.setAttribute("aria-pressed", String(pressed));
    if (swatch) {
      const dot = document.createElement("span");
      dot.className = "swatch";
      dot.style.background = swatch.length > 1
        ? `conic-gradient(${swatch.map((c, k) => `${c} ${(k / swatch.length) * 360}deg ${((k + 1) / swatch.length) * 360}deg`).join(", ")})`
        : swatch[0];
      button.append(dot);
    }
    button.append(label);
    button.addEventListener("click", onclick);
    return button;
  };

  function renderControls() {
    const card = cards[current];
    document.getElementById("studio-name").textContent = card.name;
    document.getElementById("studio-count").textContent = `${current + 1} of ${cards.length}`;
    document.getElementById("studio-layouts").replaceChildren(...card.layouts.map((layout) =>
      chip(layout.name, layout.id === choice[current].layout, () => {
        choice[current].layout = layout.id;
        repaint(current);
        renderControls();
      })));
    document.getElementById("studio-themes").replaceChildren(...themes.map((theme) =>
      chip(theme.name, theme.id === choice[current].theme, () => {
        choice[current].theme = theme.id;
        repaint(current);
        renderControls();
      }, theme.swatch)));
  }

  document.getElementById("studio-shuffle").addEventListener("click", () => {
    const order = themes.map((t) => t.id).sort(() => Math.random() - 0.5);
    cards.forEach((card, i) => {
      choice[i] = { layout: card.layouts[random(card.layouts.length)].id, theme: order[i % order.length] };
      repaint(i);
    });
    renderControls();
  });
  document.querySelector(".deck-arrow.prev").addEventListener("click", () => go(current - 1));
  document.querySelector(".deck-arrow.next").addEventListener("click", () => go(current + 1));
  const deck = document.getElementById("deck");
  deck.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); go(current - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); go(current + 1); }
  });
  // Swipe on touch screens (and drag with a mouse).
  let startX = null;
  deck.addEventListener("pointerdown", (e) => { startX = e.clientX; });
  deck.addEventListener("pointerup", (e) => {
    if (startX === null) return;
    const dx = e.clientX - startX;
    startX = null;
    if (Math.abs(dx) > 40) go(current + (dx < 0 ? 1 : -1));
  });
  place();
}

setUpStudio();
