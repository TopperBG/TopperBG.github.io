const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'map/assets/map-interface.js'),'utf8');
class Element{
 constructor(){this.children=[];this.attrs={};this.dataset={};this.hidden=false;this.tabIndex=undefined;}
 setAttribute(k,v){this.attrs[k]=String(v);}
 append(child){if(child.parent)child.parent.children=child.parent.children.filter(x=>x!==child);child.parent=this;this.children.push(child);}
 querySelectorAll(selector){assert.equal(selector,'[role="tab"]');return this.children.filter(x=>x.attrs.role==='tab');}
 click(){this.onclick();}
 focus(){this.focused=true;}
}
const version=new Element(),formerHeader=new Element();version.textContent='v'+JSON.parse(fs.readFileSync(path.join(root,'map/data/map-version.json'))).version;formerHeader.append(version);
const context={document:{createElement:()=>new Element()},layerContent:new Element(),legendContent:new Element(),q:selector=>{assert.equal(selector,'.bgwf-filter-version');return version;}};
vm.createContext(context);
vm.runInContext(source.slice(source.indexOf('  const tabs='),source.indexOf('  const controls=')),context);
const placement=source.match(/  const version=q\('\.bgwf-filter-version'\)[^\n]+/)[0];vm.runInContext(placement,context);
const tabs=version.parent;assert.equal(tabs.children.length,3);assert.equal(formerHeader.children.length,0);
assert.deepEqual(tabs.children.map(x=>x.textContent),['Слоеве','Легенда',version.textContent]);
const [layers,legend]=tabs.children;legend.click();assert.equal(context.layerContent.hidden,true);assert.equal(context.legendContent.hidden,false);
assert.equal(legend.attrs['aria-selected'],'true');assert.equal(layers.attrs['aria-selected'],'false');
assert.equal(version.attrs.role,undefined);assert.equal(version.attrs['aria-selected'],undefined);assert.equal(version.tabIndex,undefined);
for(const [key,target] of [['ArrowLeft',layers],['End',legend],['Home',layers]]){let prevented=false;legend.onkeydown({key,preventDefault(){prevented=true;}});assert(prevented);assert(target.focused);assert.equal(target.attrs['aria-selected'],'true');}
assert(!source.includes('footer.append(version)'));
console.log('PASS: version beside Слоеве/Легенда, unique placement, mouse/keyboard tab switching, version remains static text.');
