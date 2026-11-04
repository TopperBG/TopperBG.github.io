/* Personal notes never leave this browser except through an explicit export. */
(function(global){
  'use strict';
  const KEY='bgwf-personal-notes-v1', LIMIT=500;
  const keys=['solar','wind','projects','future','foreign','natura','epm','industry','kkkr'];
  const point=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)&&Math.abs(p[0])<=180&&Math.abs(p[1])<=85.051129;
  function normalize(raw){
    if(raw?.type!=='Feature'||raw.geometry?.type!=='Point'||!point(raw.geometry.coordinates))throw Error('Невалидна точка (GeoJSON longitude, latitude).');
    const p=raw.properties,s=p?.view;
    if(typeof p?.title!=='string'||!p.title.trim()||p.title.length>120||typeof p.text!=='string'||p.text.length>10000)throw Error('Невалидно заглавие или текст.');
    if(!s||!point(s.center)||!Number.isFinite(s.zoom)||s.zoom<0||s.zoom>30||!Number.isFinite(s.rotation)||typeof s.satellite!=='boolean'||!s.layers||!keys.every(k=>typeof s.layers[k]==='boolean')||!(s.years===null||Array.isArray(s.years)&&s.years.length<=100&&s.years.every(y=>Number.isInteger(y)&&y>=2000&&y<=2100)))throw Error('Липсва или е невалидна конфигурацията на картата.');
    return {type:'Feature',id:typeof raw.id==='string'&&raw.id.length<=100?raw.id:global.crypto.randomUUID(),geometry:{type:'Point',coordinates:[...raw.geometry.coordinates]},properties:{title:p.title.trim(),text:p.text,objectName:typeof p.objectName==='string'?p.objectName.slice(0,200):'',view:{center:[...s.center],zoom:s.zoom,rotation:s.rotation,satellite:s.satellite,layers:Object.fromEntries(keys.map(k=>[k,s.layers[k]])),years:s.years===null?null:[...new Set(s.years)]}}};
  }
  function decode(value){
    if(value?.type!=='FeatureCollection'||!Array.isArray(value.features)||value.features.length>LIMIT)throw Error('Очаква се GeoJSON с до 500 бележки, експортиран от картата.');
    const rows=value.features.map(normalize);
    if(new Set(rows.map(n=>n.id)).size!==rows.length)throw Error('Повтарящи се идентификатори в бележките.');
    return rows;
  }
  const collection=features=>({type:'FeatureCollection',schema:'bgwf-personal-notes-v1',features});
  function merge(existing,incoming){
    const rows=[...existing];
    for(const note of incoming){
      const same=rows.find(n=>n.id===note.id);
      if(same&&JSON.stringify(same)===JSON.stringify(note))continue;
      rows.push(same?{...note,id:global.crypto.randomUUID()}:note);
    }
    if(rows.length>LIMIT)throw Error('Максимум 500 бележки. Експортирайте архив и освободете място.');
    return rows;
  }
  function shareUrl(note,href){const url=new URL(href);url.search='';url.hash='note='+encodeURIComponent(JSON.stringify(normalize(note)));return url.href;}
  function sharedNote(hash){if(!hash.startsWith('#note='))return null;if(hash.length>150000)throw Error('Твърде дълга споделена бележка.');return normalize(JSON.parse(decodeURIComponent(hash.slice(6))));}
  global.bgwfNotesData={normalize,decode,collection,merge,shareUrl,sharedNote};
  global.setupBgwfNotes=function({root,map,capture,restore,closePanels}){
    const ol=global.ol;
    let rows=[],draft=null,selectedId=null,storageBlocked=false,savedRaw=null;
    const el=(tag,text,parent)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(parent)parent.append(n);return n;};
    const button=(text,parent,fn)=>{const n=el('button',text,parent);n.type='button';n.onclick=fn;return n;};
    const toolbar=root.querySelector('.bgwf-main-toolbar');
    const toggle=button('',toolbar,()=>{if(!panel.hidden){close();return;}if(!discard())return;draft=null;form.hidden=true;render();open();});toggle.dataset.uiNotes='';toggle.setAttribute('aria-label','Моите бележки');toggle.setAttribute('aria-controls','bgwf-notes-panel');toggle.setAttribute('aria-expanded','false');
    toggle.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor"><path d="M5 3h14v18l-7-4-7 4V3Z"/><path d="M9 8h6M9 12h6"/></svg><span>Бележки</span>';
    const panel=el('section',undefined,root.querySelector('.bgwf-map-wrap'));panel.id='bgwf-notes-panel';panel.className='bgwf-notes-panel';panel.hidden=true;panel.setAttribute('aria-label','Моите бележки');
    const header=el('header',undefined,panel);el('h2','Моите бележки',header);button('Затвори',header,close);
    el('p','Лични за този браузър. При изчистване на данните на сайта се губят. Експортирайте за резервно копие или друго устройство.',panel);
    const status=el('p','',panel);status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const actions=el('div',undefined,panel);actions.className='bgwf-notes-actions';
    button('Експорт',actions,()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify(collection(rows),null,2)],{type:'application/geo+json'}));
      const a=el('a');a.href=url;a.download='moi-belezhki.geojson';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
    const file=el('input',undefined,panel);file.type='file';file.accept='.geojson,.json,application/geo+json,application/json';file.hidden=true;
    button('Импорт',actions,()=>file.click());
    const form=el('form',undefined,panel);form.hidden=true;
    const label=el('label','Заглавие',form),title=el('input',undefined,label);title.required=true;title.maxLength=120;
    const textLabel=el('label','Моята информация',form),body=el('textarea',undefined,textLabel);body.maxLength=10000;body.rows=4;
    const coords=el('p','',form),config=el('p','',form);
    const save=el('button','Запази бележката',form);save.type='submit';
    button('Отказ',form,()=>{if(discard()){draft=null;form.hidden=true;render();}});
    const list=el('div',undefined,panel);list.className='bgwf-notes-list';
    const source=new ol.source.Vector();
    const layer=new ol.layer.Vector({source,zIndex:1000,style:new ol.style.Style({image:new ol.style.Circle({radius:8,fill:new ol.style.Fill({color:'#7c3aed'}),stroke:new ol.style.Stroke({color:'#fff',width:3})})})});map.addLayer(layer);
    function discard(){return !draft||global.confirm('Да се откажат незаписаните промени по бележката?');}
    function open(){closePanels();panel.hidden=false;toggle.setAttribute('aria-expanded','true');}
    function close(){if(!discard())return;draft=null;form.hidden=true;render();panel.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.focus();}
    function describe(){const v=draft.properties.view;coords.textContent=`LAT ${draft.geometry.coordinates[1].toFixed(6)} / LON ${draft.geometry.coordinates[0].toFixed(6)}`;config.textContent=(v.satellite?'Сателит':'Карта')+' · '+Object.entries(v.layers).filter(([,on])=>on).map(([key])=>({solar:'ФЕЦ',wind:'ВяЕЦ',projects:'Проектни ВЕИ',future:'RED III',foreign:'Чужди ВЕИ',natura:'Natura 2000',epm:'Електропреносна мрежа',industry:'Мини / кариери',kkkr:'Кадастър'})[key]).join(', ');}
    function edit(note){open();draft=JSON.parse(JSON.stringify(note));title.value=draft.properties.title;body.value=draft.properties.text;form.hidden=false;describe();render();title.focus();}
    function select(note){if(!discard())return;draft=null;form.hidden=true;selectedId=note.id;open();restore(note.properties.view);render();status.textContent='Избрана бележка: '+note.properties.title;}
    function persist(next){
      if(storageBlocked){status.textContent='Съхранението не е достъпно или има повредени данни. Нищо не е презаписано.';return false;}
      try{if(global.localStorage.getItem(KEY)!==savedRaw){storageBlocked=true;status.textContent='Бележките са променени в друг раздел. Презаредете страницата преди запис.';return false;}const serialized=JSON.stringify(collection(next));global.localStorage.setItem(KEY,serialized);savedRaw=serialized;rows=next;render();return true;}
      catch{status.textContent='Неуспешен запис: браузърът блокира съхранението или мястото е изчерпано. Текстът остава във формата.';return false;}
    }
    async function share(note){
      const url=shareUrl(note,global.location.href);
      try{if(global.navigator.share){await global.navigator.share({title:note.properties.title,url});return;}}catch(err){if(err.name==='AbortError')return;}
      try{await global.navigator.clipboard.writeText(url);status.textContent='Линкът към бележката е копиран. Съдържа текста, точката и изгледа.';}
      catch{global.prompt('Копирайте линка към бележката:',url);}
    }
    function render(){
      list.replaceChildren();source.clear();
      if(draft)source.addFeature(new ol.Feature({geometry:new ol.geom.Point(ol.proj.fromLonLat(draft.geometry.coordinates)),noteId:draft.id}));
      if(!rows.length)el('p','Още няма бележки. Десен клик върху картата → „Нова бележка“.',list);
      for(const n of rows){
        const feature=new ol.Feature({geometry:new ol.geom.Point(ol.proj.fromLonLat(n.geometry.coordinates)),noteId:n.id});source.addFeature(feature);
        const item=el('article',undefined,list);
        const choose=button(undefined,item,()=>select(n));choose.className='bgwf-note-select';choose.dataset.noteId=n.id;choose.setAttribute('aria-pressed',String(selectedId===n.id));
        el('strong',n.properties.title,choose);
        if(n.properties.objectName&&n.properties.objectName!==n.properties.title)el('small',n.properties.objectName,choose);
        el('small',`LAT ${n.geometry.coordinates[1].toFixed(6)} / LON ${n.geometry.coordinates[0].toFixed(6)}`,choose);
        el('span',n.properties.text,choose);
        const icons=el('div',undefined,item);icons.className='bgwf-note-icons';
        const send=button(undefined,icons,()=>share(n));send.setAttribute('aria-label','Споделяне на '+n.properties.title);send.title='Споделяне на бележката';
        send.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 10.5 6.8-4M8.6 13.5l6.8 4"/></svg>';
        const remove=button('×',icons,()=>{if(global.confirm('Да се изтрие бележката „'+n.properties.title+'“?')&&persist(rows.filter(r=>r.id!==n.id))){if(draft?.id===n.id){draft=null;form.hidden=true;}if(selectedId===n.id)selectedId=null;status.textContent='Бележката е изтрита.';}});
        remove.title='Изтриване на бележката';remove.setAttribute('aria-label','Изтриване на '+n.properties.title);
      }
    }
    form.onsubmit=e=>{e.preventDefault();if(!draft)return;try{
      const note=normalize({...draft,properties:{...draft.properties,title:title.value,text:body.value}});
      const next=rows.some(n=>n.id===note.id)?rows.map(n=>n.id===note.id?note:n):merge(rows,[note]);
      if(persist(next)){draft=null;form.hidden=true;render();status.textContent='Бележката е запазена в този браузър.';}
    }catch(err){status.textContent=err.message;}};
    file.onchange=async()=>{try{const f=file.files[0];if(!f)return;if(f.size>8000000)throw Error('Файлът е твърде голям (максимум 8 MB).');const imported=decode(JSON.parse(await f.text()));if(persist(merge(rows,imported)))status.textContent='Импортът приключи. Налични бележки: '+rows.length;}catch(err){status.textContent='Импортът не е записан. '+err.message;}finally{file.value='';}};
    try{savedRaw=global.localStorage.getItem(KEY);if(savedRaw)rows=decode(JSON.parse(savedRaw));}catch{storageBlocked=true;status.textContent='Локалните бележки не могат да бъдат прочетени. Данните няма да бъдат презаписани.';}
    render();
    global.addEventListener('storage',e=>{if(e.key===KEY||e.key===null){storageBlocked=true;status.textContent='Бележките са променени в друг раздел. Презаредете страницата, преди да записвате.';}});
    root.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){close();}});
    toolbar.addEventListener('click',e=>{if(!toggle.contains(e.target)&&!panel.hidden){panel.hidden=true;toggle.setAttribute('aria-expanded','false');}});
    function openShared(){
      try{const note=sharedNote(global.location?.hash||'');if(!note||!discard())return;
        note.id=global.crypto.randomUUID();restore(note.properties.view);edit(note);
        status.textContent='Споделена бележка. Натиснете „Запази бележката“, за да я добавите към своите.';
      }catch{open();status.textContent='Невалиден линк към бележка.';}
    }
    if(global.location?.hash?.startsWith('#note='))setTimeout(openShared,0);
    global.addEventListener('hashchange',openShared);
    return {createAt(coordinates,objectName=''){
      if(!discard()||!Array.isArray(coordinates))return;
      const p=[...coordinates];p[0]=((p[0]+180)%360+360)%360-180;
      if(!point(p))return;
      const state=capture();selectedId=null;
      edit({type:'Feature',id:global.crypto.randomUUID(),geometry:{type:'Point',coordinates:p},properties:{title:objectName.slice(0,120),objectName:objectName.slice(0,200),text:'',view:state}});
      status.textContent='Добавете заглавие и текст за избраната точка, после запазете.';
    },handleClick(e){
      const feature=map.forEachFeatureAtPixel(e.pixel,f=>f,{layerFilter:l=>l===layer,hitTolerance:7});
      if(feature){const n=rows.find(r=>r.id===feature.get('noteId'));if(n)select(n);return true;}return false;
    }};
  };
})(window);
