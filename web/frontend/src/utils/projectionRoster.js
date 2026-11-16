export function projectionRosterParams(simulationMode, teamId, storage = localStorage) {
    const params = { simulation_mode: simulationMode };
    if (simulationMode !== 'top_n') return params;
    params.top_n_players = 13;
    try {
        const selected = JSON.parse(storage.getItem(`customTeamPlayers_${teamId}`) || '[]');
        if (Array.isArray(selected) && selected.length) params.custom_team_players = selected.join(',');
    } catch {
        // Invalid saved selections fall back to the backend's top 13.
    }
    return params;
}
