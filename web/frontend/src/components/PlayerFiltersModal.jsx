import React, { useState, useEffect } from 'react';
import { LEAGUE_CATEGORIES as CATEGORIES } from '../utils/categories';
const EMPTY_AVAILABILITY_FILTERS = Object.freeze({});

const PlayerFiltersModal = ({ isOpen, onClose, onApply, initialFilters = {}, showAvailabilityFilters = false, initialAvailabilityFilters = EMPTY_AVAILABILITY_FILTERS }) => {
    const [filters, setFilters] = useState({});
    const [availabilityFilters, setAvailabilityFilters] = useState({});

    // Инициализация фильтров при открытии модального окна
    useEffect(() => {
        if (isOpen) {
            setFilters(initialFilters || {});
            setAvailabilityFilters(initialAvailabilityFilters);
        }
    }, [isOpen, initialFilters, initialAvailabilityFilters]);

    const handleFilterChange = (category, value) => {
        const numValue = value === '' ? null : parseFloat(value);
        setFilters(prev => {
            const newFilters = { ...prev };
            if (numValue === null || isNaN(numValue)) {
                delete newFilters[category];
            } else {
                newFilters[category] = numValue;
            }
            return newFilters;
        });
    };

    const handleReset = () => {
        setFilters({});
        setAvailabilityFilters({ hideNoTeam: false, hideLongTermInjuries: false });
    };

    const handleApply = () => {
        onApply(filters, availabilityFilters);
        onClose();
    };

    const getFilterValue = (category) => {
        const value = filters[category];
        return value !== undefined && value !== null ? value.toString() : '';
    };

    const isPercentageCategory = (cat) => {
        return ['FG%', 'FT%', '3PT%'].includes(cat);
    };

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50" onClick={onClose}>
            <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full mx-4 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
                <div className="p-6">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-2xl font-bold text-gray-800">Фильтры игроков</h2>
                        <button
                            onClick={onClose}
                            className="text-gray-500 hover:text-gray-700 text-2xl font-bold"
                        >
                            ×
                        </button>
                    </div>

                    {showAvailabilityFilters && (
                        <div className="mb-6 space-y-3 rounded border bg-gray-50 p-4">
                            <label className="flex items-center gap-2 text-sm">
                                <input type="checkbox" checked={Boolean(availabilityFilters.hideNoTeam)}
                                    onChange={event => setAvailabilityFilters(current => ({ ...current, hideNoTeam: event.target.checked }))} />
                                Скрывать игроков без NBA-команды (FA)
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <input type="checkbox" checked={Boolean(availabilityFilters.hideLongTermInjuries)}
                                    onChange={event => setAvailabilityFilters(current => ({ ...current, hideLongTermInjuries: event.target.checked }))} />
                                Скрывать игроков с длительной травмой
                            </label>
                            <p className="text-xs text-gray-500">
                                Длительная травма: возвращение через 30 дней и позже или явный статус «до конца сезона» по данным ESPN. OUT без даты возвращения сам по себе не скрывается.
                            </p>
                        </div>
                    )}

                    <div className="mb-4 text-sm text-gray-600">
                        Укажите минимальные значения для фильтрации игроков. Оставьте поле пустым, чтобы не применять фильтр по этой категории.
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
                        {CATEGORIES.map(category => (
                            <div key={category}>
                                <label className="block text-sm font-medium text-gray-700 mb-1">
                                    {category}
                                </label>
                                <input
                                    type="number"
                                    step={isPercentageCategory(category) ? "0.1" : "0.1"}
                                    min="0"
                                    className="w-full border p-2 rounded"
                                    placeholder={isPercentageCategory(category) ? "0.0-100.0" : "0.0"}
                                    value={getFilterValue(category)}
                                    onChange={(e) => handleFilterChange(category, e.target.value)}
                                />
                            </div>
                        ))}
                    </div>

                    <div className="flex justify-end gap-4 pt-4 border-t">
                        <button
                            onClick={handleReset}
                            className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100"
                        >
                            Сбросить
                        </button>
                        <button
                            onClick={onClose}
                            className="px-4 py-2 border border-gray-300 rounded hover:bg-gray-100"
                        >
                            Отмена
                        </button>
                        <button
                            onClick={handleApply}
                            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                        >
                            Применить
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default PlayerFiltersModal;
































