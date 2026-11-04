const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),helper=fs.readFileSync(path.join(root,'map/assets/renewable-freshness.js'),'utf8');
const html=fs.readFileSync(path.join(root,'map/index.html'),'utf8'),listing=fs.readFileSync(path.join(root,'map/renewables.html'),'utf8');
const stale={checkedAt:'2026-11-03T10:00:00Z',sources:{osm:{status:'stale',retained:70,lastAttemptAt:'2026-11-03T10:00:00Z',lastSuccessAt:'2026-11-02T10:00:00Z'},'veiregistar:test':{status:'ok',lastSuccessAt:'2026-11-03T10:00:00Z'}}};
const ok=JSON.parse(JSON.stringify(stale));ok.sources.osm.status='ok';ok.sources.osm.lastSuccessAt=ok.checkedAt;
const project={id:'mixed',name:'Mixed',technology:'solar',mw:10,status:'operating',source:'https://example.org/test',sourceMode:'veiregistar:test',sourceModes:['osm','veiregistar:test'],retrievedAt:'2026-11-03T10:00:00Z',statusSourceMode:'veiregistar:test',capacitySourceMode:'veiregistar:test',geometrySourceMode:'osm',sourceFreshness:{osm:{status:'stale',lastSuccessAt:'2026-11-02T10:00:00Z'}}};
function context(extra={}){const c={console,...extra};c.window=c;vm.createContext(c);vm.runInContext(helper,c);return c;}
class Element{
 constructor(){this.children=[];this.value='';this.textContent='';this.events={};}
 append(...xs){this.children.push(...xs);}appendChild(x){this.children.push(x);return x;}
 replaceChildren(...xs){this.children=xs;}addEventListener(type,fn){this.events[type]=fn;}
}
async function listCase(health,fail=false){
 const elements=Object.fromEntries(['q','min-mw','max-mw','range-error','status','tech','count','rows','source-freshness','pending-review','pending-review-count','pending-review-rows'].map(id=>[id,new Element()]));
 const c=context({document:{getElementById:id=>elements[id],createElement:()=>new Element()},fetch:async url=>{
  if(url.includes('health')){if(fail)throw Error('offline');return {ok:true,json:async()=>health};}
  return {ok:true,json:async()=>({features:[{type:'Feature',properties:project,geometry:{type:'Point',coordinates:[25,42]}}]})};
 }});
 vm.runInContext(listing.match(/<script>([\s\S]*?)<\/script>/)[1],c);
 await new Promise(r=>setTimeout(r,0));
 assert.equal(elements.rows.children.length,1,'Health failure must preserve cached rows');
 return elements;
}
async function run(){
 const c=context(),api=c.bgwfRenewableFreshness;
 assert.equal(api.warnings(ok).length,0);
 assert.match(api.warnings(stale).join(' '),/70 записа/);
 assert.match(api.recordNote(project,stale),/OSM \(местоположение\)/);
 assert(!api.recordNote(project,stale).includes('OSM (статус'));
 assert(api.recordNote(project,stale).includes('2.11.2026'),'Fresh registry date must not replace the OSM observation date');
 assert.equal(api.recordNote(project,ok),'','Recovery clears stale row notices');
 const agkk={...project,sourceMode:'osm',capacitySourceMode:'osm',statusSourceMode:'osm',geometrySourceMode:'agkk'};
 assert(!api.recordNote(agkk,stale).includes('местоположение'),'OSM outage must not date AGKK geometry');
 assert.equal(await api.load(async()=>{throw Error('offline');}),null);
 assert.equal(await api.load(async()=>({ok:false,status:404})),null);
 assert.equal(await api.load(async()=>({ok:true,json:async()=>({sources:{}})})),null);
 assert.equal(await api.load(async()=>({ok:true,json:async()=>({sources:{osm:{status:'surprise'}}})})),null);
 // Exercise the real map completion resolver and warning selector.
 Object.assign(c,{layerVisibility:{solar:true},renewableHealthChecked:true,renewableSourceHealth:stale,bgwfRenewableInventory:{features:[]},trackMapLoader:(_id,_layers,_fn,result)=>result,loadRenewableCache:()=>{}});
 vm.runInContext(html.slice(html.indexOf('function layerSourceWarnings(){'),html.indexOf('function renderSourceWarning(){')),c);
 vm.runInContext(html.split('\n').find(line=>line.startsWith("loadRenewableCache=trackMapLoader('renewable-cache'")),c);
 for(const [health,expected] of [[stale,'warning'],[null,'warning'],[ok,'ready']]){
  c.renewableSourceHealth=health;assert.equal(c.loadRenewableCache(),expected);
  const warnings=c.layerSourceWarnings();assert.equal(warnings.length,expected==='ready'?0:1);
  assert(warnings.every(w=>!w.transient),'Freshness warnings must survive transient notice expiry');
 }
 c.layerVisibility.solar=false;c.renewableSourceHealth=stale;assert.equal(c.layerSourceWarnings().length,0);
 const retained=await listCase(stale);assert.equal(retained['source-freshness'].hidden,false);assert.match(retained['source-freshness'].textContent,/70 записа/);
 assert(retained.rows.children[0].children.at(-1).children.some(x=>typeof x==='string'&&x.includes('OSM (местоположение)')));
 const missing=await listCase(null,true);assert.equal(missing['source-freshness'].hidden,false);assert.match(missing['source-freshness'].textContent,/не може да се провери/);
 const invalid=await listCase({sources:{}});assert.equal(invalid['source-freshness'].hidden,false);
 const recovered=await listCase(ok);assert.equal(recovered['source-freshness'].hidden,true);
 assert(!recovered.rows.children[0].children.at(-1).children.some(x=>typeof x==='string'&&x.includes('запазени данни')));
 console.log('PASS: stale/missing/invalid health; per-source dates and geometry provenance; map warning/ready and active layers; inventory rows preserved; recovery clears notices.');
}
run().catch(e=>{console.error(e.stack);process.exitCode=1;});
