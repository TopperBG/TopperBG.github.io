/* Map-first shell. Reuse the atlas controls and their original event handlers. */
window.setupBgwfInterface=function({root,map,setFilterPanelOpen,refreshFilterLayout,openAndFocusMethods,activeLayerCount}){
  const q=selector=>root.querySelector(selector);
  const paths={layers:'<path d="m12 3 9 5-9 5-9-5 9-5Zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',list:'<path d="M8 5h13M8 12h13M8 19h13M3 5h1M3 12h1M3 19h1"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',base:'<path d="m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2V5Zm6-2v16m6-14v16"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>'};
  const icon=key=>`<svg viewBox="0 0 24 24" aria-hidden="true">${paths[key]}</svg>`;
  const panel=q('.bgwf-floating-controls');panel.id='bgwf-layers-panel';panel.setAttribute('aria-label','Слоеве на картата');
  const wrap=q('.bgwf-map-wrap');
  q('.bgwf-brand')?.remove();
  const toolbar=document.createElement('nav');toolbar.className='bgwf-main-toolbar';toolbar.setAttribute('aria-label','Управление на картата');wrap.append(toolbar);
  const layers=document.createElement('button');layers.type='button';layers.dataset.uiLayers='';layers.setAttribute('aria-controls',panel.id);layers.innerHTML=icon('layers')+'<span>Слоеве</span><sup data-active-layer-count></sup>';
  const searchButton=document.createElement('button');searchButton.type='button';searchButton.dataset.uiSearch='';searchButton.setAttribute('aria-controls','bgwf-search-panel');searchButton.setAttribute('aria-label','Търсене');searchButton.setAttribute('aria-expanded','false');searchButton.innerHTML=icon('search')+'<span>Търси</span>';
  const objects=q('[data-renewables-list]');objects.className='bgwf-toolbar-objects';objects.innerHTML=icon('list')+'<span>Обекти</span>';objects.setAttribute('aria-label','Отвори списъка с ВЕИ обекти');
  const info=q('[data-compact-info]');info.className='bgwf-toolbar-info';info.innerHTML=icon('info')+'<span>Info</span>';
  const base=q('[data-layer="satellite"]');base.className='bgwf-toolbar-base';base.setAttribute('aria-label','Превключи карта / сателит');base.innerHTML=icon('base')+'<span data-base-label>Основа</span>';
  toolbar.append(layers,searchButton,objects,info,base);
  const closePanel=q('[data-mobile-filter-toggle]');closePanel.querySelector('strong').textContent='Какво да видиш?';
  const eyebrow=document.createElement('small');eyebrow.className='bgwf-panel-eyebrow';eyebrow.textContent='ИЗСЛЕДВАЙ БЪЛГАРИЯ';panel.prepend(eyebrow);
  closePanel.querySelector('.bgwf-filter-chevron').innerHTML=icon('close');
  q('.bgwf-search-icon').innerHTML=icon('search');
  const search=q('[data-map-search]');search.id='bgwf-search-panel';search.classList.add('bgwf-search-panel');wrap.append(search);
  const closeSearch=document.createElement('button');closeSearch.type='button';closeSearch.className='bgwf-search-dismiss';closeSearch.setAttribute('aria-label','Затвори търсенето');closeSearch.innerHTML=icon('close');search.append(closeSearch);
  q('.bgwf-search-strip').remove();
  // Preserve real controls and their handlers while restoring the mockup's hierarchy.
  const body=q('.bgwf-mobile-filter-body'),layerStrip=q('.bgwf-layer-strip'),fireStrip=q('.bgwf-year-strip');
  const layerContent=document.createElement('div');layerContent.id='bgwf-layer-content';layerContent.className='bgwf-layer-content';
  const legendContent=document.createElement('div');legendContent.id='bgwf-legend-content';legendContent.className='bgwf-legend-content';legendContent.hidden=true;
  const tabs=document.createElement('div');tabs.className='bgwf-panel-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Слоеве и легенда');
  for(const [name,label,content] of [['layers','Слоеве',layerContent],['legend','Легенда',legendContent]]){
    const tab=document.createElement('button');tab.type='button';tab.id='bgwf-tab-'+name;tab.dataset.panelTab=name;tab.textContent=label;tab.setAttribute('role','tab');tab.setAttribute('aria-controls',content.id);tab.setAttribute('aria-selected',String(name==='layers'));tab.tabIndex=name==='layers'?0:-1;
    content.setAttribute('role','tabpanel');content.setAttribute('aria-labelledby',tab.id);
    tab.onclick=()=>{for(const other of tabs.querySelectorAll('[role="tab"]')){const selected=other===tab;other.setAttribute('aria-selected',String(selected));other.tabIndex=selected?0:-1;}layerContent.hidden=name!=='layers';legendContent.hidden=name!=='legend';};
    tab.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const other=event.key==='Home'?tabs.children[0]:event.key==='End'?tabs.children[1]:tabs.children[name==='layers'?1:0];other.click();other.focus();};
    tabs.append(tab);
  }
  const controls=q('.bgwf-layer-controls'),hint=q('[data-industry-legend]');
  const names={solar:'Фотоволтаици',projects:'Планирани · ПУП/ПИ',wind:'Вятърни турбини',foreign:'ВЕИ в съседни държави',natura:'Natura 2000',future:'Зони RED III',epm:'Електропреносна мрежа',industry:'Мини и хвостохранилища'};
  const groups=[];
  for(const [title,keys] of [['ЕНЕРГИЯ',['solar','projects','wind','foreign']],['ТЕРИТОРИЯ',['natura','future','epm','industry']]]){
    const group=document.createElement('div');group.className='bgwf-layer-group';
    const heading=document.createElement('div');heading.className='bgwf-group-title';heading.textContent=title;group.append(heading);
    for(const key of keys){const button=q('[data-layer="'+key+'"]');if(!button)continue;button.querySelector('span:last-child').textContent=names[key];group.append(button);
      const entry=document.createElement('p'),swatch=button.querySelector('.bgwf-swatch').cloneNode(true);entry.append(swatch,document.createTextNode(names[key]));legendContent.append(entry);
    }
    groups.push(group);
  }
  controls.replaceChildren(...groups);if(hint)controls.append(hint);
  layerStrip.querySelector('.bgwf-control-label').hidden=true;
  const allYears=fireStrip.querySelector('[data-year="all"]'),iskra=fireStrip.querySelector('.bgwf-iskra-year-link');
  const fireLabel=document.createElement('div');fireLabel.className='bgwf-fire-heading';fireLabel.append(document.createTextNode('Пожарни периметри'),allYears);
  fireStrip.querySelector('.bgwf-control-label').textContent='ПРИРОДНИ РИСКОВЕ';
  fireStrip.insertBefore(fireLabel,fireStrip.querySelector('.bgwf-legend'));
  const yearNote=document.createElement('div');yearNote.className='bgwf-year-note';yearNote.append(document.createTextNode('Годината филтрира само пожарите. '),iskra);fireStrip.append(yearNote);
  const fireLegend=document.createElement('p');fireLegend.textContent='Исторически пожари по години';legendContent.append(fireLegend);
  const yearKeys=document.createElement('div');yearKeys.className='bgwf-legend-years';
  for(const button of fireStrip.querySelectorAll('.bgwf-legend [data-year]')){const label=document.createElement('span'),dot=document.createElement('i');dot.style.background=button.style.getPropertyValue('--bgwf-filter-color');label.append(dot,document.createTextNode(button.dataset.year));yearKeys.append(label);}legendContent.append(yearKeys);
  const legendNote=document.createElement('p');legendNote.className='bgwf-legend-note';legendNote.textContent='Цветовете обозначават тематичните слоеве. Полигоните показват наличните контури, а точковите маркери — местоположение. Годините управляват само историческите пожари.';legendContent.append(legendNote);
  layerContent.append(layerStrip,fireStrip);
  const stats=document.createElement('details');stats.className='bgwf-panel-stats';stats.open=true;stats.innerHTML='<summary>Площи и статистика</summary>';stats.append(q('.bgwf-status-row'),q('[data-natura-overlap]'),q('[data-territory-scale-bars]'));
  body.prepend(tabs,layerContent,legendContent);body.append(stats);
  const version=q('.bgwf-filter-version');version.setAttribute('aria-label','Версия на картата');tabs.append(version);

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
  searchButton.onclick=()=>{const open=!root.classList.contains('is-search-open');closeLayers();root.classList.toggle('is-search-open',open);searchButton.setAttribute('aria-expanded',String(open));if(open)q('[data-map-search-input]').focus();else closeSearchPanel();};
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
  let wasMobile=mobile();window.addEventListener('resize',()=>{const isMobile=mobile();if(isMobile!==wasMobile){setFilterPanelOpen(false);closeSearchPanel();wasMobile=isMobile;}sync();});
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
