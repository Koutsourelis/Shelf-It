/**
 * ShelfSense AR — Agent Application & State Machine (Frontend)
 * States: idle, scanning, recommending, awaiting_move, verifying, done, needs_photo, error
 */

document.addEventListener("DOMContentLoaded", () => {
    const videoElem = document.getElementById("cameraVideo");
    const fallbackImgElem = document.getElementById("fallbackImagePreview");
    const canvasElem = document.getElementById("arCanvas");
    const ctx = canvasElem.getContext("2d");

    const scanBtn = document.getElementById("scanBtn");
    const rescanBtn = document.getElementById("rescanBtn");
    const targetAudienceSelect = document.getElementById("targetAudience");
    const scenarioSelect = document.getElementById("scenarioSelect");
    const useCachedToggle = document.getElementById("useCachedDemo");
    const fallbackFileInput = document.getElementById("fallbackFile");

    const traceLog = document.getElementById("traceLog");
    const traceSourceBadge = document.getElementById("traceSourceBadge");
    const stepCounter = document.getElementById("stepCounter");
    const errorToast = document.getElementById("errorToast");
    const errorMessage = document.getElementById("errorMessage");
    const fallbackToggleBtn = document.getElementById("fallbackToggleBtn");

    const recommendationCard = document.getElementById("recommendationCard");
    const salesLiftBadge = document.getElementById("salesLiftBadge");
    const recReasonText = document.getElementById("recReasonText");
    const acceptBtn = document.getElementById("acceptBtn");
    const overrideBtn = document.getElementById("overrideBtn");

    const needsUserCard = document.getElementById("needsUserCard");
    const needsUserMessage = document.getElementById("needsUserMessage");
    const resumeActionBtn = document.getElementById("resumeActionBtn");

    const doneSummaryCard = document.getElementById("doneSummaryCard");
    const doneSummaryText = document.getElementById("doneSummaryText");

    const shelfTalkerSection = document.getElementById("shelfTalkerSection");
    const talkerContainer = document.getElementById("talkerContainer");
    const downloadTalkerLink = document.getElementById("downloadTalkerLink");

    const viewportBadge = document.getElementById("viewportBadge");
    const viewportStatusText = document.getElementById("viewportStatusText");
    const verifyBanner = document.getElementById("verifyBanner");
    const verifyIcon = document.getElementById("verifyIcon");
    const verifyText = document.getElementById("verifyText");

    // State Machine
    let currentState = "idle"; // idle, scanning, recommending, awaiting_move, verifying, done, needs_photo, error
    let mediaStream = null;
    let currentRunId = null;
    let currentResult = null;
    let fallbackImageData = null;
    let isSpeaking = false;
    let stepCount = 0;
    const maxSteps = 8;
    const snapshotIntervalMs = 3000;
    let snapshotTimer = null;
    let analysisInFlight = false;
    let monitoringActive = false;
    let motionSupported = false;
    let motionStable = true;
    let lastMotionAt = 0;

    function handleMotion(event) {
        const rotation = event.rotationRate || {};
        const acceleration = event.accelerationIncludingGravity || {};
        const motionMagnitude = Math.abs(rotation.alpha || 0)
            + Math.abs(rotation.beta || 0)
            + Math.abs(rotation.gamma || 0);
        const accelerationMagnitude = Math.abs(acceleration.x || 0)
            + Math.abs(acceleration.y || 0)
            + Math.abs(acceleration.z || 0);
        motionStable = motionMagnitude < 12 && accelerationMagnitude < 35;
        if (!motionStable) {
            lastMotionAt = performance.now();
            updateViewportStatus("Hold steady for snapshot", "warning");
        }
    }

    async function enableMotionTracking() {
        if (!("DeviceMotionEvent" in window)) return;
        try {
            if (typeof DeviceMotionEvent.requestPermission === "function") {
                const permission = await DeviceMotionEvent.requestPermission();
                if (permission !== "granted") return;
            }
            window.addEventListener("devicemotion", handleMotion);
            motionSupported = true;
        } catch (err) {
            console.warn("Motion tracking unavailable:", err);
        }
    }

    function setState(newState) {
        currentState = newState;
        console.log("[State Machine] Transitioned to:", currentState);

        if (currentState === "idle") {
            scanBtn.textContent = "Scan Shelf";
            scanBtn.disabled = false;
            rescanBtn.disabled = true;
            updateViewportStatus("Camera Ready", "success");
        } else if (currentState === "scanning") {
            scanBtn.textContent = "Agent Running...";
            scanBtn.disabled = true;
            rescanBtn.disabled = true;
            updateViewportStatus("Agent Reasoning Live...", "warning");
        } else if (currentState === "awaiting_move") {
            scanBtn.textContent = "Scan Shelf";
            scanBtn.disabled = false;
            rescanBtn.disabled = false;
            updateViewportStatus("Awaiting Product Move — AR Active", "warning");
        } else if (currentState === "verifying") {
            rescanBtn.textContent = "Verifying...";
            rescanBtn.disabled = true;
            updateViewportStatus("Verifying Placement...", "warning");
        } else if (currentState === "done") {
            scanBtn.textContent = "Scan Shelf";
            scanBtn.disabled = false;
            rescanBtn.disabled = false;
            updateViewportStatus("Optimization Verified & Complete", "success");
        } else if (currentState === "needs_photo") {
            scanBtn.textContent = "Scan Shelf";
            scanBtn.disabled = false;
            rescanBtn.disabled = true;
            updateViewportStatus("Action Required: Better Photo Needed", "warning");
        } else if (currentState === "error") {
            scanBtn.textContent = "Scan Shelf";
            scanBtn.disabled = false;
            rescanBtn.disabled = true;
            updateViewportStatus("Error encountered", "error");
        }
    }

    async function initCamera() {
        try {
            const constraints = {
                video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }
            };
            mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
            videoElem.srcObject = mediaStream;
            videoElem.classList.remove("hidden");
            fallbackImgElem.classList.add("hidden");
            setState("idle");
        } catch (err) {
            console.warn("Rear camera failed, trying any video...", err);
            try {
                mediaStream = await navigator.mediaDevices.getUserMedia({ video: true });
                videoElem.srcObject = mediaStream;
                videoElem.classList.remove("hidden");
                fallbackImgElem.classList.add("hidden");
                setState("idle");
            } catch (fallbackErr) {
                console.error("Camera access denied:", fallbackErr);
                showError("Camera unavailable. Please upload a shelf photo or enable Cached Demo (Plan B).");
                videoElem.classList.add("hidden");
                useCachedToggle.checked = true;
                setState("error");
            }
        }
    }

    function updateViewportStatus(text, statusType = "success") {
        viewportStatusText.textContent = text;
        const dot = viewportBadge.querySelector(".status-dot");
        if (statusType === "success") dot.style.backgroundColor = "var(--accent-green)";
        else if (statusType === "warning") dot.style.backgroundColor = "var(--accent-amber)";
        else dot.style.backgroundColor = "var(--accent-red)";
    }

    function showError(msg) {
        errorMessage.textContent = msg;
        errorToast.classList.remove("hidden");
        setState("error");
    }

    fallbackToggleBtn.addEventListener("click", () => {
        useCachedToggle.checked = true;
        errorToast.classList.add("hidden");
        updateViewportStatus("Cached Demo Ready (Plan B)", "warning");
    });

    fallbackFileInput.addEventListener("change", (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (event) => {
            fallbackImageData = event.target.result;
            fallbackImgElem.src = fallbackImageData;
            fallbackImgElem.classList.remove("hidden");
            videoElem.classList.add("hidden");
            updateViewportStatus("Uploaded Shelf Photo Loaded", "success");
        };
        reader.readAsDataURL(file);
    });

    function showCachedDemoImage() {
        fallbackImageData = "/demo_shelf.jpg";
        fallbackImgElem.onerror = () => showError("Demo image failed to load");
        fallbackImgElem.src = fallbackImageData;
        fallbackImgElem.classList.remove("hidden");
        videoElem.classList.add("hidden");
        updateViewportStatus("Cached Demo Shelf Loaded", "warning");
    }

    useCachedToggle.addEventListener("change", () => {
        if (useCachedToggle.checked) showCachedDemoImage();
    });

    function ensureFallbackImageReady() {
        if (fallbackImgElem.complete && fallbackImgElem.naturalWidth > 0) return Promise.resolve();
        return new Promise((resolve, reject) => {
            fallbackImgElem.addEventListener("load", () => resolve(true), { once: true });
            fallbackImgElem.addEventListener("error", () => {
                fallbackImgElem.onerror = null;
                showError("Demo image failed to load");
                resolve(false);
            }, { once: true });
        });
    }

    async function captureStableFrame() {
        updateViewportStatus("Preparing stable snapshot", "warning");
        if (fallbackImageData && !fallbackImgElem.classList.contains("hidden")) {
            return captureFrameAsBase64();
        }

        const stabilityDeadline = performance.now() + 2500;
        while (motionSupported && (!motionStable || performance.now() - lastMotionAt < 350)) {
            if (performance.now() >= stabilityDeadline) {
                throw new Error("Camera did not become stable before snapshot timeout");
            }
            updateViewportStatus("Hold steady for snapshot", "warning");
            await new Promise((resolve) => setTimeout(resolve, 100));
        }
        updateViewportStatus("Analyzing stable snapshot", "warning");
        return captureFrameAsBase64();
    }

    function captureFrameAsBase64() {
        const offCanvas = document.createElement("canvas");
        const offCtx = offCanvas.getContext("2d");
        let srcWidth = videoElem.videoWidth || 1280;
        let srcHeight = videoElem.videoHeight || 720;

        if (fallbackImageData && fallbackImgElem.complete && !fallbackImgElem.classList.contains("hidden")) {
            srcWidth = fallbackImgElem.naturalWidth || 1280;
            srcHeight = fallbackImgElem.naturalHeight || 720;
            offCanvas.width = srcWidth;
            offCanvas.height = srcHeight;
            offCtx.drawImage(fallbackImgElem, 0, 0);
        } else {
            const maxDim = 1024;
            let targetW = srcWidth;
            let targetH = srcHeight;
            if (targetW > maxDim || targetH > maxDim) {
                if (targetW > targetH) {
                    targetH = Math.round((targetH * maxDim) / targetW);
                    targetW = maxDim;
                } else {
                    targetW = Math.round((targetW * maxDim) / targetH);
                    targetH = maxDim;
                }
            }
            offCanvas.width = targetW;
            offCanvas.height = targetH;
            offCtx.drawImage(videoElem, 0, 0, targetW, targetH);
        }
        return offCanvas.toDataURL("image/jpeg", 0.8);
    }

    async function analyzeSnapshot(isFollowUp = false) {
        if (analysisInFlight) return;
        analysisInFlight = true;
        if (!isFollowUp) {
            setState("scanning");
            stepCount = 0;
            stepCounter.textContent = `step 0 of max ${maxSteps}`;
            traceLog.innerHTML = "";
            recommendationCard.classList.add("hidden");
            needsUserCard.classList.add("hidden");
            doneSummaryCard.classList.add("hidden");
            shelfTalkerSection.classList.add("hidden");
            verifyBanner.classList.add("hidden");
            errorToast.classList.add("hidden");
        }

        const targetAudience = targetAudienceSelect.value;
        const scenario = scenarioSelect.value;
        const useCachedDemo = useCachedToggle.checked;

        traceSourceBadge.textContent = useCachedDemo ? "CACHED" : "LIVE";
        traceSourceBadge.className = `source-badge ${useCachedDemo ? "cached" : "live"}`;

        try {
            if (useCachedDemo) {
                showCachedDemoImage();
                if (!await ensureFallbackImageReady()) return;
            }
            const imageBase64 = await captureStableFrame();
            const response = await fetch("/api/analyze-stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    image_base64: imageBase64,
                    target_audience: targetAudience,
                    use_cached_demo: useCachedDemo,
                    scenario: useCachedDemo ? "default" : scenario
                })
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            await consumeSSEStream(response, !isFollowUp);
        } catch (err) {
            console.error("Scan error:", err);
            if (!isFollowUp) {
                showError("Live detection unavailable. Enable Cached Demo (Plan B) to use the verified mock result.");
            }
        } finally {
            analysisInFlight = false;
        }
    }

    function scheduleSnapshot() {
        if (snapshotTimer) clearTimeout(snapshotTimer);
        if (!monitoringActive || currentState === "needs_photo" || currentState === "verifying") return;
        snapshotTimer = setTimeout(async () => {
            await analyzeSnapshot(true);
            scheduleSnapshot();
        }, snapshotIntervalMs);
    }

    // Scan Button Handler
    scanBtn.addEventListener("click", async () => {
        if (currentState === "scanning" || currentState === "verifying") return;
        monitoringActive = true;
        if (snapshotTimer) clearTimeout(snapshotTimer);
        await analyzeSnapshot();
        scheduleSnapshot();
    });

    async function consumeSSEStream(response, showTrace = true) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n\n");
            buffer = lines.pop();

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    try {
                        const data = JSON.parse(line.replace("data: ", "").trim());
                        if (data.run_id) currentRunId = data.run_id;

                        if (data.type === "result") {
                            handleScanResult(data);
                        } else if (showTrace) {
                            handleAgentEvent(data);
                        }
                    } catch (e) {
                        console.error("SSE parse error", e);
                    }
                }
            }
        }
    }

    function handleAgentEvent(event) {
        stepCount = Math.min(stepCount + 1, maxSteps);
        stepCounter.textContent = `step ${stepCount} of max ${maxSteps}`;

        const div = document.createElement("div");
        div.className = "trace-step done";

        if (event.type === "decision") {
            div.innerHTML = `
                <div class="trace-step-header">
                    <span class="trace-step-name">🤖 Agent Chose: ${event.tool}</span>
                    <span class="chip done">decision</span>
                </div>
                <div class="trace-step-detail"><strong>Why:</strong> ${event.why}</div>
            `;
        } else if (event.type === "observation") {
            const sourceLabel = event.source ? event.source.toUpperCase() : "LIVE";
            div.innerHTML = `
                <div class="trace-step-header">
                    <span class="trace-step-name">👁️ Observation [${sourceLabel}]</span>
                    <span class="chip ${sourceLabel.toLowerCase()}">${event.tool}</span>
                </div>
                <div class="trace-step-detail">${event.detail}</div>
            `;
        } else if (event.type === "needs_user") {
            div.innerHTML = `
                <div class="trace-step-header">
                    <span class="trace-step-name" style="color:var(--accent-blue);">⚠️ Action Required</span>
                    <span class="chip running">waiting</span>
                </div>
                <div class="trace-step-detail">${event.message}</div>
            `;

            if (event.action === "request_better_photo") {
                needsUserMessage.textContent = event.message;
                needsUserCard.classList.remove("hidden");
                setState("needs_photo");
                speakText(event.message);
            } else if (event.action === "await_move") {
                setState("awaiting_move");
            }
        }

        traceLog.appendChild(div);
        traceLog.scrollTop = traceLog.scrollHeight;
    }

    // Resume button when blurry photo prompt appears
    resumeActionBtn.addEventListener("click", async () => {
        needsUserCard.classList.add("hidden");
        setState("scanning");
        const imageBase64 = await captureStableFrame();
        const scenario = scenarioSelect.value;

        try {
            const response = await fetch("/api/resume", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    run_id: currentRunId,
                    image_base64: imageBase64,
                    scenario
                })
            });
            if (!response.ok) throw new Error("Resume failed");
            await consumeSSEStream(response);
        } catch (err) {
            console.error("Resume error:", err);
            showError("Failed to resume agent run.");
        }
    });

    function handleScanResult(result) {
        currentResult = result;
        currentTraceId = result.trace_id || currentRunId;

        recReasonText.textContent = result.recommendation.reason;
        salesLiftBadge.textContent = result.recommendation.projected_sales_lift;
        recommendationCard.classList.remove("hidden");

        if (result.shelf_talker_image_url) {
            if (result.shelf_talker_image_url.startsWith("data:image/svg+xml")) {
                talkerContainer.innerHTML = decodeURIComponent(result.shelf_talker_image_url.replace("data:image/svg+xml;utf8,", ""));
            } else {
                talkerContainer.innerHTML = `<img src="${result.shelf_talker_image_url}" alt="Shelf Talker" style="width:100%; height:auto;">`;
            }
            downloadTalkerLink.href = result.shelf_talker_image_url;
            shelfTalkerSection.classList.remove("hidden");
        }

        speakText(result.recommendation.reason);
        requestAnimationFrame(renderARCanvas);
    }

    function speakText(text) {
        if (!("speechSynthesis" in window)) return;
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.05;
        utterance.onstart = () => { isSpeaking = true; };
        utterance.onend = () => { isSpeaking = false; };
        utterance.onerror = () => { isSpeaking = false; };
        window.speechSynthesis.speak(utterance);
    }

    // AR Canvas Renderer
    function renderARCanvas(timestamp) {
        if (!currentResult) return;
        const displayWidth = viewportContainer.clientWidth;
        const displayHeight = viewportContainer.clientHeight;

        if (canvasElem.width !== displayWidth || canvasElem.height !== displayHeight) {
            canvasElem.width = displayWidth;
            canvasElem.height = displayHeight;
        }

        ctx.clearRect(0, 0, canvasElem.width, canvasElem.height);

        const mediaWidth = fallbackImgElem.classList.contains("hidden")
            ? videoElem.videoWidth || 1280
            : fallbackImgElem.naturalWidth || 1280;
        const mediaHeight = fallbackImgElem.classList.contains("hidden")
            ? videoElem.videoHeight || 720
            : fallbackImgElem.naturalHeight || 720;
        const mediaScale = Math.min(canvasElem.width / mediaWidth, canvasElem.height / mediaHeight);
        const mediaRect = {
            x: (canvasElem.width - mediaWidth * mediaScale) / 2,
            y: (canvasElem.height - mediaHeight * mediaScale) / 2,
            width: mediaWidth * mediaScale,
            height: mediaHeight * mediaScale
        };

        function normToPx(box) {
            const [ymin, xmin, ymax, xmax] = box;
            return {
                x: mediaRect.x + (xmin / 1000) * mediaRect.width,
                y: mediaRect.y + (ymin / 1000) * mediaRect.height,
                w: ((xmax - xmin) / 1000) * mediaRect.width,
                h: ((ymax - ymin) / 1000) * mediaRect.height
            };
        }

        const placedLabels = [];
        function drawLabel(text, anchorX, anchorY, fillColor, textColor, minWidth = 0) {
            const labelHeight = 22;
            const maxLabelWidth = 190;
            const labelWidth = Math.min(maxLabelWidth, Math.max(minWidth, ctx.measureText(text).width + 12));
            let labelText = text;
            while (ctx.measureText(`${labelText}...`).width + 12 > labelWidth && labelText.length > 4) {
                labelText = labelText.slice(0, -1);
            }
            if (labelText !== text) labelText += "...";
            const minX = mediaRect.x;
            const maxX = mediaRect.x + mediaRect.width - labelWidth;
            const x = Math.max(minX, Math.min(anchorX, maxX));
            const firstY = anchorY - labelHeight - 4;
            const yCandidates = [];
            for (let y = firstY; y + labelHeight <= mediaRect.y + mediaRect.height; y += labelHeight + 4) {
                if (y >= mediaRect.y) yCandidates.push(y);
            }
            for (let y = anchorY + 4; y + labelHeight <= mediaRect.y + mediaRect.height; y += labelHeight + 4) {
                if (y >= mediaRect.y) yCandidates.push(y);
            }

            const overlaps = (candidateY) => placedLabels.some((label) =>
                x < label.x + label.width
                && x + labelWidth > label.x
                && candidateY < label.y + label.height
                && candidateY + labelHeight > label.y
            );
            const y = yCandidates.find((candidateY) => !overlaps(candidateY));
            if (y === undefined) return;
            placedLabels.push({ x, y, width: labelWidth, height: labelHeight });
            ctx.fillStyle = fillColor;
            ctx.fillRect(x, y, labelWidth, labelHeight);
            ctx.fillStyle = textColor;
            ctx.textAlign = "left";
            ctx.fillText(labelText, x + 6, y + 15);
        }

        ctx.font = "bold 12px Inter, sans-serif";
        if (currentResult.detected_items) {
            for (const item of currentResult.detected_items) {
                if (item.name === currentResult.recommendation.product_to_move) continue;
                const box = normToPx(item.box_2d);
                ctx.strokeStyle = "rgba(56, 189, 248, 0.7)";
                ctx.lineWidth = 2;
                ctx.strokeRect(box.x, box.y, box.w, box.h);
                drawLabel(`${item.name} (${item.shelf_tier})`, box.x, box.y, "rgba(15, 23, 42, 0.9)", "#38bdf8", 120);
            }
        }

        const moveItem = currentResult.recommendation;
        const fromBox = normToPx(moveItem.move_from_box);
        ctx.strokeStyle = "#ffb020";
        ctx.lineWidth = 4;
        ctx.strokeRect(fromBox.x, fromBox.y, fromBox.w, fromBox.h);

        ctx.font = "bold 13px Inter, sans-serif";
        drawLabel(`MOVE THIS: ${moveItem.product_to_move}`, fromBox.x, fromBox.y, "#ffb020", "#090d16", 140);

        const [destY, destX] = moveItem.move_to_point;
        const destPxX = mediaRect.x + (destX / 1000) * mediaRect.width;
        const destPxY = mediaRect.y + (destY / 1000) * mediaRect.height;
        const pulseRadius = 24;

        ctx.beginPath();
        ctx.arc(destPxX, destPxY, pulseRadius, 0, 2 * Math.PI);
        ctx.strokeStyle = "#22c55e";
        ctx.lineWidth = 3;
        ctx.setLineDash([6, 6]);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = "rgba(34, 197, 94, 0.25)";
        ctx.fill();

        ctx.font = "bold 12px Inter, sans-serif";
        drawLabel("PUT HERE (Eye Level)", destPxX - 70, destPxY - 21, "#22c55e", "#ffffff", 140);
        ctx.textAlign = "center";
        ctx.textAlign = "left";
    }

    window.addEventListener("resize", () => {
        if (currentResult) requestAnimationFrame(renderARCanvas);
    });

    // Feedback (Accept / Override)
    acceptBtn.addEventListener("click", () => sendFeedback("accept", "User accepted swap."));
    overrideBtn.addEventListener("click", () => sendFeedback("override", "User overrode swap."));

    async function sendFeedback(decision, note) {
        if (!currentTraceId) return;
        try {
            const resp = await fetch("/api/feedback", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ trace_id: currentTraceId, decision, note })
            });
            const data = await resp.json();
            alert(`Oumi Feedback Logged: ${data.message || decision}`);
            recommendationCard.classList.add("hidden");
        } catch (err) {
            console.error("Feedback error:", err);
        }
    }

    // Re-scan to Verify Handler
    rescanBtn.addEventListener("click", async () => {
        if (!currentRunId) return;
        monitoringActive = false;
        if (snapshotTimer) clearTimeout(snapshotTimer);
        setState("verifying");
        verifyBanner.classList.add("hidden");

        const imageBase64 = await captureStableFrame();
        const scenario = scenarioSelect.value;

        try {
            const resp = await fetch("/api/verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image_base64: imageBase64, trace_id: currentRunId, scenario })
            });
            const data = await resp.json();
            verifyBanner.classList.remove("hidden");

            if (data.verified) {
                verifyBanner.className = "verify-banner";
                verifyIcon.textContent = "✅";
                verifyText.textContent = data.detail;
                updateViewportStatus("Verified Successfully", "success");
                setState("done");
                doneSummaryCard.classList.remove("hidden");
                speakText("Verification successful! Product is perfectly positioned at eye level.");
            } else {
                verifyBanner.className = "verify-banner error";
                verifyIcon.textContent = "❌";
                verifyText.textContent = data.detail || "Verification failed.";
                updateViewportStatus("Verification Failed — Corrective Action Needed", "error");
                setState("awaiting_move");
                speakText(data.detail);
            }
        } catch (err) {
            console.error("Verify error:", err);
            showError("Verification network request failed.");
            setState("awaiting_move");
        }
    });

    initCamera().then(enableMotionTracking);
});
