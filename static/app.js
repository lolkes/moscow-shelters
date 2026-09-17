const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
let timer;
const speciesName=s=>s==='cat'?'Кошка':s==='dog'?'Собака':'Другое животное';
const sexName=s=>s==='male'?'Мальчик':s==='female'?'Девочка':'Пол не указан';
function photoMarkup(a){
  const photos=Array.isArray(a.photos)?a.photos.filter(Boolean):[];
  if(!photos.length) return `<div class="animal-icon">${a.species==='cat'?'🐱':a.species==='dog'?'🐶':'🐾'}</div>`;
  const main=esc(photos[0]);
  const more=photos.length>1?`<span class="photo-count">📷 ${photos.length}</span>`:'';
  return `<div class="animal-photo-wrap"><img class="animal-photo" src="${main}" alt="${esc(a.name)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('.animal-photo-wrap').classList.add('photo-failed')"><div class="photo-fallback">${a.species==='cat'?'🐱':a.species==='dog'?'🐶':'🐾'}</div>${more}</div>`;
}
async function loadStats(){
  const s=await fetch('/api/stats').then(r=>r.json());
  document.querySelector('#heroCount').textContent=s.animals_active;
  document.querySelector('#stats').innerHTML=`<div class="stat"><b>${s.animals_active}</b><span>животных</span></div><div class="stat"><b>${s.shelters}</b><span>приютов</span></div><div class="stat"><b>${s.verified_shelters}</b><span>источников проверено</span></div><div class="stat"><b>${s.sources_enabled}</b><span>источников импортируют</span></div>`;
}
async function loadAnimals(){
  clearTimeout(timer);
  const q=new URLSearchParams(); const v=document.querySelector('#search').value.trim(); const sp=document.querySelector('#species').value; const reg=document.querySelector('#region').value;
  if(v)q.set('q',v); if(sp)q.set('species',sp); if(reg)q.set('region',reg); q.set('limit','50');
  const response=await fetch('/api/animals?'+q); const payload=await response.json(); const rows=payload.items||[];
  document.querySelector('#animalGrid').innerHTML=rows.map(({animal:a,shelter:s})=>`<article class="animal-card">${photoMarkup(a)}<div class="animal-card-body"><div class="badge">${speciesName(a.species)}</div><h3>${esc(a.name)}</h3><div class="muted">${esc(a.age||'Возраст не указан')} · ${sexName(a.sex)}</div><p>${esc((a.description||'').slice(0,180))}</p><div class="muted">🏠 ${esc(s?.name||'')}</div><a class="button small" href="/animals/${a.id}">Посмотреть</a></div></article>`).join('')||'<div class="empty">По вашему запросу животных не найдено.</div>';
  timer=setTimeout(loadAnimals,60000);
}
async function loadShelters(){
  const r=document.querySelector('#shelterRegion').value; const data=await fetch('/api/shelters'+(r?'?region='+encodeURIComponent(r):'')).then(x=>x.json());
  document.querySelector('#shelterGrid').innerHTML=data.map(s=>`<article class="shelter-card"><div class="shelter-top"><span class="home-icon">🏠</span><span class="badge ${s.verified?'ok':'warn'}">${s.verified?'Проверен':'Проверяется'}</span></div><h3>${esc(s.name)}</h3><div class="muted">📍 ${esc(s.city||s.region)}</div><p>${esc(s.description||'Приют и источник первичной информации.')}</p><div class="count">🐾 ${s.animal_count||0} активных животных</div><div class="actions"><a class="button small" href="/shelters/${encodeURIComponent(s.id)}">Животные</a>${s.website?`<a class="button small ghost" target="_blank" rel="noopener" href="${esc(s.website)}">Сайт ↗</a>`:''}</div></article>`).join('')||'<div class="empty">Приюты не найдены.</div>';
}
['search','species','region'].forEach(id=>document.querySelector('#'+id).addEventListener(id==='search'?'input':'change',loadAnimals));
document.querySelector('#shelterRegion').onchange=loadShelters; loadStats(); loadAnimals(); loadShelters(); setInterval(()=>{loadStats();loadShelters()},60000);
