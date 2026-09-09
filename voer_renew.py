#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voer_renew.py — Voer.host 免费服务器「看视频增加使用时间」全自动优化版

核心特性与优化：
1. 【Page Visibility 伪装】：深度伪装 document.hidden 与 visibilityState，拦截 blur 事件，
   保证 Google 激励视频广告在后台、最小化或被遮挡时持续顺畅播放，彻底解决广告播放中断与超时问题。
2. 【智能过验证与免密秒登】：集成 Stealth 反指纹；自动模拟点击 Cloudflare Turnstile 复选框；
   登录成功后自动更新并持久化保存 Session（session.json），下次启动零验证码秒进面板。
3. 【主动广告交互与弹窗接管】：深入 iframe 自动识别并点击 Play / Consent / Done / Close 按钮；
   自动捕获与协同 "Open ad player" 弹出的独立播放器窗口（Popup）。
4. 【前置 Geo 诊断与 90 秒防卡看门狗】：在看广告前自动检测 /api/servers/geo-info，若当前节点 IP
   不支持广告立即给出清晰换节点指引；广告播放单步超时 90 秒自动刷新重试，避免死等。
5. 【无人值守守护模式 (--loop)】：全自动循环续签，自动休眠至会话到期前唤醒，满 4 次自动等待次日 UTC 重置。
6. 【多服务器支持 (--all) & 漂亮状态看板】：支持一键续签所有服务器，格式化显示剩余可用时长。
7. 【多渠道消息推送】：支持 Telegram、Server酱、PushPlus、Discord 与自定义 Webhook 通知。
"""

import argparse
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# 常量定义
# ---------------------------------------------------------------------------
BASE_URL = "https://voer.host"
LOGIN_URL = BASE_URL + "/login"
PANEL_URL = BASE_URL + "/panel"
GEO_INFO_URL = BASE_URL + "/api/servers/geo-info"
MAX_EXTENSIONS_PER_UTC_DAY = 4      # 每天最多续签 4 次（每次 4 小时 = 最多 16 小时）
ADS_PER_EXTENSION = 3               # 每次续签观看 3 个广告
HOURS_PER_EXTENSION = 4

# 页面关键词
TXT_WATCH_ADS = "Watch Ads"
TXT_EXTEND_NOW = "Extend Now"
TXT_ALL_VERIFIED = "All ads verified"
TXT_PROGRESS_RESET = "Progress reset"
TXT_OPEN_PLAYER = "Open ad player"

PLAYER_IFRAME_SRC = "voer-ads-api.html"

# ---------------------------------------------------------------------------
# JS 注入补丁：Stealth 反指纹 + Page Visibility 伪装
# ---------------------------------------------------------------------------
STEALTH_JS = """
(() => {
    // 隐藏 navigator.webdriver
    try {
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    } catch(e) {}

    // 伪造 chrome 对象
    window.chrome = window.chrome || {
        app: { isInstalled: false },
        runtime: { PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' } },
        loadTimes: function() {},
        csi: function() {}
    };

    // 伪造语言与插件
    try {
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    } catch(e) {}

    // 修复权限 API
    if (navigator.permissions && navigator.permissions.query) {
        const origQuery = navigator.permissions.query;
        navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                origQuery(parameters)
        );
    }
})();
"""

PAGE_VISIBILITY_JS = """
(() => {
    // 深度伪装页面前台可见性，防止 Google 广告在后台/被遮挡时暂停播放
    try {
        Object.defineProperty(document, 'hidden', { get: () => false, configurable: true });
        Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true });
        Object.defineProperty(document, 'webkitVisibilityState', { get: () => 'visible', configurable: true });
    } catch(e) {}

    // 拦截并阻止 visibilitychange 等暂停信号
    ['visibilitychange', 'webkitvisibilitychange', 'blur', 'pagehide'].forEach(evtName => {
        window.addEventListener(evtName, (e) => {
            e.stopImmediatePropagation();
        }, true);
        document.addEventListener(evtName, (e) => {
            e.stopImmediatePropagation();
        }, true);
    });

    // 恒定窗口有焦点
    window.hasFocus = () => true;
    document.hasFocus = () => true;
})();
"""


# ---------------------------------------------------------------------------
# 日志与工具函数
# ---------------------------------------------------------------------------
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prefix = {
        "INFO": "[INFO]",
        "WARN": "[WARN]",
        "SUCCESS": "[SUCCESS]",
        "ERROR": "[ERROR]",
        "DEBUG": "[DEBUG]"
    }.get(level, f"[{level}]")
    print(f"[{ts}] {prefix} {msg}", flush=True)


def utc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def format_ms(ms) -> str:
    """将毫秒转化为容易阅读的 时:分 格式"""
    try:
        total_seconds = int(ms) // 1000
        if total_seconds <= 0:
            return "已过期"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours}小时{minutes}分"
    except Exception:
        return str(ms)


def load_config(cfg_path: str) -> dict:
    cfg = {
        "email": "",
        "password": "",
        "server_name": None,
        "proxy": None,
        "notify": {}
    }
    if cfg_path and os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            log(f"读取配置文件失败: {e}", "WARN")

    cfg.setdefault("email", os.environ.get("VOER_EMAIL", ""))
    cfg.setdefault("password", os.environ.get("VOER_PASS", ""))
    if os.environ.get("VOER_PROXY"):
        cfg["proxy"] = os.environ.get("VOER_PROXY")

    return cfg


def write_probe(tag: str, text: str):
    fn = f"probe_{tag}_{utc_today()}_{int(time.time())}.txt"
    try:
        with open(fn, "w", encoding="utf-8") as f:
            f.write(text)
        log(f"已保存排查快照: {fn} ({len(text)} 字符)", "DEBUG")
    except Exception as e:
        log(f"保存排查快照失败: {e}", "WARN")


# ---------------------------------------------------------------------------
# 推送通知模块
# ---------------------------------------------------------------------------
def send_notification(cfg: dict, title: str, content: str):
    """支持 Telegram, Server酱, Pushplus, Discord 及通用 Webhook 推送"""
    notify_cfg = cfg.get("notify", {})
    if not notify_cfg:
        return

    # 1. Telegram
    tg_token = notify_cfg.get("tg_bot_token") or os.environ.get("TG_BOT_TOKEN")
    tg_chat_id = notify_cfg.get("tg_chat_id") or os.environ.get("TG_CHAT_ID")
    if tg_token and tg_chat_id:
        try:
            url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
            payload = json.dumps({
                "chat_id": tg_chat_id,
                "text": f"*{title}*\n\n{content}",
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            log("已发送 Telegram 通知", "DEBUG")
        except Exception as e:
            log(f"Telegram 推送失败: {e}", "WARN")

    # 2. Server酱 (SendKey)
    serverchan_key = notify_cfg.get("serverchan_key") or os.environ.get("SERVERCHAN_KEY")
    if serverchan_key:
        try:
            url = f"https://sctapi.ftqq.com/{serverchan_key}.send"
            data = urllib.parse.urlencode({"title": title, "desp": content}).encode("utf-8")
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
            log("已发送 Server酱 通知", "DEBUG")
        except Exception as e:
            log(f"Server酱 推送失败: {e}", "WARN")

    # 3. PushPlus
    pushplus_token = notify_cfg.get("pushplus_token") or os.environ.get("PUSHPLUS_TOKEN")
    if pushplus_token:
        try:
            url = "http://www.pushplus.plus/send"
            payload = json.dumps({"token": pushplus_token, "title": title, "content": content}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            log("已发送 PushPlus 通知", "DEBUG")
        except Exception as e:
            log(f"PushPlus 推送失败: {e}", "WARN")

    # 4. Webhook / Discord
    webhook_url = notify_cfg.get("webhook_url") or os.environ.get("WEBHOOK_URL")
    if webhook_url:
        try:
            payload = json.dumps({"title": title, "content": content, "text": f"{title}\n{content}"}).encode("utf-8")
            req = urllib.request.Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            log("已发送 Webhook 通知", "DEBUG")
        except Exception as e:
            log(f"Webhook 推送失败: {e}", "WARN")


# ---------------------------------------------------------------------------
# 核心续签控制器
# ---------------------------------------------------------------------------
class VoerRenewer:
    def __init__(self, cfg: dict, args):
        self.cfg = cfg
        self.args = args
        self.cdp_mode = False
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.profile_dir = args.profile_dir or os.path.join(self.base_dir, ".profile")
        self.session_file = args.session_file or os.path.join(self.base_dir, "session.json")
        self.timeout_min = float(args.timeout_min or 10)
        self.popup_page = None

    def setup_page_hooks(self, target_page):
        """给页面注入反检测与可见性欺骗补丁，并监听认证相关请求和错误提示"""
        try:
            target_page.add_init_script(STEALTH_JS)
            target_page.add_init_script(PAGE_VISIBILITY_JS)
            target_page.set_default_timeout(30_000)

            # 监听认证相关的响应
            def on_resp(r):
                if any(k in r.url for k in ["/api/auth", "/api/login", "/api/servers"]):
                    try:
                        body_txt = r.text()[:200]
                        log(f"[API 响应 {r.status}] {r.url} -> {body_txt}", "DEBUG")
                    except Exception:
                        log(f"[API 响应 {r.status}] {r.url}", "DEBUG")

            target_page.on("response", on_resp)
        except Exception as e:
            log(f"注入页面钩子警告: {e}", "DEBUG")

    def open_browser(self, pw):
        """启动浏览器，支持 CDP、持久化目录与自动导入 Session"""
        # 1. CDP 模式：直连已打开的 Chrome
        if self.args.cdp:
            self.cdp_mode = True
            log(f"直连真实 Chrome 调试端口: {self.args.cdp}")
            self.browser = pw.chromium.connect_over_cdp(self.args.cdp)
            self.ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
            self.setup_page_hooks(self.page)
            self._listen_popups()
            return self.page

        # 2. 本地独立启动模式
        launch_args = [
            "--lang=en-US",
            "--autoplay-policy=no-user-gesture-required",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-features=IsolateOrigins,site-per-process"
        ]
        if self.args.headless:
            launch_args.append("--headless=new")

        proxy_opt = None
        proxy_url = self.args.proxy or self.cfg.get("proxy")
        # 检查是否传入了有效的 storage_state
        storage_opt = None
        cookie_path = self.args.cookies or (self.session_file if os.path.exists(self.session_file) else None)
        if cookie_path and os.path.exists(cookie_path):
            storage_opt = cookie_path
            log(f"启动时挂载 Session 文件: {cookie_path}", "INFO")

        ctx = pw.chromium.launch_persistent_context(
            self.profile_dir,
            headless=self.args.headless,
            args=launch_args,
            viewport={"width": 1440, "height": 960},
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/128.0.0.0 Safari/537.36"),
            proxy=proxy_opt,
        )
        self.ctx = ctx
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.setup_page_hooks(self.page)

        # 双保险：再执行一次 import_cookies 确保 cookies 和 localStorage 完全生效
        if cookie_path and os.path.exists(cookie_path):
            self.import_cookies(cookie_path)

        self._listen_popups()
        return self.page

    def _listen_popups(self):
        """监听由主页面弹出的新标签页/独立播放器窗口"""
        def on_popup(popup):
            log(f"检测到弹出独立窗口: {popup.url or 'loading...'}")
            self.popup_page = popup
            self.setup_page_hooks(popup)
            popup.on("close", lambda: setattr(self, "popup_page", None))
        self.ctx.on("page", on_popup)

    def import_cookies(self, path: str):
        """导入会话信息 (兼容 Playwright storage_state 格式与纯 Cookie 列表)"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return
            data = json.loads(raw)
            if isinstance(data, dict) and "cookies" in data:
                cookies = data.get("cookies", [])
                if cookies:
                    self.ctx.add_cookies(cookies)
                for origin in data.get("origins", []):
                    items = []
                    for item in origin.get("localStorage", []):
                        if isinstance(item, dict):
                            k, v = item.get("name"), item.get("value")
                        elif isinstance(item, (list, tuple)) and len(item) == 2:
                            k, v = item[0], item[1]
                        else:
                            continue
                        items.append(f"try{{localStorage.setItem({json.dumps(k)}, {json.dumps(v)} );}}catch(e){{}}")
                    if items:
                        self.page.add_init_script("() => {" + "".join(items) + "}")
                log(f"已成功加载并注入 Session ({path})，包含 {len(cookies)} 个 Cookie", "SUCCESS")
            elif isinstance(data, list):
                self.ctx.add_cookies(data)
                log(f"已导入 {len(data)} 个 Cookie ({path})")
        except Exception as e:
            log(f"导入 Session 出现异常: {e}", "WARN")

    def save_session(self):
        """自动保存当前登录态供下次启动零验证码秒登"""
        try:
            self.ctx.storage_state(path=self.session_file)
            log(f"已自动持久化登录 Session -> {self.session_file}", "SUCCESS")
        except Exception as e:
            log(f"保存 Session 失败: {e}", "DEBUG")

    # ------------------------------------------------------------------
    # 智能 Cloudflare Turnstile 与 登录
    # ------------------------------------------------------------------
    def try_solve_turnstile(self) -> bool:
        """尝试自动识别并模拟点击 Turnstile 验证复选框"""
        page = self.page
        found = False
        for frame in page.frames:
            if "challenges.cloudflare.com" in frame.url or "turnstile" in frame.url:
                found = True
                for sel in ["input[type=checkbox]", ".ctp-checkbox-label", "#challenge-stage", "[aria-label*='Cloudflare']", ".cb-lb"]:
                    try:
                        box = frame.locator(sel)
                        if box.count() and box.first.is_visible():
                            log("检测到 Turnstile 验证框，正在模拟鼠标悬停并点击...", "DEBUG")
                            box.first.hover()
                            time.sleep(0.2)
                            box.first.click(delay=120)
                            return True
                    except Exception:
                        pass
        return found

    def check_is_logged_in(self) -> bool:
        """准确检查当前是否处于登录状态（排除 SPA 延迟重定向和未登录表单）"""
        page = self.page
        if "/login" in page.url:
            return False
        try:
            # 检查是否有登录输入框
            if page.locator("#login-email, input[type='password']").count() > 0:
                return False
            # 检查是否有控制台特征元素
            txt = page.locator("body").inner_text()
            if any(k in txt for k in ["귀하의 계정에 로그인하세요", "Sign in to your account", "Log in to your account"]):
                return False
        except Exception:
            pass
        return True

    def ensure_login(self):
        page = self.page

        # CDP 模式
        if self.cdp_mode:
            page.goto(PANEL_URL, wait_until="domcontentloaded")
            time.sleep(3)
            if self.check_is_logged_in():
                log(f"Chrome 已登录，进入控制台：{page.url}")
                return
            log("当前 Chrome 尚未登录 voer.host，请在浏览器中手动登录一次...")
            deadline = time.time() + 300
            while time.time() < deadline:
                time.sleep(4)
                page.goto(PANEL_URL, wait_until="domcontentloaded")
                if self.check_is_logged_in():
                    log("检测到已成功登录，继续执行")
                    return
            log("等待登录超时", "ERROR")
            sys.exit(4)

        # 检查是否已凭 Session 直登面板（给予 SPA 异步验证充足时间）
        log(f"正在验证 Session 是否有效，访问控制台: {PANEL_URL}...")
        page.goto(PANEL_URL, wait_until="domcontentloaded")
        for _ in range(8):
            time.sleep(1)
            if self.check_is_logged_in():
                log(f"Session 验证有效！免密成功进入控制台：{page.url}", "SUCCESS")
                return

        # 前往登录页
        log("Session 未生效或首次运行，打开登录页面...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        time.sleep(2)

        # 尝试自动关掉 Cookie 授权弹窗
        try:
            accept_btn = page.locator("button:has-text('Accept'), button:has-text('동의'), button:has-text('I agree')")
            if accept_btn.count() and accept_btn.first.is_visible():
                accept_btn.first.click()
        except Exception:
            pass

        # 填入账号密码
        email = self.cfg.get("email")
        password = self.cfg.get("password")
        if not email or not password:
            log("缺少账号密码！请在 config.json 填写 email 与 password 或设置环境变量", "ERROR")
            sys.exit(2)

        try:
            # 兼容多种定位器
            email_input = page.locator("#login-email, input[type='email'], input[name='email']").first
            pass_input = page.locator("#login-password, input[type='password'], input[name='password']").first
            
            email_input.scroll_into_view_if_needed()
            email_input.fill(email)
            pass_input.fill(password)
            log(f"已自动填入账号 ({email}) 与密码，正在检测人机安全验证...")
        except Exception as e:
            log(f"填写登录表单异常: {e}", "WARN")

        # 真正的提交按钮（必须严格为 type='submit'，避开小眼睛按钮）
        submit = page.locator("form button[type='submit'], button[type='submit']").first

        # 提示用户
        log("已为您打开浏览器窗口并自动填写账号密码。")
        log("如果弹出 Cloudflare 人机验证，请在浏览器窗口中勾选复选框；亦可直接在浏览器中登录。")

        # 智能等待/自动点击 Turnstile 验证码并轮询登录态
        start_t = time.time()
        deadline = start_t + 180  # 给予充分的 3 分钟窗口
        auto_clicked = False
        last_hint_time = 0

        while time.time() < deadline:
            # 优先检测是否已经成功进入控制台（可能用户点击了快捷登录或直接跳过了）
            if self.check_is_logged_in():
                log("检测到已成功进入控制台！", "SUCCESS")
                self.save_session()
                return

            # 如果提交按钮被激活，自动点击提交
            try:
                if submit.is_enabled():
                    log("检测到安全验证已通过，自动提交登录表单...", "SUCCESS")
                    submit.click()
                    time.sleep(3)
                    if self.check_is_logged_in():
                        log("账号登录成功！", "SUCCESS")
                        self.save_session()
                        return
            except Exception:
                pass

            # 尝试自动定位并点击 Turnstile
            if not auto_clicked or int(time.time() - start_t) % 8 == 0:
                if self.try_solve_turnstile():
                    auto_clicked = True

            # 每隔 15 秒友善提醒一次
            if time.time() - last_hint_time > 15:
                last_hint_time = time.time()
                log("等待登录中... 若浏览器窗口出现复选框，请在浏览器中手动点击一次；也可点下方 Google/Discord 快捷登录。")

            time.sleep(1.5)

        if not self.check_is_logged_in():
            try:
                page.screenshot(path="login_failed.png")
            except Exception:
                pass
            log("登录等待超时。截图已存为 login_failed.png", "ERROR")
            sys.exit(4)

    # ------------------------------------------------------------------
    # 前置诊断与服务器数据
    # ------------------------------------------------------------------
    def api_get(self, url: str) -> dict:
        return self.page.evaluate(
            """async (u) => {
                try {
                    const r = await fetch(u, { credentials: 'include', headers: {'Accept':'application/json'} });
                    return { status: r.status, body: await r.json().catch(()=>null) };
                } catch(e) {
                    return { status: 0, error: e.message };
                }
            }""", url)

    def check_geo_support(self) -> bool:
        """检查当前 IP 所在地区是否受 Google 激励广告支持"""
        res = self.api_get(GEO_INFO_URL)
        body = res.get("body") or {}
        if body.get("blocked"):
            country = body.get("countryIso", "未知")
            log(f"!! 当前 IP 节点国家/地区 ({country}) 被 Voer.host 广告提供商判定为不支持！", "WARN")
            log("   原因：该地区无法获取 Google 激励视频广告，继续运行极可能发生超时。", "WARN")
            log("   解决建议：使用 --proxy 参数挂载常用节点（如香港、台湾、日本、欧美优质家庭代理）。", "WARN")
            return False
        return True

    def get_servers(self) -> list:
        res = self.api_get("/api/servers")
        data = res.get("body")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("servers") or data.get("data") or []
        return []

    def print_status(self) -> list:
        servers = self.get_servers()
        if not servers:
            log("未查询到有效服务器列表，可能接口结构变更或当前账号无服务器", "WARN")
            return []

        print("\n" + "=" * 70)
        print("                   VOER.HOST 服务器状态一览")
        print("=" * 70)
        for idx, s in enumerate(servers, 1):
            sid = s.get("id", "?")
            name = s.get("name") or s.get("minecraftName") or s.get("gameName") or f"Server #{idx}"
            status = s.get("status", "unknown")
            ext_today = s.get("extensionsToday", s.get("extensions_today", 0))
            ms_left = s.get("timeRemainingMs", s.get("timeRemaining", 0))
            readable_time = format_ms(ms_left)

            print(f"[{idx}] 服务器: {name} (ID: {sid})")
            print(f"    - 运行状态: {status}")
            print(f"    - 今日续签: {ext_today} / {MAX_EXTENSIONS_PER_UTC_DAY} 次 (已延长 {int(ext_today)*HOURS_PER_EXTENSION} 小时)")
            print(f"    - 剩余使用时间: {readable_time}")
            print("-" * 70)
        return servers

    # ------------------------------------------------------------------
    # 交互式广告播放引擎（深入 iframe 与独立播放器窗口）
    # ------------------------------------------------------------------
    def get_all_ad_targets(self):
        targets = [self.page]
        if self.popup_page and not self.popup_page.is_closed():
            targets.append(self.popup_page)
        return targets

    def try_start_video(self):
        """仅在视频尚未开始时，尝试点击可能存在的启动/授权按钮"""
        for target in self.get_all_ad_targets():
            for f in target.frames:
                # 授权弹窗确认
                for sel in ["button:has-text('Accept')", "button:has-text('I agree')", "button:has-text('Consent')", "[aria-label='Consent']"]:
                    try:
                        c_btn = f.locator(sel).first
                        if c_btn.count() and c_btn.is_visible():
                            c_btn.click(timeout=1000)
                            return
                    except Exception:
                        pass
                # 初始封面播放按钮
                for sel in ["button:has-text('Play')", "button:has-text('Start')", "[aria-label='Play']", ".reward-button"]:
                    try:
                        btn = f.locator(sel).first
                        if btn.count() and btn.is_visible():
                            btn.click(timeout=1000)
                            return
                    except Exception:
                        pass

    def find_and_click_close_button(self) -> bool:
        """
        在所有页面及嵌套 iframe 中，检测视频播放完毕后才出现的 Close 关闭按钮
        只有当视频播放完成出现真正可见的 Close 时才执行点击
        """
        close_selectors = [
            "button[aria-label='Close ad']",
            "button[aria-label='Close']",
            "[aria-label*='Close' i]",
            "#dismiss-button",
            "div[id='dismiss-button']",
            "button:has-text('Close')",
            "button:has-text('닫기')",
            "div[id='close-button']",
            ".reward-close",
            "[aria-label*='닫기']"
        ]
        for target in self.get_all_ad_targets():
            for f in target.frames:
                for sel in close_selectors:
                    try:
                        btn = f.locator(sel).first
                        if btn.count() and btn.is_visible():
                            box = btn.bounding_box()
                            if box and box["width"] > 8 and box["height"] > 8:
                                log(f"🎯 视频播放完毕，检测到 Close 按钮 ({sel})，点击进入下一步！", "SUCCESS")
                                btn.click(timeout=2000)
                                return True
                    except Exception:
                        pass
        return False

    def extend_once(self, server_id: str, server_name: str = "") -> bool:
        """执行单次续签 (+4 小时，观看 3 个视频广告)"""
        page = self.page
        url = f"{BASE_URL}/panel/server/{server_id}"
        log(f"正在打开服务器详情页: {url}")
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(3)

        body_text = lambda: page.locator("body").inner_text()

        # 1. 检查今日续签是否已达上限
        txt = body_text()
        m = re.search(r"Extensions today\s*(\d+)\s*/\s*(\d+)", txt)
        if m:
            used, total = int(m.group(1)), int(m.group(2))
            log(f"今日已续签: {used}/{total} 次")
            if used >= total or used >= MAX_EXTENSIONS_PER_UTC_DAY:
                log(f"服务器【{server_name or server_id}】今日续签次数已达上限 ({used}/{total})，无需重复续签", "SUCCESS")
                return True

        # 2. 前置 Geo 诊断
        self.check_geo_support()

        # 3. 第一步：点击详情页上的 "Extend" 按钮唤起续签弹窗
        clicked_extend = False
        for name in ("Extend", "Extend Now", "연장", "Watch Ads"):
            b = page.get_by_role("button", name=name)
            if b.count() and b.is_visible():
                log(f"点击页面【{name}】按钮唤起续签弹窗")
                b.first.click()
                clicked_extend = True
                break

        if not clicked_extend:
            write_probe("no_extend_btn", body_text())
            log("未在页面中找到 'Extend' 按钮，可能当前会话不支持或该服务器无权续签", "WARN")
            return False

        time.sleep(2)

        # 4. 第二步：在弹窗中点击 "Watch Ads" 确认按钮激活广告播放器
        clicked_watch = False
        for name in ("Watch Ads", "광고 시청", "Confirm", "Extend"):
            b = page.get_by_role("button", name=name)
            if b.count() and b.is_visible():
                log(f"点击弹窗确认按钮【{name}】启动广告播放器")
                b.first.click()
                clicked_watch = True
                break

        time.sleep(3)

        # 5. 等待续签弹窗与播放器加载
        gate_found = False
        for _ in range(15):
            cur_txt = body_text()
            if any(k in cur_txt for k in ["Watching ad", "All ads verified", "rewarded ads required", "Open ad player", "광고"]):
                gate_found = True
                break
            time.sleep(1)

        if not gate_found:
            write_probe("no_gate", body_text())
            log("广告播放器初始化加载超时", "ERROR")
            return False

        log("已成功激活广告播放器，开始观看激励广告...", "SUCCESS")

        # 5. 核心观看循环（依次观看 3 个视频，播放完毕等待 Close 按钮）
        current_ad = 0
        ad_start_time = time.time()
        last_progress_time = time.time()
        start_wait = time.time()
        max_duration = self.timeout_min * 60

        while time.time() - start_wait < max_duration:
            txt = body_text()

            # 检测全部验证完成
            if TXT_ALL_VERIFIED in txt or "All ads verified" in txt:
                log("🎉 3 个视频广告已全部验证通过，正在自动结算使用时间...", "SUCCESS")
                time.sleep(6)
                # 刷新页面验证新状态
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(3)
                m3 = re.search(r"Extensions today\s*(\d+)\s*/\s*(\d+)", body_text())
                log(f"续签完成！当前今日已续签: {m3.group(0) if m3 else '?'} (+4小时使用时间)", "SUCCESS")
                send_notification(
                    self.cfg,
                    f"Voer.host 续签成功: {server_name or server_id}",
                    f"服务器: {server_name or server_id}\n进度: +4 小时使用时间\n状态: {m3.group(0) if m3 else '已更新'}"
                )
                return True

            # 匹配当前广告进度 (1 of 3, 2 of 3, 3 of 3)
            m_ad = re.search(r"Watching ad (\d+) of (\d+)", txt)
            if m_ad:
                cur, total = int(m_ad.group(1)), int(m_ad.group(2))
                if cur != current_ad:
                    current_ad = cur
                    ad_start_time = time.time()
                    last_progress_time = time.time()
                    log(f"🎬 开始播放第 {cur}/{total} 个广告，正在等待视频播放倒计时...", "INFO")

            # 检查是否有独立播放器弹窗降级按钮
            try:
                open_p_btn = page.get_by_role("button", name=TXT_OPEN_PLAYER)
                if open_p_btn.count() and open_p_btn.is_visible():
                    log("内嵌播放器降级，点击 'Open ad player' 唤起独立窗口...", "INFO")
                    open_p_btn.click(timeout=2000)
            except Exception:
                pass

            # 进度被重置提示
            if "watch all 3 ads again" in txt.lower() or TXT_PROGRESS_RESET in txt:
                log("广告进度被重置，重新开始播放...", "WARN")
                ad_start_time = time.time()
                last_progress_time = time.time()

            # 核心生命周期控制：
            elapsed = time.time() - ad_start_time
            if elapsed < 12:
                # 视频刚开始播放的前 12 秒：专心等待视频播放，绝不点击关闭，确保奖励有效
                self.try_start_video()
                time.sleep(2)
                continue
            else:
                # 12 秒之后：视频进入尾声，开始持续探测并点击已显现的 Close 按钮
                clicked_close = self.find_and_click_close_button()
                if clicked_close:
                    time.sleep(3)  # 点击 Close 后等待 3 秒以使后端结算并跳到下一个视频
                    last_progress_time = time.time()
                    continue

            # 90 秒防卡死看门狗
            if time.time() - last_progress_time > 90:
                log("当前广告播放超 90 秒无进度更新，触发看门狗自动重试...", "WARN")
                try:
                    retry_btn = page.locator("button:has-text('Try another ad'), button:has-text('Reload')")
                    if retry_btn.count() and retry_btn.first.is_visible():
                        retry_btn.first.click()
                except Exception:
                    pass
                last_progress_time = time.time()
                ad_start_time = time.time()

            time.sleep(2)

        write_probe("extend_timeout", body_text())
        log("单次看广告超时未完成，常见原因为当前代理 IP 缺乏广告库存或网络断流", "ERROR")
        return False


# ---------------------------------------------------------------------------
# 业务流程入口
# ---------------------------------------------------------------------------
def run_renew(renewer: VoerRenewer, args):
    """单次运行或全量续签"""
    renewer.print_status()
    servers = renewer.get_servers()
    if not servers:
        log("未找到可用的服务器", "ERROR")
        return False

    targets = []
    if args.all:
        targets = servers
    elif args.server:
        for s in servers:
            name = s.get("name") or ""
            if args.server.lower() in name.lower() or str(s.get("id")) == str(args.server):
                targets.append(s)
                break
        if not targets:
            log(f"未找到名称或 ID 包含 '{args.server}' 的服务器", "ERROR")
            return False
    else:
        # 默认续签第一台
        targets = [servers[0]]

    all_success = True
    for s in targets:
        sid = str(s.get("id"))
        sname = s.get("name") or sid
        log(f"\n>>> 开始为服务器【{sname}】(ID: {sid}) 执行看视频续签...")
        ok = renewer.extend_once(sid, sname)
        if not ok:
            all_success = False
        time.sleep(3)

    # 汇总通知：获取更新后的最新状态
    try:
        latest_servers = renewer.get_servers()
        if latest_servers:
            summary_lines = []
            for s in latest_servers:
                sname = s.get("name") or s.get("id")
                ext = s.get("extensionsToday", s.get("extensions_today", 0))
                ms_left = s.get("timeRemainingMs", s.get("timeRemaining", 0))
                summary_lines.append(f"• *{sname}*: 剩余 {format_ms(ms_left)} (今日已续 {ext}/{MAX_EXTENSIONS_PER_UTC_DAY} 次)")
            
            status_text = "全部成功 ✅" if all_success else "部分失败 ⚠️"
            msg = f"执行结果: {status_text}\n\n当前服务器状态：\n" + "\n".join(summary_lines)
            send_notification(renewer.cfg, "🤖 Voer.host 续签运行报告", msg)
    except Exception as e:
        log(f"发送汇总通知异常: {e}", "DEBUG")

    return all_success


def daemon_loop(renewer: VoerRenewer, args):
    """
    无人值守守护挂机模式：
    自动监测使用时间，在需要续签时看视频增加时间；达到当日 4 次上限后自动休眠等待至次日 UTC 0 点重置。
    """
    log("已进入【无人值守守护模式】，脚本将 7x24 小时保持运行并自动管理服务器使用时间...", "SUCCESS")

    while True:
        try:
            log("正在巡检服务器状态...")
            servers = renewer.print_status()
            if not servers:
                log("未检测到服务器，将在 10 分钟后重试...", "WARN")
                time.sleep(600)
                continue

            all_day_full = True
            min_remaining_s = 24 * 3600

            for s in servers:
                ext_today = int(s.get("extensionsToday", s.get("extensions_today", 0)))
                ms_left = int(s.get("timeRemainingMs", s.get("timeRemaining", 0)))
                sec_left = max(0, ms_left // 1000)
                sid = str(s.get("id"))
                sname = s.get("name") or sid

                if ext_today < MAX_EXTENSIONS_PER_UTC_DAY:
                    all_day_full = False
                    # 如果剩余时间小于 3.5 小时，或者剩余时间不足，立即续签
                    if sec_left < 3.5 * 3600:
                        log(f"服务器【{sname}】剩余时间不足 ({format_ms(ms_left)})，今日已续 {ext_today}/4 次，立即启动看视频续签！")
                        renewer.extend_once(sid, sname)
                    else:
                        log(f"服务器【{sname}】剩余时间充足 ({format_ms(ms_left)})，暂无需续签。")
                        min_remaining_s = min(min_remaining_s, sec_left - int(3 * 3600))
                else:
                    log(f"服务器【{sname}】今日 4 次续签名额已全部用满（已延长 16 小时）。")

            if all_day_full:
                # 计算距离下一个 UTC 00:05 的秒数
                now = datetime.now(timezone.utc)
                seconds_until_utc_midnight = (24 * 3600) - (now.hour * 3600 + now.minute * 60 + now.second) + 300
                hours_wait = round(seconds_until_utc_midnight / 3600, 1)
                log(f"账号下所有服务器今日续签已满额！脚本进入休眠，将于次日 UTC 重置后唤醒（约 {hours_wait} 小时后）", "SUCCESS")
                time.sleep(seconds_until_utc_midnight)
                continue

            # 决定下一次休眠时间（最短 15 分钟，最长 3 小时）
            sleep_sec = max(900, min(min_remaining_s, 3 * 3600))
            log(f"本次巡检完成，计划在 {sleep_sec // 60} 分钟后进行下一次状态巡检...", "INFO")
            time.sleep(sleep_sec)

        except KeyboardInterrupt:
            log("用户终止守护进程，退出。", "INFO")
            break
        except Exception as e:
            log(f"守护循环出现异常: {e}，将在 5 分钟后自动恢复...", "ERROR")
            time.sleep(300)


def parse_args():
    p = argparse.ArgumentParser(description="Voer.host 看视频自动增加使用时间脚本 (深度优化版)")
    p.add_argument("action", nargs="?", default="run", choices=["run", "status", "probe", "loop", "login"])
    p.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
                   help="配置文件路径")
    p.add_argument("--server", default=None, help="指定要续签的服务器名称或 ID")
    p.add_argument("--all", action="store_true", help="一键为账号下所有服务器执行续签")
    p.add_argument("--loop", action="store_true", help="开启无人值守守护模式（7x24小时全自动续签挂机）")
    p.add_argument("--profile-dir", default=None, help="Chromium 用户数据持久化目录")
    p.add_argument("--session-file", default=None, help="会话持久化存储文件 (默认 session.json)")
    p.add_argument("--cookies", default=None, help="自定义导入 cookie / session 路径")
    p.add_argument("--proxy", default=None, help="代理地址 (例如 http://127.0.0.1:7890)")
    p.add_argument("--cdp", default=None, help="直连已打开的真实 Chrome 端口 (例如 http://127.0.0.1:9222)")
    p.add_argument("--headless", action="store_true", help="无头模式运行")
    p.add_argument("--timeout-min", default=10, help="单次续签超时时间（分钟）")
    p.add_argument("--debug", action="store_true", help="调试模式：保留浏览器窗口")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config(args.config)
    renewer = VoerRenewer(cfg, args)

    with sync_playwright() as pw:
        renewer.open_browser(pw)
        try:
            if args.action == "login":
                log("已进入【登录与 Session 提取模式】，正在打开登录页面...")
                renewer.ensure_login()
                renewer.save_session()
                # 打印单行 Session 供 GitHub Secrets 复制
                if os.path.exists(renewer.session_file):
                    with open(renewer.session_file, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                    
                    # 尝试自动复制到系统剪贴板
                    copied_to_clip = False
                    try:
                        import subprocess
                        p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
                        p.communicate(input=content.encode("utf-8"))
                        copied_to_clip = True
                    except Exception:
                        pass

                    print("\n" + "=" * 70)
                    print("【GitHub Actions 部署专用】复制下方整行内容填入 GitHub Secrets:")
                    print("Secret 名称: VOER_SESSION")
                    print("=" * 70)
                    print(content)
                    print("=" * 70 + "\n")
                    if copied_to_clip:
                        log("【超贴心提示】整串凭据已自动写入系统剪贴板！直接去 GitHub 粘贴 (Ctrl+V) 即可！", "SUCCESS")
                    log("Session 提取成功！已在当前目录保存 session.json", "SUCCESS")
                return

            renewer.ensure_login()

            if args.action == "status":
                renewer.print_status()
                return

            if args.action == "probe":
                renewer.print_status()
                write_probe("panel", renewer.page.locator("body").inner_text())
                return

            if args.action == "loop" or args.loop:
                daemon_loop(renewer, args)
                return

            # run 动作
            success = run_renew(renewer, args)
            if success:
                log("任务执行完成！", "SUCCESS")
            else:
                log("部分或全部续签任务未完成，请参阅日志排查", "WARN")
                sys.exit(1)

        finally:
            if renewer.cdp_mode:
                log("CDP 模式：保持外部真实浏览器开启。")
            elif not args.debug and not (args.action == "loop" or args.loop):
                try:
                    renewer.ctx.close()
                except Exception:
                    pass
            else:
                log("浏览器保持打开状态。")


if __name__ == "__main__":
    main()