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
})();
