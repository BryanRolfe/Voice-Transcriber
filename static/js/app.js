const API = '';

// DOM elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const dropContent = document.getElementById('drop-content');
const uploadProgress = document.getElementById('upload-progress');
const progressFill = document.getElementById('progress-fill');
const uploadStatus = document.getElementById('upload-status');
const recordingsList = document.getElementById('recordings-list');
const refreshBtn = document.getElementById('refresh-btn');
const retranscribeAllBtn = document.getElementById('retranscribe-all-btn');
const modelSelect = document.getElementById('model-select');
const diarizeToggle = document.getElementById('diarize-toggle');
const diarizeOption = document.getElementById('diarize-option');
const notifyToggle = document.getElementById('notify-toggle');
const notifyOption = document.getElementById('notify-option');

let pollInterval = null;
let expandedCards = new Set();
let selectedCards = new Set();
let audioPlaying = false;
let isRenaming = false;
let selectMode = false;
let transcriptCache = {};

// Load available models
async function loadModels() {
    try {
        const res = await fetch(`${API}/api/models`);
        const data = await res.json();
        modelSelect.innerHTML = data.models.map(m =>
            `<option value="${m.id}"${m.id === data.default ? ' selected' : ''}>${m.name} \u2014 ${m.description}</option>`
        ).join('');
        if (data.diarization_available) {
            diarizeOption.style.display = '';
        }
        if (data.notifications_available) {
            notifyOption.style.display = '';
            notifyToggle.checked = data.notify_progress;
        }
    } catch {
        modelSelect.innerHTML = '<option value="medium.en">Medium</option>';
    }
}
loadModels();

notifyToggle.addEventListener('change', async () => {
    try {
        const res = await fetch(`${API}/api/notifications/toggle`, { method: 'POST' });
        const data = await res.json();
        notifyToggle.checked = data.notify_progress;
    } catch { }
});

// File upload
dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
});
fileInput.addEventListener('change', () => {
    if (fileInput.files.length) uploadFiles(fileInput.files);
});

function uploadFiles(files) {
    const fileList = Array.from(files);
    let completed = 0;
    let failed = 0;
    const total = fileList.length;

    dropContent.classList.add('hidden');
    uploadProgress.classList.remove('hidden');
    uploadStatus.textContent = `Uploading 0/${total}...`;
    progressFill.style.width = '0%';

    function uploadNext(index) {
        if (index >= fileList.length) {
            const msg = failed > 0
                ? `Done! ${completed} uploaded, ${failed} failed.`
                : `${completed} file${completed > 1 ? 's' : ''} uploaded! Transcribing...`;
            uploadStatus.textContent = msg;
            progressFill.style.width = '100%';
            loadRecordings();
            startPolling();
            setTimeout(() => {
                dropContent.classList.remove('hidden');
                uploadProgress.classList.add('hidden');
                progressFill.style.width = '0%';
                fileInput.value = '';
            }, 2000);
            return;
        }

        const file = fileList[index];
        const formData = new FormData();
        formData.append('file', file);
        formData.append('model', modelSelect.value);
        if (diarizeToggle.checked) formData.append('diarize', 'true');

        const xhr = new XMLHttpRequest();
        xhr.open('POST', `${API}/api/upload`);

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const filePct = e.loaded / e.total;
                const overallPct = Math.round(((index + filePct) / total) * 100);
                progressFill.style.width = overallPct + '%';
                uploadStatus.textContent = `Uploading ${index + 1}/${total}: ${file.name}`;
            }
        };

        xhr.onload = () => {
            if (xhr.status === 401) { window.location.href = '/login'; return; }
            if (xhr.status === 201) completed++;
            else failed++;
            loadRecordings();
            uploadNext(index + 1);
        };

        xhr.onerror = () => {
            failed++;
            uploadNext(index + 1);
        };

        xhr.send(formData);
    }

    uploadNext(0);
}

// Load recordings
async function loadRecordings() {
    try {
        const res = await fetch(`${API}/api/recordings`);
        if (res.status === 401) { window.location.href = '/login'; return; }
        const recordings = await res.json();

        if (!audioPlaying && !isRenaming) renderRecordings(recordings);

        const processing = recordings.some(r => r.status === 'transcribing' || r.status === 'uploaded');
        if (processing) startPolling();
        else stopPolling();
    } catch {
        if (!audioPlaying && !isRenaming) {
            recordingsList.innerHTML = '<p class="empty-state">Failed to load recordings</p>';
        }
    }
}

function renderRecordings(recordings) {
    if (!recordings.length) {
        recordingsList.innerHTML = '<p class="empty-state">No recordings yet. Upload one above!</p>';
        updateBatchBar();
        return;
    }

    recordingsList.innerHTML = recordings.map(r => {
        const isOpen = expandedCards.has(r.id);
        const isSelected = selectedCards.has(r.id);
        const preview = getPreviewText(r);
        const progressBar = r.status === 'transcribing' && r.progress != null && r.progress >= 80
            ? `<div class="card-progress"><div class="card-progress-fill" style="width:${r.progress}%"></div></div><div class="card-progress-text">Identifying speakers...${r.transcribing_model ? ' · ' + escapeHtml(r.transcribing_model) : ''}</div>`
            : r.status === 'transcribing' && r.progress != null
            ? `<div class="card-progress"><div class="card-progress-fill" style="width:${r.progress}%"></div></div><div class="card-progress-text">${Math.round(r.progress)}% transcribed${r.transcribing_model ? ' · ' + escapeHtml(r.transcribing_model) : ''}${estimateETA(r)}</div>`
            : r.status === 'transcribing'
            ? `<div class="card-progress"><div class="card-progress-fill card-progress-indeterminate"></div></div><div class="card-progress-text">Loading model...${r.transcribing_model ? ' · ' + escapeHtml(r.transcribing_model) : ''}</div>`
            : '';
        const selectedModel = modelSelect.options[modelSelect.selectedIndex];
        const modelLabel = selectedModel ? selectedModel.textContent.split(' —')[0] : '';
        return `
        <div class="recording-card${isOpen ? ' open' : ''}${isSelected ? ' selected' : ''}${selectMode ? ' select-mode' : ''}" data-id="${r.id}">
            <div class="card-header">
                ${selectMode ? `<label class="select-checkbox" onclick="event.stopPropagation()"><input type="checkbox" ${isSelected ? 'checked' : ''} data-select-id="${r.id}"><span class="checkbox-mark"></span></label>` : ''}
                <span class="card-icon">${statusIcon(r.status)}</span>
                <div class="card-info">
                    <div class="card-name"><span class="card-name-text">${escapeHtml(r.display_name || r.original_filename)}</span></div>
                    <div class="card-meta">${r.display_name ? escapeHtml(r.original_filename) + ' · ' : ''}${formatSize(r.file_size)} · ${formatDate(r.created_at)}${r.duration_seconds ? ' · ' + formatDuration(r.duration_seconds) : ''}${(r.transcribing_model || r.model) ? ' · ' + escapeHtml(r.transcribing_model || r.model) : ''}</div>
                </div>
                <span class="card-status status-${r.status}">${r.status}</span>
                <span class="card-chevron">▼</span>
            </div>
            ${progressBar}
            <div class="card-preview${!preview ? ' empty-transcript' : ''}">${escapeHtml(preview)}</div>
            <div class="card-body${isOpen ? ' expanded' : ''}">
                <div class="custom-player">
                    <audio preload="none" src="${API}/api/recordings/${r.id}/audio"></audio>
                    <button class="player-btn" aria-label="Play">
                        <svg class="play-icon" viewBox="0 0 24 24" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg>
                        <svg class="pause-icon hidden" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="4" width="4" height="16"/><rect x="15" y="4" width="4" height="16"/></svg>
                    </button>
                    <span class="player-time player-current">0:00</span>
                    <div class="player-progress">
                        <div class="player-track"><div class="player-fill"></div></div>
                        <input type="range" class="player-range" min="0" max="100" step="0.1" value="0">
                    </div>
                    <span class="player-time player-duration">${r.duration_seconds ? formatDuration(r.duration_seconds) : '-:--'}</span>
                </div>
                <div class="transcript-full">${transcriptContent(r)}</div>
                <div class="card-actions">
                    <button class="btn rename-btn" data-id="${r.id}">✏️ Rename</button>
                    <button class="btn copy-btn" data-id="${r.id}">📋 Copy</button>
                    <button class="btn retranscribe-btn" data-id="${r.id}">✨ Re-transcribe (${modelLabel})</button>
                    <button class="btn btn-danger delete-btn" data-id="${r.id}">🗑️ Delete</button>
                </div>
            </div>
        </div>`;
    }).join('');

    // Attach events
    recordingsList.querySelectorAll('.card-header').forEach(header => {
        header.addEventListener('click', () => {
            if (selectMode) return;
            toggleCard(header.closest('.recording-card').dataset.id);
        });
    });
    recordingsList.querySelectorAll('.card-preview').forEach(preview => {
        preview.addEventListener('click', () => {
            if (selectMode) return;
            toggleCard(preview.closest('.recording-card').dataset.id);
        });
    });
    recordingsList.querySelectorAll('[data-select-id]').forEach(cb => {
        cb.addEventListener('change', () => {
            const id = cb.dataset.selectId;
            if (cb.checked) selectedCards.add(id);
            else selectedCards.delete(id);
            updateBatchBar();
            cb.closest('.recording-card').classList.toggle('selected', cb.checked);
        });
    });
    recordingsList.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); copyTranscript(btn); });
    });
    recordingsList.querySelectorAll('.retranscribe-btn').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); retranscribe(btn.dataset.id, btn); });
    });
    recordingsList.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); deleteRecording(btn.dataset.id); });
    });
    recordingsList.querySelectorAll('.rename-btn').forEach(btn => {
        btn.addEventListener('click', (e) => { e.stopPropagation(); startRename(btn.dataset.id); });
    });
    setupPlayers();
    updateBatchBar();
}

function getPreviewText(r) {
    if (r.status === 'completed' && r.transcript_preview) return r.transcript_preview;
    if (r.status === 'transcribing') return 'Transcription in progress...';
    if (r.status === 'failed') return 'Transcription failed';
    if (r.status === 'uploaded') return 'Waiting for transcription...';
    return '';
}

function estimateETA(r) {
    if (!r.started || !r.progress || r.progress < 5) return '';
    const elapsed = Date.now() / 1000 - r.started;
    const remaining = (elapsed / r.progress) * (100 - r.progress);
    if (remaining < 60) return ` · ~${Math.round(remaining)}s left`;
    return ` · ~${Math.round(remaining / 60)}m left`;
}

function transcriptContent(r) {
    const full = transcriptCache[r.id];
    if (r.status === 'completed' && full) {
        return full.split('\n').map(line => escapeHtml(line)).join('<br>');
    }
    if (r.status === 'completed') return '<span style="color:var(--text-muted)">Loading transcript...</span>';
    if (r.status === 'transcribing') return '<span style="color:var(--warning)">Transcription in progress...</span>';
    if (r.status === 'failed') return `<span style="color:var(--danger)">Failed: ${escapeHtml(r.transcript_preview || 'Unknown error')}</span>`;
    return '<span style="color:var(--text-muted)">Waiting for transcription...</span>';
}

async function toggleCard(id) {
    if (expandedCards.has(id)) {
        expandedCards.delete(id);
    } else {
        expandedCards.add(id);
        if (!transcriptCache[id]) {
            try {
                const res = await fetch(`${API}/api/recordings/${id}`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.transcript) transcriptCache[id] = data.transcript;
                }
            } catch { /* ignore */ }
        }
    }
    loadRecordings();
}

function statusIcon(status) {
    switch (status) {
        case 'completed': return '✅';
        case 'transcribing': return '⏳';
        case 'uploaded': return '📤';
        case 'failed': return '❌';
        default: return '🎵';
    }
}

// Polling
function startPolling() {
    if (pollInterval) return;
    pollInterval = setInterval(loadRecordings, 3000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// Actions
async function copyTranscript(btn) {
    const card = btn.closest('.recording-card');
    const id = card.dataset.id;
    let text = transcriptCache[id];
    if (!text) {
        try {
            const res = await fetch(`${API}/api/recordings/${id}`);
            if (res.ok) {
                const data = await res.json();
                text = data.transcript || '';
                if (text) transcriptCache[id] = text;
            }
        } catch { text = card.querySelector('.transcript-full').textContent; }
    }
    navigator.clipboard.writeText(text || '').then(() => {
        btn.textContent = '✓ Copied!';
        setTimeout(() => btn.textContent = '📋 Copy', 1500);
    });
}

async function retranscribe(id, btn) {
    btn.textContent = '⏳ Queued...';
    btn.disabled = true;
    try {
        await fetch(`${API}/api/recordings/${id}/retranscribe`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelSelect.value, diarize: diarizeToggle.checked})
        });
        loadRecordings();
        startPolling();
    } catch {
        alert('Failed to re-transcribe');
    } finally {
        btn.textContent = '✨ Re-transcribe';
        btn.disabled = false;
    }
}

async function deleteRecording(id) {
    if (!confirm('Delete this recording?')) return;
    try {
        await fetch(`${API}/api/recordings/${id}`, { method: 'DELETE' });
        expandedCards.delete(id);
        loadRecordings();
    } catch {
        alert('Failed to delete');
    }
}

function startRename(id) {
    const card = document.querySelector(`.recording-card[data-id="${id}"]`);
    const nameEl = card.querySelector('.card-name-text');
    if (!nameEl) return;
    const currentName = nameEl.textContent;

    isRenaming = true;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'card-name-input';
    input.value = currentName;
    nameEl.replaceWith(input);
    input.focus();
    input.select();

    let saved = false;
    const save = async () => {
        if (saved) return;
        saved = true;
        isRenaming = false;
        const newName = input.value.trim();
        if (newName && newName !== currentName) {
            try {
                await fetch(`${API}/api/recordings/${id}/rename`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({name: newName})
                });
            } catch { /* ignore */ }
        }
        loadRecordings();
    };

    input.addEventListener('blur', save);
    input.addEventListener('click', (e) => e.stopPropagation());
    input.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.value = currentName; input.blur(); }
    });
}

function setupPlayers() {
    document.querySelectorAll('.custom-player').forEach(player => {
        const audio = player.querySelector('audio');
        const playBtn = player.querySelector('.player-btn');
        const playIcon = player.querySelector('.play-icon');
        const pauseIcon = player.querySelector('.pause-icon');
        const currentTimeEl = player.querySelector('.player-current');
        const durationEl = player.querySelector('.player-duration');
        const range = player.querySelector('.player-range');
        const fill = player.querySelector('.player-fill');

        audio.addEventListener('loadedmetadata', () => {
            durationEl.textContent = formatDuration(audio.duration);
            range.max = audio.duration;
        });

        audio.addEventListener('timeupdate', () => {
            currentTimeEl.textContent = formatDuration(audio.currentTime);
            if (audio.duration) {
                fill.style.width = (audio.currentTime / audio.duration * 100) + '%';
                range.value = audio.currentTime;
            }
        });

        audio.addEventListener('ended', () => {
            playIcon.classList.remove('hidden');
            pauseIcon.classList.add('hidden');
            audioPlaying = false;
        });

        playBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            // Pause all other players
            document.querySelectorAll('.custom-player audio').forEach(a => {
                if (a !== audio && !a.paused) a.pause();
            });
            document.querySelectorAll('.custom-player').forEach(p => {
                if (p !== player) {
                    p.querySelector('.play-icon').classList.remove('hidden');
                    p.querySelector('.pause-icon').classList.add('hidden');
                }
            });

            if (audio.paused) {
                audio.play();
                playIcon.classList.add('hidden');
                pauseIcon.classList.remove('hidden');
                audioPlaying = true;
            } else {
                audio.pause();
                playIcon.classList.remove('hidden');
                pauseIcon.classList.add('hidden');
                audioPlaying = false;
            }
        });

        range.addEventListener('input', (e) => {
            e.stopPropagation();
            audio.currentTime = range.value;
            fill.style.width = (range.value / (audio.duration || 1) * 100) + '%';
        });

        range.addEventListener('click', (e) => e.stopPropagation());
    });
}

retranscribeAllBtn.addEventListener('click', async () => {
    if (!confirm('Re-transcribe all recordings with the selected model?')) return;
    retranscribeAllBtn.textContent = '⏳';
    retranscribeAllBtn.disabled = true;
    try {
        const res = await fetch(`${API}/api/retranscribe-all`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({model: modelSelect.value, diarize: diarizeToggle.checked})
        });
        const data = await res.json();
        loadRecordings();
        startPolling();
        alert(`Queued ${data.queued} recording(s) for re-transcription.`);
    } catch {
        alert('Failed to queue re-transcription');
    } finally {
        retranscribeAllBtn.textContent = '✨';
        retranscribeAllBtn.disabled = false;
    }
});

refreshBtn.addEventListener('click', loadRecordings);

// Select mode
const selectBtn = document.getElementById('select-btn');
selectBtn.addEventListener('click', () => {
    selectMode = !selectMode;
    if (!selectMode) selectedCards.clear();
    selectBtn.textContent = selectMode ? 'Cancel' : '☑️';
    selectBtn.classList.toggle('select-active', selectMode);
    loadRecordings();
});

function updateBatchBar() {
    const bar = document.getElementById('batch-bar');
    const count = document.getElementById('batch-count');
    if (selectMode && selectedCards.size > 0) {
        bar.classList.remove('hidden');
        count.textContent = selectedCards.size;
    } else {
        bar.classList.add('hidden');
    }
}

document.getElementById('batch-retranscribe').addEventListener('click', async () => {
    const ids = Array.from(selectedCards);
    const selectedModel = modelSelect.options[modelSelect.selectedIndex];
    const modelLabel = selectedModel ? selectedModel.textContent.split(' —')[0] : modelSelect.value;
    if (!confirm(`Re-transcribe ${ids.length} recording(s) with ${modelLabel}?`)) return;
    try {
        await fetch(`${API}/api/recordings/batch/retranscribe`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ids, model: modelSelect.value, diarize: diarizeToggle.checked})
        });
        selectedCards.clear();
        selectMode = false;
        selectBtn.textContent = '☑️';
        selectBtn.classList.remove('select-active');
        loadRecordings();
        startPolling();
    } catch {
        alert('Failed to re-transcribe');
    }
});

document.getElementById('batch-delete').addEventListener('click', async () => {
    const ids = Array.from(selectedCards);
    if (!confirm(`Delete ${ids.length} recording(s)? This cannot be undone.`)) return;
    try {
        await fetch(`${API}/api/recordings/batch/delete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ids})
        });
        ids.forEach(id => expandedCards.delete(id));
        selectedCards.clear();
        selectMode = false;
        selectBtn.textContent = '☑️';
        selectBtn.classList.remove('select-active');
        loadRecordings();
    } catch {
        alert('Failed to delete');
    }
});

// Helpers
function formatSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) { size /= 1024; i++; }
    return size.toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr + 'Z');
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatDuration(secs) {
    if (!secs) return '';
    const m = Math.floor(secs / 60);
    const s = Math.round(secs % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Pull to refresh
(function() {
    const wrapper = document.getElementById('scroll-wrapper');
    const indicator = document.getElementById('ptr-indicator');
    const ptrText = indicator.querySelector('.ptr-text');
    let startY = 0;
    let pulling = false;
    let refreshing = false;

    wrapper.addEventListener('touchstart', (e) => {
        if (refreshing) return;
        if (wrapper.scrollTop <= 0) {
            startY = e.touches[0].clientY;
        }
    }, { passive: true });

    wrapper.addEventListener('touchmove', (e) => {
        if (refreshing || startY === 0) return;
        const dy = e.touches[0].clientY - startY;
        if (dy > 10 && wrapper.scrollTop <= 0) {
            pulling = true;
            indicator.classList.add('visible');
            ptrText.textContent = dy > 80 ? 'Release to refresh' : 'Pull to refresh';
        }
    }, { passive: true });

    wrapper.addEventListener('touchend', async () => {
        if (!pulling) { startY = 0; return; }
        if (ptrText.textContent === 'Release to refresh') {
            refreshing = true;
            ptrText.textContent = 'Refreshing...';
            indicator.classList.add('refreshing');
            await loadRecordings();
            indicator.classList.remove('refreshing');
            refreshing = false;
        }
        indicator.classList.remove('visible');
        pulling = false;
        startY = 0;
    });
})();

// Initial load
loadRecordings();
