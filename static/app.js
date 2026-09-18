const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));
let page=1, species='', loading=false, more=true, timer;
const speciesName=s=>s==='cat'?'Кошка':s==='dog'?'Собака':'Животное';
const sexName=s=>s==='male'?'Мальчик':s==='female'?'Девочка':'Пол не указан';
const fallback=s=>s==='cat'?'🐱':s==='dog'?'🐶':'🐾';
function photoMarkup(a){
 const photos=Array.isArray(a.photos)?a.photos.filter(Boolean):[];
 if(!photos.length)return '<div class="animal-photo placeholder">'+fallback(a.species)+'</div>';
 return '<div class="animal-photo"><img src="'+esc(photos[0])+'" alt="'+esc(a.name)+'" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.innerHTML=\'<span>'+fallback(a.species)+'</span>\'"></div>';
}
function animalCard(x){
 const a=x.animal,s=x.shelter;
 return '<article class="animal-card">'+photoMarkup(a)+'<div class="card-body"><div class="card-top"><span class="type-pill">'+fallback(a.species)+' '+speciesName(a.species)+'</span></div><h3>'+esc(a.name)+'</h3><div class="facts"><span>'+esc(a.age||'Возраст не указан')+'</span><span>'+sexName(a.sex)+'</span></div><p>'+esc((a.description||'').replace(/\s+/g,' ').slice(0,150))+'</p><div class="shelter-line">⌂ '+esc(s?.name||'Приют не указан')+'</div><a class="card-link" href="/animals/'+a.id+'">Открыть анкету <span>→</span></a></div></article>';
}
async function loadStats(){
 try{const s=await fetch('/api/stats').then(r=>r.json());$('#heroCount').textContent=s.animals_active??0;$('#stats').innerHTML='<div><strong>'+s.animals_active+'</strong><span>животных ищут дом</span></div><div><strong>'+s.shelters+'</strong><span>приютов в реестре</span></div><div><strong>'+s.verified_shelters+'</strong><span>проверенных источников</span></div><div><strong>'+s.sources_enabled+'</strong><span>автоматических источников</span></div>';const all=await fetch('/api/animals?limit=100').then(r=>r.json());const items=all.items||[];$('#heroDogs').textContent=items.filter(x=>x.animal.species==='dog').length;$('#heroCats').textContent=items.filter(x=>x.animal.species==='cat').length}catch(e){console.error(e)}}
async function loadAnimals(reset=true){
 if(loading)return;loading=true;if(reset){page=1;more=true;$('#animalGrid').innerHTML='<div class="loading"><span></span><span></span><span></span></div>'}
 const q=new URLSearchParams({limit:'24',page:String(page)});const v=$('#search').value.trim(),reg=$('#region').value;if(v)q.set('q',v);if(species)q.set('species',species);if(reg)q.set('region',reg);
 try{const p=await fetch('/api/animals?'+q).then(r=>r.json());const rows=p.items||[];if(reset)$('#animalGrid').innerHTML='';if(!rows.length&&page===1){$('#animalGrid').innerHTML='<div class="empty">По этому фильтру пока ничего не найдено.<br><small>Попробуйте другой запрос.</small></div>'}else{$('#animalGrid').insertAdjacentHTML('beforeend',rows.map(animalCard).join(''))}$('#resultCount').textContent=(p.total||0)+' найдено';more=page<p.pages;$('#loadMore').hidden=!more}catch(e){$('#animalGrid').innerHTML='<div class="empty">Не удалось загрузить каталог. Попробуйте обновить страницу.</div>';console.error(e)}finally{loading=false}}
async function loadShelters(){try{const r=$('#region').value;const data=await fetch('/api/shelters'+(r?'?region='+encodeURIComponent(r):'')).then(x=>x.json());$('#shelterGrid').innerHTML=data.slice(0,24).map(s=>'<article class="shelter-card"><div class="shelter-head"><span>⌂</span><i class="'+(s.verified?'verified':'')+'">'+(s.verified?'Проверен':'Источник')+'</i></div><h3>'+esc(s.name)+'</h3><p>'+esc(s.city||s.region||'Москва и МО')+'</p><strong>🐾 '+(s.animal_count||0)+' животных</strong><div class="shelter-actions"><a href="/shelters/'+encodeURIComponent(s.id)+'">Каталог</a>'+(s.website?'<a target="_blank" rel="noopener" href="'+esc(s.website)+'">Сайт ↗</a>':'')+'</div></article>').join('')}catch(e){console.error(e)}}
$('#speciesTabs').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;document.querySelectorAll('#speciesTabs button').forEach(x=>x.classList.remove('active'));b.classList.add('active');species=b.dataset.species;loadAnimals(true)});
$('#region').addEventListener('change',()=>{loadAnimals(true);loadShelters()});
$('#search').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>loadAnimals(true),350)});
$('#loadMore').addEventListener('click',()=>{page++;loadAnimals(false)});
loadStats();loadAnimals();loadShelters();setInterval(loadStats,60000);