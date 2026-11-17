# Calendar Monte Carlo engine (v1)

The engine can run from the CLI without starting the frontend or backend. It supports
ESPN H2H Most Categories leagues with one division and H2H_RECORD playoff seeding.
It simulates final **regular-season positions**, not playoff-bracket championships.

## Web interface

The application exposes the engine under **Симуляции → Вероятностный**.
The view automatically submits the current statistics period, roster mode, resolved
manual selections and punt settings, always using 10,000 trials. There is no run
button, trial-count picker or calculation metadata panel.
Calculations run in one background worker, so the app remains usable. Identical
requests for the same league snapshot reuse the existing job. A second different
job is rejected while the worker is busy.

The view has two modes: **Места** (final rank probabilities) and **Соперники**
(a weekly matrix of every team against every opponent). A matrix cell is the
probability that its row team beats its column team, using that week's calendars.
Click a cell to open the category probabilities; diagonal cells are not interactive.
The chosen mode and matrix week survive navigation and reload.

Click a team in the rank table to see its official remaining schedule, then a week
to see category probabilities. The Any Opponent view in that panel is also available.
All values in the rank grid are percentages.

**Составы расчёта** displays the archived roster names in the displayed result's
`metadata.rosters`, with a team selector. It never substitutes the current browser
selection for the archived one. Changing views, weeks or the roster viewer does not
start another calculation. Matchup and roster dialogs keep the clicked result snapshot
if a newer calculation finishes while they are open.

Completed jobs persist under `.cache/probabilistic/<league>-<season>/` and are
restored after navigation or reload. Changed settings/data automatically trigger a debounced recalculation. A previous
result stays visible only if its input settings still match. A result for a different
roster is never restored or displayed, including late completions of older jobs. Data freshness is checked every minute while the
view is open. A failed recalculation preserves the last good result.
Restarted servers mark interrupted jobs as failed instead of polling forever.
Backend code changes require restarting a server launched without `--reload`.

API:

- `POST /api/probabilistic/jobs`: submit settings; returns job ID and status.
- `GET /api/probabilistic/jobs/{job_id}`: progress or full completed result.
- `GET /api/probabilistic/latest`: last successful result for the active league.

Run from the project root:

```powershell
.venv/Scripts/python.exe scripts/run_monte_carlo.py --trials 10000 --output .cache/monte_carlo/first-run
```

Default roster mode is `top_n`, 13 players per team, using exactly the existing
calendar roster selector. `--roster-mode all` and `--roster-mode exclude_ir` are
available. To reproduce manually selected website rosters, pass `--rosters picks.json`
with a JSON object mapping team IDs to player names. `--punts PTS,FT%` affects lineup
selection only; all actual scoring categories still determine matchup winners.

The engine does not read browser localStorage. Default runs therefore use automatic
top-13 rosters, not any browser-specific manual picks or punts.

## Outputs

- `inputs.json`: frozen, credential-free calendar plans and player distributions.
- `result.json`: complete model output, input metadata, history coverage and assumptions.
- `rank_probabilities.csv`: probability of each final rank and making the playoff field.
- `matchup_probabilities.csv`: both directions of every pair of teams for each remaining week.
  Only `official=true` pairs affect the simulated standings. Other pairs answer the
  hypothetical question of playing that opponent **in that same week**, using both
  teams' NBA calendars. There is no calendar-independent head-to-head probability.
- `summary.txt`: short text report for every team.

Probabilities are fractions between 0 and 1, never percentages in the stored data.
Rank probability sums are one per team and one per position across the league.
The sum of playoff probabilities equals the number of playoff slots.

Replay without any ESPN requests:

```powershell
.venv/Scripts/python.exe scripts/run_monte_carlo.py --input .cache/monte_carlo/first-run/inputs.json --trials 10000 --seed 20261116 --output .cache/monte_carlo/replay
```

The same frozen inputs, seed and trial count reproduce the same probabilities.
Runtime metadata will differ. Cached public game logs live under
`.cache/monte_carlo/game_logs`; credentials and the mutable league object are never serialized.

## Model

1. Freeze a league snapshot, completed results, and ESPN's official fantasy schedule.
2. Reuse `get_matchup_scoring_periods`, `get_remaining_scoring_periods`,
   `select_projection_roster` and `build_matchup_lineups`. The NBA schedule and legal
   daily slots determine which player-games contribute, before any random stats are drawn.
3. Fetch full regular-season ESPN game logs. Exclude DNP, incomplete rows, duplicate events,
   and impossible shooting lines. Derive DD from that game's counting stats.
4. Sample whole stat lines, independently for each future player-game. Recent games
   have exponentially greater weight (20-game half-life, at most 60 games).
   With fewer than 8 current-season games, supplement with the previous season at
   weight 0.35. Coverage and effective sample size are included per player.
   Missing histories fail the run, rather than silently inventing variance or a fixed result.
5. Sum counting stats and makes/attempts, then derive FG%, FT%, 3PT% and A/TO.
   Freeze credited actual component totals for the current week and simulate only
   remaining games, following the calendar engine's exclusion of already-started games.
6. Compare categories. Respect reverse categories and the configured weekly stat
   tiebreaker (`STAT_POINTS` / the configured stat ID), or leave weekly ties intact.
7. Update records **only for official pairs** and seed the entire league jointly.
   Use winning percentage, H2H among tied teams when they have equal game counts,
   restarting after each assigned seed, then a seeded random coin flip.
   Multi-division or unsupported seeding rules fail explicitly.

Seeding follows ESPN's documented single-division sequence:
https://support.espn.com/hc/en-us/articles/47191901860884-H2H-Most-Categories-League-Playoff-Seeding-Tiebreakers

## Interpretation and limits

These are probabilities **conditional on the fixed rosters and availability**.
Injured selected players remain eligible, just as in the current calendar engine.
There are no stochastic absences, future trades, streaming, role-change forecasts,
opponent-strength adjustments, or shared game-level/team-level random effects.
Within a sampled game, stats remain related; outcomes of different players/games
are sampled independently. The model does not yet represent uncertainty about a
player's underlying long-term ability. Previous-season samples may have an outdated role.

Current-week aggregation requires credited shot components (FGM/FGA, FTM/FTA,
3PM/3PA) if actual stats are already nonzero. If an ESPN response exposes only
percentages, the run stops explicitly instead of combining percentages incorrectly.
An in-progress NBA game follows the existing calendar treatment: its current credited
totals are frozen and the unplayed part is not separately modeled.

No past rosters are reconstructed. Completed historical results are fixed ESPN
results; a consistency check prevents double-counting or accepting incomplete history.

At 10,000 trials the worst-case Monte Carlo standard error is 0.5 percentage points
(roughly ±1 percentage point at 95%). This is sampling noise, **not model accuracy**.
The model has not yet been calibrated or validated on held-out historical weeks.
Do not interpret high probabilities as evidence that future injuries or roster changes
are unlikely. The first live report is a model demonstration, not a measured accuracy claim.

## Trade rank distributions

Trade evaluation also starts an asynchronous paired forecast at
`POST /api/probabilistic/trade/jobs`; poll `/api/probabilistic/trade/jobs/{job_id}`.
It uses 3,000 trials for each side and only official matchups. Each player/week
has a stable random stream shared before and after the trade, including when
the player's fantasy team or selected game count changes. Completed results and
current-week credited totals stay fixed; future lineups are rebuilt after moving
players and carrying manual selections through the trade.

The running job publishes the baseline before calculating the after-trade result.
The trade results switch includes Probabilities: each category shows the average
win chance against that team's remaining official opponents, before and after
the trade, plus the difference in percentage points. These values are aggregated
from the same paired forecast, including correct away-team orientation; no extra
simulation is started by switching table modes. Missing future matchups display
a dash. Baseline probabilities stream first, with after/delta cells pending.
Baseline standings are cached in memory across proposals for the same league,
input-data version, period and roster settings. The UI shows two rank distributions,
expected ranks and playoff probabilities, and discards results when trade inputs
change. Errors in this forecast do not prevent the regular trade analysis.
The trial count is fixed server-side; worst-case sampling error is approximately
±1.8 percentage points at 95%, separate from model uncertainty.

## Validation

### Roster contribution

The team tab `Вклад состава` runs 3,000 paired trials per player via
`POST /api/probabilistic/contribution/jobs` and polls the returned job ID.
Each counterfactual removes only that player's remaining scheduled starts;
other starters and already credited totals are held fixed. There is no
replacement player or automatic bench promotion. Players outside the selected
lineups have zero future contribution under these assumptions.

Category cells show the average change in category win probability across
remaining official matchups (with player minus without, percentage points).
Expected wins sum the matchup win probability changes. Playoff contribution
is the probability difference; rank contribution is expected rank without minus
with. Positive values indicate benefit from keeping the player. These are
individual counterfactual effects, not additive shares of team strength.
Rows stream as they finish; settings changes invalidate the displayed result.

Punts in this table are presentation-only: column headers and values use the
existing muted `bf-punted` style. They do not change the contribution request,
automatic roster selection, or the probabilities.

### Cache keys

Probability jobs (season, trade, contribution) index completed disk results by
league, season, parameters and a content-based data version. Returning to an older
parameter combination reuses it, including after process restart and while a
different job runs. The data version includes player statistics, roster ownership,
positions, schedules, records, credited matchup scores, league rules and weighted
coefficients. Passing a scheduled tip-off invalidates future-only forecasts.
Unchanged ESPN refreshes leave this version stable. Probability caches also have
a six-hour freshness boundary matching the game-log cache policy. Calendar season
and ordinary trade responses use the same content version in bounded memory caches.
Increment `core.analytics_cache.CACHE_REVISION` when changing calculation semantics.

```powershell
.venv/Scripts/python.exe -m pytest tests/test_monte_carlo.py tests/test_calendar_selected_roster.py tests/test_projection.py tests/test_simulation.py -q
```
