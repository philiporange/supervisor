/**
 * AI chat functionality for the supervisor dashboard.
 * Handles streaming chat with Robot AI and project onboarding.
 */

let chatAbortController = null;

async function loadProjects() {
    try {
        const data = await api('GET', '/projects');
        const select = document.getElementById('chat-project');
        select.innerHTML = '<option value="">No project</option>';
        for (const proj of data.projects) {
            select.innerHTML += `<option value="${proj.name}">${proj.name}</option>`;
        }
    } catch (e) {
        console.error('Failed to load projects:', e);
    }
}

function clearChat() {
    document.getElementById('chat-messages').innerHTML = `
        <div class="text-center text-gray-600 py-16">
            <p class="mb-2 text-gray-500">AI Assistant</p>
            <p class="text-xs text-gray-600">Ask questions, onboard projects, or get help with services</p>
        </div>
    `;
}

function addChatMessage(role, content, isStreaming = false) {
    const messages = document.getElementById('chat-messages');
    const isWelcome = messages.querySelector('.text-center');
    if (isWelcome) messages.innerHTML = '';

    const msgId = isStreaming ? 'streaming-message' : `msg-${Date.now()}`;
    const existing = document.getElementById(msgId);

    if (existing) {
        existing.querySelector('.message-content').innerHTML = formatMessage(content);
    } else {
        const roleClass = role === 'user' ? 'chat-message user' : 'chat-message';
        const roleLabel = role === 'user' ? 'You' : 'Assistant';
        messages.innerHTML += `
            <div id="${msgId}" class="${roleClass}">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide font-medium">${roleLabel}</div>
                <div class="message-content text-sm leading-relaxed whitespace-pre-wrap text-gray-300">${formatMessage(content)}</div>
            </div>
        `;
    }

    messages.scrollTop = messages.scrollHeight;
    return msgId;
}

function formatMessage(content) {
    return escapeHtml(content)
        .replace(/`([^`]+)`/g, '<code class="bg-gray-800 px-1.5 py-0.5 rounded text-gray-200 text-xs">$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-gray-100">$1</strong>');
}

function setChatLoading(loading) {
    const btn = document.getElementById('chat-send');
    const container = document.getElementById('chat-input-container');
    const input = document.getElementById('chat-input');

    if (loading) {
        btn.innerHTML = `<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>`;
        btn.onclick = stopChat;
        btn.classList.add('stop');
        container.classList.add('processing');
        input.disabled = true;
    } else {
        btn.innerHTML = `<svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 5l7 7-7 7M5 12h15"/>
        </svg>`;
        btn.onclick = sendChatMessage;
        btn.classList.remove('stop');
        container.classList.remove('processing');
        input.disabled = false;
        input.focus();
        input.style.height = '24px';
    }
}

function stopChat() {
    if (chatAbortController) {
        chatAbortController.abort();
        chatAbortController = null;
    }
    setChatLoading(false);
}

async function sendChatMessage() {
    const input = document.getElementById('chat-input');
    const message = input.value.trim();
    if (!message) return;

    const project = document.getElementById('chat-project').value || null;
    const model = document.getElementById('chat-model').value;

    addChatMessage('user', message);
    input.value = '';
    setChatLoading(true);

    chatAbortController = new AbortController();
    let responseContent = '';

    try {
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, project, model }),
            signal: chatAbortController.signal,
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Chat request failed');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const event = JSON.parse(line.slice(6));
                    if (event.type === 'text' || event.type === 'content') {
                        responseContent += (event.content || '') + '\n';
                        addChatMessage('assistant', responseContent.trim(), true);
                    } else if (event.type === 'result' && event.content) {
                        responseContent = event.content;
                        addChatMessage('assistant', responseContent, true);
                    } else if (event.type === 'error') {
                        addChatMessage('assistant', `Error: ${event.content}`, true);
                    } else if (event.type === 'done') {
                        const streaming = document.getElementById('streaming-message');
                        if (streaming) streaming.id = `msg-${Date.now()}`;
                    }
                } catch (e) {
                    // Ignore parse errors
                }
            }
        }
    } catch (e) {
        if (e.name !== 'AbortError') {
            addChatMessage('assistant', `Error: ${e.message}`);
        }
    } finally {
        setChatLoading(false);
        chatAbortController = null;
    }
}

async function onboardProject() {
    const project = document.getElementById('chat-project').value.trim();
    if (!project) {
        alert('Enter a project name or path first');
        return;
    }

    const model = document.getElementById('chat-model').value;

    addChatMessage('user', `Onboard project: ${project}`);
    setChatLoading(true);

    try {
        const preview = await api('GET', `/onboard/preview?project=${encodeURIComponent(project)}`);
        addChatMessage('assistant', `Analyzing project: ${preview.project_name}\nPath: ${preview.project_path}\nData dir: ${preview.data_dir}\n\nStarting onboard job...`);

        const result = await api('POST', '/onboard', { project, model });
        addChatMessage('assistant', `Onboard job started: ${result.job_id}\n\nCheck the Jobs tab for progress.`);

        pollJobStatus(result.job_id);
    } catch (e) {
        addChatMessage('assistant', `Error: ${e.message}`);
    } finally {
        setChatLoading(false);
    }
}

async function pollJobStatus(jobId) {
    const poll = async () => {
        try {
            const job = await api('GET', `/jobs/${jobId}`);
            if (job.status === 'completed') {
                addChatMessage('assistant', `Onboard completed!\n\n${job.result?.output || 'Project registered successfully.'}`);
                await updateStatus();
            } else if (job.status === 'failed') {
                addChatMessage('assistant', `Onboard failed: ${job.error || 'Unknown error'}`);
            } else {
                setTimeout(poll, 2000);
            }
        } catch (e) {
            console.error('Poll error:', e);
        }
    };
    setTimeout(poll, 1000);
}
