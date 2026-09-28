'use strict';
const $ = id => document.getElementById(id);
const data = window.STOCK_DATA;
const number = value => Number(value).toLocaleString('zh-TW', {maximumFractionDigits: 3});
let selected;
window.addEventListener('chart-ready', () => { if (data && selected) show(data.matches.find(s => s.code === selected)); });
function show(stock) {
  selected = stock.code;
  for (const row of $('rows').children) row.classList.toggle('active', row.dataset.code === selected);
  $('stock-title').textContent = `${stock.code} ${stock.name}`;
  $('csv').hidden = false;
  $('csv').href = `downloads/${stock.code}_D1.csv`;
  $('metrics').replaceChildren();
  for (const [label, value] of [['MA20',stock.ma['20']],['MA60',stock.ma['60']],['昨收',stock.previous_close],['紅 K 高點',stock.high],['紅 K 低點',stock.low],['近六日低點',stock.pullback_low],['回檔幅度',`${stock.pullback_pct}%`],['收盤位置',`${number(stock.close_position*100)}%`],['歷史日 K',stock.data_bars]]) {
    const item=document.createElement('div'), term=document.createElement('dt'), desc=document.createElement('dd');
    term.textContent=label; desc.textContent=typeof value==='number'?number(value):value;
    item.append(term,desc); $('metrics').append(item);
  }
  const bars=data.candles[stock.code];
  if (!window.Plotly) { $('chart').textContent='圖表尚未載入，可先查看數值與下載 CSV。'; return; }
  const dates=bars.map(b=>b.date);
  const average=n=>bars.map((b,i)=>i<n-1?null:bars.slice(i-n+1,i+1).reduce((sum,v)=>sum+v.close,0)/n);
  Plotly.react('chart',[
    {type:'candlestick',x:dates,open:bars.map(b=>b.open),high:bars.map(b=>b.high),low:bars.map(b=>b.low),close:bars.map(b=>b.close),name:'日 K',increasing:{line:{color:'#c84750'}},decreasing:{line:{color:'#25836b'}}},
    {type:'scatter',mode:'lines',x:dates,y:average(20),name:'MA20',line:{color:'#ba851a',width:1.5}},
    {type:'scatter',mode:'lines',x:dates,y:average(60),name:'MA60',line:{color:'#537abc',width:1.5}}
  ],{margin:{t:15,l:44,r:12,b:38},paper_bgcolor:'#f5f7f7',plot_bgcolor:'#f5f7f7',font:{family:'system-ui',color:'#526363'},xaxis:{type:'category',nticks:5,rangeslider:{visible:false}},yaxis:{fixedrange:true,gridcolor:'#dfe6e5'},legend:{orientation:'h',y:1.12},showlegend:true},{responsive:true,displayModeBar:false});
}
function render() {
  const query=$('search').value.trim().toLowerCase(), market=$('market').value, sort=$('sort').value;
  const matches=data.matches.filter(s=>(!market||s.market===market)&&`${s.code} ${s.name}`.toLowerCase().includes(query))
    .sort((a,b)=>sort==='code'?a.code.localeCompare(b.code):b[sort]-a[sort]);
  $('rows').replaceChildren(); $('empty').hidden=matches.length>0;
  for (const stock of matches) {
    const row=document.createElement('tr'); row.dataset.code=stock.code;
    const cell=document.createElement('td'), button=document.createElement('button'), sub=document.createElement('small');
    button.textContent=`${stock.code} ${stock.name}`; button.addEventListener('click',()=>show(stock));
    sub.textContent=stock.market==='listed'?'上市':'上櫃'; cell.append(button,sub); row.append(cell);
    for(const value of [number(stock.close),number(stock.volume_lots),`${stock.pullback_pct}%`]) { const td=document.createElement('td'); td.textContent=value; row.append(td); }
    $('rows').append(row);
  }
  if(matches.length) show(matches.find(s=>s.code===selected)||matches[0]);
  else { selected=null; $('stock-title').textContent='沒有符合的股票'; $('csv').hidden=true; $('metrics').replaceChildren(); if(window.Plotly) Plotly.purge('chart'); $('chart').replaceChildren(); }
}
if(!data) { $('status').textContent='資料載入失敗，請重新整理或稍後再試。'; document.querySelector('.download').hidden=true; }
else {
  $('date').textContent=data.date; $('count').textContent=`${data.matches.length} 檔`;
  const age=Math.floor((Date.now()-new Date(`${data.date}T00:00:00+08:00`).getTime())/86400000);
  $('status').textContent=`成交量達標 ${data.liquid_universe} 檔 · 紅 K ${data.red_candidates} 檔 · ${age>=4?'資料日距今 '+age+' 天，可能為休市或更新未完成，請核對更新紀錄。':'以標示的完整交易日行情為準。'}`;
  $('built').textContent=`網頁產生時間 ${new Date(data.built_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}（台灣）`;
  for(const id of ['search','market','sort']) $(id).addEventListener(id==='search'?'input':'change',render);
  render();
}
