(function () {
    "use strict";

    const URL_PROTOCOLS = new Set(["http:", "https:"]);

    function safeUrl(value) {
        try {
            const url = new URL(String(value || ""), window.location.origin);
            return URL_PROTOCOLS.has(url.protocol) ? url.href : "";
        } catch (_) {
            return "";
        }
    }

    function appendInline(target, source) {
        const pattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\s)]+\))/g;
        let cursor = 0;
        for (const match of source.matchAll(pattern)) {
            if (match.index > cursor) target.append(document.createTextNode(source.slice(cursor, match.index)));
            const token = match[0];
            if (token.startsWith("`")) {
                const code = document.createElement("code");
                code.textContent = token.slice(1, -1);
                target.append(code);
            } else if (token.startsWith("**")) {
                const strong = document.createElement("strong");
                strong.textContent = token.slice(2, -2);
                target.append(strong);
            } else if (token.startsWith("*")) {
                const emphasis = document.createElement("em");
                emphasis.textContent = token.slice(1, -1);
                target.append(emphasis);
            } else {
                const parts = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
                const href = safeUrl(parts?.[2]);
                if (!href) {
                    target.append(document.createTextNode(parts?.[1] || token));
                } else {
                    const link = document.createElement("a");
                    link.textContent = parts[1];
                    link.href = href;
                    link.target = "_blank";
                    link.rel = "noopener noreferrer";
                    target.append(link);
                }
            }
            cursor = match.index + token.length;
        }
        if (cursor < source.length) target.append(document.createTextNode(source.slice(cursor)));
    }

    function render(markdown) {
        const root = document.createElement("div");
        root.className = "safe-markdown";
        const lines = String(markdown || "").replace(/\r\n?/g, "\n").split("\n");
        let index = 0;
        while (index < lines.length) {
            const line = lines[index];
            if (line.startsWith("```")) {
                const language = line.slice(3).trim();
                const chunks = [];
                index += 1;
                while (index < lines.length && !lines[index].startsWith("```")) chunks.push(lines[index++]);
                if (index < lines.length) index += 1;
                const pre = document.createElement("pre");
                const code = document.createElement("code");
                if (language) code.dataset.language = language.slice(0, 24);
                code.textContent = chunks.join("\n");
                pre.append(code);
                root.append(pre);
                continue;
            }
            const heading = /^(#{1,4})\s+(.+)$/.exec(line);
            if (heading) {
                const element = document.createElement(`h${Math.min(heading[1].length + 2, 6)}`);
                appendInline(element, heading[2]);
                root.append(element);
                index += 1;
                continue;
            }
            if (/^\s*[-*]\s+/.test(line)) {
                const list = document.createElement("ul");
                while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
                    const item = document.createElement("li");
                    appendInline(item, lines[index].replace(/^\s*[-*]\s+/, ""));
                    list.append(item);
                    index += 1;
                }
                root.append(list);
                continue;
            }
            if (/^\s*\d+\.\s+/.test(line)) {
                const list = document.createElement("ol");
                while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
                    const item = document.createElement("li");
                    appendInline(item, lines[index].replace(/^\s*\d+\.\s+/, ""));
                    list.append(item);
                    index += 1;
                }
                root.append(list);
                continue;
            }
            if (line.startsWith("> ")) {
                const quote = document.createElement("blockquote");
                appendInline(quote, line.slice(2));
                root.append(quote);
                index += 1;
                continue;
            }
            if (/^\s*---+\s*$/.test(line)) {
                root.append(document.createElement("hr"));
                index += 1;
                continue;
            }
            if (!line.trim()) {
                index += 1;
                continue;
            }
            const paragraph = document.createElement("p");
            const paragraphLines = [line];
            index += 1;
            while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+|^```|^\s*[-*]\s+|^\s*\d+\.\s+|^>\s+/.test(lines[index])) {
                paragraphLines.push(lines[index++]);
            }
            appendInline(paragraph, paragraphLines.join("\n"));
            root.append(paragraph);
        }
        return root;
    }

    window.DataFinderMarkdown = Object.freeze({render, safeUrl});
})();
