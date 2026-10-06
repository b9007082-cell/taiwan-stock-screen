const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const stocks={
  '2330':['台積電',1015], '2454':['聯發科',1420], '2317':['鴻海',214], '0050':['元大台灣50',198.5],
  '2308':['台達電',882], '2881':['富邦金',89.7], '2891':['中信金',43.8], '2382':['廣達',288]
};
const state={ticker:'2330',period:120,data:[],viewStart:0,viewEnd:120,dragX:null,dragMoved:false,crosshairIndex:null,crosshairLocked:false,source:'demo',name:'',showPivots:true,showTurns:true,showTrend:true};

function seeded(seed){let x=seed||1;return()=>((x=Math.imul(48271,x)%2147483647)&2147483647)/2147483647}
function generateData(ticker,count=260){
  const base=(stocks[ticker]||[`台股 ${ticker}`,80+(+ticker%300)])[1], rnd=seeded(+ticker+991), out=[];
  let p=base*.72, start=new Date();start.setDate(start.getDate()-count*1.45);
  for(let i=0;i<count;i++){
    const cycle=Math.sin(i/17)*.009+Math.sin(i/43)*.005, drift=(base-p)*.0008, shock=(rnd()-.47)*.026;
    const open=p*(1+(rnd()-.5)*.012), close=Math.max(5,p*(1+cycle+drift+shock));
    const high=Math.max(open,close)*(1+rnd()*.014), low=Math.min(open,close)*(1-rnd()*.014);
    const d=new Date(start);d.setDate(start.getDate()+Math.floor(i*1.45));
    out.push({date:d,open,high,low,close,volume:Math.round((.55+rnd()*1.5)*1e7)});p=close;
  }
  const ratio=base/out.at(-1).close;out.forEach(x=>['open','high','low','close'].forEach(k=>x[k]*=ratio));return out;
}
function cleanNumber(value){const n=Number(String(value??'').replace(/,/g,'').replace(/[+X]/g,''));return Number.isFinite(n)?n:null}
function parseRocDate(value){const [y,m,d]=String(value).split('/').map(Number);return new Date(y+1911,m-1,d)}
async function fetchTwseHistory(ticker){
  const now=new Date(),months=[];
  for(let i=0;i<13;i++){const d=new Date(now.getFullYear(),now.getMonth()-i,1);months.push(`${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}01`)}
  const rows=[];let detectedName='';
  for(let i=0;i<months.length;i+=4){
    const batch=months.slice(i,i+4).map(async date=>{const url=`https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=${date}&stockNo=${encodeURIComponent(ticker)}`;const res=await fetch(url,{headers:{Accept:'application/json'}});if(!res.ok)throw new Error(`TWSE ${res.status}`);return res.json()});
    const results=await Promise.allSettled(batch);
    for(const result of results){if(result.status!=='fulfilled')continue;const json=result.value;if(json.stat!=='OK'||!Array.isArray(json.data))continue;
      if(!detectedName&&json.title){const match=json.title.match(new RegExp(`${ticker}\\s+(.+?)\\s+各日成交資訊`));if(match)detectedName=match[1].trim()}
      for(const row of json.data){const open=cleanNumber(row[3]),high=cleanNumber(row[4]),low=cleanNumber(row[5]),close=cleanNumber(row[6]),volume=cleanNumber(row[1]);if([open,high,low,close,volume].some(v=>v==null))continue;rows.push({date:parseRocDate(row[0]),open,high,low,close,volume})}
    }
  }
  const unique=[...new Map(rows.map(r=>[r.date.toISOString().slice(0,10),r])).values()].sort((a,b)=>a.date-b.date);
  if(unique.length<20)throw new Error('找不到足夠的上市歷史資料');return {data:unique,name:detectedName||stocks[ticker]?.[0]||`上市 ${ticker}`};
}
async function fetchStockInfo(ticker){
  const res=await fetch(`https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo&data_id=${encodeURIComponent(ticker)}`);if(!res.ok)return null;const json=await res.json();return json.data?.[0]||null;
}
async function fetchFinMindHistory(ticker,knownInfo=null){
  const start=new Date();start.setMonth(start.getMonth()-13);const startDate=start.toISOString().slice(0,10),base='https://api.finmindtrade.com/api/v4/data';
  const [priceRes,info]=await Promise.all([fetch(`${base}?dataset=TaiwanStockPrice&data_id=${encodeURIComponent(ticker)}&start_date=${startDate}`),knownInfo?Promise.resolve(knownInfo):fetchStockInfo(ticker)]);
  if(!priceRes.ok)throw new Error('上櫃行情服務無法連線');const priceJson=await priceRes.json();
  if(priceJson.status!==200||!Array.isArray(priceJson.data)||priceJson.data.length<20||info?.type!=='tpex')throw new Error('找不到足夠的上櫃歷史資料');
  const data=priceJson.data.map(q=>({date:new Date(`${q.date}T00:00:00`),open:+q.open,high:+q.max,low:+q.min,close:+q.close,volume:+q.Trading_Volume})).filter(q=>[q.open,q.high,q.low,q.close,q.volume].every(Number.isFinite));
  return {data,name:info.stock_name||`上櫃 ${ticker}`};
}
function setSource(source,message=''){
  state.source=source;const live=source!=='demo';$('#sourceBadge').classList.toggle('demo',!live);$('#sourceLabel').textContent=source==='twse'?'證交所官方資料':source==='finmind'?'上櫃行情 · FinMind':'示範資料模式';$('#exchange').textContent=source==='twse'?'TWSE':source==='finmind'?'TPEx':'DEMO';
  const last=state.data.at(-1)?.date;$('#dataStamp').textContent=live&&last?`更新至 ${last.toLocaleDateString('zh-TW')} · 盤後`:(message||'官方資料暫時無法取得');
}
function sma(data,n=20){return data.map((_,i)=>i<n-1?null:data.slice(i-n+1,i+1).reduce((s,x)=>s+x.close,0)/n)}
function emaValues(values,n){const alpha=2/(n+1),out=[];let previous=null;values.forEach(value=>{previous=previous==null?value:value*alpha+previous*(1-alpha);out.push(previous)});return out}
function stochasticKD(data,period=5,kSmooth=3,dSmooth=3){let previousK=50,previousD=50;return data.map((q,i)=>{if(i<period-1)return {k:null,d:null};const window=data.slice(i-period+1,i+1),high=Math.max(...window.map(x=>x.high)),low=Math.min(...window.map(x=>x.low)),rsv=high===low?50:(q.close-low)/(high-low)*100;previousK=((kSmooth-1)*previousK+rsv)/kSmooth;previousD=((dSmooth-1)*previousD+previousK)/dSmooth;return {k:previousK,d:previousD}})}
function macdValues(data,fast=6,slow=13,signalPeriod=9){const closes=data.map(q=>q.close),fastEma=emaValues(closes,fast),slowEma=emaValues(closes,slow),dif=fastEma.map((v,i)=>v-slowEma[i]),signal=emaValues(dif,signalPeriod);return dif.map((value,i)=>({dif:value,signal:signal[i],hist:value-signal[i]}))}
function atr(data,n=14){let tr=data.map((x,i)=>i?Math.max(x.high-x.low,Math.abs(x.high-data[i-1].close),Math.abs(x.low-data[i-1].close)):x.high-x.low);return tr.slice(-n).reduce((a,b)=>a+b,0)/Math.min(n,tr.length)}
function trendStructure(data,offset=0){
  const windowSize=data.length>180?3:2,highs=[],lows=[];
  for(let i=windowSize;i<data.length-windowSize;i++){
    const window=data.slice(i-windowSize,i+windowSize+1),q=data[i];
    if(q.high===Math.max(...window.map(x=>x.high)))highs.push({i:i+offset,value:q.high,date:q.date,type:'high'});
    if(q.low===Math.min(...window.map(x=>x.low)))lows.push({i:i+offset,value:q.low,date:q.date,type:'low'});
  }
  const raw=[...highs,...lows].sort((a,b)=>a.i-b.i),pivots=[];
  raw.forEach(p=>{const last=pivots.at(-1);if(!last||last.type!==p.type)pivots.push(p);else if((p.type==='high'&&p.value>last.value)||(p.type==='low'&&p.value<last.value))pivots[pivots.length-1]=p});
  const risingPair=points=>{for(let b=points.length-1;b>0;b--){for(let a=b-1;a>=Math.max(0,b-6);a--){if(points[b].value>points[a].value&&points[b].i-points[a].i>=4)return [points[a],points[b]]}}return null};
  return {highPair:risingPair(highs),lowPair:risingPair(lows),highs,lows,pivots};
}
function levels(data){
  const last=data.at(-1).close,rangeAtr=atr(data),band=Math.max(rangeAtr*.7,last*.004),bins=new Map(),totalVolume=data.reduce((s,q)=>s+q.volume,0);
  data.forEach((q,i)=>{
    const from=Math.floor(q.low/band),to=Math.floor(q.high/band),count=Math.max(1,to-from+1),recency=.6+.4*i/Math.max(1,data.length-1);
    for(let key=from;key<=to;key++){const b=bins.get(key)||{raw:0,recent:0};const share=q.volume/count;b.raw+=share;b.recent+=share*recency;bins.set(key,b)}
  });
  const keys=[...bins.keys()].sort((a,b)=>a-b),smoothed=new Map();
  keys.forEach(k=>{const here=bins.get(k)?.recent||0,near=(bins.get(k-1)?.recent||0)+(bins.get(k+1)?.recent||0);smoothed.set(k,here+near*.28)});
  const peaks=keys.filter(k=>(smoothed.get(k)||0)>=(smoothed.get(k-1)||0)&&(smoothed.get(k)||0)>=(smoothed.get(k+1)||0));
  const maxDensity=Math.max(...peaks.map(k=>smoothed.get(k)),1);
  const zones=peaks.map(k=>{
    const price=(k+.5)*band,low=k*band,high=(k+1)*band;
    const touches=data.filter(q=>q.low<=high&&q.high>=low).length,latest=[...data].reverse().findIndex(q=>q.low<=high&&q.high>=low),recent=latest<0?0:1-latest/Math.max(1,data.length-1);
    const volumeScore=(smoothed.get(k)/maxDensity)*70,touchScore=Math.min(20,touches*2.5),recentScore=recent*10;
    return {price,low,high,score:volumeScore+touchScore+recentScore,volumeShare:(bins.get(k)?.raw||0)/Math.max(1,totalVolume)*100,touches};
  }).sort((a,b)=>b.score-a.score);
  const swings=trendStructure(data),lookback=Math.min(45,data.length),start=data.length-lookback,lastIndex=data.length-1;
  const highs=swings.highs.filter(p=>p.i>=start),lows=swings.lows.filter(p=>p.i>=start);
  const lastBar=data.at(-1),wick=lastBar.high-last;
  if(wick>=rangeAtr*.25)highs.push({i:lastIndex,value:lastBar.high,date:lastBar.date,type:'high'});
  const latestBeyond=(points,distance,side)=>points.filter(p=>side==='high'?p.value>=last+distance:p.value<=last-distance).sort((a,b)=>b.i-a.i||Math.abs(a.value-last)-Math.abs(b.value-last))[0]||null;
  const resistancePoint=latestBeyond(highs,rangeAtr*.25,'high')||latestBeyond(highs,rangeAtr*.08,'high');
  const clusterGap=Math.max(rangeAtr*.16,last*.0015),lowPoints=data.map((q,i)=>({i,value:q.low,date:q.date})).filter(p=>p.i>=start).sort((a,b)=>a.value-b.value),lowClusters=[];
  lowPoints.forEach(p=>{const cluster=lowClusters.at(-1);if(cluster&&p.value-cluster.max<=clusterGap){cluster.points.push(p);cluster.max=Math.max(cluster.max,p.value)}else lowClusters.push({min:p.value,max:p.value,points:[p]})});
  const clusteredSupports=lowClusters.filter(c=>c.points.length>=2).map(c=>{
    const counts=new Map();c.points.forEach(p=>counts.set(p.value,(counts.get(p.value)||0)+1));
    const maxCount=Math.max(...counts.values()),repeated=[...counts.entries()].filter(([,count])=>count===maxCount).map(([value])=>value);
    const modeValue=repeated.sort((a,b)=>{const ai=Math.max(...c.points.filter(p=>p.value===a).map(p=>p.i)),bi=Math.max(...c.points.filter(p=>p.value===b).map(p=>p.i));return bi-ai})[0];
    const value=modeValue-c.min<=clusterGap*.25?c.min:modeValue,selectedPoint=[...c.points].filter(p=>p.value===value).sort((a,b)=>b.i-a.i)[0];
    return {i:selectedPoint.i,value,date:selectedPoint.date,type:'low',clusterLow:c.min,clusterHigh:c.max,tests:c.points.length};
  });
  const supportPoint=latestBeyond(clusteredSupports,rangeAtr*1.35,'low')||latestBeyond(lows,rangeAtr*1.35,'low')||latestBeyond(clusteredSupports,rangeAtr*.45,'low')||latestBeyond(lows,rangeAtr*.45,'low');
  const structuralZone=(point,type)=>{
    if(!point)return null;
    const half=Math.max(last*.0025,rangeAtr*.12),low=Math.min(point.clusterLow??point.value-half,point.value-half),high=Math.max(point.clusterHigh??point.value+half,point.value+half);
    const touched=data.filter(q=>q.low<=high&&q.high>=low),touches=touched.length,volumeShare=touched.reduce((s,q)=>s+q.volume,0)/Math.max(1,totalVolume)*100;
    const age=lastIndex-point.i,recency=Math.max(0,1-age/lookback),distance=Math.abs(point.value-last)/Math.max(rangeAtr,1e-6),score=Math.min(94,55+recency*20+Math.min(12,touches*1.5)+Math.max(0,7-distance));
    return {price:point.value,low,high,score,volumeShare,touches,date:point.date,type};
  };
  const resistance=structuralZone(resistancePoint,'swing-high'),support=structuralZone(supportPoint,'swing-low');
  return {resistance:resistance?.price??null,support:support?.price??null,resistanceZone:resistance,supportZone:support,all:zones.slice(0,6)};
}
function fmt(n){return n>=100?Math.round(n).toLocaleString('zh-TW'):n.toFixed(2)}
function volumeFmt(n){return n>=1e8?`${(n/1e8).toFixed(1)}億`:n>=1e4?`${(n/1e4).toFixed(0)}萬`:Math.round(n).toLocaleString('zh-TW')}
function updateSummary(){
  const d=state.data,last=d.at(-1).close,prev=d.at(-2).close,change=last-prev,pct=change/prev*100,periodStart=Math.max(0,d.length-state.period),trend=trendStructure(d.slice(periodStart),periodStart),lv=levels(d.slice(-state.period)),ma=sma(d,20).at(-1);
  const zoneScores=[lv.resistanceZone,lv.supportZone].filter(Boolean).map(z=>z.score),name=state.name||(stocks[state.ticker]||[`台股 ${state.ticker}`])[0],bullish=last>ma,score=Math.round(Math.min(94,zoneScores.reduce((a,b)=>a+b,0)/Math.max(1,zoneScores.length)));
  $('#stockName').textContent=name;$('#stockTicker').textContent=state.ticker;$('#lastPrice').textContent=fmt(last);
  $('#priceChange').textContent=`${change>=0?'+':''}${fmt(change)} (${pct>=0?'+':''}${pct.toFixed(2)}%)`;$('#priceChange').style.color=change>=0?'#63d5a5':'#ef866d';
  $('#resistance').textContent=lv.resistanceZone?fmt(lv.resistance):'—';$('#support').textContent=lv.supportZone?fmt(lv.support):'—';$('#resistanceDistance').textContent=lv.resistanceZone?`+${((lv.resistance/last-1)*100).toFixed(1)}%`:'創高區';$('#supportDistance').textContent=lv.supportZone?`${((lv.support/last-1)*100).toFixed(1)}%`:'破底區';
  const levelDate=z=>z?.date?z.date.toLocaleDateString('zh-TW',{month:'numeric',day:'numeric'}):'';
  $('#resistanceMeta').textContent=lv.resistanceZone?`近期高點 ${levelDate(lv.resistanceZone)} · 量價確認 ${lv.resistanceZone.touches} 次`:'上方尚無確認壓力';$('#supportMeta').textContent=lv.supportZone?`確認低點 ${levelDate(lv.supportZone)} · 量價確認 ${lv.supportZone.touches} 次`:'下方尚無確認支撐';
  $('#score').textContent=score;$('#scoreRing').style.setProperty('--score',score);$('#scoreRing span').textContent=bullish?'偏多':'整理';
  const overhead=lv.resistanceZone?'上方近期波段高點可能形成賣壓':'目前上方尚無確認壓力',under=lv.supportZone?'回測確認支撐不破，結構仍完整':'下方尚無確認支撐';
  $('#structureText').textContent=bullish?`價格位於 MA20 之上，短期結構偏多。${overhead}；${under}。`:`價格位於 MA20 之下，短期處於整理。${lv.resistanceZone?'若能帶量突破波段壓力，結構有機會轉強':'若能帶量站回均線，結構有機會轉強'}；${lv.supportZone?'跌破波段支撐則需留意風險':'下方沒有明確支撐'}。`;
  $('#trendState').textContent=trend.highPair&&trend.lowPair?'多方結構：頭頭高・底底高':trend.highPair?'波段頭頭高':trend.lowPair?'波段底底高':'尚未形成上升結構';
}
function draw(){
  const canvas=$('#chart'),box=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio,2);canvas.width=box.width*dpr;canvas.height=box.height*dpr;const c=canvas.getContext('2d');c.scale(dpr,dpr);const W=box.width,H=box.height,pad={l:52,r:62,t:24,b:38},priceBottom=Math.max(285,H-390),volumeTop=priceBottom+30,volumeBottom=volumeTop+82,kdTop=volumeBottom+34,kdBottom=kdTop+82,macdTop=kdBottom+34,macdBottom=H-pad.b;
  const periodStart=Math.max(0,state.data.length-state.period),trend=trendStructure(state.data.slice(periodStart),periodStart),data=state.data.slice(state.viewStart,state.viewEnd),ma=sma(state.data,20).slice(state.viewStart,state.viewEnd),volumeMa=state.data.map((_,i)=>i<4?null:state.data.slice(i-4,i+1).reduce((s,q)=>s+q.volume,0)/5).slice(state.viewStart,state.viewEnd),kd=stochasticKD(state.data,5,3,3).slice(state.viewStart,state.viewEnd),macd=macdValues(state.data,6,13,9).slice(state.viewStart,state.viewEnd),lv=levels(state.data.slice(-state.period));if(!data.length)return;
  const lo=Math.min(...data.map(x=>x.low),lv.support??Infinity)*.985,hi=Math.max(...data.map(x=>x.high),lv.resistance??-Infinity)*1.015,volMax=Math.max(...data.map(x=>x.volume))*1.12,x=i=>pad.l+i*(W-pad.l-pad.r)/(data.length-1||1),y=v=>pad.t+(hi-v)*(priceBottom-pad.t)/(hi-lo),vy=v=>volumeBottom-v/volMax*(volumeBottom-volumeTop),kdY=v=>kdBottom-v/100*(kdBottom-kdTop),macdMax=Math.max(.001,...macd.flatMap(v=>[Math.abs(v.dif),Math.abs(v.signal),Math.abs(v.hist)]))*1.12,macdY=v=>(macdTop+macdBottom)/2-v/macdMax*(macdBottom-macdTop)/2;
  c.clearRect(0,0,W,H);c.font='10px system-ui';c.fillStyle='#75837b';c.strokeStyle='#2b3d34';c.lineWidth=1;
  for(let i=0;i<6;i++){let yy=pad.t+i*(priceBottom-pad.t)/5,val=hi-i*(hi-lo)/5;c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke();c.fillText(fmt(val),W-pad.r+8,yy+3)}
  for(let i=0;i<5;i++){let xx=pad.l+i*(W-pad.l-pad.r)/4,idx=Math.round(i*(data.length-1)/4),dt=data[idx].date;c.fillText(`${dt.getMonth()+1}/${dt.getDate()}`,xx-10,H-20)}
  const drawLevel=(zone,color,label)=>{if(!zone)return;const yy=y(zone.price),top=y(zone.high),bottom=y(zone.low);c.save();c.fillStyle=color+'24';c.fillRect(pad.l,top,W-pad.l-pad.r,bottom-top);c.strokeStyle=color;c.setLineDash([6,5]);c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke();c.setLineDash([]);c.fillStyle=color;c.fillRect(pad.l,yy-10,84,18);c.fillStyle='#102019';c.font='700 10px system-ui';c.fillText(`${label} ${fmt(zone.price)}`,pad.l+6,yy+3);c.restore()};drawLevel(lv.resistanceZone,'#e7775b','波段壓力');drawLevel(lv.supportZone,'#55d29c','波段支撐');
  const cw=Math.max(2,Math.min(9,(W-pad.l-pad.r)/data.length*.62));data.forEach((q,i)=>{const xx=x(i),up=q.close>=q.open,col=up?'#ef7457':'#4ed39b';c.strokeStyle=col;c.fillStyle=up?col:'#16261e';c.beginPath();c.moveTo(xx,y(q.high));c.lineTo(xx,y(q.low));c.stroke();const top=Math.min(y(q.open),y(q.close)),ht=Math.max(1,Math.abs(y(q.open)-y(q.close)));up?c.fillRect(xx-cw/2,top,cw,ht):c.strokeRect(xx-cw/2,top,cw,ht);c.globalAlpha=.55;c.fillStyle=col;c.fillRect(xx-cw/2,vy(q.volume),cw,volumeBottom-vy(q.volume));c.globalAlpha=1});
  c.strokeStyle='#e5b83f';c.lineWidth=1.5;c.beginPath();let started=false;ma.forEach((v,i)=>{if(v==null)return;started?(c.lineTo(x(i),y(v))):(c.moveTo(x(i),y(v)),started=true)});c.stroke();
  const drawTrend=(pair,color,label)=>{if(!pair)return;const [a,b]=pair,slope=(b.value-a.value)/(b.i-a.i),left=Math.max(state.viewStart,a.i),right=state.viewEnd-1,valueAt=index=>a.value+slope*(index-a.i);c.save();c.beginPath();c.rect(pad.l,pad.t,W-pad.l-pad.r,priceBottom-pad.t);c.clip();c.strokeStyle=color;c.lineWidth=2.2;c.beginPath();c.moveTo(x(left-state.viewStart),y(valueAt(left)));c.lineTo(x(right-state.viewStart),y(valueAt(right)));c.stroke();[a,b].forEach(p=>{if(p.i<state.viewStart||p.i>=state.viewEnd)return;c.fillStyle='#16261e';c.strokeStyle=color;c.lineWidth=2;c.beginPath();c.arc(x(p.i-state.viewStart),y(p.value),4,0,Math.PI*2);c.fill();c.stroke()});c.restore();const labelY=y(valueAt(right));if(labelY>pad.t+8&&labelY<priceBottom-8){c.fillStyle=color;c.font='800 9px system-ui';c.fillText(label,W-pad.r-42,labelY-5)}};
  const visiblePivots=trend.pivots.filter(p=>p.i>=state.viewStart&&p.i<state.viewEnd);
  if(state.showTurns&&visiblePivots.length>1){c.save();c.strokeStyle='#8f9d95';c.lineWidth=1.25;c.globalAlpha=.8;c.beginPath();visiblePivots.forEach((p,i)=>i?c.lineTo(x(p.i-state.viewStart),y(p.value)):c.moveTo(x(p.i-state.viewStart),y(p.value)));c.stroke();c.restore()}
  if(state.showTrend){drawTrend(trend.highPair,'#e7775b','頭頭高');drawTrend(trend.lowPair,'#55d29c','底底高')}
  if(state.showPivots){visiblePivots.forEach(p=>{const px=x(p.i-state.viewStart),py=y(p.value),color=p.type==='high'?'#ef6657':'#31b976',text=p.type==='high'?'頭':'底';c.save();c.fillStyle='#f7f5ed';c.strokeStyle=color;c.lineWidth=1.8;c.beginPath();c.arc(px,py,7,0,Math.PI*2);c.fill();c.stroke();c.fillStyle=color;c.font='900 8px "Microsoft JhengHei",sans-serif';c.textAlign='center';c.textBaseline='middle';c.fillText(text,px,py+.5);c.restore()})}
  const drawSeries=(values,mapY,color,width=1.5)=>{c.strokeStyle=color;c.lineWidth=width;c.beginPath();let active=false;values.forEach((v,i)=>{if(v==null||!Number.isFinite(v)){active=false;return}active?c.lineTo(x(i),mapY(v)):(c.moveTo(x(i),mapY(v)),active=true)});c.stroke()};
  drawSeries(volumeMa,vy,'#a9b9b1',1.2);c.fillStyle='#839188';c.font='700 9px system-ui';c.fillText('成交量／MA5',pad.l,volumeTop-9);c.fillText(volumeFmt(volMax),W-pad.r+8,volumeTop+3);c.strokeStyle='#405048';c.beginPath();c.moveTo(pad.l,priceBottom+15);c.lineTo(W-pad.r,priceBottom+15);c.stroke();
  [20,50,80].forEach(value=>{const yy=kdY(value);c.strokeStyle=value===50?'#405048':'#2b3d34';c.beginPath();c.moveTo(pad.l,yy);c.lineTo(W-pad.r,yy);c.stroke();c.fillStyle='#75837b';c.fillText(String(value),W-pad.r+8,yy+3)});drawSeries(kd.map(v=>v.k),kdY,'#ef6657',1.55);drawSeries(kd.map(v=>v.d),kdY,'#58a6e7',1.55);const kdLast=[...kd].reverse().find(v=>v.k!=null),kdText=kdLast?`KD(5,3,3)  K ${kdLast.k.toFixed(2)}  D ${kdLast.d.toFixed(2)}`:'KD(5,3,3)';c.fillStyle='#ef6657';c.font='800 9px system-ui';c.fillText(kdText,pad.l,kdTop-10);c.strokeStyle='#405048';c.beginPath();c.moveTo(pad.l,kdTop-20);c.lineTo(W-pad.r,kdTop-20);c.stroke();
  const zeroY=macdY(0),histWidth=Math.max(1,Math.min(7,(W-pad.l-pad.r)/data.length*.55));c.strokeStyle='#405048';c.beginPath();c.moveTo(pad.l,zeroY);c.lineTo(W-pad.r,zeroY);c.stroke();macd.forEach((v,i)=>{c.fillStyle=v.hist>=0?'#ef6657':'#4ed39b';const yy=macdY(v.hist);c.fillRect(x(i)-histWidth/2,Math.min(zeroY,yy),histWidth,Math.max(1,Math.abs(yy-zeroY)))});drawSeries(macd.map(v=>v.dif),macdY,'#e5b83f',1.55);drawSeries(macd.map(v=>v.signal),macdY,'#58a6e7',1.55);const macdLast=macd.at(-1),macdText=`MACD(6,13,9)  DIF ${macdLast.dif.toFixed(2)}  Signal ${macdLast.signal.toFixed(2)}  OSC ${macdLast.hist.toFixed(2)}`;c.fillStyle='#e5b83f';c.font='800 9px system-ui';c.fillText(macdText,pad.l,macdTop-10);c.fillStyle='#75837b';c.fillText(macdMax.toFixed(2),W-pad.r+8,macdTop+3);c.fillText((-macdMax).toFixed(2),W-pad.r+8,macdBottom);c.strokeStyle='#405048';c.beginPath();c.moveTo(pad.l,macdTop-20);c.lineTo(W-pad.r,macdTop-20);c.stroke();
  const crosshairRelative=state.crosshairIndex==null?-1:state.crosshairIndex-state.viewStart;if(crosshairRelative>=0&&crosshairRelative<data.length){const xx=x(crosshairRelative),q=data[crosshairRelative],dateLabel=`${q.date.getMonth()+1}/${q.date.getDate()}`;c.save();c.strokeStyle='#f3f1e7';c.lineWidth=1.35;c.globalAlpha=.96;c.shadowColor='#ffffff';c.shadowBlur=1.5;c.setLineDash([6,4]);c.beginPath();c.moveTo(xx,pad.t);c.lineTo(xx,macdBottom);c.stroke();c.setLineDash([]);c.shadowBlur=0;c.fillStyle='#f3f1e7';c.beginPath();c.arc(xx,y(q.close),3.4,0,Math.PI*2);c.fill();const tagW=42,tagX=Math.max(pad.l,Math.min(W-pad.r-tagW,xx-tagW/2));c.fillStyle='#f3f1e7';c.fillRect(tagX,macdBottom-15,tagW,15);c.fillStyle='#122019';c.font='800 9px system-ui';c.textAlign='center';c.fillText(dateLabel,tagX+tagW/2,macdBottom-4);c.restore()}
  canvas._geom={data,kd,macd,x,y,pad,W,H};
}
async function analyze(ticker){
  if(!/^\d{4,6}$/.test(ticker)){const i=$('#ticker');i.setCustomValidity('請輸入 4～6 位數字的台股代號');i.reportValidity();return}$('#ticker').setCustomValidity('');
  $('#workspace').classList.add('loading');$('#dataStamp').textContent='讀取近 13 個月行情…';state.ticker=ticker;
  try{
    const info=await fetchStockInfo(ticker);
    if(info?.type==='tpex'){const result=await fetchFinMindHistory(ticker,info);state.data=result.data;state.name=result.name;setSource('finmind')}
    else{const result=await fetchTwseHistory(ticker);state.data=result.data;state.name=result.name;setSource('twse')}
  }catch(primaryError){
    try{const result=await fetchFinMindHistory(ticker);state.data=result.data;state.name=result.name;setSource('finmind')}
    catch(fallbackError){state.data=generateData(ticker);state.name=(stocks[ticker]||[`台股 ${ticker}`])[0];setSource('demo','上市／上櫃皆查無資料 · 已切換示範')}
  }
  state.viewEnd=state.data.length;state.viewStart=Math.max(0,state.viewEnd-state.period);state.crosshairIndex=null;state.crosshairLocked=false;tip.hidden=true;updateSummary();draw();$('#workspace').classList.remove('loading');$('#workspace').scrollIntoView({behavior:'smooth',block:'start'});
}
$('#stockForm').addEventListener('submit',e=>{e.preventDefault();analyze($('#ticker').value.trim())});$$('[data-ticker]').forEach(b=>b.onclick=()=>{$('#ticker').value=b.dataset.ticker;analyze(b.dataset.ticker)});
$$('[data-period]').forEach(b=>b.onclick=()=>{$$('[data-period]').forEach(x=>x.classList.toggle('active',x===b));state.period=+b.dataset.period;state.viewEnd=state.data.length;state.viewStart=Math.max(0,state.viewEnd-state.period);state.crosshairIndex=null;state.crosshairLocked=false;tip.hidden=true;updateSummary();draw()});
$('#resetZoom').onclick=()=>{state.viewEnd=state.data.length;state.viewStart=Math.max(0,state.viewEnd-state.period);state.crosshairIndex=null;state.crosshairLocked=false;tip.hidden=true;draw()};
$('#togglePivots').onchange=e=>{state.showPivots=e.target.checked;draw()};$('#toggleTurns').onchange=e=>{state.showTurns=e.target.checked;draw()};$('#toggleTrend').onchange=e=>{state.showTrend=e.target.checked;draw()};
const canvas=$('#chart'),tip=$('#tooltip');
const pointerPosition=(e,g)=>{const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,i=Math.max(0,Math.min(g.data.length-1,Math.round((mx-g.pad.l)/(g.W-g.pad.l-g.pad.r)*(g.data.length-1))));return {mx,i}};
const showCrosshairTip=(i,mx,g)=>{const q=g.data[i],kd=g.kd[i],macd=g.macd[i];tip.hidden=false;tip.style.left=Math.min(g.W-190,Math.max(8,mx+12))+'px';tip.style.top='18px';tip.innerHTML=`${state.crosshairLocked?'📌 ':''}${q.date.toLocaleDateString('zh-TW')}<br>開 ${fmt(q.open)}　高 ${fmt(q.high)}<br>低 ${fmt(q.low)}　收 ${fmt(q.close)}<br>量 ${volumeFmt(q.volume)}${kd?.k!=null?`<br>K ${kd.k.toFixed(2)}　D ${kd.d.toFixed(2)}`:''}${macd?`<br>DIF ${macd.dif.toFixed(2)}　Signal ${macd.signal.toFixed(2)}<br>OSC ${macd.hist.toFixed(2)}`:''}`};
canvas.addEventListener('mousemove',e=>{const g=canvas._geom;if(!g||state.crosshairLocked)return;const {mx,i}=pointerPosition(e,g);state.crosshairIndex=state.viewStart+i;draw();showCrosshairTip(i,mx,canvas._geom)});
canvas.addEventListener('click',e=>{if(state.dragMoved){state.dragMoved=false;return}const g=canvas._geom;if(!g)return;const {mx,i}=pointerPosition(e,g),absolute=state.viewStart+i;if(state.crosshairLocked&&state.crosshairIndex===absolute){state.crosshairLocked=false;state.crosshairIndex=null;tip.hidden=true;draw();return}state.crosshairIndex=absolute;state.crosshairLocked=true;draw();showCrosshairTip(i,mx,canvas._geom)});
canvas.addEventListener('mouseleave',()=>{if(!state.crosshairLocked){state.crosshairIndex=null;tip.hidden=true;draw()}});
canvas.addEventListener('wheel',e=>{e.preventDefault();const len=state.viewEnd-state.viewStart,next=Math.max(35,Math.min(state.data.length,len+(e.deltaY>0?14:-14))),center=(state.viewStart+state.viewEnd)/2;state.viewStart=Math.max(0,Math.round(center-next/2));state.viewEnd=Math.min(state.data.length,state.viewStart+next);state.viewStart=Math.max(0,state.viewEnd-next);state.crosshairIndex=null;state.crosshairLocked=false;tip.hidden=true;draw()},{passive:false});
canvas.addEventListener('pointerdown',e=>{state.dragX=e.clientX;state.dragMoved=false;canvas.setPointerCapture(e.pointerId)});canvas.addEventListener('pointermove',e=>{if(state.dragX==null)return;const len=state.viewEnd-state.viewStart,shift=Math.round((state.dragX-e.clientX)/canvas.clientWidth*len);if(shift){state.dragMoved=true;let s=Math.max(0,Math.min(state.data.length-len,state.viewStart+shift));state.viewStart=s;state.viewEnd=s+len;state.dragX=e.clientX;state.crosshairIndex=null;state.crosshairLocked=false;tip.hidden=true;draw()}});canvas.addEventListener('pointerup',()=>state.dragX=null);
$('#explainBtn').onclick=()=>$('#methodDialog').showModal();$('#dialogClose').onclick=()=>$('#methodDialog').close();$('#themeBtn').onclick=()=>document.body.classList.toggle('light-off');window.addEventListener('resize',draw);
state.data=generateData(state.ticker);state.name=stocks[state.ticker][0];state.viewEnd=state.data.length;state.viewStart=state.viewEnd-state.period;setSource('demo','準備讀取官方行情…');updateSummary();requestAnimationFrame(draw);analyze(state.ticker);
