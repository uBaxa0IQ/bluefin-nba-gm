import { expect, test } from '@playwright/test';

test('Shift-click adds and removes metrics in the shared player tables', async ({ page }) => {
    const players = [
        { name: 'Steals leader', stats: { STL: 3, BLK: .1 }, z_scores: { STL: 1, BLK: .1 } },
        { name: 'Blocks leader', stats: { STL: .5, BLK: 3 }, z_scores: { STL: .2, BLK: 1 } },
        { name: 'Combined leader', stats: { STL: 2.1, BLK: 2.1 }, z_scores: { STL: .3, BLK: .3 } },
    ].map((player, i) => ({ ...player, player_id: i+1, fantasy_team_id: 1, position: 'PG', nba_team: 'ATL' }));
    await page.route('**/api/**', route => {
        const data = {
            '/api/settings': { season: { league_id: 123, year: 2027, default_team_id: 1, categories: ['STL', 'BLK'],
                reverse_categories: [], periods: { total: '2027_total' } } },
            '/api/teams': [{ team_id: 1, team_name: 'Team A' }],
            '/api/weeks': { current_week: 4, weeks: [4] },
            '/api/all-players': { players },
            '/api/bluefin/roster-meta': { players: [] },
            '/api/bluefin/injuries': { players: [] },
            '/api/bluefin/season': { standings: [] },
        }[new URL(route.request().url()).pathname];
        return route.fulfill({ json: data ?? {} });
    });
    await page.goto('/');
    await page.getByRole('link', { name: 'Игроки', exact: true }).click();
    const table = page.locator('.bf-players');
    const leader = table.locator('tbody tr').first().locator('.pe-entity a');
    const steals = table.getByRole('button', { name: /^STL/ });
    const blocks = table.getByRole('button', { name: /^BLK/ });
    await steals.click();
    await expect(leader).toHaveText('Steals leader');
    await blocks.click({ modifiers: ['Shift'] });
    await expect(leader).toHaveText('Combined leader');
    await expect(table.locator('caption')).toHaveText('STL + BLK ↓');
    await expect(steals).toHaveAttribute('aria-pressed', 'true');
    await expect(blocks).toHaveAttribute('aria-pressed', 'true');
    await page.getByRole('button', { name: 'Z-score', exact: true }).first().click();
    await expect(leader).toHaveText('Blocks leader');
    await blocks.click({ modifiers: ['Shift'] });
    await expect(table.locator('caption')).toHaveCount(0);
    await expect(leader).toHaveText('Steals leader');

    await page.getByRole('link', { name: 'Команда', exact: true }).click();
    await page.getByRole('button', { name: 'Состав', exact: true }).click();
    await page.getByRole('button', { name: 'Статистика', exact: true }).click();
    await blocks.click({ modifiers: ['Shift'] });
    await expect(leader).toHaveText('Combined leader');
    await blocks.click();
    await expect(leader).toHaveText('Blocks leader');
    await blocks.click();
    await expect(leader).toHaveText('Steals leader');
});
