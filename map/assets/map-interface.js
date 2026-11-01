/* Map-first shell. Reuse the atlas controls and their original event handlers. */
window.setupBgwfInterface=function({root,map,setFilterPanelOpen,refreshFilterLayout,openAndFocusMethods,activeLayerCount}){
  const q=selector=>root.querySelector(selector);
  const paths={layers:'<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',list:'<path d="M8 5h13M8 12h13M8 19h13M3 5h1M3 12h1M3 19h1"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',base:'<path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2V5Zm6-2v16m6-14v16"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>'};
  const icon=key=>`<svg viewBox="0 0 24 24" aria-hidden="true">${paths[key]}</svg>`;
  const panel=q('.bgwf-floating-controls');panel.id='bgwf-layers-panel';panel.setAttribute('aria-label','Слоеве на картата');
  const wrap=q('.bgwf-map-wrap');
  const brand=q('.bgwf-brand');brand.innerHTML='<span class="bgwf-brand-mark" aria-hidden="true">◈</span><div><h1>ЕнергоКарта</h1><p>Б Ъ Л Г А Р И Я</p></div>';
  const toolbar=document.createElement('nav');toolbar.className='bgwf-main-toolbar';toolbar.setAttribute('aria-label','Управление на картата');wrap.append(toolbar);
  const layers=document.createElement('button');layers.type='button';layers.dataset.uiLayers='';layers.setAttribute('aria-controls',panel.id);layers.innerHTML=icon('layers')+'<span>Слоеве</span><sup data-active-layer-count></sup>';
  const searchButton=document.createElement('button');searchButton.type='button';searchButton.dataset.uiSearch='';searchButton.setAttribute('aria-controls','bgwf-search-panel');searchButton.setAttribute('aria-label','Търсене');searchButton.innerHTML=icon('search')+'<span>Търси</span>';
  const objects=q('[data-renewables-list]');objects.className='bgwf-toolbar-objects';objects.innerHTML=icon('list')+'<span>Обекти</span>';objects.setAttribute('aria-label','Отвори списъка с ВЕИ обекти');
  const info=q('[data-compact-info]');info.className='bgwf-toolbar-info';info.innerHTML=icon('info')+'<span>Info</span>';
  const base=q('[data-layer="satellite"]');base.className='bgwf-toolbar-base';base.setAttribute('aria-label','Превключи карта / сателит');base.innerHTML=icon('base')+'<span data-base-label>Основа</span>';
  toolbar.append(layers,searchButton,objects,info,base);
  const closePanel=q('[data-mobile-filter-toggle]');closePanel.querySelector('strong').textContent='Слоеве на картата';
  closePanel.querySelector('.bgwf-filter-chevron').innerHTML=icon('close');
  q('.bgwf-search-icon').innerHTML=icon('search');
  const search=q('[data-map-search]');search.id='bgwf-search-panel';search.classList.add('bgwf-search-panel');wrap.append(search);
  const closeSearch=document.createElement('button');closeSearch.type='button';closeSearch.className='bgwf-search-dismiss';closeSearch.setAttribute('aria-label','Затвори търсенето');closeSearch.innerHTML=icon('close');search.append(closeSearch);
  q('.bgwf-search-strip').remove();
  q('.bgwf-mobile-filter-body').append(q('[data-territory-scale-bars]'));
  // Info is a modal, so it never expands the map's layout or opens the layers.
  const dialog=document.createElement('dialog');dialog.className='bgwf-info-dialog';dialog.dataset.infoDialog='';dialog.setAttribute('aria-labelledby','bgwf-info-title');
  dialog.innerHTML='<div class="bgwf-dialog-heading"><h2 id="bgwf-info-title">Методика и източници</h2><button type="button" data-info-close aria-label="Затвори информацията">'+icon('close')+'</button></div>';
  dialog.append(q('[data-mobile-footer]'));root.append(dialog);
  q('[data-mobile-footer]').open=true;q('[data-method-note]').open=true;
  q('[data-info-close]').onclick=()=>dialog.close();
  dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();});
  const detail=q('.bgwf-detail');const closeDetail=document.createElement('button');closeDetail.type='button';closeDetail.className='bgwf-detail-close';closeDetail.setAttribute('aria-label','Затвори информацията за обекта');closeDetail.innerHTML=icon('close');detail.append(closeDetail);
  closeDetail.onclick=()=>detail.classList.add('is-hint');
  const mobile=()=>matchMedia('(max-width:700px), (max-height:600px) and (hover:none), (max-width:950px) and (max-height:600px)').matches;
  const closeLayers=()=>{setFilterPanelOpen(false);refreshFilterLayout();};
  const closeSearchPanel=()=>{root.classList.remove('is-search-open');q('[data-map-search-results]').hidden=true;searchButton.setAttribute('aria-expanded','false');q('[data-map-search-input]').setAttribute('aria-expanded','false');};
  layers.onclick=()=>{closeSearchPanel();setFilterPanelOpen(!panel.classList.contains('is-filter-open'));refreshFilterLayout();};
  searchButton.onclick=()=>{const open=!root.classList.contains('is-search-open');if(mobile())closeLayers();root.classList.toggle('is-search-open',open);searchButton.setAttribute('aria-expanded',String(open));if(open)q('[data-map-search-input]').focus();else closeSearchPanel();};
  info.addEventListener('click',closeSearchPanel);
  closeSearch.onclick=()=>{closeSearchPanel();searchButton.focus();};
  search.addEventListener('click',event=>{if(event.target.closest('.bgwf-search-result')){closeSearchPanel();if(mobile())closeLayers();}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){if(root.classList.contains('is-search-open')){closeSearchPanel();searchButton.focus();}else if(panel.classList.contains('is-filter-open')&&!dialog.open){closeLayers();layers.focus();}}});
  wrap.addEventListener('pointerdown',event=>{if(event.target.closest('.bgwf-ol-map')){closeSearchPanel();if(mobile()&&panel.classList.contains('is-filter-open'))closeLayers();}});
  const sync=()=>{
    const count=activeLayerCount(),badge=q('[data-active-layer-count]'),open=panel.classList.contains('is-filter-open');
    if(badge.textContent!==String(count))badge.textContent=String(count);
    const label=`Слоеве: ${count} активни`;if(layers.getAttribute('aria-label')!==label)layers.setAttribute('aria-label',label);
    if(layers.getAttribute('aria-expanded')!==String(open))layers.setAttribute('aria-expanded',String(open));
    const mode=base.getAttribute('aria-pressed')==='true'?'Сателит':'Карта';if(q('[data-base-label]').textContent!==mode)q('[data-base-label]').textContent=mode;
  };
  new MutationObserver(sync).observe(root,{subtree:true,attributes:true,attributeFilter:['aria-pressed','class']});
  let wasMobile=mobile();window.addEventListener('resize',()=>{const isMobile=mobile();if(isMobile!==wasMobile){setFilterPanelOpen(!isMobile);closeSearchPanel();wasMobile=isMobile;}sync();});
  // Native OpenLayers scale responds to resolution and latitude, including pinch zoom.
  map.addControl(new ol.control.ScaleLine({units:'metric',minWidth:70}));
  map.getControls().forEach(control=>{if(control instanceof ol.control.Attribution)control.setCollapsible(false);});
  const osm='<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>';
  for(const layer of map.getLayers().getArray()){
    const source=layer.getSource?.(),attributions=source?.getAttributions?.();
    if(!attributions)continue;
    source.setAttributions(frame=>[...new Set([].concat(attributions(frame)||[],osm))]);
  }
  sync();
};
