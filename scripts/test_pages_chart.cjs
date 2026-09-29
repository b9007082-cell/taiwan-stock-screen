'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function checkChart(mobile) {
  function element() {
    return {children:[], value:'', classList:{toggle(){}, contains(){return false;}},
      append(...items){this.children.push(...items);}, replaceChildren(){this.children=[];},
      addEventListener(){}};
  }
  const nodes = new Map();
  const get = id => { if (!nodes.has(id)) nodes.set(id, element()); return nodes.get(id); };
  get('sort').value = 'code';
  const bars = Array.from({length:100}, (_,i) => ({date:String(i),open:10,high:12,low:9,close:11}));
  const stock = {code:'TEST',name:'Test',ma:{},bullish_reasons:[],close_position:0.5};
  let layout, config, range;
  const Plotly = {purge(){}, react(id,traces,l,c){layout=l;config=c;},
    relayout(id,values){range=values['xaxis.range'];}};
  const context = vm.createContext({document:{getElementById:get,createElement:element}, Plotly,
    window:{STOCK_DATA:{matches:[],candles:{TEST:bars},date:'2026-09-29',built_at:'2026-09-29'},
      Plotly,addEventListener(){},matchMedia(){return {matches:mobile,addEventListener(){}};}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../pages/app.js'),'utf8'), context);
  context.show(stock);
  assert.equal(config.staticPlot, mobile);
  assert.equal(config.scrollZoom,false);
  assert.equal(config.doubleClick,false);
  assert.equal(layout.dragmode,false);
  assert.equal(layout.xaxis.fixedrange,true);
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
}
checkChart(true);
checkChart(false);
console.log('Mobile and desktop chart tests passed: bounded zoom, reset, selection, empty state.');
