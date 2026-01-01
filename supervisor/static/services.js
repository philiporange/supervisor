/**
 * Service management for the supervisor dashboard.
 * Handles service listing, rendering, context menu, actions, and register/edit forms.
 */

// Live status updates
async function updateStatus() {
    try {
        const status = await api('GET', '/status');
        services = status.services;
        serviceHost = status.service_host || 'localhost';
        document.getElementById('running-count').textContent = status.running;
        document.getElementById('total-count').textContent = status.total;
        renderHome();
        renderServicesList();
    } catch (e) {
        console.error('Status update failed:', e);
    }
}

// Render home grid
function renderHome() {
    const grid = document.getElementById('home-grid');
    const noServices = document.getElementById('no-services');

    if (services.length === 0) {
        grid.innerHTML = '';
        noServices.classList.remove('hidden');
        return;
    }

    noServices.classList.add('hidden');
    grid.innerHTML = services.map(s => {
        const statusClass = s.running ? 'status-running' : 'status-stopped';
        const url = s.port ? `http://${serviceHost}:${s.port}` : '#';

        return `
            <a href="${url}" target="_blank"
               class="block p-4 bg-[#0a0a0a] border border-gray-800 hover:border-gray-600 transition-all ${statusClass}"
               data-service="${s.name}"
               oncontextmenu="showContextMenu(event, '${s.name}', ${s.running}, ${s.port || 'null'}); return false;">
                <div class="flex items-center gap-2 mb-2">
                    <span class="w-2 h-2 rounded-full ${s.running ? 'bg-green-500 pulse-dot' : 'bg-red-500'}"></span>
                    <span class="font-medium text-sm truncate">${escapeHtml(s.name)}</span>
                </div>
                <div class="text-xs text-gray-500 font-mono">
                    ${s.port ? ':' + s.port : 'no port'}
                </div>
                ${s.metrics ? `
                <div class="mt-2 text-xs text-gray-600 font-mono">
                    ${s.running ? `CPU ${s.metrics.cpu_percent}% | ${Math.round(s.metrics.memory_mb)}MB` : 'stopped'}
                </div>
                ` : ''}
            </a>
        `;
    }).join('');
}

// Render services list
function renderServicesList() {
    const list = document.getElementById('services-list');
    if (services.length === 0) {
        list.innerHTML = '<p class="text-gray-600 text-center py-8">No services registered</p>';
        return;
    }

    list.innerHTML = services.map(s => {
        const statusClass = s.running ? 'border-l-green-500' : 'border-l-red-500';
        const caddySubdomain = s.caddy_subdomain ? `'${s.caddy_subdomain}'` : 'null';
        return `
            <div class="bg-[#0a0a0a] border border-gray-800 border-l-2 ${statusClass} p-3 flex items-center justify-between"
                 oncontextmenu="showContextMenu(event, '${s.name}', ${s.running}, ${s.port || 'null'}, ${caddySubdomain}); return false;">
                <div class="flex items-center gap-4">
                    <span class="w-2 h-2 rounded-full ${s.running ? 'bg-green-500' : 'bg-red-500'}"></span>
                    <div>
                        <div class="font-medium text-sm">${escapeHtml(s.name)}</div>
                        <div class="text-xs text-gray-500 font-mono">${s.port ? ':' + s.port : '-'} | PID: ${s.pid || '-'}</div>
                    </div>
                </div>
                <div class="flex items-center gap-4">
                    ${s.metrics && s.running ? `
                    <div class="text-xs text-gray-500 font-mono">
                        CPU ${s.metrics.cpu_percent}% | ${Math.round(s.metrics.memory_mb)}MB
                    </div>
                    ` : ''}
                    <div class="flex gap-1">
                        ${s.running ? `
                            <button onclick="stopService('${s.name}')" class="px-2 py-1 text-xs border border-gray-700 text-red-400 hover:bg-red-500/10">Stop</button>
                            <button onclick="restartService('${s.name}')" class="px-2 py-1 text-xs border border-gray-700 text-yellow-400 hover:bg-yellow-500/10">Restart</button>
                        ` : `
                            <button onclick="startService('${s.name}')" class="px-2 py-1 text-xs border border-gray-700 text-green-400 hover:bg-green-500/10">Start</button>
                        `}
                        <button onclick="showServiceLogs('${s.name}')" class="px-2 py-1 text-xs border border-gray-700 text-gray-400 hover:text-white">Logs</button>
                        <button onclick="showServiceMetrics('${s.name}')" class="px-2 py-1 text-xs border border-gray-700 text-gray-400 hover:text-white">Metrics</button>
                        <button onclick="showServiceFixes('${s.name}')" class="px-2 py-1 text-xs border border-gray-700 text-gray-400 hover:text-white">Fixes</button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Context menu
function showContextMenu(e, name, running, port, caddySubdomain) {
    e.preventDefault();
    ctxService = { name, running, port, caddySubdomain };

    const menu = document.getElementById('context-menu');
    document.getElementById('ctx-start').classList.toggle('hidden', running);
    document.getElementById('ctx-stop').classList.toggle('hidden', !running);
    document.getElementById('ctx-security').classList.toggle('hidden', !caddySubdomain);

    menu.style.left = e.pageX + 'px';
    menu.style.top = e.pageY + 'px';
    menu.classList.remove('hidden');
}

function hideContextMenu() {
    document.getElementById('context-menu').classList.add('hidden');
}

document.addEventListener('click', hideContextMenu);
document.addEventListener('contextmenu', (e) => {
    if (!e.target.closest('[data-service]') && !e.target.closest('.service-card')) {
        hideContextMenu();
    }
});

async function ctxAction(action) {
    hideContextMenu();
    if (!ctxService) return;

    const { name, port } = ctxService;

    switch (action) {
        case 'open':
            if (port) window.open(`http://${serviceHost}:${port}`, '_blank');
            break;
        case 'start': await startService(name); break;
        case 'stop': await stopService(name); break;
        case 'restart': await restartService(name); break;
        case 'logs': showServiceLogs(name); break;
        case 'metrics': showServiceMetrics(name); break;
        case 'fixes': showServiceFixes(name); break;
        case 'fix': await triggerFix(name); break;
        case 'security': showSecurityScan(name); break;
        case 'edit': await showEditModal(name); break;
        case 'delete': await deleteService(name); break;
    }
}

// Service actions
async function startService(name) {
    try {
        await api('POST', `/services/${name}/start`);
        await updateStatus();
    } catch (e) { alert('Error: ' + e.message); }
}

async function stopService(name) {
    try {
        await api('POST', `/services/${name}/stop`);
        await updateStatus();
    } catch (e) { alert('Error: ' + e.message); }
}

async function restartService(name) {
    try {
        await api('POST', `/services/${name}/restart`);
        await updateStatus();
    } catch (e) { alert('Error: ' + e.message); }
}

async function deleteService(name) {
    if (!confirm(`Delete "${name}"?`)) return;
    try {
        await api('DELETE', `/services/${name}`);
        await updateStatus();
    } catch (e) { alert('Error: ' + e.message); }
}

async function triggerFix(name) {
    if (!confirm(`Trigger auto-fix for "${name}"?`)) return;
    try {
        const res = await api('POST', `/services/${name}/fix`);
        alert(`Fix job started: ${res.job_id}`);
    } catch (e) { alert('Error: ' + e.message); }
}

// Security Scan
let securityPollInterval = null;

async function showSecurityScan(name) {
    currentService = name;
    document.getElementById('security-title').textContent = name;
    document.getElementById('scan-status').textContent = '';
    document.getElementById('scan-summary').innerHTML = '';
    document.getElementById('security-placeholder').classList.remove('hidden');
    document.getElementById('security-findings').classList.add('hidden');
    showModal('security-modal');
    await loadLatestSecurityScan(name);
}

async function loadLatestSecurityScan(name) {
    try {
        const data = await api('GET', `/services/${name}/security-scan/latest`);
        if (data.has_scan) {
            if (data.status === 'running') {
                document.getElementById('scan-status').textContent = 'Scan in progress...';
                document.getElementById('scan-btn').disabled = true;
                startSecurityPoll(name);
            } else if (data.status === 'completed' && data.result) {
                displaySecurityResults(data.result);
            } else if (data.status === 'failed') {
                document.getElementById('scan-status').textContent = `Scan failed: ${data.error || 'Unknown error'}`;
            }
        }
    } catch (e) {
        console.error('Error loading security scan:', e);
    }
}

async function runSecurityScan(name) {
    document.getElementById('scan-btn').disabled = true;
    document.getElementById('scan-status').textContent = 'Starting scan...';
    document.getElementById('scan-summary').innerHTML = '';
    document.getElementById('security-placeholder').classList.remove('hidden');
    document.getElementById('security-findings').classList.add('hidden');

    try {
        await api('POST', `/services/${name}/security-scan`);
        document.getElementById('scan-status').textContent = 'Scan in progress...';
        startSecurityPoll(name);
    } catch (e) {
        document.getElementById('scan-btn').disabled = false;
        document.getElementById('scan-status').textContent = `Error: ${e.message}`;
    }
}

function startSecurityPoll(name) {
    stopSecurityPoll();
    securityPollInterval = setInterval(async () => {
        try {
            const data = await api('GET', `/services/${name}/security-scan/latest`);
            if (data.status === 'completed' && data.result) {
                stopSecurityPoll();
                displaySecurityResults(data.result);
            } else if (data.status === 'failed') {
                stopSecurityPoll();
                document.getElementById('scan-btn').disabled = false;
                document.getElementById('scan-status').textContent = `Scan failed: ${data.error || 'Unknown error'}`;
            }
        } catch (e) {
            console.error('Error polling security scan:', e);
        }
    }, 2000);
}

function stopSecurityPoll() {
    if (securityPollInterval) {
        clearInterval(securityPollInterval);
        securityPollInterval = null;
    }
}

function displaySecurityResults(result) {
    document.getElementById('scan-btn').disabled = false;
    document.getElementById('scan-status').textContent = result.scan_time ? `Scanned: ${new Date(result.scan_time).toLocaleString()}` : '';
    document.getElementById('security-placeholder').classList.add('hidden');
    document.getElementById('security-findings').classList.remove('hidden');

    const summary = result.summary || { red: 0, amber: 0, green: 0 };
    document.getElementById('scan-summary').innerHTML = `
        <span class="flex items-center gap-1">
            <span class="w-3 h-3 rounded-full bg-red-500"></span>
            <span class="text-sm text-red-400">${summary.red || 0}</span>
        </span>
        <span class="flex items-center gap-1">
            <span class="w-3 h-3 rounded-full bg-amber-500"></span>
            <span class="text-sm text-amber-400">${summary.amber || 0}</span>
        </span>
        <span class="flex items-center gap-1">
            <span class="w-3 h-3 rounded-full bg-green-500"></span>
            <span class="text-sm text-green-400">${summary.green || 0}</span>
        </span>
    `;

    const findings = result.findings || [];
    const findingsEl = document.getElementById('security-findings');

    if (findings.length === 0) {
        findingsEl.innerHTML = '<p class="text-gray-500 text-center py-4">No findings</p>';
        return;
    }

    const grouped = { red: [], amber: [], green: [] };
    findings.forEach(f => {
        if (grouped[f.status]) grouped[f.status].push(f);
    });

    findingsEl.innerHTML = [...grouped.red, ...grouped.amber, ...grouped.green].map(f => {
        const statusColors = {
            red: 'border-l-red-500 bg-red-500/5',
            amber: 'border-l-amber-500 bg-amber-500/5',
            green: 'border-l-green-500 bg-green-500/5'
        };
        const dotColors = { red: 'bg-red-500', amber: 'bg-amber-500', green: 'bg-green-500' };
        return `
            <div class="border border-gray-800 border-l-2 ${statusColors[f.status] || ''} p-3">
                <div class="flex items-start gap-2">
                    <span class="w-2 h-2 rounded-full ${dotColors[f.status] || ''} mt-1.5 flex-shrink-0"></span>
                    <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-xs text-gray-500 uppercase">${escapeHtml(f.category || '')}</span>
                        </div>
                        <div class="font-medium text-sm">${escapeHtml(f.check || '')}</div>
                        <div class="text-sm text-gray-400 mt-1">${escapeHtml(f.detail || '')}</div>
                        ${f.recommendation ? `<div class="text-xs text-blue-400 mt-2">Recommendation: ${escapeHtml(f.recommendation)}</div>` : ''}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// Register form
function showRegisterModal() { showModal('register-modal'); }

document.getElementById('reg-expose-caddy').addEventListener('change', (e) => {
    document.getElementById('reg-caddy-subdomain').classList.toggle('hidden', !e.target.checked);
});

document.getElementById('register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const watchDirs = form.watch_dirs.value.trim();

    try {
        await api('POST', '/services', {
            name: form.name.value,
            command: form.command.value,
            working_dir: form.working_dir.value || null,
            port: form.port.value ? parseInt(form.port.value) : null,
            enabled: form.enabled.checked,
            expose_caddy: form.expose_caddy.checked,
            caddy_subdomain: form.caddy_subdomain.value || null,
            watch_dirs: watchDirs ? watchDirs.split(',').map(d => d.trim()) : null,
        });
        hideModal('register-modal');
        form.reset();
        await updateStatus();
    } catch (e) { alert('Error: ' + e.message); }
});

// Edit form
async function showEditModal(name) {
    try {
        const s = await api('GET', `/services/${name}`);
        document.getElementById('edit-title').textContent = name;
        document.getElementById('edit-name').value = name;
        document.getElementById('edit-command').value = s.command;
        document.getElementById('edit-working_dir').value = s.working_dir || '';
        document.getElementById('edit-port').value = s.port || '';
        document.getElementById('edit-watch_dirs').value = s.watch_dirs ? s.watch_dirs.join(', ') : '';
        document.getElementById('edit-enabled').checked = s.enabled;
        document.getElementById('edit-expose_caddy').checked = s.expose_caddy;
        document.getElementById('edit-caddy_subdomain').value = s.caddy_subdomain || '';
        showModal('edit-modal');
    } catch (e) { alert('Error: ' + e.message); }
}

document.getElementById('edit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const name = form.name.value;
    const watchDirs = form.watch_dirs.value.trim();

    try {
        await api('PUT', `/services/${name}`, {
            command: form.command.value,
            working_dir: form.working_dir.value || null,
            port: form.port.value ? parseInt(form.port.value) : null,
            enabled: form.enabled.checked,
            expose_caddy: form.expose_caddy.checked,
            caddy_subdomain: form.caddy_subdomain.value || null,
            watch_dirs: watchDirs ? watchDirs.split(',').map(d => d.trim()) : [],
        });
        hideModal('edit-modal');
        await updateStatus();
    } catch (e) { alert('Error: ' + e.message); }
});
