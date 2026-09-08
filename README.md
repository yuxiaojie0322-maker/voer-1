# voer_renew — Voer.host 免费服务器「看视频续签」深度优化版

Voer.host 免费档服务器：每个会话 4 小时，可通过看 Google 激励视频广告增加使用时间：
**3 个广告 = +4 小时**，**每个 UTC 日最多 4 次（共增加 16 小时）**。

本脚本基于 Playwright 驱动 Chromium 进行了全方位深度优化与逆向适配，攻克了原本后台暂停、弹窗卡死、验证码频繁等核心痛点。

---

## 🌟 核心优化与新特性

1. **Page Visibility 伪装（防广告暂停）**：
   - 深度劫持 `document.hidden` 与 `visibilityState`，拦截 `blur` 与 `visibilitychange` 事件；
   - 保证 Google 激励广告在**后台运行、最小化或被遮挡时**依然持续播放，彻底根治原本广告频繁暂停与超时的问题。
2. **Chromium 自动播放与防降频优化**：
   - 注入 `--autoplay-policy=no-user-gesture-required`，无需人工点击即可自动播放视频广告；
   - 禁用后台定时器节流降频（`--disable-background-timer-throttling` 等）。
3. **主动广告交互与独立播放器接管**：
   - 深入 `iframe` 自动识别并主动点击 `Play`、`Consent/I agree`、`Close (✕)`、`Done` 等按钮；
   - 自动接管内嵌播放器降级时通过 `window.open` 弹出的独立播放器窗口（Popup）。
4. **Cloudflare Turnstile 智能穿透与自动免密秒登**：
   - 注入 Stealth 反指纹抹除 `navigator.webdriver` 等自动化痕迹；
   - 自动模拟鼠标轨迹尝试点击 Turnstile 验证码复选框；
   - 登录成功后**默认自动保存 Session** 到 `session.json`，下次启动无需输入验证码直进控制台。
5. **前置 Geo-info 诊断与 90 秒防卡死看门狗**：
   - 续签前自动检测 `/api/servers/geo-info`，若当前 IP 地区被广告商判定为不支持，立即给出更换节点建议，不再盲等 10 分钟；
   - 90 秒广告无进展看门狗，自动触发页面内部重新请求重试，避免死锁。
6. **7x24小时无人值守守护挂机模式 (`--loop`)**：
   - 自动巡检各服务器剩余时间，时间不足时自动看视频增加 4 小时；
   - 当日已达 4 次上限后，自动计算倒计时并休眠等待至次日 UTC 00:05 重置后自动唤醒继续。
7. **全服务器一键续签 (`--all`) & 友好看板 (`status`)**：
   - 一键续签账号下的多台服务器；
   - 剩余时间精准换算为 `X小时Y分`，直观显示今日续签配额进度。
8. **多渠道通知推送**：
   - 续签成功、当日满额或异常时支持通过 Telegram、Server酱、PushPlus、Discord 或自定义 Webhook 实时通知到手机。

---

## 🚀 快速上手

### 1. 环境准备
```bash
# 需要 Python 3.9+
pip install playwright
playwright install chromium
```

### 2. 配置账号
复制模板 `config.example.json` 为 `config.json`：
```json
{
  "email": "你的邮箱@example.com",
  "password": "你的密码",
  "server_name": null,
  "proxy": "http://127.0.0.1:7890",
  "notify": {
    "tg_bot_token": "",
    "tg_chat_id": "",
    "serverchan_key": "",
    "pushplus_token": "",
    "webhook_url": ""
  }
}
```

### 3. Windows 用户一键启动
- 双击 **`启动_看视频续签.bat`**：可自由选择单次续签、一键续签所有服务器或查看状态。
- 双击 **`启动_守护挂机模式.bat`**：全天候 24 小时后台自动挂机续签。

---

## 💻 命令行使用指南

```bash
# 1. 默认单次续签（看 3 个广告，延长 4 小时）
python voer_renew.py run

# 2. 一键为账号下所有服务器续签
python voer_renew.py run --all

# 3. 指定某台服务器续签
python voer_renew.py run --server 我的服务器名

# 4. 挂代理运行（针对 IP 被阻断或国内用户）
python voer_renew.py run --proxy http://127.0.0.1:7890

# 5. 启动 7x24 小时无人值守守护挂机模式
python voer_renew.py loop
# 或者
python voer_renew.py run --loop

# 6. 查询服务器状态（直观展示剩余时间、今日续签进度）
python voer_renew.py status

# 7. 直连已登录的 Chrome（CDP 模式）
# 先以调试模式启动 Chrome：chrome.exe --remote-debugging-port=9222
python voer_renew.py run --cdp http://127.0.0.1:9222
```

---

## ☁️ GitHub Actions 云端全自动续签（无需服务器，永久免费）

已为您配置好全套 [renew.yml](file:///.github/workflows/renew.yml) 工作流，每天每 4 小时自动触发看视频续签。

### 部署步骤：
1. **Fork 或推送本项目到你的 GitHub 仓库**；
2. **在本地运行提取凭据**：
   - Windows 双击运行 **`导出_GitHub部署凭据.bat`**（或终端运行 `python voer_renew.py login`）；
   - 登录成功后，终端会自动打印整串 `VOER_SESSION` 文本。
3. **在 GitHub 仓库添加 Secrets**：
   - 打开 GitHub 仓库 -> **Settings** -> **Secrets and variables** -> **Actions** -> 点击 **New repository secret**；
   - **名称**：`VOER_SESSION`
   - **内容**：粘贴刚刚终端复制的那一整行 JSON 文本。
   - *(可选)* 添加推送密钥：`TG_BOT_TOKEN`、`TG_CHAT_ID`、`SERVERCHAN_KEY`、`PUSHPLUS_TOKEN` 或 `VOER_PROXY`。
4. **测试与启用**：
   - 进入仓库 **Actions** 标签页 -> 点击 **Voer.host 自动看视频续签** -> 点击 **Run workflow** 手动测试一次；
   - 此后 GitHub 将每 4 小时自动定时为您看视频续签！

---

### 推荐：直接使用守护模式挂机
使用 `nohup` 或 `screen` / `tmux` 在后台持续运行：
```bash
nohup python3 voer_renew.py loop > renew.log 2>&1 &
```
> 无桌面环境的 Linux 服务器，可搭配 `xvfb` 运行：
```bash
nohup xvfb-run -a python3 voer_renew.py loop > renew.log 2>&1 &
```

### 或者配置 crontab 定时运行
```bash
crontab -e
# 每 4 小时执行一次续签
0 */4 * * * cd /path/to/voer-renew && python3 voer_renew.py run >> renew.log 2>&1
```

---

## ❓ 常见问题排查

| 现象 | 原因与解决对策 |
|---|---|
| **Turnstile 验证码提示未通过** | 首次运行时若自动点击未成功，可在弹出的浏览器中手动勾选一次。通过后会自动保存 `session.json`，以后启动无需重复验证。 |
| **检测到当前 IP 地区被广告提供商阻断** | Google 广告对某些数据中心 IP 或特定地区不投放。请在 `config.json` 或添加 `--proxy` 参数配置优质代理节点（如香港、台湾、日本家庭宽带节点）。 |
| **单次看广告超时** | 脚本已内置 90 秒无进度自动重试与可见性伪装。若依然超时，通常是当前节点无广告库存或网络波动，脚本会在守护模式下自动稍后重试。 |
| **今日已续签 4/4 次** | Voer.host 官方规定每个 UTC 日最多续签 4 次（增加 16 小时）。脚本守护模式会自动休眠等待次日 UTC 0 点重置后继续。 |

---

## ⚠️ 免责声明

自动观看广告可能违反 voer.host 或 Google 广告平台的相关条款，账号有被限制的风险。
本脚本仅供学习与自动化测试交流，请自行承担使用后果。