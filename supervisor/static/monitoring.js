/**
 * Monitoring functionality for the supervisor dashboard.
 * Handles service logs, supervisor logs, metrics charts, and fix history.
 */

// Service Logs
let logsInterval = null;
let logsUserScrolled = false;

async function showServiceLogs(name) {
    currentService = name;
    logsUserScrolled = false;
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
        logsInterval = setInterval(refreshServiceLogs, 1000);
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

async function refreshServiceLogs() {
    if (!currentService) return;
    const level = document.getElementById('logs-level').value;
    const limit = document.getElementById('logs-limit').value;
    let path = `/services/${currentService}/logs?limit=${limit}`;
    if (level) path += `&level=${level}`;

    try {
        const logs = await api('GET', path);
        const content = document.getElementById('logs-content');
        const wasAtBottom = content.scrollHeight - content.scrollTop - content.clientHeight < 50;

        content.innerHTML = logs.map(l =>
            `<span class="${l.level === 'error' ? 'text-red-400' : 'text-gray-400'}">[${formatTime(l.timestamp)}] ${escapeHtml(l.message)}</span>`
        ).join('\n') || 'No logs';

        if (!logsUserScrolled || wasAtBottom) {
            content.scrollTop = content.scrollHeight;
        }

        document.getElementById('logs-status').textContent = `${logs.length} lines`;
    } catch (e) {
        document.getElementById('logs-content').textContent = 'Error: ' + e.message;
    }
}

// Supervisor logs
let supervisorLogsInterval = null;
let supervisorLogsUserScrolled = false;

async function loadSupervisorLogs() {
    const lines = document.getElementById('log-lines').value;
    const content = document.getElementById('supervisor-logs');
    const wasAtTop = content.scrollTop < 50;

    try {
        const res = await api('GET', `/supervisor/logs?lines=${lines}`);
        content.textContent = res.lines.reverse().join('');

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
        supervisorLogsInterval = setInterval(loadSupervisorLogs, 1000);
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
                    ${f.can_restore ? `<button onclick="restoreBackup(${f.id})" class="px-2 py-1 text-xs bg-yellow-600 text-white hover:bg-yellow-500">Restore</button>` : ''}
                    ${f.restored ? '<span class="text-xs text-gray-500">Restored</span>' : ''}
                </div>
                <pre class="text-xs text-gray-400 whitespace-pre-wrap mb-2 max-h-24 overflow-auto">${escapeHtml(f.error_summary)}</pre>
                ${f.robot_response ? `<pre class="text-xs text-gray-500 whitespace-pre-wrap max-h-32 overflow-auto">${escapeHtml(f.robot_response)}</pre>` : ''}
            </div>
        `).join('');
    } catch (e) {
        document.getElementById('fixes-content').innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}

async function restoreBackup(fixId) {
    if (!confirm('Restore from backup?')) return;
    try {
        await api('POST', `/fixes/${fixId}/restore`);
        alert('Restored successfully');
        await refreshFixes();
    } catch (e) { alert('Error: ' + e.message); }
}
