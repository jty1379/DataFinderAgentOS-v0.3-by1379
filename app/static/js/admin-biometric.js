(function () {
    "use strict";
    if (!window.DataFinderApp) return;
    const app = window.DataFinderApp;
    async function update(button, action, userId = null) {
        const enabled = button.dataset.enabled !== "1";
        app.setBusy(button, true, "保存中…");
        try {
            const result = await app.request("/api/admin/face-settings", {method: "POST", json: {action, enabled, user_id: userId}});
            button.dataset.enabled = enabled ? "1" : "0";
            if (action === "global") button.innerHTML = `<i class="layui-icon layui-icon-face-smile"></i>人脸登录：${enabled ? "已启用" : "已停用"}`;
            else { button.textContent = enabled ? "已启用" : "已停用"; button.classList.toggle("enabled", enabled); button.classList.toggle("disabled", !enabled); }
            app.announce(result.message, "success");
        } catch (error) { app.announce(app.errorMessage(error), "error"); }
        finally { button.disabled = false; button.removeAttribute("aria-busy"); }
    }
    document.querySelector("[data-face-global]")?.addEventListener("click", (event) => update(event.currentTarget, "global"));
    document.querySelectorAll("[data-face-user]").forEach((button) => button.addEventListener("click", () => update(button, "user", button.dataset.faceUser)));
})();
