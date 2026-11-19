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

OUT, DTD, other injury statuses and expected return dates never remove a selected
player from a calendar forecast. This is a scenario in which the chosen roster
plays its scheduled games. Injury labels remain visible, and injured assets
remain protected from automatic drop recommendations.

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
