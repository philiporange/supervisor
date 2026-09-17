/**
 * Monitoring functionality for the supervisor dashboard.
 * Handles service logs, supervisor logs, metrics charts, incidents, and fix history.
 */

// Service Logs
let logsInterval = null;
let logsUserScrolled = false;
let logsEntries = [];   // oldest first
let logsLastId = null;

function resetServiceLogs() {
    logsEntries = [];
    logsLastId = null;
}

async function showServiceLogs(name) {
    currentService = name;
    logsUserScrolled = false;
    resetServiceLogs();
    document.getElementById('logs-title').textContent = name;
    document.getElementById('logs-live').checked = true;
    updateLogsLiveIndicator(true);
    showModal('logs-modal');
    await refreshServiceLogs();
    startLogsInterval();
}

function closeLogsModal() {
    stopLogsInterval();
    hideModal('logs-modal');
}

function startLogsInterval() {
    stopLogsInterval();
    if (document.getElementById('logs-live').checked) {
        logsInterval = setInterval(refreshServiceLogs, 3000);
    }
}

function stopLogsInterval() {
    if (logsInterval) {
        clearInterval(logsInterval);
        logsInterval = null;
    }
}

function updateLogsLiveIndicator(live) {
    const dot = document.getElementById('logs-live-dot');
    if (live) {
        dot.classList.remove('bg-gray-500');
        dot.classList.add('bg-green-500', 'pulse-dot');
    } else {
        dot.classList.remove('bg-green-500', 'pulse-dot');
        dot.classList.add('bg-gray-500');
    }
}

document.getElementById('logs-live').addEventListener('change', (e) => {
    updateLogsLiveIndicator(e.target.checked);
    if (e.target.checked) {
        logsUserScrolled = false;
        startLogsInterval();
        refreshServiceLogs();
    } else {
        stopLogsInterval();
    }
});

document.getElementById('logs-content').addEventListener('scroll', (e) => {
    const el = e.target;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    logsUserScrolled = !atBottom;
});

document.getElementById('logs-level').addEventListener('change', () => { resetServiceLogs(); refreshServiceLogs(); });
document.getElementById('logs-limit').addEventListener('change', () => { resetServiceLogs(); refreshServiceLogs(); });

// The API returns newest first. The first call loads a full window; later
// calls pass after_id and only fetch lines added since, which are appended.
async function refreshServiceLogs() {
    if (!currentService) return;
    const level = document.getElementById('logs-level').value;
    const limit = parseInt(document.getElementById('logs-limit').value, 10);
    let path = `/services/${currentService}/logs?limit=${limit}`;
    if (level) path += `&level=${level}`;
    if (logsLastId !== null) path += `&after_id=${logsLastId}`;

    try {
        const logs = await api('GET', path);
        const content = document.getElementById('logs-content');
        const wasAtBottom = content.scrollHeight - content.scrollTop - content.clientHeight < 50;

        if (logs.length) {
            logsEntries = logsEntries.concat(logs.slice().reverse()).slice(-limit);
            logsLastId = logs[0].id;
        } else if (logsLastId === null) {
            logsLastId = 0;
        }
        if (logs.length || !content.innerHTML) {
            content.innerHTML = logsEntries.map(l =>
                `<span class="${l.level === 'error' ? 'text-red-400' : 'text-gray-400'}">[${formatTime(l.timestamp)}] ${escapeHtml(l.message)}</span>`
            ).join('\n') || 'No logs';
        }

        if (!logsUserScrolled || wasAtBottom) {
            content.scrollTop = content.scrollHeight;
        }

        document.getElementById('logs-status').textContent = `${logsEntries.length} lines`;
    } catch (e) {
        document.getElementById('logs-content').textContent = 'Error: ' + e.message;
    }
}

// Supervisor logs
let supervisorLogsInterval = null;
let supervisorLogsUserScrolled = false;
let supervisorLines = [];   // newest first
let supervisorOffset = null;

document.getElementById('log-lines').addEventListener('change', () => { supervisorOffset = null; loadSupervisorLogs(); });

// The server returns only bytes appended since the offset it last handed
// back; a reset response (first load or log rotation) replaces the view.
async function loadSupervisorLogs() {
    const lines = parseInt(document.getElementById('log-lines').value, 10);
    const content = document.getElementById('supervisor-logs');
    const wasAtTop = content.scrollTop < 50;

    try {
        let path = `/supervisor/logs?lines=${lines}`;
        if (supervisorOffset !== null) path += `&offset=${supervisorOffset}`;
        const res = await api('GET', path);
        supervisorOffset = res.offset;
        const fresh = res.lines.slice().reverse();
        if (res.reset) {
            supervisorLines = fresh;
        } else if (fresh.length) {
            supervisorLines = fresh.concat(supervisorLines).slice(0, lines);
        } else {
            return;
        }
        content.textContent = supervisorLines.join('');

        if (!supervisorLogsUserScrolled || wasAtTop) {
            content.scrollTop = 0;
        }
    } catch (e) {
        content.textContent = 'Error: ' + e.message;
    }
}

function startSupervisorLogsInterval() {
    stopSupervisorLogsInterval();
    if (document.getElementById('supervisor-logs-live').checked) {
        supervisorLogsInterval = setInterval(loadSupervisorLogs, 5000);
    }
}

function stopSupervisorLogsInterval() {
    if (supervisorLogsInterval) {
        clearInterval(supervisorLogsInterval);
        supervisorLogsInterval = null;
    }
}

function updateSupervisorLogsIndicator(live) {
    const dot = document.getElementById('supervisor-logs-dot');
    if (live) {
        dot.classList.remove('bg-gray-500');
        dot.classList.add('bg-green-500', 'pulse-dot');
    } else {
        dot.classList.remove('bg-green-500', 'pulse-dot');
        dot.classList.add('bg-gray-500');
    }
}

document.getElementById('supervisor-logs-live').addEventListener('change', (e) => {
    updateSupervisorLogsIndicator(e.target.checked);
    if (e.target.checked) {
        supervisorLogsUserScrolled = false;
        startSupervisorLogsInterval();
        loadSupervisorLogs();
    } else {
        stopSupervisorLogsInterval();
    }
});

document.getElementById('supervisor-logs').addEventListener('scroll', (e) => {
    const el = e.target;
    const atTop = el.scrollTop < 50;
    supervisorLogsUserScrolled = !atTop;
});

// Metrics
async function showServiceMetrics(name) {
    currentService = name;
    document.getElementById('metrics-title').textContent = name;
    showModal('metrics-modal');
    await refreshMetrics();
}

async function refreshMetrics() {
    if (!currentService) return;
    const hours = document.getElementById('metrics-hours').value;

    try {
        const metrics = await api('GET', `/services/${currentService}/metrics?hours=${hours}`);
        const timestamps = metrics.map(m => m.timestamp);
        drawChart('cpu-chart', metrics.map(m => m.cpu_percent), timestamps, '#22c55e');
        drawChart('memory-chart', metrics.map(m => m.memory_mb), timestamps, '#3b82f6');
        drawChart('disk-chart', metrics.map(m => m.disk_mb || 0), timestamps, '#f59e0b');
    } catch (e) {
        console.error('Metrics error:', e);
    }
}

function drawChart(canvasId, data, timestamps, color) {
    const canvas = document.getElementById(canvasId);
    const ctx = canvas.getContext('2d');
    const w = canvas.width = canvas.parentElement.clientWidth - 24;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    if (!data.length) {
        ctx.fillStyle = '#666';
        ctx.textAlign = 'center';
        ctx.fillText('No data', w/2, h/2);
        return;
    }

    const max = Math.max(...data) * 1.1 || 1;
    const pad = { t: 10, b: 20, l: 50, r: 10 };
    const plotW = w - pad.l - pad.r;
    const plotH = h - pad.t - pad.b;

    const dates = timestamps.map(t => new Date(t));
    const minTime = dates[0].getTime();
    const maxTime = dates[dates.length - 1].getTime();
    const timeRange = maxTime - minTime;

    // Horizontal grid
    ctx.strokeStyle = '#222';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = pad.t + (plotH / 4) * i;
        ctx.beginPath();
        ctx.moveTo(pad.l, y);
        ctx.lineTo(w - pad.r, y);
        ctx.stroke();

        ctx.fillStyle = '#555';
        ctx.textAlign = 'right';
        ctx.font = '10px monospace';
        ctx.fillText((max - (max/4)*i).toFixed(1), pad.l - 5, y + 3);
    }

    // Hourly markers
    if (timeRange > 0) {
        const firstHour = new Date(dates[0]);
        firstHour.setMinutes(0, 0, 0);
        if (firstHour.getTime() <= minTime) {
            firstHour.setHours(firstHour.getHours() + 1);
        }

        ctx.strokeStyle = '#333';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 2]);
        ctx.fillStyle = '#666';
        ctx.textAlign = 'center';
        ctx.font = '9px monospace';

        let hour = new Date(firstHour);
        while (hour.getTime() <= maxTime) {
            const x = pad.l + ((hour.getTime() - minTime) / timeRange) * plotW;
            if (x >= pad.l && x <= w - pad.r) {
                ctx.beginPath();
                ctx.moveTo(x, pad.t);
                ctx.lineTo(x, pad.t + plotH);
                ctx.stroke();

                const label = hour.getHours().toString().padStart(2, '0') + ':00';
                ctx.fillText(label, x, h - 3);
            }
            hour.setHours(hour.getHours() + 1);
        }
        ctx.setLineDash([]);
    }

    // Line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    for (let i = 0; i < data.length; i++) {
        const x = timeRange > 0
            ? pad.l + ((dates[i].getTime() - minTime) / timeRange) * plotW
            : pad.l + (i / (data.length - 1 || 1)) * plotW;
        const y = pad.t + plotH - (data[i] / max) * plotH;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Fill
    const lastX = timeRange > 0
        ? pad.l + ((dates[dates.length - 1].getTime() - minTime) / timeRange) * plotW
        : pad.l + plotW;
    ctx.lineTo(lastX, pad.t + plotH);
    ctx.lineTo(pad.l, pad.t + plotH);
    ctx.closePath();
    ctx.fillStyle = color + '15';
    ctx.fill();
}

// Fixes
async function showServiceFixes(name) {
    currentService = name;
    document.getElementById('fixes-title').textContent = name;
    showModal('fixes-modal');
    await refreshFixes();
}

async function refreshFixes() {
    if (!currentService) return;
    try {
        const fixes = await api('GET', `/services/${currentService}/fixes`);
        if (!fixes.length) {
            document.getElementById('fixes-content').innerHTML = '<p class="text-gray-600">No fix attempts</p>';
            return;
        }

        document.getElementById('fixes-content').innerHTML = fixes.map(f => `
            <div class="bg-[#111] border-l-2 ${f.success ? 'border-l-green-500' : 'border-l-red-500'} border border-gray-800 p-3">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm ${f.success ? 'text-green-400' : 'text-red-400'}">${f.success ? 'Success' : 'Failed'}</span>
                    <span class="text-xs text-gray-500 font-mono">${formatTime(f.timestamp)}</span>
                    ${f.verdict ? `<span class="text-xs text-gray-500">${escapeHtml(f.verdict)}</span>` : ''}
                </div>
                <pre class="text-xs text-gray-400 whitespace-pre-wrap mb-2 max-h-24 overflow-auto">${escapeHtml(f.error_summary)}</pre>
                ${f.robot_response ? `<pre class="text-xs text-gray-500 whitespace-pre-wrap max-h-32 overflow-auto">${escapeHtml(f.robot_response)}</pre>` : ''}
            </div>
        `).join('');
    } catch (e) {
        document.getElementById('fixes-content').innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}

// Incidents
const DECISION_COLORS = {
    diagnosed: 'border-l-blue-500',
    fix_attempted: 'border-l-green-500',
    dismissed: 'border-l-gray-600',
    jev_unavailable: 'border-l-yellow-500',
    cooldown: 'border-l-gray-600',
    daily_cap: 'border-l-gray-600',
    disabled: 'border-l-gray-600',
};

async function showServiceIncidents(name) {
    currentService = name;
    document.getElementById('incidents-title').textContent = name;
    showModal('incidents-modal');
    await refreshIncidents();
}

function formatProbabilities(probs) {
    if (!probs) return '';
    return Object.entries(probs)
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => `${k} ${Math.round(v * 100)}%`)
        .join(' · ');
}

async function refreshIncidents() {
    if (!currentService) return;
    const content = document.getElementById('incidents-content');
    try {
        const incidents = await api('GET', `/services/${currentService}/incidents`);
        if (!incidents.length) {
            content.innerHTML = '<p class="text-gray-600">No incidents</p>';
            return;
        }
        content.innerHTML = incidents.map(i => `
            <div class="bg-[#111] border-l-2 ${DECISION_COLORS[i.decision] || 'border-l-gray-600'} border border-gray-800 p-3">
                <div class="flex items-center justify-between mb-1">
                    <span class="text-sm text-gray-200">${escapeHtml(i.decision)}${i.jev_kind ? ` · ${escapeHtml(i.jev_kind)}` : ''}${i.notified ? ' · notified' : ''}</span>
                    <span class="text-xs text-gray-500 font-mono">${formatTime(i.timestamp)}</span>
                </div>
                <div class="text-xs text-gray-500 mb-2">${i.strong_hits} strong hits${i.jev_probabilities ? ` · ${formatProbabilities(i.jev_probabilities)}` : ''}${i.jev_fixable != null ? ` · fixable ${Math.round(i.jev_fixable * 100)}%` : ''}</div>
                <pre class="text-xs text-gray-400 whitespace-pre-wrap mb-2 max-h-24 overflow-auto">${escapeHtml(i.sample)}</pre>
                ${i.diagnosis ? `<div class="text-xs text-blue-300 mb-1">Diagnosis</div><pre class="text-xs text-gray-300 whitespace-pre-wrap max-h-64 overflow-auto">${escapeHtml(i.diagnosis)}</pre>` : ''}
            </div>
        `).join('');
    } catch (e) {
        content.innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}
