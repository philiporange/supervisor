/**
 * Core utilities and shared state for the supervisor dashboard.
 * Provides API helper, utility functions, modal/tab management, and initialization.
 */

// Shared state
let services = [];
let cronJobs = [];
let serviceHost = 'localhost';
let currentService = null;
let currentCronJob = null;
let ctxService = null;
let statusInterval = null;

// API helper
async function api(method, path, body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch('/api' + path, opts);
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'API error');
    }
    return res.json();
}

// Utility functions
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// Modal helpers
function showModal(id) { document.getElementById(id).classList.remove('hidden'); }
function hideModal(id) { document.getElementById(id).classList.add('hidden'); }

// Hamburger menu toggle
document.getElementById('menu-toggle').addEventListener('click', () => {
    const nav = document.getElementById('mobile-nav');
    nav.classList.toggle('hidden');
});

// Tab navigation
function switchTab(tab) {
    // Update desktop tabs
    document.querySelectorAll('.tab').forEach(t => {
        t.classList.remove('bg-white', 'text-black');
        t.classList.add('text-gray-400', 'border-gray-800');
    });
    const activeDesktop = document.querySelector(`.tab[data-tab="${tab}"]`);
    if (activeDesktop) {
        activeDesktop.classList.add('bg-white', 'text-black');
        activeDesktop.classList.remove('text-gray-400', 'border-gray-800');
    }

    // Update mobile tabs
    document.querySelectorAll('.tab-mobile').forEach(t => {
        t.classList.remove('bg-gray-800', 'text-white');
        t.classList.add('text-gray-400');
    });
    const activeMobile = document.querySelector(`.tab-mobile[data-tab="${tab}"]`);
    if (activeMobile) {
        activeMobile.classList.add('bg-gray-800', 'text-white');
        activeMobile.classList.remove('text-gray-400');
    }

    // Hide mobile nav after selection
    document.getElementById('mobile-nav').classList.add('hidden');

    // Show tab content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.add('hidden'));
    document.getElementById(tab + '-tab').classList.remove('hidden');

    // Stop supervisor logs interval when leaving logs tab
    if (tab !== 'logs' && typeof stopSupervisorLogsInterval === 'function') {
        stopSupervisorLogsInterval();
    }

    // Load tab-specific content
    if (tab === 'cron' && typeof loadCronJobs === 'function') loadCronJobs();
    if (tab === 'jobs' && typeof loadJobs === 'function') loadJobs();
    if (tab === 'logs' && typeof loadSupervisorLogs === 'function') {
        loadSupervisorLogs();
        if (typeof startSupervisorLogsInterval === 'function') startSupervisorLogsInterval();
    }
    if (tab === 'caddy' && typeof loadCaddy === 'function') loadCaddy();
}

document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

document.querySelectorAll('.tab-mobile').forEach(tab => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        // Handle logs modal specially to stop interval
        if (!document.getElementById('logs-modal').classList.contains('hidden')) {
            if (typeof closeLogsModal === 'function') closeLogsModal();
        }
        document.querySelectorAll('[id$="-modal"]:not(.hidden)').forEach(m => m.classList.add('hidden'));
        if (typeof hideContextMenu === 'function') hideContextMenu();
    }
});

// Click outside modal to close
document.querySelectorAll('[id$="-modal"]').forEach(modal => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            if (modal.id === 'logs-modal' && typeof closeLogsModal === 'function') {
                closeLogsModal();
            } else {
                modal.classList.add('hidden');
            }
        }
    });
});

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    if (typeof updateStatus === 'function') updateStatus();
    if (typeof loadProjects === 'function') loadProjects();
    statusInterval = setInterval(() => {
        if (typeof updateStatus === 'function') updateStatus();
    }, 3000);
});
