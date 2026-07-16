(function () {
    "use strict";
    const dialog = document.querySelector("[data-biometric-dialog]");
    if (!dialog || !window.DataFinderApp) return;
    const app = window.DataFinderApp;
    const video = dialog.querySelector("[data-biometric-video]");
    const canvas = dialog.querySelector("[data-biometric-canvas]");
    const status = dialog.querySelector("[data-biometric-status]");
    const capture = dialog.querySelector("[data-biometric-capture]");
    const passwordWrap = dialog.querySelector("[data-biometric-password]");
    const password = dialog.querySelector("[data-face-password]");
    const remove = dialog.querySelector("[data-face-delete]");
    let stream = null;
    let mode = "";

    function message(text, level = "") { status.textContent = text; status.className = `biometric-status ${level}`; }
    function stopCamera() { if (stream) stream.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null; }
    async function startCamera() {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("当前浏览器不支持摄像头访问");
        stopCamera();
        stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: "user", width: {ideal: 640}, height: {ideal: 480}}, audio: false});
        video.srcObject = stream;
        await video.play();
    }
    async function frames(count) {
        const output = [];
        canvas.width = 480; canvas.height = 360;
        const context = canvas.getContext("2d", {alpha: false});
        for (let index = 0; index < count; index += 1) {
            message(`正在采集第 ${index + 1} / ${count} 帧，请保持在取景框内…`);
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            output.push(canvas.toDataURL("image/jpeg", .78));
            await new Promise((resolve) => setTimeout(resolve, 260));
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
        if (kicker) kicker.textContent = mode === "gesture" ? "MediaPipe · 多帧确认" : "指定账号 · 活体校验";
        if (hint) hint.textContent = mode === "gesture" ? "胜利=天气 · 握拳=音乐 · 张开手掌=新闻" : "请正对镜头，并轻微转头或眨眼";
        capture.textContent = mode === "gesture" ? "识别手势" : mode === "enroll" ? "录入 / 重新录入" : "开始验证";
    }
    async function open(nextMode) {
        configure(nextMode); message("正在申请摄像头权限…"); dialog.showModal();
        try { await startCamera(); message("摄像头已开启，画面不会保存为原始照片。"); }
        catch (error) { message(error.message || "无法开启摄像头", "error"); }
    }
    async function submit() {
        if (!stream) return message("请先允许摄像头权限", "error");
        app.setBusy(capture, true, "多帧校验中…");
        try {
            const captured = await frames(mode === "enroll" ? 6 : 5);
            let endpoint = "/api/auth/face-login";
            let payload = {frames: captured, username: document.querySelector("#username")?.value.trim() || ""};
            if (mode === "enroll") { endpoint = "/api/profile/face"; payload = {frames: captured, password: password.value}; }
            if (mode === "gesture") { endpoint = "/api/gestures/recognize"; payload = {frames: captured}; }
            const result = await app.request(endpoint, {method: "POST", json: payload, timeoutMs: 60000});
            message(result.message || `${result.label || "验证"}已完成`, "success");
            if (result.redirect) window.location.assign(result.redirect);
            if (mode === "gesture" && result.prompt) {
                const input = document.querySelector("[data-question-input]");
                const employee = result.employee_id ? document.querySelector(`[data-employee-id="${result.employee_id}"]`) : null;
                employee?.click();
                input.value = result.prompt; input.dispatchEvent(new Event("input", {bubbles: true})); input.focus();
                app.announce(`${result.label}已写入输入框（置信度 ${Math.round(result.confidence * 100)}%）`, "success");
                setTimeout(() => dialog.close(), 800);
            }
            if (mode === "enroll") { password.value = ""; app.announce(result.message, "success"); }
        } catch (error) { message(app.errorMessage(error), "error"); }
        finally { app.setBusy(capture, false); configure(mode); }
    }
    document.querySelectorAll("[data-biometric-open]").forEach((button) => button.addEventListener("click", () => open(button.dataset.biometricOpen)));
    dialog.querySelectorAll("[data-biometric-close]").forEach((button) => button.addEventListener("click", () => dialog.close()));
    dialog.addEventListener("close", stopCamera); capture.addEventListener("click", submit);
    remove?.addEventListener("click", async () => {
        if (!window.confirm("确认删除你的人脸档案？删除后仍可使用密码登录。")) return;
        try { const result = await app.request("/api/profile/face", {method: "DELETE"}); message(result.message, "success"); app.announce(result.message, "success"); }
        catch (error) { message(app.errorMessage(error), "error"); }
    });
})();
