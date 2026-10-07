'use strict';
const $ = id => document.getElementById(id);
const data = window.STOCK_DATA;
const number = value => Number(value).toLocaleString('zh-TW', {maximumFractionDigits: 3});
const nullable = value => value == null ? '—' : number(value);
const probability = value => value == null ? '—' : `${number(value * 100)}%`;
const yesNo = value => value === true ? '是' : value === false ? '否' : '—';
const volumeThreshold = () => data?.min_volume_lots ?? 1500;
const volumeThresholdText = () => number(volumeThreshold());
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
function trendStructure(bars) {
  const windowSize=bars.length>180?5:4, highs=[], lows=[];
  for(let i=windowSize;i<bars.length-windowSize;i++) {
    const window=bars.slice(i-windowSize,i+windowSize+1), bar=bars[i];
    if(bar.high===Math.max(...window.map(item=>item.high))) highs.push({i,value:bar.high,date:bar.date,type:'high'});
    if(bar.low===Math.min(...window.map(item=>item.low))) lows.push({i,value:bar.low,date:bar.date,type:'low'});
  }
  const pivots=[];
  for(const pivot of [...highs,...lows].sort((a,b)=>a.i-b.i)) {
    const last=pivots.at(-1);
    if(!last||last.type!==pivot.type) pivots.push(pivot);
    else if((pivot.type==='high'&&pivot.value>last.value)||(pivot.type==='low'&&pivot.value<last.value)) pivots[pivots.length-1]=pivot;
  }
  return {highs:pivots.filter(p=>p.type==='high'),lows:pivots.filter(p=>p.type==='low'),pivots};
}
let selected;
let activeView = 'confirmed';
let visibleBars = 0;
let showPivots = true;
let showTurns = true;
const currentStocks = () => activeView === 'waiting' ? (data.waiting_matches || []) : data.matches;
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
let chartExpanded = false;
function setChartExpanded(expanded) {
  chartExpanded = expanded;
  $('stock-detail').classList.toggle('chart-expanded', expanded);
  document.body.classList.toggle('chart-open', expanded);
  const button = $('chart-expand');
  button.textContent = expanded ? '×' : '⛶';
  button.title = expanded ? '縮回圖表' : '展開圖表';
  button.setAttribute('aria-label', button.title);
  button.setAttribute('aria-pressed', String(expanded));
  if (window.Plotly?.Plots?.resize) Plotly.Plots.resize($('chart'));
}
$('chart-expand').addEventListener('click', () => setChartExpanded(!chartExpanded));
$('toggle-pivots').addEventListener('change', event => {
  showPivots=event.target.checked;
  const stock=currentStocks().find(item=>item.code===selected);
  if(stock) show(stock);
});
$('toggle-turns').addEventListener('change', event => {
  showTurns=event.target.checked;
  const stock=currentStocks().find(item=>item.code===selected);
  if(stock) show(stock);
});
window.addEventListener('keydown', event => {
  if (event.key === 'Escape' && chartExpanded) setChartExpanded(false);
});
const touchChart = window.matchMedia('(any-pointer: coarse), (max-width: 850px)');
touchChart.addEventListener('change', () => {
  const stock = currentStocks().find(s => s.code === selected);
  if (stock) show(stock);
});
window.addEventListener('chart-ready', () => {
  if (data && selected) {
    const stock = currentStocks().find(s => s.code === selected);
    if (stock) show(stock);
  }
});
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
  const temporary=stock.intraday_bar || {};
  const highLabel=stock.red_k_confirmed?'紅 K 高點':'今日 K 高點';
  const lowLabel=stock.red_k_confirmed?'紅 K 低點':'今日 K 低點';
  const details = data.is_intraday
    ? [['訊號狀態',stock.red_k_confirmed?'止跌紅 K':'等待紅 K'],['暫時 K 截至',temporary.as_of?new Date(temporary.as_of).toLocaleTimeString('zh-TW',{timeZone:'Asia/Taipei'}):'—'],['暫時開／高／低／現',temporary.open==null?'—':`${number(temporary.open)}／${number(temporary.high)}／${number(temporary.low)}／${number(temporary.close)}`],['多頭依據',(stock.bullish_reasons||[]).map(r=>labels[r]).join('、')],['位於月線之上',yesNo(stock.above_ma20)],['紅 K 量大於前 K',yesNo(stock.volume_increased)],['回檔下跌量縮',yesNo(stock.pullback_volume_contracted)],['上漲階段',stock.rising_stage || '—'],['階段依據',stock.rising_stage_reason || '—'],['KD(5,3,3) 黃金交叉',yesNo(stock.kd_golden_cross)],['K / D',`${number(stock.kd_k)} / ${number(stock.kd_d)}`],['MACD(6,13,9) 紅柱',yesNo(stock.macd_red_bar)],['成交量門檻',`已達 ${volumeThresholdText()} 張`],['回檔幅度',`${stock.pullback_pct}%`],['歷史日 K',stock.data_bars]]
    : [['訊號狀態',stock.red_k_confirmed?'止跌紅 K':'等待紅 K'],['多頭依據',(stock.bullish_reasons||[]).map(r=>labels[r]).join('、')],['位於月線之上',yesNo(stock.above_ma20)],['紅 K 量大於前 K',yesNo(stock.volume_increased)],['回檔下跌量縮',yesNo(stock.pullback_volume_contracted)],['上漲階段',stock.rising_stage || '—'],['階段依據',stock.rising_stage_reason || '—'],['KD(5,3,3) 黃金交叉',yesNo(stock.kd_golden_cross)],['K / D',`${number(stock.kd_k)} / ${number(stock.kd_d)}`],['MACD(6,13,9) 紅柱',yesNo(stock.macd_red_bar)],['MA5',ma['5']],['MA10',ma['10']],['MA20',ma['20']],['MA60',ma['60']],['昨收',stock.previous_close],[highLabel,stock.high],[lowLabel,stock.low],['近六日低點',stock.pullback_low],['回檔幅度',`${stock.pullback_pct}%`],['收盤位置',`${number(stock.close_position*100)}%`],['歷史日 K',stock.data_bars]];
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
  const completedBars=bars.filter(b=>!b.is_partial), partialBars=bars.filter(b=>b.is_partial);
  const candleTraces=[{type:'candlestick',x:completedBars.map(b=>b.date),open:completedBars.map(b=>b.open),high:completedBars.map(b=>b.high),low:completedBars.map(b=>b.low),close:completedBars.map(b=>b.close),name:'完整日 K',increasing:{line:{color:'#c84750'}},decreasing:{line:{color:'#25836b'}}}];
  if(partialBars.length) candleTraces.push({type:'candlestick',x:partialBars.map(b=>b.date),open:partialBars.map(b=>b.open),high:partialBars.map(b=>b.high),low:partialBars.map(b=>b.low),close:partialBars.map(b=>b.close),name:'盤中暫時 K',increasing:{line:{color:'#e06b32',width:3}},decreasing:{line:{color:'#3b8fbc',width:3}}});
  const indicators=chartIndicators(bars);
  const compact = touchChart.matches;
  const structure=trendStructure(bars);
  const structureTraces=[];
  if(showTurns) structureTraces.push({type:'scatter',mode:'lines',x:structure.pivots.map(p=>p.date),y:structure.pivots.map(p=>p.value),name:'轉折',line:{color:'#687575',width:1.5},hovertemplate:'%{x}<br>轉折 %{y}<extra></extra>'});
  if(showPivots) structureTraces.push(
    {type:'scatter',mode:'markers+text',x:structure.highs.map(p=>p.date),y:structure.highs.map(p=>p.value),text:structure.highs.map(()=>'頭'),textposition:'top center',name:'頭',marker:{color:'#c84750',size:7,symbol:'triangle-down'},textfont:{color:'#a7333d',size:compact?9:11},cliponaxis:false,hovertemplate:'%{x}<br>頭 %{y}<extra></extra>'},
    {type:'scatter',mode:'markers+text',x:structure.lows.map(p=>p.date),y:structure.lows.map(p=>p.value),text:structure.lows.map(()=>'底'),textposition:'bottom center',name:'底',marker:{color:'#25836b',size:7,symbol:'triangle-up'},textfont:{color:'#196b57',size:compact?9:11},cliponaxis:false,hovertemplate:'%{x}<br>底 %{y}<extra></extra>'}
  );
  visibleBars = bars.length;
  updateZoomButtons(bars.length);
  const average=n=>bars.map((b,i)=>i<n-1?null:bars.slice(i-n+1,i+1).reduce((sum,v)=>sum+v.close,0)/n);
  const volumes=bars.map(b=>b.tick_volume==null?null:b.tick_volume/1000);
  const volumeAverage=n=>volumes.map((value,i)=>{
    if(value==null||i<n-1) return null;
    const window=volumes.slice(i-n+1,i+1);
    return window.some(item=>item==null)?null:window.reduce((sum,item)=>sum+item,0)/n;
  });
  Plotly.react('chart',[
    ...candleTraces,
    ...structureTraces,
    {type:'scatter',mode:'lines',x:dates,y:average(5),name:'MA5',line:{color:'#966690',width:1}},
    {type:'scatter',mode:'lines',x:dates,y:average(10),name:'MA10',line:{color:'#647370',width:1}},
    {type:'scatter',mode:'lines',x:dates,y:average(20),name:'MA20',line:{color:'#ba851a',width:1.5}},
    {type:'scatter',mode:'lines',x:dates,y:average(60),name:'MA60',line:{color:'#537abc',width:1.5}},
    {type:'bar',x:dates,y:volumes,name:'成交量',yaxis:'y2',marker:{color:bars.map(b=>b.close>=b.open?'#c84750':'#25836b')}},
    {type:'scatter',mode:'lines',x:dates,y:volumeAverage(5),name:'量 MA5',yaxis:'y2',line:{color:'#ba851a',width:1.5},connectgaps:false},
    {type:'scatter',mode:'lines',x:dates,y:volumeAverage(10),name:'量 MA10',yaxis:'y2',line:{color:'#537abc',width:1.5},connectgaps:false},
    {type:'scatter',mode:'lines',x:dates,y:indicators.k,name:'K(5,3)',yaxis:'y3',line:{color:'#c84750',width:1.4}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.d,name:'D(5,3)',yaxis:'y3',line:{color:'#537abc',width:1.4}},
    {type:'bar',x:dates,y:indicators.histogram,name:'MACD柱',yaxis:'y4',marker:{color:indicators.histogram.map(v=>v>0?'#c84750':'#25836b')}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.dif,name:'DIF(6,13)',yaxis:'y4',line:{color:'#ba851a',width:1.3}},
    {type:'scatter',mode:'lines',x:dates,y:indicators.signal,name:'Signal(9)',yaxis:'y4',line:{color:'#537abc',width:1.3}}
  ],{margin:compact?{t:44,l:46,r:8,b:34}:{t:34,l:50,r:12,b:38},paper_bgcolor:'#f5f7f7',plot_bgcolor:'#f5f7f7',font:{family:'system-ui',color:'#526363',size:compact?10:12},dragmode:false,
    xaxis:{type:'category',nticks:5,rangeslider:{visible:false},fixedrange:true,autorange:true,anchor:'y4'},
    yaxis:{domain:[0.55,1],fixedrange:true,autorange:true,gridcolor:'#dfe6e5',title:'價格'},
    yaxis2:{domain:[0.40,0.50],fixedrange:true,autorange:true,gridcolor:'#dfe6e5',title:'量(張)'},
    yaxis3:{domain:[0.20,0.34],fixedrange:true,range:[0,100],gridcolor:'#dfe6e5',title:'KD'},
    yaxis4:{domain:[0,0.14],fixedrange:true,autorange:true,gridcolor:'#dfe6e5',title:'MACD'},
    shapes:[{type:'line',xref:'paper',x0:0,x1:1,yref:'y3',y0:20,y1:20,line:{color:'#9aa8a7',width:1,dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,yref:'y3',y0:80,y1:80,line:{color:'#9aa8a7',width:1,dash:'dot'}},{type:'line',xref:'paper',x0:0,x1:1,yref:'y4',y0:0,y1:0,line:{color:'#9aa8a7',width:1}}],
    annotations:partialBars.map(b=>({xref:'x',yref:'y',x:b.date,y:b.high,text:'盤中暫時 K',showarrow:true,arrowhead:2,ax:0,ay:-24,font:{color:'#9a4b1f',size:compact?9:11}})),
    legend:{orientation:'h',y:1.08,font:{size:compact?9:11}},showlegend:true,barmode:'relative'},{responsive:true,displayModeBar:false,scrollZoom:false,doubleClick:false,staticPlot:compact});
}
function render() {
  const query=$('search').value.trim().toLowerCase(), market=$('market').value, sort=$('sort').value;
  const matches=currentStocks().filter(s=>(!market||s.market===market)&&`${s.code} ${s.name}`.toLowerCase().includes(query))
    .sort((a,b)=>sort==='code'?a.code.localeCompare(b.code):((b.analysis?.[sort] ?? b[sort] ?? -Infinity) - (a.analysis?.[sort] ?? a[sort] ?? -Infinity)) || a.code.localeCompare(b.code));
  $('count').textContent=`${matches.length} 檔`;
  $('rows').replaceChildren(); $('empty').hidden=matches.length>0;
  for (const stock of matches) {
    const row=document.createElement('tr'); row.dataset.code=stock.code;
    const cell=document.createElement('td'), button=document.createElement('button'), sub=document.createElement('small');
    button.textContent=`${stock.code} ${stock.name}`; button.addEventListener('click',()=>show(stock));
    sub.textContent=stock.market==='listed'?'上市':'上櫃'; cell.append(button,sub); row.append(cell);
    const a=stock.analysis || {};
    if(a.error) { sub.textContent+=' · 分析失敗'; sub.title=a.error; }
    const change=data.is_intraday ? null : (a.change_pct ?? (stock.previous_close > 0 ? (stock.close/stock.previous_close-1)*100 : null));
    const values=[data.is_intraday?'—':nullable(a.current_price ?? stock.close),change == null?'—':`${change>=0?'+':''}${number(change)}%`,probability(a.p_touch),probability(a.p_hold),a.n_events==null?'—':`${a.n_events} 次`,a.trend_label || '—',stock.rising_stage || '—',yesNo(stock.kd_golden_cross),yesNo(stock.macd_red_bar),a.nearest_distance_atr==null?'—':`${number(Math.abs(a.nearest_distance_atr))} ATR`,nullable(a.nearest_support),nullable(a.nearest_resistance),nullable(a.n_zones),data.is_intraday?`≥${volumeThresholdText()}`:number(stock.volume_lots),`${stock.pullback_pct}%`];
    for(const [i,value] of values.entries()) { const td=document.createElement('td'); td.textContent=value; if(i===1 && change!=null) td.className=change>=0?'price-up':'price-down'; row.append(td); }
    $('rows').append(row);
  }
  if(matches.length) show(matches.find(s=>s.code===selected)||matches[0]);
  else { selected=null; $('stock-title').textContent='沒有符合的股票'; $('csv').hidden=true; $('metrics').replaceChildren(); if(window.Plotly) Plotly.purge('chart'); $('chart').replaceChildren(); for (const action of ['in','out','reset']) $('zoom-'+action).disabled=true; }
}
if(!data) { $('status').textContent='資料載入失敗，請重新整理或稍後再試。'; document.querySelector('.download').hidden=true; }
else {
  const waiting=data.waiting_matches || [];
  $('date').textContent=data.date;
  $('confirmed-count').textContent=`${data.matches.length} 檔`;
  $('waiting-count').textContent=`${waiting.length} 檔`;
  const age=Math.floor((Date.now()-new Date(`${data.date}T00:00:00+08:00`).getTime())/86400000);
  const asOf=data.as_of?new Date(data.as_of).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'}):'';
  const coverage=data.snapshot_universe!=null&&data.universe_size!=null?` · 有效快照 ${data.snapshot_universe}/${data.universe_size} 檔`:'';
  $('status').textContent=data.is_intraday
    ? `盤中暫定（截至 ${asOf}）${coverage} · 累積量達 ${volumeThresholdText()} 張 ${data.liquid_universe} 檔 · 止跌紅 K ${data.matches.length} 檔 · 等待紅 K ${waiting.length} 檔 · 13:30 收盤前條件仍可能改變。`
    : `成交量達標 ${data.liquid_universe} 檔 · 止跌紅 K ${data.matches.length} 檔 · 等待紅 K ${waiting.length} 檔 · ${age>=4?'資料日距今 '+age+' 天，可能為休市或更新未完成，請核對更新紀錄。':'以標示的完整交易日行情為準。'}`;
  if(data.is_intraday) $('analysis-note').textContent=`本頁為盤中暫定篩選結果；成交量門檻固定為累積 ${volumeThresholdText()} 張。圖表最右側「盤中暫時 K」使用證交所 MIS 的開、高、低、最新價，收盤前仍會變動；精確盤中成交量不公開，因此量 MA5／MA10 只計算完整日成交量。頭、底與轉折採 line-lab 的左右波段確認方式，可分別顯示或隱藏；暫時 K 尚未形成已確認轉折。支撐壓力與機率仍以最近完整收盤資料計算。`;
  $('built').textContent=`網頁產生時間 ${new Date(data.built_at).toLocaleString('zh-TW',{timeZone:'Asia/Taipei'})}（台灣）`;
  for(const id of ['search','market','sort']) $(id).addEventListener(id==='search'?'input':'change',render);
  for(const view of ['confirmed','waiting']) $(view+'-tab').addEventListener('click',()=>{
    activeView=view; selected=null;
    for(const name of ['confirmed','waiting']) $(name+'-tab').setAttribute('aria-selected',String(name===view));
    render();
  });
  render();
}
