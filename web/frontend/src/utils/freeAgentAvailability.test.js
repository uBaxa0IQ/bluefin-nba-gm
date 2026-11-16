import assert from 'node:assert/strict';
import test from 'node:test';
import { matchesFreeAgentAvailability as matches } from './freeAgentAvailability.js';

const today = new Date(2026, 10, 16);
const filters = { hideNoTeam: true, hideLongTermInjuries: true };
const player = { nba_team: 'BOS', injured: true, injury_status: 'OUT' };

test('hides NBA free agents only when enabled', () => {
    for (const nba_team of ['FA', ' fa ', '', null, 'N/A']) {
        assert.equal(matches({ nba_team }, filters, today), false);
        assert.equal(matches({ nba_team }, {}, today), true);
    }
    assert.equal(matches({ nba_team: 'BOS' }, filters, today), true);
});

test('hides injuries at 30 days and season-ending statuses, retains short or unknown OUT', () => {
    assert.equal(matches({ ...player, expected_return_date: '2026-12-15' }, filters, today), true);
    assert.equal(matches({ ...player, expected_return_date: '2026-12-16' }, filters, today), false);
    assert.equal(matches({ ...player, injury_status: 'OUT_FOR_SEASON' }, filters, today), false);
    assert.equal(matches(player, filters, today), true);
    assert.equal(matches({ ...player, expected_return_date: '2027-06-01' }, { hideNoTeam: true }, today), true);
    assert.equal(matches({ nba_team: 'BOS', injury_status: 'ACTIVE', expected_return_date: '2027-06-01' }, filters, today), true);
});
