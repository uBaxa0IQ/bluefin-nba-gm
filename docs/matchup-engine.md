# Calendar matchup engine

The application offers `calendar` (default) and `legacy` (averages/Z-score).
The seasonal probability engine and `/api/matchup/odds` endpoint have been removed.
Saved browser engine settings other than `legacy` migrate to `calendar`.
Draft simulations and draft ML are separate and remain available.

## Roster membership

- `top_n`: use the explicit `custom_team_players` selection, including selected IR
  players. Without a manual selection, take the top `top_n_players` by total Z.
- `exclude_ir`: use all rostered players except those in the IR slot.

Saved browser settings for the former full-roster option migrate to `exclude_ir`.
API callers can still request `all` explicitly to include every rostered player.

The `top_n` and `exclude_ir` browser modes assume selected players play their scheduled games.

The «С учётом травм» roster option uses `injury_aware`. The forecast reads the public
ESPN injury report and the league's roster limit. It excludes OUT players until
their estimated return date in NBA calendar time. OUT without a usable date
remains unavailable in that forecast. On return from IR, a full roster drops its
eligible player with the lowest overall Z-score on the activation day. A player
already occupying a regular slot returns without a roster move. An explicit ESPN
undroppable flag protects the player. When punts are enabled, the main team's
drop and lineup scores use its active categories. Opponents use their overall Z.
API callers identify the main team with `punt_team_id`. Simulated drops persist through later weeks
and are visible in the roster timeline. They affect neither credited scores nor ESPN.

Calendar and Monte Carlo forecasts, including forecasts for trades and add/drop
scenarios, use this policy. The two sides of an exchange receive independent
roster timelines. Undated averages and Z views, including trade rankings, use
the same membership as «Без IR» in injury mode: players in regular slots count
even when OUT, and players in IR are excluded until their actual activation.

## Calculation

For each scoring day, the Hungarian assignment algorithm places scheduled players
in valid ESPN active slots. It accounts for multi-position eligibility and daily
slot competition. Only selected starter-games contribute per-game statistics.
Percentages and A/TO are recomputed from summed component statistics.

Current-week remaining projections add accrued ESPN totals where applicable and
exclude already started games from future production. Opponent-aware lineup and
add/drop utility remains a heuristic, not a calibrated win probability.

Roster selection is applied consistently to team, league, scheduled-week and
season projections, lineup optimization, trade impact, add/drop recommendations
and future player-game counts. Historical counted games remain observed data.

## API

- `GET /api/projections/team/{team_id}`
- `GET /api/projections/league`
- `GET /api/projections/matchups`
- `GET /api/projections/season`
- `GET /api/lineup/{team_id}/optimize`
- `GET /api/free-agent-recommendations/{team_id}`

Projection endpoints accept `simulation_mode`, `top_n_players` and a comma-separated
`custom_team_players` selection; league endpoints use `custom_team_id` for the
manual selection. Other teams use the same mode with automatic top-N selection.
Trade endpoints accept the existing per-team selection map and apply roster
membership consistently before and after the proposed exchange.

Forecast history retains compatibility with existing SQLite databases. Calendar
validation reports category MAE and matchup-result accuracy after observed results
become available; retired probability fitting and metrics are no longer computed.
