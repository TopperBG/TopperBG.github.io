/* Regression tests against the same OpenLayers build as the map.
   Usage: node scripts/test-renewable-map.cjs /path/to/ol-10.10.0.js */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
async function main(){
  const root=path.resolve(__dirname,'..'),html=fs.readFileSync(path.join(root,'map/index.html'),'utf8');
  const c={console,navigator:{userAgent:''},TextEncoder,TextDecoder,URL,URLSearchParams,setTimeout,clearTimeout};
  vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),c);
  const ol=c.ol;
  Object.assign(c,{VectorSource:ol.source.Vector,VectorLayer:ol.layer.Vector,Style:ol.style.Style,CircleStyle:ol.style.Circle,Fill:ol.style.Fill,Stroke:ol.style.Stroke,TextStyle:ol.style.Text,
    solarSource:new ol.source.Vector(),projectSource:new ol.source.Vector(),windSource:new ol.source.Vector(),layerVisibility:{solar:true,wind:true,projects:true},satelliteMode:()=>false,cssVar:(_k,v)=>v,haloPolygonStyles:()=>[],map:{addLayer(){}},view:{getResolution:()=>1},window:{},document:{createElement:()=>({})},root:{querySelector:()=>({appendChild(){}})},dbgWarn:(name,e)=>{throw Error(name+JSON.stringify(e));},cloneGeoFeature:raw=>new ol.format.GeoJSON().readFeature(raw,{featureProjection:'EPSG:3857'})});
  for(const name of ['operatingSolarProjects','operatingWindProjects','cadastralProjects','CURATED_SOLAR_FOOTPRINTS']){
    const m=html.match(new RegExp('const\\s+'+name+'\\s*=\\s*(\\[[\\s\\S]*?\\n\\s*\\]);'));
    c[name]=vm.runInNewContext('('+m[1]+')');
  }
  vm.runInContext(html.slice(html.indexOf('  const LARGE_SOLAR_THRESHOLD_MWP'),html.indexOf('  function hasSolarMapGeometry')),c);
  assert(!c.meetsRenewableMapThreshold({mw:9.99}));assert(c.meetsRenewableMapThreshold({mw:10}));assert(!c.meetsRenewableMapThreshold(c.operatingSolarProjects.find(p=>p.id==='SOL-2012-MARINO-POLE-ALFA')));
  Object.assign(c,{debugState:{layerCounts:{}},veiDbgStage(){},updateLayerStatus(){},Feature:ol.Feature,Point:ol.geom.Point,CircleGeom:ol.geom.Circle,fromLonLat:ol.proj.fromLonLat});
  vm.runInContext(html.slice(html.indexOf('function renderParcelRows(loaded){'),html.indexOf('async function fetchRowsInBatches')),c);
  c.renderParcelRows([9.99,10].map(mw=>({layerType:'solar',project:{id:'threshold-'+mw,mw},feature:pointGeometry(mw)})));
  function pointGeometry(mw){return {type:'Feature',properties:{},geometry:{type:'Point',coordinates:[24,mw===10?42:43]}};}
  for(const f of [...c.solarSource.getFeatures(),...c.projectSource.getFeatures()])assert(c.meetsRenewableMapThreshold(f.get('data').project));
  assert(c.solarSource.getFeatures().some(f=>f.get('data').project.id==='threshold-10'));
  assert(!c.solarSource.getFeatures().some(f=>f.get('data').project.id==='threshold-9.99'));
  c.solarSource.clear();c.projectSource.clear();
  c.windLayer=new ol.layer.Vector({source:c.windSource});
  vm.runInContext(html.slice(html.indexOf('const projectLayer=new VectorLayer({'),html.indexOf('const windLayer=new VectorLayer({')),c);
  const payload=JSON.parse(fs.readFileSync(path.join(root,'map/data/bg-renewables-cache-v1.geojson')));
  function point(id,tech,xy,mw=10){return {type:'Feature',id,properties:{id,name:id,technology:tech,mw,status:'operating',source:'https://example.org/'+id,geometryQuality:'location-only'},geometry:{type:'Point',coordinates:xy}};}
  const fixtures=[point('inside-late','solar',[24,42]),point('outside','solar',[24.2,42.2]),point('hole','solar',[24.05,42.05]),point('multi','solar',[24.42,42.42]),point('hydro-fixture','hydro',[24.2,42.2]),point('bio-fixture','biomass',[24.2,42.2]),point('identity-fixture','solar',[24.2,42.2])];
  fixtures.unshift(point('under-ten','solar',[24.2,42.2],9.99),point('small-wind','wind',[24.2,42.2],2));
  fixtures.at(-1).properties.source='https://www.openstreetmap.org/way/123456789012';
  c.CURATED_SOLAR_FOOTPRINTS.push({id:'known-identity',source:'https://example.org/other',parcelRef:'OSM-W123456789012',geometry:{type:'Polygon',coordinates:[[[23,43],[23.01,43],[23.01,43.01],[23,43.01],[23,43]]]}});
  c.fetch=async()=>({ok:true,json:async()=>({...payload,features:[...payload.features,...fixtures]})});
  const start=html.indexOf('// The inventory retains every technology;');
  vm.runInContext(html.slice(start,html.indexOf('// Load status wiring:',start))+'\nvoid loadRenewableCache();'+'\nglobalThis.cacheSource=renewableCacheSource;globalThis.cacheLayer=renewableCacheLayer;',c);
  await new Promise(r=>setTimeout(r,0));
  const has=id=>!!c.cacheSource.getFeatureById(id);
  assert(!has('under-ten'));assert(!has('small-wind'));assert(has('inside-late'));assert(has('outside'));assert(!has('hydro-fixture'));assert(!has('bio-fixture'));assert(!has('identity-fixture'));
  assert.equal(c.window.bgwfRenewableInventory.features.length,payload.features.length+fixtures.length,'Inventory retains all technologies');
  for(const id of ['OSM-BG-W157097156','OSM-BG-W320537211','OSM-BG-W469655230'])assert(!has(id),'Known solar footprint replaces '+id);
  function addPolygon(geometry){c.solarSource.addFeature(c.cloneGeoFeature({type:'Feature',properties:{},geometry}));}
  addPolygon({type:'Polygon',coordinates:[[[23.99,41.99],[24.1,41.99],[24.1,42.1],[23.99,42.1],[23.99,41.99]],[[24.04,42.04],[24.06,42.04],[24.06,42.06],[24.04,42.06],[24.04,42.04]]]});
  addPolygon({type:'MultiPolygon',coordinates:[[[[24.4,42.4],[24.45,42.4],[24.45,42.45],[24.4,42.45],[24.4,42.4]]]]});
  await new Promise(r=>setTimeout(r,10));
  assert(!has('inside-late'),'Delayed polygon removes overlapping marker');assert(!has('multi'));assert(has('hole'),'A point in a polygon hole must survive');assert(has('outside'),'A nearby distinct site must survive');
  c.solarSource.clear();await new Promise(r=>setTimeout(r,10));assert(has('inside-late'),'Point returns when its polygon is removed');
  for(const f of c.cacheSource.getFeatures()){
    const p=f.get('data').project;assert(p.mw>=10);assert(['solar','wind'].includes(p.technology));
    const k=p.status==='operating'?(p.technology==='wind'?'wind':'solar'):'projects';assert(c.cacheLayer.getStyleFunction()(f,1));c.layerVisibility[k]=false;assert.equal(c.cacheLayer.getStyleFunction()(f,1),null);c.layerVisibility[k]=true;
  }
  const makeFeature=mw=>{const f=new ol.Feature(new ol.geom.Point([0,0]));f.set('data',{project:{mw}});return f;};
  const solar=vm.runInContext('solarLayer',c),project=vm.runInContext('projectLayer',c);
  const small=solar.getStyleFunction()(makeFeature(1.1),1)[1].getImage().getRadius(),large=solar.getStyleFunction()(makeFeature(100),1)[1].getImage().getRadius();
  assert(small<3);assert(large>small);assert(large<=7);assert(project.getStyleFunction()(makeFeature(1.1),1).getImage().getRadius()<3);
  console.log('PASS: solar/wind-only mapping; inventory preservation; OSM aliases; delayed polygons, holes, multipolygons; nearby separate site; capacity-scaled small markers.');
  console.log('Actual cache:',payload.features.length,'inventory records;',c.cacheSource.getFeatures().length-fixtures.filter(f=>has(f.id)).length,'additional mapped records after filtering.');
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
