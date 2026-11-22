import { expect, test } from '@playwright/test';

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
                score: '1-0-0', categories: [{ category: 'PTS', my_value: 15, opponent_value: 12, winner: 'my_team' }] },
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
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(plot).toBeVisible();
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
});
