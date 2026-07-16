(function () {
    "use strict";

    const admin = window.DataFinderAdmin;
    const qs = admin ? admin.qs : (selector, root = document) => root.querySelector(selector);
    const qsa = admin ? admin.qsa : (selector, root = document) => Array.from(root.querySelectorAll(selector));

    function setupUserBatch() {
        const form = qs("[data-user-batch-form]");
        if (!form) return;

        const selectAll = qs("[data-select-all-users]");
        const items = qsa("[data-user-select]");
        const action = qs("select[name='batch_action']", form);
        const submit = qs("[data-batch-submit]", form);
        const count = qs("[data-selected-count]", form);

        const refresh = () => {
            const selected = items.filter((item) => item.checked).length;
            count.textContent = String(selected);
            submit.disabled = selected === 0 || !action.value;
            if (selectAll) {
                selectAll.checked = items.length > 0 && selected === items.length;
                selectAll.indeterminate = selected > 0 && selected < items.length;
            }
        };

        if (selectAll) {
            selectAll.addEventListener("change", () => {
                items.forEach((item) => { item.checked = selectAll.checked; });
                refresh();
            });
        }
        items.forEach((item) => item.addEventListener("change", refresh));
        action.addEventListener("change", refresh);

        form.addEventListener("submit", (event) => {
            const selected = items.filter((item) => item.checked).length;
            const labels = {enable: "启用", disable: "停用", delete: "删除"};
            if (!selected || !labels[action.value]) {
                event.preventDefault();
                if (admin) admin.announce("请先选择用户和批量操作", "error");
                return;
            }
            if (!window.confirm(`确认批量${labels[action.value]}选中的 ${selected} 个用户？默认超级管理员不会被处理。`)) {
                event.preventDefault();
            }
        });
        refresh();
    }

    function setupPasswordConfirmation() {
        const dialog = qs("#change-admin-password");
        if (!dialog) return;
        const password = qs("input[name='new_password']", dialog);
        const confirmation = qs("input[name='confirm_password']", dialog);
        const validate = () => {
            confirmation.setCustomValidity(password.value === confirmation.value ? "" : "两次输入的新密码不一致");
        };
        password.addEventListener("input", validate);
        confirmation.addEventListener("input", validate);
    }

    function deepClone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function walk(nodes, callback) {
        (nodes || []).forEach((node) => {
            callback(node);
            walk(node.children, callback);
        });
    }

    function setupRolePermissionTrees() {
        const source = qs("#feature-tree-data");
        const forms = qsa("[data-permission-form]");
        if (!source || !forms.length) return;

        let treeData;
        try {
            treeData = JSON.parse(source.textContent || "[]");
        } catch (_) {
            forms.forEach((form) => {
                const container = qs("[data-role-feature-tree]", form);
                container.innerHTML = '<p class="tree-error">权限树数据格式错误，请刷新后重试。</p>';
            });
            return;
        }

        if (!window.layui) return;
        window.layui.use("tree", function () {
            const tree = window.layui.tree;
            forms.forEach((form) => {
                const container = qs("[data-role-feature-tree]", form);
                const submit = qs("[data-permission-submit]", form);
                const treeId = form.dataset.treeId;
                const checkedIds = new Set(qsa("[data-initial-feature-id]", form).map((input) => String(input.value)));
                const disabledIds = new Set();
                const data = deepClone(treeData);

                walk(data, (node) => {
                    node.spread = true;
                    node.checked = checkedIds.has(String(node.id));
                    if (node.disabled) disabledIds.add(String(node.id));
                });

                try {
                    tree.render({
                        elem: `#${container.id}`,
                        id: treeId,
                        data,
                        showCheckbox: true,
                        accordion: false
                    });
                    submit.disabled = false;
                } catch (_) {
                    container.innerHTML = '<p class="tree-error">权限树加载失败，请刷新后重试。</p>';
                    return;
                }

                form.addEventListener("submit", () => {
                    qsa("[data-generated-feature-id]", form).forEach((input) => input.remove());
                    const selected = [];
                    walk(tree.getChecked(treeId), (node) => {
                        const value = String(node.id);
                        if (!disabledIds.has(value) && !selected.includes(value)) selected.push(value);
                    });
                    selected.forEach((value) => {
                        const input = document.createElement("input");
                        input.type = "hidden";
                        input.name = "feature_ids";
                        input.value = value;
                        input.dataset.generatedFeatureId = "true";
                        form.appendChild(input);
                    });
                });
            });
        });
    }

    setupUserBatch();
    setupPasswordConfirmation();
    setupRolePermissionTrees();
})();
