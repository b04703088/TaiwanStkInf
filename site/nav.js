/* 共用導覽列：每頁 <header> 裡放 <nav class="gnav"></nav>，緊接著同步載入本檔。
   新增頁面只要在 GROUPS 加一行；子頁（例如 watch、cb-calendar）用 also 歸到主頁簽。 */
(function () {
  var GROUPS = [
    ["市場總覽", [
      ["ranking.html", "成交排行", "個股／族群資金流向", ["flow"]],
      ["industry.html", "產業分類"],
    ]],
    ["籌碼動向", [
      ["broker.html", "分點籌碼", "前15大／重點／地方主力", ["watch", "local"]],
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
      ["calendar.html", "指數行事曆"],
    ]],
  ];

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
  @media (max-width:860px){
    .nav-row{flex-wrap:wrap;}
    .gnav-btn{display:flex; align-items:center; justify-content:center; width:38px; height:34px; margin-left:auto; background:none; border:1px solid var(--line-strong); border-radius:var(--radius-s, 3px); color:var(--brass); cursor:pointer;}
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
    .gnav .gm a{padding:9px 0; font-size:14.5px;}
    .gnav .gm a:hover{background:none;}
    .gnav .side{margin:12px 0 4px; padding:4px 2px; font-size:13px;}
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
      return '<a href="' + it[0] + '"' + cur(h) + ">" + it[1] + (it[2] ? "<small>" + it[2] + "</small>" : "") + "</a>";
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
  nav.innerHTML = '<div class="gs">' + html + '</div><a class="side" href="health.html"' + cur(path === "health") + ">資料健檢</a>";

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
})();
