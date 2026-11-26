import { expect, test } from '@playwright/test';

test('shows opening odds and zero category totals, then refreshes live scores in place', async ({ page }) => {
    await page.clock.install();
    const points = [{ day: 1, at: '2026-11-23T20:00:00Z', p_win: .7, p_tie: .04, p_loss: .26 }];
    const matchup = { my_team: { id: 1, name: 'Team A' }, opponent: { id: 2, name: 'Team B' }, score: '0-0-1',
        categories: [{ category: 'PTS', my_value: 0, opponent_value: 0, winner: 'tie' }] };
    await page.route('**/api/**', route => {
        const url = new URL(route.request().url());
        const data = {
            '/api/settings': { season: { league_id: 123, year: 2027, default_team_id: 1, categories: ['PTS'],
                periods: { total: '2027_total' } } },
            '/api/teams': [{ team_id: 1, team_name: 'Team A' }, { team_id: 2, team_name: 'Team B' }],
            '/api/weeks': { current_week: 6, weeks: [6] },
            '/api/all-players': { players: [] },
            '/api/bluefin/matchups': { matchups: [{ team1_id: 1, team2_id: 2, team1: 'Team A', team2: 'Team B',
                week: 6, score: { formatted: '0-0-1' } }] },
            '/api/dashboard/1/matchup-details': matchup,
            '/api/dashboard/1/matchup-timeline': { points },
        }[url.pathname];
        return route.fulfill({ json: data ?? {} });
    });
    await page.goto('/');
    await page.getByRole('link', { name: 'Матчапы' }).click();
    await page.getByRole('button', { name: /Team A.*Team B/ }).click();
    const dialog = page.getByRole('dialog');
    const stats = dialog.getByRole('row', { name: /PTS/ }).getByRole('cell');
    const plot = dialog.locator('[data-odds-plot]');
    await expect(plot.locator('[data-odds-mark]')).toHaveCount(1);
    await expect(plot.locator('polyline')).toHaveCount(0);
    await expect(dialog.locator('[data-odds-value]')).toContainText('Team A 70.0%');
    await expect(dialog.locator('.bf-match-title strong')).toHaveText('0-0-1');
    await expect(stats).toHaveText(['PTS', '0.0', '0.0']);

    matchup.score = '0-1-0';
    matchup.categories[0].opponent_value = 12;
    matchup.categories[0].winner = 'opponent';
    await page.clock.fastForward(60_000);
    await expect(stats).toHaveText(['PTS', '0.0', '12.0']);
    await expect(plot.locator('[data-odds-mark]')).toHaveCount(1);

    points.push({ day: 1, at: '2026-11-23T23:00:00Z', game: 'DET @ ATL', p_win: .2, p_tie: 0, p_loss: .8 });
    await page.clock.fastForward(60_000);
    await expect(dialog.locator('[data-odds-value]')).toContainText('Team B 80.0%');
    await expect(plot.locator('[data-odds-mark]')).toHaveCount(2);
});

test('shows both sides of momentum with game-level odds in the matchup dialog', async ({ page }) => {
    const opponent = "Team B's Impressive Team";
    const points = [
        { day: 1, at: '2026-11-01T20:00:00Z', p_win: .7, p_tie: 0, p_loss: .3 },
        { day: 1, at: '2026-11-01T22:00:00Z', game: 'DET @ ATL', p_win: .2, p_tie: .1, p_loss: .7 },
        { day: 2, at: '2026-11-02T22:00:00Z', game: 'BOS @ NY', p_win: 1, p_tie: 0, p_loss: 0, final: true },
    ];
    await page.route('**/api/**', route => {
        const url = new URL(route.request().url());
        const data = {
            '/api/settings': { season: { league_id: 123, year: 2027, default_team_id: 1, categories: ['PTS'],
                periods: { total: '2027_total' } } },
            '/api/teams': [{ team_id: 1, team_name: 'Team A' }, { team_id: 2, team_name: opponent }],
            '/api/weeks': { current_week: 2, weeks: [1, 2] },
            '/api/all-players': { players: [] },
            '/api/bluefin/matchups': { matchups: [{ team1_id: 2, team2_id: 1, team1: opponent, team2: 'Team A',
                week: 1, score: { formatted: '0-1' } }] },
            '/api/dashboard/1/matchup-details': { my_team: { id: 1, name: 'Team A' }, opponent: { id: 2, name: opponent },
                score: '1-1-1', categories: [
                    { category: 'PTS', my_value: 15, opponent_value: 12, winner: 'my_team' },
                    { category: 'BLK', my_value: 1, opponent_value: 4, winner: 'opponent' },
                    { category: 'REB', my_value: 7, opponent_value: 7, winner: 'tie' },
                ] },
            '/api/dashboard/1/matchup-timeline': { points },
        }[url.pathname];
        return route.fulfill({ json: data ?? {} });
    });
    await page.goto('/');
    await page.getByRole('link', { name: 'Матчапы' }).click();
    await page.getByRole('button', { name: /Team B.*Team A/ }).click();
    const dialog = page.getByRole('dialog');
    const plot = dialog.locator('[data-odds-plot]');
    await expect(dialog.getByText('50%', { exact: true })).toBeVisible();
    await expect(plot.locator('[data-state=behind]')).toHaveCount(1);
    await expect(plot.locator('[data-state=ahead]')).toHaveCount(2);
    await expect(dialog.locator('[data-odds-value]')).toContainText('Team A 100.0%');
    await plot.focus();
    await plot.press('ArrowLeft');
    await expect(dialog.locator('[data-odds-label]')).toContainText('DET @ ATL');
    await expect(dialog.locator('[data-odds-value]')).toContainText(`${opponent} 70.0%`);
    await expect(dialog.getByRole('cell', { name: 'PTS' })).toBeVisible();
    await expect(dialog.getByText(/Реконструкция по завершённым играм/)).toHaveCount(0);
    const ownWin = dialog.locator('.bf-match-win-own');
    const opponentWin = dialog.locator('.bf-match-win-opponent');
    await expect(ownWin).toHaveText('15.0');
    await expect(opponentWin).toHaveText('4.00');
    await expect(ownWin).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(opponentWin).not.toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await expect(dialog.getByRole('row', { name: /REB/ }).getByRole('cell').nth(1))
        .toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(plot).toBeVisible();
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
});
