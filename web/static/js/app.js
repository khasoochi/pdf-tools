/**
 * Smart PDF Compressor - Frontend Application
 */

// State
let currentFile = null;
let analysisData = null;
let jobId = null;
let pollInterval = null;

// DOM Elements
const dropZone = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const browseBtn = document.getElementById('browse-btn');
const uploadSection = document.getElementById('upload-section');
const analysisSection = document.getElementById('analysis-section');
const optionsSection = document.getElementById('options-section');
const progressSection = document.getElementById('progress-section');
const resultsSection = document.getElementById('results-section');
const errorSection = document.getElementById('error-section');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    setupDropZone();
    setupEventListeners();
});

function setupDropZone() {
    // Click to browse
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    dropZone.addEventListener('click', () => {
        fileInput.click();
    });

    // File input change
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleFile(e.target.files[0]);
        }
    });

    // Drag and drop
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0 && files[0].type === 'application/pdf') {
            handleFile(files[0]);
        } else {
            showError('Please drop a PDF file.');
        }
    });
}

function setupEventListeners() {
    // Compress button
    document.getElementById('compress-btn').addEventListener('click', startCompression);

    // Start over button
    document.getElementById('start-over-btn').addEventListener('click', resetUI);

    // Error retry button
    document.getElementById('error-retry-btn').addEventListener('click', resetUI);

    // Target size input validation
    document.getElementById('target-size-value').addEventListener('input', updateSizeHint);
    document.getElementById('target-size-unit').addEventListener('change', updateSizeHint);
}

async function handleFile(file) {
    if (file.type !== 'application/pdf') {
        showError('Only PDF files are allowed.');
        return;
    }

    currentFile = file;

    // Show upload progress
    const uploadProgress = document.getElementById('upload-progress');
    const uploadFill = document.getElementById('upload-fill');
    uploadProgress.hidden = false;
    uploadFill.style.width = '0%';

    // Create form data
    const formData = new FormData();
    formData.append('file', file);

    try {
        // Simulate progress during upload
        let progress = 0;
        const progressInterval = setInterval(() => {
            progress = Math.min(progress + 10, 90);
            uploadFill.style.width = progress + '%';
        }, 100);

        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData,
        });

        clearInterval(progressInterval);
        uploadFill.style.width = '100%';

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Upload failed');
        }

        const data = await response.json();
        analysisData = data;

        // Show analysis
        setTimeout(() => {
            uploadProgress.hidden = true;
            showAnalysis(data);
        }, 300);

    } catch (error) {
        uploadProgress.hidden = true;
        showError(error.message);
    }
}

function showAnalysis(data) {
    const analysis = data.analysis;

    // Update analysis display
    document.getElementById('current-size').textContent = analysis.current_size_formatted;
    document.getElementById('page-count').textContent = analysis.pages;
    document.getElementById('image-percentage').textContent = analysis.image_percentage + '%';
    document.getElementById('text-detected').textContent = analysis.text_detected ? 'Yes' : 'No';
    document.getElementById('pdf-type').textContent = formatPdfType(analysis.pdf_type);
    document.getElementById('estimated-size').textContent =
        `${analysis.estimated_min_size_formatted} - ${analysis.estimated_max_size_formatted}`;

    // Show/hide text options
    const textOptions = document.getElementById('text-options');
    textOptions.hidden = !analysis.text_detected;

    // Set default target size (midpoint of estimated range)
    const avgEstimate = (analysis.estimated_min_size + analysis.estimated_max_size) / 2;
    setTargetSizeFromBytes(avgEstimate);

    // Show sections
    analysisSection.hidden = false;
    optionsSection.hidden = false;

    // Update size hint
    updateSizeHint();
}

function formatPdfType(type) {
    const types = {
        'image-heavy': 'Image Heavy',
        'text-heavy': 'Text Heavy',
        'mixed': 'Mixed Content',
    };
    return types[type] || type;
}

function setTargetSizeFromBytes(bytes) {
    const sizeValue = document.getElementById('target-size-value');
    const sizeUnit = document.getElementById('target-size-unit');

    if (bytes >= 1024 * 1024) {
        sizeValue.value = (bytes / (1024 * 1024)).toFixed(1);
        sizeUnit.value = 'MB';
    } else {
        sizeValue.value = Math.round(bytes / 1024);
        sizeUnit.value = 'KB';
    }
}

function getTargetSizeBytes() {
    const value = parseFloat(document.getElementById('target-size-value').value);
    const unit = document.getElementById('target-size-unit').value;

    if (unit === 'MB') {
        return Math.round(value * 1024 * 1024);
    } else {
        return Math.round(value * 1024);
    }
}

function updateSizeHint() {
    const hint = document.getElementById('size-hint');

    if (!analysisData) return;

    const targetBytes = getTargetSizeBytes();
    const minSize = analysisData.analysis.estimated_min_size;
    const currentSize = analysisData.analysis.current_size;

    if (targetBytes < minSize) {
        hint.textContent = `Target may be too small. Estimated minimum: ${analysisData.analysis.estimated_min_size_formatted}`;
        hint.style.color = 'var(--warning-color)';
    } else if (targetBytes >= currentSize) {
        hint.textContent = 'Target is larger than current size. No compression needed.';
        hint.style.color = 'var(--warning-color)';
    } else {
        hint.textContent = '';
    }
}

async function startCompression() {
    const tolerance = document.querySelector('input[name="tolerance"]:checked').value;
    const extractText = document.getElementById('extract-text').checked;
    const removeText = document.getElementById('remove-text').checked;

    const targetSizeStr = document.getElementById('target-size-value').value +
                         document.getElementById('target-size-unit').value;

    // Hide options, show progress
    uploadSection.hidden = true;
    analysisSection.hidden = true;
    optionsSection.hidden = true;
    progressSection.hidden = false;

    try {
        const response = await fetch('/api/compress', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                file_id: analysisData.file_id,
                filename: analysisData.filename,
                target_size: targetSizeStr,
                tolerance: tolerance,
                extract_text: extractText,
                remove_text: removeText,
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Failed to start compression');
        }

        const data = await response.json();
        jobId = data.job_id;

        // Start polling for progress
        startProgressPolling();

    } catch (error) {
        showError(error.message);
    }
}

function startProgressPolling() {
    pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/job/${jobId}`);

            if (!response.ok) {
                throw new Error('Failed to get job status');
            }

            const job = await response.json();
            updateProgress(job);

            if (job.status === 'completed') {
                clearInterval(pollInterval);
                showResults(job);
            } else if (job.status === 'failed') {
                clearInterval(pollInterval);
                showError(job.error || 'Compression failed');
            }

        } catch (error) {
            clearInterval(pollInterval);
            showError(error.message);
        }
    }, 500);
}

function updateProgress(job) {
    const progressFill = document.getElementById('compress-fill');
    const progressText = document.getElementById('progress-text');

    progressFill.style.width = job.progress + '%';
    progressText.textContent = job.stage;

    // Update stage indicators
    const stageMap = {
        'Analyzing PDF': 1,
        'Processing images': 2,
        'Optimizing objects': 3,
        'Text extraction': 4,
        'Finalizing PDF': 5,
        'Complete': 5,
    };

    const currentStage = stageMap[job.stage] || 1;

    document.querySelectorAll('.stage').forEach((el) => {
        const stage = parseInt(el.dataset.stage);
        el.classList.remove('active', 'completed');

        if (stage < currentStage) {
            el.classList.add('completed');
        } else if (stage === currentStage) {
            el.classList.add('active');
        }
    });
}

function showResults(job) {
    progressSection.hidden = true;
    resultsSection.hidden = false;

    const result = job.result;

    document.getElementById('result-original').textContent = result.original_size_formatted;
    document.getElementById('result-compressed').textContent = result.compressed_size_formatted;
    document.getElementById('result-reduction').textContent = result.compression_ratio + '%';
    document.getElementById('result-quality').textContent = result.quality_estimate;
    document.getElementById('result-target').textContent = result.target_achieved ? 'Yes' : 'No';

    // Create download buttons
    const downloadButtons = document.getElementById('download-buttons');
    downloadButtons.innerHTML = '';

    if (job.output_files.compressed_pdf) {
        const btn = document.createElement('a');
        btn.href = `/api/download/${jobId}/compressed_pdf`;
        btn.className = 'btn btn-success';
        btn.textContent = 'Download Compressed PDF';
        downloadButtons.appendChild(btn);
    }

    if (job.output_files.extracted_text) {
        const btn = document.createElement('a');
        btn.href = `/api/download/${jobId}/extracted_text`;
        btn.className = 'btn btn-secondary';
        btn.textContent = 'Download Extracted Text';
        downloadButtons.appendChild(btn);
    }

    if (job.output_files.notext_pdf) {
        const btn = document.createElement('a');
        btn.href = `/api/download/${jobId}/notext_pdf`;
        btn.className = 'btn btn-secondary';
        btn.textContent = 'Download PDF (No Text)';
        downloadButtons.appendChild(btn);
    }

    // Report download
    const reportBtn = document.createElement('a');
    reportBtn.href = `/api/report/${jobId}`;
    reportBtn.className = 'btn btn-secondary';
    reportBtn.textContent = 'Download Report (JSON)';
    reportBtn.setAttribute('download', 'compression_report.json');
    downloadButtons.appendChild(reportBtn);
}

function showError(message) {
    // Hide all sections
    uploadSection.hidden = true;
    analysisSection.hidden = true;
    optionsSection.hidden = true;
    progressSection.hidden = true;
    resultsSection.hidden = true;

    // Show error
    errorSection.hidden = false;
    document.getElementById('error-message').textContent = message;

    // Clear any polling
    if (pollInterval) {
        clearInterval(pollInterval);
    }
}

function resetUI() {
    // Clear state
    currentFile = null;
    analysisData = null;
    jobId = null;

    if (pollInterval) {
        clearInterval(pollInterval);
    }

    // Reset file input
    fileInput.value = '';

    // Reset form
    document.getElementById('target-size-value').value = '5';
    document.getElementById('target-size-unit').value = 'MB';
    document.querySelector('input[name="tolerance"][value="balanced"]').checked = true;
    document.getElementById('extract-text').checked = false;
    document.getElementById('remove-text').checked = false;

    // Reset progress
    document.getElementById('upload-fill').style.width = '0%';
    document.getElementById('compress-fill').style.width = '0%';
    document.querySelectorAll('.stage').forEach((el) => {
        el.classList.remove('active', 'completed');
    });

    // Show only upload section
    uploadSection.hidden = false;
    analysisSection.hidden = true;
    optionsSection.hidden = true;
    progressSection.hidden = true;
    resultsSection.hidden = true;
    errorSection.hidden = true;

    document.getElementById('upload-progress').hidden = true;
}
