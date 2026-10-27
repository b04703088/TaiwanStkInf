/* 共用導覽列：每頁 <header> 裡放 <nav class="gnav"></nav>，緊接著同步載入本檔。
   新增頁面只要在 GROUPS 加一行；子頁（例如 watch、cb-calendar）用 also 歸到主頁簽。 */
(function () {
  /* 淺色模式：存在這台裝置；預設深色 */
  var theme = "dark";
  try { theme = localStorage.getItem("tide.theme") || "dark"; } catch (e) {}
  var setTheme = function (t) {
    theme = t;
    document.documentElement.setAttribute("data-theme", t);
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) m.content = t === "light" ? "#F6F7F9" : "#0E1620";
  };
  setTheme(theme);

  var GROUPS = [
    ["市場總覽", [
      ["ranking.html", "成交排行", "含族群資金流向", ["flow"]],
      ["industry.html", "產業分類"],
      ["screen.html", "選股", "技術・財報・籌碼條件", null, "技術面掃描、營收財報、籌碼條件混搭篩選；除權息與填息紀錄"],
      ["chips.html#dt", "當沖比率"],
    ]],
    ["籌碼動向", [
      ["broker.html", "分點籌碼", "前15大・重點・地方", ["watch", "local"], "全市場前 15 大分點、重點分點、地方主力"],
      ["chips.html", "法人籌碼", "法人・借券・集保", null, "三大法人買賣超、借券賣出、集保千張大戶"],
      ["futures.html", "期權籌碼", "台指期・選擇權", null, "外資台指期與選擇權未平倉、P/C Ratio、大額交易人"],
      ["margin.html", "融資融券"],
      ["insider.html", "內部人"],
    ]],
    ["公司事件", [
      ["news.html", "重大訊息"],
      ["alert.html", "處置注意"],
      ["treasury.html", "庫藏股"],
      ["cb.html", "CB詢圈", "含行事曆", [/^cb-/]],
    ]],
    ["個股研究", [
      ["kline.html", "K線"],
      ["fin.html", "財報"],
      ["analyst.html", "外資報告"],
      ["index.html#quant", "量化策略"],
    ]],
    ["ETF", [
      ["etf.html", "ETF持股"],
      ["etf.html#aum", "ETF規模", "折溢價・受益人數", null, "全體 ETF 規模排行、資金流入、5 日均折溢價、受益人數"],
      ["calendar.html", "指數行事曆"],
    ]],
  ];

  /* 各頁資料來源（附在頁尾） */
  var SRC = {
    index: "證交所、櫃買中心、富邦證券分點、臺灣指數公司、公開資訊觀測站",
    ranking: "證交所、櫃買中心每日收盤行情", flow: "證交所、櫃買中心每日收盤行情", industry: "證交所、櫃買中心產業分類與產業價值鏈平台",
    screen: "證交所、櫃買中心行情與法人資料；公開資訊觀測站財報", chips: "證交所、櫃買中心三大法人／借券／當沖；集保結算所股權分散表",
    futures: "臺灣期貨交易所", broker: "富邦證券券商分點進出", watch: "富邦證券券商分點進出", local: "富邦證券券商分點進出",
    margin: "證交所、櫃買中心融資融券", insider: "公開資訊觀測站內部人申報", news: "公開資訊觀測站重大訊息與行事曆",
    alert: "證交所、櫃買中心處置及注意股公告", treasury: "公開資訊觀測站庫藏股；富邦證券分點", cb: "公開資訊觀測站、金管會、證交所、櫃買中心",
    kline: "證交所、櫃買中心每日收盤行情（還原權息自算）", fin: "公開資訊觀測站月營收與季報", analyst: "鉅亨網（FactSet 共識、外資報告）",
    etf: "各投信官網每日持股、證交所 ETF 淨值揭露、集保結算所", calendar: "臺灣指數公司、MSCI、富時", health: "本站各項資料抓取紀錄",
  };

  var CSS = `
  .nav-row{gap:0 28px;}
  .brand{text-decoration:none;}
  .gnav{flex:1; display:flex; align-items:center; font-size:14px; white-space:nowrap;}
  .gnav a{text-decoration:none;}
  .gnav .gs{display:flex; align-items:center; gap:6px;}
  .gnav .gl, .gnav .home{display:flex; align-items:center; gap:5px; padding:8px 10px; background:none; border:0; font:inherit; color:var(--text-muted); cursor:pointer; transition:color .15s ease;}
  .gnav .gl::after{content:""; width:5px; height:5px; border-right:1.5px solid currentColor; border-bottom:1.5px solid currentColor; transform:rotate(45deg); margin:-3px 0 0 3px; opacity:.7;}
  .gnav .gl:hover, .gnav .home:hover, .gnav .g:hover .gl{color:var(--brass);}
  .gnav .cur > .gl, .gnav .home[aria-current]{color:var(--brass);}
  .gnav .g{position:relative;}
  .gnav .gm{display:none; position:absolute; left:0; top:100%; min-width:210px; padding:8px 0; background:var(--panel-2, #182531); border:1px solid var(--line-strong); border-radius:var(--radius-m, 6px); box-shadow:0 12px 32px rgba(0,0,0,.45); z-index:50;}
  .gnav .g:hover .gm, .gnav .g.open .gm{display:block;}
  .gnav .g::before{content:""; position:absolute; left:0; right:0; top:100%; height:6px;}
  .gnav .gm a{display:block; padding:8px 16px; color:var(--text);}
  .gnav .gm a:hover{background:rgba(198,161,91,.1); color:var(--brass);}
  .gnav .gm a[aria-current]{color:var(--brass);}
  .gnav .gm small{display:block; font-size:11.5px; color:var(--text-faint); margin-top:2px;}
  .gnav .side{margin-left:auto; font-size:12.5px; color:var(--text-faint);}
  .gnav .side:hover, .gnav .side[aria-current]{color:var(--brass);}
  .gnav-btn{display:none;}
  html[data-theme="light"]{
    --ink:#F6F7F9; --panel:#FFFFFF; --panel-2:#EDF0F3;
    --line:rgba(14,22,32,.09); --line-strong:rgba(14,22,32,.17);
    --text:#16202B; --text-muted:#4E5B68; --text-faint:#7A8794;
    --brass:#946C25; --brass-dim:#C4A469; --rise:#D0362C; --fall:#16884E;
    color-scheme:light;
  }
  html[data-theme="light"] header.site{background:rgba(246,247,249,.92);}
  html[data-theme="light"] .gnav .gm{box-shadow:0 12px 32px rgba(14,22,32,.14);}
  html[data-theme="light"] .gs-modal{background:rgba(14,22,32,.35);}
  html[data-theme="light"] .gs-box{box-shadow:0 20px 50px rgba(14,22,32,.2);}
  html[data-theme="light"] .skel{background:linear-gradient(90deg, rgba(14,22,32,.05) 25%, rgba(14,22,32,.11) 50%, rgba(14,22,32,.05) 75%); background-size:200% 100%;}
  html[data-theme="light"] .tx-over{box-shadow:inset -16px 0 14px -14px rgba(148,108,37,.5);}
  .gtheme{order:6; display:flex; align-items:center; justify-content:center; width:34px; height:32px; margin-left:8px; background:none; border:1px solid var(--line-strong); border-radius:var(--radius-s, 3px); color:var(--text-muted); cursor:pointer;}
  .gtheme:hover{color:var(--brass); border-color:var(--brass);}
  .gnav .side{display:flex; align-items:center; gap:6px; color:var(--text-muted);}
  .hdot{width:7px; height:7px; border-radius:50%; background:var(--text-faint); flex:none;}
  .hdot.ok{background:var(--fall, #3FAE72);} .hdot.warn{background:var(--brass);} .hdot.error{background:var(--rise, #E1594F);}
  /* 個股搜尋 */
  .gsearch{order:5; display:flex; align-items:center; gap:8px; margin-left:14px; padding:6px 8px 6px 10px; min-width:150px; background:var(--panel, #141F2B); border:1px solid var(--line-strong); border-radius:var(--radius-s, 3px); color:var(--text-faint); font:inherit; font-size:13px; cursor:pointer; white-space:nowrap;}
  .gsearch:hover{border-color:var(--brass); color:var(--text-muted);}
  .gsearch svg{flex:none;}
  .gsearch kbd{margin-left:auto; font-family:'IBM Plex Mono',monospace; font-size:11px; padding:0 5px; border:1px solid var(--line-strong); border-radius:3px; color:var(--text-faint);}
  .gs-modal{position:fixed; inset:0; z-index:100; background:rgba(5,9,14,.62); backdrop-filter:blur(3px); display:flex; justify-content:center; align-items:flex-start; padding:9vh 12px 12px;}
  .gs-modal[hidden]{display:none;}
  .gs-box{width:min(600px,100%); max-height:80vh; display:flex; flex-direction:column; background:var(--panel-2, #182531); border:1px solid var(--line-strong); border-radius:var(--radius-m, 6px); box-shadow:0 20px 50px rgba(0,0,0,.5); overflow:hidden;}
  .gs-in{display:flex; align-items:center; gap:10px; padding:12px 14px; border-bottom:1px solid var(--line-strong); color:var(--text-faint);}
  .gs-in input::-webkit-search-cancel-button{display:none;}
  .gs-in input{flex:1; min-width:0; background:none; border:0; outline:none; color:var(--text); font:inherit; font-size:16px;}
  .gs-in button{background:none; border:1px solid var(--line-strong); border-radius:3px; color:var(--text-faint); font:inherit; font-size:12px; padding:2px 8px; cursor:pointer;}
  .gs-list{overflow-y:auto; padding:4px 0;}
  .gs-head{padding:10px 16px 4px; font-size:12px; color:var(--text-faint);}
  .gs-empty{padding:18px 16px; font-size:13.5px; color:var(--text-muted); line-height:1.8;}
  .gs-row{display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:center; gap:2px 10px; padding:9px 12px 9px 16px; border-left:2px solid transparent;}
  .gs-row.on{background:rgba(198,161,91,.08); border-left-color:var(--brass);}
  .gs-main{display:flex; align-items:baseline; gap:8px; text-decoration:none; color:var(--text); font-size:15px; min-width:0;}
  .gs-main b{font-family:'IBM Plex Mono',monospace; font-weight:500; font-size:13.5px; color:var(--brass);}
  .gs-main small{font-size:11.5px; color:var(--text-faint);}
  .gs-star{background:none; border:0; padding:4px 6px; font-size:18px; line-height:1; color:var(--text-faint); cursor:pointer;}
  .gs-star[aria-pressed="true"]{color:var(--brass);}
  .gs-links{grid-column:1/-1; display:flex; flex-wrap:wrap; gap:4px 14px; font-size:12.5px;}
  .gs-links a{color:var(--text-muted); text-decoration:none; padding:2px 0;}
  .gs-links a:hover{color:var(--brass);}
  .gs-tip{padding:8px 16px; border-top:1px solid var(--line); font-size:11.5px; color:var(--text-faint);}
  /* 表格：橫向捲動提示、數字等寬 */
  td, th{font-variant-numeric:tabular-nums;}
  .tx-auto{overflow-x:auto;}
  .tx-over{-webkit-overflow-scrolling:touch; box-shadow:inset -16px 0 14px -14px rgba(198,161,91,.55);}
  .tx-over.tx-end{box-shadow:none;}
  .tx-hint{display:none; font-size:12px; color:var(--text-faint); margin:6px 0 4px; text-align:right;}
  .tx-hint.show{display:block;}
  .tx-hint::before{content:"← "; color:var(--brass);} .tx-hint::after{content:" →"; color:var(--brass);}
  /* 載入中骨架 */
  .skel-box{display:block; padding:6px 0;}
  .skel{display:block; height:12px; margin:9px 0; border-radius:3px; background:linear-gradient(90deg, rgba(232,237,242,.05) 25%, rgba(232,237,242,.12) 50%, rgba(232,237,242,.05) 75%); background-size:200% 100%; animation:skel 1.3s ease-in-out infinite;}
  @keyframes skel{from{background-position:200% 0;} to{background-position:-200% 0;}}
  .foot-extra{margin:14px 0 0; font-size:12px; color:var(--text-faint); line-height:1.8;}
  .foot-extra a{color:var(--text-muted); text-decoration:none;} .foot-extra a:hover{color:var(--brass);}
  .foot-extra kbd{font-family:'IBM Plex Mono',monospace; font-size:11px; padding:0 4px; border:1px solid var(--line-strong); border-radius:3px;}
  @media (max-width:1180px) and (min-width:861px){ .gsearch{min-width:0;} .gsearch span, .gsearch kbd{display:none;} }
  @media (max-width:860px){
    .nav-row{flex-wrap:wrap;}
    .gnav-btn{order:2; display:flex; align-items:center; justify-content:center; width:44px; height:40px; margin-left:8px; background:none; border:1px solid var(--line-strong); border-radius:var(--radius-s, 3px); color:var(--brass); cursor:pointer;}
    .gnav-btn span, .gnav-btn span::before, .gnav-btn span::after{display:block; position:relative; width:16px; height:1.5px; background:currentColor; transition:transform .2s ease;}
    .gnav-btn span::before, .gnav-btn span::after{content:""; position:absolute; left:0;}
    .gnav-btn span::before{top:-5px;} .gnav-btn span::after{top:5px;}
    .gnav-btn[aria-expanded="true"] span{background:transparent;}
    .gnav-btn[aria-expanded="true"] span::before{transform:translateY(5px) rotate(45deg);}
    .gnav-btn[aria-expanded="true"] span::after{transform:translateY(-5px) rotate(-45deg);}
    .gnav{display:none; order:3; flex-basis:100%; flex-direction:column; align-items:stretch; font-size:15px; max-height:calc(100vh - 70px); overflow-y:auto; margin-top:8px;}
    .gnav.show{display:flex;}
    .gnav .gs{flex-direction:column; align-items:stretch; gap:0;}
    .gnav .gl, .gnav .home{width:100%; justify-content:space-between; padding:13px 2px; border-bottom:1px solid var(--line); color:var(--text);}
    .gnav .gl::after{margin:-4px 4px 0 0; transition:transform .2s ease;}
    .gnav .g.x > .gl::after{transform:rotate(-135deg); margin-top:3px;}
    .gnav .g::before{display:none;}
    .gnav .gm, .gnav .g:hover .gm, .gnav .g.open .gm{display:none; position:static; min-width:0; padding:4px 0 8px 14px; background:none; border:0; box-shadow:none;}
    .gnav .g.x .gm{display:block;}
    .gnav .gm a{padding:12px 0; font-size:15px;}
    .gnav .gm small{display:inline; margin:0 0 0 8px;}
    .gsearch{order:1; margin-left:auto; min-width:0; height:40px; padding:0 12px; color:var(--brass);}
    .gsearch span, .gsearch kbd{display:none;}
    .gtheme{order:1; width:40px; height:40px; margin-left:8px;}
    .tx-stick table tr > :first-child, .tx-stick2 table tr > :nth-child(2){position:sticky; left:0; z-index:1; background:var(--tx-bg, var(--ink));}
    .tx-stick table tr > :first-child, .tx-stick2 table tr > :nth-child(2){box-shadow:6px 0 8px -6px rgba(0,0,0,.6);}
    .tx-stick2 table tr > :first-child{position:sticky; left:0; z-index:1; background:var(--tx-bg, var(--ink));}
    .tx-stick2 table tr > :nth-child(2){left:var(--tx-l1, 40px);}
    .gs-modal{padding-top:8px;}
    .gs-box{max-height:calc(100vh - 16px);}
    .gs-links{gap:2px 16px;} .gs-links a{padding:6px 0;}
    .gnav .gm a:hover{background:none;}
    .gnav .side{margin:12px 0 4px; padding:10px 2px; font-size:14px;}
  }`;

  var path = location.pathname.split("/").pop().replace(/\.html$/, "") || "index";
  var hit = function (href, also) {
    var p = href.split("#")[0].replace(/\.html$/, "");
    if (href.indexOf("#") < 0 && p === path) return true;
    return (also || []).some(function (a) { return a instanceof RegExp ? a.test(path) : a === path; });
  };
  var cur = function (on) { return on ? ' aria-current="page"' : ""; };

  var mobileNow = window.matchMedia("(max-width:860px)").matches;
  var html = '<a class="home" href="index.html"' + cur(path === "index") + ">首頁</a>";
  GROUPS.forEach(function (g) {
    var on = false, items = g[1].map(function (it) {
      var h = hit(it[0], it[3]);
      on = on || h;
      return '<a href="' + it[0] + '"' + cur(h) + (it[4] ? ' title="' + it[4] + '"' : "") + ">" + it[1] + (it[2] ? "<small>" + it[2] + "</small>" : "") + "</a>";
    }).join("");
    html += '<div class="g' + (on ? " cur x" : "") + '"><button type="button" class="gl" aria-expanded="' + (on && mobileNow) + '">' + g[0] +
      '</button><div class="gm">' + items + "</div></div>";
  });

  var style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);

  var nav = document.querySelector("nav.gnav");
  if (!nav) return;
  nav.setAttribute("aria-label", "主選單");
  nav.innerHTML = '<div class="gs">' + html + '</div><a class="side" href="health.html" title="每天的資料是否都有正確抓到"' + cur(path === "health") + '><i class="hdot"></i>資料健檢</a>';

  var btn = document.createElement("button");
  btn.type = "button";
  btn.className = "gnav-btn";
  btn.setAttribute("aria-label", "選單");
  btn.setAttribute("aria-expanded", "false");
  btn.innerHTML = "<span></span>";
  nav.parentNode.insertBefore(btn, nav);
  btn.addEventListener("click", function () {
    var open = nav.classList.toggle("show");
    btn.setAttribute("aria-expanded", open);
  });

  var mobile = window.matchMedia("(max-width:860px)");
  var closeAll = function (except) {
    nav.querySelectorAll(".g.open").forEach(function (g) {
      if (g !== except) { g.classList.remove("open"); g.firstChild.setAttribute("aria-expanded", "false"); }
    });
  };
  nav.querySelectorAll(".gl").forEach(function (b) {
    b.addEventListener("click", function () {
      var g = b.parentNode;
      if (mobile.matches) {
        b.setAttribute("aria-expanded", g.classList.toggle("x"));
      } else {
        closeAll(g);
        b.setAttribute("aria-expanded", g.classList.toggle("open"));
      }
    });
  });
  document.addEventListener("click", function (e) { if (!nav.contains(e.target)) closeAll(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeAll(); });
  /* ---------- 資料健檢燈號 ---------- */
  var loadLater = window.requestIdleCallback || function (f) { setTimeout(f, 300); };
  loadLater(function () {
    fetch("data/health.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (h) {
      var dot = nav.querySelector(".hdot");
      if (!h || !dot || !h.count) return;
      var c = h.count, k = c.error ? "error" : c.warn ? "warn" : "ok";
      dot.className = "hdot " + k;
      dot.parentNode.title = c.error ? c.error + " 項資料異常，點開看細節" : c.warn ? c.warn + " 項需留意" : "資料全部正常（" + (h.generated || "") + "）";
    }).catch(function () {});
  });

  /* ---------- 自選股（存在這台裝置的瀏覽器） ---------- */
  var WKEY = "tide.watch";
  var Watch = window.TideWatch = {
    list: function () { try { return JSON.parse(localStorage.getItem(WKEY)) || []; } catch (e) { return []; } },
    has: function (c) { return Watch.list().indexOf(c) >= 0; },
    toggle: function (c) {
      var l = Watch.list(), i = l.indexOf(c);
      if (i >= 0) l.splice(i, 1); else l.push(c);
      try { localStorage.setItem(WKEY, JSON.stringify(l)); } catch (e) {}
      document.dispatchEvent(new CustomEvent("tide:watch", { detail: l }));
      return i < 0;
    },
  };

  /* ---------- 個股搜尋（/ 開啟） ---------- */
  var esc = function (x) { return String(x == null ? "" : x).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); };
  var ICON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="5"/><path d="M11 11l3.5 3.5"/></svg>';
  var sbtn = document.createElement("button");
  sbtn.type = "button";
  sbtn.className = "gsearch";
  sbtn.setAttribute("aria-label", "搜尋個股");
  sbtn.innerHTML = ICON + "<span>搜尋個股</span><kbd>/</kbd>";
  nav.parentNode.insertBefore(sbtn, btn);

  var SUN = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="8" cy="8" r="3"/><path d="M8 1v2M8 13v2M1 8h2M13 8h2M3 3l1.4 1.4M11.6 11.6L13 13M3 13l1.4-1.4M11.6 4.4L13 3"/></svg>';
  var MOON = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M13.5 9.5A5.5 5.5 0 1 1 6.5 2.5a4.5 4.5 0 0 0 7 7z"/></svg>';
  var tbtn = document.createElement("button");
  tbtn.type = "button";
  tbtn.className = "gtheme";
  var paintT = function () {
    tbtn.innerHTML = theme === "light" ? MOON : SUN;
    tbtn.title = theme === "light" ? "切換深色模式" : "切換淺色模式";
    tbtn.setAttribute("aria-label", tbtn.title);
  };
  paintT();
  tbtn.addEventListener("click", function () {
    setTheme(theme === "light" ? "dark" : "light");
    try { localStorage.setItem("tide.theme", theme); } catch (e) {}
    paintT();
    document.dispatchEvent(new CustomEvent("tide:theme", { detail: theme }));
  });
  nav.parentNode.insertBefore(tbtn, btn);

  var modal = document.createElement("div");
  modal.className = "gs-modal";
  modal.hidden = true;
  modal.innerHTML = '<div class="gs-box" role="dialog" aria-modal="true" aria-label="搜尋個股">' +
    '<div class="gs-in">' + ICON + '<input type="search" placeholder="代號或名稱，例如 2330、台積電" autocomplete="off" enterkeyhint="go" aria-label="股票代號或名稱"><button type="button">Esc</button></div>' +
    '<div class="gs-list"></div><div class="gs-tip">Enter 開 K 線・↑↓ 選擇・☆ 加入自選（存在這台裝置）</div></div>';
  document.body ? document.body.appendChild(modal) : document.addEventListener("DOMContentLoaded", function () { document.body.appendChild(modal); });
  var input = modal.querySelector("input"), list = modal.querySelector(".gs-list");
  var STOCKS = null, NAMES = {}, hits = [], sel = 0;
  var MKT = { TWSE: "上市", TPEx: "上櫃", TPEX: "上櫃", OTC: "上櫃" };
  var LINKS = [["K線", "kline.html#s="], ["財報", "fin.html#s="], ["分點", "broker.html?s="], ["重訊", "news.html#s="], ["內部人", "insider.html#s="], ["ETF持有", "etf.html?stock="]];

  var loadStocks = function () {
    if (STOCKS) return Promise.resolve();
    return fetch("data/kline/index.json").then(function (r) { return r.json(); }).then(function (d) {
      STOCKS = d.stocks;
      STOCKS.forEach(function (x) { NAMES[x[0]] = x; });
    }).catch(function () { STOCKS = []; });
  };
  var row = function (x, i) {
    var on = Watch.has(x[0]);
    return '<div class="gs-row' + (i === sel ? " on" : "") + '" data-i="' + i + '">' +
      '<a class="gs-main" href="kline.html#s=' + encodeURIComponent(x[0]) + '"><b>' + esc(x[0]) + "</b>" + esc(x[1]) + "<small>" + (MKT[x[2]] || esc(x[2] || "")) + "</small></a>" +
      '<button type="button" class="gs-star" data-code="' + esc(x[0]) + '" aria-pressed="' + on + '" title="' + (on ? "移出自選" : "加入自選") + '">' + (on ? "★" : "☆") + "</button>" +
      '<div class="gs-links">' + LINKS.map(function (l) { return '<a href="' + l[1] + encodeURIComponent(x[0]) + '">' + l[0] + "</a>"; }).join("") + "</div></div>";
  };
  var render = function () {
    var q = input.value.trim().toUpperCase();
    if (!STOCKS) { list.innerHTML = '<div class="gs-empty">載入股票清單…</div>'; return; }
    if (!q) {
      hits = Watch.list().map(function (c) { return NAMES[c] || [c, "", ""]; });
      list.innerHTML = hits.length ? '<div class="gs-head">我的自選 ' + hits.length + " 檔</div>" + hits.map(row).join("")
        : '<div class="gs-empty">輸入股票代號或名稱，直接跳到 K 線、財報、分點等頁面。<br>按 ☆ 可以把常看的股票加入自選，首頁會列出自選股的最新漲跌。</div>';
      return;
    }
    var exact = [], pre = [], name = [];
    STOCKS.forEach(function (x) {
      if (x[0] === q) exact.push(x);
      else if (x[0].indexOf(q) === 0) pre.push(x);
      else if (x[1].toUpperCase().indexOf(q) >= 0) name.push(x);
    });
    hits = exact.concat(pre, name).slice(0, 12);
    if (sel >= hits.length) sel = 0;
    list.innerHTML = hits.length ? hits.map(row).join("") : '<div class="gs-empty">找不到「' + esc(input.value.trim()) + "」</div>";
  };
  var go = function (href) {
    var u = new URL(href, location.href);
    var same = u.pathname.replace(/\.html$/, "") === location.pathname.replace(/\.html$/, "");
    location.href = u.href;
    if (same && u.hash) location.reload();  // 同一頁只換 hash 的頁面不一定會重新讀取
  };
  var openSearch = function () {
    modal.hidden = false;
    document.documentElement.style.overflow = "hidden";
    input.value = "";
    sel = 0;
    render();
    input.focus();
    loadStocks().then(render);
  };
  var closeSearch = function () {
    modal.hidden = true;
    document.documentElement.style.overflow = "";
  };
  sbtn.addEventListener("click", openSearch);
  modal.addEventListener("click", function (e) {
    var star = e.target.closest(".gs-star");
    if (star) { Watch.toggle(star.dataset.code); render(); return; }
    var a = e.target.closest("a");
    if (a) { e.preventDefault(); closeSearch(); go(a.getAttribute("href")); return; }
    if (e.target === modal || e.target.closest(".gs-in button")) closeSearch();
  });
  input.addEventListener("input", function () { sel = 0; render(); });
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!hits.length) return;
      sel = (sel + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % hits.length;
      render();
      var on = list.querySelector(".gs-row.on");
      if (on) on.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && hits[sel]) {
      e.preventDefault();
      closeSearch();
      go("kline.html#s=" + encodeURIComponent(hits[sel][0]));
    } else if (e.key === "Escape") {
      closeSearch();
    }
  });
  document.addEventListener("keydown", function (e) {
    var t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && modal.hidden) {
      e.preventDefault();
      openSearch();
    }
  });

  /* ---------- 頁面載入後：骨架、表格捲動提示、頁尾 ---------- */
  var onReady = function () {
    // 「載入中…」換成骨架條，資料到了頁面程式會整個換掉
    document.querySelectorAll("main td, main p, main div").forEach(function (el) {
      if (el.childElementCount || !/^載入中/.test(el.textContent.trim())) return;
      var n = el.tagName === "TD" ? 4 : 2;
      el.setAttribute("aria-label", "載入中");
      el.innerHTML = '<span class="skel-box">' + Array.apply(null, Array(n)).map(function (_, i) {
        return '<span class="skel" style="width:' + [92, 78, 86, 64][i % 4] + '%"></span>';
      }).join("") + "</span>";
    });

    var foot = document.querySelector("footer .wrap") || document.querySelector("footer");
    if (foot && !foot.querySelector(".foot-extra")) {
      var p = document.createElement("p");
      p.className = "foot-extra";
      var src = SRC[path] || SRC[path.replace(/-.*/, "")];
      p.innerHTML = (src ? "資料來源：" + src + "。" : "") + '各表標題旁標示資料日期；抓取狀況見 <a href="health.html">資料健檢 →</a>' +
        '<br>按 <kbd>/</kbd> 搜尋個股，☆ 加入自選。';
      foot.appendChild(p);
    }
    scanTables();
    var t = 0;
    new MutationObserver(function () { clearTimeout(t); t = setTimeout(scanTables, 150); })
      .observe(document.querySelector("main") || document.body, { childList: true, subtree: true });
    addEventListener("resize", function () { clearTimeout(t); t = setTimeout(scanTables, 150); });
  };

  // 表格比容器寬：包一層可橫向捲動的框，右緣加陰影，上方加「左右滑動」提示
  var scanTables = function () {
    document.querySelectorAll("main table").forEach(function (tb) {
      var w = tb.parentElement;
      if (!w || tb.offsetParent === null) return;
      if (!/auto|scroll/.test(getComputedStyle(w).overflowX)) {
        if (tb.scrollWidth <= w.clientWidth + 2) return;
        var d = document.createElement("div");
        d.className = "tx-auto";
        w.insertBefore(d, tb);
        d.appendChild(tb);
        w = d;
      }
      var over = w.scrollWidth > w.clientWidth + 2;
      var end = function () { w.classList.toggle("tx-end", w.scrollLeft + w.clientWidth >= w.scrollWidth - 2); };
      w.classList.toggle("tx-over", over);
      // 手機橫向捲動時，股票名稱那欄固定在左邊（第一欄是名次「#」就連第二欄一起固定）
      var th = tb.querySelector("tr > :first-child");
      var rankCol = th && /^#?$/.test(th.textContent.trim());
      var stick = over && th && !(th.rowSpan > 1);
      if (stick && rankCol) w.style.setProperty("--tx-l1", th.getBoundingClientRect().width + "px");
      if (stick && !w.style.getPropertyValue("--tx-bg")) {
        for (var a = w, bg = ""; a && a !== document.documentElement; a = a.parentElement) {
          bg = getComputedStyle(a).backgroundColor;
          if (bg && !/rgba\(.*,\s*0\)$|transparent/.test(bg)) break;
        }
        w.style.setProperty("--tx-bg", bg && !/transparent|, 0\)$/.test(bg) ? bg : "#0E1620");
      }
      w.classList.toggle("tx-stick", !!stick && !rankCol);
      w.classList.toggle("tx-stick2", !!stick && !!rankCol);
      end();
      var hint = w.previousElementSibling && w.previousElementSibling.classList.contains("tx-hint") ? w.previousElementSibling : null;
      if (over && !hint) {
        hint = document.createElement("div");
        hint.className = "tx-hint";
        hint.textContent = "左右滑動查看更多欄位";
        w.parentNode.insertBefore(hint, w);
      }
      if (hint) hint.classList.toggle("show", over && !w._moved);
      if (!w._tx) {
        w._tx = 1;
        w.addEventListener("scroll", function () {
          end();
          if (!w._moved && w.scrollLeft > 20) {
            w._moved = 1;
            var h = w.previousElementSibling;
            if (h && h.classList.contains("tx-hint")) h.classList.remove("show");
          }
        }, { passive: true });
      }
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", onReady); else onReady();
})();
