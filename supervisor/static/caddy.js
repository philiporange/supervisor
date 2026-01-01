/**
 * Caddy configuration management for the supervisor dashboard.
 * Handles displaying and reloading Caddy reverse proxy config.
 */

async function loadCaddy() {
    try {
        const conf = await api('GET', '/caddy/config');
        document.getElementById('caddy-config').textContent = conf.caddyfile;

        if (conf.services.length) {
            document.getElementById('caddy-services').innerHTML = conf.services.map(s => `
                <div class="bg-[#111] border border-gray-800 px-3 py-2 font-mono text-sm flex gap-4">
                    <span class="text-gray-300">${escapeHtml(s.name)}</span>
                    <span class="text-blue-400">${s.path}</span>
                    <span class="text-gray-500">:${s.port}</span>
                </div>
            `).join('');
        } else {
            document.getElementById('caddy-services').innerHTML = '<p class="text-gray-600">No services exposed</p>';
        }
    } catch (e) {
        document.getElementById('caddy-config').textContent = 'Error: ' + e.message;
    }
}

async function reloadCaddy() {
    try {
        await api('POST', '/caddy/reload');
        alert('Caddy reloaded');
        await loadCaddy();
    } catch (e) { alert('Error: ' + e.message); }
}
