const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'map/renewables.html'),'utf8'),mapHtml=fs.readFileSync(path.join(root,'map/index.html'),'utf8');
const payload=JSON.parse(fs.readFileSync(path.join(root,'map/data/bg-renewables-cache-v1.geojson')));
const visible=payload.features.filter(f=>(f.properties.inventoryReviewStatus!=='pending-location'||f.geometry)&&(!f.properties.componentOf||!payload.features.some(p=>p.id===f.properties.componentOf)));
class Element{constructor(){this.children=[];this.value='';this.textContent='';this.events={};}append(...xs){this.children.push(...xs);}appendChild(x){this.children.push(x);return x;}replaceChildren(...xs){this.children=xs;}addEventListener(type,fn){this.events[type]=fn;}}
const elements=Object.fromEntries(['q','min-mw','max-mw','range-error','status','tech','count','rows','source-freshness','pending-review','pending-review-count','pending-review-rows'].map(id=>[id,new Element()]));
const c={document:{getElementById:id=>elements[id],createElement:()=>new Element()},fetch:async url=>({ok:true,json:async()=>url.includes('health')?JSON.parse(fs.readFileSync(path.join(root,'map/data/bg-renewables-health-v1.json'))):payload}),console};c.window=c;vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(root,'map/assets/renewable-freshness.js'),'utf8'),c);vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],c);
async function run(){
 await new Promise(r=>setTimeout(r,0));assert.equal(elements['pending-review-rows'].children.length,3);assert.equal(elements.rows.children.length,visible.length);
 function check(min,tech='',status='',query='',max=''){
  elements['min-mw'].value=min;elements['max-mw'].value=max;elements.tech.value=tech;elements.status.value=status;elements.q.value=query;elements['min-mw'].events.input();
  const expected=visible.filter(f=>f.properties.mw>=Math.max(0,Number(min)||0)&&f.properties.mw<=(max===''?Infinity:Math.max(0,Number(max)))&&(!tech||f.properties.technology===tech)&&(!status||f.properties.status===status)&&JSON.stringify(f.properties).toLowerCase().includes(query.toLowerCase()));
  assert.equal(elements.rows.children.length,expected.length);
  assert(elements.count.textContent.startsWith(`${expected.length} от`));return expected;
 }
 check('');check('100');check('1.5','solar');check('0','solar','planned');check('100000');
 const belmeken=check('375','pumped_hydro','','Белмекен');assert.equal(belmeken.length,1);assert(belmeken[0].geometry);assert.equal(belmeken[0].properties.mw,375);
 const orfey=check('160','pumped_hydro','','Орфей');assert.equal(orfey.length,1);assert(orfey[0].geometry);
 for(const name of ['Батак','Ивайловград','Кърджали','Сестримо','Кунино','Калето']){
  const plant=check('','hydro','',name);assert.equal(plant.length,1,name+' has one row');assert(plant[0].geometry,name+' keeps its coordinates');
 }
 const nikola=check('','wind','','Свети Никола');assert.equal(nikola.length,1);assert.equal(nikola[0].properties.mw,156);assert.equal(nikola[0].properties.componentRecords.length,2);
 const vetrocom=check('','wind','','Контакт консул');assert.equal(vetrocom.length,1);assert.equal(vetrocom[0].properties.mw,72.5);
 const lovech=check('','solar','','Ловеч');assert.equal(lovech.length,2);assert(lovech.every(f=>!f.properties.possibleDuplicateIds));
 const batak=check('','hydro','','Батак')[0];assert.equal(batak.properties.mw,46);
 assert.equal(elements.rows.children[0].children[2].children[0].children[0].textContent,'Различни мощности по източниците');
 assert.deepEqual(new Set(batak.properties.capacityObservations.map(o=>o.mw)),new Set([46,46.8]));
 check('','','','','50');check('10','','','','100');check('1.5','solar','','','10.5');
 const exact=check('375','pumped_hydro','','Белмекен','375');assert.equal(exact.length,1);
 check('100','','','','10');assert.equal(elements.rows.children.length,0);assert.equal(elements['range-error'].hidden,false);
 check('');assert.equal(elements['range-error'].hidden,true);assert.equal(elements.rows.children.length,visible.length);
 assert.equal((mapHtml.match(/data-renewables-list(?:\s|>)/g)||[]).length,1);assert(/href="\.\/renewables.html"[^>]*data-renewables-list[^>]*>Лист ВЕИ обекти<\/a>/.test(mapHtml));
 console.log('PASS: inclusive minimum/maximum MW filters, exact bounds, invalid ranges, decimal threshold, combined filters, reset, merged hydro rows with coordinates, persistent Лист ВЕИ link.');
}
run().catch(e=>{console.error(e.message);process.exitCode=1;});
