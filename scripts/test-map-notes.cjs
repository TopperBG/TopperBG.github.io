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
 const window={crypto:{randomUUID:()=>`note-${++id}`},confirm:()=>true,addEventListener:(k,f)=>events[k]=f,localStorage:{getItem:()=>value,setItem:(k,v)=>{if(fail)throw Error('quota');value=v;}},ol:{source:{Vector:Source},layer:{Vector:stub},style:{Style:stub,Circle:stub,Fill:stub,Stroke:stub},Feature,geom:{Point:stub},proj:{fromLonLat:p=>p,toLonLat:p=>p}}};
 const context={window,document:{createElement:t=>new Element(t),body:new Element('body')},URL,Blob,setTimeout};vm.runInNewContext(fs.readFileSync('map/assets/map-notes.js','utf8'),context);
 const controller=window.setupBgwfNotes({root,map,capture:()=>structuredClone(state),restore:s=>restored=s,closePanels(){}});
 const find=text=>all(root).find(n=>n.tag==='button'&&n.textContent===text);
 const panel=wrap.children[0],form=all(root).find(n=>n.tag==='form');
 const input=all(form).find(n=>n.tag==='input'),text=all(form).find(n=>n.tag==='textarea');
 const status=all(root).find(n=>n.attrs.role==='status');
 return {root,map,controller,find,panel,form,input,text,status,window,state,events,get value(){return value;},get restored(){return restored;},set fail(v){fail=v;}};
}
const s=setup();s.find('Нова точка').click();assert(s.controller.isPicking());
assert(s.controller.handleClick({coordinate:[23.6,43.1],pixel:{}}));assert(!s.controller.isPicking());
s.input.value='Върбешница';s.text.value='<img src=x onerror=alert(1)> 4 кариери';s.form.onsubmit({preventDefault(){}});
let data=JSON.parse(s.value);assert.equal(data.features.length,1);assert(Math.abs(data.features[0].geometry.coordinates[0]-23.6)<1e-10);assert.equal(data.features[0].geometry.coordinates[1],43.1);assert.deepEqual(data.features[0].properties.view,s.state);
assert.equal(s.map.layers[0].source.features.length,1);
const reload=setup(s.value);assert.equal(reload.map.layers[0].source.features.length,1);reload.find('Отвори изгледа').click();assert.deepEqual(JSON.parse(JSON.stringify(reload.restored)),s.state);
reload.find('Редактирай').click();reload.text.value='Променен текст';reload.fail=true;reload.form.onsubmit({preventDefault(){}});assert.equal(reload.text.value,'Променен текст');assert.match(reload.status.textContent,/Неуспешен/);assert.equal(JSON.parse(reload.value).features[0].properties.text,s.text.value);
reload.fail=false;reload.form.onsubmit({preventDefault(){}});assert.equal(JSON.parse(reload.value).features[0].properties.text,'Променен текст');reload.find('Изтрий').click();assert.equal(JSON.parse(reload.value).features.length,0);
const api=s.window.bgwfNotesData;
assert.equal(api.decode(data).length,1);assert.equal(api.merge(api.decode(data),api.decode(data)).length,1);
const changed=structuredClone(data);changed.features[0].properties.text='Other';assert.equal(api.merge(api.decode(data),api.decode(changed)).length,2);
for(const mutate of [d=>d.features[0].geometry.coordinates=[200,43],d=>delete d.features[0].properties.view,d=>d.features[0].properties.view.layers.solar='yes',d=>d.features[0].properties.view.zoom=null,d=>d.features.push(d.features[0])]){const bad=structuredClone(data);mutate(bad);assert.throws(()=>api.decode(bad));}
const corrupt=setup('{bad');corrupt.find('Нова точка').click();corrupt.controller.handleClick({coordinate:[24,43]});corrupt.input.value='test';corrupt.form.onsubmit({preventDefault(){}});assert.equal(corrupt.value,'{bad');assert.match(corrupt.status.textContent,/не е презаписано/);
s.events.storage({key:'bgwf-personal-notes-v1'});assert.match(s.status.textContent,/друг раздел/);
const index=fs.readFileSync('map/index.html','utf8');assert(index.includes('if(notesController?.handleClick(e))'));assert(index.includes('view.setRotation(state.rotation)'));
for(const m of index.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)){if(m[1].trim()&&!m[0].includes('application/ld+json'))new vm.Script(m[1]);}
console.log('PASS notes: creation, reload, state restore, safe text, edit/delete, quota failure, import validation/merge, corrupted storage, multi-tab warning, map syntax');

(async()=>{
 const imported=setup(),file=all(imported.root).find(n=>n.type==='file');
 file.files=[{size:100,text:async()=>JSON.stringify(data)}];await file.onchange();assert.equal(JSON.parse(imported.value).features.length,1);
 await file.onchange();assert.equal(JSON.parse(imported.value).features.length,1);
 const before=imported.value;file.files=[{size:100,text:async()=>'{bad'}];await file.onchange();assert.equal(imported.value,before);assert.match(imported.status.textContent,/не е записан/);
 imported.root.children[0].children[0].click();imported.find('Нова точка').click();imported.root.listeners.keydown({key:'Escape'});assert(!imported.controller.isPicking());
 assert(all(s.root).some(n=>n.tag==='p'&&n.textContent===s.text.value));
 console.log('PASS import UI: valid file, repeat import, invalid JSON leaves data intact; Escape cancels point; user HTML remains text');
})().catch(e=>{console.error(e);process.exitCode=1;});
