/** @odoo-module **/
/**
 * 使用者 2026-11-16：內部使用不需要點數／儲值／帳單 → lab 前台隱藏財務入口（模板部分在 lab_no_billing.xml）。
 * 只是外觀；扣款本身由後端 _lab_disable_charging 關掉（方案 0 元、不試用、扣款排程停用）。
 */
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { router } from "@woow_paas_platform/paas/core/router";
import { Sidebar } from "@woow_paas_platform/paas/layout/sidebar/Sidebar";
import { BottomNav } from "@woow_paas_platform/paas/layout/bottom_nav/BottomNav";
import { DashboardPage } from "@woow_paas_platform/paas/pages/dashboard/DashboardPage";
import { WorkspaceDetailPage } from "@woow_paas_platform/paas/pages/workspace/WorkspaceDetailPage";
import { SubscriptionBadge } from "@woow_paas_platform/paas/components/subscription/SubscriptionBadge";

const isFinanceItem = (item) => typeof item.path === "string" && item.path.startsWith("billing");

// 側欄：「財務」分區標題＋帳單／發票／儲值商店
patch(Sidebar.prototype, {
    setup() {
        super.setup(...arguments);
        this.navItems = this.navItems.filter(
            (item, i, all) => !isFinanceItem(item) && !(item.section && all[i + 1] && isFinanceItem(all[i + 1]))
        );
    },
});

// 手機底欄：帳單
patch(BottomNav.prototype, {
    setup() {
        super.setup(...arguments);
        this.navItems = this.navItems.filter((item) => !isFinanceItem(item));
    },
});

// 總覽：「帳單」卡（剩餘點數、本期用量、下期帳單）
patch(DashboardPage.prototype, {
    get statCards() {
        return super.statCards.filter((card) => card.icon !== "account_balance_wallet");
    },
});

// 工作區：「預估費用 N 點/月」統計卡
patch(WorkspaceDetailPage.prototype, {
    get computedStats() {
        return super.computedStats.filter((stat) => stat.icon !== "payments");
    },
});

// 試用徽章：不試用、不收費，沒有「試用中」這回事（舊的試用訂閱一律顯示成「使用中」）
patch(SubscriptionBadge.prototype, {
    get label() {
        const sub = this.props.subscription;
        return sub && sub.state === "in_progress" && sub.is_trial ? _t("Active") : super.label;
    },
    get badgeClass() {
        const sub = this.props.subscription;
        return sub && sub.state === "in_progress" && sub.is_trial ? "o_woow_sub_badge--active" : super.badgeClass;
    },
});

// 帳單、發票、儲值、交易紀錄、付款方式的網址（含通知或舊書籤直接開）一律導回總覽，比照上游 project／LLM 的外觀閘門
const BILLING_ROUTE_NAMES = new Set([
    "billing", "billing-topup", "billing-invoices", "billing-invoice-detail",
    "billing-subscriptions", "billing-transactions",
    "settings-payment-methods", "settings-payment-methods-add",
]);
const applyLlmGate = router._applyLlmGate;
router._applyLlmGate = function () {
    applyLlmGate.call(this);
    if (BILLING_ROUTE_NAMES.has(this.current)) {
        this.current = "dashboard";
        this.params = {};
        if (window.location.hash !== "#/dashboard") {
            window.location.hash = "#/dashboard";
        }
        this._currentHash = "#/dashboard";
    }
};
