/* Shared source freshness presentation for the map and the inventory. */
(function(global){
  'use strict';
  const name=mode=>mode==='osm'?'OSM':mode.startsWith('veiregistar:')?'VEIRegistar':mode;
  const date=value=>value&&!Number.isNaN(Date.parse(value))?new Date(value).toLocaleString('bg-BG',{timeZone:'Europe/Sofia'}):'неизвестна';
  function validate(health){
    if(!health||!health.sources||typeof health.sources!=='object'||Array.isArray(health.sources)||!health.sources.osm)throw Error('Invalid renewable source health');
    for(const source of Object.values(health.sources))if(!source||!['ok','stale','unavailable'].includes(source.status))throw Error('Invalid renewable source status');
    return health;
  }
  function warnings(health){
    if(!health)return ['Актуалността на ВЕИ източниците не може да се провери; показват се наличните кеширани данни.'];
    return Object.entries(health.sources).filter(([,s])=>s.status!=='ok').map(([mode,s])=>`${name(mode)}: ${s.status==='stale'?`не е опреснен; запазени са ${s.retained||0} записа`:'източникът е недостъпен'}. Последно успешно извличане: ${date(s.lastSuccessAt)}. Последен опит: ${date(s.lastAttemptAt||health.checkedAt)}.`);
  }
  function recordNote(p,health){
    const modes=p.sourceModes||[p.sourceMode];
    const notes=[];
    for(const mode of modes){
      const source=health?.sources?.[mode];
      const observation=p.sourceFreshness?.[mode];
      if(!source){
        if(mode==='osm'||mode?.startsWith('veiregistar:'))notes.push(`${name(mode)}: актуалността не е потвърдена`);
        continue;
      }
      if(source.status==='ok')continue;
      const fields=[['statusSourceMode','статус'],['capacitySourceMode','мощност'],['geometrySourceMode','местоположение']].filter(([key])=>(p[key]||p.sourceMode)===mode).map(([,label])=>label);
      // A newer observation from another source must not date this source.
      const success=observation?.lastSuccessAt||source.lastSuccessAt||(p.sourceMode===mode?p.retrievedAt:null);
      notes.push(`${name(mode)}${fields.length?` (${fields.join(', ')})`:''}: ${source.status==='stale'?'запазени данни; текущото състояние не е потвърдено при последния опит':'недостъпен'}. Последно успешно извличане: ${date(success)}`);
    }
    return notes.join(' · ');
  }
  async function load(fetcher){
    try{
      const options={cache:'no-cache'};
      if(typeof AbortSignal!=='undefined'&&AbortSignal.timeout)options.signal=AbortSignal.timeout(10000);
      const response=await fetcher('./data/bg-renewables-health-v1.json',options);
      if(!response.ok)throw Error(`HTTP ${response.status}`);
      return validate(await response.json());
    }catch(_error){return null;}
  }
  global.bgwfRenewableFreshness={validate,warnings,recordNote,load};
})(typeof window==='undefined'?globalThis:window);
