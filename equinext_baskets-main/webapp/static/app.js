// Equinext frontend — vanilla JS + Plotly, talks to the Flask API.
const $ = s => document.querySelector(s);
const fmt = (v, d = 2) => v == null ? "—" : Number(v).toLocaleString("en-IN", {maximumFractionDigits: d, minimumFractionDigits: d});
const pct = v => v == null ? "—" : (v >= 0 ? "+" : "") + fmt(v) + "%";
const cls = v => v == null ? "" : (v >= 0 ? "up" : "down");
const PLOT = {displayModeBar: false, responsive: true};
const LAYOUT = {paper_bgcolor: "transparent", plot_bgcolor: "transparent", font: {color: "#8a93a6", size: 11},
  margin: {l: 48, r: 12, t: 10, b: 30}, xaxis: {gridcolor: "#232b3a"}, yaxis: {gridcolor: "#232b3a"}, showlegend: false};

let STOCKS = [], CUR = null, RANGE = 252;

// ---------------- boot ----------------
async function boot() {
  const d = await (await fetch("/api/overview")).json();
  STOCKS = d.stocks;
  if (d.as_of) $("#asof").textContent = "Basket as of " + d.as_of;
  renderList(STOCKS);
  if (STOCKS.length) selectStock(STOCKS.find(s => s.in_basket)?.symbol || STOCKS[0].symbol);
}

function renderList(items) {
  $("#stocklist").innerHTML = items.map(s => `
    <div class="srow ${s.symbol === CUR ? "sel" : ""}" data-sym="${s.symbol}">
      <div class="l"><div class="sym">${s.symbol} ${s.in_basket ? '<span class="bdot" title="in basket"></span>' : ""}</div>
        <div class="nm">${s.name}</div></div>
      <div class="r"><div class="px">₹${fmt(s.price)}</div>
        <div class="${cls(s.change_pct)}">${pct(s.change_pct)}</div></div>
    </div>`).join("");
  document.querySelectorAll(".srow").forEach(r => r.onclick = () => selectStock(r.dataset.sym));
}

// ---------------- stock detail ----------------
async function selectStock(sym) {
  CUR = sym;
  document.querySelectorAll(".srow").forEach(r => r.classList.toggle("sel", r.dataset.sym === sym));
  $("#detail").innerHTML = '<div class="loading">Loading ' + sym + '…</div>';
  const d = await (await fetch("/api/stock/" + sym)).json();
  renderDetail(d);
}

function renderDetail(d) {
  _price = d.price;                       // set before panels build (technicals signal reads it)
  const t = d.technicals, v = d.valuation.current, vp = d.valuation.percentile;
  $("#detail").innerHTML = `
    <div class="head">
      <div><h1>${d.symbol} ${d.basket.in_basket ? '<span class="badge">In Basket · ' + fmt(d.basket.weight * 100, 1) + '%</span>' : ""}</h1>
        <div class="sec">${d.name} · ${d.sector}</div></div>
      <div class="price">₹${fmt(d.price)}</div>
      <div class="chg ${cls(d.change_pct)}">${pct(d.change_pct)}</div>
    </div>
    <div class="chips">
      ${chip("P/E", fmt(v.pe, 1))}${chip("P/B", fmt(v.pb, 1))}
      ${chip("EV/EBITDA", v.ev_ebitda == null ? "—" : fmt(v.ev_ebitda, 1))}
      ${chip("52W High", "₹" + fmt(t.high_52w, 0))}${chip("52W Low", "₹" + fmt(t.low_52w, 0))}
      ${chip("1Y Return", pct(t.ret_1y), cls(t.ret_1y))}
    </div>

    <div class="card">
      <div class="range">${[["1M",21],["6M",126],["1Y",252],["3Y",756],["Max",99999]]
        .map(([l,n]) => `<button data-n="${n}" class="${n===RANGE?"on":""}">${l}</button>`).join("")}</div>
      <div id="pxchart" class="chart" style="height:360px"></div>
    </div>

    <div class="tabbar">
      ${["Overview","Technicals","Fundamentals","Valuation"].map((t,i)=>`<button class="tab ${i===0?"active":""}" data-tab="${i}">${t}</button>`).join("")}
    </div>
    <div class="panel active" data-panel="0">${overviewPanel(d)}</div>
    <div class="panel" data-panel="1">${technicalsPanel(t)}</div>
    <div class="panel" data-panel="2"><div class="two"><div class="card"><h3>EPS (₹)</h3><div id="f_eps" style="height:220px"></div></div>
      <div class="card"><h3>Net Profit (₹ Cr)</h3><div id="f_pat" style="height:220px"></div></div>
      <div class="card"><h3>Book Value / Share (₹)</h3><div id="f_bv" style="height:220px"></div></div>
      <div class="card"><h3>Return on Equity (%)</h3><div id="f_roe" style="height:220px"></div></div></div></div>
    <div class="panel" data-panel="3">${valuationPanel(v,vp)}
      <div class="two"><div class="card"><h3>P/E history</h3><div id="v_pe" style="height:220px"></div></div>
      <div class="card"><h3>P/B history</h3><div id="v_pb" style="height:220px"></div></div>
      <div class="card"><h3>EV/EBITDA history</h3><div id="v_ev" style="height:220px"></div></div>
      <div class="card"><h3>FCF yield history (%)</h3><div id="v_fcf" style="height:220px"></div></div></div></div>`;

  drawPrice(d);
  document.querySelectorAll(".range button").forEach(b => b.onclick = () => {
    RANGE = +b.dataset.n; document.querySelectorAll(".range button").forEach(x=>x.classList.toggle("on",x===b)); drawPrice(d);
  });
  document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
    document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active")); b.classList.add("active");
    document.querySelectorAll(".panel").forEach(p=>p.classList.toggle("active", p.dataset.panel===b.dataset.tab));
    if (b.dataset.tab==="2") drawFundamentals(d.fundamentals);
    if (b.dataset.tab==="3") drawValuation(d.valuation);
  });
}

const chip = (k,v,c="") => `<div class="chip"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
const stat = (k,v,sig="") => `<div class="stat"><div class="k">${k}</div><div class="v">${v}${sig}</div></div>`;
const S = (txt,c) => `<span class="sig ${c}">${txt}</span>`;

function overviewPanel(d){
  const t=d.technicals;
  return `<div class="grid">
    ${stat("1M", pct(t.ret_1m))}${stat("3M", pct(t.ret_3m))}${stat("6M", pct(t.ret_6m))}${stat("1Y", pct(t.ret_1y))}
    ${stat("Momentum 12-1", pct(t.mom_12_1))}
    ${stat("From 52W High", pct(t.pct_from_high))}
    ${stat("Volatility (ann)", fmt(t.vol_annual,1)+"%")}
    ${stat("RSI (14)", fmt(t.rsi14,0), rsiSig(t.rsi14))}
    ${d.basket.in_basket ? stat("Basket momentum score", fmt(d.basket.score,2)) : ""}</div>`;
}
function technicalsPanel(t){
  const above = (p,m)=> m==null?"" : (CURprice()>m ? S("above","g") : S("below","r"));
  return `<div class="grid">
    ${stat("SMA 20", "₹"+fmt(t.sma20,0), above(0,t.sma20))}
    ${stat("SMA 50", "₹"+fmt(t.sma50,0), above(0,t.sma50))}
    ${stat("SMA 200", "₹"+fmt(t.sma200,0), above(0,t.sma200))}
    ${stat("RSI (14)", fmt(t.rsi14,0), rsiSig(t.rsi14))}
    ${stat("Momentum 12-1", pct(t.mom_12_1), t.mom_12_1>0?S("positive","g"):S("negative","r"))}
    ${stat("From 52W High", pct(t.pct_from_high))}
    ${stat("Volume trend", pct(t.vol_trend), t.vol_trend>0?S("rising","g"):S("falling","n"))}
    ${stat("Volatility (ann)", fmt(t.vol_annual,1)+"%")}
    ${stat("Trend", t.sma50>t.sma200 ? "Uptrend" : "Downtrend", t.sma50>t.sma200?S("50>200","g"):S("50<200","r"))}</div>`;
}
function valuationPanel(v,vp){
  const pctChip=(k,val,p)=> stat(k, val==null?"—":fmt(val, k==="FCF yield"?3:1)+(k==="FCF yield"?"":""),
    p==null?"": S(fmt(p,0)+"%ile", p>70?"r":p<30?"g":"n"));
  return `<div class="grid">
    ${pctChip("P/E", v.pe, vp.pe)}${pctChip("P/B", v.pb, vp.pb)}
    ${pctChip("EV/EBITDA", v.ev_ebitda, vp.ev_ebitda)}
    ${pctChip("FCF yield", v.fcf_yield==null?null:v.fcf_yield*100, vp.fcf_yield)}</div>
    <div class="stat" style="margin-top:10px"><div class="k">Own-history percentile — how the stock is priced vs its OWN past.
      Low = cheap vs itself (green), high = frothy (red). This is the basket's froth gate.</div></div>`;
}
const rsiSig = r => r==null?"":(r>70?S("overbought","r"):r<30?S("oversold","g"):S("neutral","n"));
let _price=0; const CURprice=()=>_price;

// ---------------- charts ----------------
function slice(arr,n){ return n>=arr.length ? arr : arr.slice(arr.length-n); }
function drawPrice(d){
  _price=d.price;
  const o=slice(d.ohlcv,RANGE);
  const x=o.map(r=>r.t);
  const cs={x, open:o.map(r=>r.o), high:o.map(r=>r.h), low:o.map(r=>r.l), close:o.map(r=>r.c),
    type:"candlestick", increasing:{line:{color:"#22c55e"}}, decreasing:{line:{color:"#ef4444"}}, name:"", yaxis:"y"};
  const smaTrace=(n,c)=>({x, y:slice(d.sma[n],RANGE), type:"scatter", mode:"lines",
    line:{color:c,width:1.2}, name:"SMA"+n, yaxis:"y", hoverinfo:"skip"});
  const volc=o.map(r=>r.c>=r.o?"rgba(34,197,94,.4)":"rgba(239,68,68,.4)");
  const vol={x, y:o.map(r=>r.v), type:"bar", marker:{color:volc}, yaxis:"y2", name:"", hoverinfo:"skip"};
  const lay={...LAYOUT, height:360, xaxis:{...LAYOUT.xaxis, rangeslider:{visible:false}, type:"date"},
    yaxis:{...LAYOUT.yaxis, domain:[0.28,1], title:""}, yaxis2:{...LAYOUT.yaxis, domain:[0,0.2]}};
  Plotly.newPlot("pxchart", [cs, smaTrace(20,"#eab308"), smaTrace(50,"#3b82f6"), smaTrace(200,"#a855f7"), vol], lay, PLOT);
}
function bar(id,x,y,color){
  Plotly.newPlot(id,[{x,y,type:"bar",marker:{color}}],{...LAYOUT,height:220,margin:{l:44,r:8,t:6,b:26}},PLOT);
}
function line(id,x,y,color){
  Plotly.newPlot(id,[{x,y,type:"scatter",mode:"lines",line:{color,width:1.6},fill:"tozeroy",fillcolor:color+"22"}],
    {...LAYOUT,height:220,margin:{l:44,r:8,t:6,b:26}},PLOT);
}
function drawFundamentals(f){
  const yr=f.map(r=>r.year);
  bar("f_eps",yr,f.map(r=>r.eps),"#3b82f6");
  bar("f_pat",yr,f.map(r=>r.pat),"#22c55e");
  bar("f_bv",yr,f.map(r=>r.book_value),"#a855f7");
  bar("f_roe",yr,f.map(r=>r.roe),"#eab308");
}
function drawValuation(v){
  line("v_pe",v.dates,v.pe,"#3b82f6");
  line("v_pb",v.dates,v.pb,"#22c55e");
  line("v_ev",v.dates,v.ev_ebitda,"#a855f7");
  line("v_fcf",v.dates,v.fcf_yield.map(x=>x==null?null:x*100),"#eab308");
}

// ---------------- basket view ----------------
async function renderBasket(){
  $("#basket").innerHTML='<div class="loading">Loading basket…</div>';
  const d=await (await fetch("/api/basket")).json();
  const m=d.metrics;
  $("#basket").innerHTML=`
    <h1 style="margin:0 0 4px">Valuation-Momentum Basket</h1>
    <div class="sec" style="color:var(--muted);margin-bottom:16px">15 holdings · quarterly rebalance · as of ${d.as_of}</div>
    <div class="metrics">
      <div class="metric"><div class="k">CAGR (basket)</div><div class="v up">${fmt(m.cagr,1)}%</div><div class="sub">Nifty50 ${fmt(m.cagr_nifty,1)}%</div></div>
      <div class="metric"><div class="k">Sharpe</div><div class="v">${fmt(m.sharpe,2)}</div></div>
      <div class="metric"><div class="k">Max Drawdown</div><div class="v down">${fmt(m.max_dd,1)}%</div></div>
      <div class="metric"><div class="k">₹100 → </div><div class="v">₹${fmt(m.final,0)}</div><div class="sub">Nifty ₹${fmt(m.final_nifty,0)} · ${fmt(m.years,1)}y</div></div>
    </div>
    <div class="card"><h3>Growth of ₹100 — basket vs NIFTY50</h3><div id="curve" style="height:340px"></div></div>
    <div class="card"><h3>Holdings</h3>
      <table><thead><tr><th>Stock</th><th>Weight</th><th>Momentum score</th><th>Price</th><th>Day</th></tr></thead>
      <tbody>${d.holdings.map(h=>`<tr data-sym="${h.symbol}">
        <td><b>${h.symbol}</b> <span style="color:var(--muted)">${h.name||""}</span></td>
        <td><span class="wbar"><span style="width:${Math.min(100,h.weight*6)}%"></span></span> ${fmt(h.weight,1)}%</td>
        <td>${fmt(h.score,2)}</td><td>₹${fmt(h.price)}</td>
        <td class="${cls(h.change_pct)}">${pct(h.change_pct)}</td></tr>`).join("")}</tbody></table></div>`;
  if(d.curve.dates){
    Plotly.newPlot("curve",[
      {x:d.curve.dates,y:d.curve.basket,type:"scatter",mode:"lines",line:{color:"#22c55e",width:2},name:"Basket"},
      {x:d.curve.dates,y:d.curve.nifty,type:"scatter",mode:"lines",line:{color:"#8a93a6",width:1.5},name:"NIFTY50"}],
      {...LAYOUT,height:340,showlegend:true,legend:{orientation:"h",y:1.08,font:{color:"#e6e9ef"}}},PLOT);
  }
  document.querySelectorAll("#basket tbody tr").forEach(r=>r.onclick=()=>{switchView("stocks");selectStock(r.dataset.sym);});
}

// ---------------- nav / search ----------------
function switchView(v){
  document.querySelectorAll(".navtab").forEach(b=>b.classList.toggle("active",b.dataset.view===v));
  $("#stocks-view").hidden = v!=="stocks";
  $("#basket-view").hidden = v!=="basket";
  if(v==="basket") renderBasket();
}
document.querySelectorAll(".navtab").forEach(b=>b.onclick=()=>switchView(b.dataset.view));
$("#search").oninput = e => {
  const q=e.target.value.toLowerCase();
  renderList(STOCKS.filter(s=>s.symbol.toLowerCase().includes(q)||(s.name||"").toLowerCase().includes(q)));
};
boot();
