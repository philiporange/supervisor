/**
 * Background jobs management for the supervisor dashboard.
 * Handles job listing and detail views.
 */

async function loadJobs() {
    const filter = document.getElementById('jobs-filter').value;
    const path = filter ? `/jobs?status=${filter}` : '/jobs';

    try {
        const jobs = await api('GET', path);
        if (!jobs.length) {
            document.getElementById('jobs-list').innerHTML = '<p class="text-gray-600 text-center py-8">No jobs</p>';
            return;
        }

        document.getElementById('jobs-list').innerHTML = jobs.map(j => `
            <div class="bg-[#0a0a0a] border border-gray-800 p-3 cursor-pointer hover:border-gray-600" onclick="showJobDetail('${j.id}')">
                <div class="flex items-center justify-between">
                    <span class="font-medium text-sm">${escapeHtml(j.name)}</span>
                    <span class="text-xs px-2 py-0.5 bg-[#111] ${
                        j.status === 'completed' ? 'text-green-400' :
                        j.status === 'failed' ? 'text-red-400' :
                        j.status === 'running' ? 'text-blue-400' : 'text-gray-400'
                    }">${j.status}</span>
                </div>
                <div class="text-xs text-gray-500 font-mono mt-1">
                    ${j.id} | ${formatTime(j.created_at)} ${j.duration_seconds ? `| ${j.duration_seconds.toFixed(1)}s` : ''}
                </div>
                ${j.error ? `<div class="text-xs text-red-400 mt-1">${escapeHtml(j.error)}</div>` : ''}
            </div>
        `).join('');
    } catch (e) {
        document.getElementById('jobs-list').innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}

async function showJobDetail(id) {
    document.getElementById('job-title').textContent = id;
    showModal('job-modal');

    try {
        const job = await api('GET', `/jobs/${id}`);
        document.getElementById('job-content').innerHTML = `
            <div class="space-y-3">
                <div class="grid grid-cols-2 gap-3 text-sm">
                    <div><span class="text-gray-500">Status:</span> <span class="${
                        job.status === 'completed' ? 'text-green-400' :
                        job.status === 'failed' ? 'text-red-400' : 'text-gray-300'
                    }">${job.status}</span></div>
                    <div><span class="text-gray-500">Duration:</span> ${job.duration_seconds ? job.duration_seconds.toFixed(1) + 's' : '-'}</div>
                    <div><span class="text-gray-500">Created:</span> ${formatTime(job.created_at)}</div>
                    <div><span class="text-gray-500">Completed:</span> ${job.completed_at ? formatTime(job.completed_at) : '-'}</div>
                </div>
                ${job.error ? `<div class="bg-red-500/10 border border-red-500/30 p-3 text-sm text-red-400"><pre class="whitespace-pre-wrap">${escapeHtml(job.error)}</pre></div>` : ''}
                ${job.result ? `<div class="bg-[#111] border border-gray-800 p-3"><pre class="text-xs text-gray-400 whitespace-pre-wrap max-h-64 overflow-auto">${escapeHtml(JSON.stringify(job.result, null, 2))}</pre></div>` : ''}
            </div>
        `;
    } catch (e) {
        document.getElementById('job-content').innerHTML = `<p class="text-red-400">Error: ${e.message}</p>`;
    }
}
