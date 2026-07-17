(function () {
    "use strict";
    const dialog = document.querySelector("[data-biometric-dialog]");
    if (!dialog || !window.DataFinderApp) return;
    const app = window.DataFinderApp;
    let video = dialog.querySelector("[data-biometric-video]");
    let canvas = dialog.querySelector("[data-biometric-canvas]");
    const faceVideo = video;
    const faceCanvas = canvas;
    const status = dialog.querySelector("[data-biometric-status]");
    const capture = dialog.querySelector("[data-biometric-capture]");
    const passwordWrap = dialog.querySelector("[data-biometric-password]");
    const password = dialog.querySelector("[data-face-password]");
    const remove = dialog.querySelector("[data-face-delete]");
    const silentBar = document.querySelector("[data-gesture-silent]");
    const silentVideo = silentBar?.querySelector("[data-gesture-silent-video]");
    const silentCanvas = silentBar?.querySelector("[data-gesture-silent-canvas]");
    const silentCancel = silentBar?.querySelector("[data-gesture-silent-cancel]");
    const silentHint = silentBar?.querySelector("[data-gesture-silent-hint]");
    let silentActive = false;
    let stream = null;
    let mode = "";
    let gestureLoopActive = false;
    let gestureLoopToken = 0;
    let requestRunning = false;

    function message(text, level = "") { status.textContent = text; status.className = `biometric-status ${level}`; }
    function wait(ms) { return new Promise((resolve) => window.setTimeout(resolve, ms)); }
    function stopCamera() {
        gestureLoopActive = false;
        gestureLoopToken += 1;
        if (stream) stream.getTracks().forEach((track) => track.stop());
        stream = null;
        video.srcObject = null;
    }
    async function startCamera() {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器不支持摄像头访问");
        stopCamera();
        stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: "user", width: {ideal: 640}, height: {ideal: 480}}, audio: false});
        video.srcObject = stream;
        await video.play();
    }
    async function frames(count, quiet = false) {
        const output = [];
        canvas.width = 480; canvas.height = 360;
        const context = canvas.getContext("2d", {alpha: false});
        for (let index = 0; index < count; index += 1) {
            if (!quiet) message(`正在采集第 ${index + 1} / ${count} 帧，请保持在取景框内…`);
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            output.push(canvas.toDataURL("image/jpeg", .78));
            await wait(quiet ? 170 : 260);
        }
        return output;
    }
    function configure(nextMode) {
        mode = nextMode;
        const title = dialog.querySelector("[data-biometric-title]");
        const kicker = dialog.querySelector("[data-biometric-kicker]");
        const hint = dialog.querySelector("[data-camera-hint]");
        if (passwordWrap) passwordWrap.hidden = mode !== "enroll";
        if (remove) remove.hidden = mode !== "enroll";
        if (title) title.textContent = mode === "gesture" ? "手势快捷调度" : "管理我的人脸登录";
        if (kicker) kicker.textContent = mode === "gesture" ? "自动取帧 · 连续识别" : "指定账号 · 活体校验";
        if (hint) hint.textContent = mode === "gesture" ? "胜利=天气 · 握拳=音乐 · 张开手掌=新闻；无需点击识别" : "请正对镜头，并轻微转头或眨眼";
        capture.textContent = mode === "gesture" ? (gestureLoopActive ? "暂停自动识别" : "继续自动识别") : mode === "enroll" ? "录入 / 重新录入" : "开始验证";
    }
    function gestureNote(text) { if (silentHint) silentHint.textContent = text; }
    function stopSilentGesture() {
        silentActive = false;
        gestureLoopActive = false;
        gestureLoopToken += 1;
        stopCamera();
        if (silentBar) silentBar.hidden = true;
        video = faceVideo; canvas = faceCanvas;
    }
    function applyGesture(result) {
        const input = document.querySelector("[data-question-input]");
        const employee = result.employee_id ? document.querySelector(`[data-employee-id="${result.employee_id}"]`) : null;
        employee?.click();
        if (input) {
            input.value = result.prompt;
            input.dispatchEvent(new Event("input", {bubbles: true}));
            input.focus();
        }
        app.announce(`${result.label}已写入输入框（置信度 ${Math.round(Number(result.confidence || 0) * 100)}%）`, "success");
        stopSilentGesture();
    }
    async function gestureLoop() {
        if (!stream || requestRunning) return;
        gestureLoopActive = true;
        const token = ++gestureLoopToken;
        gestureNote("静默识别手势中，请在镜头前保持手势约 1 秒…");
        while (gestureLoopActive && stream && token === gestureLoopToken && silentActive) {
            requestRunning = true;
            try {
                const result = await app.request("/api/gestures/recognize", {method: "POST", json: {frames: await frames(5, true)}, timeoutMs: 60000});
                if (result.prompt) { gestureNote(`${result.label || "手势"}识别成功`); applyGesture(result); break; }
            } catch (error) {
                gestureNote(`${app.errorMessage(error)}；仍在继续识别`);
            } finally {
                requestRunning = false;
            }
            await wait(650);
        }
    }
    async function openSilentGesture() {
        if (silentActive) { stopSilentGesture(); return; }
        if (!silentBar || !silentVideo) return;
        mode = "gesture";
        video = silentVideo; canvas = silentCanvas;
        silentActive = true;
        silentBar.hidden = false;
        gestureNote("正在申请摄像头权限…");
        app.announce("正在调用摄像头，静默识别手势中…", "info");
        try {
            await startCamera();
            gestureNote("静默识别手势中，请在镜头前保持手势约 1 秒…");
            gestureLoop();
        } catch (error) {
            const text = error.message || "无法开启摄像头";
            gestureNote(text); app.announce(text, "error");
            stopSilentGesture();
        }
    }
    async function open(nextMode) {
        if (nextMode === "gesture") { openSilentGesture(); return; }
        configure(nextMode);
        message("正在申请摄像头权限…");
        dialog.showModal();
        try {
            await startCamera();
            message("摄像头已开启，画面不会保存为原始照片。");
        } catch (error) { message(error.message || "无法开启摄像头", "error"); }
    }
    async function submit() {
        if (mode === "gesture") {
            if (!stream) return message("请先允许摄像头权限", "error");
            gestureLoopActive = !gestureLoopActive;
            if (gestureLoopActive) gestureLoop(); else { gestureLoopToken += 1; message("自动识别已暂停"); configure("gesture"); }
            return;
        }
        if (!stream) return message("请先允许摄像头权限", "error");
        app.setBusy(capture, true, "多帧校验中…");
        try {
            const captured = await frames(mode === "enroll" ? 6 : 5);
            let endpoint = "/api/auth/face-login";
            let payload = {frames: captured, username: document.querySelector("#username")?.value.trim() || ""};
            if (mode === "enroll") { endpoint = "/api/profile/face"; payload = {frames: captured, password: password.value}; }
            const result = await app.request(endpoint, {method: "POST", json: payload, timeoutMs: 60000});
            message(result.message || "验证已完成", "success");
            if (result.redirect) window.location.assign(result.redirect);
            if (mode === "enroll") { password.value = ""; app.announce(result.message, "success"); }
        } catch (error) { message(app.errorMessage(error), "error"); }
        finally { app.setBusy(capture, false); configure(mode); }
    }
    document.querySelectorAll("[data-biometric-open]").forEach((button) => button.addEventListener("click", () => open(button.dataset.biometricOpen)));
    dialog.querySelectorAll("[data-biometric-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    dialog.addEventListener("close", stopCamera);
    silentCancel?.addEventListener("click", stopSilentGesture);
    capture.addEventListener("click", submit);
    remove?.addEventListener("click", async () => {
        if (!window.confirm("确认删除你的人脸档案？删除后仍可使用密码登录。")) return;
        try { const result = await app.request("/api/profile/face", {method: "DELETE"}); message(result.message, "success"); app.announce(result.message, "success"); }
        catch (error) { message(app.errorMessage(error), "error"); }
    });
})();
