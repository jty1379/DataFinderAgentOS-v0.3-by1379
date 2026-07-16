(function () {
    "use strict";

    const root = document.querySelector("[data-user-workspace]");
    const app = window.DataFinderApp;
    const sse = window.DataFinderSSE;
    const cards = window.DataFinderCards;
    if (!root || !app || !sse || !cards) return;

    const $ = (selector, scope = root) => app.qs(selector, scope);
    const $$ = (selector, scope = root) => app.qsa(selector, scope);
    const rail = $("[data-task-rail]");
    const scrim = $("[data-workspace-scrim]");
    const welcome = $("[data-workspace-welcome]");
    const stream = $("[data-message-stream]");
    const dialogue = $("[data-dialogue-area]");
    const form = $("[data-question-composer]");
    const input = $("[data-question-input]");
    const sendButton = $("[data-send-button]");
    const modelSelect = $("[data-model-select]");
    const title = $("[data-conversation-title]");
    const command = $("[data-employee-command]");
    const commandButtons = $$('[data-employee-id]', command);
    const activeEmployee = $("[data-active-employee]");
    const activeEmployeeName = $("[data-active-employee-name]");
    const historyList = $("[data-history-list]");
    const historyEmpty = $("[data-history-empty]");
    let conversationId = null;
    let employeeId = null;
    let employeeMention = "";
    let commandIndex = 0;
    let loading = false;

    function closeRail() {
        rail.classList.remove("open");
        scrim.classList.remove("show");
    }

    $("[data-rail-open]").addEventListener("click", () => {
        rail.classList.add("open");
        scrim.classList.add("show");
    });
    $("[data-rail-close]").addEventListener("click", closeRail);
    scrim.addEventListener("click", closeRail);

    function setCommandIndex(index) {
        if (!commandButtons.length) return;
        commandIndex = (index + commandButtons.length) % commandButtons.length;
        commandButtons.forEach((button, current) => button.classList.toggle("active", current === commandIndex));
        commandButtons[commandIndex].scrollIntoView({block: "nearest"});
    }

    function setCommandVisible(visible) {
        command.hidden = !visible || commandButtons.length === 0;
        if (!command.hidden) setCommandIndex(0);
    }

    function resizeInput() {
        input.style.height = "auto";
        input.style.height = `${Math.min(180, input.scrollHeight)}px`;
    }

    function selectEmployee(button, keepQuestion = false) {
        employeeId = Number(button.dataset.employeeId || button.dataset.starterEmployee || 0) || null;
        employeeMention = button.dataset.employeeMention || button.dataset.starterMention || "";
        activeEmployee.hidden = !employeeId;
        activeEmployeeName.textContent = employeeMention ? `@${employeeMention}` : "";
        if (!keepQuestion) {
            const text = input.value.replace(/^\s*[/@][^\s]*\s*/, "");
            input.value = `@${employeeMention} ${text}`;
            resizeInput();
        }
        setCommandVisible(false);
        input.focus();
    }

    commandButtons.forEach((button) => button.addEventListener("click", () => selectEmployee(button)));
    $$('[data-starter-employee]').forEach((button) => button.addEventListener("click", () => {
        selectEmployee(button);
        input.scrollIntoView({behavior: "smooth", block: "center"});
    }));
    $("[data-clear-employee]").addEventListener("click", () => {
        employeeId = null;
        employeeMention = "";
        activeEmployee.hidden = true;
        input.value = input.value.replace(/^\s*[/@][^\s]+\s*/, "");
        input.focus();
    });

    input.addEventListener("input", () => {
        resizeInput();
        const trimmed = input.value.trimStart();
        setCommandVisible(trimmed === "@" || trimmed === "/" || /^[/@][^\s]*$/.test(trimmed));
        if (employeeId && !trimmed.startsWith(`@${employeeMention}`) && !trimmed.startsWith(`/${employeeMention}`)) {
            employeeId = null;
            employeeMention = "";
            activeEmployee.hidden = true;
        }
    });
    input.addEventListener("keydown", (event) => {
        if (!command.hidden && ["ArrowDown", "ArrowUp"].includes(event.key)) {
            event.preventDefault();
            setCommandIndex(commandIndex + (event.key === "ArrowDown" ? 1 : -1));
            return;
        }
        if (!command.hidden && event.key === "Enter") {
            event.preventDefault();
            selectEmployee(commandButtons[commandIndex]);
            return;
        }
        if (!command.hidden && event.key === "Escape") {
            event.preventDefault();
            setCommandVisible(false);
            return;
        }
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    function beginMessages() {
        welcome.hidden = true;
        stream.classList.add("active");
    }

    function textNode(tag, className, value) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        element.textContent = value;
        return element;
    }

    function messageCard(message) {
        let data = message.metadata?.data;
        if (!data) {
            try {
                data = JSON.parse(message.content);
            } catch (_) {
                data = {type: "text", data: {text: message.content || "暂无卡片数据"}};
            }
        }
        return cards.render(data);
    }

    function appendMessage(message, temporary = false) {
        beginMessages();
        const wrapper = document.createElement("article");
        wrapper.className = `chat-message ${message.role || "assistant"}`;
        if (temporary) wrapper.dataset.temporary = "1";
        const avatar = textNode("span", "message-avatar", message.role === "user" ? "我" : "DF");
        const content = document.createElement("div");
        content.className = `message-content${message.content_type === "error" ? " error" : ""}`;
        if (temporary) {
            const typing = document.createElement("span");
            typing.className = "typing-indicator";
            typing.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
            content.append(typing);
        } else if (message.content_type === "card") {
            content.append(messageCard(message));
        } else {
            content.textContent = message.content || "";
        }
        if (!temporary && message.metadata) {
            const source = message.metadata.employee || message.metadata.model || "系统服务";
            const usage = message.metadata.usage || {};
            const elapsed = Number(message.metadata.elapsed_seconds ?? (Number(usage.latency_ms || 0) / 1000)).toFixed(2);
            content.append(textNode("small", "message-meta", `响应 ${elapsed}s · ${Number(usage.total_tokens || 0)} token · 服务：${source}`));
        }
        wrapper.append(avatar, content);
        stream.append(wrapper);
        dialogue.scrollTop = dialogue.scrollHeight;
        return wrapper;
    }

    function resetWorkspace() {
        conversationId = null;
        employeeId = null;
        employeeMention = "";
        activeEmployee.hidden = true;
        title.textContent = "新建问数任务";
        stream.replaceChildren();
        stream.classList.remove("active");
        welcome.hidden = false;
        $$(".history-item", historyList).forEach((item) => item.classList.remove("active"));
        input.value = "";
        resizeInput();
        input.focus();
        closeRail();
    }
    $("[data-new-conversation]").addEventListener("click", resetWorkspace);

    function addOrUpdateHistory(conversation) {
        if (!conversation) return;
        historyEmpty.classList.add("hidden");
        let button = $(`[data-conversation-id="${conversation.id}"]`, historyList);
        if (!button) {
            button = document.createElement("button");
            button.type = "button";
            button.className = "history-item";
            button.dataset.conversationId = conversation.id;
            button.innerHTML = '<i class="layui-icon layui-icon-file-b"></i><span><b></b><small>刚刚 · 2 条</small></span>';
            button.addEventListener("click", () => loadConversation(button));
            historyList.prepend(button);
        }
        $("b", button).textContent = conversation.title;
        $$(".history-item", historyList).forEach((item) => item.classList.toggle("active", item === button));
        title.textContent = conversation.title;
    }

    async function loadConversation(button) {
        if (loading) return;
        closeRail();
        $$(".history-item", historyList).forEach((item) => item.classList.toggle("active", item === button));
        stream.replaceChildren();
        appendMessage({role: "assistant"}, true);
        try {
            const data = await app.request(`/api/conversations/${button.dataset.conversationId}`);
            stream.replaceChildren();
            conversationId = data.conversation.id;
            title.textContent = data.conversation.title;
            modelSelect.value = data.conversation.model_id || modelSelect.value;
            employeeId = data.conversation.employee_id || null;
            employeeMention = "";
            activeEmployee.hidden = true;
            data.messages.forEach((message) => appendMessage(message));
        } catch (error) {
            stream.replaceChildren();
            appendMessage({role: "assistant", content_type: "error", content: app.errorMessage(error, "加载会话失败")});
        }
    }
    $$(".history-item", historyList).forEach((button) => button.addEventListener("click", () => loadConversation(button)));

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message || loading) return;
        loading = true;
        app.setBusy(sendButton, true, "处理中…");
        appendMessage({role: "user", content_type: "text", content: message});
        const pending = appendMessage({role: "assistant"}, true);
        let reply = {role: "assistant", content_type: "text", content: "", metadata: {}};
        input.value = "";
        resizeInput();
        setCommandVisible(false);
        try {
            await sse.stream("/api/chat/stream", {
                method: "POST",
                json: {message, conversation_id: conversationId, model_id: modelSelect.value || null, employee_id: employeeId},
                onEvent: ({event: eventName, data}) => {
                    if (eventName === "delta") {
                        reply.content += data.text || "";
                        const target = pending.querySelector(".message-content");
                        target.classList.remove("error");
                        target.textContent = reply.content;
                    } else if (eventName === "card") {
                        reply = data;
                    } else if (eventName === "done") {
                        const usage = data.usage || {};
                        reply.metadata = {...(reply.metadata || {}), usage: {total_tokens: usage.total_tokens || 0}, elapsed_seconds: usage.elapsed_seconds || 0, employee: usage.source};
                        if (data.conversation) {
                            conversationId = data.conversation.id;
                            addOrUpdateHistory(data.conversation);
                        }
                    }
                }
            });
            pending.remove();
            appendMessage(reply);
        } catch (error) {
            pending.remove();
            if (error.details?.conversation_id) conversationId = error.details.conversation_id;
            appendMessage({role: "assistant", content_type: "error", content: app.errorMessage(error, "问数服务暂时不可用")});
        } finally {
            loading = false;
            app.setBusy(sendButton, false);
            input.focus();
        }
    });
})();
