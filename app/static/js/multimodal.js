(function () {
    "use strict";
    const root = document.querySelector("[data-multimodal-page]");
    const app = window.DataFinderApp;
    if (!root || !app) return;
    let filter = "";

    const resultBox = (name) => root.querySelector(`[data-mm-${name}-result]`);
    const show = (name, message, type = "info") => {
        const node = resultBox(name);
        node.className = `v02-feedback ${type}`;
        node.innerHTML = `<p>${app.escapeHtml(message)}</p>`;
    };
    const poll = async (taskId, name) => {
        for (let count = 0; count < 60; count += 1) {
            const payload = await app.request(`/admin/multimodal/tasks/${taskId}`, {method: "GET"});
            const task = payload.data;
            if (task.status === "completed") return task;
            if (task.status === "failed") throw new Error(task.error_message || "生成任务失败");
            show(name, `任务 #${taskId.slice(0, 8)} 正在执行…`);
            await new Promise((resolve) => window.setTimeout(resolve, 1000));
        }
        throw new Error("任务仍在执行，请稍后在任务列表刷新查看");
    };
    const submit = async (taskType, body, name) => {
        const payload = await app.request("/admin/multimodal/generate", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({task_type: taskType, ...body}), timeoutMs: 15000,
        });
        show(name, `任务 #${payload.data.task_id.slice(0, 8)} 已进入队列`);
        return poll(payload.data.task_id, name);
    };

    root.querySelector("[data-mm-generate-image]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        const prompt = root.querySelector("[data-mm-image-prompt]").value.trim();
        if (!prompt) return show("image", "请输入提示词", "error");
        button.disabled = true;
        show("image", "正在提交任务…");
        try {
            const task = await submit("image", {
                prompt, style: root.querySelector("[data-mm-style]").value,
                image_size: root.querySelector("[data-mm-size]").value,
            }, "image");
            const preview = root.querySelector("[data-mm-image-preview]");
            preview.querySelector("img").src = task.resource_url;
            preview.hidden = false;
            show("image", `生成完成，耗时 ${task.latency_ms} ms`, "success");
        } catch (error) { show("image", error.message, "error"); }
        finally { button.disabled = false; loadTasks(); }
    });

    root.querySelector("[data-mm-video-check]")?.addEventListener("click", async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
            await submit("video", {prompt: "视频能力可用性检查", duration: 5}, "video");
        } catch (error) { show("video", error.message, "error"); }
        finally { button.disabled = false; loadTasks(); }
    });

    const statusText = {pending: "等待中", running: "生成中", completed: "已完成", failed: "失败"};
    async function loadTasks() {
        const list = root.querySelector("[data-mm-task-list]");
        list.innerHTML = '<div class="v02-feedback"><p>正在读取任务…</p></div>';
        try {
            const payload = await app.request(`/admin/multimodal/tasks${filter ? `?type=${filter}` : ""}`, {method: "GET"});
            list.innerHTML = payload.data.length ? payload.data.map((task) => `
                <article class="multimodal-task-item">
                    <div><b>${app.escapeHtml(task.display_prompt || task.prompt || `生成任务 #${task.id}`)}</b><small>${app.escapeHtml(task.task_type === "image" ? "图片" : "视频")} · ${app.escapeHtml(task.created_at)}</small></div>
                    <span class="v02-status ${task.status === "completed" ? "enabled" : task.status === "failed" ? "error" : "warning"}">${statusText[task.status] || app.escapeHtml(task.status)}</span>
                    <small>${task.status === "failed" ? app.escapeHtml(task.error_message) : `${Number(task.latency_ms || 0)} ms`}</small>
                    <button class="v02-row-action danger" type="button" data-mm-delete="${task.task_id}">删除</button>
                </article>`).join("") : '<div class="v02-feedback"><p>暂无任务记录。</p></div>';
        } catch (error) { list.innerHTML = `<div class="v02-feedback error"><p>${app.escapeHtml(error.message)}</p></div>`; }
    }
    root.addEventListener("click", async (event) => {
        const filterButton = event.target.closest("[data-mm-filter]");
        if (filterButton) {
            filter = filterButton.dataset.mmFilter;
            root.querySelectorAll("[data-mm-filter]").forEach((item) => item.classList.toggle("active", item === filterButton));
            return loadTasks();
        }
        const deleteButton = event.target.closest("[data-mm-delete]");
        if (deleteButton && window.confirm("确认删除该生成任务？")) {
            try { await app.request(`/admin/multimodal/tasks/${deleteButton.dataset.mmDelete}/delete`, {method: "POST", body: ""}); await loadTasks(); }
            catch (error) { app.announce(error.message, "error"); }
        }
    });
    root.querySelector("[data-mm-refresh]")?.addEventListener("click", loadTasks);
    loadTasks();
})();
