(function () {
    "use strict";

    const api = window.DataFinderAdmin;
    if (!api) return;

    const form = api.qs("[data-lookout-form]");
    const keywordInput = api.qs("#lookout-keyword");
    const ruleSelect = api.qs("[data-rule-select]");
    const taskType = api.qs("[data-task-type]");
    const pagesField = api.qs("[data-pages-field]");
    const pagesInput = api.qs("[data-pages-input]");
    const pageInput = api.qs("[data-page-input]");
    const pageSizeInput = api.qs("[data-page-size-input]");
    const ruleContext = api.qs("[data-rule-context]");
    const region = api.qs("[data-result-region]");
    const resultCount = api.qs("[data-result-count]");
    const selectAll = api.qs("[data-select-all]");
    const selectionCount = api.qs("[data-selection-count]");
    const importButton = api.qs("[data-import-results]");
    const taskDialog = api.qs("[data-collection-task-dialog]");
    if (!form || !region) return;

    const terminalStatuses = new Set(["success", "partial", "failed", "cancelled"]);
    const statusLabels = {pending: "等待中", running: "采集中", success: "已完成", partial: "部分成功", failed: "失败", cancelled: "已取消"};
    const state = {items: [], selected: new Set(), taskId: 0, pollTimer: 0};

    function safeUrl(value) {
        try {
            const url = new URL(value, window.location.origin);
            return ["http:", "https:"].includes(url.protocol) ? url.href : "#";
        } catch (_) {
            return "#";
        }
    }

    function updatePipeline(activeName, completed = []) {
        api.qsa("[data-pipeline-step]").forEach((step) => {
            const name = step.dataset.pipelineStep;
            step.classList.toggle("active", name === activeName);
            step.classList.toggle("done", completed.includes(name));
        });
    }

    function updateTaskType() {
        const batch = taskType?.value === "batch";
        if (pagesField) pagesField.hidden = !batch;
        if (pagesInput) pagesInput.disabled = !batch;
    }

    function updateRuleContext() {
        if (!ruleSelect?.selectedOptions.length) return;
        const option = ruleSelect.selectedOptions[0];
        const size = Math.min(Number(option.dataset.pageSize) || 12, 12);
        if (pageSizeInput && !pageSizeInput.dataset.edited) pageSizeInput.value = String(size);
        ruleContext.textContent = `当前规则：${option.dataset.source}；关键词参数 ${option.dataset.keywordParam}，页码参数 ${option.dataset.pageParam}，分页步长 ${option.dataset.pageStep}。`;
    }

    function updateSelection() {
        const total = state.items.length;
        const selected = state.selected.size;
        selectionCount.textContent = `已选择 ${selected} 条`;
        selectAll.disabled = total === 0;
        selectAll.checked = total > 0 && selected === total;
        selectAll.indeterminate = selected > 0 && selected < total;
        importButton.disabled = selected === 0;
        api.qsa("[data-result-select]", region).forEach((checkbox) => {
            checkbox.checked = state.selected.has(checkbox.value);
        });
    }

    function showLoading() {
        region.setAttribute("aria-busy", "true");
        region.innerHTML = '<div class="v02-feedback"><div class="skeleton-grid" aria-hidden="true"><span class="skeleton-card"></span><span class="skeleton-card"></span><span class="skeleton-card"></span></div><p>正在创建采集任务…</p></div>';
        resultCount.textContent = "准备中";
    }

    function showError(message, retry = true) {
        region.setAttribute("aria-busy", "false");
        region.innerHTML = `<div class="v02-feedback" role="alert"><i class="layui-icon layui-icon-close-fill"></i><h4>采集未完成</h4><p>${api.escapeHtml(message)}</p>${retry ? '<button class="v02-button-secondary" type="button" data-retry-collect>重新尝试</button>' : ""}</div>`;
        resultCount.textContent = "采集失败";
        api.qs("[data-retry-collect]", region)?.addEventListener("click", () => form.requestSubmit());
    }

    function showEmpty(message) {
        region.setAttribute("aria-busy", "false");
        region.innerHTML = `<div class="v02-feedback"><i class="layui-icon layui-icon-search"></i><h4>没有采集到结果</h4><p>${api.escapeHtml(message || "可更换关键词、规则或页码后重试。")}</p></div>`;
        resultCount.textContent = "0 条结果";
    }

    function renderProgress(task) {
        const logs = (task.logs || []).slice(-5).map((item) => `<li><span>${api.escapeHtml(item.created_at?.slice(11, 19) || "--:--:--")}</span><b>${api.escapeHtml(item.step || "执行")}</b><p>${api.escapeHtml(item.message || "")}</p></li>`).join("");
        region.setAttribute("aria-busy", task.terminal ? "false" : "true");
        region.innerHTML = `<section class="live-task-card" aria-live="polite">
            <div><span class="v02-status ${task.status === "running" ? "warning" : "disabled"}">${api.escapeHtml(statusLabels[task.status] || task.status)}</span><strong>任务 #${Number(task.id)} · ${Number(task.progress || 0)}%</strong></div>
            <div class="deep-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Number(task.progress || 0)}"><span style="width:${Number(task.progress || 0)}%"></span></div>
            <p>已处理 ${Number(task.processed_pages || 0)} / ${Number(task.total_pages || 1)} 页，保存 ${Number(task.result_count || 0)} 条，失败 ${Number(task.failed_count || 0)} 页。</p>
            <ol class="live-task-logs">${logs || "<li><p>等待任务日志…</p></li>"}</ol>
            ${["pending", "running"].includes(task.status) ? `<button class="v02-button-secondary" type="button" data-current-task-cancel="${Number(task.id)}">取消任务</button>` : ""}
        </section>`;
        resultCount.textContent = `${Number(task.progress || 0)}% · ${statusLabels[task.status] || task.status}`;
        api.qs("[data-current-task-cancel]", region)?.addEventListener("click", (event) => runTaskAction(event.currentTarget.dataset.currentTaskCancel, "cancel", event.currentTarget));
    }

    function renderResults(items) {
        state.items = (items || []).slice(0, 100);
        state.selected.clear();
        region.setAttribute("aria-busy", "false");
        if (!state.items.length) {
            showEmpty();
            updateSelection();
            return;
        }
        region.innerHTML = `<div class="result-grid">${state.items.map((item) => {
            const id = String(item.id);
            const href = safeUrl(item.url);
            return `<article class="result-card">
                <label class="result-select-control"><input class="result-select" type="checkbox" value="${api.escapeHtml(id)}" data-result-select><span class="visually-hidden">选择结果：${api.escapeHtml(item.title)}</span></label>
                <span class="result-card-source">${api.escapeHtml(item.source_name || "未知来源")}</span>
                <h4>${api.escapeHtml(item.title || "未命名结果")}</h4>
                <p>${api.escapeHtml(item.summary || "该结果暂未提供摘要，请打开原文核对。")}</p>
                <footer><span>${api.escapeHtml(item.published_at || "时间未知")}</span><a href="${api.escapeHtml(href)}" target="_blank" rel="noopener noreferrer">查看原文<i class="layui-icon layui-icon-right"></i></a></footer>
            </article>`;
        }).join("")}</div>`;
        resultCount.textContent = `${state.items.length} 条结果`;
        api.qsa("[data-result-select]", region).forEach((checkbox) => checkbox.addEventListener("change", () => {
            if (checkbox.checked) state.selected.add(checkbox.value);
            else state.selected.delete(checkbox.value);
            updateSelection();
        }));
        updateSelection();
        updatePipeline("result", ["query", "rule"]);
    }

    async function loadTask(taskId) {
        const data = await api.fetchJson(`/admin/lookout/tasks/${taskId}`, {method: "GET"});
        return data.task;
    }

    async function pollTask() {
        window.clearTimeout(state.pollTimer);
        if (!state.taskId) return;
        try {
            const task = await loadTask(state.taskId);
            renderProgress(task);
            if (terminalStatuses.has(task.status)) {
                if (Array.isArray(task.items) && task.items.length) renderResults(task.items);
                else if (task.status === "failed") showError(task.error_message || "采集任务失败", false);
                else showEmpty(task.error_message || "任务已结束，但没有解析到结果。");
                api.announce(`任务 #${task.id}：${statusLabels[task.status] || task.status}`, task.status === "failed" ? "error" : "success");
                return;
            }
            state.pollTimer = window.setTimeout(pollTask, 900);
        } catch (error) {
            showError(api.errorMessage(error, "无法读取任务进度，请稍后重试。"), false);
        }
    }

    function renderTaskDialog(task) {
        if (!taskDialog) return;
        api.qs("[data-task-dialog-title]", taskDialog).textContent = `采集任务 #${task.id}`;
        api.qs("[data-task-dialog-summary]", taskDialog).textContent = `${task.source_name || "未知来源"} · ${task.rule_name || "规则已删除"} · ${task.keyword}`;
        const status = api.qs("[data-task-dialog-status]", taskDialog);
        status.textContent = statusLabels[task.status] || task.status;
        status.className = `v02-status ${task.status === "success" ? "enabled" : ["running", "partial"].includes(task.status) ? "warning" : "disabled"}`;
        api.qs("[data-task-dialog-progress]", taskDialog).textContent = `${Number(task.progress || 0)}%`;
        const track = api.qs("[data-task-dialog-track]", taskDialog);
        track.setAttribute("aria-valuenow", String(Number(task.progress || 0)));
        track.querySelector("span").style.width = `${Number(task.progress || 0)}%`;
        api.qs("[data-task-dialog-logs]", taskDialog).innerHTML = (task.logs || []).map((item) => `<article class="task-log ${api.escapeHtml(item.level)}"><time>${api.escapeHtml(item.created_at || "")}</time><b>${api.escapeHtml(item.step || "执行")}</b><p>${api.escapeHtml(item.message || "")}</p></article>`).join("") || "<p>暂无日志</p>";
        api.qs("[data-task-dialog-results]", taskDialog).innerHTML = (task.items || []).map((item) => `<a href="${api.escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer"><b>${api.escapeHtml(item.title)}</b><small>${api.escapeHtml(item.source_name || "未知来源")}</small></a>`).join("") || "<p>暂无结果</p>";
    }

    async function openTask(taskId) {
        if (!taskDialog) return;
        taskDialog.showModal();
        try { renderTaskDialog(await loadTask(taskId)); }
        catch (error) { api.qs("[data-task-dialog-logs]", taskDialog).innerHTML = `<p role="alert">${api.escapeHtml(api.errorMessage(error))}</p>`; }
    }

    async function runTaskAction(taskId, action, button) {
        if (action === "cancel" && !window.confirm("确认取消该采集任务？已经保存的结果不会删除。")) return;
        api.setBusy(button, true, action === "retry" ? "正在重试…" : "正在取消…");
        try {
            const data = await api.fetchJson(`/admin/lookout/tasks/${taskId}/${action}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
            api.announce(data.message);
            if (Number(taskId) === state.taskId) pollTask();
            else window.setTimeout(() => window.location.reload(), 450);
        } catch (error) { api.announce(api.errorMessage(error), "error"); }
        finally { api.setBusy(button, false); }
    }

    ruleSelect?.addEventListener("change", updateRuleContext);
    taskType?.addEventListener("change", updateTaskType);
    pageSizeInput?.addEventListener("input", () => { pageSizeInput.dataset.edited = "true"; });
    updateRuleContext();
    updateTaskType();

    selectAll?.addEventListener("change", () => {
        state.selected.clear();
        if (selectAll.checked) state.items.forEach((item) => state.selected.add(String(item.id)));
        updateSelection();
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = api.qs("button[type='submit']", form);
        const keyword = keywordInput.value.trim();
        if (!keyword) { keywordInput.focus(); return api.announce("请输入采集关键词", "error"); }
        if (!ruleSelect?.value) return api.announce("当前没有可用采集规则", "error");
        const body = new URLSearchParams();
        body.set("keyword", keyword);
        body.set("rule_id", ruleSelect.value);
        body.set("task_type", taskType?.value || "single");
        body.set("page", pageInput?.value || "1");
        body.set("pages", taskType?.value === "batch" ? pagesInput?.value || "1" : "1");
        body.set("page_size", pageSizeInput?.value || "12");
        body.set("_xsrf", api.xsrfToken());
        api.setBusy(button, true, "正在创建…");
        showLoading();
        updatePipeline("result", ["query", "rule"]);
        try {
            const data = await api.fetchJson(form.action, {method: "POST", headers: {"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}, body: body.toString()});
            state.taskId = Number(data.run_id);
            api.announce(data.message || `采集任务 #${state.taskId} 已创建`);
            pollTask();
        } catch (error) { showError(api.errorMessage(error, "采集任务创建失败，请检查规则后重试。")); }
        finally { api.setBusy(button, false); }
    });

    importButton?.addEventListener("click", async () => {
        const ids = Array.from(state.selected);
        if (!ids.length) return;
        api.setBusy(importButton, true, "正在入仓…");
        try {
            const data = await api.fetchJson("/admin/warehouse/import", {method: "POST", headers: {"Content-Type": "application/json;charset=UTF-8"}, body: JSON.stringify({result_ids: ids})});
            api.announce(data.message || `已保存 ${ids.length} 条结果到数据仓库`);
            updatePipeline("warehouse", ["query", "rule", "result"]);
        } catch (error) { api.announce(api.errorMessage(error, "入仓失败，请稍后重试"), "error"); }
        finally { api.setBusy(importButton, false); updateSelection(); }
    });

    api.qsa("[data-task-open]").forEach((button) => button.addEventListener("click", () => openTask(button.dataset.taskOpen)));
    api.qsa("[data-task-action]").forEach((button) => button.addEventListener("click", () => runTaskAction(button.dataset.taskId, button.dataset.taskAction, button)));
    api.qsa("[data-task-dialog-close]", taskDialog).forEach((button) => button.addEventListener("click", () => taskDialog.close()));
})();
