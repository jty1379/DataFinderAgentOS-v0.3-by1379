(function () {
    "use strict";
    const api = window.DataFinderAdmin;
    if (!api) return;
    const itemChecks = api.qsa("[data-warehouse-item]");
    const selectAll = api.qs("[data-warehouse-select-all]");
    const selection = api.qs("[data-warehouse-selection]");
    const taskDialog = api.qs("#deep-task-dialog");
    const resultDialog = api.qs("#deep-result-dialog");
    let taskIds = [];
    let activeTaskId = null;
    let pollTimer = null;

    function selectedIds() { return itemChecks.filter((input) => input.checked).map((input) => Number(input.value)); }
    function syncSelection() {
        const count = selectedIds().length;
        if (selection) selection.textContent = `已选 ${count} 条`;
        api.qsa("[data-batch-deep]").forEach((button) => button.disabled = count === 0);
        if (selectAll) { selectAll.checked = count > 0 && count === itemChecks.length; selectAll.indeterminate = count > 0 && count < itemChecks.length; }
    }
    itemChecks.forEach((input) => input.addEventListener("change", syncSelection));
    selectAll?.addEventListener("change", () => { itemChecks.forEach((input) => input.checked = selectAll.checked); syncSelection(); });

    function taskButton(id) { return api.qs(`[data-task-id="${id}"]`); }
    function statusLabel(status) { return ({pending: "等待调度", running: "执行中", success: "已完成", failed: "失败"})[status] || status; }
    function renderTask(task) {
        const status = api.qs("[data-deep-status]");
        status.textContent = statusLabel(task.status);
        status.className = `v02-status ${task.status === "success" ? "enabled" : (task.status === "failed" ? "error" : "disabled")}`;
        api.qs("[data-deep-progress-text]").textContent = `${task.progress}%`;
        const progress = api.qs("[data-deep-progress]");
        progress.setAttribute("aria-valuenow", task.progress);
        progress.querySelector("span").style.width = `${task.progress}%`;
        api.qs("[data-deep-task-summary]").textContent = `任务 #${task.id} · ${statusLabel(task.status)} · ${task.created_at}`;
        api.qs("[data-deep-employee]").textContent = task.employee_name || "未分配";
        api.qs("[data-deep-mention]").textContent = task.employee_mention ? `@${task.employee_mention}` : "—";
        api.qs("[data-deep-employee-description]").textContent = task.employee_description || "暂无员工说明";
        api.qs("[data-deep-current-step]").textContent = task.current_step;
        api.qs("[data-deep-item-title]").textContent = task.item_title;
        api.qs("[data-deep-mode]").textContent = task.is_update ? "更新采集" : "首次采集";
        const stepIndex = Math.min(5, Math.floor(Number(task.progress) / 18));
        api.qsa("li", api.qs("[data-deep-steps]")).forEach((li, index) => { li.classList.toggle("done", index < stepIndex || task.status === "success"); li.classList.toggle("active", index === stepIndex && task.status === "running"); });
        const logs = task.logs || [];
        api.qs("[data-deep-logs]").innerHTML = logs.length ? logs.map((log) => `<article class="${api.escapeHtml(log.level)}"><time>${api.escapeHtml(log.created_at)}</time><div><b>${api.escapeHtml(log.step)}</b><p>${api.escapeHtml(log.message)}</p></div></article>`).join("") : "<p>暂无执行日志。</p>";
        const result = api.qs("[data-deep-task-result]");
        if (task.result_id) { result.hidden = false; result.querySelector("p").textContent = task.excerpt || "采集结果已写入数据仓库。"; } else { result.hidden = true; }
        const button = taskButton(task.id);
        if (button) { button.dataset.status = task.status; button.querySelector("span").textContent = statusLabel(task.status); }
    }

    async function pollTasks() {
        window.clearTimeout(pollTimer);
        if (!taskDialog?.open || !taskIds.length) return;
        let terminal = 0;
        for (const id of taskIds) {
            try {
                const data = await api.fetchJson(`/admin/warehouse/deep-tasks/${id}`, {method: "GET", timeoutMs: 10000});
                const task = data.task;
                if (["success", "failed"].includes(task.status)) terminal += 1;
                const button = taskButton(id);
                if (button) { button.dataset.status = task.status; button.querySelector("span").textContent = statusLabel(task.status); }
                if (id === activeTaskId) renderTask(task);
            } catch (error) { if (id === activeTaskId) api.announce(error.message, "error"); }
        }
        if (terminal < taskIds.length) pollTimer = window.setTimeout(pollTasks, 900);
    }

    function openTasks(ids) {
        taskIds = ids.map(Number); activeTaskId = taskIds[0];
        const switcher = api.qs("[data-deep-task-switcher]");
        switcher.innerHTML = taskIds.map((id, index) => `<button type="button" data-task-id="${id}" class="${index === 0 ? "active" : ""}">#${id}<span>等待调度</span></button>`).join("");
        switcher.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => { activeTaskId = Number(button.dataset.taskId); switcher.querySelectorAll("button").forEach((item) => item.classList.toggle("active", item === button)); pollTasks(); }));
        if (!taskDialog.open) taskDialog.showModal();
        pollTasks();
    }

    async function startDeep(ids, update, button) {
        api.setBusy(button, true, "创建任务…");
        try {
            const data = await api.fetchJson("/admin/warehouse/deep-collect", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({item_ids: ids, update})});
            api.announce(data.message);
            openTasks(data.task_ids);
        } catch (error) { api.announce(error.message, "error"); }
        finally { api.setBusy(button, false); }
    }
    api.qsa("[data-deep-start]").forEach((button) => button.addEventListener("click", () => startDeep([Number(button.dataset.deepStart)], button.dataset.deepUpdate === "1", button)));
    api.qsa("[data-batch-deep]").forEach((button) => button.addEventListener("click", () => startDeep(selectedIds(), button.dataset.batchDeep === "update", button)));
    taskDialog?.addEventListener("close", () => window.clearTimeout(pollTimer));

    api.qsa("[data-deep-result]").forEach((button) => button.addEventListener("click", async () => {
        const title = api.qs("[data-deep-result-title]");
        const meta = api.qs("[data-deep-result-meta]");
        const content = api.qs("[data-deep-result-content]");
        title.textContent = "深度采集数据"; meta.textContent = "正在读取持久化结果"; content.innerHTML = "<p>正在加载…</p>";
        resultDialog.showModal();
        try {
            const data = await api.fetchJson(`/admin/warehouse/deep-results/${button.dataset.deepResult}`, {method: "GET"});
            const result = data.result;
            title.textContent = result.title;
            meta.textContent = `${result.employee_mention ? "@" + result.employee_mention : "采集专员"} · ${result.created_at} · ${result.is_update ? "更新采集" : "首次采集"}`;
            content.innerHTML = `<dl class="deep-result-metadata"><div><dt>来源</dt><dd>${api.escapeHtml(result.source_name || "未知")}</dd></div><div><dt>原始地址</dt><dd>${api.escapeHtml(result.item_url)}</dd></div><div><dt>正文字符</dt><dd>${Number(result.content?.length || 0)}</dd></div></dl><pre>${api.escapeHtml(result.content || "暂无正文")}</pre>`;
        } catch (error) { content.innerHTML = `<p class="preview-error">${api.escapeHtml(error.message)}</p>`; }
    }));
})();
