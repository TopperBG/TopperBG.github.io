const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../map/index.html'),'utf8');
class Element{
 constructor(){this.dataset={};this.attrs={};this.values=new Set();this.style={setProperty(k,v){this[k]=v;}};this.classList={toggle:(key,on)=>{on?this.values.add(key):this.values.delete(key);},contains:key=>this.values.has(key)};}
 setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
}
const keys=['solar','projects','wind','natura','industry','future'];const buttons=Object.fromEntries(keys.map(key=>{const b=new Element();b.dataset.layer=key;b.setAttribute('aria-pressed',key==='solar'?'true':'false');return [key,b];}));
const bar=new Element(),fill=new Element(),panel=new Element();const c={mapLoadbar:bar,mapLoadbarFill:fill,filterPanel:panel,root:{querySelectorAll:()=>Object.values(buttons),querySelector:selector=>buttons[selector.match(/data-layer="([^"]+)"/)?.[1]]}};
vm.createContext(c);vm.runInContext(html.slice(html.indexOf('// Requested sources share one completion model;'),html.indexOf('function updateProvinceChipPosition()')),c);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};}
async function run(){
 const cadastre=deferred(),natura=deferred();let missing=false;
 const loadCadastre=c.trackMapLoader('cadastre',['solar','projects'],()=>cadastre.promise,()=>missing?'warning':'ready');
 const loadNatura=c.trackMapLoader('natura',['natura'],()=>natura.promise);
 const cad=loadCadastre(),nat=loadNatura();
 c.setMapLoadProgress(50,'loading');assert.equal(buttons.solar.style['--load-progress'],'50%');assert.equal(bar.dataset.loadState,'loading');assert.equal(buttons.solar.attrs['aria-busy'],'true');
 c.setMapLoadProgress(100,'ready');c.setFilterPanelLoading(false);assert.equal(bar.dataset.loadState,'loading','A processed cadastre must not prematurely finish pending sources');
 cadastre.resolve();await cad;assert.equal(buttons.solar.dataset.loadState,'ready');assert.equal(buttons.natura.dataset.loadState,'loading');assert.equal(bar.dataset.loadState,'loading','Natura still pending');
 natura.resolve();await nat;assert.equal(bar.dataset.loadState,'ready');assert(bar.classList.contains('is-ready'));assert.equal(fill.style.background,'#16a34a');assert.equal(fill.style.width,'100%');assert.equal(bar.attrs['aria-valuenow'],'100');
 assert.equal(buttons.solar.attrs['aria-pressed'],'true');assert.equal(buttons.natura.attrs['aria-pressed'],'false','Loading must preserve selection');
 const cache=c.trackMapLoader('cache',['wind'],async()=>[]);await cache();assert.equal(buttons.wind.dataset.loadState,'ready');assert.equal(bar.dataset.loadState,'ready','Cache-only success is green');
 const failed=c.trackMapLoader('industry',['industry'],async()=>{throw Error('HTTP 503');});await assert.rejects(failed,/503/);assert.equal(bar.dataset.loadState,'warning');assert(!bar.classList.contains('is-ready'));assert.equal(fill.style.background,'#f59e0b');assert.equal(buttons.industry.attrs['aria-busy'],'false');
 const retry=c.trackMapLoader('industry',['industry'],async()=>[]);await retry();assert.equal(bar.dataset.loadState,'ready','A successful retry clears the warning');
 const partial=c.trackMapLoader('partial',['projects'],async()=>[],()=> 'error');await partial();assert.equal(bar.dataset.loadState,'warning','A swallowed loader error must not show green');assert.equal(buttons.projects.dataset.loadState,'warning');
 c.setLayerLoadState('future','ready');assert.equal(buttons.future.dataset.loadState,'ready');
 console.log('PASS: concurrent online/cache completion; queued/pending protection; full green success; partial failures and retry; progress and aria-pressed preserved.');
}
run().catch(e=>{console.error(e.stack);process.exitCode=1;});
