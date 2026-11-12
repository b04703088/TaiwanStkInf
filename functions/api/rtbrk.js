/* 盤中熱門股券商進出（櫃買中心）代理：瀏覽器不能直接跨網域抓櫃買，由 Cloudflare Pages Function 轉一手。
   回傳 {fetched, vol, amt}；vol/amt 是櫃買原始 JSON（tables[0].subtitle / fields / data）。
   邊緣快取 60 秒：同一分鐘內不論多少人開頁面，只打櫃買一次。 */
const SRC = "https://www.tpex.org.tw/www/zh-tw/mostActive/";
const TTL = 60;

async function pull(kind) {
  const r = await fetch(SRC + kind + "?response=json", {
    headers: { "User-Agent": "Mozilla/5.0 (tide-stk-infs)", "Accept": "application/json" },
  });
  if (!r.ok) throw new Error(kind + " HTTP " + r.status);
  const j = await r.json();
  if (!j || !j.tables || !j.tables[0]) throw new Error(kind + " 格式不符");
  return j.tables[0];
}

export async function onRequestGet(ctx) {
  const cache = caches.default;
  const key = new Request("https://tide-cache.invalid/api/rtbrk");
  const hit = await cache.match(key);
  if (hit) return hit;
  let body, status = 200;
  try {
    const [vol, amt] = await Promise.all([pull("brokerVol"), pull("brokerAmt")]);
    body = JSON.stringify({ fetched: new Date().toISOString(), vol, amt });
  } catch (e) {
    status = 502;
    body = JSON.stringify({ error: String(e && e.message || e) });
  }
  const resp = new Response(body, {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": status === 200 ? "public, max-age=" + TTL : "no-store",
    },
  });
  if (status === 200) ctx.waitUntil(cache.put(key, resp.clone()));
  return resp;
}
