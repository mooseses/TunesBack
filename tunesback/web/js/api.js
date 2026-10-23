// Talks to the local Python server. The token proves requests come from this page.

const token = document.querySelector('meta[name="tunesback-token"]').content;

export async function call(method, args = {}) {
  let response;
  try {
    response = await fetch(`/api/${method}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-TunesBack-Token": token },
      body: JSON.stringify(args),
    });
  } catch {
    return { error: "TunesBack's background process isn't responding. Try restarting the app." };
  }
  if (!response.ok) return { error: `Request failed (${response.status})` };
  return response.json();
}

/** A card image: `size` is "thumb", "preview" or "full". */
export function cardImageUrl(card, format, size, seed, rank, extra = {}) {
  const query = new URLSearchParams({ s: seed, r: rank, token, ...extra });
  return `/api/card/${card.type}/${card.layout}/${card.theme}/${format}/${size}.jpg?${query}`;
}

// ---------- artwork ----------
// Thumbnails load lazily as tiles scroll into view, a batch at a time.
// Anything already fetched is applied synchronously, so redraws never flash.

const artCache = new Map(); // location -> data URI, or null when there is none
const queue = new Map(); // location -> Set of tiles waiting for it
const BATCH = 16;
const PARALLEL = 2;
let inFlight = 0;
let flushTimer = null;

export function cachedArtwork(location) {
  return artCache.get(location);
}

export function requestArtwork(location, tile) {
  if (!queue.has(location)) queue.set(location, new Set());
  queue.get(location).add(tile);
  if (!flushTimer) flushTimer = setTimeout(flush, 16);
}

function flush() {
  flushTimer = null;
  while (inFlight < PARALLEL && queue.size) {
    const batch = [];
    for (const [location, tiles] of queue) {
      queue.delete(location);
      const live = [...tiles].filter((t) => t.isConnected);
      if (!live.length) continue; // scrolled away or view changed
      batch.push([location, live]);
      if (batch.length === BATCH) break;
    }
    if (!batch.length) return;
    inFlight++;
    call("artwork", { locations: batch.map(([location]) => location) }).then((result) => {
      inFlight--;
      for (const [location, tiles] of batch) {
        const uri = result.art ? result.art[location] ?? null : undefined;
        if (uri !== undefined) artCache.set(location, uri);
        if (uri) tiles.forEach((tile) => paintArtwork(tile, uri, true));
      }
      if (queue.size) flush();
    });
  }
}

export function paintArtwork(tile, uri, animate) {
  tile.style.backgroundImage = `url("${uri}")`;
  tile.classList.add("loaded");
  if (animate) tile.classList.add("fade-in");
}
