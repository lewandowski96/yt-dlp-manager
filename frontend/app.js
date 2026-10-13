/**
 * yt-dlp Manager — Frontend Application Logic
 */

(() => {
    "use strict";

    // ---------- DOM Elements ----------
    const $ = (sel) => document.querySelector(sel);
    const urlInput = $("#url-input");
    const btnFetch = $("#btn-fetch");
    const btnClearUrl = $("#btn-clear-url");
    const btnOpenDownloads = $("#btn-open-downloads");
    const errorBanner = $("#error-banner");
    const errorText = $("#error-text");
    const btnDismissError = $("#btn-dismiss-error");

    const videoSection = $("#video-section");
    const videoThumbnail = $("#video-thumbnail");
    const videoDuration = $("#video-duration");
    const videoTitle = $("#video-title");
    const videoChannel = $("#video-channel");
    const presetsGrid = $("#presets-grid");

    const btnToggleFormats = $("#btn-toggle-formats");
    const formatsContent = $("#formats-content");
    const formatsTbody = $("#formats-tbody");

    const downloadSection = $("#download-section");
    const downloadStatusIcon = $("#download-status-icon");
    const downloadStatusText = $("#download-status-text");
    const downloadFilename = $("#download-filename");
    const progressBarFill = $("#progress-bar-fill");
    const progressPercent = $("#progress-percent");
    const progressSpeed = $("#progress-speed");
    const progressEta = $("#progress-eta");
    const btnCancelDownload = $("#btn-cancel-download");

    const completeSection = $("#complete-section");
    const completeFilename = $("#complete-filename");
    const btnOpenFolder = $("#btn-open-folder");
    const btnDownloadAnother = $("#btn-download-another");

    // ---------- State ----------
    let currentVideoInfo = null;
    let activeWebSocket = null;
    let currentDownloadDir = "";
    let browsingPath = "";

    // ---------- Destination Bar ----------
    const destPath = $("#dest-path");
    const btnChangeDest = $("#btn-change-dest");

    // ---------- Directory Modal ----------
    const dirModal = $("#dir-modal");
    const dirPathInput = $("#dir-path-input");
    const btnGoPath = $("#btn-go-path");
    const dirCurrentPath = $("#dir-current-path");
    const dirListing = $("#dir-listing");
    const btnCloseModal = $("#btn-close-modal");
    const btnDirCancel = $("#btn-dir-cancel");
    const btnDirSelect = $("#btn-dir-select");

    // ---------- Helpers ----------

    function formatDuration(seconds) {
        if (!seconds) return "";
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
        return `${m}:${String(s).padStart(2, "0")}`;
    }

    function formatFilesize(bytes) {
        if (!bytes || bytes <= 0) return "—";
        const units = ["B", "KB", "MB", "GB"];
        let i = 0;
        let size = bytes;
        while (size >= 1024 && i < units.length - 1) {
            size /= 1024;
            i++;
        }
        return `${size.toFixed(1)} ${units[i]}`;
    }

    function showError(message) {
        errorText.textContent = message;
        errorBanner.style.display = "flex";
        errorBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    function hideError() {
        errorBanner.style.display = "none";
    }

    function setFetchLoading(loading) {
        const text = btnFetch.querySelector(".btn-text");
        const loader = btnFetch.querySelector(".btn-loader");
        if (loading) {
            text.style.display = "none";
            loader.style.display = "flex";
            btnFetch.disabled = true;
            urlInput.disabled = true;
        } else {
            text.style.display = "inline";
            loader.style.display = "none";
            btnFetch.disabled = false;
            urlInput.disabled = false;
        }
    }

    function resetToInitial() {
        videoSection.style.display = "none";
        downloadSection.style.display = "none";
        completeSection.style.display = "none";
        hideError();
        currentVideoInfo = null;
    }

    // ---------- Download Directory ----------

    async function loadDownloadDir() {
        try {
            const resp = await fetch("/api/downloads-dir");
            const data = await resp.json();
            currentDownloadDir = data.path;
            destPath.textContent = data.path;
            destPath.title = data.path;
        } catch {
            destPath.textContent = "Unknown";
        }
    }

    async function setDownloadDir(path) {
        try {
            const resp = await fetch("/api/downloads-dir", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path }),
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error);
            currentDownloadDir = data.path;
            destPath.textContent = data.path;
            destPath.title = data.path;
            return true;
        } catch (err) {
            showError(err.message || "Failed to set download directory.");
            return false;
        }
    }

    // ---------- Directory Browser Modal ----------

    function openDirModal() {
        dirModal.style.display = "flex";
        browsingPath = currentDownloadDir;
        dirPathInput.value = browsingPath;
        browseTo(browsingPath);
        document.body.style.overflow = "hidden";
    }

    function closeDirModal() {
        dirModal.style.display = "none";
        document.body.style.overflow = "";
    }

    async function browseTo(path) {
        dirListing.innerHTML = '<div class="dir-loading"><div class="spinner"></div><span>Loading...</span></div>';

        try {
            const resp = await fetch(`/api/browse?path=${encodeURIComponent(path || "")}`);
            const data = await resp.json();

            if (!resp.ok) throw new Error(data.error);

            browsingPath = data.current;
            dirPathInput.value = browsingPath;

            // Render breadcrumb
            renderBreadcrumb(data.current);

            // Render listing
            renderDirListing(data);
        } catch (err) {
            dirListing.innerHTML = `<div class="dir-empty">Error: ${err.message}</div>`;
        }
    }

    function renderBreadcrumb(pathStr) {
        dirCurrentPath.innerHTML = "";

        // Detect path separator
        const sep = pathStr.includes("\\") ? "\\" : "/";
        const parts = pathStr.split(sep).filter(Boolean);

        // If Unix-like, we need the leading /
        const isUnix = sep === "/";

        parts.forEach((part, i) => {
            if (i > 0 || isUnix) {
                const sepSpan = document.createElement("span");
                sepSpan.className = "path-sep";
                sepSpan.textContent = sep;
                dirCurrentPath.appendChild(sepSpan);
            }

            const seg = document.createElement("span");
            seg.className = "path-segment";
            seg.textContent = part;

            // Build partial path for this segment
            let partial;
            if (isUnix) {
                partial = "/" + parts.slice(0, i + 1).join("/");
            } else {
                partial = parts.slice(0, i + 1).join("\\");
                // Ensure drive letter has backslash
                if (i === 0 && !partial.endsWith("\\")) partial += "\\";
            }

            seg.addEventListener("click", () => browseTo(partial));
            dirCurrentPath.appendChild(seg);
        });
    }

    function renderDirListing(data) {
        dirListing.innerHTML = "";

        // Parent directory (go up)
        if (data.parent) {
            const upItem = document.createElement("div");
            upItem.className = "dir-item dir-up";
            upItem.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="15 18 9 12 15 6"/>
                </svg>
                <span>.. (Parent Directory)</span>
            `;
            upItem.addEventListener("click", () => browseTo(data.parent));
            dirListing.appendChild(upItem);
        }

        // Drive letters (Windows)
        if (data.drives && data.drives.length > 0) {
            data.drives.forEach((drive) => {
                const item = document.createElement("div");
                item.className = "dir-item";
                item.innerHTML = `
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>
                        <rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>
                        <line x1="6" y1="6" x2="6.01" y2="6"/>
                        <line x1="6" y1="18" x2="6.01" y2="18"/>
                    </svg>
                    <span>${drive.name}</span>
                `;
                item.addEventListener("click", () => browseTo(drive.path));
                dirListing.appendChild(item);
            });
        }

        // Directories
        if (data.directories.length === 0 && !data.parent && (!data.drives || data.drives.length === 0)) {
            dirListing.innerHTML = '<div class="dir-empty">No subdirectories found</div>';
            return;
        }

        data.directories.forEach((dir) => {
            const item = document.createElement("div");
            item.className = "dir-item";
            item.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                </svg>
                <span>${dir.name}</span>
            `;
            item.addEventListener("click", () => browseTo(dir.path));
            dirListing.appendChild(item);
        });
    }

    // Modal event listeners
    btnChangeDest.addEventListener("click", openDirModal);
    btnCloseModal.addEventListener("click", closeDirModal);
    btnDirCancel.addEventListener("click", closeDirModal);

    // Close modal on overlay click
    dirModal.addEventListener("click", (e) => {
        if (e.target === dirModal) closeDirModal();
    });

    // Close modal on Escape
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && dirModal.style.display !== "none") {
            closeDirModal();
        }
    });

    // Go to typed path
    btnGoPath.addEventListener("click", () => {
        const path = dirPathInput.value.trim();
        if (path) browseTo(path);
    });

    dirPathInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            const path = dirPathInput.value.trim();
            if (path) browseTo(path);
        }
    });

    // Select current folder
    btnDirSelect.addEventListener("click", async () => {
        if (browsingPath) {
            const ok = await setDownloadDir(browsingPath);
            if (ok) closeDirModal();
        }
    });

    // ---------- API Calls ----------

    async function fetchVideoInfo(url) {
        hideError();
        setFetchLoading(true);
        resetToInitial();

        try {
            const resp = await fetch(`/api/info?url=${encodeURIComponent(url)}`);
            const data = await resp.json();

            if (!resp.ok) {
                throw new Error(data.error || "Failed to fetch video information.");
            }

            currentVideoInfo = data;
            renderVideoInfo(data);
        } catch (err) {
            showError(err.message);
        } finally {
            setFetchLoading(false);
        }
    }

    // ---------- Render Video Info ----------

    function renderVideoInfo(info) {
        // Thumbnail
        if (info.thumbnail) {
            videoThumbnail.src = info.thumbnail;
            videoThumbnail.alt = info.title;
        } else {
            videoThumbnail.src = "";
        }

        // Duration
        videoDuration.textContent = formatDuration(info.duration);
        videoDuration.style.display = info.duration ? "block" : "none";

        // Metadata
        videoTitle.textContent = info.title;
        videoChannel.textContent = info.channel;

        // Presets
        renderPresets(info.presets);

        // Formats table
        renderFormatsTable(info.formats);

        videoSection.style.display = "flex";
    }

    function renderPresets(presets) {
        presetsGrid.innerHTML = "";
        presets.forEach((preset) => {
            const card = document.createElement("div");
            card.className = "preset-card";
            card.innerHTML = `
                <span class="preset-icon">${preset.icon}</span>
                <span class="preset-label">${preset.label}</span>
                <span class="preset-desc">${preset.description}</span>
            `;
            card.addEventListener("click", () => {
                startDownload(
                    currentVideoInfo.webpage_url,
                    preset.format_str,
                    preset.postprocessors || []
                );
            });
            presetsGrid.appendChild(card);
        });
    }

    function renderFormatsTable(formats) {
        formatsTbody.innerHTML = "";

        // Sort: video+audio first, then video, then audio; by resolution descending
        const sorted = [...formats].sort((a, b) => {
            const typeOrder = { "video+audio": 0, video: 1, audio: 2 };
            const ta = typeOrder[a.type] ?? 3;
            const tb = typeOrder[b.type] ?? 3;
            if (ta !== tb) return ta - tb;

            // Parse resolution height
            const ha = parseInt(a.resolution) || 0;
            const hb = parseInt(b.resolution) || 0;
            return hb - ha;
        });

        sorted.forEach((fmt) => {
            const tr = document.createElement("tr");
            tr.dataset.type = fmt.type;

            const badgeClass =
                fmt.type === "video+audio" ? "video-audio" :
                fmt.type === "video" ? "video-only" : "audio-only";
            const badgeLabel =
                fmt.type === "video+audio" ? "V+A" :
                fmt.type === "video" ? "Video" : "Audio";

            tr.innerHTML = `
                <td><code>${fmt.format_id}</code></td>
                <td>${fmt.ext}</td>
                <td>${fmt.resolution}</td>
                <td>${fmt.fps || "—"}</td>
                <td>${formatFilesize(fmt.filesize)}</td>
                <td><span class="type-badge ${badgeClass}">${badgeLabel}</span></td>
                <td><button class="btn-download-format" data-format-id="${fmt.format_id}">Download</button></td>
            `;
            formatsTbody.appendChild(tr);
        });

        // Attach download handlers
        formatsTbody.querySelectorAll(".btn-download-format").forEach((btn) => {
            btn.addEventListener("click", () => {
                const fmtId = btn.dataset.formatId;
                startDownload(currentVideoInfo.webpage_url, fmtId);
            });
        });

        // Apply active filter
        applyFormatFilter();
    }

    // ---------- Format Filters ----------

    let activeFilter = "all";

    document.querySelectorAll(".filter-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            activeFilter = btn.dataset.filter;
            applyFormatFilter();
        });
    });

    function applyFormatFilter() {
        const rows = formatsTbody.querySelectorAll("tr");
        rows.forEach((row) => {
            if (activeFilter === "all" || row.dataset.type === activeFilter) {
                row.style.display = "";
            } else {
                row.style.display = "none";
            }
        });
    }

    // ---------- Formats Toggle ----------

    const chevron = btnToggleFormats.querySelector(".chevron");
    btnToggleFormats.addEventListener("click", () => {
        const isOpen = formatsContent.style.display !== "none";
        formatsContent.style.display = isOpen ? "none" : "block";
        btnToggleFormats.classList.toggle("open", !isOpen);
        if (chevron) {
            chevron.textContent = isOpen ? "[+]" : "[-]";
        }
    });

    // ---------- Download via WebSocket ----------

    function startDownload(url, formatStr, postprocessors = []) {
        hideError();
        videoSection.style.display = "none";
        completeSection.style.display = "none";
        downloadSection.style.display = "block";

        // Reset progress UI
        downloadStatusText.textContent = "Starting download...";
        downloadFilename.textContent = "";
        progressBarFill.style.width = "0%";
        progressPercent.textContent = "0%";
        progressSpeed.textContent = "";
        progressEta.textContent = "";
        downloadStatusIcon.innerHTML = '<div class="spinner-large"></div>';

        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${protocol}//${location.host}/ws/download`);
        activeWebSocket = ws;

        ws.addEventListener("open", () => {
            ws.send(JSON.stringify({
                url,
                format_str: formatStr,
                postprocessors,
            }));
        });

        ws.addEventListener("message", (event) => {
            const msg = JSON.parse(event.data);
            handleDownloadEvent(msg);
        });

        ws.addEventListener("close", () => {
            activeWebSocket = null;
        });

        ws.addEventListener("error", () => {
            showError("WebSocket connection failed. Is the server running?");
            downloadSection.style.display = "none";
            videoSection.style.display = "flex";
        });
    }

    function handleDownloadEvent(msg) {
        switch (msg.type) {
            case "started":
                downloadStatusText.textContent = "Downloading...";
                break;

            case "progress":
                if (msg.status === "downloading") {
                    downloadStatusText.textContent = "Downloading...";
                    downloadFilename.textContent = msg.filename || "";

                    const pct = parseFloat(msg.percent) || 0;
                    progressBarFill.style.width = `${pct}%`;
                    progressPercent.textContent = msg.percent;
                    progressSpeed.textContent = msg.speed !== "N/A" ? msg.speed : "";
                    progressEta.textContent = msg.eta !== "N/A" ? `ETA: ${msg.eta}` : "";
                } else if (msg.status === "post_processing") {
                    downloadStatusText.textContent = "Post-processing...";
                    progressBarFill.style.width = "100%";
                    progressPercent.textContent = "100%";
                    progressSpeed.textContent = "";
                    progressEta.textContent = "";
                }
                break;

            case "complete":
                onDownloadComplete(msg);
                break;

            case "error":
                showError(msg.error || "Download failed.");
                downloadSection.style.display = "none";
                videoSection.style.display = "flex";
                break;

            case "cancelled":
                downloadSection.style.display = "none";
                videoSection.style.display = "flex";
                break;
        }
    }

    function onDownloadComplete(msg) {
        downloadSection.style.display = "none";
        completeSection.style.display = "block";
        completeFilename.textContent = msg.filename || "Download complete";
    }

    // ---------- Cancel Download ----------

    btnCancelDownload.addEventListener("click", () => {
        if (activeWebSocket && activeWebSocket.readyState === WebSocket.OPEN) {
            activeWebSocket.send(JSON.stringify({ action: "cancel" }));
        }
        downloadSection.style.display = "none";
        videoSection.style.display = "flex";
    });

    // ---------- Event Listeners ----------

    // Fetch Info
    btnFetch.addEventListener("click", () => {
        const url = urlInput.value.trim();
        if (!url) {
            showError("Please enter a valid URL.");
            urlInput.focus();
            return;
        }
        fetchVideoInfo(url);
    });

    // Enter key
    urlInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            btnFetch.click();
        }
    });

    // Clear URL
    urlInput.addEventListener("input", () => {
        btnClearUrl.style.display = urlInput.value.length > 0 ? "flex" : "none";
    });

    btnClearUrl.addEventListener("click", () => {
        urlInput.value = "";
        btnClearUrl.style.display = "none";
        resetToInitial();
        urlInput.focus();
    });

    // Dismiss error
    btnDismissError.addEventListener("click", hideError);

    // Open downloads folder
    btnOpenDownloads.addEventListener("click", async () => {
        try {
            await fetch("/api/open-downloads", { method: "POST" });
        } catch {
            showError("Could not open downloads folder.");
        }
    });

    btnOpenFolder.addEventListener("click", async () => {
        try {
            await fetch("/api/open-downloads", { method: "POST" });
        } catch {
            showError("Could not open downloads folder.");
        }
    });

    // Download Another
    btnDownloadAnother.addEventListener("click", () => {
        completeSection.style.display = "none";
        urlInput.value = "";
        btnClearUrl.style.display = "none";
        urlInput.focus();
    });

    // ---------- Auto-paste on focus ----------
    urlInput.addEventListener("focus", async () => {
        if (urlInput.value.trim() !== "") return;
        try {
            const text = await navigator.clipboard.readText();
            if (text && (text.startsWith("http://") || text.startsWith("https://"))) {
                urlInput.value = text;
                btnClearUrl.style.display = "flex";
            }
        } catch {
            // Clipboard API may not be available — silently ignore
        }
    });

    // ---------- Theme Switcher ----------
    const themeBtns = document.querySelectorAll(".theme-btn");
    const savedTheme = localStorage.getItem("retro-theme") || "amber";
    applyTheme(savedTheme);

    function applyTheme(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("retro-theme", theme);
        themeBtns.forEach((btn) => {
            btn.classList.toggle("active", btn.dataset.theme === theme);
        });
    }

    themeBtns.forEach((btn) => {
        btn.addEventListener("click", () => applyTheme(btn.dataset.theme));
    });

    // ---------- Cookie Settings ----------
    const cookieSelect = $("#cookie-select");

    async function loadCookieSetting() {
        try {
            const resp = await fetch("/api/cookies");
            const data = await resp.json();
            if (data.source && cookieSelect) {
                cookieSelect.value = data.source;
            }
        } catch {
            // ignore
        }
    }

    if (cookieSelect) {
        cookieSelect.addEventListener("change", async () => {
            const source = cookieSelect.value;
            try {
                await fetch("/api/cookies", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ source }),
                });
            } catch (err) {
                showError("Failed to update cookie source: " + err.message);
            }
        });
    }

    // ---------- Initialize ----------
    loadDownloadDir();
    loadCookieSetting();

})();

