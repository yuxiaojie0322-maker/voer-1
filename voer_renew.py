#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voer_renew.py — Voer.host 免费服务器"看广告续签"自动化脚本

原理：voer.host 免费档服务器每会话 4 小时，可在服务器详情页通过观看 Google
激励广告（rewarded ads）续签 —— 3 个广告 = +4 小时，每个 UTC 日最多 4 次
(=16 小时)，每个会话最多 4 次。广告播放器是站点内嵌 iframe /voer-ads-api.html。

本脚本用 Playwright 驱动真实 Chromium（带头窗口，保证 Cloudflare Turnstile
与 Google 广告能正常通过），完成：登录 → 打开服务器详情 → 点“Watch Ads” →
等待 3 个广告依次播完并被服务端验证 → 自动结算 +4 小时。

用法：
    python voer_renew.py run                 # 续签一次（3 个广告 +4h），默认动作
    python voer_renew.py run --server 名称    # 指定要续签的服务器（不指定则用第一台）
    python voer_renew.py status              # 只打印服务器列表与可续签状态，不动作
    python voer_renew.py probe               # 登录后把关键页面文本存盘（调试/反馈用）

可选参数：
    --config config.json     指定配置文件（默认读取同目录 config.json）
    --profile-dir DIR        Chromium 用户数据目录（持久化登录态，默认同目录 .profile）
    --headless               无头模式（Google 广告大概率拒绝投放，不推荐）
    --timeout-min N          单次广告最长等待分钟数（默认 10）
    --debug                  保留浏览器现场 & 打印更多日志

首次运行：
    1. pip install playwright &&  playwright install chromium
    2. 编辑 config.json 填入账号密码
    3. python voer_renew.py run
    4. 弹出浏览器后若出现 Cloudflare 人机验证，手动勾选复选框 / 完成验证，
       脚本会自动继续（登录按钮会从禁用变为可点）。
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# 常量（来自 voer.host 前端 i18n 字符串，站点改版时需同步更新）
# ---------------------------------------------------------------------------
BASE_URL = "https://voer.host"
LOGIN_URL = BASE_URL + "/login"
PANEL_URL = BASE_URL + "/panel"
MAX_EXTENSIONS_PER_UTC_DAY = 4      # “A server can be extended up to 4 times per UTC day and per session.”
ADS_PER_EXTENSION = 3               # “Each extension adds 4 hours for 3 rewarded ads.”
HOURS_PER_EXTENSION = 4

# 页面 UI 文案（英文；脚本按这些关键词定位元素）
TXT_WATCH_ADS = "Watch Ads"
TXT_EXTEND_NOW = "Extend Now"
TXT_EXTENSIONS_TODAY = "Extensions today"
TXT_TIME_REMAINING = "Time Remaining"
TXT_ALL_VERIFIED = "All ads verified"
TXT_PROGRESS_RESET = "Progress reset"
TXT_CLOSE_GATE = "Close ad gate"
TXT_OPEN_PLAYER = "Open ad player"

# 广告播放器 iframe 特征
PLAYER_IFRAME_TITLE = "Rewarded ad player"
PLAYER_IFRAME_SRC = "voer-ads-api.html"

# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def utc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_config(cfg_path: str) -> dict:
    cfg = {"email": "", "password": "", "server_name": None}
    if cfg_path and os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    # 允许环境变量覆盖（对定时任务/CI 更安全）
    cfg.setdefault("email", os.environ.get("VOER_EMAIL", ""))
    cfg.setdefault("password", os.environ.get("VOER_PASS", ""))
    if not cfg.get("email") or not cfg.get("password"):
        log("!! 缺少账号密码：请在 config.json 填写 email/password，")
        log("   或设置环境变量 VOER_EMAIL / VOER_PASS")
        sys.exit(2)
    return cfg


def write_probe(tag: str, text: str):
    fn = f"probe_{tag}_{utc_today()}_{int(time.time())}.txt"
    with open(fn, "w", encoding="utf-8") as f:
        f.write(text)
    log(f"probe: 已保存 {fn} ({len(text)} chars)")


# ---------------------------------------------------------------------------
# 浏览器与登录
# ---------------------------------------------------------------------------
class VoerRenewer:
    def __init__(self, cfg: dict, args):
        self.cfg = cfg
        self.args = args
        self.profile_dir = args.profile_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".profile")
        self.timeout_min = float(args.timeout_min or 10)

    # ---- 浏览器 ----
    def open_browser(self, pw):
        """带头启动 Chromium + 持久化 profile（登录态跨次保存）。"""
        launch_args = ["--lang=en-US"]
        if self.args.headless:
            launch_args.append("--headless=new")
        ctx = pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=self.args.headless,
            args=launch_args,
            viewport={"width": 1400, "height": 950},
            locale="en-US",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"),
            proxy={"server": self.args.proxy} if self.args.proxy else None,
        )
        self.ctx = ctx
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.page.set_default_timeout(30_000)
        return self.page

    # ---- 登录（含 Turnstile）----
    def ensure_login(self):
        page = self.page
        log("打开登录页 …")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")

        # 关闭隐私弹窗（klaro）
        try:
            btn = page.get_by_role("button", name="Accept")
            if btn.count() and btn.is_visible():
                btn.click()
                log("已接受 Cookie 弹窗")
        except Exception:
            pass

        # 已登录则直接跳面板
        page.goto(PANEL_URL, wait_until="domcontentloaded")
        if "/login" not in page.url:
            log(f"已登录，直接进入面板：{page.url}")
            return

        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.locator("#login-email").fill(self.cfg["email"])
        page.locator("#login-password").fill(self.cfg["password"])
        log("账号密码已填写，等待 Turnstile 验证 …")

        submit = page.get_by_role("button", name="Sign in")
        deadline = time.time() + 300  # 最多等 5 分钟让人手工完成验证码
        while time.time() < deadline:
            if submit.is_enabled():
                break
            time.sleep(2)
        if not submit.is_enabled():
            write_probe("login_stuck", page.locator("body").inner_text())
            log("!! Turnstile 验证长时间未通过。请在弹出的浏览器窗口里勾选/完成")
            log("   Cloudflare 验证（若出现拼图等挑战也手动完成），然后按回车继续 …")
            input("   完成验证后按 Enter 继续 …")
        if not submit.is_enabled():
            log("!! 验证仍未通过，中止。可重跑脚本（登录态会保留）。")
            sys.exit(3)

        submit.click()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(3)
        if "/login" in page.url:
            body = page.locator("body").inner_text()
            write_probe("login_failed", body)
            log("!! 登录似乎失败，页面仍停留在 /login。请检查账号密码是否正确、")
            log("   是否需要邮箱验证，或在浏览器里手动登录一次。")
            sys.exit(4)
        log("登录成功")

    # ---- 面板内 API 辅助（利用页面自身 cookie 发请求）----
    def api_get(self, url: str) -> dict:
        return self.page.evaluate(
            """async (u) => {
                const r = await fetch(u, { credentials: 'include', headers: {'Accept':'application/json'} });
                return { status: r.status, body: await r.json().catch(()=>null) };
            }""", url)

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def get_servers(self) -> list:
        """返回服务器列表。字段名以实际返回为准。"""
        res = self.api_get("/api/servers")
        data = res.get("body")
        servers = []
        if isinstance(data, list):
            servers = data
        elif isinstance(data, dict):
            servers = data.get("servers") or data.get("data") or []
        return servers

    def print_status(self):
        servers = self.get_servers()
        if not servers:
            log("没有查到服务器（字段结构未知，probe 模式可帮助定位）。")
            write_probe("servers_api", json.dumps(self.api_get("/api/servers"), ensure_ascii=False, indent=2))
            return
        log(f"共 {len(servers)} 台服务器：")
        for s in servers:
            sid = s.get("id", "?")
            name = s.get("name") or s.get("minecraftName") or s.get("gameName") or "?"
            status = s.get("status", "?")
            ext_today = s.get("extensionsToday", s.get("extensions_today", "?"))
            remaining_s = s.get("timeRemainingMs", s.get("timeRemaining", "?"))
            log(f"  - id={sid}  name={name}  status={status}  extensionsToday={ext_today}  timeLeft={remaining_s}")

    def pick_server_id(self) -> str:
        servers = self.get_servers()
        if not servers:
            log("!! 服务器列表为空或结构未知。请先用 probe 模式反馈，或手动打开服务器页。")
            sys.exit(5)
        if self.args.server:
            for s in servers:
                nm = s.get("name") or ""
                if self.args.server.lower() in nm.lower():
                    return str(s.get("id"))
            log(f"!! 没有找到名字包含 '{self.args.server}' 的服务器。")
            sys.exit(6)
        return str(servers[0].get("id"))

    # ------------------------------------------------------------------
    # 看广告续签
    # ------------------------------------------------------------------
    def extend_once(self, server_id: str) -> bool:
        page = self.page
        url = f"{BASE_URL}/panel/server/{server_id}"
        log(f"打开服务器详情页 {url}")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(3)

        body_text = lambda: page.locator("body").inner_text()

        # 检查"今日续签次数"是否已满
        m = re.search(r"Extensions today\s*(\d+)\s*/\s*(\d+)", body_text())
        if m:
            used, total = int(m.group(1)), int(m.group(2))
            log(f"今日已续签 {used}/{total} 次")
            if used >= total:
                log("!! 已达到今日续签上限，无需继续。")
                return False
            if used >= MAX_EXTENSIONS_PER_UTC_DAY:
                log(f"!! 已达到脚本设定的每日上限 {MAX_EXTENSIONS_PER_UTC_DAY} 次。")
                return False
        else:
            log("(未在页面找到 'Extensions today' 计数，继续尝试)")

        # 点击 "Watch Ads"（免费档）按钮打开续签弹窗
        clicked = False
        for name in (TXT_WATCH_ADS, TXT_EXTEND_NOW):
            b = page.get_by_role("button", name=name)
            if b.count() and b.is_visible():
                log(f"点击按钮: {name}")
                b.click()
                clicked = True
                break
        if not clicked:
            write_probe("no_watch_ads", body_text())
            log("!! 没找到 'Watch Ads / Extend Now' 按钮。已保存页面快照 probe_no_watch_ads*.txt，")
            log("   请把它发给我以便修正选择器。")
            return False
        time.sleep(3)

        # 等待弹窗出现（可能出现 "Watch Ads to Extend" 标题）
        gate_visible = self.wait_text(["Watch Ads to Extend", "Extend Session", "rewarded ads required", "Open ad player"], timeout=30)
        if not gate_visible:
            write_probe("no_gate", body_text())
            log("!! 续签弹窗未出现。已保存快照 probe_no_gate*.txt。")
            return False

        # 主循环：等待 3 个广告依次被验证
        seen = set()
        all_done = False
        start_wait = time.time()
        while time.time() - start_wait < self.timeout_min * 60:
            txt = body_text()

            # 播放器 iframe 是否存在
            frame = self.find_player_frame()

            m2 = re.search(r"Watching ad (\d+) of (\d+)", txt)
            if m2:
                cur, need = int(m2.group(1)), int(m2.group(2))
                if need and (cur, need) not in seen:
                    seen.add((cur, need))
                    log(f"进度: 第 {cur}/{need} 个广告（已验证 {cur - 1} 个）")

            if TXT_ALL_VERIFIED in txt:
                log("检测到 'All ads verified. Starting your 4 hour session...'")
                all_done = True
                break

            if "watch all 3 ads again" in txt.lower() or TXT_PROGRESS_RESET in txt:
                log("!! 广告进度被重置（可能需要更“人工”的播放环境）。继续尝试…")

            # 缺帧时尝试打开独立播放器
            if frame is None and TXT_OPEN_PLAYER in txt:
                b = page.get_by_role("button", name=TXT_OPEN_PLAYER)
                if b.count() and b.is_visible():
                    log("内嵌播放器不可用，尝试打开独立播放器窗口")
                    b.click()
                    time.sleep(3)
                    continue

            time.sleep(5)

        if all_done:
            log("三个广告已全部验证，等待结算 …")
            time.sleep(8)
            # 结算后刷新页面确认续签结果
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(3)
            m3 = re.search(r"Extensions today\s*(\d+)\s*/\s*(\d+)", body_text())
            log(f"续签完成。当前页面显示 Extensions today: {m3.group(0) if m3 else '?'}（+4h）")
            return True

        write_probe("extend_timeout", body_text())
        log("!! 等待广告超时。已保存快照 probe_extend_timeout*.txt。")
        log("   常见原因：Google 无广告可投（地区/库存）、严格广告过滤、或无头模式被识别。")
        return False

    def wait_text(self, needles: list, timeout: int = 30) -> bool:
        page = self.page
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                txt = page.locator("body").inner_text(timeout=3000)
            except Exception:
                txt = ""
            for n in needles:
                if n in txt:
                    return True
            time.sleep(1)
        return False

    def find_player_frame(self):
        for frame in self.page.frames:
            src = frame.url or ""
            if PLAYER_IFRAME_SRC in src or "voer-ads" in src:
                return frame
        return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Voer.host 看广告续签脚本")
    p.add_argument("action", nargs="?", default="run", choices=["run", "status", "probe"])
    p.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    p.add_argument("--server", default=None, help="服务器名称关键字（默认第一台）")
    p.add_argument("--profile-dir", default=None)
    p.add_argument("--headless", action="store_true")
    p.add_argument("--timeout-min", default=10, help="单次续签最长等待分钟数")
    p.add_argument("--proxy", default=None,
                   help="代理地址，如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7891"
                        "（Clash/v2ray 等本地代理常见端口）")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config(args.config)
    renewer = VoerRenewer(cfg, args)

    with sync_playwright() as pw:
        renewer.open_browser(pw)
        try:
            renewer.ensure_login()

            if args.action == "status":
                renewer.print_status()
                return

            if args.action == "probe":
                renewer.print_status()
                write_probe("panel", renewer.page.locator("body").inner_text())
                return

            # run：默认先查状态，再续签一次
            renewer.print_status()
            sid = renewer.pick_server_id()
            log(f"对服务器 {sid} 执行续签 …")
            ok = renewer.extend_once(sid)
            if ok:
                log("✓ 续签完成：+4 小时。建议每 4 小时运行一次（注意每日 4 次上限）。")
            else:
                log("✗ 本次续签未完成。")
                sys.exit(1)
        finally:
            if not args.debug:
                try:
                    renewer.ctx.close()
                except Exception:
                    pass
            else:
                log("--debug：浏览器保持打开，请手动关闭。")


if __name__ == "__main__":
    main()