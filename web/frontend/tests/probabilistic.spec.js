import { expect, test } from '@playwright/test';

const result = {
    trials: 10000,
    metadata: { as_of: '2026-11-16T15:00:00Z', rosters: { 1: ['Chet Holmgren'], 2: ['Rudy Gobert'] } },
    standings: [
        { team_id: 1, team_name: 'Team A', expected_rank: 1.3, p_playoffs: .7, rank_probabilities: { 1: .7, 2: .3 } },
        { team_id: 2, team_name: 'Team B', expected_rank: 1.7, p_playoffs: .3, rank_probabilities: { 1: .3, 2: .7 } },
    ],
    weeks: [{ week: 5, matchups: [{ team1_id: 1, team2_id: 2, official: true,
        p_win: .65, p_tie: .05, p_loss: .3,
        categories: { PTS: { p_win: .8, p_tie: 0, p_loss: .2 }, REB: { p_win: .5, p_tie: .1, p_loss: .4 } },
    }] }, { week: 6, matchups: [{ team1_id: 2, team2_id: 1, official: true,
        p_win: .4, p_tie: .1, p_loss: .5, categories: { PTS: { p_win: .4, p_tie: .1, p_loss: .5 } },
    }] }, { week: 7, matchups: [{ team1_id: 1, team2_id: 2, official: false,
        p_win: .9, p_tie: 0, p_loss: .1, categories: {},
    }] }],
};

async function setup(page, { failNext = false, extraPlayers = [], rosterMeta = [] } = {}) {
    let completed = null;
    let current = null;
    let starts = 0;
    const calls = [];
    await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        if (path === '/api/settings') return route.fulfill({ json: { features: { probabilistic: true }, season: {
            league_id: 123, year: 2027, default_team_id: 1, categories: ['PTS', 'REB'], reverse_categories: [],
            periods: { total: '2027_total', last_7: '2027_last_7' },
        } } });
        if (path === '/api/teams') return route.fulfill({ json: [
            { team_id: 1, team_name: 'Team A' }, { team_id: 2, team_name: 'Team B' },
        ] });
        if (path === '/api/weeks') return route.fulfill({ json: { current_week: 5, weeks: [4, 5], forecast_weeks: [5] } });
        if (path === '/api/all-players') return route.fulfill({ json: { players: [
            { player_id: 11, name: 'Player A', fantasy_team_id: 1, team_id: 1, position: 'PG', stats: { PTS: 10 }, z_scores: { PTS: 1 } },
            { player_id: 22, name: 'Player B', fantasy_team_id: 2, team_id: 2, position: 'PG', stats: { PTS: 9 }, z_scores: { PTS: .5 } },
            ...extraPlayers,
        ] } });
        if (path === '/api/bluefin/roster-meta') return route.fulfill({ json: { players: rosterMeta } });
        if (path === '/api/bluefin/injuries') return route.fulfill({ json: { players: [] } });
        if (path === '/api/bluefin/season') return route.fulfill({ json: { standings: [] } });
        if (path === '/api/refresh-status') return route.fulfill({ json: { last_refresh_time: '2026-11-16T14:00:00Z' } });
        if (path === '/api/probabilistic/latest') return route.fulfill({ json: { job: completed } });
        if (path === '/api/probabilistic/jobs') {
            const params = route.request().postDataJSON();
            calls.push(params);
            starts++;
            current = { job_id: String(starts).repeat(32), status: 'running', stage: 'simulation', params,
                source_version: '2026-11-16T14:00:00Z' };
            return route.fulfill({ json: current });
        }
        if (path.startsWith('/api/probabilistic/jobs/')) {
            if (failNext && starts === 2) return route.fulfill({ json: { ...current, status: 'failed', message: 'Попробуйте позже' } });
            completed = { ...current, status: 'complete', result: { ...result, trials: current.params.trials } };
            return route.fulfill({ json: completed });
        }
        return route.fulfill({ json: {} });
    });
    await page.goto('/#simulations/probabilistic');
    await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
    return calls;
}

test('automatically calculates 10000 runs, drills down and restores after reload', async ({ page }) => {
    const calls = await setup(page);
    await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
    expect(calls[0].custom_rosters).toEqual({ 1: ['Player A'], 2: ['Player B'] });
    expect(calls[0].trials).toBe(10000);
    await page.getByRole('button', { name: 'Team A', exact: true }).click();
    await page.locator('[data-action="prob-match"]').first().click();
    await expect(page.locator('.bf-prob-categories tbody tr')).toHaveCount(2);
    await page.getByRole('button', { name: 'Любой соперник', exact: true }).click();
    await expect(page.locator('.bf-prob-chances')).toContainText('65.0%');
    await page.reload();
    await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
    await expect(page.locator('.bf-prob-team-panel')).toBeVisible();
    await expect(page.locator('.bf-prob-chances')).toContainText('65.0%');
    await expect(page.locator('[data-control="probTrials"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Рассчитать', exact: true })).toHaveCount(0);
    await expect(page.locator('.bf-prob-result-meta, .bf-prob-stale, .bf-prob-controls')).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('migrates the saved full roster to exclude IR', async ({ page }) => {
    await page.addInitScript(() => {
        const key = 'bluefin-live-v1:123:2027';
        if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({ rosterMode: 'all' }));
    });
    const calls = await setup(page);
    expect(calls[0].simulation_mode).toBe('exclude_ir');
    expect(calls[0].custom_rosters).toEqual({});
    await page.locator('button[data-action="settings"]').click();
    const select = page.locator('[data-control="rosterMode"]');
    await expect(select).toHaveValue('exclude_ir');
    await expect(select.locator('option')).toHaveCount(3);
    await expect(select.locator('option[value="all"]')).toHaveCount(0);
});

test('injury mode persists and sends punts only for the selected main team', async ({ page }) => {
    await page.addInitScript(() => {
        const key = 'bluefin-live-v1:123:2027';
        if (!localStorage.getItem(key)) localStorage.setItem(key, JSON.stringify({ punts: ['PTS'], puntsEnabled: true }));
    });
    const calls = await setup(page);
    await page.locator('button[data-action="settings"]').click();
    await page.locator('[data-control="mainTeam"]').selectOption('2');
    const select = page.locator('[data-control="rosterMode"]');
    await expect(select.locator('option[value="injury_aware"]')).toHaveText('С учётом травм');
    await select.selectOption('injury_aware');
    await page.locator('[data-action="close"]').click();
    await expect.poll(() => calls.at(-1)).toMatchObject({
        simulation_mode: 'injury_aware', punt_team_id: 2, punt_categories: ['PTS'], custom_rosters: {},
    });
    await page.locator('body').press('Shift+P');
    await expect.poll(() => calls.at(-1)).toMatchObject({
        simulation_mode: 'injury_aware', punt_team_id: 2, punt_categories: [],
    });
    await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
    await page.reload();
    await page.locator('button[data-action="settings"]').click();
    await expect(select).toHaveValue('injury_aware');
});

test('league averages and Z keep ordinary-slot OUT players and exclude actual IR', async ({ page }) => {
    await page.addInitScript(() => {
        localStorage.setItem('bluefin-live-v1:123:2027', JSON.stringify({ rosterMode: 'injury_aware' }));
    });
    await setup(page, {
        extraPlayers: [{ player_id: 33, name: 'Player IR', fantasy_team_id: 1, position: 'C', stats: { PTS: 50 }, z_scores: { PTS: 5 } }],
        rosterMeta: [{ player_id: 11, injury_status: 'OUT' }, { player_id: 33, is_ir: true }],
    });
    await page.locator('[data-page="league"]').click();
    await page.locator('[data-set="matrix"][data-value="value"]').click();
    const points = page.locator('.bf-matrix tbody tr').filter({ hasText: 'Team A' }).locator('td').nth(1);
    await expect(points).toHaveText(/^10(?:\.0+)?$/);
    await page.locator('[data-set="matrixSource"][data-value="z"]').click();
    await expect(points).toHaveText('1.00');
});

test('team overview keeps seven rows and includes OUT players in ordinary slots', async ({ page }) => {
    await page.addInitScript(() => {
        localStorage.setItem('bluefin-live-v1:123:2027', JSON.stringify({ rosterMode: 'injury_aware' }));
    });
    await setup(page, {
        extraPlayers: Array.from({ length: 8 }, (_, i) => ({
            player_id: 30 + i, name: i === 7 ? 'Player IR' : 'Roster player ' + (i + 1),
            fantasy_team_id: 1, position: 'C', stats: { PTS: 5 }, z_scores: { PTS: .1 },
        })),
        rosterMeta: [{ player_id: 11, injury_status: 'OUT' }, { player_id: 37, is_ir: true }],
    });
    await page.route('**/api/bluefin/active-rosters?**', route => route.fulfill({
        json: { rosters: { 1: Array.from({ length: 7 }, (_, i) => 'Roster player ' + (i + 1)) } },
    }));
    await page.locator('header [data-page="team"]').first().click();
    const overview = page.locator('.bf-team-profile table tbody');
    await expect(page.locator('.pe-metrics')).toContainText('7 / 9');
    await expect(overview.locator('tr')).toHaveCount(7);
    await expect(overview).toContainText('Player A');
    await expect(overview).not.toContainText('Player IR');
    await expect(page.getByRole('button', { name: 'Все игроки · 9' })).toBeVisible();
    await page.getByRole('button', { name: 'Все игроки · 9' }).click();
    const roster = page.locator('.pe-main table tbody');
    await expect(roster.locator('tr')).toHaveCount(9);
    await expect(roster).toContainText('Player A');
    await expect(roster).toContainText('Player IR');
});

test('failed recalculation never presents a result for different settings', async ({ page }) => {
    const calls = await setup(page, { failNext: true });
    await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
    await page.locator('button[data-action="settings"]').click();
    await page.locator('[data-control="rosterMode"]').selectOption('exclude_ir');
    await page.locator('[data-action="close"]').click();
    await expect(page.getByRole('alert')).toContainText('Попробуйте позже');
    await expect(page.locator('.bf-prob-matrix')).toHaveCount(0);
    await page.getByRole('button', { name: 'Повторить', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect.poll(() => calls.length).toBe(3);
    expect(calls.every(p => p.trials === 10000)).toBe(true);
    expect(calls[1].simulation_mode).toBe('exclude_ir');
    await expect(page.locator('.bf-prob-stale')).toHaveCount(0);
});

test('weekly schedule matrix uses official row-team odds and opens categories without rerunning the engine', async ({ page }) => {
    const calls = await setup(page);
    await page.getByRole('button', { name: 'Соперники', exact: true }).click();
    await expect(page.locator('.bf-prob-opponents tbody tr')).toHaveCount(2);
    await expect(page.locator('[data-action="prob-pair"]')).toHaveCount(4);
    await expect(page.locator('[data-control="probMatrixWeek"]')).toHaveCount(0);
    await expect(page.locator('.bf-prob-opponents thead th')).toHaveText(['Команда', 'Неделя 5', 'Неделя 6', 'Неделя 7']);
    await expect(page.locator('.bf-prob-opponents tbody tr').first().locator('td')).toHaveText(['65.0%', '50.0%', '—']);
    await expect(page.locator('[data-action="prob-pair"][data-team="2"][data-week="6"]')).toHaveText('40.0%');
    await expect(page.locator('[data-action="prob-pair"][data-team="1"][data-week="5"]')).toHaveText('65.0%');
    await expect(page.locator('[data-action="prob-pair"][data-team="2"][data-week="5"]')).toHaveText('30.0%');
    await page.locator('[data-action="prob-pair"][data-team="2"][data-week="5"]').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.locator('.bf-prob-categories tbody tr')).toHaveCount(2);
    await expect(dialog.locator('.bf-prob-categories tbody tr').first()).toContainText('20.0%');
    await expect(dialog.locator('.bf-prob-chances')).toContainText('30.0%');
    await page.locator('[data-action="close"]').click();
    await page.reload();
    await expect(page.locator('.bf-prob-opponents tbody tr')).toHaveCount(2);
    expect(calls).toHaveLength(1);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('calculation rosters show the archived players rather than the current browser selection', async ({ page }) => {
    const calls = await setup(page);
    await page.getByRole('button', { name: 'Составы расчёта', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.locator('.bf-prob-roster-list')).toContainText('Chet Holmgren');
    await expect(dialog.locator('.bf-prob-roster-list')).not.toContainText('Player A');
    await dialog.locator('[data-control="probRosterTeam"]').selectOption('2');
    await expect(dialog.locator('.bf-prob-roster-list')).toContainText('Rudy Gobert');
    expect(calls).toHaveLength(1);
});

test('saved trades stay in browser storage and load without evaluating the trade', async ({ page }) => {
    await setup(page);
    let evaluations = 0;
    await page.route('**/api/bluefin/trade', route => { evaluations++; return route.fulfill({ json: {} }); });
    await page.locator('[data-page="trades"]').first().click();
    await page.locator('[data-control="tradeMyTeam"]').selectOption('1');
    await page.locator('[data-control="tradeTeam"]').selectOption('2');
    await page.locator('[data-trade="give"]').first().check();
    await page.locator('[data-trade="receive"]').first().check();
    await page.locator('[data-action="save-trade"]').click();
    await expect(page.locator('[data-action="save-trade"]')).toBeDisabled();
    const stored = await page.evaluate(() => JSON.parse(localStorage.getItem('bluefin-saved-trades:123:2027')));
    expect(stored).toHaveLength(1);
    expect(stored[0].teams[0].players[0].player_id).toBe('11');
    await page.reload();
    await page.locator('[data-page="trades"]').first().click();
    await page.locator('[data-trade="give"]').first().uncheck();
    await page.locator('[data-action="saved-trades"]').click();
    await expect(page.locator('.bf-saved-trade')).toHaveCount(1);
    await expect(page.locator('.bf-saved-trade')).toContainText('Player A');
    await expect(page.locator('.bf-saved-trade')).toContainText('Player B');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.getByRole('dialog').evaluate(d => d.scrollWidth <= d.clientWidth)).toBe(true);
    await page.locator('[data-action="saved-trade-load"]').click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.locator('[data-trade="give"]').first()).toBeChecked();
    await expect(page.locator('[data-trade="receive"]').first()).toBeChecked();
    expect(evaluations).toBe(0);
    await page.locator('[data-action="saved-trades"]').click();
    await page.locator('[data-action="saved-trade-delete"]').click();
    await expect(page.locator('.bf-saved-trade')).toHaveCount(0);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('bluefin-saved-trades:123:2027')))).toEqual([]);
});

test('team category probabilities reuse the season result, orient odds and show category details', async ({ page }) => {
    const calls = await setup(page);
    await page.route('**/api/bluefin/season?*', route => route.fulfill({ json: { standings: [] } }));
    await page.locator('nav [data-page="team"]').click();
    await page.locator('[data-set="tab"][data-value="categories"]').click();
    await expect(page.locator('[data-set="categoryMode"]')).toHaveCount(2);
    await page.locator('[data-set="categoryMode"][data-value="probability"]').click();
    const matrix = page.locator('.bf-category-probabilities');
    await expect(matrix.locator('tbody tr').first().locator('td')).toHaveText(['80.0%', '50.0%', '—', '65.0%']);
    await expect(matrix.locator('tbody tr').nth(1).locator('td')).toHaveText(['50.0%', '—', '—', '50.0%']);
    await matrix.locator('tbody [data-action="prob-pair"]').first().click();
    await expect(page.getByRole('dialog', { name: 'Матчап · неделя 5' })).toBeVisible();
    await expect(page.locator('.bf-prob-categories tbody tr')).toHaveCount(2);
    await expect(page.locator('.bf-prob-chances')).toContainText('65.0%');
    await expect(page.locator('.bf-prob-categories')).toContainText('80.0%');
    await page.locator('[data-action="close"]').click();
    for (let i = 0; i < 2; i++) {
        await matrix.locator('tfoot tr').nth(i).locator('button').first().click();
        await expect(page.getByRole('dialog', { name: 'Матчап · неделя 5' })).toBeVisible();
        await expect(page.locator('.bf-prob-categories tbody tr')).toHaveCount(2);
        await page.locator('[data-action="close"]').click();
    }
    await page.locator('nav [data-page="league"]').click();
    await page.locator('[data-page="team"][data-id="2"]').first().click();
    await page.locator('[data-set="tab"][data-value="categories"]').click();
    await expect(matrix.locator('tbody tr').first().locator('td')).toHaveText(['20.0%', '40.0%', '—', '30.0%']);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: 'E:/NBAFantasyAnalytics/.cache/category-probabilities-mobile.png', fullPage: true });
    expect(calls).toHaveLength(1);
});

test('roster contribution streams rows, opens details and drops results after a settings change', async ({ page }) => {
    await setup(page);
    await page.route('**/api/bluefin/season?*', route => route.fulfill({ json: { standings: [] } }));
    const base = { ...result.standings[0], expected_record: { wins: 8, losses: 4, ties: 0 } };
    const row = { player_id: 11, name: 'Player A', games: 30, category_deltas: { PTS: .12, REB: -.03 },
        win_delta: 1.25, playoff_delta: .15, rank_delta: 1.1,
        without: { ...base, expected_rank: 2.4, p_playoffs: .55, expected_record: { wins: 6.75, losses: 5.25, ties: 0 } },
        weeks: [{ week: 5, opponent_id: 2, p_win: .7, without_p_win: .4, win_delta: .3 }],
    };
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let calls = 0;
    await page.route('**/api/probabilistic/contribution/jobs', route => {
        calls++;
        expect(route.request().postDataJSON().team_id).toBe(1);
        expect(route.request().postDataJSON().trials).toBe(3000);
        return route.fulfill({ json: { job_id: 'c'.repeat(32), status: 'running' } });
    });
    await page.route('**/api/probabilistic/contribution/jobs/*', async route => {
        await gate;
        await route.fulfill({ json: { status: 'complete', result: { baseline: { standing: base }, players: [row] } } });
    });
    await page.locator('nav [data-page="team"]').click();
    await page.locator('[data-set="tab"][data-value="contribution"]').click();
    await expect(page.locator('button[data-action="contribution-player"]')).toBeDisabled();
    release();
    await expect(page.locator('.bf-contribution-table tbody')).toContainText('+12.0');
    await expect(page.locator('.bf-contribution-table tbody')).toContainText('-3.0');
    const contributionTable = page.locator('.bf-contribution-table');
    await contributionTable.getByRole('button', { name: 'PTS', exact: true }).click();
    await contributionTable.getByRole('button', { name: 'REB', exact: true }).click({ modifiers: ['Shift'] });
    await expect(contributionTable.locator('caption')).toHaveText('PTS + REB ↓');
    const beforePunts = calls;
    await page.getByRole('button', { name: /Настройки/ }).click();
    await page.locator('[data-punt="PTS"]').check();
    await page.locator('[data-action="close"]').click();
    await expect(page.locator('.bf-contribution-table thead th').nth(1)).toHaveClass('bf-punted');
    await expect(page.locator('.bf-contribution-table tbody td').first()).toHaveClass('bf-punted');
    await expect(page.locator('.bf-contribution-table tbody td').first()).toHaveText('+12.0');
    expect(calls).toBe(beforePunts);
    await page.locator('button[data-action="contribution-player"]').click();
    await expect(page.getByRole('dialog', { name: 'Player A', exact: true })).toBeVisible();
    await expect(page.locator('.pe-main .bf-contribution-detail')).toHaveCount(0);
    await expect(page.locator('.bf-contribution-detail')).toContainText('Team B');
    await expect(page.locator('.bf-contribution-weeks')).toContainText('40.0%');
    await page.screenshot({ path: 'E:/NBAFantasyAnalytics/.cache/contribution-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.locator('[data-action="close"]').click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: /Настройки/ }).click();
    await page.locator('[data-control="rosterMode"]').selectOption('exclude_ir');
    await expect.poll(() => calls).toBe(2);
    await expect(page.locator('.bf-contribution-detail')).toHaveCount(0);
});

test('trade displays baseline first, then paired rank curves and clears stale results', async ({ page }) => {
    await setup(page);
    const team = { name: 'Team', before_z: 1, after_z: 2, delta: 1, categories: {}, raw_categories: {} };
    await page.route('**/api/bluefin/trade', route => route.fulfill({ json: { my_team: team, their_team: team } }));
    const before = result.standings.map(t => ({ ...t, category_probabilities: { PTS: t.team_id === 1 ? .6 : .4, REB: t.team_id === 1 ? .8 : .2 } }));
    const after = before.map(t => ({ ...t, expected_rank: t.expected_rank + .1, p_playoffs: .5,
        rank_probabilities: { 1: .5, 2: .5 }, category_probabilities: { PTS: t.team_id === 1 ? .72 : .3, REB: t.team_id === 1 ? .75 : .35 } }));
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let tradeStarts = 0;
    await page.route('**/api/probabilistic/trade/jobs', route => {
        tradeStarts++;
        expect(route.request().postDataJSON().trials).toBe(3000);
        return route.fulfill({ json: { job_id: 'a'.repeat(32), status: 'running', stage: 'after', result: { before, after: null } } });
    });
    await page.route('**/api/probabilistic/trade/jobs/*', async route => {
        await gate;
        await route.fulfill({ json: { status: 'complete', result: { before, after, trials: 3000 } } });
    });
    await page.locator('[data-page="trades"]').first().click();
    await page.locator('[data-control="tradeMyTeam"]').selectOption('1');
    await page.locator('[data-control="tradeTeam"]').selectOption('2');
    await page.locator('[data-trade="give"]').first().check();
    await page.locator('[data-trade="receive"]').first().check();
    await page.locator('[data-action="trade"]').click();
    await expect(page.locator('.bf-trade-prob svg')).toHaveCount(2);
    await expect(page.locator('.bf-trade-prob polyline')).toHaveCount(2);
    await expect(page.locator('.bf-trade-prob-impact')).not.toContainText('Считаем');
    await page.locator('[data-set="tradeValues"][data-value="probability"]').click();
    await expect(page.locator('.bf-trade-table tbody tr').first().locator('td')).toHaveText(['PTS', '60.0%', '…', '…', '40.0%', '…', '…']);
    release();
    await expect(page.locator('.bf-trade-prob polyline')).toHaveCount(4);
    await expect(page.locator('.bf-trade-table tbody tr').first().locator('td')).toHaveText(['PTS', '60.0%', '72.0%', '+12.0 п.п.', '40.0%', '30.0%', '-10.0 п.п.']);
    await page.locator('[data-set="tradeValues"][data-value="raw"]').click();
    await page.locator('[data-set="tradeValues"][data-value="probability"]').click();
    expect(tradeStarts).toBe(1);
    await expect(page.locator('.bf-trade-prob-impact section').first()).toContainText('1.3 → 1.4');
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.screenshot({ path: 'E:/NBAFantasyAnalytics/.cache/trade-probability-mobile.png', fullPage: true });
    await page.locator('[data-trade="give"]').first().uncheck();
    await expect(page.locator('.bf-trade-prob')).toHaveCount(0);
});

test('never displays another roster restored from the league-wide latest result', async ({ page }) => {
    const calls = await setup(page);
    const selectedParams = calls[0];
    const foreign = { job_id: 'f'.repeat(32), status: 'complete', source_version: '2026-11-16T14:00:00Z',
        params: { ...selectedParams, custom_rosters: { 1: ['Chet Holmgren'], 2: ['Player B'] } },
        result: { ...result, standings: result.standings.map(t => ({ ...t, expected_rank: 99 })) },
    };
    await page.route('**/api/probabilistic/latest', route => route.fulfill({ json: { job: foreign } }));
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    let submitted = null;
    await page.route('**/api/probabilistic/jobs', async route => {
        submitted = route.request().postDataJSON();
        await gate;
        await route.fulfill({ json: { ...foreign, params: submitted,
            result: { ...result, metadata: { ...result.metadata, rosters: submitted.custom_rosters } },
        } });
    });
    try {
        await page.reload();
        await expect.poll(() => submitted).not.toBeNull();
        expect(submitted.custom_rosters[1]).toEqual(['Player A']);
        expect(submitted.custom_rosters[1]).not.toContain('Chet Holmgren');
        await expect(page.locator('.bf-prob-matrix')).toHaveCount(0);
        await expect(page.getByText('99.00', { exact: true })).toHaveCount(0);
        release();
        await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
        await page.getByRole('button', { name: 'Составы расчёта', exact: true }).click();
        await expect(page.locator('.bf-prob-roster-list')).toContainText('Player A');
        await expect(page.locator('.bf-prob-roster-list')).not.toContainText('Chet Holmgren');
    } finally { release(); }
});
