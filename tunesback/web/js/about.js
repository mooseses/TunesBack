// About TunesBack (styled like a Mac app's About window) and the privacy policy,
// plus the notes that point people to the privacy policies of online services.
// PRIVACY.md in the repository has the same policy.

import { call } from "./api.js";
import { state } from "./app.js";
import { h, icon } from "./util.js";

const WEBSITE = "https://github.com/mooseses/TunesBack";
export const POLICIES = {
  lastfm: { name: "Last.fm", url: "https://www.last.fm/legal/privacy" },
  listenbrainz: { name: "MetaBrainz", url: "https://metabrainz.org/privacy", covers: "ListenBrainz and the Cover Art Archive" },
  spotify: { name: "Spotify", url: "https://www.spotify.com/legal/privacy-policy/" },
};
const EFFECTIVE = "October 23, 2026";

/** A link that opens in the system browser (the desktop window can't navigate away). */
export function externalLink(url, ...children) {
  return h("a", {
    href: url, target: "_blank", rel: "noreferrer",
    onclick: (event) => {
      if (!state.info?.desktop) return;
      event.preventDefault();
      call("open_url", { url });
    },
  }, children.length ? children : url);
}

/** The heads-up shown wherever an online service is connected. */
export function serviceNote(kind) {
  const policy = POLICIES[kind];
  const text = kind === "spotify"
    ? ["TunesBack only reads the file you choose and never connects to Spotify. What Spotify keeps about you is covered by ",
      externalLink(policy.url, "Spotify's privacy policy"), "."]
    : [`Connecting sends your user name to ${kind === "lastfm" ? "Last.fm" : "ListenBrainz"}. TunesBack collects nothing itself, `
      + "but it can't control what an online service collects, such as your IP address. Please read ",
    externalLink(policy.url, `${policy.name}'s privacy policy`), " before you connect."];
  return h("div.privacy-note", icon("shield"), h("span", text));
}

// ---------- the dialog ----------

const dialog = () => document.getElementById("about-dialog");

/** Open About, or go straight to the privacy policy (`page: "privacy"`, e.g. from set-up). */
export function openAbout({ page = "about" } = {}) {
  const d = dialog();
  show(page === "privacy" ? privacyPage({ back: false }) : aboutPage(), "none");
  if (!d.open) d.showModal();
}

export const openPrivacy = () => openAbout({ page: "privacy" });

function show(page, direction) {
  page.classList.add(`enter-${direction}`);
  dialog().replaceChildren(page);
  page.querySelector("[autofocus]")?.focus({ preventScroll: true });
}

function closeButton() {
  return h("button.btn.btn-ghost.about-close", { "aria-label": "Close", onclick: () => dialog().close() }, icon("close"));
}

function aboutPage() {
  return h("div.about-page",
    closeButton(),
    h("div.about-mac",
      h("img.about-icon", { src: "/assets/icon.png", alt: "", width: 128, height: 128 }),
      h("div.about-info",
        h("h2", { id: "about-title", tabindex: "-1", autofocus: true }, "TunesBack"),
        h("p.about-version", `Version ${state.info?.version ?? ""}`),
        h("p.about-desc", "Year-in-review statistics for your music library."),
        h("p.about-promise", icon("shield"), h("span", h("b", "Collects no data."), " Your music and listening history stay on this computer.")),
        h("p.about-legal", "© Peter Jin and contributors", h("br"), "Free software under the GNU General Public License v3"),
        h("div.about-buttons",
          h("button.btn", { onclick: () => show(privacyPage({ back: true }), "forward") }, "Privacy Policy"),
          h("button.btn", {
            onclick: () => (state.info?.desktop ? call("open_website") : window.open(WEBSITE, "_blank", "noreferrer")),
          }, "Website", icon("external"))))));
}

function privacyPage({ back }) {
  return h("div.about-page.privacy-page",
    h("div.privacy-head",
      back
        ? h("button.btn.btn-ghost.btn-small", { onclick: () => show(aboutPage(), "back") }, "‹ About")
        : h("span"),
      h("h2", { id: "about-title", tabindex: "-1", autofocus: true }, "Privacy Policy"),
      closeButton()),
    h("div.privacy-body", privacyPolicy()));
}

/** The policy itself. Keep PRIVACY.md in step with it. */
export function privacyPolicy() {
  const link = (kind) => {
    const p = POLICIES[kind];
    return h("li", externalLink(p.url, `${p.name} Privacy Policy`), p.covers ? ` (${p.covers})` : "");
  };
  return [
    h("div.privacy-hero",
      h("span.privacy-shield", icon("shield")),
      h("div",
        h("h3", "Your music is nobody's business but yours."),
        h("p", "TunesBack collects no data. None. No account, no analytics, no ads, no tracking, no “anonymous usage statistics”. "
          + "There isn't even a TunesBack server for anything to be sent to."))),
    section("Everything happens on your computer",
      "TunesBack reads your music library and listening history, works out your stats and draws your Wrapped cards right here. "
      + "What it remembers (your sources, your listens and your settings) is saved in TunesBack's own folders on this computer, and nowhere else."),
    section("We don't collect anything",
      "Not your library, not your listening history, not how you use the app, not crash reports. Nothing reaches us, because there's nothing for it to reach."),
    section("Online features: you're in charge",
      "TunesBack goes online only when you use a feature that needs to:",
      h("ul",
        h("li", h("b", "Last.fm"), ": to read your scrobbles with the user name (and API key) you give it, and to fetch album covers."),
        h("li", h("b", "ListenBrainz"), ": to read your listens, with album covers from the Cover Art Archive.")),
      h("p", "These requests go straight from your computer to those services. Like any website, they can see things such as your IP address "
        + "and what was asked for, and their own privacy policies decide what happens next. ",
      h("b", "TunesBack can't control what they collect"), ", so please read their policies before you connect:"),
      h("ul.privacy-links", link("lastfm"), link("listenbrainz"), link("spotify")),
      h("p.muted", "Spotify is different: TunesBack never connects to it, and only reads the download you choose. "
        + "Spotify's policy covers what it keeps and what it put in that download.")),
    section("Sharing is your call",
      "Wrapped cards are saved only where you save them. Once you post them, what happens next is up to you and the place you post them."),
    section("Take it all back",
      "Remove a source on the Services or Library page and TunesBack deletes what it imported from it. To erase everything, quit TunesBack and delete its folders "
      + "(the Dev space lists where they are)."),
    section("If this ever changes",
      "Any change to this policy will be announced in the release notes before it ships. Questions? Ask on ",
      externalLink(WEBSITE, "GitHub"), "."),
    h("p.privacy-date", `Effective ${EFFECTIVE}`),
  ];
}

function section(title, ...body) {
  return h("section.privacy-section", h("h4", title), body.map((part) => (typeof part === "string" ? h("p", part) : part)));
}
