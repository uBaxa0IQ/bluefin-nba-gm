Object.assign(s,{lang:'ru',coloring:'full',theme:document.documentElement.dataset.theme??'system',tradeMyTeam:null,rosterOpen:{give:true,receive:true},rosterScroll:{give:0,receive:0},giveSearch:'',receiveSearch:'',tradeValues:'raw',tradeSummaryOpen:false,analyticsMetric:'PTS',analyticsWindow:'20'});
try{const ui=JSON.parse(localStorage.getItem('bluefin-ui')??'{}');s.lang=ui.lang==='en'?'en':'ru';s.coloring=['full','text','none'].includes(ui.coloring)?ui.coloring:'full';}catch{}
function openRoute(page,pid){s.page=page;s.overlay=null;if(page==='team'){s.team=+pid||myTeam;s.tab='overview';s.compare=null;}if(page==='player'){s.player=pid;s.profileTab='profile';s.logsOffset=0;}history.replaceState(null,'','#'+page+(pid?'/'+encodeURIComponent(pid):''));render();}
app.addEventListener('click',async event=>{
 const el=event.target.closest('[data-page],[data-action],[data-set],[data-sort],[data-compare],[data-remove],[data-match],[data-sim-team]');if(!el||el.disabled)return;
 if(el.dataset.page){event.preventDefault();openRoute(el.dataset.page,el.dataset.id);return;}
 if(el.dataset.compare){toggleCompare(el.dataset.compare);render();return;}
 if(el.dataset.remove){s[el.dataset.remove]=s[el.dataset.remove].filter(n=>n!==el.dataset.name);invalidate();save();render();return;}
 if(el.dataset.sort){s.direction=s.sort===el.dataset.sort?-s.direction:-1;s.sort=el.dataset.sort;s.sortValues=s.values;render();return;}
 if(el.dataset.set){s[el.dataset.set]=el.dataset.value;if(el.dataset.set==='tradeValues')save();render();return;}
 if(el.dataset.match){s.detail={team:+el.dataset.match,week:+el.dataset.week};s.overlay='match';render();return;}
 if(el.dataset.simTeam){s.detail={team:+el.dataset.simTeam,path:el.dataset.source==='forecast'?seasonPath():simulationPath(),season:el.dataset.source==='forecast'||s.simMode==='calendar'};s.overlay='sim-details';render();return;}
 const action=el.dataset.action;
 if(action==='close'||action==='backdrop'&&event.target===el){s.overlay=null;render();return;}
 if(['settings','columns','filters','comparison','forecast'].includes(action)){s.overlay=action;if(action==='settings')s.pickTeam=s.page==='team'?s.team:myTeam;render();return;}
 if(action==='retry'){for(const [k,v] of cache)if(v.error)cache.delete(k);render();return;}
 if(action==='reload'){location.reload();return;}
 if(action==='compare-player'){toggleCompare(el.dataset.player);render();return;}
 if(action==='clear-comparison'){s.comparePlayers=[];save();render();return;}
 if(action==='reset-picks'){delete s.picks[s.pickTeam];invalidate();save();render();return;}
 if(action==='calendar-day'){s.calendarDay=+el.dataset.index;s.overlay='calendar-day';render();return;}
 if(action==='logs-prev'||action==='logs-next'){s.logsOffset=Math.max(0,s.logsOffset+(action==='logs-next'?15:-15));render();return;}
 if(action==='toggle-roster'){s.rosterOpen[el.dataset.side]=!s.rosterOpen[el.dataset.side];save();render();return;}
 if(action==='toggle-rosters'){const open=!(s.rosterOpen.give||s.rosterOpen.receive);s.rosterOpen={give:open,receive:open};save();render();return;}
 if(action==='trade'){
  s.tradeBusy=true;s.tradeError='';render();
  const body={my_team_id:s.tradeMyTeam,their_team_id:s.tradeTeam,i_give:[...s.give],i_receive:[...s.receive],period:settings.season.periods[s.period],simulation_mode:s.rosterMode,top_n_players:13,punt_categories:punts(),calculation_engine:'calendar',custom_team_players:s.rosterMode==='top_n'?{...s.picks,[s.tradeMyTeam]:selected(s.tradeMyTeam).map(p=>p.name),[s.tradeTeam]:selected(s.tradeTeam).map(p=>p.name)}:null};
  const fingerprint=JSON.stringify([s.tradeMyTeam,s.tradeTeam,s.give,s.receive,s.period,s.rosterMode,s.picks,punts()]);
  try{const d=await request('/api/bluefin/trade',{method:'POST',body:JSON.stringify(body)});if(fingerprint===JSON.stringify([s.tradeMyTeam,s.tradeTeam,s.give,s.receive,s.period,s.rosterMode,s.picks,punts()]))s.trade=d;}
  catch(e){s.tradeError=e.message;}finally{s.tradeBusy=false;render();}
 }
});
app.addEventListener('change',async event=>{
 const el=event.target;
 if(el.dataset.control){const k=el.dataset.control,previous=s[k];s[k]=['team','compare','pickTeam','week','simWeek','weeksCount','calendarWeek','tradeTeam','tradeMyTeam'].includes(k)?(+el.value||null):el.value;
  if(k==='tradeMyTeam'&&s.tradeMyTeam===s.tradeTeam){s.tradeTeam=previous;s.receive=[];}
  if(k==='tradeTeam'&&s.tradeMyTeam===s.tradeTeam){s.tradeMyTeam=previous;s.give=[];}
  if(k==='tradeTeam'||k==='tradeMyTeam'){if(k==='tradeTeam'){s.receive=[];s.receiveSearch='';s.rosterScroll.receive=0;}else{s.give=[];s.giveSearch='';s.rosterScroll.give=0;}invalidate();save();}
  if(k==='team'){s.tab='overview';s.compare=null;}
  if(k==='simWeek')s.weeksCount=Math.min(s.weeksCount,s.simWeek);
  if(k==='theme')s.theme=applyTheme(s.theme);
  if(['lang','coloring','theme'].includes(k))save();
  if(['period','rosterMode'].includes(k)){invalidate();save();if(k==='period'){await loadPlayers();return;}}
 }
 if(el.dataset.pick){const team=s.pickTeam,chosen=selected(team).map(p=>p.name);if(el.checked&&chosen.length>=13){el.checked=false;return;}s.picks[team]=el.checked?[...chosen,el.dataset.pick]:chosen.filter(n=>n!==el.dataset.pick);if(!s.picks[team].length){s.picks[team]=chosen;el.checked=true;return;}invalidate();save();}
 if(el.dataset.punt){s.punts=el.checked?[...s.punts,el.dataset.punt]:s.punts.filter(c=>c!==el.dataset.punt);invalidate();save();}
 if(el.dataset.toggle){s[el.dataset.toggle]=el.checked;invalidate();save();}
 if(el.dataset.column){s.columns=el.checked?[...s.columns,el.dataset.column]:s.columns.filter(c=>c!==el.dataset.column);save();}
 if(el.dataset.trade){const k=el.dataset.trade;s[k]=el.checked?[...s[k],el.value]:s[k].filter(v=>v!==el.value);invalidate();save();}
 render();
});
app.addEventListener('input',event=>{if(event.target.dataset.input){const k=event.target.dataset.input;s[k]=event.target.value;if(k==='giveSearch'||k==='receiveSearch'){s.rosterScroll[k==='giveSearch'?'give':'receive']=0;save();}render();}});
app.addEventListener('scroll',event=>{const side=event.target.dataset?.rosterScroll;if(side)s.rosterScroll[side]=event.target.scrollTop;},true);
app.addEventListener('toggle',event=>{if(event.target.hasAttribute('data-trade-summary')){s.tradeSummaryOpen=event.target.open;save();}},true);
document.addEventListener('keydown',e=>{
 if(e.key==='Escape'&&s.overlay){s.overlay=null;render();return;}
 const editing=e.target.closest('textarea,[contenteditable="true"],input:not([type="checkbox"]):not([type="radio"]),select');
 if(e.shiftKey&&e.code==='KeyP'&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!e.repeat&&!editing){e.preventDefault();s.puntsEnabled=!s.puntsEnabled;invalidate();save();render();return;}
 if((e.key==='Enter'||e.key===' ')&&e.target.matches('tr[data-match],tr[data-sim-team],.bf-chart-point')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}
});
render();start();
