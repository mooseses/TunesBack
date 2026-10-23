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

export const cardUrl = (index) => `/api/card/${index}.jpg?token=${encodeURIComponent(token)}`;

// Artwork is requested lazily, in small batches, as rows scroll into view.
const artCache = new Map();
const waiting = new Map();
let flushTimer = null;

export function artwork(location) {
  if (!location) return Promise.resolve(null);
  if (artCache.has(location)) return Promise.resolve(artCache.get(location));
  return new Promise((resolve) => {
    if (!waiting.has(location)) waiting.set(location, []);
    waiting.get(location).push(resolve);
    clearTimeout(flushTimer);
    flushTimer = setTimeout(flushArtwork, 40);
  });
}

async function flushArtwork() {
  const batch = [...waiting.keys()].slice(0, 24);
  if (!batch.length) return;
  const result = await call("artwork", { locations: batch });
  for (const location of batch) {
    const uri = result.art ? result.art[location] ?? null : null;
    artCache.set(location, uri);
    for (const resolve of waiting.get(location) || []) resolve(uri);
    waiting.delete(location);
  }
  if (waiting.size) flushTimer = setTimeout(flushArtwork, 0);
}

export function clearArtwork() {
  artCache.clear();
}
