const API_BASE = '/api';

// State
let jobs = [];
let pollingInterval = null;
let currentSummaryJobId = null;

// DOM Elements
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const urlInput = document.getElementById('urlInput');
const submitUrlBtn = document.getElementById('submitUrl');
const jobsList = document.getElementById('jobsList');
const summarySection = document.getElementById('summarySection');
const toastContainer = document.getElementById('toastContainer');
const logsModal = document.getElementById('logsModal');
const logsContent = document.getElementById('logsContent');
const logsModalTitle = document.getElementById('logsModalTitle');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupEventListeners();
    loadJobs();
    startPolling();
});

function setupEventListeners() {
    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', handleDragOver);
    dropZone.addEventListener('dragleave', handleDragLeave);
    dropZone.addEventListener('drop', handleDrop);
    fileInput.addEventListener('change', handleFileSelect);

    submitUrlBtn.addEventListener('click', handleUrlSubmit);
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleUrlSubmit();
    });

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.dropdown')) {
            document.querySelectorAll('.dropdown-menu').forEach(m => m.style.display = 'none');
        }
    });
}

// Drag and Drop
function handleDragOver(e) { e.preventDefault(); dropZone.classList.add('drag-over'); }
function handleDragLeave(e) { e.preventDefault(); dropZone.classList.remove('drag-over'); }

function handleDrop(e) {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) uploadFile(e.dataTransfer.files[0]);
}

function handleFileSelect(e) {
    if (e.target.files.length > 0) uploadFile(e.target.files[0]);
    fileInput.value = '';
}

// File Upload
async function uploadFile(file) {
    const validTypes = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm', 'video/x-matroska'];
    if (!validTypes.some(type => file.type.includes(type.split('/')[1]))) {
        showToast('Please upload a valid video file (MP4, MOV, AVI, WebM, MKV)', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        showToast('Uploading video...', 'info');
        const response = await fetch(`${API_BASE}/videos/upload`, { method: 'POST', body: formData });
        if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Upload failed'); }
        const job = await response.json();
        showToast('Video uploaded successfully! Processing started.', 'success');
        addJobToList(job);
    } catch (error) {
        showToast(`Upload failed: ${error.message}`, 'error');
    }
}

// URL Submission
async function handleUrlSubmit() {
    const url = urlInput.value.trim();
    if (!url) { showToast('Please enter a URL', 'error'); return; }
    if (!url.startsWith('http://') && !url.startsWith('https://')) { showToast('Please enter a valid URL', 'error'); return; }

    try {
        submitUrlBtn.disabled = true;
        showToast('Submitting URL...', 'info');
        const response = await fetch(`${API_BASE}/videos/url`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url })
        });
        if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Submission failed'); }
        const job = await response.json();
        showToast('URL submitted successfully! Download and processing started.', 'success');
        urlInput.value = '';
        addJobToList(job);
    } catch (error) {
        showToast(`Submission failed: ${error.message}`, 'error');
    } finally {
        submitUrlBtn.disabled = false;
    }
}

// Jobs Management
async function loadJobs() {
    try {
        const response = await fetch(`${API_BASE}/jobs?limit=20`);
        if (!response.ok) throw new Error('Failed to load jobs');
        const data = await response.json();
        jobs = data.jobs;
        renderJobs();
    } catch (error) { console.error('Failed to load jobs:', error); }
}

function addJobToList(job) {
    const existingIndex = jobs.findIndex(j => j.id === job.id);
    if (existingIndex >= 0) jobs[existingIndex] = job;
    else jobs.unshift(job);
    renderJobs();
}

function renderJobs() {
    if (jobs.length === 0) {
        jobsList.innerHTML = '<p class="empty-state">No jobs yet. Upload a video or enter a URL to get started.</p>';
        return;
    }

    jobsList.innerHTML = jobs.map(job => {
        const name = escapeHtml(job.original_filename || 'Unknown');
        const safeName = escapeHtml(job.original_filename || 'Job').replace(/'/g, '&#39;');
        const isComplete = job.status === 'complete';
        const isFailed = job.status === 'failed';
        const isTerminal = ['complete', 'failed', 'cancelled'].includes(job.status);

        let actionsHtml = '';
        if (isComplete) {
            actionsHtml = `
                <button class="btn btn-small btn-primary" onclick="viewSummary('${job.id}')">View Summary</button>
                <button class="btn btn-small btn-secondary" onclick="viewLogs('${job.id}', '${safeName}')">View Logs</button>
                <div class="dropdown">
                    <button class="btn btn-small btn-secondary" onclick="toggleDropdown(event)">Download &#9662;</button>
                    <div class="dropdown-menu">
                        <button class="dropdown-item" onclick="downloadSummaryPDF('${job.id}')">Summary PDF</button>
                        <button class="dropdown-item" onclick="downloadLogs('${job.id}', '${safeName}')">Logs</button>
                        <button class="dropdown-item" onclick="downloadAll('${job.id}', '${safeName}')">All</button>
                    </div>
                </div>
                <button class="btn btn-small btn-danger" onclick="deleteJob('${job.id}')">Delete</button>`;
        } else if (isFailed) {
            actionsHtml = `
                <button class="btn btn-small btn-primary" onclick="retryJob('${job.id}')">Retry</button>
                <button class="btn btn-small btn-secondary" onclick="viewLogs('${job.id}', '${safeName}')">View Logs</button>
                <button class="btn btn-small btn-danger" onclick="deleteJob('${job.id}')">Delete</button>`;
        } else if (isTerminal) {
            actionsHtml = `<button class="btn btn-small btn-danger" onclick="deleteJob('${job.id}')">Delete</button>`;
        } else {
            actionsHtml = `<button class="btn btn-small btn-danger" onclick="deleteJob('${job.id}')">Delete</button>`;
        }

        return `
            <div class="job-item" data-job-id="${job.id}">
                <div class="job-info">
                    <div class="job-filename">${name}</div>
                    <div class="job-status ${getStatusClass(job.status)}">
                        ${formatStatus(job.status)}${job.current_step ? ': ' + job.current_step : ''}
                    </div>
                </div>
                <div class="job-progress">
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${job.progress}%"></div>
                    </div>
                    <div class="progress-text">${job.progress}%</div>
                </div>
                <div class="job-actions">${actionsHtml}</div>
            </div>`;
    }).join('');
}

function toggleDropdown(event) {
    event.stopPropagation();
    const menu = event.target.closest('.dropdown').querySelector('.dropdown-menu');
    const isVisible = menu.style.display === 'block';
    document.querySelectorAll('.dropdown-menu').forEach(m => m.style.display = 'none');
    menu.style.display = isVisible ? 'none' : 'block';
}

function getStatusClass(status) {
    const statusMap = {
        'pending': 'status-pending', 'downloading': 'status-processing',
        'processing_video': 'status-processing', 'transcribing': 'status-processing',
        'analyzing': 'status-processing', 'vision_analysis': 'status-processing',
        'valuation': 'status-processing', 'complete': 'status-complete',
        'failed': 'status-failed', 'cancelled': 'status-failed'
    };
    return statusMap[status] || '';
}

function formatStatus(status) {
    const statusMap = {
        'pending': 'Pending', 'downloading': 'Downloading',
        'processing_video': 'Processing Video', 'transcribing': 'Transcribing',
        'analyzing': 'Analyzing', 'vision_analysis': 'Inspecting Condition',
        'valuation': 'Market Valuation', 'complete': 'Complete',
        'failed': 'Failed', 'cancelled': 'Cancelled'
    };
    return statusMap[status] || status;
}

// Polling
function startPolling() {
    pollingInterval = setInterval(async () => {
        const activeJobs = jobs.filter(j => !['complete', 'failed', 'cancelled'].includes(j.status));
        for (const job of activeJobs) {
            try {
                const response = await fetch(`${API_BASE}/jobs/${job.id}`);
                if (response.ok) {
                    const updatedJob = await response.json();
                    addJobToList(updatedJob);
                    if (updatedJob.status === 'complete') showToast(`Analysis complete: ${updatedJob.original_filename}`, 'success');
                    else if (updatedJob.status === 'failed') showToast(`Processing failed: ${updatedJob.error || 'Unknown error'}`, 'error');
                }
            } catch (error) { console.error(`Failed to update job ${job.id}:`, error); }
        }
    }, 3000);
}

// View Summary
async function viewSummary(jobId) {
    try {
        const response = await fetch(`${API_BASE}/jobs/${jobId}`);
        if (!response.ok) throw new Error('Failed to load summary');
        const job = await response.json();
        currentSummaryJobId = jobId;

        document.getElementById('summaryMake').textContent = job.make || '-';
        document.getElementById('summaryModel').textContent = job.model || '-';
        document.getElementById('summaryYear').textContent = job.year || '-';
        document.getElementById('summaryText').textContent = job.summary || 'No summary available';
        document.getElementById('summaryCost').textContent = `Processing cost: $${(job.cost || 0).toFixed(4)}`;

        renderConditionSection(job);
        renderValuationSection(job);

        summarySection.style.display = 'block';
        summarySection.scrollIntoView({ behavior: 'smooth' });
    } catch (error) {
        showToast(`Failed to load summary: ${error.message}`, 'error');
    }
}

function renderObservationItem(obs, jobId) {
    if (typeof obs === 'string') {
        return `<li>${escapeHtml(obs)}</li>`;
    }
    const text = escapeHtml(obs.text || '');
    const evidenceFrame = obs.evidence_frame;
    if (evidenceFrame && jobId) {
        const imgUrl = `${API_BASE}/jobs/${jobId}/evidence/${evidenceFrame}`;
        return `<li class="obs-with-evidence">
            <img class="evidence-thumb" src="${imgUrl}" alt="Evidence" onclick="openLightbox('${imgUrl}', '${text.replace(/'/g, "\\'")}')">
            <span>${text}</span>
        </li>`;
    }
    return `<li>${text}</li>`;
}

function renderConditionSection(job) {
    const section = document.getElementById('conditionSection');
    if (!job.condition_report) { section.style.display = 'none'; return; }

    section.style.display = 'block';
    let report;
    try { report = JSON.parse(job.condition_report); } catch { section.style.display = 'none'; return; }

    const score = job.condition_score || report.overall_score || 0;
    const badge = document.getElementById('conditionBadge');
    document.getElementById('conditionScoreNum').textContent = score.toFixed(1);

    badge.className = 'condition-score-badge';
    if (score >= 4.5) badge.classList.add('score-excellent');
    else if (score >= 3.5) badge.classList.add('score-good');
    else if (score >= 2.5) badge.classList.add('score-fair');
    else if (score >= 1.5) badge.classList.add('score-below-avg');
    else badge.classList.add('score-poor');

    document.getElementById('conditionAssessment').textContent = report.overall_assessment || '';

    const areasContainer = document.getElementById('conditionAreas');
    const areaLabels = {
        exterior_paint: 'Exterior Paint', body_panels: 'Body Panels',
        chrome_trim: 'Chrome & Trim', wheels_tires: 'Wheels & Tires',
        glass: 'Glass', interior_seats: 'Interior Seats',
        dashboard: 'Dashboard', carpet_headliner: 'Carpet & Headliner',
    };

    let areasHtml = '';
    if (report.area_scores) {
        for (const [key, data] of Object.entries(report.area_scores)) {
            const areaScore = data.score || 0;
            const label = areaLabels[key] || key.replace(/_/g, ' ');
            const scoreText = areaScore > 0 ? `${areaScore}/5` : 'N/A';
            areasHtml += `<div class="area-item" title="${escapeHtml(data.notes || '')}">
                <span class="area-name">${escapeHtml(label)}</span>
                <span class="area-score area-score-${areaScore}">${scoreText}</span>
            </div>`;
        }
    }
    areasContainer.innerHTML = areasHtml;

    const obsGrid = document.getElementById('observationsGrid');
    const goodList = document.getElementById('goodObservations');
    const badList = document.getElementById('badObservations');

    if (report.observations) {
        const goods = report.observations.good || [];
        const bads = report.observations.bad || [];
        if (goods.length > 0 || bads.length > 0) {
            obsGrid.style.display = 'grid';
            goodList.innerHTML = goods.map(o => renderObservationItem(o, job.id)).join('');
            badList.innerHTML = bads.map(o => renderObservationItem(o, job.id)).join('');
        } else {
            obsGrid.style.display = 'none';
        }
    } else {
        obsGrid.style.display = 'none';
    }
}

function formatPrice(value) {
    if (!value || value <= 0) return '-';
    return '$' + Math.round(value).toLocaleString();
}

function renderValuationSection(job) {
    const section = document.getElementById('valuationSection');
    if (!job.market_value_low && !job.bid_range_low) { section.style.display = 'none'; return; }

    section.style.display = 'block';
    const mvLow = job.market_value_low || 0;
    const mvHigh = job.market_value_high || 0;
    const bidLow = job.bid_range_low || 0;
    const bidHigh = job.bid_range_high || 0;

    document.getElementById('marketRange').textContent = mvLow > 0 ? `${formatPrice(mvLow)} - ${formatPrice(mvHigh)}` : '-';
    document.getElementById('bidRange').textContent = bidLow > 0 ? `${formatPrice(bidLow)} - ${formatPrice(bidHigh)}` : '-';

    const barContainer = document.getElementById('bidBarContainer');
    if (mvHigh > 0 && bidHigh > 0) {
        barContainer.style.display = 'block';
        const maxVal = mvHigh * 1.1;
        document.getElementById('bidBarMarket').style.left = `${(mvLow / maxVal) * 100}%`;
        document.getElementById('bidBarMarket').style.width = `${((mvHigh - mvLow) / maxVal) * 100}%`;
        document.getElementById('bidBarBid').style.left = `${(bidLow / maxVal) * 100}%`;
        document.getElementById('bidBarBid').style.width = `${((bidHigh - bidLow) / maxVal) * 100}%`;
        document.getElementById('bidBarLow').textContent = formatPrice(Math.min(mvLow, bidLow));
        document.getElementById('bidBarHigh').textContent = formatPrice(mvHigh);
    } else {
        barContainer.style.display = 'none';
    }

    document.getElementById('valuationNotes').textContent = job.valuation_notes || '';
}

// Lightbox
function openLightbox(imgUrl, caption) {
    document.getElementById('lightboxImage').src = imgUrl;
    document.getElementById('lightboxCaption').textContent = caption;
    document.getElementById('lightboxModal').style.display = 'flex';
}

function closeLightbox() {
    document.getElementById('lightboxModal').style.display = 'none';
    document.getElementById('lightboxImage').src = '';
}

// Retry Job
async function retryJob(jobId) {
    try {
        const response = await fetch(`${API_BASE}/jobs/${jobId}/retry`, { method: 'POST' });
        if (!response.ok) { const error = await response.json(); throw new Error(error.detail || 'Retry failed'); }
        const job = await response.json();
        showToast('Job resubmitted for processing.', 'success');
        addJobToList(job);
    } catch (error) {
        showToast(`Retry failed: ${error.message}`, 'error');
    }
}

// Download Functions
async function downloadSummaryPDF(jobId) {
    try {
        showToast('Generating PDF...', 'info');
        const response = await fetch(`${API_BASE}/jobs/${jobId}`);
        if (!response.ok) throw new Error('Failed to load job data');
        const job = await response.json();

        const container = document.getElementById('pdfContainer');
        container.innerHTML = buildPdfHtml(job);

        await new Promise(resolve => {
            const images = container.querySelectorAll('img');
            if (images.length === 0) { resolve(); return; }
            let loaded = 0;
            images.forEach(img => {
                if (img.complete) { loaded++; if (loaded === images.length) resolve(); }
                else {
                    img.onload = img.onerror = () => { loaded++; if (loaded === images.length) resolve(); };
                }
            });
        });

        const filename = `${(job.original_filename || 'report').replace(/[^a-zA-Z0-9]/g, '_')}_summary.pdf`;
        await html2pdf().set({
            margin: [10, 10, 10, 10],
            filename: filename,
            image: { type: 'jpeg', quality: 0.95 },
            html2canvas: { scale: 2, useCORS: true },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' },
            pagebreak: { mode: ['avoid-all', 'css', 'legacy'] },
        }).from(container).save();

        container.innerHTML = '';
        showToast('PDF downloaded!', 'success');
    } catch (error) {
        showToast(`PDF generation failed: ${error.message}`, 'error');
    }
}

function buildPdfHtml(job) {
    let html = `<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1e293b; max-width: 700px; padding: 20px;">`;
    html += `<h1 style="font-size: 22px; margin-bottom: 4px;">Vehicle Analysis Report</h1>`;
    html += `<p style="color: #64748b; margin-bottom: 20px;">${escapeHtml(job.original_filename || '')}</p>`;

    html += `<div style="display: flex; gap: 40px; margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid #e2e8f0;">`;
    html += `<div><span style="font-size: 11px; color: #64748b; text-transform: uppercase;">Make</span><br><strong>${escapeHtml(job.make || '-')}</strong></div>`;
    html += `<div><span style="font-size: 11px; color: #64748b; text-transform: uppercase;">Model</span><br><strong>${escapeHtml(job.model || '-')}</strong></div>`;
    html += `<div><span style="font-size: 11px; color: #64748b; text-transform: uppercase;">Year</span><br><strong>${escapeHtml(job.year || '-')}</strong></div>`;
    html += `</div>`;

    if (job.summary) {
        html += `<h2 style="font-size: 16px;">Summary</h2>`;
        html += `<p style="white-space: pre-wrap; line-height: 1.6;">${escapeHtml(job.summary)}</p>`;
    }

    if (job.condition_report) {
        let report;
        try { report = JSON.parse(job.condition_report); } catch { report = null; }
        if (report) {
            const score = job.condition_score || report.overall_score || 0;
            html += `<h2 style="font-size: 16px; margin-top: 24px;">Condition Assessment — Score: ${score.toFixed(1)} / 5</h2>`;
            html += `<p style="color: #64748b;">${escapeHtml(report.overall_assessment || '')}</p>`;

            if (report.observations) {
                const goods = report.observations.good || [];
                const bads = report.observations.bad || [];

                if (goods.length > 0) {
                    html += `<h3 style="font-size: 14px; color: #16a34a; margin-top: 16px;">Positive Observations</h3><ul>`;
                    for (const obs of goods) {
                        const text = typeof obs === 'string' ? obs : (obs.text || '');
                        const frame = typeof obs === 'object' ? obs.evidence_frame : null;
                        html += `<li style="margin-bottom: 8px;">`;
                        if (frame) {
                            html += `<img src="${API_BASE}/jobs/${job.id}/evidence/${frame}" style="width: 120px; height: 80px; object-fit: cover; border-radius: 4px; margin-right: 8px; vertical-align: middle;">`;
                        }
                        html += `${escapeHtml(text)}</li>`;
                    }
                    html += `</ul>`;
                }
                if (bads.length > 0) {
                    html += `<h3 style="font-size: 14px; color: #dc2626; margin-top: 16px;">Issues Found</h3><ul>`;
                    for (const obs of bads) {
                        const text = typeof obs === 'string' ? obs : (obs.text || '');
                        const frame = typeof obs === 'object' ? obs.evidence_frame : null;
                        html += `<li style="margin-bottom: 8px;">`;
                        if (frame) {
                            html += `<img src="${API_BASE}/jobs/${job.id}/evidence/${frame}" style="width: 120px; height: 80px; object-fit: cover; border-radius: 4px; margin-right: 8px; vertical-align: middle;">`;
                        }
                        html += `${escapeHtml(text)}</li>`;
                    }
                    html += `</ul>`;
                }
            }
        }
    }

    if (job.market_value_low || job.bid_range_low) {
        html += `<h2 style="font-size: 16px; margin-top: 24px;">Market Valuation</h2>`;
        if (job.market_value_low) {
            html += `<p><strong>Market Value Range:</strong> ${formatPrice(job.market_value_low)} - ${formatPrice(job.market_value_high)}</p>`;
        }
        if (job.bid_range_low) {
            html += `<p><strong>Suggested Starting Bid:</strong> ${formatPrice(job.bid_range_low)} - ${formatPrice(job.bid_range_high)}</p>`;
        }
    }

    html += `<p style="margin-top: 24px; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; padding-top: 12px;">Processing cost: $${(job.cost || 0).toFixed(4)} | Generated ${new Date().toLocaleString()}</p>`;
    html += `</div>`;
    return html;
}

async function downloadLogs(jobId, jobName) {
    try {
        const response = await fetch(`${API_BASE}/jobs/${jobId}/logs`);
        if (!response.ok) throw new Error('Failed to load logs');
        const data = await response.json();
        const text = JSON.stringify(data.logs, null, 2);
        const blob = new Blob([text], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${(jobName || 'job').replace(/[^a-zA-Z0-9]/g, '_')}_logs.json`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
        showToast('Logs downloaded!', 'success');
    } catch (error) {
        showToast(`Download failed: ${error.message}`, 'error');
    }
}

async function downloadAll(jobId, jobName) {
    await downloadSummaryPDF(jobId);
    await downloadLogs(jobId, jobName);
}

// Delete Job
async function deleteJob(jobId) {
    if (!confirm('Are you sure you want to delete this job?')) return;
    try {
        const response = await fetch(`${API_BASE}/jobs/${jobId}`, { method: 'DELETE' });
        if (!response.ok) throw new Error('Failed to delete job');
        jobs = jobs.filter(j => j.id !== jobId);
        renderJobs();
        showToast('Job deleted', 'success');
    } catch (error) {
        showToast(`Failed to delete job: ${error.message}`, 'error');
    }
}

// Toast Notifications
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 4000);
}

// Logs Modal
async function viewLogs(jobId, jobName) {
    try {
        const response = await fetch(`${API_BASE}/jobs/${jobId}/logs`);
        if (!response.ok) throw new Error('Failed to load logs');
        const data = await response.json();
        logsModalTitle.textContent = `Logs: ${jobName}`;
        renderLogs(data.logs);
        logsModal.style.display = 'flex';
    } catch (error) {
        showToast(`Failed to load logs: ${error.message}`, 'error');
    }
}

function closeLogsModal() { logsModal.style.display = 'none'; }

function renderLogs(logs) {
    if (!logs || logs.length === 0) { logsContent.innerHTML = '<p class="empty-state">No logs available yet</p>'; return; }

    const summary = calculateLogSummary(logs);
    let html = `
        <div class="log-summary">
            <div class="log-summary-title">Summary</div>
            <div class="log-summary-stats">
                <div class="log-stat"><span class="log-stat-label">Total Time: </span><span class="log-stat-value">${formatDuration(summary.totalTime)}</span></div>
                <div class="log-stat"><span class="log-stat-label">Phases: </span><span class="log-stat-value">${summary.completedPhases}/${summary.totalPhases}</span></div>
                <div class="log-stat"><span class="log-stat-label">Status: </span><span class="log-stat-value" style="color: ${summary.status === 'success' ? 'var(--success-color)' : summary.status === 'failed' ? 'var(--error-color)' : 'var(--primary-color)'};">${summary.status === 'success' ? 'Completed' : summary.status === 'failed' ? 'Failed' : 'In Progress'}</span></div>
            </div>
        </div>`;

    html += logs.map((log, index) => `
        <div class="log-entry log-${log.status}">
            <div class="log-header">
                <span class="log-phase">${formatPhase(log.phase)}</span>
                ${log.duration_ms ? `<span class="log-duration">${formatDuration(log.duration_ms)}</span>` : ''}
            </div>
            <div class="log-timestamp">${formatTimestamp(log.timestamp)}</div>
            <div class="log-message">${escapeHtml(log.message)}</div>
            ${log.details ? renderLogDetails(log.details, index) : ''}
        </div>`).join('');

    logsContent.innerHTML = html;
}

function calculateLogSummary(logs) {
    const phases = new Set();
    const completedPhases = new Set();
    let totalTime = 0;
    let status = 'in_progress';

    logs.forEach(log => {
        if (log.phase && !['init', 'error', 'complete'].includes(log.phase)) {
            phases.add(log.phase);
            if (log.status === 'completed') completedPhases.add(log.phase);
        }
        if (log.phase === 'complete' && log.status === 'success') { status = 'success'; if (log.duration_ms) totalTime = log.duration_ms; }
        if (log.status === 'failed' || log.phase === 'error') { status = 'failed'; if (log.duration_ms && log.duration_ms > totalTime) totalTime = log.duration_ms; }
    });

    if (totalTime === 0) logs.forEach(log => { if (log.duration_ms && log.status === 'completed') totalTime += log.duration_ms; });

    return { totalPhases: phases.size || 1, completedPhases: completedPhases.size, totalTime, status };
}

function formatPhase(phase) {
    const phaseNames = {
        'init': 'Initialization', 'download': 'Download', 'video_processing': 'Video Processing',
        'ai_analysis': 'AI Analysis', 'vision_analysis': 'Vision Condition Analysis',
        'valuation': 'Market Valuation', 'complete': 'Complete', 'error': 'Error'
    };
    return phaseNames[phase] || phase.replace(/_/g, ' ');
}

function formatDuration(ms) {
    if (!ms) return '-';
    if (ms < 1000) return `${ms}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.floor(ms / 60000)}m ${((ms % 60000) / 1000).toFixed(0)}s`;
}

function formatTimestamp(timestamp) {
    try { return new Date(timestamp).toLocaleString(); } catch { return timestamp; }
}

function renderLogDetails(details, index) {
    if (!details || Object.keys(details).length === 0) return '';
    const hasTraceback = details.traceback;
    const displayDetails = { ...details };
    delete displayDetails.traceback;
    let html = `<div class="log-details">`;
    if (Object.keys(displayDetails).length > 0) html += `<strong>Details:</strong><pre>${escapeHtml(JSON.stringify(displayDetails, null, 2))}</pre>`;
    if (hasTraceback) {
        html += `<button class="log-details-toggle" onclick="toggleTraceback(${index})">Show Traceback</button>`;
        html += `<pre id="traceback-${index}" style="display: none; color: var(--error-color);">${escapeHtml(details.traceback)}</pre>`;
    }
    html += `</div>`;
    return html;
}

function toggleTraceback(index) {
    const traceback = document.getElementById(`traceback-${index}`);
    const button = traceback.previousElementSibling;
    if (traceback.style.display === 'none') { traceback.style.display = 'block'; button.textContent = 'Hide Traceback'; }
    else { traceback.style.display = 'none'; button.textContent = 'Show Traceback'; }
}

// Close modals on escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        if (document.getElementById('lightboxModal').style.display === 'flex') closeLightbox();
        else if (logsModal.style.display === 'flex') closeLogsModal();
    }
});

// Utility
function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
