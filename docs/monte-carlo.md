# Calendar Monte Carlo engine (v1)

The engine runs without frontend changes or a backend restart. It currently supports
ESPN H2H Most Categories leagues with one division and H2H_RECORD playoff seeding.
It simulates final **regular-season positions**, not playoff-bracket championships.

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

## Validation

```powershell
.venv/Scripts/python.exe -m pytest tests/test_monte_carlo.py tests/test_calendar_selected_roster.py tests/test_projection.py tests/test_simulation.py -q
```
