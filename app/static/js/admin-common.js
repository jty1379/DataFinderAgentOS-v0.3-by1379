(function () {
    "use strict";

    const app = window.DataFinderApp;
    if (!app) return;

    app.qsa("[data-reserved-action]").forEach((button) => {
        button.addEventListener("click", () => app.announce(button.dataset.reservedAction));
    });

    const accountMenu = app.qs(".admin-account-menu");
    if (accountMenu) {
        document.addEventListener("click", (event) => {
            if (!accountMenu.contains(event.target)) accountMenu.removeAttribute("open");
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") accountMenu.removeAttribute("open");
        });
    }

    const sidebarNav = app.qs(".admin-sidebar-nav");
    const activeLink = app.qs(".admin-nav a.active", sidebarNav || document);
    if (sidebarNav && activeLink) {
        window.requestAnimationFrame(() => {
            const navRect = sidebarNav.getBoundingClientRect();
            const linkRect = activeLink.getBoundingClientRect();
            if (linkRect.top < navRect.top || linkRect.bottom > navRect.bottom) {
                activeLink.scrollIntoView({block: "center"});
            }
        });
    }

    // 兼容现有管理模块名称；实现统一由 DataFinderApp 提供。
    window.DataFinderAdmin = Object.freeze({
        announce: app.announce,
        errorMessage: app.errorMessage,
        escapeHtml: app.escapeHtml,
        fetchJson: app.request,
        qs: app.qs,
        qsa: app.qsa,
        request: app.request,
        responseData: app.responseData,
        setBusy: app.setBusy,
        xsrfToken: app.xsrfToken
    });
})();
