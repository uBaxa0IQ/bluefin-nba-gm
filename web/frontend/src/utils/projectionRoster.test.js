import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeCalculationEngine } from './calculationEngine.js';
import { projectionRosterParams } from './projectionRoster.js';

test('migrates retired engines to calendar while preserving legacy', () => {
    assert.equal(normalizeCalculationEngine('probabilistic'), 'calendar');
    assert.equal(normalizeCalculationEngine(null), 'calendar');
    assert.equal(normalizeCalculationEngine('legacy'), 'legacy');
});

test('forwards manual roster membership and ignores it for exclude IR', () => {
    const storage = { getItem: key => key === 'customTeamPlayers_7' ? '["OUT player","IR player"]' : null };
    assert.deepEqual(projectionRosterParams('top_n', 7, storage), {
        simulation_mode: 'top_n', top_n_players: 13, custom_team_players: 'OUT player,IR player',
    });
    assert.deepEqual(projectionRosterParams('exclude_ir', 7, storage), { simulation_mode: 'exclude_ir' });
});

test('invalid saved roster falls back to automatic top 13', () => {
    assert.deepEqual(projectionRosterParams('top_n', 7, { getItem: () => 'broken' }), {
        simulation_mode: 'top_n', top_n_players: 13,
    });
});
