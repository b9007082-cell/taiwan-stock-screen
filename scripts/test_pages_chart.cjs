'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function checkChart(mobile) {
  function element() {
    const classes = new Set();
    return {children:[], value:'', attributes:{}, classList:{toggle(name,force){
        const add = force === undefined ? !classes.has(name) : force;
        if(add) classes.add(name); else classes.delete(name);
        return add;
      }, contains(name){return classes.has(name);}},
      append(...items){this.children.push(...items);}, replaceChildren(){this.children=[];},
      addEventListener(){}, setAttribute(name,value){this.attributes[name]=String(value);}};
  }
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  const body = element();
  get('sort').value = 'code';
  const bars = Array.from({length:100}, (_,i) => ({date:String(i),open:10,high:12,low:9,close:11,tick_volume:2000000+i*1000}));
  const stock = {code:'TEST',name:'Test',ma:{},bullish_reasons:[],close_position:0.5};
  let layout, config, range, chartTraces;
  let resizeCount=0;
  const Plotly = {purge(){}, Plots:{resize(){resizeCount++;}}, react(id,traces,l,c){chartTraces=traces;layout=l;config=c;},
    relayout(id,values){range=values['xaxis.range'];}};
  const context = vm.createContext({document:{body,getElementById:get,createElement:element}, Plotly,
    window:{STOCK_DATA:{matches:[],candles:{TEST:bars},date:'2026-09-29',built_at:'2026-09-29',min_volume_lots:1500},
      Plotly,addEventListener(){},matchMedia(){return {matches:mobile,addEventListener(){}};}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../pages/app.js'),'utf8'), context);
  context.show(stock);
  assert.equal(config.staticPlot, mobile);
  assert.equal(config.scrollZoom,false);
  assert.equal(config.doubleClick,false);
  assert.equal(layout.dragmode,false);
  assert.equal(layout.xaxis.fixedrange,true);
  assert.equal(chartTraces.length,11);
  assert.equal(chartTraces.find(trace=>trace.name==='成交量').yaxis,'y2');
  assert.equal(chartTraces.find(trace=>trace.name==='成交量').y[0],2000);
  assert.ok(chartTraces.findIndex(trace=>trace.name==='成交量') < chartTraces.findIndex(trace=>trace.name==='K(5,3)'));
  assert.equal(chartTraces.find(trace=>trace.name==='K(5,3)').yaxis,'y3');
  assert.equal(chartTraces.find(trace=>trace.name==='MACD柱').yaxis,'y4');
  assert.equal(layout.yaxis3.range[1],100);
  assert.ok(layout.yaxis2.domain[0] > layout.yaxis3.domain[1]);
  assert.equal(layout.font.size,mobile?10:12);
  assert.equal(get('zoom-out').disabled,true);
  context.zoomChart('in');
  assert.equal(range[1]-range[0],80);
  assert.equal(range[1],99.5);
  context.zoomChart('out');
  assert.equal(range[1]-range[0],100);
  for(let i=0;i<30;i++) context.zoomChart('in');
  assert.equal(range[1]-range[0],20);
  assert.equal(get('zoom-in').disabled,true);
  context.zoomChart('reset');
  assert.equal(range[1]-range[0],100);
  assert.equal(get('zoom-reset').disabled,true);
  context.zoomChart('in');
  context.show(stock);
  assert.equal(layout.xaxis.autorange,true);
  assert.equal(get('zoom-reset').disabled,true);
  context.render();
  assert.equal(get('zoom-in').disabled,true);
  context.setChartExpanded(true);
  assert.equal(get('stock-detail').classList.contains('chart-expanded'),true);
  assert.equal(body.classList.contains('chart-open'),true);
  assert.equal(get('chart-expand').attributes['aria-label'],'縮回圖表');
  context.setChartExpanded(false);
  assert.equal(get('stock-detail').classList.contains('chart-expanded'),false);
  assert.equal(body.classList.contains('chart-open'),false);
  assert.equal(get('chart-expand').attributes['aria-label'],'展開圖表');
  assert.equal(resizeCount,2);
}
checkChart(true);
checkChart(false);
assert.match(fs.readFileSync(path.join(__dirname,'../pages/index.html'),'utf8'), />上漲階段<\/th>/);
const css = fs.readFileSync(path.join(__dirname,'../pages/style.css'),'utf8');
assert.match(css, /@media\(max-width:850px\)\{#chart\{height:720px\}/);
assert.match(css, /\.detail\.chart-expanded/);
console.log('Mobile and desktop chart tests passed: taller chart, expand mode, bounded zoom, reset, selection, empty state.');
