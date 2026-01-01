/**
 * Cron job management for the supervisor dashboard.
 * Handles cron job listing, registration, editing, and execution history.
 */

async function loadCronJobs() {
    try {
        cronJobs = await api('GET', '/cron');
        renderCronList();
    } catch (e) {
        document.getElementById('cron-list').innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}

function renderCronList() {
    const list = document.getElementById('cron-list');
    if (!cronJobs.length) {
        list.innerHTML = '<p class="text-gray-600 text-center py-8">No cron jobs registered</p>';
        return;
    }

    list.innerHTML = cronJobs.map(j => {
        const statusClass = j.running ? 'border-l-blue-500' : (j.enabled ? 'border-l-green-500' : 'border-l-gray-500');
        return `
            <div class="bg-[#0a0a0a] border border-gray-800 border-l-2 ${statusClass} p-3">
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-4">
                        <span class="w-2 h-2 rounded-full ${j.running ? 'bg-blue-500 pulse-dot' : (j.enabled ? 'bg-green-500' : 'bg-gray-500')}"></span>
                        <div>
                            <div class="font-medium text-sm">${escapeHtml(j.name)}</div>
                            <div class="text-xs text-gray-500 font-mono">${escapeHtml(j.schedule)} - ${escapeHtml(j.schedule_description || '')}</div>
                        </div>
                    </div>
                    <div class="flex items-center gap-4">
                        <div class="text-xs text-gray-500">
                            ${j.last_run ? 'Last: ' + formatTime(j.last_run) : 'Never run'}
                            ${j.next_run ? ' | Next: ' + formatTime(j.next_run) : ''}
                        </div>
                        <div class="flex gap-1">
                            <button onclick="runCronJobNow('${j.name}')" class="px-2 py-1 text-xs border border-gray-700 text-green-400 hover:bg-green-500/10">Run</button>
                            <button onclick="showCronExecutions('${j.name}')" class="px-2 py-1 text-xs border border-gray-700 text-gray-400 hover:text-white">History</button>
                            <button onclick="showCronEditModal('${j.name}')" class="px-2 py-1 text-xs border border-gray-700 text-gray-400 hover:text-white">Edit</button>
                            <button onclick="deleteCronJob('${j.name}')" class="px-2 py-1 text-xs border border-gray-700 text-red-400 hover:bg-red-500/10">Delete</button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function showCronRegisterModal() {
    document.getElementById('cron-register-form').reset();
    showModal('cron-register-modal');
}

document.getElementById('cron-register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;

    try {
        await api('POST', '/cron', {
            name: form.name.value,
            command: form.command.value,
            schedule: form.schedule.value,
            working_dir: form.working_dir.value || null,
            timeout: parseInt(form.timeout.value) || 300,
            enabled: form.enabled.checked,
            env_file: form.env_file.value || null,
            env_vars: parseEnvVars(form.env_vars.value),
        });
        hideModal('cron-register-modal');
        form.reset();
        await loadCronJobs();
    } catch (e) { alert('Error: ' + e.message); }
});

function parseEnvVars(text) {
    if (!text || !text.trim()) return null;
    const vars = {};
    text.split('\n').forEach(line => {
        line = line.trim();
        if (!line || line.startsWith('#')) return;
        const idx = line.indexOf('=');
        if (idx > 0) {
            const key = line.slice(0, idx).trim();
            let value = line.slice(idx + 1).trim();
            if ((value.startsWith('"') && value.endsWith('"')) ||
                (value.startsWith("'") && value.endsWith("'"))) {
                value = value.slice(1, -1);
            }
            vars[key] = value;
        }
    });
    return Object.keys(vars).length > 0 ? vars : null;
}

function envVarsToText(vars) {
    if (!vars || Object.keys(vars).length === 0) return '';
    return Object.entries(vars).map(([k, v]) => `${k}=${v}`).join('\n');
}

async function showCronEditModal(name) {
    try {
        const j = await api('GET', `/cron/${name}`);
        document.getElementById('cron-edit-title').textContent = name;
        document.getElementById('cron-edit-name').value = name;
        document.getElementById('cron-edit-command').value = j.command;
        document.getElementById('cron-edit-schedule').value = j.schedule;
        document.getElementById('cron-edit-working_dir').value = j.working_dir || '';
        document.getElementById('cron-edit-timeout').value = j.timeout || 300;
        document.getElementById('cron-edit-enabled').checked = j.enabled;
        document.getElementById('cron-edit-env_file').value = j.env_file || '';
        document.getElementById('cron-edit-env_vars').value = envVarsToText(j.env_vars);
        showModal('cron-edit-modal');
    } catch (e) { alert('Error: ' + e.message); }
}

document.getElementById('cron-edit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = e.target;
    const name = form.name.value;

    try {
        await api('PUT', `/cron/${name}`, {
            command: form.command.value,
            schedule: form.schedule.value,
            working_dir: form.working_dir.value || null,
            timeout: parseInt(form.timeout.value) || 300,
            enabled: form.enabled.checked,
            env_file: form.env_file.value || null,
            env_vars: parseEnvVars(form.env_vars.value),
        });
        hideModal('cron-edit-modal');
        await loadCronJobs();
    } catch (e) { alert('Error: ' + e.message); }
});

async function deleteCronJob(name) {
    if (!confirm(`Delete cron job "${name}"?`)) return;
    try {
        await api('DELETE', `/cron/${name}`);
        await loadCronJobs();
    } catch (e) { alert('Error: ' + e.message); }
}

async function runCronJobNow(name) {
    try {
        const res = await api('POST', `/cron/${name}/run`);
        if (res.status === 'already_running') {
            alert(`${name} is already running`);
        } else {
            alert(`Started ${name}`);
        }
        await loadCronJobs();
    } catch (e) { alert('Error: ' + e.message); }
}

async function showCronExecutions(name) {
    currentCronJob = name;
    document.getElementById('cron-executions-title').textContent = name;
    showModal('cron-executions-modal');
    await refreshCronExecutions();
}

async function refreshCronExecutions() {
    if (!currentCronJob) return;
    try {
        const execs = await api('GET', `/cron/${currentCronJob}/executions?limit=50`);
        if (!execs.length) {
            document.getElementById('cron-executions-content').innerHTML = '<p class="text-gray-600">No executions yet</p>';
            return;
        }

        document.getElementById('cron-executions-content').innerHTML = execs.map(e => `
            <div class="bg-[#111] border-l-2 ${e.success ? 'border-l-green-500' : 'border-l-red-500'} border border-gray-800 p-3">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-sm ${e.success ? 'text-green-400' : 'text-red-400'}">${e.success ? 'Success' : 'Failed'} (exit ${e.exit_code})</span>
                    <div class="flex items-center gap-3 text-xs text-gray-500 font-mono">
                        <span>${e.duration_seconds ? e.duration_seconds.toFixed(1) + 's' : '-'}</span>
                        <span>${formatTime(e.started_at)}</span>
                    </div>
                </div>
                ${e.cpu_percent || e.memory_mb ? `
                <div class="text-xs text-gray-500 mb-2">CPU: ${e.cpu_percent?.toFixed(1) || 0}% | Mem: ${e.memory_mb?.toFixed(1) || 0}MB</div>
                ` : ''}
                ${e.fix_attempted ? `<div class="text-xs ${e.fix_success ? 'text-green-400' : 'text-yellow-400'} mb-2">Auto-fix ${e.fix_success ? 'succeeded' : 'attempted'}</div>` : ''}
                ${e.stdout ? `<pre class="text-xs text-gray-400 whitespace-pre-wrap max-h-24 overflow-auto mb-2">${escapeHtml(e.stdout.slice(0, 1000))}</pre>` : ''}
                ${e.stderr ? `<pre class="text-xs text-red-400 whitespace-pre-wrap max-h-24 overflow-auto">${escapeHtml(e.stderr.slice(0, 1000))}</pre>` : ''}
            </div>
        `).join('');
    } catch (e) {
        document.getElementById('cron-executions-content').innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}

// Schedule preview for cron register form
const scheduleInput = document.querySelector('#cron-register-form input[name="schedule"]');
if (scheduleInput) {
    let debounceTimer;
    scheduleInput.addEventListener('input', async (e) => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(async () => {
            const schedule = e.target.value.trim();
            if (!schedule) {
                document.getElementById('cron-schedule-preview').textContent = '';
                return;
            }
            try {
                const res = await api('GET', `/cron/validate?schedule=${encodeURIComponent(schedule)}`);
                if (res.valid) {
                    document.getElementById('cron-schedule-preview').textContent = res.description;
                    document.getElementById('cron-schedule-preview').classList.remove('text-red-400');
                    document.getElementById('cron-schedule-preview').classList.add('text-gray-500');
                } else {
                    document.getElementById('cron-schedule-preview').textContent = res.message;
                    document.getElementById('cron-schedule-preview').classList.remove('text-gray-500');
                    document.getElementById('cron-schedule-preview').classList.add('text-red-400');
                }
            } catch (e) {
                document.getElementById('cron-schedule-preview').textContent = 'Error validating';
            }
        }, 300);
    });
}
