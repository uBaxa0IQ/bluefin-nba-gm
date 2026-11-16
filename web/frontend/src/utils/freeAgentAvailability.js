const DAY_MS = 86400000;
const NO_TEAM = new Set(['', 'FA', 'F/A', 'N/A', 'NA', 'NONE', 'NULL', '0', 'FREE AGENT', 'FREE AGENTS']);
const SEASON_OUT = new Set(['OUT_FOR_SEASON', 'SEASON_ENDING', 'SEASON_ENDING_INJURY']);

export function matchesFreeAgentAvailability(player, filters, now = new Date()) {
    if (filters.hideNoTeam && NO_TEAM.has(String(player.nba_team ?? '').trim().toUpperCase())) return false;
    if (!filters.hideLongTermInjuries) return true;
    const status = String(player.injury_status ?? '').trim().toUpperCase().replace(/[ -]+/g, '_');
    if (player.out_for_season || SEASON_OUT.has(status)) return false;
    const injured = player.injured || ['OUT', 'DTD', 'DAY_TO_DAY', 'QUESTIONABLE', 'DOUBTFUL', 'INJURY_RESERVE'].includes(status);
    if (!injured) return true;
    const parts = String(player.expected_return_date ?? '').match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!parts) return true;
    const returnDay = Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3]));
    const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    return returnDay - today < 30 * DAY_MS;
}
