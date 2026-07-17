(function () {
    "use strict";

    const root = document.querySelector("[data-user-workspace]");
    const app = window.DataFinderApp;
    const sse = window.DataFinderSSE;
    const cards = window.DataFinderCards;
    const markdown = window.DataFinderMarkdown;
    if (!root || !app || !sse || !cards || !markdown) return;

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
    const stopButton = $("[data-stop-button]");
    const exportButton = $("[data-export-conversation]");
    const deleteButton = $("[data-delete-conversation]");
    const voiceButton = $("[data-voice-toggle]");
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
    let streamController = null;
    let voiceEnabled = window.localStorage.getItem("datafinder-voice") === "1";
    const modelAvailable = Array.from(modelSelect.options).some((option) => Boolean(option.value));

    function stripInternalReasoning(value) {
        return String(value || "")
            .replace(/<(think|analysis|reasoning)(?:\s[^>]*)?>[\s\S]*?<\/\1\s*>/gi, "")
            .replace(/<\/?(?:think|analysis|reasoning)(?:\s[^>]*)?>/gi, "")
            .trim();
    }

    function setConversationActions(enabled) {
        exportButton.disabled = !enabled;
        deleteButton.disabled = !enabled;
    }

    function setGenerating(active) {
        loading = active;
        sendButton.hidden = active;
        stopButton.hidden = !active;
        input.disabled = active;
        modelSelect.disabled = active || !modelAvailable;
        if (active) stopButton.focus({preventScroll: true});
    }

    function updateVoiceButton() {
        voiceButton.setAttribute("aria-pressed", String(voiceEnabled));
        voiceButton.title = voiceEnabled ? "关闭语音播报" : "开启语音播报";
    }

    function speak(text) {
        if (!voiceEnabled || !text || !("speechSynthesis" in window)) return;
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(stripInternalReasoning(text).replace(/[`*_#>-]/g, " ").slice(0, 3000));
        utterance.lang = "zh-CN";
        utterance.rate = 1;
        window.speechSynthesis.speak(utterance);
    }

    updateVoiceButton();
    setConversationActions(false);

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
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;
        if (!command.hidden) {
            event.preventDefault();
            event.stopPropagation();
            setCommandVisible(false);
            input.focus({preventScroll: true});
            return;
        }
        if (rail.classList.contains("open")) {
            event.preventDefault();
            closeRail();
        }
    }, true);

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
        const avatar = document.createElement("span");
        avatar.className = "message-avatar";
        if (message.role === "user") {
            avatar.textContent = "我";
        } else {
            // AI 助手头像使用零界品牌标识。
            avatar.classList.add("is-logo");
            const logo = document.createElement("img");
            logo.src = "/static/img/logo-mark.png";
            logo.alt = "零界";
            logo.className = "message-avatar-logo";
            avatar.append(logo);
        }
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
            content.append(markdown.render(stripInternalReasoning(message.content)));
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

    function appendRecoverableError(error, submission) {
        const wrapper = appendMessage({
            role: "assistant",
            content_type: "error",
            content: app.errorMessage(error, "问数服务暂时不可用，请稍后重试。")
        });
        const recovery = document.createElement("div");
        recovery.className = "message-recovery";
        const retry = textNode("button", "", "重新生成");
        retry.type = "button";
        retry.addEventListener("click", () => submitMessage(submission.message, {...submission, retry: true}));
        recovery.append(retry);
        wrapper.querySelector(".message-content").append(recovery);
    }

    function appendAudio(data) {
        const wrapper = appendMessage({role: "assistant", content_type: "text", content: data.text || "语音结果"});
        const content = wrapper.querySelector(".message-content");
        const url = markdown.safeUrl(data.url || data.audio_url);
        if (url) {
            const audio = document.createElement("audio");
            audio.controls = true;
            audio.preload = "metadata";
            audio.src = url;
            audio.setAttribute("aria-label", data.title || "语音结果播放器");
            content.append(audio);
            if (voiceEnabled) audio.play().catch(() => {});
        } else if (data.text) {
            speak(data.text);
        }
    }

    function resetWorkspace() {
        conversationId = null;
        employeeId = null;
        employeeMention = "";
        activeEmployee.hidden = true;
        title.textContent = "新建问数任务";
        setConversationActions(false);
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
            setConversationActions(true);
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

    voiceButton.addEventListener("click", () => {
        voiceEnabled = !voiceEnabled;
        window.localStorage.setItem("datafinder-voice", voiceEnabled ? "1" : "0");
        if (!voiceEnabled && "speechSynthesis" in window) window.speechSynthesis.cancel();
        updateVoiceButton();
        app.announce(voiceEnabled ? "已开启回答语音播报" : "已关闭回答语音播报", "info");
    });

    exportButton.addEventListener("click", () => {
        if (!conversationId) return;
        window.location.assign(`/api/conversations/${conversationId}/export.pdf`);
    });

    deleteButton.addEventListener("click", async () => {
        if (!conversationId || loading) return;
        if (!window.confirm("删除后无法恢复，确认删除当前会话？")) return;
        const deletedId = conversationId;
        try {
            await app.request(`/api/conversations/${deletedId}`, {method: "DELETE"});
            $(`[data-conversation-id="${deletedId}"]`, historyList)?.remove();
            if (!$(".history-item", historyList)) historyEmpty.classList.remove("hidden");
            resetWorkspace();
            app.announce("会话已删除", "success");
        } catch (error) {
            app.announce(app.errorMessage(error, "删除会话失败"), "error");
        }
    });

    stopButton.addEventListener("click", () => {
        streamController?.abort("user_stop");
        stopButton.disabled = true;
        stopButton.querySelector("span").textContent = "正在停止";
    });

    async function submitMessage(message, submission = null) {
        if (!message || loading) return;
        const request = submission || {
            message,
            model_id: modelSelect.value || null,
            employee_id: employeeId
        };
        setGenerating(true);
        if (!request.retry) appendMessage({role: "user", content_type: "text", content: message});
        const pending = appendMessage({role: "assistant"}, true);
        let reply = {role: "assistant", content_type: "text", content: "", metadata: {}};
        streamController = new AbortController();
        input.value = "";
        resizeInput();
        setCommandVisible(false);
        try {
            await sse.stream("/api/chat/stream", {
                method: "POST",
                signal: streamController.signal,
                json: {message, conversation_id: conversationId, model_id: request.model_id, employee_id: request.employee_id},
                onEvent: ({event: eventName, data}) => {
                    if (eventName === "delta") {
                        reply.content = stripInternalReasoning(reply.content + (data.text || ""));
                        const target = pending.querySelector(".message-content");
                        target.classList.remove("error");
                        target.textContent = reply.content;
                    } else if (eventName === "card") {
                        reply = data;
                    } else if (eventName === "audio") {
                        appendAudio(data);
                    } else if (eventName === "done") {
                        const usage = data.usage || {};
                        reply.metadata = {...(reply.metadata || {}), usage: {total_tokens: usage.total_tokens || 0}, elapsed_seconds: usage.elapsed_seconds || 0, employee: usage.source};
                        if (data.conversation) {
                            conversationId = data.conversation.id;
                            setConversationActions(true);
                            addOrUpdateHistory(data.conversation);
                        }
                    }
                }
            });
            pending.remove();
            appendMessage(reply);
            if (reply.content_type === "text") speak(reply.content);
        } catch (error) {
            pending.remove();
            if (error.name === "AbortError") {
                if (reply.content) appendMessage(reply);
                appendMessage({role: "assistant", content_type: "text", content: "已停止生成。你可以修改问题后重新发送。"});
            } else {
                if (error.details?.conversation_id) {
                    conversationId = error.details.conversation_id;
                    setConversationActions(true);
                }
                appendRecoverableError(error, request);
            }
        } finally {
            streamController = null;
            stopButton.disabled = false;
            stopButton.querySelector("span").textContent = "停止";
            setGenerating(false);
            input.focus();
        }
    }

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message || loading) return;
        await submitMessage(message);
    });
})();
