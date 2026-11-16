import React, { useState, useEffect } from 'react';
import api from '../api';
import { projectionRosterParams } from '../utils/projectionRoster';

const MatchupDetails = ({ teamId, currentMatchup, period, simulationMode = 'all', customPlayersKey = 0 }) => {
    const [expanded, setExpanded] = useState(false);
    const [matchupData, setMatchupData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const matchupWeek = currentMatchup?.week;
    const myGames = matchupData?.game_usage?.[teamId];
    const opponentGames = matchupData?.game_usage?.[currentMatchup?.opponent_id];

    useEffect(() => {
        if (!expanded) return;
        let cancelled = false;
        if (!teamId || !matchupWeek) {
            setMatchupData(null);
            return;
        }

        setLoading(true);
        setError(null);
        api.get(`/dashboard/${teamId}/matchup-details`, {
            params: { period, ...projectionRosterParams(simulationMode, teamId) },
        })
            .then(res => res.data)
            .then(data => {
                if (cancelled) return;
                if (data.error) {
                    setError(data.error);
                    setMatchupData(null);
                } else {
                    setMatchupData(data);
                    setError(null);
                }
                setLoading(false);
            })
            .catch(err => {
                if (cancelled) return;
                console.error('Error fetching matchup details:', err);
                setError('Ошибка загрузки данных матчапа');
                setLoading(false);
            });
        return () => { cancelled = true; };
    }, [expanded, teamId, matchupWeek, period, simulationMode, customPlayersKey]);

    const formatValue = (category, value) => {
        if (category === 'FG%' || category === 'FT%' || category === '3PT%') {
            // Проценты: отображаем как десятичную дробь с 4 знаками (например, .4023)
            // Убираем ведущий ноль, если значение меньше 1
            const formatted = value.toFixed(4);
            return formatted.startsWith('0.') ? formatted.substring(1) : formatted;
        } else if (category === 'A/TO') {
            // A/TO: округляем до 3 знаков
            return value.toFixed(3);
        } else {
            // Счетные категории: показываем с одним знаком после запятой
            return value.toFixed(1);
        }
    };

    return (
        <div className="bg-white border rounded-lg p-6 shadow-sm">
            <button
                type="button"
                aria-expanded={expanded}
                aria-controls="dashboard-matchup-details"
                onClick={() => setExpanded(value => !value)}
                className="flex w-full items-center justify-between gap-4 text-left"
            >
                <span>
                    <span className="block text-lg font-semibold text-gray-700">Детали матчапа</span>
                    <span className="block text-sm text-gray-500">
                        Неделя {matchupWeek} · {currentMatchup.opponent_name}
                    </span>
                </span>
                <span className="flex shrink-0 items-center gap-2 text-sm font-medium text-gray-500">
                    {expanded ? 'Свернуть' : 'Развернуть'}
                    <span aria-hidden="true" className={`inline-block transition-transform ${expanded ? 'rotate-180' : ''}`}>▼</span>
                </span>
            </button>

            {expanded && <div id="dashboard-matchup-details" className="mt-4">
            {loading ? (
                <div className="text-center text-gray-500">Загрузка данных матчапа...</div>
            ) : error ? (
                <div className="text-center text-red-500">{error}</div>
            ) : matchupData ? (<>

            {/* Заголовок с командами и счетом */}
            <div className="mb-4 flex items-center justify-between flex-wrap gap-4">
                <div className="flex-1 min-w-[200px]">
                    <div className="font-bold text-lg">{matchupData.my_team.name}</div>
                    {myGames && (
                        <div className="mt-1 text-sm tabular-nums text-gray-500" aria-label={`Игры: ${myGames.played} сыграно, прогноз ${myGames.projected_total} к концу недели`}>
                            {myGames.played} · {myGames.projected_total}
                        </div>
                    )}
                    {matchupData.my_team.overall_record && (
                        <div className="text-sm text-gray-600">
                            {matchupData.my_team.overall_record}
                            {matchupData.my_team.rank && (
                                <span className="ml-1">, {matchupData.my_team.rank} место</span>
                            )}
                        </div>
                    )}
                    <div className="text-xs text-gray-500 mt-1">Неделя {matchupData.week}</div>
                </div>
                <div className="text-center">
                    <div className="text-2xl font-bold text-blue-600">
                        {matchupData.score}
                    </div>
                    <div className="text-xs text-gray-500">Счет матчапа</div>
                </div>
                <div className="flex-1 min-w-[200px] text-right">
                    <div className="font-bold text-lg">{matchupData.opponent.name}</div>
                    {opponentGames && (
                        <div className="mt-1 text-sm tabular-nums text-gray-500" aria-label={`Игры: ${opponentGames.played} сыграно, прогноз ${opponentGames.projected_total} к концу недели`}>
                            {opponentGames.played} · {opponentGames.projected_total}
                        </div>
                    )}
                    {matchupData.opponent.overall_record && (
                        <div className="text-sm text-gray-600">
                            {matchupData.opponent.overall_record}
                            {matchupData.opponent.rank && (
                                <span className="ml-1">, {matchupData.opponent.rank} место</span>
                            )}
                        </div>
                    )}
                    <div className="text-xs text-gray-500 mt-1">Соперник</div>
                </div>
            </div>

            {/* Таблица сравнения категорий */}
            <div className="mt-4 overflow-x-auto">
                <table className="min-w-full">
                    <thead>
                        <tr className="bg-gray-100 border-b">
                            <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">Категория</th>
                            <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">
                                {matchupData.my_team.name}
                            </th>
                            <th className="px-4 py-3 text-center text-sm font-semibold text-gray-700">
                                {matchupData.opponent.name}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {matchupData.categories.map((item, idx) => {
                            const myWins = item.winner === 'my_team';
                            const opponentWins = item.winner === 'opponent';
                            const isTie = item.winner === 'tie';

                            return (
                                <tr 
                                    key={item.category} 
                                    className={`border-b hover:bg-gray-50 ${
                                        idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'
                                    }`}
                                >
                                    <td className="px-4 py-3 text-sm font-medium text-gray-700">
                                        {item.category}
                                    </td>
                                    <td className={`px-4 py-3 text-center text-sm font-semibold ${
                                        myWins ? 'bg-green-100 text-green-800' : 
                                        isTie ? 'bg-gray-100 text-gray-600' : 
                                        'text-gray-700'
                                    }`}>
                                        {formatValue(item.category, item.my_value)}
                                    </td>
                                    <td className={`px-4 py-3 text-center text-sm font-semibold ${
                                        opponentWins ? 'bg-green-100 text-green-800' : 
                                        isTie ? 'bg-gray-100 text-gray-600' : 
                                        'text-gray-700'
                                    }`}>
                                        {formatValue(item.category, item.opponent_value)}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
            </>) : null}
            </div>}
        </div>
    );
};

export default MatchupDetails;
