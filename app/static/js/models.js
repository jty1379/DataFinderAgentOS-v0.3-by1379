(function () {
    "use strict";

    const api = window.DataFinderAdmin;
    if (!api) return;

    const cards = api.qsa("[data-model-card]");
    const maxTokens = Math.max(1, ...cards.map((card) => Number(card.dataset.totalTokens) || 0));
    cards.forEach((card) => {
        const bar = api.qs("[data-token-bar]", card);
        const value = Number(card.dataset.totalTokens) || 0;
        if (bar) bar.style.width = value ? `${Math.max(3, Math.round(value / maxTokens * 100))}%` : "0";
    });

    api.qsa("[data-model-form]").forEach((form) => {
        form.addEventListener("submit", () => {
            const button = api.qs("button[type='submit']", form);
            api.setBusy(button, true, "正在保存…");
        });
    });

    const dialog = api.qs("#model-chat");
    const chatForm = api.qs("[data-model-chat-form]");
    if (!dialog || !chatForm) return;

    const title = api.qs("[data-model-chat-title]", dialog);
    const modelId = api.qs("[data-chat-model-id]", dialog);
    const transcript = api.qs("[data-model-transcript]", dialog);
    const messageInput = api.qs("#model-chat-message", dialog);
    const cancelButton = api.qs("[data-cancel-stream]", dialog);
    const streamStatus = api.qs("[data-stream-status]", dialog);
    const promptTokens = api.qs("[data-prompt-tokens]", dialog);
    const completionTokens = api.qs("[data-completion-tokens]", dialog);
    const totalTokens = api.qs("[data-total-tokens]", dialog);
    let controller = null;

    function resetChat(name, id) {
        title.textContent = `模型对话 · ${name}`;
        modelId.value = id;
        transcript.innerHTML = '<div class="v02-feedback"><i class="layui-icon layui-icon-dialogue"></i><h4>发送一条测试消息</h4><p>用于验证模型端点和流式响应，不会写入用户侧历史记录。</p></div>';
        streamStatus.textContent = "未连接";
        promptTokens.textContent = "0";
        completionTokens.textContent = "0";
        totalTokens.textContent = "0";
        messageInput.value = "";
    }

    api.qsa("[data-chat-model]").forEach((button) => {
        button.addEventListener("click", () => resetChat(button.dataset.chatModelName, button.dataset.chatModel));
    });

    function addMessage(role, text = "") {
        const empty = api.qs(".v02-feedback", transcript);
        if (empty) empty.remove();
        const wrapper = document.createElement("div");
        wrapper.className = `model-message ${role}`;
        const label = document.createElement("b");
        label.textContent = role === "user" ? "你" : "模型";
        const content = document.createElement("p");
        content.textContent = text;
        wrapper.append(label, content);
        transcript.appendChild(wrapper);
        transcript.scrollTop = transcript.scrollHeight;
        return content;
    }

    function applyUsage(usage) {
        if (!usage || typeof usage !== "object") return;
        const input = Number(usage.prompt_tokens ?? usage.input_tokens ?? promptTokens.textContent) || 0;
        const output = Number(usage.completion_tokens ?? usage.output_tokens ?? completionTokens.textContent) || 0;
        const total = Number(usage.total_tokens) || input + output;
        promptTokens.textContent = String(input);
        completionTokens.textContent = String(output);
        totalTokens.textContent = String(total);
    }

    function parseEvent(block, assistantNode) {
        const dataLines = block.split(/\r?\n/).filter((line) => line.startsWith("data:"));
        for (const line of dataLines) {
            const raw = line.slice(5).trim();
            if (!raw || raw === "[DONE]") continue;
            let payload;
            try {
                payload = JSON.parse(raw);
            } catch (_) {
                assistantNode.textContent += raw;
                continue;
            }
            if (payload.error) throw new Error(typeof payload.error === "string" ? payload.error : payload.error.message || "模型服务返回错误");
            const delta = payload.delta ?? payload.content ?? payload.choices?.[0]?.delta?.content ?? "";
            if (delta) assistantNode.textContent += String(delta);
            if (payload.usage) applyUsage(payload.usage);
            if (payload.status) streamStatus.textContent = String(payload.status);
        }
        transcript.scrollTop = transcript.scrollHeight;
    }

    cancelButton.addEventListener("click", () => controller?.abort());
    dialog.addEventListener("close", () => controller?.abort());

    chatForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = messageInput.value.trim();
        if (!message || !modelId.value) {
            messageInput.focus();
            api.announce("请输入测试消息", "error");
            return;
        }
        const submitButton = api.qs("button[type='submit']", chatForm);
        addMessage("user", message);
        const assistantNode = addMessage("assistant", "");
        controller = new AbortController();
        cancelButton.disabled = false;
        streamStatus.textContent = "连接中";
        api.setBusy(submitButton, true, "生成中…");
        messageInput.value = "";

        try {
            const response = await fetch("/admin/models/chat", {
                method: "POST",
                signal: controller.signal,
                headers: {
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json;charset=UTF-8",
                    "X-Xsrftoken": api.xsrfToken()
                },
                body: JSON.stringify({model_id: Number(modelId.value), message})
            });
            if (!response.ok) {
                const data = await api.responseData(response);
                throw new Error(data.message || `模型请求失败（HTTP ${response.status}）`);
            }
            if (!response.body) throw new Error("浏览器未获得可读取的流式响应");

            streamStatus.textContent = "接收中";
            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");
            let buffer = "";
            while (true) {
                const {value, done} = await reader.read();
                buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
                const blocks = buffer.split(/\r?\n\r?\n/);
                buffer = blocks.pop() || "";
                blocks.forEach((block) => parseEvent(block, assistantNode));
                if (done) break;
            }
            if (buffer.trim()) parseEvent(buffer, assistantNode);
            streamStatus.textContent = "已完成";
            api.announce("模型响应完成");
        } catch (error) {
            if (error.name === "AbortError") {
                streamStatus.textContent = "已停止";
                if (!assistantNode.textContent) assistantNode.textContent = "响应已由用户停止。";
                api.announce("已停止模型响应");
            } else {
                streamStatus.textContent = "失败";
                assistantNode.textContent += `${assistantNode.textContent ? "\n" : ""}请求失败：${error.message || "未知错误"}`;
                api.announce(error.message || "模型对话失败", "error");
            }
        } finally {
            controller = null;
            cancelButton.disabled = true;
            api.setBusy(submitButton, false);
            messageInput.focus();
        }
    });

    // 模型调用统计详情
    const usageStatsDialog = api.qs("#model-usage-stats");
    const usageTitle = api.qs("[data-usage-title]", usageStatsDialog);
    const usageTable = api.qs("[data-usage-table]", usageStatsDialog);
    const filterButtons = api.qsa("[data-filter]", usageStatsDialog);
    let currentModelId = null;
    let currentFilter = "all";

    function renderUsageTable(logs, modelName) {
        if (!logs || logs.length === 0) {
            usageTable.innerHTML = '<div class="v02-feedback"><i class="layui-icon layui-icon-chart"></i><h4>暂无调用记录</h4><p>该模型尚未被调用，或当前筛选条件下没有记录。</p></div>';
            return;
        }

        const table = document.createElement("table");
        table.className = "v02-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>调用用户</th>
                    <th>状态</th>
                    <th>输入Token</th>
                    <th>输出Token</th>
                    <th>总Token</th>
                    <th>耗时(ms)</th>
                    <th>调用时间</th>
                    <th>错误信息</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        const tbody = table.querySelector("tbody");

        logs.forEach(log => {
            const row = document.createElement("tr");
            row.className = log.success ? "success" : "error";
            row.innerHTML = `
                <td>${log.user_name || "系统"}</td>
                <td><span class="v02-badge ${log.success ? "success" : "error"}">${log.success ? "成功" : "失败"}</span></td>
                <td>${log.prompt_tokens}</td>
                <td>${log.completion_tokens}</td>
                <td>${log.total_tokens}</td>
                <td>${log.latency_ms}</td>
                <td>${log.created_at}</td>
                <td>${log.error_message || "-"}</td>
            `;
            tbody.appendChild(row);
        });

        usageTable.innerHTML = "";
        usageTable.appendChild(table);
    }

    async function loadUsageLogs(modelId, modelName, filter = "all") {
        usageTitle.textContent = `模型调用统计 · ${modelName}`;
        usageTable.innerHTML = '<div class="v02-feedback"><i class="layui-icon layui-icon-loading layui-anim layui-anim-rotate layui-anim-loop"></i><h4>加载中...</h4></div>';

        try {
            const params = new URLSearchParams({model_id: modelId, limit: "50"});
            if (filter === "success") params.append("success", "1");
            if (filter === "failure") params.append("failure", "1");

            const response = await fetch(`/admin/models/usage-logs?${params}`, {
                headers: {"X-Xsrftoken": api.xsrfToken()}
            });
            const data = await api.responseData(response);

            if (!data.ok) {
                throw new Error(data.message || "加载失败");
            }

            renderUsageTable(data.logs, modelName);
        } catch (error) {
            usageTable.innerHTML = `<div class="v02-feedback error"><i class="layui-icon layui-icon-error"></i><h4>加载失败</h4><p>${error.message || "未知错误"}</p></div>`;
            api.announce(error.message || "加载调用统计失败", "error");
        }
    }

    api.qsa("[data-open-usage-stats]").forEach(button => {
        button.addEventListener("click", () => {
            currentModelId = button.dataset.modelId;
            const modelName = button.dataset.modelName;
            currentFilter = "all";
            filterButtons.forEach(btn => btn.setAttribute("aria-pressed", btn.dataset.filter === "all" ? "true" : "false"));
            usageStatsDialog.showModal();
            loadUsageLogs(currentModelId, modelName, currentFilter);
        });
    });

    filterButtons.forEach(button => {
        button.addEventListener("click", () => {
            currentFilter = button.dataset.filter;
            filterButtons.forEach(btn => btn.setAttribute("aria-pressed", btn === button ? "true" : "false"));
            const modelName = usageTitle.textContent.replace("模型调用统计 · ", "");
            loadUsageLogs(currentModelId, modelName, currentFilter);
        });
    });

    // 模型失败日志
    const failureLogsDialog = api.qs("#model-failure-logs");
    const failureTitle = api.qs("[data-failure-title]", failureLogsDialog);
    const failureTable = api.qs("[data-failure-table]", failureLogsDialog);

    function renderFailureTable(logs, modelName) {
        if (!logs || logs.length === 0) {
            failureTable.innerHTML = '<div class="v02-feedback"><i class="layui-icon layui-icon-error"></i><h4>暂无失败记录</h4><p>该模型调用均成功，或尚未被调用。</p></div>';
            return;
        }

        const table = document.createElement("table");
        table.className = "v02-table";
        table.innerHTML = `
            <thead>
                <tr>
                    <th>调用用户</th>
                    <th>输入Token</th>
                    <th>输出Token</th>
                    <th>总Token</th>
                    <th>耗时(ms)</th>
                    <th>调用时间</th>
                    <th>错误信息</th>
                </tr>
            </thead>
            <tbody></tbody>
        `;
        const tbody = table.querySelector("tbody");

        logs.forEach(log => {
            const row = document.createElement("tr");
            row.className = "error";
            row.innerHTML = `
                <td>${log.user_name || "系统"}</td>
                <td>${log.prompt_tokens}</td>
                <td>${log.completion_tokens}</td>
                <td>${log.total_tokens}</td>
                <td>${log.latency_ms}</td>
                <td>${log.created_at}</td>
                <td><span class="error-message">${log.error_message || "-"}</span></td>
            `;
            tbody.appendChild(row);
        });

        failureTable.innerHTML = "";
        failureTable.appendChild(table);
    }

    async function loadFailureLogs(modelId, modelName) {
        failureTitle.textContent = `模型失败日志 · ${modelName}`;
        failureTable.innerHTML = '<div class="v02-feedback"><i class="layui-icon layui-icon-loading layui-anim layui-anim-rotate layui-anim-loop"></i><h4>加载中...</h4></div>';

        try {
            const params = new URLSearchParams({model_id: modelId, failure: "1", limit: "50"});
            const response = await fetch(`/admin/models/usage-logs?${params}`, {
                headers: {"X-Xsrftoken": api.xsrfToken()}
            });
            const data = await api.responseData(response);

            if (!data.ok) {
                throw new Error(data.message || "加载失败");
            }

            renderFailureTable(data.logs, modelName);
        } catch (error) {
            failureTable.innerHTML = `<div class="v02-feedback error"><i class="layui-icon layui-icon-error"></i><h4>加载失败</h4><p>${error.message || "未知错误"}</p></div>`;
            api.announce(error.message || "加载失败日志失败", "error");
        }
    }

    api.qsa("[data-open-failure-logs]").forEach(button => {
        button.addEventListener("click", () => {
            const modelId = button.dataset.modelId;
            const modelName = button.dataset.modelName;
            failureLogsDialog.showModal();
            loadFailureLogs(modelId, modelName);
        });
    });
})();
