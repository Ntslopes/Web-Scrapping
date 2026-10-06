const API_BASE = "http://127.0.0.1:8000";

const state = {
    filters: {
        search: '',
        gender: '',
        belt: '',
        age_category: '',
        ranking_type: '',
        min_points: '',
        max_points: ''
    },
    pagination: {
        page: 1,
        page_size: 10
    },
    sort: {
        sort_by: 'rank',
        order: 'asc'
    }
};

let charts = {
    top: null,
    dist: null,
    history: null,
    modal: null
};

let requestControllers = {
    dashboard: null,
    athletes: null
};

Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.color = "#0A0A0A";

const formatNumber = (num) => num != null ? num.toLocaleString("pt-BR") : '-';
const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    return new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(dateStr));
};

function buildQuery(params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value !== '' && value !== null && value !== undefined) {
            searchParams.append(key, value);
        }
    }
    return searchParams.toString();
}

async function fetchJSON(endpoint, queryParams = {}, controllerKey = null) {
    if (controllerKey) {
        if (requestControllers[controllerKey]) {
            requestControllers[controllerKey].abort();
        }
        requestControllers[controllerKey] = new AbortController();
    }
    
    const query = buildQuery(queryParams);
    const url = `${API_BASE}${endpoint}${query ? '?' + query : ''}`;
    
    try {
        const options = controllerKey ? { signal: requestControllers[controllerKey].signal } : {};
        const response = await fetch(url, options);
        if (!response.ok) throw new Error('API error');
        hideError();
        return await response.json();
    } catch (err) {
        if (err.name !== 'AbortError') {
            showError();
        }
        throw err;
    }
}

function showError() {
    const banner = document.getElementById('error-banner');
    document.getElementById('api-url-error').textContent = API_BASE;
    banner.classList.remove('hidden');
}

function hideError() {
    document.getElementById('error-banner').classList.add('hidden');
}

async function loadFilters() {
    try {
        const data = await fetchJSON('/filters');
        populateSelect('gender', data.gender);
        populateSelect('belt', data.belt);
        populateSelect('age_category', data.age_category);
        populateSelect('ranking_type', data.ranking_type);
    } catch (e) {
        console.error('Failed to load filters', e);
    }
}

function populateSelect(id, options) {
    const select = document.getElementById(id);
    options.forEach(opt => {
        if (opt) {
            const el = document.createElement('option');
            el.value = opt;
            el.textContent = opt;
            select.appendChild(el);
        }
    });
}

function getActiveFilters() {
    return { ...state.filters };
}

async function loadDashboard() {
    const filters = getActiveFilters();
    try {
        setLoadingStateCards(true);
        const data = await fetchJSON('/dashboard', filters, 'dashboard');
        renderCards(data.cards);
        renderCharts(data);
    } catch (e) {
        if (e.name !== 'AbortError') console.error('Dashboard load failed', e);
    }
}

function setLoadingStateCards(isLoading) {
    document.querySelectorAll('.card .value').forEach(el => {
        if (isLoading) el.classList.add('loader');
        else el.classList.remove('loader');
    });
}

function renderCards(cards) {
    document.getElementById('card-total').querySelector('.value').textContent = formatNumber(cards.total_athletes);
    document.getElementById('card-avg').querySelector('.value').textContent = formatNumber(cards.average_points);
    document.getElementById('card-max').querySelector('.value').textContent = formatNumber(cards.max_points);
    document.getElementById('card-leader').querySelector('.value').textContent = cards.leader || '-';
    
    document.getElementById('card-collections').querySelector('.value').textContent = formatNumber(cards.total_collections);
    document.getElementById('card-last-date').textContent = cards.last_collected_at ? formatDate(cards.last_collected_at) : '';
    setLoadingStateCards(false);
}

function renderCharts(data) {
    // Top 10 Athletes
    const ctxTop = document.getElementById('chart-top');
    if (charts.top) charts.top.destroy();
    if (data.top_athletes && data.top_athletes.length > 0) {
        charts.top = new Chart(ctxTop, {
            type: 'bar',
            data: {
                labels: data.top_athletes.map(a => a.name.split(' ')[0]), // Primeiro nome para caber
                datasets: [{
                    label: 'Pontuação',
                    data: data.top_athletes.map(a => a.points),
                    backgroundColor: '#2F4FD8',
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: 'rgba(10,10,10,0.05)' } },
                    y: { grid: { display: false } }
                }
            }
        });
    }

    // Points Distribution
    const ctxDist = document.getElementById('chart-dist');
    if (charts.dist) charts.dist.destroy();
    if (data.points_distribution && data.points_distribution.length > 0) {
        charts.dist = new Chart(ctxDist, {
            type: 'bar',
            data: {
                labels: data.points_distribution.map(d => `${d.min}-${d.max}`),
                datasets: [{
                    label: 'Atletas',
                    data: data.points_distribution.map(d => d.count),
                    backgroundColor: '#2F4FD8',
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: 'rgba(10,10,10,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });
    }

    // History
    const ctxHistory = document.getElementById('chart-history');
    const msgHistory = document.getElementById('chart-history-msg');
    if (charts.history) charts.history.destroy();
    
    if (!data.collections_timeline || data.collections_timeline.length <= 1) {
        ctxHistory.style.display = 'none';
        msgHistory.classList.remove('hidden');
    } else {
        ctxHistory.style.display = 'block';
        msgHistory.classList.add('hidden');
        
        charts.history = new Chart(ctxHistory, {
            type: 'line',
            data: {
                labels: data.collections_timeline.map(c => formatDate(c.collected_at)),
                datasets: [{
                    label: 'Média de Pontos',
                    data: data.collections_timeline.map(c => c.average_points),
                    borderColor: '#2F4FD8',
                    backgroundColor: 'rgba(47, 79, 216, 0.1)',
                    fill: true,
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { grid: { color: 'rgba(10,10,10,0.05)' } },
                    x: { grid: { display: false } }
                }
            }
        });
    }
}

async function loadAthletes() {
    const params = {
        ...state.filters,
        ...state.pagination,
        ...state.sort
    };
    try {
        const data = await fetchJSON('/athletes', params, 'athletes');
        renderTable(data);
    } catch (e) {
        if (e.name !== 'AbortError') console.error('Athletes load failed', e);
    }
}

function getAvatarInitials(name) {
    if (!name) return '?';
    return name.charAt(0).toUpperCase();
}

function renderTable(data) {
    const tbody = document.querySelector('#athletes-table tbody');
    const emptyState = document.getElementById('table-empty');
    tbody.innerHTML = '';
    
    document.getElementById('table-results-info').textContent = `${formatNumber(data.total)} resultados`;
    document.getElementById('page-info').textContent = `Página ${data.page} de ${data.total_pages || 1}`;
    
    document.getElementById('page-prev').disabled = data.page <= 1;
    document.getElementById('page-next').disabled = data.page >= data.total_pages || data.total_pages === 0;

    if (!data.items || data.items.length === 0) {
        emptyState.classList.remove('hidden');
        document.getElementById('athletes-table').style.display = 'none';
        return;
    }
    
    emptyState.classList.add('hidden');
    document.getElementById('athletes-table').style.display = 'table';

    data.items.forEach(item => {
        const tr = document.createElement('tr');
        tr.onclick = (e) => {
            if (e.target.tagName !== 'A') openAthleteModal(item);
        };
        
        let photoHtml = `<div class="avatar">${getAvatarInitials(item.name)}</div>`;
        if (item.photo) {
            photoHtml = `<img src="${item.photo}" class="avatar" alt="Avatar">`;
        }
        
        const rank = item.rank != null ? item.rank : '-';
        const points = formatNumber(item.points);
        const nameLink = item.profile_url ? `<a href="${item.profile_url}" target="_blank" rel="noopener noreferrer" class="link-profile">${item.name}</a>` : `<span class="link-profile">${item.name}</span>`;
        const category = [item.gender, item.age_category, item.belt].filter(Boolean).join(', ');
        
        tr.innerHTML = `
            <td>${rank}</td>
            <td>${photoHtml}</td>
            <td>${nameLink}</td>
            <td>${points}</td>
            <td>${category}</td>
            <td>${formatDate(item.last_collected_at)}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateSortIcons() {
    document.querySelectorAll('th[data-sort]').forEach(th => {
        const icon = th.querySelector('.sort-icon');
        icon.textContent = '';
        if (th.dataset.sort === state.sort.sort_by) {
            icon.textContent = state.sort.order === 'asc' ? ' ▲' : ' ▼';
        }
    });
}

async function openAthleteModal(athlete) {
    const modal = document.getElementById('modal');
    
    document.getElementById('modal-name').textContent = athlete.name;
    document.getElementById('modal-category').textContent = [athlete.gender, athlete.age_category, athlete.belt].filter(Boolean).join(', ');
    document.getElementById('modal-rank').textContent = athlete.rank != null ? athlete.rank : '-';
    document.getElementById('modal-points').textContent = formatNumber(athlete.points);
    document.getElementById('modal-first-date').textContent = formatDate(athlete.first_collected_at);
    document.getElementById('modal-last-date').textContent = formatDate(athlete.last_collected_at);
    
    const photoContainer = document.getElementById('modal-photo');
    if (athlete.photo) {
        photoContainer.innerHTML = `<img src="${athlete.photo}" alt="${athlete.name}">`;
    } else {
        photoContainer.innerHTML = `<div class="avatar-fallback">${getAvatarInitials(athlete.name)}</div>`;
    }
    
    modal.classList.remove('hidden');
    
    // Load history
    try {
        const history = await fetchJSON(`/athletes/${athlete.id}/history`);
        renderModalChart(history);
    } catch (e) {
        console.error('Failed to load history', e);
    }
}

function renderModalChart(history) {
    const ctx = document.getElementById('modal-history-chart');
    if (charts.modal) charts.modal.destroy();
    
    if (!history || history.length === 0) return;
    
    charts.modal = new Chart(ctx, {
        type: 'line',
        data: {
            labels: history.map(h => formatDate(h.collected_at)),
            datasets: [{
                label: 'Pontos',
                data: history.map(h => h.points),
                borderColor: '#2F4FD8',
                backgroundColor: 'rgba(47, 79, 216, 0.1)',
                fill: true,
                tension: 0.1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { grid: { color: 'rgba(10,10,10,0.05)' } },
                x: { grid: { display: false } }
            }
        }
    });
}

function closeAthleteModal() {
    document.getElementById('modal').classList.add('hidden');
}

let debounceTimer;
function onFilterChange() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
        state.filters.search = document.getElementById('search').value;
        state.filters.gender = document.getElementById('gender').value;
        state.filters.belt = document.getElementById('belt').value;
        state.filters.age_category = document.getElementById('age_category').value;
        state.filters.ranking_type = document.getElementById('ranking_type').value;
        state.filters.min_points = document.getElementById('min_points').value;
        state.filters.max_points = document.getElementById('max_points').value;
        
        state.pagination.page = 1; // reset page
        
        loadDashboard();
        loadAthletes();
    }, 400);
}

function setupListeners() {
    // Filters
    ['search', 'gender', 'belt', 'age_category', 'ranking_type', 'min_points', 'max_points'].forEach(id => {
        document.getElementById(id).addEventListener('input', onFilterChange);
    });
    
    document.getElementById('clear-filters').addEventListener('click', () => {
        document.querySelectorAll('.filter-group input, .filter-group select').forEach(el => el.value = '');
        onFilterChange();
    });
    
    // Pagination
    document.getElementById('page-prev').addEventListener('click', () => {
        if (state.pagination.page > 1) {
            state.pagination.page--;
            loadAthletes();
        }
    });
    document.getElementById('page-next').addEventListener('click', () => {
        state.pagination.page++;
        loadAthletes();
    });
    document.getElementById('page-size').addEventListener('change', (e) => {
        state.pagination.page_size = parseInt(e.target.value);
        state.pagination.page = 1;
        loadAthletes();
    });
    
    // Sorting
    document.querySelectorAll('th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const sortBy = th.dataset.sort;
            if (state.sort.sort_by === sortBy) {
                state.sort.order = state.sort.order === 'asc' ? 'desc' : 'asc';
            } else {
                state.sort.sort_by = sortBy;
                state.sort.order = 'asc';
            }
            updateSortIcons();
            loadAthletes();
        });
        th.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                th.click();
            }
        });
    });
    
    // Modal
    document.getElementById('modal-close').addEventListener('click', closeAthleteModal);
    document.getElementById('modal-overlay').addEventListener('click', closeAthleteModal);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeAthleteModal();
    });
    
    // Retry
    document.getElementById('retry-btn').addEventListener('click', () => {
        loadFilters();
        loadDashboard();
        loadAthletes();
    });
}

// Init
async function init() {
    setupListeners();
    updateSortIcons();
    await loadFilters();
    loadDashboard();
    loadAthletes();
}

document.addEventListener('DOMContentLoaded', init);
