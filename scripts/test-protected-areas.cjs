const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'map/index.html'),'utf8');
const data=JSON.parse(fs.readFileSync(path.join(root,'map/data/protected-areas-bg-v1.geojson'),'utf8'));
assert.equal(data.features.length,data.metadata.featureCount);
assert(data.features.length>=1000);
assert.equal(new Set(data.features.map(f=>f.id)).size,data.features.length);
for(const f of data.features){assert(['Polygon','MultiPolygon'].includes(f.geometry.type));assert(f.properties.NameBg);assert(f.properties.categoryLabel);assert(f.properties.registerUrl.startsWith('https://eea.government.bg/zpo/bg/'));assert(!('k' in f.properties));}
const c={console,navigator:{userAgent:''},TextEncoder,TextDecoder,URL,URLSearchParams,setTimeout,clearTimeout};vm.createContext(c);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),c);
let calls=0,fail=false;
Object.assign(c,{protectedSource:new c.ol.source.Vector(),readFeatures:d=>new c.ol.format.GeoJSON().readFeatures(d,{featureProjection:'EPSG:3857'}),fetch:async()=>{calls++;if(fail)throw Error('offline');return {ok:true,json:async()=>data};},setLayerLoadState(){},updateLayerStatus(){},debugState:{layerCounts:{}},dbgWarn(){}});
const code=html.slice(html.indexOf("let protectedLoadState='idle'"),html.indexOf('// ---------- Natura 2000 (official'));
vm.runInContext(code,c);
(async()=>{
 const [a,b]=await Promise.all([c.ensureProtectedAreas(),c.ensureProtectedAreas()]);assert.equal(calls,1);assert.equal(a,b);assert.equal(a.length,data.features.length);assert(a.every(f=>f.get('kind')==='protected'));assert(a.every(f=>f.getGeometry().getExtent().every(Number.isFinite)));
 await c.ensureProtectedAreas();assert.equal(calls,1);
 vm.runInContext("protectedLoadState='idle'",c);fail=true;await assert.rejects(c.ensureProtectedAreas(),/offline/);assert.equal(vm.runInContext('protectedLoadState',c),'error');fail=false;await c.ensureProtectedAreas();assert.equal(vm.runInContext('protectedLoadState',c),'ready');assert.equal(c.protectedSource.getFeatures().length,data.features.length);
 console.log('PASS: official snapshot, unique identities, register links, OpenLayers geometry parsing, concurrent loading, cached reuse, failure and retry.');
})().catch(e=>{console.error(e);process.exitCode=1;});
