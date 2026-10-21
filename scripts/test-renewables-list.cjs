const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'map/renewables.html'),'utf8'),mapHtml=fs.readFileSync(path.join(root,'map/index.html'),'utf8');
const payload=JSON.parse(fs.readFileSync(path.join(root,'map/data/bg-renewables-cache-v1.geojson')));
class Element{constructor(){this.children=[];this.value='';this.textContent='';this.events={};}append(...xs){this.children.push(...xs);}appendChild(x){this.children.push(x);return x;}replaceChildren(...xs){this.children=xs;}addEventListener(type,fn){this.events[type]=fn;}}
const elements=Object.fromEntries(['q','min-mw','status','tech','count','rows'].map(id=>[id,new Element()]));
const c={document:{getElementById:id=>elements[id],createElement:()=>new Element()},fetch:async()=>({ok:true,json:async()=>payload}),console};vm.createContext(c);vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],c);
async function run(){
 await new Promise(r=>setTimeout(r,0));assert.equal(elements.rows.children.length,payload.features.length);
 function check(min,tech='',status='',query=''){
  elements['min-mw'].value=min;elements.tech.value=tech;elements.status.value=status;elements.q.value=query;elements['min-mw'].events.input();
  const expected=payload.features.filter(f=>f.properties.mw>=Math.max(0,Number(min)||0)&&(!tech||f.properties.technology===tech)&&(!status||f.properties.status===status)&&JSON.stringify(f.properties).toLowerCase().includes(query.toLowerCase()));
  assert.equal(elements.rows.children.length,expected.length);
  assert(elements.count.textContent.startsWith(`${expected.length} от`));return expected;
 }
 check('');check('100');check('1.5','solar');check('0','solar','planned');check('100000');
 const belmeken=check('375','pumped_hydro','','Белмекен');assert.equal(belmeken.length,1);assert(belmeken[0].geometry);assert.equal(belmeken[0].properties.mw,375);
 const orfey=check('160','pumped_hydro','','Орфей');assert.equal(orfey.length,1);assert(orfey[0].geometry);
 check('');assert.equal(elements.rows.children.length,payload.features.length);
 assert.equal((mapHtml.match(/data-renewables-list(?:\s|>)/g)||[]).length,1);assert(/href="\.\/renewables.html"[^>]*data-renewables-list[^>]*>Лист ВЕИ<\/a>/.test(mapHtml));
 console.log('PASS: inclusive minimum MW filter, decimal threshold, combined filters, reset, merged hydro rows with coordinates, persistent Лист ВЕИ link.');
}
run().catch(e=>{console.error(e.message);process.exitCode=1;});
