(function () {
    "use strict";

    const api = window.DataFinderAdmin;
    const sse = window.DataFinderSSE;
    if (!api || !sse) return;

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
            await sse.stream("/admin/models/chat", {
                method: "POST",
                signal: controller.signal,
                json: {model_id: Number(modelId.value), message},
                onEvent: ({event: eventName, data}) => {
                    if (eventName === "meta") streamStatus.textContent = data.status || "接收中";
                    else if (eventName === "delta") assistantNode.textContent += String(data.delta || data.text || "");
                    else if (eventName === "done") {
                        applyUsage(data.usage);
                        streamStatus.textContent = data.status || "已完成";
                    }
                    transcript.scrollTop = transcript.scrollHeight;
                }
            });
            api.announce("模型响应完成");
        } catch (error) {
            if (error.name === "AbortError") {
                streamStatus.textContent = "已停止";
                if (!assistantNode.textContent) assistantNode.textContent = "响应已由用户停止。";
                api.announce("已停止模型响应");
            } else {
                streamStatus.textContent = "失败";
                const message = api.errorMessage(error, "模型对话失败");
                assistantNode.textContent += `${assistantNode.textContent ? "\n" : ""}请求失败：${message}`;
                api.announce(message, "error");
            }
        } finally {
            controller = null;
            cancelButton.disabled = true;
            api.setBusy(submitButton, false);
            messageInput.focus();
        }
    });
})();
