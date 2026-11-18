// A Cloudflare Worker that forwards Bot API calls to Telegram, unchanged.
//
// For a server that cannot reach api.telegram.org and finds no proxy that
// gets through. Cloudflare is reachable from Iran, and a Worker on the
// operator's own domain is a path Telegram's filtering does not see. Set the
// bot's TELEGRAM__API_BASE_URL to this Worker's address; the bot then calls
// <worker>/bot<token>/<method> exactly as it would call Telegram.
//
// ALLOWED_BOT_IDS (Settings -> Variables): the numeric ids of the bots that
// may use it - the part of each token before the colon, comma separated, ours
// and every reseller's. Without it the Worker relays for nobody, because an
// open relay is anybody's free path to the Bot API on the operator's account.
//
// Nothing is logged or stored here: every request carries a bot token in its
// path, and the Worker only passes it on.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const match = url.pathname.match(/^\/(?:file\/)?bot(\d+):[A-Za-z0-9_-]+\//);
    const allowed = (env.ALLOWED_BOT_IDS || "")
      .split(",")
      .map((id) => id.trim())
      .filter(Boolean);
    if (!match || !allowed.includes(match[1])) {
      return new Response("Not found", { status: 404 });
    }

    const target = new URL(url.pathname + url.search, "https://api.telegram.org");
    // A new request rather than the incoming one: the Host header and
    // Cloudflare's own headers must not reach Telegram.
    const init = {
      method: request.method,
      headers: { "content-type": request.headers.get("content-type") || "" },
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual",
    };
    return fetch(target.toString(), init);
  },
};
