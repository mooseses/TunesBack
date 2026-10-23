import { call, cardUrl } from "../api.js";
import { hideBusy, render as renderApp, showBusy, state } from "../app.js";
import { h, icon, showMessage, toast } from "../util.js";

export function render(root) {
  const by = state.settings.rank_by === "time" ? "listening time" : "play count";
  root.append(h("div.card.wrapped-intro",
    h("div",
      h("div.card-title", { style: { marginBottom: "6px" } }, "Shareable cards"),
      h("p", `Story-sized images of your top songs, albums, genres and more, ranked by ${by}. Change the ranking at the top right.`)),
    h("button.btn.btn-primary.btn-large", { onclick: generate }, icon("wrapped"), state.cards ? "Regenerate" : "Generate cards")));

  if (!state.cards) return;
  const selected = state.selectedCards;
  const gallery = h("div.gallery", state.cards.map((card) => {
    const tile = h(`button.card-tile${selected.has(card.index) ? ".selected" : ""}`, {
      type: "button", "aria-pressed": String(selected.has(card.index)), "aria-label": `Select ${card.name}`,
    },
      h("img", { src: card.preview, alt: card.name, loading: "lazy" }),
      h("span.check", icon("check")),
      h("span.name", card.name));
    tile.addEventListener("click", () => {
      if (selected.has(card.index)) selected.delete(card.index); else selected.add(card.index);
      tile.classList.toggle("selected");
      tile.setAttribute("aria-pressed", String(selected.has(card.index)));
      updateSaveBar();
    });
    return tile;
  }));

  const saveSelected = h("button.btn", { onclick: () => save([...selected]) }, icon("download"), "");
  const selectAll = h("button.btn.btn-ghost", { onclick: () => {
    const all = selected.size !== state.cards.length;
    selected.clear();
    if (all) state.cards.forEach((c) => selected.add(c.index));
    renderApp();
  } }, "");
  const updateSaveBar = () => {
    saveSelected.lastChild.textContent = `Save selected (${selected.size})`;
    saveSelected.disabled = !selected.size;
    selectAll.textContent = selected.size === state.cards.length ? "Select none" : "Select all";
  };
  updateSaveBar();

  root.append(gallery, h("div.save-bar", selectAll, saveSelected,
    h("button.btn.btn-primary", { onclick: () => save(null) }, icon("download"), "Save all")));
}

async function generate() {
  showBusy("Drawing your cards…");
  const result = await call("generate_cards", { rank_by: state.settings.rank_by });
  hideBusy();
  if (result.error) return showMessage("Couldn't make the cards", result.error);
  state.cards = result.cards;
  state.selectedCards.clear();
  renderApp();
}

export async function save(indices) {
  if (!state.info.desktop) {
    // In a browser, hand the full-size images to the browser's own downloads.
    for (const index of indices ?? state.cards.map((c) => c.index)) {
      h("a", { href: cardUrl(index), download: "" }).click();
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    return;
  }
  const result = await call("save_cards", { indices });
  if (result.error) return toast(result.error, { error: true });
  if (result.saved) toast(`Saved ${result.saved} card${result.saved === 1 ? "" : "s"} to ${result.folder}`);
}
