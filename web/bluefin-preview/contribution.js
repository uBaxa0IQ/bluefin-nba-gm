'use strict';

const contribution={key:null,version:0,job:null,error:'',expanded:null,sort:'win_delta',direction:-1};
function contributionParams(team){
 const custom={};
 if(s.rosterMode==='top_n')for(const t of teams)custom[t.team_id]=leagueSelected(t.team_id).map(p=>p.name).sort();
 return {...probabilityParams(),custom_rosters:custom,punt_categories:injuryMode()?punts():[],team_id:team,trials:3000};
}
function contributionKey(team){return JSON.stringify([settings.season.league_id,settings.season.year,contributionParams(team),(()=>{const data=resource(refreshStatusPath(),60000).data;return data?.data_version??data?.last_refresh_time;})()]);}
async function contributionRun(team){
 const key=contributionKey(team),version=++contribution.version,params=contributionParams(team);
 if(s.overlay==='contribution-player')s.overlay=null;
 Object.assign(contribution,{key,job:null,error:'',expanded:null});
 try{
  let job=await request('/api/probabilistic/contribution/jobs',{method:'POST',body:JSON.stringify(params)});
  while(version===contribution.version&&key===contributionKey(team)){
   contribution.job=job;render();
   if(job.status!=='running')return;
   await new Promise(resolve=>setTimeout(resolve,1200));
   if(version!==contribution.version||key!==contributionKey(team))return;
   job=await request('/api/probabilistic/contribution/jobs/'+job.job_id);
  }
 }catch(e){if(version===contribution.version){contribution.error=e.message;render();}}
}
function contributionSigned(n,d=1){return finite(n)?(n>0?'+':'')+fmt(n,d):'—';}
function contributionDetail(row,baseline){
 const base=baseline.standing,without=row.without;
 const metric=(label,before,after,delta)=>`<div><span>${label}</span><strong>${before} → ${after}</strong><small>${delta}</small></div>`;
 return `<section class="bf-contribution-detail"><div class="bf-contribution-metrics bf-trade-metrics">${metric(tr('Ожидаемые победы','Expected wins'),fmt(base.expected_record.wins,1),fmt(without.expected_record.wins,1),contributionSigned(-row.win_delta))}${metric(tr('Ожидаемое место','Expected rank'),fmt(base.expected_rank,1),fmt(without.expected_rank,1),contributionSigned(row.rank_delta))}${metric(tr('Плей-офф','Playoffs'),probabilityPercent(base.p_playoffs),probabilityPercent(without.p_playoffs),contributionSigned(-row.playoff_delta*100)+' '+tr('п.п.','pp'))}</div><div class="pe-table-wrap"><table class="bf-contribution-weeks"><thead><tr><th>${tr('Неделя','Week')}</th><th>${tr('Соперник','Opponent')}</th><th>${tr('С игроком','With player')}</th><th>${tr('Без игрока','Without player')}</th><th>Δ</th></tr></thead><tbody>${row.weeks.map(w=>`<tr><td>${w.week}</td><td>${E(tname(w.opponent_id))}</td><td>${probabilityPercent(w.p_win)}</td><td>${probabilityPercent(w.without_p_win)}</td><td style="${tone(w.win_delta*100/5)}">${contributionSigned(w.win_delta*100)} ${tr('п.п.','pp')}</td></tr>`).join('')}</tbody></table></div></section>`;
}
function contributionPage(team){
 const key=contributionKey(team);
 if(contribution.key!==key)void contributionRun(team);
 const job=contribution.job,result=job?.result,error=contribution.error||(job?.status==='failed'?job.message:'');
 const rows=result?.players??[],byId=new Map(rows.map(r=>[r.player_id,r]));
 const ordered=[...rows.map(r=>roster(team).find(p=>+p.player_id===r.player_id)).filter(Boolean),...roster(team).filter(p=>!byId.has(+p.player_id))];
 const value=p=>{const row=byId.get(+p.player_id);return cats.includes(contribution.sort)?row?.category_deltas[contribution.sort]:row?.[contribution.sort];};
 ordered.sort((a,b)=>{
  if(contribution.sort==='name')return contribution.direction*a.name.localeCompare(b.name);
  const av=value(a),bv=value(b);
  if(!finite(av)||!finite(bv))return Number(finite(bv))-Number(finite(av))||a.name.localeCompare(b.name);
  return contribution.direction*(av-bv)||a.name.localeCompare(b.name);
 });
 const heading=(key,label,title='')=>{const active=contribution.sort===key;return `<th class="${punts().includes(key)?'bf-punted':''}" aria-sort="${active?(contribution.direction===-1?'descending':'ascending'):'none'}" title="${E(title)}"><button class="pe-sort" data-action="contribution-sort" data-key="${E(key)}">${E(label)}${active?(contribution.direction===-1?' ↓':' ↑'):''}</button></th>`;};
 const unit=tr('п.п.','pp'),tip=tr('С игроком минус без игрока. Категории — среднее по оставшимся матчапам, в п.п.; победы — за остаток регулярки.','With player minus without player. Categories: average across remaining matchups in pp; wins: remaining regular season.');
 const cells=row=>cats.map(c=>`<td class="${punts().includes(c)?'bf-punted':''}" style="${tone(row.category_deltas[c]*100/5)}">${contributionSigned(row.category_deltas[c]*100)}</td>`).join('');
 return `<div class="pe-controls pe-row bf-between">${job?.status==='running'?`<span class="pe-muted" role="status">${result?`${rows.length} / ${roster(team).length}`:'…'}</span>`:''}</div>${error?`<div class="pe-error" role="alert">${E(error)} <button class="pe-link" data-action="contribution-retry">${tr('Повторить','Retry')}</button></div>`:''}<div class="pe-table-wrap"><table class="bf-contribution-table" style="--contribution-width:${210+cats.length*72+3*100}px"><thead><tr>${heading('name',tr('Игрок','Player'))}${cats.map(c=>heading(c,c,tip)).join('')}${heading('win_delta',tr('Δ побед','Δ wins'))}${heading('playoff_delta',tr('Плей-офф','Playoffs')+', '+unit)}${heading('rank_delta',tr('Δ места','Δ rank'),tr('Ожидаемое место без игрока минус с игроком','Expected rank without player minus with player'))}</tr></thead><tbody>${ordered.map(p=>{
  const row=byId.get(+p.player_id),active=s.overlay==='contribution-player'&&contribution.expanded===+p.player_id;
  return `<tr class="${active?'bf-contribution-selected':''}" ${row?`data-action="contribution-player" data-player="${p.player_id}"`:""}><th scope="row"><button class="bf-prob-team" data-action="contribution-player" data-player="${p.player_id}" aria-haspopup="dialog" aria-expanded="${active}" ${row?'':'disabled'}>${E(p.name)}</button>${row&&!row.games?`<span class="pe-subname">${tr('Нет выходов в расчёте','No scheduled starts')}</span>`:''}</th>${row?`${cells(row)}<td style="${tone(row.win_delta)}">${contributionSigned(row.win_delta,2)}</td><td style="${tone(row.playoff_delta*100/5)}">${contributionSigned(row.playoff_delta*100)}</td><td style="${tone(row.rank_delta)}">${contributionSigned(row.rank_delta)}</td>`:cats.map(c=>`<td class="${punts().includes(c)?'bf-punted':''}">…</td>`).join('')+'<td>…</td><td>…</td><td>…</td>'}</tr>`;
 }).join('')}</tbody></table></div>`;
}
app.addEventListener('click',event=>{
 const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
 if(el.dataset.action==='contribution-sort'){
  const key=el.dataset.key;
  if(!['name','win_delta','playoff_delta','rank_delta',...cats].includes(key))return;
  contribution.direction=contribution.sort===key?-contribution.direction:key==='name'?1:-1;
  contribution.sort=key;render();
 }
 if(el.dataset.action==='contribution-player'){contribution.expanded=+el.dataset.player;s.overlay='contribution-player';render();}
 if(el.dataset.action==='contribution-retry')void contributionRun(s.team);
});

function contributionDialog(){
 const result=contribution.job?.result;
 const row=result?.players.find(r=>r.player_id===contribution.expanded);
 return row?contributionDetail(row,result.baseline):'';
}
