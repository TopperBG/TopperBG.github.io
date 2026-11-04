const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const crypto=require('node:crypto');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.dataset={};this.style={};this.listeners={};this.hidden=false;this.value='';this.classList={remove(){}};}
 append(...nodes){this.children.push(...nodes);for(const n of nodes)if(typeof n==='object')n.parent=this;}
 setAttribute(k,v){this.attrs[k]=v;}
 addEventListener(k,f){this.listeners[k]=f;}
 replaceChildren(){this.children=[];}
 focus(){} remove(){} click(){this.onclick?.({target:this});}
 contains(n){return this===n||this.children.some(c=>c.contains?.(n));}
}
const all=(n)=>[n,...n.children.flatMap(c=>typeof c==='object'?all(c):[])];
function setup(saved=null){
 const root=new Element('root'),toolbar=new Element('nav'),wrap=new Element('wrap');root.append(toolbar,wrap);
 root.querySelector=s=>s==='.bgwf-main-toolbar'?toolbar:wrap;
 let value=saved,fail=false,restored=null,id=0;
 const events={},target=new Element('map');
 const map={layers:[],addLayer(l){this.layers.push(l);},getTargetElement:()=>target,forEachFeatureAtPixel(pixel,fn,opts){return pixel?.feature&&opts.layerFilter(this.layers[0])?fn(pixel.feature):null;}};
 const state={center:[23.7,43.2],zoom:12,rotation:0,satellite:true,layers:Object.fromEntries(['solar','wind','projects','future','foreign','natura','epm','industry','kkkr'].map(k=>[k,['solar','natura'].includes(k)])),years:[2026]};
 class Source{constructor(){this.features=[];}clear(){this.features=[];}addFeature(f){this.features.push(f);}}
 class Feature{constructor(p){this.p=p;}get(k){return this.p[k];}}
 const stub=class{constructor(p){Object.assign(this,p);}};
 const window={crypto:{randomUUID:()=>crypto.randomUUID()},confirm:()=>true,addEventListener:(k,f)=>events[k]=f,localStorage:{getItem:()=>value,setItem:(k,v)=>{if(fail)throw Error('quota');value=v;}},ol:{source:{Vector:Source},layer:{Vector:stub},style:{Style:stub,Circle:stub,Fill:stub,Stroke:stub},Feature,geom:{Point:stub},proj:{fromLonLat:p=>p,toLonLat:p=>p}}};
 const context={window,document:{createElement:t=>new Element(t),body:new Element('body')},URL,Blob,setTimeout};vm.runInNewContext(fs.readFileSync('map/assets/map-notes.js','utf8'),context);
 const controller=window.setupBgwfNotes({root,map,capture:()=>structuredClone(state),restore:s=>restored=s,closePanels(){}});
 const find=text=>all(root).find(n=>n.tag==='button'&&n.textContent===text);
 const panel=wrap.children[0],form=all(root).find(n=>n.tag==='form');
 const input=all(form).find(n=>n.tag==='input'),text=all(form).find(n=>n.tag==='textarea');
 const status=all(root).find(n=>n.attrs.role==='status');
 return {root,map,controller,find,panel,form,input,text,status,window,state,events,get value(){return value;},get restored(){return restored;},set fail(v){fail=v;}};
}
const s=setup();assert.equal(s.find('Нова точка'),undefined);assert.equal(s.controller.handleClick({pixel:{}}),false);s.controller.createAt([23.6,43.1]);assert.equal(s.form.hidden,false);
s.input.value='Върбешница';s.text.value='<img src=x onerror=alert(1)> 4 кариери';s.form.onsubmit({preventDefault(){}});
let data=JSON.parse(s.value);assert.equal(data.features.length,1);assert(Math.abs(data.features[0].geometry.coordinates[0]-23.6)<1e-10);assert.equal(data.features[0].geometry.coordinates[1],43.1);assert.deepEqual(data.features[0].properties.view,s.state);
assert.equal(s.map.layers[0].source.features.length,1);
const reload=setup(s.value);assert.equal(reload.map.layers[0].source.features.length,1);all(reload.root).find(n=>n.dataset.noteId).click();assert.equal(reload.form.hidden,true);assert.deepEqual(JSON.parse(JSON.stringify(reload.restored)),s.state);
reload.controller.createAt([24,43]);reload.input.value='Втора бележка';reload.text.value='Променен текст';reload.fail=true;reload.form.onsubmit({preventDefault(){}});assert.equal(reload.text.value,'Променен текст');assert.match(reload.status.textContent,/Неуспешен/);assert.equal(JSON.parse(reload.value).features[0].properties.text,s.text.value);
reload.fail=false;reload.form.onsubmit({preventDefault(){}});assert.equal(JSON.parse(reload.value).features[1].properties.text,'Променен текст');reload.find('×').click();assert.equal(JSON.parse(reload.value).features.length,1);assert.equal(JSON.parse(reload.value).features[0].properties.title,'Втора бележка');
const api=s.window.bgwfNotesData;
assert.equal(api.decode(data).length,1);assert.equal(api.merge(api.decode(data),api.decode(data)).length,1);
const changed=structuredClone(data);changed.features[0].properties.text='Other';assert.equal(api.merge(api.decode(data),api.decode(changed)).length,2);
for(const mutate of [d=>d.features[0].geometry.coordinates=[200,43],d=>delete d.features[0].properties.view,d=>d.features[0].properties.view.layers.solar='yes',d=>d.features[0].properties.view.zoom=null,d=>d.features.push(d.features[0])]){const bad=structuredClone(data);mutate(bad);assert.throws(()=>api.decode(bad));}
const corrupt=setup('{bad');corrupt.controller.createAt([24,43]);corrupt.input.value='test';corrupt.form.onsubmit({preventDefault(){}});assert.equal(corrupt.value,'{bad');assert.match(corrupt.status.textContent,/не е презаписано/);
s.events.storage({key:'bgwf-personal-notes-v1'});assert.match(s.status.textContent,/друг раздел/);
const index=fs.readFileSync('map/index.html','utf8');assert(index.includes('if(notesController?.handleClick(e))'));assert(index.includes('view.setRotation(state.rotation)'));
for(const m of index.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)){if(m[1].trim()&&!m[0].includes('application/ld+json'))new vm.Script(m[1]);}
console.log('PASS notes: creation, reload, state restore, safe text, select/delete, quota failure, import validation/merge, corrupted storage, multi-tab warning, map syntax');

(async()=>{
 const imported=setup(),file=all(imported.root).find(n=>n.type==='file');
 file.files=[{size:100,text:async()=>JSON.stringify(data)}];await file.onchange();assert.equal(JSON.parse(imported.value).features.length,1);
 await file.onchange();assert.equal(JSON.parse(imported.value).features.length,1);
 const before=imported.value;file.files=[{size:100,text:async()=>'{bad'}];await file.onchange();assert.equal(imported.value,before);assert.match(imported.status.textContent,/не е записан/);
 imported.controller.createAt([25,43]);imported.root.listeners.keydown({key:'Escape'});assert.equal(imported.panel.hidden,true);
 assert(all(s.root).some(n=>n.tag==='span'&&n.textContent===s.text.value));
 console.log('PASS import UI: valid file, repeat import, invalid JSON leaves data intact; Escape closes new-note form; user HTML remains text');
})().catch(e=>{console.error(e);process.exitCode=1;});


assert(index.includes('data-action="note">Нова бележка'));
assert(index.includes('notesController?.createAt(mapContextLonLat,mapContextObjectName)'));
assert(!index.includes('notesController?.isPicking'));
const selected=all(s.root).find(n=>n.dataset.noteId);selected.click();assert.equal(all(s.root).find(n=>n.dataset.noteId).attrs['aria-pressed'],'true');
assert(s.controller.handleClick({pixel:{feature:s.map.layers[0].source.features[0]}}));assert.equal(s.form.hidden,true);
console.log('PASS context-menu entry, exact clicked coordinates, list selection, selected state, marker selection and no point-picking mode');

const shareNote=api.normalize({...data.features[0],properties:{...data.features[0].properties,objectName:'ФЕЦ Тест'}});
const link=api.shareUrl(shareNote,'https://topperbg.github.io/map/?solar=0#s=old');
assert.equal(new URL(link).search,'');assert.deepEqual(JSON.parse(JSON.stringify(api.sharedNote(new URL(link).hash))),JSON.parse(JSON.stringify(shareNote)));
assert.throws(()=>api.sharedNote('#note=invalid'));
const named=setup();named.controller.createAt([25,43],'ФЕЦ Тест');assert.equal(named.input.value,'ФЕЦ Тест');named.form.onsubmit({preventDefault(){}});assert.equal(JSON.parse(named.value).features[0].properties.objectName,'ФЕЦ Тест');
assert(all(named.root).some(n=>n.attrs['aria-label']==='Споделяне на ФЕЦ Тест'));assert(named.find('×'));
console.log('PASS share link roundtrip with Cyrillic, text, coordinates, layers and object name; icon actions');

(async()=>{
 const owner=setup(s.value);let copied='';owner.window.location={href:'https://topperbg.github.io/map/'};owner.window.navigator={clipboard:{writeText:async text=>{copied=text;}}};
 await all(owner.root).find(n=>n.attrs['aria-label']?.startsWith('Споделяне на')).onclick();
 assert(copied.includes('#note='));const recipient=setup();recipient.window.location={hash:new URL(copied).hash};recipient.events.hashchange();
 assert.equal(recipient.form.hidden,false);assert.equal(recipient.input.value,'Върбешница');assert.equal(recipient.value,null);assert.deepEqual(JSON.parse(JSON.stringify(recipient.restored)),s.state);
 recipient.form.onsubmit({preventDefault(){}});assert.equal(JSON.parse(recipient.value).features.length,1);assert.equal(recipient.map.layers[0].source.features.length,1);
 console.log('PASS share icon copies link; recipient previews without automatic save; explicit save persists and removes draft marker');
})().catch(e=>{console.error(e);process.exitCode=1;});
