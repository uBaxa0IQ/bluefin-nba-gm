'use strict';

const matchupTimelinePath=(team,week)=>`/api/dashboard/${team}/matchup-timeline?week=${week}`;
const matchupDetailsPath=(team,week)=>`/api/dashboard/${team}/matchup-details?week=${week}&include_game_usage=false`;

function matchupTimeline(team, week, matchup){
 const title=tr('Шансы по ходу матчапа','Matchup win probability');
 const path=matchupTimelinePath(team,week);
 const entry=resource(path);
 let content;
 if(entry.pending){
  content=`<p class="bf-odds-state" role="status">${tr('Восстанавливаем хронологию матчапа…','Reconstructing the matchup timeline…')}</p>`;
 }else if(entry.error){
  content=`<div class="bf-odds-state"><span>${tr('График временно недоступен','Timeline temporarily unavailable')}</span><button class="pe-link" data-odds-retry="${E(path)}">${tr('Повторить','Retry')}</button></div>`;
 }else if(!entry.data?.points?.length){
  content=`<p class="bf-odds-state">${tr('Нет данных для графика','No timeline data')}</p>`;
 }else{
  content=matchupOddsChart(entry.data,matchup);
 }
 return `<section class="bf-match-odds" aria-label="${E(title)}"><h3>${title}</h3>${content}</section>`;
}

function matchupOddsChart(data, matchup){
 const points=data.points;
 const hasTrend=points.length>1;
 const W=800,H=210,mid=H/2;
 const x=i=>hasTrend?i*W/(points.length-1):0;
 const equity=p=>p.p_win+p.p_tie/2;
 const y=p=>5+(1-equity(p))*(H-10);
 const coordinates=points.map((p,i)=>`${x(i)},${y(p)}`).join(' ');
 const dateFormat=new Intl.DateTimeFormat(uiLocale(),{month:'short',day:'numeric'});
 const timeFormat=new Intl.DateTimeFormat(uiLocale(),{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
 const pct=p=>fmt(100*p,1)+'%';
 const dates=points.map(p=>dateFormat.format(new Date(p.at)));
 const labels=dates.flatMap((label,index)=>label!==dates[index-1]?[{index,label}]:[]);
 if(labels.length>1)labels.at(-1).index=points.length-1;
 const ticks=labels.filter((tick,i)=>i===0||i===labels.length-1||
  (tick.index>=3&&points.length-1-tick.index>=3&&tick.index-labels[i-1].index>=3));
 const rows=points.map((p,i)=>{
  const balance=equity(p);
  const state=balance===.5?'level':balance>.5?'ahead':'behind';
  const label=p.game?[`${p.game}`,timeFormat.format(new Date(p.at)),p.final?tr('Итог матчапа','Matchup final'):''].filter(Boolean).join(' · '):
   tr('Перед началом матчапа','Before the matchup');
  const detail=`${matchup.my_team.name} ${pct(p.p_win)} · ${matchup.opponent.name} ${pct(p.p_loss)}${p.p_tie?(' · '+tr('Ничья','Tie')+' '+pct(p.p_tie)):''}`;
  return {label,detail,marker:`<span class="${i===points.length-1?'selected':''}" data-odds-mark data-label="${E(label)}" data-value="${E(detail)}" data-state="${state}"
   style="left:${100*x(i)/W}%;top:${100*y(p)/H}%"></span>`};
 });
 const latest=rows.at(-1);
 return `<div class="bf-odds-legend"><span>${E(matchup.my_team.name)}</span><span>${E(matchup.opponent.name)}</span></div>
  <div class="bf-odds-plot">
   <div class="bf-odds-scale" aria-hidden="true"><span>100%</span><strong>50%</strong><span>0%</span></div>
   <div class="bf-odds-canvas" data-odds-plot data-index="${points.length-1}" tabindex="0"
    aria-label="${hasTrend?tr('Шансы по матчам NBA. Стрелки влево и вправо выбирают игру.','Odds after each NBA game. Use the arrow keys to select a game.'):tr('Стартовые шансы','Opening odds')}"
    aria-description="${E(latest.label+'. '+latest.detail)}">
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
     <defs>
      <clipPath id="bf-odds-ahead"><rect width="${W}" height="${mid}"/></clipPath>
      <clipPath id="bf-odds-behind"><rect y="${mid}" width="${W}" height="${mid}"/></clipPath>
      <linearGradient id="bf-odds-good" x2="0" y2="100%" gradientUnits="objectBoundingBox"><stop class="bf-odds-gradient-ahead" stop-opacity=".31"/><stop offset="100%" class="bf-odds-gradient-ahead" stop-opacity="0"/></linearGradient>
      <linearGradient id="bf-odds-bad" x2="0" y2="100%" gradientUnits="objectBoundingBox"><stop class="bf-odds-gradient-behind" stop-opacity="0"/><stop offset="100%" class="bf-odds-gradient-behind" stop-opacity=".32"/></linearGradient>
     </defs>
     ${[5,H/4,mid,H*3/4,H-5].map(v=>`<line class="${v===mid?'bf-odds-parity':'bf-odds-grid'}" x1="0" y1="${v}" x2="${W}" y2="${v}"/>`).join('')}
     ${hasTrend?`<polygon class="bf-odds-area-ahead" clip-path="url(#bf-odds-ahead)" points="0,${mid} ${coordinates} ${W},${mid}"/>
     <polygon class="bf-odds-area-behind" clip-path="url(#bf-odds-behind)" points="0,${mid} ${coordinates} ${W},${mid}"/>
     <polyline class="bf-odds-line bf-odds-ahead" clip-path="url(#bf-odds-ahead)" points="${coordinates}"/>
     <polyline class="bf-odds-line bf-odds-behind" clip-path="url(#bf-odds-behind)" points="${coordinates}"/>`:''}
    </svg>
    ${rows.map(row=>row.marker).join('')}
   </div>
   <div class="bf-odds-days" aria-hidden="true">${ticks.map(t=>`<span style="left:${100*x(t.index)/W}%">${E(t.label)}</span>`).join('')}</div>
  </div>
  <div class="bf-odds-readout"><span data-odds-label>${E(latest.label)}</span><strong data-odds-value>${E(latest.detail)}</strong></div>`;
}

function selectMatchupOddsPoint(plot, index){
 const marks=[...plot.querySelectorAll('[data-odds-mark]')];
 const selected=Math.max(0,Math.min(marks.length-1,index));
 if(!marks.length)return;
 const mark=marks[selected];
 plot.querySelector('.selected')?.classList.remove('selected');
 mark.classList.add('selected');
 plot.dataset.index=selected;
 const section=plot.closest('.bf-match-odds');
 section.querySelector('[data-odds-label]').textContent=mark.dataset.label;
 section.querySelector('[data-odds-value]').textContent=mark.dataset.value;
 plot.setAttribute('aria-description',`${mark.dataset.label}. ${mark.dataset.value}`);
}

function pointAtPointer(event){
 const plot=event.target.closest('[data-odds-plot]');
 if(!plot)return;
 const {left,width}=plot.getBoundingClientRect();
 const index=Math.round((event.clientX-left)/width*(plot.querySelectorAll('[data-odds-mark]').length-1));
 if(index!==+plot.dataset.index)selectMatchupOddsPoint(plot,index);
}

app.addEventListener('pointermove',pointAtPointer);
app.addEventListener('pointerdown',pointAtPointer);
app.addEventListener('keydown',event=>{
 const plot=event.target.closest('[data-odds-plot]');
 if(!plot||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
 event.preventDefault();
 const index=+plot.dataset.index;
 selectMatchupOddsPoint(plot,{ArrowLeft:index-1,ArrowRight:index+1,Home:0,End:Infinity}[event.key]);
});
app.addEventListener('click',event=>{
 const retry=event.target.closest('[data-odds-retry]');
 if(!retry)return;
 cache.delete(retry.dataset.oddsRetry);
 render();
});

async function refreshMatchupResource(path){
 const previous=cache.get(path);
 if(!previous||previous.pending||previous.refreshing)return false;
 previous.refreshing=true;
 try{
  const data=await request(path);
  if(cache.get(path)!==previous)return false;
  cache.set(path,{data,created:Date.now(),pending:false});
  return JSON.stringify(data)!==JSON.stringify(previous.data);
 }catch{
  return false;
 }finally{
  previous.refreshing=false;
 }
}

setInterval(async()=>{
 if(s.overlay!=='match'||s.detail.week!==weeks.current_week||document.hidden)return;
 const {team,week}=s.detail;
 const changed=await Promise.all([
  refreshMatchupResource(matchupDetailsPath(team,week)),
  refreshMatchupResource(matchupTimelinePath(team,week)),
 ]);
 if(changed.some(Boolean)&&s.overlay==='match'&&s.detail.team===team&&s.detail.week===week)render();
},60000);
