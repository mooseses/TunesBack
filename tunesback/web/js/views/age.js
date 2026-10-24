// Listening age: the era your music comes from. Press Calculate and TunesBack sweeps a
// five-year window across the release years you played until it lands on your
// era, counting the age as it goes.

import { navigate, reducedMotion, saveSettingsNow, state } from "../app.js";
import { h, icon, number } from "../util.js";
import { editCard } from "./wrapped.js";

const WINDOW = 5;
const FORMATIVE_AGE = 18;

let shownFor = null; // the recap whose result is on screen (so redraws don't replay it)
let frame = null;

export function render(root) {
  const report = state.report;
  const age = report.listening_age;
  if (!age) {
    root.append(h("div.card.age-empty",
      h("span.invite-icon", icon("age")),
      h("h2", "No listening age for this recap"),
      h("p.muted", "It needs release years on the songs you played. iTunes and Apple Music libraries usually have them; TunesBack fills them in for Last.fm, ListenBrainz and Spotify listens it can match to your library.")));
    return;
  }
  const data = histogram(report);
  if (shownFor !== report) {
    root.append(intro(() => {
      shownFor = report;
      if (!state.settings.age_calculated) saveSettingsNow({ age_calculated: true });
      const stage = result(report, data);
      root.replaceChildren(stage);
      play(stage, report, data);
    }), methodology());
    return;
  }
  root.append(result(report, data));
}

function intro(start) {
  return h("div.card.age-intro",
    h("div.age-orbit", h("span"), h("span"), h("span"), icon("age")),
    h("h2", "What era is your music from?"),
    h("p.muted", "Most people love the music of their late teens for life. TunesBack finds the five years of releases you played most, then works out how old you'd be if you were 18 back then."),
    h("button.btn.btn-primary.btn-large", { "data-autofocus": true, onclick: start }, "Calculate", icon("arrow")));
}

/** Plays per release year, every year from the oldest to the newest (gaps as zero). */
function histogram(report) {
  const counts = new Map();
  for (const e of report.years) {
    const year = Number(e.title);
    if (year > 1900) counts.set(year, (counts.get(year) || 0) + e.plays);
  }
  const { era_start: eraStart, era_end: eraEnd } = report.listening_age;
  const first = Math.min(eraStart, ...counts.keys());
  const last = Math.max(eraEnd, ...counts.keys());
  const years = Array.from({ length: last - first + 1 }, (_, i) => first + i);
  const total = [...counts.values()].reduce((a, b) => a + b, 0);
  const inEra = years.filter((y) => y >= eraStart && y <= eraEnd).reduce((sum, y) => sum + (counts.get(y) || 0), 0);
  const peak = years.reduce((a, b) => ((counts.get(b) || 0) > (counts.get(a) || 0) ? b : a), years[0]);
  return { counts, years, first, last, total, inEra, peak, max: Math.max(1, ...counts.values()) };
}

const reference = (report) => Number(report.end_date.slice(0, 4));
const ageFor = (report, start) => reference(report) - (start + Math.floor(WINDOW / 2) - FORMATIVE_AGE);

function result(report, data) {
  const age = report.listening_age;
  const born = age.era_start + Math.floor(WINDOW / 2) - FORMATIVE_AGE;
  const pct = data.total ? Math.round((data.inEra / data.total) * 100) : 0;
  const bars = data.years.map((year) => {
    const plays = data.counts.get(year) || 0;
    const era = year >= age.era_start && year <= age.era_end;
    return h(`div.age-bar${era ? ".in" : ""}`, { "data-year": year, title: `${year}: ${number(plays)} plays` },
      h("span", { style: `--h: ${Math.max(plays ? 2 : 0, (plays / data.max) * 100)}%` })); // custom properties need the string form
  });
  const decades = data.years.filter((y) => y % 10 === 0);
  const ticks = decades.length >= 2 ? decades : [data.first, data.last];
  const left = (year) => `${((year - data.first) / data.years.length) * 100}%`;

  return h("div.age-stage",
    h("div.card.age-hero",
      h("div.age-number",
        h("span.label", "Your listening age"),
        h("div.age-value", { "aria-live": "polite" }, String(age.age)),
        h("div.age-era", `Into the music of the ${age.era_label}`)),
      h("div.age-chart",
        h("div.age-bars", { role: "img", "aria-label": `Plays by release year, ${data.first} to ${data.last}. Your era: ${age.era_start} to ${age.era_end}.` },
        bars,
        h("div.age-window", { style: { left: left(age.era_start), width: `${(WINDOW / data.years.length) * 100}%` } },
          h("span", `${age.era_start}–${age.era_end}`))),
        h("div.age-ticks", ticks.map((y) => h("span", { style: { left: left(y + 0.5) } }, y))))),
    h("div.age-facts",
      fact("Your era", `${age.era_start} – ${age.era_end}`, "the five release years you played most"),
      fact("Share of your plays", `${pct}%`, "came out in those five years"),
      fact("Most played year", String(data.peak), `${number(data.counts.get(data.peak) || 0)} plays`),
      fact("Musically born in", String(born), `18 in ${born + FORMATIVE_AGE}, the middle of your era`)),
    choices(report, data),
    methodology(report, data));
}

/** Where else the age may appear: nowhere until you say so. */
function choices(report, data) {
  const s = state.settings;
  const toggle = (key, title, desc, after) => h("label.switch.setting",
    h("div", h("div", { style: { fontWeight: 600 } }, title), h("div.desc", desc)),
    h("input", {
      type: "checkbox", role: "switch", checked: s[key] === true,
      onchange: async (e) => { await saveSettingsNow({ [key]: e.target.checked }); after?.(); },
    }));
  return h("div.card.age-choices",
    h("div.card-title", "Use your listening age", h("span.muted", "only where you want it")),
    toggle("age_overview", "Show on the Overview", "A card with your age and era, next to Genres."),
    toggle("age_cards", "Listening age cards in Wrapped", "Two designs to share: Big number and Timeline.",
      () => { state.deck = null; }),
    h("div.age-actions",
      h("button.btn", { onclick: (e) => replay(e.target.closest(".age-stage"), report, data) }, icon("refresh"), "Replay"),
      h("button.btn.btn-primary", {
        onclick: async () => {
          if (!state.settings.age_cards) await saveSettingsNow({ age_cards: true });
          state.deck = null;
          navigate("wrapped");
          editCard("listening_age");
        },
      }, icon("wrapped"), "Make a card")));
}

/** How the number comes about, with your own numbers once it's been worked out. */
function methodology(report = null, data = null) {
  const age = report?.listening_age;
  let examples = [];
  if (age && data) {
    const years = [...data.counts.keys()];
    const windows = years.length ? Math.max(...years) - Math.min(...years) + 1 : 0;
    const middle = age.era_start + Math.floor(WINDOW / 2);
    const pct = data.total ? Math.round((data.inEra / data.total) * 100) : 0;
    examples = [
      `You: ${number(data.total)} plays across ${data.counts.size} release years`,
      `You: ${number(windows)} windows, from ${Math.min(...years)} onwards`,
      `You: ${age.era_start}–${age.era_end}, with ${pct}% of those plays`,
      `You: ${reference(report)} − (${middle} − ${FORMATIVE_AGE}) = ${age.age}`,
    ];
  }
  const steps = [
    ["Count your plays by release year", "Every play of a song counts toward the year it came out. Songs without a release year are left out."],
    ["Slide a five-year window", "A five-year window moves along those years one year at a time, adding up the plays inside it."],
    ["Find the busiest five years", "The window with the most plays is your era. If two windows tie, the earlier one wins."],
    ["Work out the age", "The middle year of your era is when you'd have been 18. Your listening age is how old that person is in the last year of the recap."],
  ];
  return h("div.card.age-method",
    h("div.card-title", "How it's calculated"),
    h("p.muted.age-method-lead", "Psychologists call it the reminiscence bump: the music of our teens and early twenties stays with us more than any other. "
      + "Listening age runs that backwards. From the music you play, it guesses when you were 18."),
    h("ol.age-steps", steps.map(([title, text], i) => h("li",
      h("span.age-step-num", i + 1),
      h("div", h("b", title), h("p.muted", text), examples[i] && h("div.age-step-example", examples[i]))))),
    h("p.hint", "Only the recap's period counts, and re-releases and compilations count in the year of the copy you played. "
      + "It's a bit of fun, not a diagnosis."));
}

function fact(label, value, note) {
  return h("div.card.age-fact", h("span.label", label), h("b", value), h("small.muted", note));
}

function replay(stage, report, data) {
  const fresh = result(report, data);
  stage.replaceWith(fresh);
  play(fresh, report, data);
}

const easeInOut = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);

/** The reveal: bars grow, the window sweeps from the oldest year to the era, the age counts along. */
function play(stage, report, data) {
  cancelAnimationFrame(frame);
  if (reducedMotion()) {
    stage.classList.add("done");
    return;
  }
  const age = report.listening_age;
  const value = stage.querySelector(".age-value");
  const win = stage.querySelector(".age-window");
  const bars = [...stage.querySelectorAll(".age-bar")];
  const final = win.style.left;
  stage.classList.add("playing");
  bars.forEach((bar, i) => bar.style.setProperty("--delay", `${Math.round((i / bars.length) * 500)}ms`));
  void stage.offsetWidth; // start the bars from zero
  stage.classList.add("grow");

  const span = age.era_start - data.first;
  const sweep = Math.min(2400, 900 + span * 40); // longer journeys take a little longer
  const begin = performance.now() + 900;
  const step = (now) => {
    if (!stage.isConnected) return;
    const t = Math.min(1, Math.max(0, (now - begin) / sweep));
    const position = easeInOut(t) * span; // years from the oldest
    const start = Math.round(data.first + position);
    stage.classList.toggle("sweeping", now >= begin);
    win.style.left = `${(position / data.years.length) * 100}%`;
    win.querySelector("span").textContent = `${start}–${start + WINDOW - 1}`;
    value.textContent = String(ageFor(report, start));
    for (const bar of bars) {
      const year = Number(bar.dataset.year);
      bar.classList.toggle("in", now >= begin && year >= start && year < start + WINDOW);
    }
    if (t < 1) {
      frame = requestAnimationFrame(step);
      return;
    }
    win.style.left = final;
    value.textContent = String(age.age);
    stage.classList.remove("playing", "grow", "sweeping");
    stage.classList.add("done");
  };
  frame = requestAnimationFrame(step);
}
