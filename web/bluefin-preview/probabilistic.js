'use strict';

const probabilityStateKeys=['probTeam','probTeamView','probWeek','probOpponent','probView','probMatrixWeek','simMode'];
Object.assign(s,{categoryMode:'averages',probTeam:null,probTeamView:'schedule',probWeek:null,probOpponent:null,probView:'ranks',probMatrixWeek:null});
const probability={restored:false,restoring:false,job:null,result:null,params:null,resultVersion:null,busy:false,error:'',timer:null,expanded:null,autoTimer:null,refreshTimer:null,lastAttempt:null,autoKey:null};
const probabilityPercent=p=>finite(p)?fmt(p*100,1)+'%':'—';
const probabilityJobKey=()=>`bluefin-probabilistic-job:${settings.season.league_id}:${settings.season.year}`;
const probabilityEnabled=()=>settings?.features?.probabilistic===true;

const tradeProbability={version:0,key:null,job:null,error:''};
const tradeProbabilityKey=()=>JSON.stringify([settings?.season.league_id,s.tradeMyTeam,s.tradeTeam,s.give,s.receive,s.tradeLegs,s.period,s.rosterMode,s.picks,punts(),injuryMode()?myTeam:null]);
async function tradeProbabilityRun(body){
 const version=++tradeProbability.version;
 tradeProbability.key=tradeProbabilityKey();tradeProbability.job=null;tradeProbability.error='';
 tradeProbability.baseline=probabilityCurrentResult()?.standings??[];
 const custom={};
 if(s.rosterMode==='top_n')for(const team of teams)custom[team.team_id]=selected(team.team_id).map(p=>p.name);
 const moves=body.trades?{trades:body.trades}:{my_team_id:body.my_team_id,their_team_id:body.their_team_id,i_give:body.i_give,i_receive:body.i_receive};
 const params={...moves,
  period:body.period,simulation_mode:body.simulation_mode,top_n_players:body.top_n_players,
  punt_categories:body.punt_categories,...(body.punt_team_id?{punt_team_id:body.punt_team_id}:{}),custom_rosters:custom,trials:3000,seed:20261116};
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
function tradeCategoryProbabilityCells(team,category){
 const current=tradeProbability.key===tradeProbabilityKey(),job=current?tradeProbability.job:null;
 const before=(job?.result?.before??(current?tradeProbability.baseline:[])??[]).find(t=>t.team_id===+team)?.category_probabilities?.[category];
 const after=job?.result?.after?.find(t=>t.team_id===+team)?.category_probabilities?.[category];
 const pending=current&&!tradeProbability.error&&!['complete','failed'].includes(job?.status);
 const show=v=>finite(v)?probabilityPercent(v):v===null||!pending?'—':'…';
 const delta=finite(before)&&finite(after)?(after-before)*100:null;
 const color=delta===null?'':tone(delta,10);
 return `<td class="bf-trade-before" style="${color}">${show(before)}</td><td class="bf-trade-after" style="${color}">${show(after)}</td><td style="${color}">${delta!==null?(delta>0?'+':'')+fmt(delta,1)+' '+tr('п.п.','pp'):pending?'…':'—'}</td>`;
}
function tradeProbabilityPanel(){
 if(!probabilityEnabled()||tradeProbability.key!==tradeProbabilityKey())return '';
 const job=tradeProbability.job,d=job?.result;
 const error=tradeProbability.error||(job?.status==='failed'?job.message:'');
 const before=d?.before??tradeProbability.baseline??[],after=d?.after??[];
 const teamIds=s.tradeLegs.length?[s.tradeLegs[0].my]:[+s.tradeMyTeam,+s.tradeTeam];
 const max=Math.max(.1,...[...before,...after].flatMap(t=>Object.values(t.rank_probabilities)));
 const chart=team=>{
  const a=before.find(t=>t.team_id===team),b=after.find(t=>t.team_id===team);
  const heading=`<h3>${E(a?.team_name??tname(team))}</h3>`;
  if(!a)return `<section>${heading}${error||job?.status==='complete'?'':'<div class="bf-trade-prob-loading" role="status">…</div>'}</section>`;
  const ranks=Object.keys(a.rank_probabilities).map(Number).sort((x,y)=>x-y),x=r=>44+(r-1)*500/Math.max(1,ranks.length-1),y=p=>210-p/max*170;
  const line=(t,color)=>!t?'':`<polyline points="${ranks.map(r=>`${x(r)},${y(t.rank_probabilities[r])}`).join(' ')}" fill="none" stroke="${color}" stroke-width="2.5"/>${ranks.map(r=>`<circle cx="${x(r)}" cy="${y(t.rank_probabilities[r])}" r="3" fill="${color}"><title>${tr('Место','Rank')} ${r} · ${t===a?tr('До','Before'):tr('После','After')}: ${probabilityPercent(t.rank_probabilities[r])}</title></circle>`).join('')}`;
  return `<section>${heading}<svg viewBox="0 0 570 255" role="img" aria-label="${E(a.team_name)} · ${tr('Распределение итогового места в регулярке','Regular-season rank distribution')}">${[0,.5,1].map(v=>`<line x1="44" y1="${y(max*v)}" x2="544" y2="${y(max*v)}" stroke="var(--pe-line)"/><text x="36" y="${y(max*v)+4}" text-anchor="end">${fmt(max*v*100,0)}%</text>`).join('')}${ranks.map(r=>`<text x="${x(r)}" y="230" text-anchor="middle">${r}</text>`).join('')}${line(a,'var(--pe-muted)')}${line(b,'var(--pe-blue)')}<text x="294" y="252" text-anchor="middle">${tr('Место в регулярке','Regular-season rank')}</text></svg></section>`;
 };
 const summary=teamIds.map(team=>{
  const a=before.find(t=>t.team_id===team),b=after.find(t=>t.team_id===team);
  const rankDelta=a&&b?a.expected_rank-b.expected_rank:null;
  const show=(row,key)=>row&&key in row?probabilityPercent(row[key]):job?.status==='complete'||error?'—':'…';
  const metrics=[['p_playoffs',tr('Плей-офф','Playoffs')],['p_final',tr('Финал','Final')],['p_title',tr('Титул','Title')]].map(([key,label])=>{
   const delta=finite(a?.[key])&&finite(b?.[key])?(b[key]-a[key])*100:null;
   return `<div><span>${label}</span><strong>${show(a,key)} → ${show(b,key)}</strong>${delta===null?'':`<small style="${tone(delta/10)}">${delta>0?'+':''}${fmt(delta,1)} ${tr('п.п.','pp')}</small>`}</div>`;
  }).join('');
  return `<section class="bf-trade-match-trigger" data-action="trade-matchups" data-team="${team}"><h2><button class="bf-prob-team" aria-haspopup="dialog" aria-label="${E(tname(team))} · ${tr('Матчапы','Matchups')}">${teamIds.length===1?tr('Матчапы','Matchups'):E(tname(team))}</button></h2><div class="bf-trade-metrics"><div><span>${tr('Ожидаемое место','Expected rank')}</span><strong>${a?fmt(a.expected_rank,1):'…'} → ${b?fmt(b.expected_rank,1):'…'}</strong>${rankDelta!==null?`<small style="${tone(rankDelta*1.5)}">${rankDelta>0?'↑':rankDelta<0?'↓':''}${fmt(Math.abs(rankDelta),1)}</small>`:''}</div>${metrics}</div></section>`;
 }).join('');
 return `<section class="bf-trade-prob"><div class="pe-section-head"><h2>${tr('Место в регулярке','Regular-season finish')}</h2></div><div class="bf-trade-prob-legend"><span>● ${tr('До обмена','Before trade')}</span><span>● ${tr('После обмена','After trade')}</span></div>${error?`<div class="pe-error" role="alert">${E(error)}</div>`:''}<div class="bf-trade-prob-content"><div class="bf-trade-prob-grid">${teamIds.map(chart).join('')}</div><div class="bf-trade-outcomes bf-trade-prob-impact">${summary}</div></div></section>
 `;
}

function tradeMatchupOdds(before,after,pending){
 const delta=finite(before)&&finite(after)?(after-before)*100:null;
 return {
  comparison:`${probabilityPercent(before)} → ${pending?'…':probabilityPercent(after)}`,
  change:delta===null?'—':`<span style="${Math.abs(delta)>=.05?tone(delta/10):''}">${delta>=.05?'+':''}${fmt(Math.abs(delta)<.05?0:delta,1)} ${tr('п.п.','pp')}</span>`,
 };
}

function tradeMatchupDialog(){
 if(tradeProbability.key!==tradeProbabilityKey())return '';
 const {job,error,matchTeam,matchView}=tradeProbability;
 const before=job?.result?.before?.find(t=>t.team_id===matchTeam);
 const after=job?.result?.after?.find(t=>t.team_id===matchTeam);
 const pending=!error&&(!job||job.status==='running');
 const views=[['regular',tr('Регулярка','Regular season')],['playoffs',tr('Плей-офф','Playoffs')]];
 const controls=`<div class="pe-tabs" role="group" aria-label="${tr('Этап сезона','Season stage')}">${views.map(([view,label])=>`<button data-action="trade-matchup-view" data-view="${view}" aria-pressed="${view===matchView}">${label}</button>`).join('')}</div>`;
 const message=error||job?.message;
 if(!before&&!after)return controls+blank(pending?'…':message||tr('Прогноз матчапов недоступен','Matchup forecast unavailable'));
 const table=(head,rows)=>`<div class="pe-table-wrap"><table class="bf-trade-match-table"><thead><tr>${head.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
 const opponent=tr('Соперник','Opponent');
 if(matchView==='regular'){
  const prior=before?.regular_matchups??[],next=after?.regular_matchups??[];
  const matches=[...new Map([...prior,...next].map(m=>[m.week,m])).values()].sort((a,b)=>a.week-b.week);
  if(!matches.length)return controls+blank(tr('Нет оставшихся матчапов','No remaining matchups'));
  return controls+table([tr('Неделя','Week'),opponent,tr('Победа до → после','Win before → after'),'Δ'],matches.map(({week,opponent_id})=>{
   const a=prior.find(m=>m.week===week&&m.opponent_id===opponent_id),b=next.find(m=>m.week===week&&m.opponent_id===opponent_id);
   const odds=tradeMatchupOdds(a?.p_win,b?.p_win,pending&&!after);
   return `<tr><td>${week}</td><td>${E(tname(opponent_id))}</td><td>${odds.comparison}</td><td>${odds.change}</td></tr>`;
  }).join(''));
 }
 const prior=before?.playoff_matchups??[],next=after?.playoff_matchups??[];
 const rounds=[...new Map([...prior,...next].map(r=>[r.week,r])).values()].sort((a,b)=>a.week-b.week);
 if(!rounds.length)return controls+blank(tr('Прогноз плей-офф недоступен','Playoff forecast unavailable'));
 return controls+rounds.map((round,i)=>{
  const a=prior.find(r=>r.week===round.week),b=next.find(r=>r.week===round.week);
  const ids=[...new Set([...(a?.opponents??[]),...(b?.opponents??[])].map(m=>m.opponent_id))];
  const pairs=ids.map(id=>({id,left:a?.opponents.find(m=>m.opponent_id===id),right:b?.opponents.find(m=>m.opponent_id===id)}));
  const title=`<h3>${playoffRoundName(i,'championship')} <small>${E(playoffDateRange(round))}</small></h3>`;
  if(!pairs.length)return title+blank(tr('Нет возможных соперников','No possible opponents'));
  pairs.sort((x,y)=>Math.max(y.left?.p_meet??0,y.right?.p_meet??0)-Math.max(x.left?.p_meet??0,x.right?.p_meet??0));
  return title+table([opponent,tr('Шанс встречи','Chance to meet'),tr('Победа при встрече','Win if matched')],pairs.map(({id,left,right})=>{
   const meet=tradeMatchupOdds(a?(left?.p_meet??0):null,b?(right?.p_meet??0):null,pending&&!after);
   const win=tradeMatchupOdds(left?.p_win,right?.p_win,pending&&!after);
   const cell=o=>`<td>${o.comparison}<small>${o.change}</small></td>`;
   return `<tr><td>${E(tname(id))}</td>${cell(meet)}${cell(win)}</tr>`;
  }).join(''));
 }).join('');
}

function probabilityParams(){
 const custom={};
 if(s.rosterMode==='top_n')for(const team of teams)custom[team.team_id]=selected(team.team_id).map(p=>p.name).sort();
 return {period:settings.season.periods[s.period],simulation_mode:s.rosterMode,top_n_players:13,
  custom_rosters:custom,punt_categories:[...punts()].sort(),...(injuryMode()?{punt_team_id:myTeam}:{}),trials:10000,seed:20261116};
}
function probabilitySettingsKey(p){return JSON.stringify([p.period,p.simulation_mode,p.top_n_players,
 Object.entries(p.custom_rosters??{}).sort(([a],[b])=>+a-+b).map(([k,names])=>[String(k),[...names].sort()]),
 [...(p.punt_categories??[])].sort(),p.punt_team_id??null,p.trials,p.seed]);}
function probabilityMatchesCurrent(params){return !!params&&probabilitySettingsKey(params)===probabilitySettingsKey(probabilityParams());}
function probabilityCurrentResult(){return probabilityMatchesCurrent(probability.params)?probability.result:null;}
function probabilityAccept(job){
 probability.job=job;
 probability.busy=job.status==='running';
 if(job.status==='complete'&&probabilityMatchesCurrent(job.params)){
  probability.result=job.result;probability.params=job.params;probability.error='';
  probability.resultVersion=job.source_version;probability.resultDataVersion=job.data_version;
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
 const refresh=resource(refreshStatusPath(),60000);
 if(refresh.pending)return;
 const params=probabilityParams(),key=probabilitySettingsKey(params);
 const stamp=refresh.data?.data_version??refresh.data?.last_refresh_time??'';
 const needsPlayoffs=s.probView==='playoffs'&&probability.result&&
  probability.result.postseason?.version!==2&&!probability.result.postseason_error;
 const stale=needsPlayoffs||!probability.result||!probability.params||probabilitySettingsKey(probability.params)!==key||
  (refresh.data?.data_version?probability.resultDataVersion!==stamp:(stamp&&Date.parse(stamp)>Date.parse(probability.resultVersion||probability.result.metadata.as_of)));
 const attempt=key+'|'+stamp+(needsPlayoffs?'|playoffs':'');
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
function probabilityCategories(match){
 const rows=Object.entries(match.categories).map(([category,p])=>{
  const win=probabilityPercent(p.p_win),loss=probabilityPercent(p.p_loss);
  const edge=win===loss?0:p.p_win-p.p_loss;
  return `<tr><td>${E(category)}</td><td class="${edge>0?'bf-match-win-own':''}">${win}</td>
   <td>${probabilityPercent(p.p_tie)}</td><td class="${edge<0?'bf-match-win-opponent':''}">${loss}</td></tr>`;
 }).join('');
 return `<table class="bf-prob-categories bf-match-category"><thead><tr><th>${tr('Категория','Category')}</th>
  <th>${tr('Победа','Win')}</th><th>${tr('Ничья','Tie')}</th><th>${tr('Поражение','Loss')}</th></tr></thead><tbody>${rows}</tbody></table>`;
}
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
 return `<div class="pe-table-wrap"><table class="bf-prob-matrix bf-playoff-cut" style="--prob-width:${370+ranks.length*57}px"><colgroup><col style="width:200px"><col style="width:80px"><col style="width:90px">${ranks.map(()=>'<col style="width:57px">').join('')}</colgroup><thead><tr><th>${tr('Команда','Team')}</th><th>${tr('Ожид. место','Exp. rank')}</th><th>${tr('Плей-офф','Playoffs')}</th>${ranks.map(r=>`<th scope="col">${r}</th>`).join('')}</tr></thead><tbody>${d.standings.map(t=>`<tr class="${t.team_id===+s.probTeam?'bf-prob-selected':''}"><td><button class="bf-prob-team" data-action="prob-team" data-team="${t.team_id}" aria-expanded="${t.team_id===+s.probTeam}">${E(t.team_name)}</button></td><td>${fmt(t.expected_rank)}</td><td style="${tone((t.p_playoffs-.5)*6)}">${probabilityPercent(t.p_playoffs)}</td>${ranks.map(r=>{const p=t.rank_probabilities[r];return `<td style="${p?tone(p,maxima[r]||1):''}" title="${E(t.team_name)} · ${tr('Место','Rank')} ${r}: ${probabilityPercent(p)}">${p?fmt(p*100,1):'—'}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div>${probabilityTeamPanel(d)}`;
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
 const controls=`<div class="pe-controls">${segment([['ranks',tr('Места','Ranks')],['opponents',tr('Соперники','Opponents')],['playoffs',tr('Плей-офф','Playoffs')]],'probView')}</div>`;
 const views={ranks:probabilityRankResults,opponents:probabilityOpponentResults,playoffs:probabilityPlayoffResults};
 return controls+views[s.probView](d);
}

const playoffPercent=p=>p>0&&p<.001?'&lt;0.1%':probabilityPercent(p);

function probabilityPlayoffResults(d){
 if(d.postseason_error)return `<div class="pe-error" role="alert">${E(d.postseason_error)} ${button(tr('Повторить','Retry'),'prob-run')}</div>`;
 const playoffs=d.postseason;
 if(!playoffs)return blank(tr('Считаем плей-офф…','Calculating playoffs…'));
 const names=Object.fromEntries(d.standings.map(t=>[t.team_id,t.team_name]));
 const rows=[...playoffs.teams].sort((a,b)=>b.p_title-a.p_title||b.p_playoffs-a.p_playoffs);
 const headers=[tr('Команда','Team'),tr('Плей-офф','Playoffs'),tr('Полуфинал','Semifinal'),tr('Финал','Final'),tr('Титул','Champion')];
 const highest=Math.max(...rows.map(t=>t.p_title));
 const table=`<div class="pe-table-wrap"><table class="bf-prob-matrix bf-postseason-matrix" style="--prob-width:560px">
 <colgroup><col style="width:34%"><col><col><col><col></colgroup>
 <thead><tr>${headers.map(h=>`<th scope="col">${E(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(t=>{
  const selected=t.team_id===+s.probTeam;
  return `<tr class="bf-click-row ${selected?'bf-prob-selected':''}" data-action="prob-team" data-team="${t.team_id}">
  <td><button class="bf-prob-team" aria-expanded="${selected}">${E(names[t.team_id])}</button></td>
  ${[t.p_playoffs,t.p_semifinal,t.p_final].map(p=>`<td>${playoffPercent(p)}</td>`).join('')}
  <td style="${t.p_title?tone(t.p_title,highest):''}"><strong>${playoffPercent(t.p_title)}</strong></td></tr>`;
 }).join('')}</tbody></table></div>`;
 const team=rows.find(t=>t.team_id===+s.probTeam);
 return table+(team?playoffTeamDetails(playoffs,team,names):'');
}

function playoffRoundName(i,branch){
 if(branch!=='championship')return tr('Раунд ','Round ')+(i+1);
 return [tr('Четвертьфинал','Quarterfinal'),tr('Полуфинал','Semifinal'),tr('Финал','Final')][i];
}

function playoffDateRange(round){
 const dateFormat=new Intl.DateTimeFormat(uiLocale(),{day:'numeric',month:'short',timeZone:'UTC'});
 const from=new Date(round.start),to=new Date(round.end);
 return typeof dateFormat.formatRange==='function'?dateFormat.formatRange(from,to):
  `${dateFormat.format(from)} – ${dateFormat.format(to)}`;
}

function playoffTeamDetails(playoffs,team,names){
 const branches=[
  ['championship',tr('За титул','Championship')],
  ['placement',tr('За места 3–8','Places 3–8')],
  ['consolation',tr('Утешительная сетка','Consolation')],
 ];
 const schedule=playoffs.rounds.map(round=>({
  ...round,
  matchups:round.matchups.filter(m=>m.team_id===team.team_id),
 }));
 const available=branches.filter(([key])=>schedule.some(r=>r.matchups.some(m=>m.bracket===key)));
 const branch=(available.find(([key])=>key===probability.playoffBranch)??available[0])?.[0];
 const rounds=schedule.map((round,i)=>{
  const matches=round.matchups.filter(m=>m.bracket===branch).sort((a,b)=>b.p_meet-a.p_meet);
  return {...round,name:playoffRoundName(i,branch),matchups:matches,reach:sum(matches,m=>m.p_meet)};
 });
 const selected=rounds.find(r=>r.week===probability.playoffRound&&r.matchups.length)??rounds.find(r=>r.matchups.length);
 const title=`<div class="pe-section-head"><h2>${E(names[team.team_id])}</h2>
  <button class="pe-link" data-action="prob-close-team">${tr('Скрыть','Hide')}</button></div>
  ${available.length>1?`<div class="pe-segment bf-playoff-branches">${available.map(([key,label])=>
   `<button data-action="playoff-branch" data-branch="${key}" aria-pressed="${key===branch}">${label}</button>`).join('')}</div>`:''}`;
 const path=`<div class="bf-playoff-path" role="group" aria-label="${tr('Раунды','Rounds')}">${rounds.map(r=>
  `<button class="bf-playoff-step" data-action="playoff-round" data-week="${r.week}" aria-pressed="${selected===r}" ${r.matchups.length?'':'disabled'}>
   <span>${r.name}</span><small>${E(playoffDateRange(r))}</small>
   <strong title="${tr('Шанс сыграть в этом раунде','Chance to play this round')}">${r.matchups.length?playoffPercent(r.reach):'—'}</strong>
  </button>`).join('')}</div>`;
 const pairings=selected?`<table class="bf-postseason-pairs" aria-label="${E(selected.name)}"><thead><tr>
   <th>${tr('Соперник','Opponent')}</th><th>${tr('Шанс встречи','Chance to meet')}</th><th>${tr('Победа при встрече','Win if matched')}</th>
  </tr></thead><tbody>${selected.matchups.map(m=>`<tr class="bf-click-row" data-action="playoff-pair"
   data-team="${team.team_id}" data-opponent="${m.opponent_id}" data-week="${selected.week}" data-branch="${branch}">
   <td><button class="bf-prob-team" aria-haspopup="dialog">${E(names[m.opponent_id])}</button></td>
   <td>${playoffPercent(m.p_meet)}</td><td style="${tone((m.p_win-.5)*6)}">${playoffPercent(m.p_win)}</td>
  </tr>`).join('')}</tbody></table>`:'';
 return `<section class="bf-prob-team-panel bf-playoff-team">${title}${path}${pairings}</section>`;
}
function probabilityOpenPair(team,opponent,week){
 const d=probabilityCurrentResult();if(!d||team===opponent)return;
 const plan=d.weeks.find(w=>w.week===week);
 const match=plan?.matchups.find(m=>[m.team1_id,m.team2_id].includes(team)&&[m.team1_id,m.team2_id].includes(opponent));
 if(!match)return;
 probability.matchDetail={week,match:probabilityViewMatch(match,team),standings:d.standings};
 s.overlay='prob-match';render();
}
function openPlayoffPair({team,opponent,week,branch}){
 const d=probabilityCurrentResult();
 const index=d?.postseason?.rounds.findIndex(r=>r.week===+week)??-1;
 if(index<0)return;
 const round=d.postseason.rounds[index];
 const match=round.matchups.find(m=>m.team_id===+team&&m.opponent_id===+opponent&&m.bracket===branch);
 if(!match)return;
 probability.matchDetail={match:{...match,team1_id:+team,team2_id:+opponent},standings:d.standings,
  roundName:playoffRoundName(index,branch),date:playoffDateRange(round),trials:d.trials};
 s.overlay='prob-match';
 render();
 app.querySelector('dialog [data-action="close"]')?.focus({preventScroll:true});
}

function probabilityMatchTitle(){
 const detail=probability.matchDetail;
 return detail?.roundName??(tr('Матчап · неделя ','Matchup · week ')+detail?.week);
}

function probabilityMatchDialog(){
 const detail=probability.matchDetail;if(!detail)return '';
 const {match,week,standings}=detail;
 const name=id=>standings.find(t=>t.team_id===id)?.team_name??'';
 if(detail.roundName){
  const categories=Object.keys(match.categories??{}).length?probabilityCategories(match):'';
  return `<div class="bf-prob-match-title bf-playoff-match-title">
   <span>${E(name(match.team1_id))}<strong class="bf-match-win-own">${playoffPercent(match.p_win)}</strong></span>
   <span>${E(name(match.team2_id))}<strong class="bf-match-win-opponent">${playoffPercent(1-match.p_win)}</strong></span></div>
   <div class="bf-prob-chances"><span>${E(detail.date)}</span>
   ${match.official?'':`<span>${tr('Шанс встречи','Chance to meet')} <strong>${playoffPercent(match.p_meet)}</strong></span>`}
   ${match.samples<100?`<span>${match.samples} / ${detail.trials} ${tr('прогонов','trials')}</span>`:''}</div>
   ${categories}`;
 }
 return `<div class="bf-prob-match-title"><span>${E(name(match.team1_id))}</span><span>${E(name(match.team2_id))}</span></div><div class="bf-prob-chances"><span>${tr('Победа','Win')} <strong>${probabilityPercent(match.p_win)}</strong></span><span>${tr('Ничья','Tie')} <strong>${probabilityPercent(match.p_tie)}</strong></span><span>${tr('Поражение','Loss')} <strong>${probabilityPercent(match.p_loss)}</strong></span><small>${match.official?tr('Матч по расписанию','Scheduled matchup'):tr('Гипотетический матч этой недели','Hypothetical matchup for this week')}</small></div>${probabilityCategories(match)}`;
}
function teamCategories(team){
 const controls=`<div class="pe-controls pe-row">${segment([['averages',tr('Средние','Averages')],['probability',tr('Вероятности','Probabilities')]],'categoryMode')}</div>`;
 if(s.categoryMode!=='probability')return controls+categoryTable(team);
 if(!probabilityEnabled())return controls+blank(tr('Вероятностный режим недоступен','Probabilistic mode unavailable'));
 const d=probabilityMaintain();
 const error=probability.error?`<div class="pe-error" role="alert">${E(probability.error)} <button class="pe-link" data-action="${probability.job?.status==='failed'?'prob-run':'prob-restore'}">${tr('Повторить','Retry')}</button></div>`:'';
 if(!d)return controls+error+(probability.error?'':`<div class="bf-prob-loading" role="status">…</div>`);
 const plans=[...d.weeks].sort((a,b)=>a.week-b.week).map(w=>{
  const match=w.matchups.find(m=>m.official&&[m.team1_id,m.team2_id].includes(team));
  return {week:w.week,match:match?probabilityViewMatch(match,team):null};
 });
 if(!plans.length)return controls+error+blank(tr('Нет оставшихся матчей','No remaining matchups'));
 const mean=values=>values.length?sum(values,x=>x)/values.length:null;
 const name=id=>d.standings.find(t=>t.team_id===id)?.team_name??tname(id);
 const rows=cats.map(cat=>{
  const values=plans.map(w=>w.match?.categories[cat]?.p_win).filter(finite),average=mean(values);
  return `<tr class="${punts().includes(cat)?'bf-punted':''}"><th scope="row">${E(cat)}</th>${plans.map(({week,match})=>{
   const p=match?.categories[cat]?.p_win;
   if(!finite(p))return '<td>—</td>';
   const label=`${cat} · ${tr('Неделя','Week')} ${week} · ${name(match.team2_id)}: ${probabilityPercent(p)}`;
   return `<td style="${tone((p-.5)*6)}"><button class="bf-prob-cell" data-action="prob-pair" data-opponent="${match.team2_id}" data-team="${team}" data-week="${week}" title="${E(label)}" aria-label="${E(label)}">${probabilityPercent(p)}</button></td>`;
  }).join('')}<td class="bf-category-prob-average" style="${finite(average)?tone((average-.5)*6):''}">${probabilityPercent(average)}</td></tr>`;
 }).join('');
 const expected=plans.map(({match})=>match?sum(cats,c=>match.categories[c]?.p_win??0):null);
 const footer=(label,values,show,scale)=>{const average=mean(values.filter(finite));return `<tr><th scope="row">${label}</th>${values.map((v,i)=>{
  const {week,match}=plans[i];
  const caption=`${label} · ${tr('Неделя','Week')} ${week} · ${match?name(match.team2_id):''}`;
  return `<td style="${finite(v)?tone(scale(v)):''}">${finite(v)&&match?`<button class="bf-prob-cell" data-action="prob-pair" data-team="${team}" data-opponent="${match.team2_id}" data-week="${week}" title="${E(caption)}" aria-label="${E(caption)}">${show(v)}</button>`:'—'}</td>`;
 }).join('')}<td class="bf-category-prob-average" style="${finite(average)?tone(scale(average)):''}">${show(average)}</td></tr>`;};
 return controls+error+`<div class="pe-table-wrap"><table class="bf-prob-opponents bf-category-probabilities" style="--prob-width:${170+plans.length*96+110}px" aria-label="${tr('Вероятности победы по категориям','Category win probabilities')}"><colgroup><col style="width:170px">${plans.map(()=>'<col style="width:96px">').join('')}<col style="width:110px"></colgroup><thead><tr><th>${tr('Категория','Category')}</th>${plans.map(w=>`<th scope="col" title="${w.match?E(name(w.match.team2_id)):''}">${tr('Неделя','Week')} ${w.week}</th>`).join('')}<th scope="col">${tr('Среднее','Average')}</th></tr></thead><tbody>${rows}</tbody><tfoot>${footer(tr('Ожид. категорий','Expected categories'),expected,v=>fmt(v,1),v=>(v/cats.length-.5)*6)}${footer(tr('Победа в матчапе','Matchup win'),plans.map(w=>w.match?.p_win),probabilityPercent,v=>(v-.5)*6)}</tfoot></table></div>`;
}
function probabilityMaintain(){
 const currentResult=probabilityCurrentResult();
 if(!currentResult&&s.overlay==='prob-match')s.overlay=null;
 if(!probability.restored)void probabilityRestore();
 probabilityAuto();
 if(!probability.refreshTimer)probability.refreshTimer=setTimeout(()=>{
  probability.refreshTimer=null;
  if(s.page==='simulations'&&s.simMode==='probabilistic'||s.page==='team'&&s.tab==='categories'&&s.categoryMode==='probability'){cache.delete(refreshStatusPath());render();}
 },60000);
 return currentResult;
}
function probabilisticPage(){
 const currentResult=probabilityMaintain();
 return `${probability.error?`<div class="pe-error" role="alert">${E(probability.error)} <button class="pe-link" data-action="${probability.job?.status==='failed'?'prob-run':'prob-restore'}">${tr('Повторить','Retry')}</button></div>`:''}
  <div aria-busy="${probability.busy||probability.restoring}">${currentResult?probabilityResults(currentResult):!probability.error?`<div class="bf-prob-loading" role="status" aria-label="${tr('Загрузка прогноза','Loading forecast')}">…</div>`:''}</div>`;
}

app.addEventListener('click',event=>{
 const el=event.target.closest('[data-action]');if(!el||el.disabled)return;
 if(el.dataset.action==='trade-matchups'){
  tradeProbability.matchTeam=+el.dataset.team;
  tradeProbability.matchView='regular';
  s.overlay='trade-matchups';
  render();
  app.querySelector('dialog [data-action="close"]')?.focus({preventScroll:true});
 }
 if(el.dataset.action==='trade-matchup-view'){
  tradeProbability.matchView=el.dataset.view;
  render();
  app.querySelector('dialog [data-action="trade-matchup-view"][aria-pressed="true"]')?.focus({preventScroll:true});
 }
 if(el.dataset.action==='prob-run')void probabilityRun();
 if(el.dataset.action==='prob-restore'){probability.error='';void probabilityRestore();}
 if(el.dataset.action==='prob-team'){
  const playoffs=el.closest('.bf-postseason-matrix');
  s.probTeam=+s.probTeam===+el.dataset.team?null:+el.dataset.team;
  probability.expanded=null;
  if(playoffs){probability.playoffBranch=null;probability.playoffRound=null;}
  save();render();
  if(playoffs&&s.probTeam)app.querySelector('.bf-playoff-team')?.scrollIntoView({block:'start'});
 }
 if(el.dataset.action==='prob-close-team'){s.probTeam=null;save();render();}
 if(el.dataset.action==='prob-match'){const key=`${el.dataset.week}:${el.dataset.opponent}`;probability.expanded=probability.expanded===key?null:key;render();}
 if(el.dataset.action==='prob-pair')probabilityOpenPair(+el.dataset.team,+el.dataset.opponent,+el.dataset.week);
 if(el.dataset.action==='playoff-branch'){
  probability.playoffBranch=el.dataset.branch;
  render();
  app.querySelector('.bf-playoff-branches [aria-pressed="true"]')?.focus({preventScroll:true});
 }
 if(el.dataset.action==='playoff-round'){
  probability.playoffRound=+el.dataset.week;
  render();
  app.querySelector('.bf-playoff-path [aria-pressed="true"]')?.focus({preventScroll:true});
 }
 if(el.dataset.action==='playoff-pair')openPlayoffPair(el.dataset);
});
