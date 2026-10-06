// 個股細產業標籤（成交排行、分點籌碼共用）
// 用法：import { loadIndustry, indTag, primaryNode, nodeMembers, nodePath } from "./industry-tags.js";
//   await loadIndustry();           載入 data/industry/industry.json（失敗時標籤不顯示）
//   indTag(code, {filter: true})    回傳 <span> 標籤 HTML；filter=true 時帶 data-node，頁面可拿來篩選
let D = null, members = null, primary = {};

// 官方產業別 → 優先採用的價值鏈產業（挑標籤時用；沒有對應就取第一個）
const PREFER = {
  "水泥工業": ["水泥"], "食品工業": ["食品", "食品生技"], "塑膠工業": ["石化及塑橡膠"], "紡織纖維": ["紡織"],
  "電機機械": ["電機機械", "自動化"], "電器電纜": ["電機機械"], "玻璃陶瓷": ["建材營造"], "造紙工業": ["造紙"],
  "鋼鐵工業": ["鋼鐵"], "橡膠工業": ["石化及塑橡膠"], "汽車工業": ["汽車", "電動車輛產業"], "建材營造": ["建材營造"],
  "航運業": ["交通運輸及航運"], "觀光餐旅": ["休閒娛樂"], "金融保險": ["金融"], "貿易百貨": ["貿易百貨", "電子商務"],
  "化學工業": ["石化及塑橡膠"], "生技醫療": ["製藥", "醫療器材", "食品生技", "再生醫療"], "油電燃氣": ["油電燃氣"],
  "半導體": ["半導體"], "電腦及週邊設備": ["電腦及週邊設備"], "光電": ["平面顯示器", "LED照明產業", "太陽能產業", "觸控面板"],
  "通信網路": ["通信網路"], "電子零組件": ["被動元件", "連接器", "印刷電路板", "能源元件"], "電子通路": ["半導體", "電腦及週邊設備"],
  "資訊服務": ["軟體服務", "雲端運算"], "其他電子": ["電腦及週邊設備", "自動化"], "文化創意": ["文化創意業"],
  "綠能環保": ["太陽能產業", "風力發電", "能源元件"], "數位雲端": ["雲端運算", "軟體服務", "電子商務"],
  "運動休閒": ["運動科技", "休閒娛樂"], "居家生活": ["貿易百貨"],
};

export async function loadIndustry() {
  if (D) return D;
  try {
    const r = await fetch("data/industry/industry.json", { cache: "no-cache" });
    D = await r.json();
  } catch (e) {
    D = { nodes: [], stocks: {}, industries: [] };
  }
  members = {};
  for (const [c, s] of Object.entries(D.stocks)) for (const i of s[2]) (members[i] ||= new Set()).add(c);
  for (const [c, s] of Object.entries(D.stocks)) {
    if (!s[2].length) continue;
    const pref = PREFER[s[1]] || [];
    const cand = s[2].filter(i => pref.includes(D.nodes[i][0]));
    primary[c] = (cand.length ? cand : s[2])[0];
  }
  if (!document.getElementById("ind-tag-style")) {
    const st = document.createElement("style");
    st.id = "ind-tag-style";
    st.textContent = `.ind-tag{display:inline-block; max-width:9em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle;
      margin-left:6px; padding:0 6px; font-size:11px; line-height:18px; border-radius:3px; color:var(--text-muted);
      border:1px solid var(--line-strong); text-decoration:none; cursor:pointer;}
      .ind-tag:hover{color:var(--brass); border-color:var(--brass);}
      .ind-tag .n{color:var(--text-faint); margin-left:3px;}
      @media (max-width:860px){ .ind-tag{max-width:7em; margin-left:0; margin-top:2px;} }`;
    document.head.appendChild(st);
  }
  return D;
}

export const primaryNode = code => primary[code];
export const nodeMembers = i => members?.[i] || new Set();
export function nodePath(i) {
  const n = D?.nodes[i];
  return n ? [n[0], n[1], n[2], n[3]].filter(Boolean).join(" › ") : "";
}
export const nodeLabel = i => { const n = D?.nodes[i]; return n ? (n[3] || n[2]) : ""; };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function indTag(code, { filter = false } = {}) {
  if (!D) return "";
  const s = D.stocks[code];
  if (!s) return "";
  const i = primary[code];
  if (i == null) {
    return s[1] ? `<a class="ind-tag" href="industry.html#s=${esc(code)}" title="官方產業別：${esc(s[1])}">${esc(s[1])}</a>` : "";
  }
  const title = `${s[2].map(nodePath).join("\n")}${filter ? "\n（點一下只看同細類）" : "\n（點一下看產業分類）"}`;
  const more = s[2].length > 1 ? `<span class="n">+${s[2].length - 1}</span>` : "";
  return filter
    ? `<span class="ind-tag" data-node="${i}" title="${esc(title)}">${esc(nodeLabel(i))}${more}</span>`
    : `<a class="ind-tag" href="industry.html#s=${esc(code)}" title="${esc(title)}">${esc(nodeLabel(i))}${more}</a>`;
}
