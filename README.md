# voer_renew — Voer.host 免费服务器「看广告续签」自动化

Voer.host 免费档服务器：每个会话 4 小时，可通过看 Google 激励广告续签：
**3 个广告 = +4 小时**，**每个 UTC 日最多 4 次（16 小时）**，每个会话最多 4 次。

本脚本用 Playwright 驱动真实 Chromium 完成：登录 → 打开服务器详情 →
点「Watch Ads」→ 观看 3 个广告（服务端 SSV 验证）→ 自动结算 +4 小时。

> 注意：广告由 Google 实际投放，能否播放取决于浏览器环境与地区。
> 无头模式 / 数据中心 IP 大概率拿不到广告；请优先在**有桌面的自己电脑**上运行。

---

## 一、安装

```bash
# 需要 Python 3.9+
pip install playwright
playwright install chromium
```

## 二、配置

先复制模板 `config.example.json` 为 `config.json` 再编辑（已预填你的账号）：

```json
{
  "email": "...",
  "password": "...",
  "server_name": null
}
```

## 三、运行

```bash
# 续签一次（默认动作）：3 个广告 → +4 小时
python voer_renew.py run

# 指定服务器
python voer_renew.py run --server 我的服务器名

# 挂代理（HK 节点等）：Clash/v2ray 本地端口示例 7890
python voer_renew.py run --proxy http://127.0.0.1:7890

# 只看状态（服务器列表、今日续签次数、剩余时间）
python voer_renew.py status

# 调试：登录后把页面文本存成 probe_*.txt
python voer_renew.py probe
```

**首次运行说明**：
1. 会弹出一个真实浏览器窗口；
2. 脚本自动填好账号密码；
3. 若出现 Cloudflare「勾选我/人机验证」，请**手动勾选或完成一次验证**（此后登录态会保存在 `.profile` 目录，之后不需要再验证）；
4. 脚本继续自动点「Watch Ads」并等待广告播放；
5. 3 个广告全部验证通过后，页面自动结算，控制台会打印结果。

> 若弹出「Open ad player」按钮，说明内嵌播放器被拦截，脚本会自动点它打开独立窗口。

## 四、定时续签（保持服务器在线）

每个续签 +4 小时，脚本会自己检查每日 4 次上限。建议每 4 小时跑一次。

### Linux（cron）

```bash
crontab -e
# 每 4 小时整点运行一次
0 */4 * * * cd /path/to/voer_renew && /usr/bin/python3 voer_renew.py run >> renew.log 2>&1
```

无桌面环境的服务器需用 xvfb 提供虚拟显示：

```bash
crontab -e
0 */4 * * * cd /path/to/voer_renew && xvfb-run -a python3 voer_renew.py run >> renew.log 2>&1
```

### Windows（任务计划程序）

`任务计划程序` → 创建任务 → 触发器：每天每 4 小时重复；
操作：`python`，参数 `D:\...\voer_renew.py run`，起始于 `D:\...\voer_renew`。
勾选「只在用户登录时运行」（需要桌面）。

## 五、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `!! Turnstile 验证长时间未通过` | 首次运行需要手动过验证码；之后靠 `.profile` 免验证 |
| `!! 没找到 'Watch Ads' 按钮` | 站点改版或该服务器无续签资格；把 `probe_no_watch_ads*.txt` 发给我 |
| `!! 等待广告超时` | Google 无广告库存（换时段/地区）、装了广告拦截、无头模式被识破 |
| `!! 已达到今日续签上限` | 一天 4 次满了，正常现象，明天再跑 |

## 六、免责声明

自动观看广告可能违反 voer.host 或 Google 广告平台的相关政策，账号有被限制的风险。
仅供学习/自用，请自行承担使用后果。