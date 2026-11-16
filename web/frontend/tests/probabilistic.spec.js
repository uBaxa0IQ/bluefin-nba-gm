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

async function setup(page, { failNext = false } = {}) {
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
        ] } });
        if (path === '/api/bluefin/roster-meta' || path === '/api/bluefin/injuries') return route.fulfill({ json: { players: [] } });
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

test('failed recalculation never presents a result for different settings', async ({ page }) => {
    const calls = await setup(page, { failNext: true });
    await expect(page.locator('.bf-prob-matrix tbody tr')).toHaveCount(2);
    await page.locator('button[data-action="settings"]').click();
    await page.locator('[data-control="rosterMode"]').selectOption('all');
    await page.locator('[data-action="close"]').click();
    await expect(page.getByRole('alert')).toContainText('Попробуйте позже');
    await expect(page.locator('.bf-prob-matrix')).toHaveCount(0);
    await page.getByRole('button', { name: 'Повторить', exact: true }).click();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await expect.poll(() => calls.length).toBe(3);
    expect(calls.every(p => p.trials === 10000)).toBe(true);
    expect(calls[1].simulation_mode).toBe('all');
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

test('trade displays baseline first, then paired rank curves and clears stale results', async ({ page }) => {
    await setup(page);
    const team = { name: 'Team', before_z: 1, after_z: 2, delta: 1, categories: {}, raw_categories: {} };
    await page.route('**/api/bluefin/trade', route => route.fulfill({ json: { my_team: team, their_team: team } }));
    const before = result.standings;
    const after = before.map(t => ({ ...t, expected_rank: t.expected_rank + .1, p_playoffs: .5,
        rank_probabilities: { 1: .5, 2: .5 } }));
    let release;
    const gate = new Promise(resolve => { release = resolve; });
    await page.route('**/api/probabilistic/trade/jobs', route => {
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
    release();
    await expect(page.locator('.bf-trade-prob polyline')).toHaveCount(4);
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
