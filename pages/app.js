'use strict';
const $ = id => document.getElementById(id);
const data = window.STOCK_DATA;
const number = value => Number(value).toLocaleString('zh-TW', {maximumFractionDigits: 3});
const nullable = value => value == null ? '—' : number(value);
const probability = value => value == null ? '—' : `${number(value * 100)}%`;
const yesNo = value => value === true ? '是' : value === false ? '否' : '—';
const ema = (values, span) => {
  const alpha=2/(span+1), output=[];
  let previous=values[0];
  for(const value of values) { previous=alpha*value+(1-alpha)*previous; output.push(previous); }
  return output;
};
function chartIndicators(bars) {
  const k=[], d=[], closes=bars.map(b=>b.close);
  let previousK=50, previousD=50;
  for(let i=0;i<bars.length;i++) {
    if(i>=4) {
      const window=bars.slice(i-4,i+1), low=Math.min(...window.map(b=>b.low)), high=Math.max(...window.map(b=>b.high));
      if(high>low) {
        const rsv=(bars[i].close-low)/(high-low)*100;
        previousK=previousK*2/3+rsv/3; previousD=previousD*2/3+previousK/3;
      }
    }
    k.push(previousK); d.push(previousD);
  }
  const fast=ema(closes,6), slow=ema(closes,13), dif=fast.map((value,i)=>value-slow[i]);
  const signal=ema(dif,9), histogram=dif.map((value,i)=>value-signal[i]);
  return {k,d,dif,signal,histogram};
}
let selected;
let visibleBars = 0;
function zoomChart(action) {
  if (!window.Plotly || !selected) return;
  const count = data.candles[selected].length;
  const minimum = Math.min(20, count);
  visibleBars = action === 'reset' ? count : Math.max(minimum, Math.min(count,
    action === 'in' ? Math.ceil(visibleBars * 0.8) : Math.ceil(visibleBars / 0.8)));
  Plotly.relayout('chart', {'xaxis.autorange':false, 'xaxis.range':[count-visibleBars-0.5,count-0.5]});
  updateZoomButtons(count);
}
function updateZoomButtons(count) {
  $('zoom-in').disabled = visibleBars <= Math.min(20, count);
  $('zoom-out').disabled = visibleBars >= count;
  $('zoom-reset').disabled = visibleBars >= count;
}
for (const action of ['in','out','reset']) $('zoom-'+action).addEventListener('click', () => zoomChart(action));
const touchChart = window.matchMedia('(any-pointer: coarse), (max-width: 850px)');
touchChart.addEventListener('change', () => {
  const stock = data?.matches.find(s => s.code === selected);
  if (stock) show(stock);
});
window.addEventListener('chart-ready', () => { if (data && selected) show(data.matches.find(s => s.code === selected)); });
function show(stock) {
  selected = stock.code;
  for (const row of $('rows').children) row.classList.toggle('active', row.dataset.code === selected);
  $('stock-title').textContent = `${stock.code} ${stock.name}`;
  $('csv').hidden = false;
  $('csv').href = `downloads/${stock.code}_D1.csv`;
  $('metrics').replaceChildren();
  const analysis=stock.analysis || {};
  for (const [label,value] of [['觸及機率',probability(analysis.p_touch)],['守住機率',probability(analysis.p_hold)],['歷史被測試',analysis.n_events == null ? '—' : `${analysis.n_events} 次`],['趨勢',analysis.trend_label || '—'],['最近支撐',nullable(analysis.nearest_support)],['最近壓力',nullable(analysis.nearest_resistance)],['距離',analysis.nearest_distance_atr == null ? '—' : `${number(Math.abs(analysis.nearest_distance_atr))} ATR`],['關鍵位',nullable(analysis.n_zones)]]) {
    const item=document.createElement('div'), term=document.createElement('dt'), desc=document.createElement('dd');
    term.textContent=label; desc.textContent=value; item.append(term,desc); $('metrics').append(item);
  }
  if(analysis.error) { const warning=document.createElement('div'); warning.textContent=analysis.error; $('metrics').append(warning); }
  const labels={hhhl:'頭頭高底底高',ma3:'三線多排',ma4:'四線多排'};
  const ma=stock.ma || {};
  const details = data.is_intraday
    ? [['多頭依據',(stock.bullish_reasons||[]).map(r=>labels[r]).join('、')],['位於月線之上',yesNo(stock.above_ma20)],['KD(5,3,3) 黃金交叉',yesNo(stock.kd_golden_cross)],['K / D',`${number(stock.kd_k)} / ${number(stock.kd_d)}`],['MACD(6,13,9) 紅柱',yesNo(stock.macd_red_bar)],['成交量門檻','已達 2,000 張'],['回檔幅度',`${stock.pullback_pct}%`],['歷史日 K',stock.data_bars]]
    : [['多頭依據',(stock.bullish_reasons||[]).map(r=>labels[r]).join('、')],['位於月線之上',yesNo(stock.above_ma20)],['KD(5,3,3) 黃金交叉',yesNo(stock.kd_golden_cross)],['K / D',`${number(stock.kd_k)} / ${number(stock.kd_d)}`],['MACD(6,13,9) 紅柱',yesNo(stock.macd_red_bar)],['MA5',ma['5']],['MA10',ma['10']],['MA20',ma['20']],['MA60',ma['60']],['昨收',stock.previous_close],['紅 K 高點',stock.high],['紅 K 低點',stock.low],['近六日低點',stock.pullback_low],['回檔幅度',`${stock.pullback_pct}%`],['收盤位置',`${number(stock.close_position*100)}%`],['歷史日 K',stock.data_bars]];
  for (const [label, value] of details) {
    const item=document.createElement('div'), term=document.createElement('dt'), desc=document.createElement('dd');
    term.textContent=label; desc.textContent=typeof value==='number'?number(value):value;
    item.append(term,desc); $('metrics').append(item);
  }
  if (stock.structure) {
    for (const [label, points] of [['波段高點',stock.structure.highs],['波段低點',stock.structure.lows]]) {
      const item=document.createElement('div'), term=document.createElement('dt'), desc=document.createElement('dd');
      term.textContent=label; desc.textContent=points.map(p=>number(p.price)).join(' → ');
      item.append(term,desc); $('metrics').append(item);
    }
  }
  const bars=data.candles[stock.code];
  for (const action of ['in','out','reset']) $('zoom-'+action).disabled = true;
  if (!window.Plotly) { $('chart').textContent='圖表尚未載入，可先查看數值與下載 CSV。'; return; }
  if (!$('chart').classList.contains('js-plotly-plot')) $('chart').replaceChildren();
  const dates=bars.map(b=>b.date);
  const indicators=chartIndicators(bars);
  visibleBars = bars.length;
  updateZoomButtons(bars.length);
  const average=n=>bars.map((b,i)=>i<n-1?null:bars.slice(i-n+1,i+1).reduce((sum,v)=>sum+v.close,0)/n);
  Plotly.react('chart',[
    {type:'candlestick',x:dates,open:bars.map(b=>b.open),high:bars.map(b=>b.high),low:bars.map(b=>b.low),close:bars.map(b=>b.close),name:'日 K',increasing:{line:{color:'#c84750'}},decreasing:{line:{color:'#25836b'}}},
    {type:'scatter',mode:'lines',x:dates,y:average(5),name:'MA5',line:{color:'#966690',width:1}},
    {type:'scatter',mode:'lines',x:dates,y:average(10),name:'MA10',line:{color:'#647370',width:1}},
    {type:'scatter',mode:'lines',x:dates,y:average(20),name:'MA20',line:{color:'#ba851a',width:1.5}},
    {type:'scatter',mode:'lines',x:dates,y:average(60),name:'MA60',line:{color:'#537abc',width:1.5}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.k,name:'K(5,3)',yaxis:'y2',line:{color:'#c84750',width:1.4}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.d,name:'D(5,3)',yaxis:'y2',line:{color:'#537abc',width:1.4}},
    {type:'bar',x:dates,y:indicators.histogram,name:'MACD柱',yaxis:'y3',marker:{color:indicators.histogram.map(v=>v>0?'#c84750':'#25836b')}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.dif,name:'DIF(6,13)',yaxis:'y3',line:{color:'#ba851a',width:1.3}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.signal,name:'Signal(9)',yaxis:'y3',line:{color:'#537abc',width:1.3}}
  ],{margin:{t:28,l:50,r:12,b:38},paper_bgcolor:'#f5f7f7',plot_bgcolor:'#f5f7f7',font:{family:'system-ui',color:'#526363'},dragmode:false,
    xaxis:{type:'category',nticks:5,rangeslider:{visible:false},fixedrange:true,autorange:true,anchor:'y3'},
    yaxis:{domain:[0.47,1],fixedrange:true,autorange:true,gridcolor:'#dfe6e5',title:'價格'},
    yaxis2:{domain:[0.25,0.41],fixedrange:true,range:[0,100],gridcolor:'#dfe6e5',title:'KD'},
    yaxis3:{domain:[0,0.19],fixedrange:true,autorange:true,gridcolor:'#dfe6e5',title:'MACD'},
    shapes:[{type:'line',xref:'paper',x0:0,x1:1,yref:'y2',y0:20,y1:20,line:{color:'#9aa8a7',width:1,dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,yref:'y2',y0:80,y1:80,line:{color:'#9aa8a7',width:1,dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,yref:'y3',y0:0,y1:0,line:{color:'#9aa8a7',width:1}}],
    legend:{orientation:'h',y:1.08},showlegend:true,barmode:'relative'},{responsive:true,displayModeBar:false,scrollZoom:false,doubleClick:false,staticPlot:touchChart.matches});
}
function render() {
  const query=$('search').value.trim().toLowerCase(), market=$('market').value, sort=$('sort').value;
  const matches=data.matches.filter(s=>(!market||s.market===market)&&`${s.code} ${s.name}`.toLowerCase().includes(query))
    .sort((a,b)=>sort==='code'?a.code.localeCompare(b.code):((b.analysis?.[sort] ?? b[sort] ?? -Infinity) - (a.analysis?.[sort] ?? a[sort] ?? -Infinity)) || a.code.localeCompare(b.code));
  $('rows').replaceChildren(); $('empty').hidden=matches.length>0;
  for (const stock of matches) {
    const row=document.createElement('tr'); row.dataset.code=stock.code;
    const cell=document.createElement('td'), button=document.createElement('button'), sub=document.createElement('small');
    button.textContent=`${stock.code} ${stock.name}`; button.addEventListener('click',()=>show(stock));
    sub.textContent=stock.market==='listed'?'上市':'上櫃'; cell.append(button,sub); row.append(cell);
    const a=stock.analysis || {};
    if(a.error) { sub.textContent+=' · 分析失敗'; sub.title=a.error; }
    const change=data.is_intraday ? null : (a.change_pct ?? (stock.previous_close > 0 ? (stock.close/stock.previous_close-1)*100 : null));
    const values=[data.is_intraday?'—':nullable(a.current_price ?? stock.close),change == null?'—':`${change>=0?'+':''}${number(change)}%`,probability(a.p_touch),probability(a.p_hold),a.n_events==null?'—':`${a.n_events} 次`,a.trend_label || '—',yesNo(stock.kd_golden_cross),yesNo(stock.macd_red_bar),a.nearest_distance_atr==null?'—':`${number(Math.abs(a.nearest_distance_atr))} ATR`,nullable(a.nearest_support),nullable(a.nearest_resistance),nullable(a.n_zones),data.is_intraday?'≥2,000':number(stock.volume_lots),`${stock.pullback_pct}%`];
    for(const [i,value] of values.entries()) { const td=document.createElement('td'); td.textContent=value; if(i===1 && change!=null) td.className=change>=0?'price-up':'price-down'; row.append(td); }
    $('rows').append(row);
  }
  if(matches.length) show(matches.find(s=>s.code===selected)||matches[0]);
  else { selected=null; $('stock-title').textContent='沒有符合的股票'; $('csv').hidden=true; $('metrics').replaceChildren(); if(window.Plotly) Plotly.purge('chart'); $('chart').replaceChildren(); for (const action of ['in','out','reset']) $('zoom-'+action).disabled=true; }
}
if(!data) { $('status').textContent='資料載入失敗，請重新整理或稍後再試。'; document.querySelector('.download').hidden=true; }
else {
  $('date').textContent=data.date; $('count').textContent=`${data.matches.length} 檔`;
  const age=Math.floor((Date.now()-new Date(`${data.date}T00:00:00+08:00`).getTime())/86400000);
  const asOf=data.as_of?new Date(data.as_of).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'';
  $('status').textContent=data.is_intraday
    ? `盤中暫定（截至 ${asOf}）· 累積量達 2,000 張 ${data.liquid_universe} 檔 · 紅 K ${data.red_candidates} 檔 · 13:30 收盤前條件仍可能改變。`
    : `成交量達標 ${data.liquid_universe} 檔 · 紅 K ${data.red_candidates} 檔 · ${age>=4?'資料日距今 '+age+' 天，可能為休市或更新未完成，請核對更新紀錄。':'以標示的完整交易日行情為準。'}`;
  if(data.is_intraday) $('analysis-note').textContent='本頁為盤中暫定篩選結果；成交量門檻固定為累積 2,000 張。盤中資料取自證交所 MIS，公開頁不顯示即時價量原始欄位；圖表、支撐壓力與機率以最近完整收盤資料計算。13:30 收盤前結果仍可能改變。';
  $('built').textContent=`網頁產生時間 ${new Date(data.built_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}（台灣）`;
  for(const id of ['search','market','sort']) $(id).addEventListener(id==='search'?'input':'change',render);
  render();
}
