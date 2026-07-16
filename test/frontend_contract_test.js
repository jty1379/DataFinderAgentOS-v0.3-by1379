"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

global.document = {
    cookie: "_xsrf=test-token",
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({textContent: "", get innerHTML() { return this.textContent; }})
};
global.window = {
    clearTimeout,
    setTimeout,
    DataFinderApp: null,
    layui: null
};

function load(relativePath) {
    const filename = path.join(__dirname, "..", relativePath);
    vm.runInThisContext(fs.readFileSync(filename, "utf8"), {filename});
}

load("app/static/js/app-core.js");
load("app/static/js/sse-client.js");

async function main() {
    const app = window.DataFinderApp;
    const sse = window.DataFinderSSE;

    assert.deepEqual([...sse.EVENTS].sort(), ["audio", "card", "delta", "done", "error", "meta"].sort());
    assert.deepEqual(sse.parseBlock('event: delta\ndata: {"text":"你好"}'), {
        event: "delta",
        data: {text: "你好"},
        id: ""
    });
    assert.equal(sse.parseBlock("event: done\ndata: [DONE]").event, "done");
    assert.throws(
        () => sse.parseBlock('event: status\ndata: {"message":"旧事件"}'),
        (error) => error instanceof app.RequestError && error.code === "INVALID_SSE_EVENT"
    );

    global.fetch = async (_url, options) => {
        assert.equal(options.headers.get("X-Xsrftoken"), "test-token");
        return new Response(JSON.stringify({
            success: true,
            data: {items: [1, 2, 3]},
            message: "ok",
            request_id: "req-success"
        }), {status: 200, headers: {"Content-Type": "application/json"}});
    };
    const result = await app.request("/api/example", {method: "POST", json: {value: 1}});
    assert.deepEqual(result.items, [1, 2, 3]);
    assert.equal(result.request_id, "req-success");

    global.fetch = async () => new Response(JSON.stringify({
        success: false,
        error: {code: "PERMISSION_DENIED", message: "无权执行该操作", request_id: "req-error"}
    }), {status: 403, headers: {"Content-Type": "application/json"}});
    await assert.rejects(
        app.request("/api/denied"),
        (error) => error instanceof app.RequestError
            && error.code === "PERMISSION_DENIED"
            && error.status === 403
            && error.requestId === "req-error"
    );

    process.stdout.write("frontend contract tests passed\n");
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
