function uiLocale(){return s.lang==='en'?'en-US':'ru-RU';}
const UI_EN={
 'Команда':'Team','Лига':'League','Игроки':'Players','Матчапы':'Matchups','Обмены':'Trades','Симуляции':'Simulations','Настройки':'Settings','Закрыть':'Close',
 'Период':'Period','Состав':'Roster','Сезон':'Season','30 дней':'30 days','15 дней':'15 days','7 дней':'7 days','Взвешенный':'Weighted','Прогноз':'Projection',
 '13 выбранных':'13 selected','Без IR':'Exclude IR','Весь состав':'Full roster','Панты':'Punts','Колонки':'Columns','Статистика':'Statistics','Средние':'Averages','Сравнить':'Compare','Сравнить с…':'Compare with…',
 'Фильтр':'Filter','Свободные агенты':'Free agents','Игроки лиги':'League players','Найти игрока':'Find player','Все позиции':'All positions','Позиция':'Position','Игрок':'Player',
 'Загрузка…':'Loading…','Подключаем лигу…':'Connecting to league…','Обновляем статистику…':'Updating statistics…','Повторить':'Retry','Нет данных':'No data','Игроков нет':'No players',
 'Фильтр свободных агентов':'Free agent filters','Скрыть игроков без NBA-команды':'Hide players without an NBA team','Скрыть выбывших на сезон / 30+ дней':'Hide season-ending / 30+ day absences',
 'Загружаем статусы игроков…':'Loading player availability…','Статусы травм недоступны.':'Injury statuses unavailable.','Здоров':'Healthy','Статус неизвестен':'Status unknown','До конца сезона':'Out for season','Срок неизвестен':'Return date unknown',
 'Места':'Ranks','Значения':'Values','Матрица':'Matrix','Команды':'Teams','Выбрать состав':'Select roster','Выбрать топ-13':'Select top 13','Очистить':'Clear',
 'Сравнение игроков':'Player comparison','Общий Z':'Z-score','Z стратегии':'Z-score','Σ Z':'Z-score','Состав на день':'Daily lineup','Прогноз сезона':'Season projection','Оставшиеся матчапы':'Remaining matchups','Все матчапы':'All matchups',
 'Дата / игровой день':'Date / game day','Игроки в составе':'Starting lineup','Календарь':'Calendar','Категория':'Category','Средние состава':'Roster averages','Место по средним':'Rank by averages','Результат':'Result','Счёт':'Score','Неделя':'Week','Соперник':'Opponent',
 'Игрок недоступен':'Player unavailable','В сравнении ✓':'Selected ✓','В сравнение':'Compare','Профиль':'Profile','По периодам':'By period','Логи игр':'Game log','Старт':'Starter','Скамейка':'Bench','Роль':'Role','Мин.':'Min.',
 'По матчапам':'By matchups','По Z-score':'By Z-score','По средним':'By averages','По календарю':'By schedule','Одна неделя':'One week','Расчёт запускается по кнопке':'',
 'игр':'games','в составе':'in lineup','в резерве':'on bench','В составе':'In lineup','Резерв':'Bench','Игра':'Game','Игр':'Games','Место':'Rank','В':'W','П':'L','Н':'T','Побед, %':'Win, %',
 'Оценить обмен':'Evaluate trade','Анализируем…':'Analyzing…','Отдаём':'Sending','Получаем':'Receiving','Игроки не выбраны':'No players selected','Без изменения':'Unchanged','Место по Z':'Rank by Z','Прогноз места':'Projected rank',
 'До':'Before','После':'After','Сбросить к топ-13':'Reset to top 13','Игроков по этим фильтрам нет':'No matching players','Матчапов нет':'No matchups',
 'Неверный состав':'Invalid roster','Не удалось получить данные ESPN':'Unable to load ESPN data','ESPN недоступен. Повторите попытку позже.':'ESPN is unavailable. Try again later.'
};
function translateText(value){let text=value.replace(/Z стратегии|Σ Z/g,'Z-score');if(s.lang!=='en')return text;const lead=text.match(/^\s*/)[0],tail=text.match(/\s*$/)[0],v=text.trim();if(UI_EN[v]!=null)return lead+UI_EN[v]+tail;return text
 .replace(/Матчап · неделя (\d+)/g,'Matchup · week $1').replace(/Неделя (\d+)/g,'Week $1').replace(/Неделя /g,'Week ')
 .replace(/Последние (\d+) недели/g,'Last $1 weeks').replace(/Возвращение · /g,'Expected return · ').replace(/Текущий матчап · /g,'Current matchup · ')
 .replace(/Статусы травм недоступны\./g,'Injury statuses unavailable.').replace(/Сравнить · (\d+)/g,'Compare · $1')
 .replace(/Добавить в сравнение /g,'Add to comparison ').replace(/Убрать из сравнения/g,'Remove from comparison').replace(/Убрать /g,'Remove ')
 .replace(/ в составе/g,' in lineup').replace(/ в резерве/g,' benched').replace(/ игр/g,' games').replace(/ игроков/g,' players').replace(/ команд/g,' teams').replace(/День (\d+)/g,'Day $1');}
function translateUI(root){document.documentElement.lang=s.lang;const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const texts=[];while(walker.nextNode())texts.push(walker.currentNode);for(const node of texts)if(!['STYLE','SCRIPT'].includes(node.parentElement?.tagName))node.textContent=translateText(node.textContent);root.querySelectorAll('[aria-label],[placeholder],[title]').forEach(el=>{for(const attr of ['aria-label','placeholder','title'])if(el.hasAttribute(attr))el.setAttribute(attr,translateText(el.getAttribute(attr)));});}
