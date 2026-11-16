'use strict';

const probabilityStateKeys=['probTeam','probTeamView','probWeek','probOpponent','probView','probMatrixWeek','probRosterTeam','simMode'];
Object.assign(s,{probTeam:null,probTeamView:'schedule',probWeek:null,probOpponent:null,probView:'ranks',probMatrixWeek:null,probRosterTeam:null});
const probability={restored:false,restoring:false,job:null,result:null,params:null,resultVersion:null,busy:false,error:'',timer:null,expanded:null,autoTimer:null,refreshTimer:null,lastAttempt:null,autoKey:null};
const probabilityPercent=p=>finite(p)?fmt(p*100,1)+'%':'—';
const probabilityJobKey=()=>`bluefin-probabilistic-job:${settings.season.league_id}:${settings.season.year}`;
const probabilityEnabled=()=>settings?.features?.probabilistic===true;

const tradeProbability={version:0,key:null,job:null,error:''};
const tradeProbabilityKey=()=>JSON.stringify([settings?.season.league_id,s.tradeMyTeam,s.tradeTeam,s.give,s.receive,s.period,s.rosterMode,s.picks,punts()]);
async function tradeProbabilityRun(body){
 const version=++tradeProbability.version;
 tradeProbability.key=tradeProbabilityKey();tradeProbability.job=null;tradeProbability.error='';
 tradeProbability.baseline=probabilityCurrentResult()?.standings??[];
 const custom={};
 if(s.rosterMode==='top_n')for(const team of teams)custom[team.team_id]=selected(team.team_id).map(p=>p.name);
 const params={my_team_id:body.my_team_id,their_team_id:body.their_team_id,i_give:body.i_give,i_receive:body.i_receive,
  period:body.period,simulation_mode:body.simulation_mode,top_n_players:body.top_n_players,
  punt_categories:body.punt_categories,custom_rosters:custom,trials:3000,seed:20261116};
 render();
 if(!tradeProbability.baseline.length)void request('/api/probabilistic/latest').then(({job})=>{
  if(version!==tradeProbability.version||tradeProbability.key!==tradeProbabilityKey())return;
  if(job?.status==='complete'&&probabilitySettingsKey({...job.params,trials:3000})===probabilitySettingsKey(params)){tradeProbability.baseline=job.result.standings;render();}
 }).catch(()=>{});
 try{
  let job=await request('/api/probabilistic/trade/jobs',{method:'POST',body:JSON.stringify(params)});
  while(version===tradeProbability.version&&tradeProbability.key===tradeProbabilityKey()){
   tradeProbability.job=job;render();
   if(job.status!=='running')break;
   await new Promise(resolve=>setTimeout(resolve,1000));
   if(version!==tradeProbability.version||tradeProbability.key!==tradeProbabilityKey())return;
   job=await request('/api/probabilistic/trade/jobs/'+job.job_id);
  }
 }catch(e){if(version===tradeProbability.version){tradeProbability.error=e.message;render();}}
}
function tradeProbabilityPanel(){
 if(!probabilityEnabled()||tradeProbability.key!==tradeProbabilityKey())return '';
 const job=tradeProbability.job,d=job?.result;
 const error=tradeProbability.error||(job?.status==='failed'?job.message:'');
 const before=d?.before??tradeProbability.baseline??[],after=d?.after??[];
 const max=Math.max(.1,...[...before,...after].flatMap(t=>Object.values(t.rank_probabilities)));
 const chart=team=>{
  const a=before.find(t=>t.team_id===team),b=after.find(t=>t.team_id===team);
  if(!a)return `<section><h3>${E(tname(team))}</h3><div class="bf-trade-prob-loading" role="status">…</div></section>`;
  const ranks=Object.keys(a.rank_probabilities).map(Number).sort((x,y)=>x-y),x=r=>44+(r-1)*500/Math.max(1,ranks.length-1),y=p=>210-p/max*170;
  const line=(t,color)=>!t?'':`<polyline points="${ranks.map(r=>`${x(r)},${y(t.rank_probabilities[r])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5"/>${ranks.map(r=>`<circle cx="${x(r)}" cy="${y(t.rank_probabilities[r])}" r="3" fill="${color}"><title>${tr('Место','Rank')} ${r} · ${t===a?tr('До','Before'):tr('После','After')}: ${probabilityPercent(t.rank_probabilities[r])}</title></circle>`).join('')}`;
  return `<section><h3>${E(a.team_name)}</h3><svg viewBox="0 0 570 255" role="img" aria-label="${E(a.team_name)} · ${tr('Распределение итогового места в регулярке','Regular-season rank distribution')}">${[0,.5,1].map(v=>`<line x1="44" y1="${y(max*v)}" x2="544" y2="${y(max*v)}" stroke="var(--pe-line)"/><text x="36" y="${y(max*v)+4}" text-anchor="end">${fmt(max*v*100,0)}%</text>`).join('')}${ranks.map(r=>`<text x="${x(r)}" y="230" text-anchor="middle">${r}</text>`).join('')}${line(a,'var(--pe-muted)')}${line(b,'var(--pe-blue)')}<text x="294" y="252" text-anchor="middle">${tr('Место в регулярке','Regular-season rank')}</text></svg></section>`;
 };
 const summary=[+s.tradeMyTeam,+s.tradeTeam].map(team=>{
  const a=before.find(t=>t.team_id===team),b=after.find(t=>t.team_id===team);
  const delta=b&&a?(b.p_playoffs-a.p_playoffs)*100:null;
  const rankDelta=a&&b?a.expected_rank-b.expected_rank:null;
  return `<section><h2>${E(tname(team))}</h2><div class="bf-trade-metrics"><div><span>${tr('Ожидаемое место','Expected rank')}</span><strong>${a?fmt(a.expected_rank,1):'…'} → ${b?fmt(b.expected_rank,1):'…'}</strong>${rankDelta!==null?`<small style="${tone(rankDelta*1.5)}">${rankDelta>0?'↑':rankDelta<0?'↓':''}${fmt(Math.abs(rankDelta),1)}</small>`:''}</div><div><span>${tr('Плей-офф','Playoffs')}</span><strong>${a?probabilityPercent(a.p_playoffs):'…'} → ${b?probabilityPercent(b.p_playoffs):'…'}</strong>${delta!==null?`<small style="${tone(delta/10)}">${delta>0?'+':''}${fmt(delta,1)} ${tr('п.п.','pp')}</small>`:''}</div></div></section>`;
 }).join('');
 return `<section class="bf-trade-prob"><div class="pe-section-head"><h2>${tr('Место в регулярке','Regular-season finish')}</h2></div><div class="bf-trade-prob-legend"><span>● ${tr('До обмена','Before trade')}</span><span>● ${tr('После обмена','After trade')}</span></div>${error?`<div class="pe-error" role="alert">${E(error)}</div>`:''}<div class="bf-trade-prob-grid">${[+s.tradeMyTeam,+s.tradeTeam].map(chart).join('')}</div><div class="bf-trade-outcomes bf-trade-prob-impact">${summary}</div></section>`;
}

function probabilityParams(){
 const custom={};
 if(s.rosterMode==='top_n')for(const team of teams)custom[team.team_id]=selected(team.team_id).map(p=>p.name).sort();
 return {period:settings.season.periods[s.period],simulation_mode:s.rosterMode,top_n_players:13,
  custom_rosters:custom,punt_categories:[...punts()].sort(),trials:10000,seed:20261116};
}
function probabilitySettingsKey(p){return JSON.stringify([p.period,p.simulation_mode,p.top_n_players,
 Object.entries(p.custom_rosters??{}).sort(([a],[b])=>+a-+b).map(([k,names])=>[String(k),[...names].sort()]),
 [...(p.punt_categories??[])].sort(),p.trials,p.seed]);}
function probabilityMatchesCurrent(params){return !!params&&probabilitySettingsKey(params)===probabilitySettingsKey(probabilityParams());}
function probabilityCurrentResult(){return probabilityMatchesCurrent(probability.params)?probability.result:null;}
function probabilityAccept(job){
 probability.job=job;
 probability.busy=job.status==='running';
 if(job.status==='complete'&&probabilityMatchesCurrent(job.params)){
  probability.result=job.result;probability.params=job.params;probability.error='';
  probability.resultVersion=job.source_version;
  if(!job.result.standings.some(t=>t.team_id===+s.probTeam))s.probTeam=null;
 }
 if(job.status==='failed')probability.error=job.message||tr('Не удалось выполнить расчёт','Calculation failed');
 if(probability.busy)localStorage.setItem(probabilityJobKey(),job.job_id);
 else localStorage.removeItem(probabilityJobKey());
}
async function probabilityPoll(jobId){
 clearTimeout(probability.timer);
 try{
  const job=await request('/api/probabilistic/jobs/'+encodeURIComponent(jobId));
  if(probability.job?.job_id!==jobId)return;
  probabilityAccept(job);
  if(probability.busy)probability.timer=setTimeout(()=>probabilityPoll(jobId),1500);
 }catch(error){
  probability.busy=false;probability.error=error.message;
 }
 render();
}
async function probabilityRestore(){
 probability.restored=true;probability.restoring=true;
 try{
  const running=localStorage.getItem(probabilityJobKey());
  const {job}=await request('/api/probabilistic/latest');
  if(job)probabilityAccept(job);
  if(running){
   try{const active=await request('/api/probabilistic/jobs/'+encodeURIComponent(running));probabilityAccept(active);
    if(probability.busy)probability.timer=setTimeout(()=>probabilityPoll(active.job_id),500);
   }catch{localStorage.removeItem(probabilityJobKey());}
  }
 }catch(error){probability.error=error.message==='Not Found'?tr('Перезапустите backend, чтобы включить вероятностный режим.','Restart the backend to enable probabilistic simulation.'):error.message;}
 finally{probability.restoring=false;render();}
}
async function probabilityRun(){
 if(!probabilityEnabled())return;
 if(probability.busy||probability.restoring)return;
 probability.busy=true;probability.error='';render();
 try{
  const job=await request('/api/probabilistic/jobs',{method:'POST',body:JSON.stringify(probabilityParams())});
  probabilityAccept(job);
  if(probability.busy)probability.timer=setTimeout(()=>probabilityPoll(job.job_id),500);
 }catch(error){probability.busy=false;probability.error=error.status===409?'':error.message;if(error.status===409)probability.timer=setTimeout(()=>void probabilityRun(),2000);}
 render();
}
function probabilityAuto(){
 if(!probabilityEnabled())return;
 if(!probability.restored||probability.restoring||probability.busy||probability.error)return;
 const refresh=resource('/api/refresh-status',60000);
 if(refresh.pending)return;
 const params=probabilityParams(),key=probabilitySettingsKey(params);
 const stamp=refresh.data?.last_refresh_time||'';
 const stale=!probability.result||!probability.params||probabilitySettingsKey(probability.params)!==key||
  (stamp&&Date.parse(stamp)>Date.parse(probability.resultVersion||probability.result.metadata.as_of));
 const attempt=key+'|'+stamp;
 if(!stale||probability.lastAttempt===attempt)return;
 if(probability.autoTimer&&probability.autoKey===attempt)return;
 clearTimeout(probability.autoTimer);
 probability.autoKey=attempt;
 probability.autoTimer=setTimeout(()=>{
  probability.autoTimer=null;
  if(probability.busy||probability.restoring||probability.error)return;
  if(probabilitySettingsKey(probabilityParams())!==key){render();return;}
  probability.lastAttempt=attempt;void probabilityRun();
 },600);
}
function probabilityViewMatch(match,team){
 if(match.team1_id===+team)return match;
 return {...match,team1_id:match.team2_id,team2_id:match.team1_id,p_win:match.p_loss,p_loss:match.p_win,
  categories:Object.fromEntries(Object.entries(match.categories).map(([c,p])=>[c,{p_win:p.p_loss,p_tie:p.p_tie,p_loss:p.p_win}]))};
}
function probabilityCategories(match){return `<table class="bf-prob-categories"><thead><tr><th>${tr('Категория','Category')}</th><th>${tr('Победа','Win')}</th><th>${tr('Ничья','Tie')}</th><th>${tr('Поражение','Loss')}</th></tr></thead><tbody>${Object.entries(match.categories).map(([c,p])=>`<tr><td>${E(c)}</td><td style="${tone((p.p_win-.5)*6)}">${probabilityPercent(p.p_win)}</td><td>${probabilityPercent(p.p_tie)}</td><td style="${tone((.5-p.p_loss)*6)}">${probabilityPercent(p.p_loss)}</td></tr>`).join('')}</tbody></table>`;}
function probabilityTeamPanel(d){
 const team=d.standings.find(t=>t.team_id===+s.probTeam);if(!team)return '';
 const names=Object.fromEntries(d.standings.map(t=>[t.team_id,t.team_name]));
 const weeks=d.weeks;
 let content='';
 if(s.probTeamView==='opponents'){
  const week=weeks.find(w=>w.week===+s.probWeek)??weeks[0];
  const opponent=d.standings.find(t=>t.team_id===+s.probOpponent&&t.team_id!==team.team_id)??d.standings.find(t=>t.team_id!==team.team_id);
  const match=week?.matchups.find(m=>[m.team1_id,m.team2_id].includes(team.team_id)&&[m.team1_id,m.team2_id].includes(opponent?.team_id));
  content=`<div class="pe-controls pe-row"><select class="pe-select" data-control="probWeek" aria-label="${tr('Неделя сравнения','Comparison week')}">${weeks.map(w=>`<option value="${w.week}" ${w===week?'selected':''}>${tr('Неделя','Week')} ${w.week}</option>`).join('')}</select><select class="pe-select" data-control="probOpponent" aria-label="${tr('Соперник','Opponent')}">${d.standings.filter(t=>t.team_id!==team.team_id).map(t=>`<option value="${t.team_id}" ${t===opponent?'selected':''}>${E(t.team_name)}</option>`).join('')}</select></div>`;
  if(match){const m=probabilityViewMatch(match,team.team_id);content+=`<div class="bf-prob-chances"><span>${tr('Победа','Win')} <strong>${probabilityPercent(m.p_win)}</strong></span><span>${tr('Ничья','Tie')} <strong>${probabilityPercent(m.p_tie)}</strong></span><span>${tr('Поражение','Loss')} <strong>${probabilityPercent(m.p_loss)}</strong></span><small>${m.official?tr('Матч по расписанию','Scheduled matchup'):tr('Гипотетический матч этой недели','Hypothetical matchup for this week')}</small></div>`+probabilityCategories(m);}
  else content+=blank(tr('Нет оставшихся матчей','No remaining matchups'));
 }else{
  const rows=weeks.flatMap(w=>w.matchups.filter(m=>m.official&&[m.team1_id,m.team2_id].includes(team.team_id)).map(match=>{
   const m=probabilityViewMatch(match,team.team_id),identity=`${w.week}:${m.team2_id}`,open=probability.expanded===identity;
   return `<tr><td><button class="pe-link" data-action="prob-match" data-week="${w.week}" data-opponent="${m.team2_id}" aria-expanded="${open}">${tr('Неделя','Week')} ${w.week} ${open?'−':'+'}</button></td><td>${E(names[m.team2_id])}</td><td style="${tone((m.p_win-.5)*6)}">${probabilityPercent(m.p_win)}</td><td>${probabilityPercent(m.p_tie)}</td><td style="${tone((.5-m.p_loss)*6)}">${probabilityPercent(m.p_loss)}</td></tr>${open?`<tr><td colspan="5" class="bf-prob-category-detail">${probabilityCategories(m)}</td></tr>`:''}`;
  }));
  content=rows.length?`<div class="pe-table-wrap"><table class="bf-prob-schedule"><thead><tr><th>${tr('Неделя','Week')}</th><th>${tr('Соперник','Opponent')}</th><th>${tr('Победа','Win')}</th><th>${tr('Ничья','Tie')}</th><th>${tr('Поражение','Loss')}</th></tr></thead><tbody>${rows.join('')}</tbody></table></div>`:blank(tr('Нет оставшихся матчей','No remaining matchups'));
 }
 return `<section class="bf-prob-team-panel"><div class="pe-section-head"><h2>${E(team.team_name)}</h2><button class="pe-link" data-action="prob-close-team">${tr('Скрыть','Hide')}</button></div>${tabs([['schedule',tr('Расписание','Schedule')],['opponents',tr('Любой соперник','Any opponent')]],'probTeamView')}${content}</section>`;
}
function probabilityRankResults(d){
 const ranks=Array.from({length:d.standings.length},(_,i)=>String(i+1));
 const maxima=Object.fromEntries(ranks.map(r=>[r,Math.max(...d.standings.map(t=>t.rank_probabilities[r]))]));
 return `<div class="pe-table-wrap"><table class="bf-prob-matrix" style="--prob-width:${370+ranks.length*57}px"><colgroup><col style="width:200px"><col style="width:80px"><col style="width:90px">${ranks.map(()=>'<col style="width:57px">').join('')}</colgroup><thead><tr><th>${tr('Команда','Team')}</th><th>${tr('Ожид. место','Exp. rank')}</th><th>${tr('Плей-офф','Playoffs')}</th>${ranks.map(r=>`<th scope="col">${r}</th>`).join('')}</tr></thead><tbody>${d.standings.map(t=>`<tr class="${t.team_id===+s.probTeam?'bf-prob-selected':''}"><td><button class="bf-prob-team" data-action="prob-team" data-team="${t.team_id}" aria-expanded="${t.team_id===+s.probTeam}">${E(t.team_name)}</button></td><td>${fmt(t.expected_rank)}</td><td style="${tone((t.p_playoffs-.5)*6)}">${probabilityPercent(t.p_playoffs)}</td>${ranks.map(r=>{const p=t.rank_probabilities[r];return `<td style="${p?tone(p,maxima[r]||1):''}" title="${E(t.team_name)} · ${tr('Место','Rank')} ${r}: ${probabilityPercent(p)}">${p?fmt(p*100,1):'—'}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>${probabilityTeamPanel(d)}`;
}
function probabilityOpponentResults(d){
 const weeks=[...d.weeks].sort((a,b)=>a.week-b.week);
 if(!weeks.length)return blank(tr('Нет оставшихся матчей','No remaining matchups'));
 const names=Object.fromEntries(d.standings.map(t=>[t.team_id,t.team_name]));
 const schedule=new Map();
 for(const week of weeks)for(const match of week.matchups){
  if(!match.official)continue;
  schedule.set(`${week.week}:${match.team1_id}`,match);
  schedule.set(`${week.week}:${match.team2_id}`,probabilityViewMatch(match,match.team2_id));
 }
 const header=weeks.map(w=>`<th scope="col">${tr('Неделя','Week')} ${w.week}</th>`).join('');
 const rows=d.standings.map(team=>`<tr><th scope="row">${E(team.team_name)}</th>${weeks.map(week=>{
  const match=schedule.get(`${week.week}:${team.team_id}`);
  if(!match)return `<td class="bf-prob-diagonal" title="${tr('Нет матча по расписанию','No scheduled matchup')}">—</td>`;
  const label=`${team.team_name} · ${names[match.team2_id]} · ${tr('Неделя','Week')} ${week.week}: ${probabilityPercent(match.p_win)}`;
  return `<td style="${tone((match.p_win-.5)*6)}"><button class="bf-prob-cell" data-action="prob-pair" data-team="${team.team_id}" data-opponent="${match.team2_id}" data-week="${week.week}" aria-label="${E(label)}" title="${E(label)}">${probabilityPercent(match.p_win)}</button></td>`;
 }).join('')}</tr>`).join('');
 return `<div class="pe-table-wrap"><table class="bf-prob-opponents" style="--prob-width:${190+weeks.length*96}px" aria-label="${tr('Вероятность победы команды по неделям в матчах по расписанию','Team win probability by week in scheduled matchups')}"><colgroup><col style="width:190px">${weeks.map(()=>'<col style="width:96px">').join('')}</colgroup><thead><tr><th>${tr('Команда','Team')}</th>${header}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function probabilityResults(d){
 const controls=`<div class="pe-controls bf-prob-view-controls">${segment([['ranks',tr('Места','Ranks')],['opponents',tr('Соперники','Opponents')]],'probView')}<div class="pe-row"><button class="pe-link" data-action="prob-rosters">${tr('Составы расчёта','Calculation rosters')}</button></div></div>`;
 return controls+(s.probView==='opponents'?probabilityOpponentResults(d):probabilityRankResults(d));
}
function probabilityOpenPair(team,opponent,week){
 const d=probabilityCurrentResult();if(!d||team===opponent)return;
 const plan=d.weeks.find(w=>w.week===week);
 const match=plan?.matchups.find(m=>[m.team1_id,m.team2_id].includes(team)&&[m.team1_id,m.team2_id].includes(opponent));
 if(!match)return;
 probability.matchDetail={week,match:probabilityViewMatch(match,team),standings:d.standings};
 s.overlay='prob-match';render();
}
function probabilityMatchDialog(){
 const detail=probability.matchDetail;if(!detail)return '';
 const {match,week,standings}=detail;
 const name=id=>standings.find(t=>t.team_id===id)?.team_name??'';
 return `<div class="bf-prob-match-title"><span>${E(name(match.team1_id))}</span><span>${E(name(match.team2_id))}</span></div><div class="bf-prob-chances"><span>${tr('Победа','Win')} <strong>${probabilityPercent(match.p_win)}</strong></span><span>${tr('Ничья','Tie')} <strong>${probabilityPercent(match.p_tie)}</strong></span><span>${tr('Поражение','Loss')} <strong>${probabilityPercent(match.p_loss)}</strong></span><small>${match.official?tr('Матч по расписанию','Scheduled matchup'):tr('Гипотетический матч этой недели','Hypothetical matchup for this week')}</small></div>${probabilityCategories(match)}`;
}
function probabilityRosterDialog(){
 const d=probability.rosterResult;if(!d)return '';
 const available=d.standings;
 const team=available.find(t=>t.team_id===+s.probRosterTeam)??available.find(t=>t.team_id===myTeam)??available[0];
 const names=d.metadata.rosters?.[team.team_id];
 return `<div class="pe-section-head"><select class="pe-select" data-control="probRosterTeam" aria-label="${tr('Команда в расчёте','Team in calculation')}">${available.map(t=>`<option value="${t.team_id}" ${t===team?'selected':''}>${E(t.team_name)}</option>`).join('')}</select>${names?`<span class="pe-muted">${names.length}</span>`:''}</div>${names?`<ul class="bf-prob-roster-list" aria-label="${tr('Игроки в расчёте','Players in calculation')}">${names.map(name=>`<li>${E(name)}</li>`).join('')}</ul>`:blank(tr('Состав этого расчёта недоступен','The roster for this calculation is unavailable'))}`;
}
function probabilisticPage(){
 const currentResult=probabilityCurrentResult();
 if(!currentResult&&['prob-match','prob-rosters'].includes(s.overlay))s.overlay=null;
 if(!probability.restored)void probabilityRestore();
 probabilityAuto();
 if(!probability.refreshTimer)probability.refreshTimer=setTimeout(()=>{
  probability.refreshTimer=null;
  if(s.page==='simulations'&&s.simMode==='probabilistic'){cache.delete('/api/refresh-status');render();}
 },60000);
 return `${probability.error?`<div class="pe-error" role="alert">${E(probability.error)} <button class="pe-link" data-action="${probability.job?.status==='failed'?'prob-run':'prob-restore'}">${tr('Повторить','Retry')}</button></div>`:''}
  <div aria-busy="${probability.busy||probability.restoring}">${currentResult?probabilityResults(currentResult):!probability.error?`<div class="bf-prob-loading" role="status" aria-label="${tr('Загрузка прогноза','Loading forecast')}">…</div>`:''}</div>`;
}

app.addEventListener('click',event=>{
 const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
 if(el.dataset.action==='prob-run')void probabilityRun();
 if(el.dataset.action==='prob-restore'){probability.error='';void probabilityRestore();}
 if(el.dataset.action==='prob-team'){s.probTeam=+s.probTeam===+el.dataset.team?null:+el.dataset.team;probability.expanded=null;save();render();}
 if(el.dataset.action==='prob-close-team'){s.probTeam=null;save();render();}
 if(el.dataset.action==='prob-match'){const key=`${el.dataset.week}:${el.dataset.opponent}`;probability.expanded=probability.expanded===key?null:key;render();}
 if(el.dataset.action==='prob-pair')probabilityOpenPair(+el.dataset.team,+el.dataset.opponent,+el.dataset.week);
 if(el.dataset.action==='prob-rosters'){
  probability.rosterResult=probabilityCurrentResult();
  if(!probability.rosterResult)return;
  if(s.probTeam)s.probRosterTeam=s.probTeam;
  s.overlay='prob-rosters';render();
 }
});
