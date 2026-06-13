/**
 * Nucleus AI — Frontend Chat Logic
 *
 * Handles:
 * - Sending questions to the backend API
 * - Rendering AI responses with markdown and source links
 * - Auto-resize textarea
 * - Health check and connection status
 * - Quick question buttons
 */

// ============================================
// Configuration
// ============================================

const API_BASE = window.location.origin;
const ENDPOINTS = {
    chat: `${API_BASE}/api/chat`,
    health: `${API_BASE}/api/health`,
};

// ============================================
// DOM Elements
// ============================================

const chatArea = document.getElementById('chat-area');
const welcomeScreen = document.getElementById('welcome-screen');
const inputField = document.getElementById('input-field');
const sendBtn = document.getElementById('send-btn');
const statusDot = document.getElementById('status-dot');
const statusText = document.getElementById('status-text');
const errorToast = document.getElementById('error-toast');

// ============================================
// State
// ============================================

let isLoading = false;
let conversationStarted = false;

// ============================================
// Health Check
// ============================================

async function checkHealth() {
    try {
        const response = await fetch(ENDPOINTS.health, { signal: AbortSignal.timeout(5000) });
        if (response.ok) {
            const data = await response.json();
            statusDot.classList.remove('offline');
            statusText.textContent = `Online · ${data.knowledge_base_size.toLocaleString()} docs`;
            return true;
        }
    } catch (e) {
        // Server not reachable
    }
    statusDot.classList.add('offline');
    statusText.textContent = 'Offline';
    return false;
}

// Check health on load and every 30 seconds
checkHealth();
setInterval(checkHealth, 30000);

// ============================================
// Input Handling
// ============================================

// Auto-resize textarea
inputField.addEventListener('input', () => {
    inputField.style.height = 'auto';
    inputField.style.height = Math.min(inputField.scrollHeight, 120) + 'px';
    sendBtn.disabled = !inputField.value.trim();
});

// Send on Enter (Shift+Enter for newline)
inputField.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!isLoading && inputField.value.trim()) {
            sendMessage();
        }
    }
});

// Send button click
sendBtn.addEventListener('click', () => {
    if (!isLoading && inputField.value.trim()) {
        sendMessage();
    }
});

// Quick question buttons
document.querySelectorAll('.quick-question').forEach((btn) => {
    btn.addEventListener('click', () => {
        const question = btn.getAttribute('data-question');
        inputField.value = question;
        sendBtn.disabled = false;
        sendMessage();
    });
});

// ============================================
// Send Message
// ============================================

async function sendMessage() {
    const question = inputField.value.trim();
    if (!question || isLoading) return;

    // Hide welcome screen
    if (!conversationStarted) {
        welcomeScreen.style.display = 'none';
        conversationStarted = true;
    }

    // Add user message
    appendMessage('user', question);

    // Clear input
    inputField.value = '';
    inputField.style.height = 'auto';
    sendBtn.disabled = true;

    // Show typing indicator
    const typingEl = appendTypingIndicator();

    // Send to API
    isLoading = true;

    try {
        const response = await fetch(ENDPOINTS.chat, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question }),
            signal: AbortSignal.timeout(60000), // 60s timeout
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Server error (${response.status})`);
        }

        const data = await response.json();

        // Remove typing indicator
        typingEl.remove();

        // Add assistant response
        appendMessage('assistant', data.answer, data.sources, data.response_time_ms);

    } catch (error) {
        typingEl.remove();

        if (error.name === 'TimeoutError') {
            showError('Request timed out. Please try again.');
            appendMessage('assistant', 'Sorry, the request timed out. Please try again with a simpler question.');
        } else if (error.name === 'TypeError' && error.message.includes('fetch')) {
            showError('Cannot connect to the server. Is it running?');
            appendMessage('assistant', 'I can\'t connect to the server right now. Make sure the backend is running on `localhost:8000`.');
        } else {
            showError(error.message);
            appendMessage('assistant', `Sorry, something went wrong: ${error.message}. Please try again.`);
        }
    } finally {
        isLoading = false;
        sendBtn.disabled = !inputField.value.trim();
    }
}

// ============================================
// Message Rendering
// ============================================

function appendMessage(role, content, sources = [], responseTimeMs = null) {
    const messageEl = document.createElement('div');
    messageEl.className = `message ${role}`;

    const avatar = role === 'assistant' ? 'N' : '👤';
    const bubbleContent = role === 'assistant'
        ? renderMarkdown(content)
        : escapeHtml(content);

    let sourcesHtml = '';
    if (sources && sources.length > 0) {
        sourcesHtml = `
            <div class="sources-section">
                <div class="sources-title">📚 Sources</div>
                ${sources.map(s => `
                    <a href="${escapeHtml(s.url)}" target="_blank" rel="noopener" class="source-link">
                        <span class="source-link-icon">🔗</span>
                        <div class="source-link-text">
                            <div class="source-link-title">${escapeHtml(s.title || 'UNSW Page')}</div>
                            <div class="source-link-url">${escapeHtml(s.url)}</div>
                        </div>
                        <span class="source-link-arrow">→</span>
                    </a>
                `).join('')}
            </div>
        `;
    }

    let metaHtml = '';
    if (responseTimeMs !== null) {
        const timeStr = responseTimeMs > 1000
            ? `${(responseTimeMs / 1000).toFixed(1)}s`
            : `${responseTimeMs}ms`;
        metaHtml = `<div class="message-meta">Response time: ${timeStr}</div>`;
    }

    messageEl.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-content">
            <div class="message-bubble">
                ${bubbleContent}
                ${sourcesHtml}
            </div>
            ${metaHtml}
        </div>
    `;

    chatArea.appendChild(messageEl);
    scrollToBottom();
}

function appendTypingIndicator() {
    const el = document.createElement('div');
    el.className = 'message assistant';
    el.innerHTML = `
        <div class="message-avatar">N</div>
        <div class="message-content">
            <div class="message-bubble">
                <div class="typing-indicator">
                    <span class="typing-dot"></span>
                    <span class="typing-dot"></span>
                    <span class="typing-dot"></span>
                </div>
            </div>
        </div>
    `;
    chatArea.appendChild(el);
    scrollToBottom();
    return el;
}

// ============================================
// Markdown Rendering (lightweight)
// ============================================

function renderMarkdown(text) {
    if (!text) return '';

    let html = escapeHtml(text);

    // Headers
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // Italic
    html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

    // Inline code
    html = html.replace(/`(.+?)`/g, '<code>$1</code>');

    // Links [text](url)
    html = html.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener">$1</a>'
    );

    // Unordered lists
    html = html.replace(/^[\-\*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>');

    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

    // Paragraphs (double newlines)
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';

    // Single newlines → <br> (but not inside lists)
    html = html.replace(/([^>])\n([^<])/g, '$1<br>$2');

    // Clean up empty paragraphs
    html = html.replace(/<p>\s*<\/p>/g, '');

    // Clean up paragraphs wrapping block elements
    html = html.replace(/<p>(<[hul])/g, '$1');
    html = html.replace(/(<\/[hul]\d?>)<\/p>/g, '$1');

    return html;
}

// ============================================
// Utilities
// ============================================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatArea.scrollTop = chatArea.scrollHeight;
    });
}

function showError(message) {
    errorToast.textContent = message;
    errorToast.classList.add('visible');
    setTimeout(() => {
        errorToast.classList.remove('visible');
    }, 4000);
}

// ============================================
// Focus input on load
// ============================================
inputField.focus();
