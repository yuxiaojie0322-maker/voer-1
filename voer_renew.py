#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
voer_renew.py — 动态安全加载器 (Core Script Private Loader)

本文件为轻量级启动引导器，不含任何核心业务逻辑代码。
核心逻辑已托管于独立私人仓库以保护知识产权与核心逻辑安全。

在运行阶段，本加载器通过安全的只读 GitHub Token 动态获取最新核心脚本，
并在内存中直接编译执行，保障核心代码不在公开仓库中持久存储。
"""

import sys
import os
import json
import urllib.request
import urllib.error

# 解决 Windows 控制台编码问题
if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if sys.stderr:
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 默认私有仓库配置
DEFAULT_CORE_REPO = "yuxiaojie0322-maker/my-private-scripts"
DEFAULT_CORE_BRANCH = "main"
DEFAULT_CORE_FILE_PATH = "voer/voer_renew.py"


def load_local_config():
    """尝试从当前目录下的 config.json 读取配置"""
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def get_credentials():
    """解析核心仓库配置与访问凭证"""
    local_cfg = load_local_config()

    token = (
        os.environ.get("CORE_SCRIPT_TOKEN")
        or os.environ.get("CORE_TOKEN")
        or os.environ.get("GITHUB_PAT")
        or local_cfg.get("core_token")
        or ""
    ).strip()

    repo = (
        os.environ.get("CORE_REPO")
        or local_cfg.get("core_repo")
        or DEFAULT_CORE_REPO
    ).strip()

    branch = (
        os.environ.get("CORE_BRANCH")
        or local_cfg.get("core_branch")
        or DEFAULT_CORE_BRANCH
    ).strip()

    file_path = (
        os.environ.get("CORE_FILE_PATH")
        or local_cfg.get("core_file_path")
        or DEFAULT_CORE_FILE_PATH
    ).strip()

    proxy = (
        os.environ.get("VOER_PROXY")
        or local_cfg.get("proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or None
    )

    return token, repo, branch, file_path, proxy


def print_missing_token_banner(repo):
    """打印未配置 Token 时的详细指引说明"""
    print("\n" + "=" * 65)
    print(" 🔒 [Voer Core Loader] 未检测到私有核心仓库访问凭据 (Token)")
    print("=" * 65)
    print(f" 目标私有仓库: https://github.com/{repo}")
    print(" 为保护核心逻辑，本系统需要只读凭据动态拉取核心脚本。\n")
    print(" 💡 配置方式如下：")
    print(" -------------------------------------------------------------")
    print(" 1. 【GitHub Actions 环境部署】：")
    print("    • 在本公开仓库页面进入 Settings -> Secrets and variables -> Actions")
    print("    • 新增 Secret 名称: CORE_SCRIPT_TOKEN")
    print("    • 填入您的 GitHub Personal Access Token (PAT，需具备私有仓库读取权限)")
    print("    • （可选）新增 Secret: CORE_REPO，值为您的私有仓库名称\n")
    print(" 2. 【本地 Windows 环境运行】：")
    print("    • 方式 A：在 config.json 中加入以下字段：")
    print('      "core_token": "ghp_xxxxxxxxxxxxxxxxxxxx"')
    print(f'      "core_repo": "{repo}"')
    print("    • 方式 B：在运行前设置系统环境变量：")
    print("      set CORE_SCRIPT_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx")
    print(" -------------------------------------------------------------")
    print(" 👉 创建 Token 教程：GitHub -> Settings -> Developer Settings -> Personal access tokens\n")
    print("=" * 65 + "\n")


def fetch_core_script(token, repo, branch, file_path, proxy):
    """通过 GitHub API 带鉴权拉取私有脚本，支持候选路径回退"""
    candidate_paths = [file_path]
    if file_path != "voer_renew.py" and "/" in file_path:
        candidate_paths.append(file_path.split("/")[-1])  # 回退到根目录 voer_renew.py
    elif file_path == "voer_renew.py":
        candidate_paths.append("voer/voer_renew.py")

    headers = {
        "User-Agent": "Voer-Core-Loader/2.0",
        "Accept": "application/vnd.github.raw",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)

    errors = []
    for path in candidate_paths:
        api_url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={branch}"
        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"

        for target_url, auth_header in [
            (api_url, f"Bearer {token}"),
            (raw_url, f"token {token}"),
        ]:
            try:
                req = urllib.request.Request(target_url, headers={**headers, "Authorization": auth_header})
                with opener.open(req, timeout=25) as resp:
                    if resp.status == 200:
                        code_content = resp.read().decode("utf-8")
                        return code_content
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    errors.append(f"HTTP 404 Not Found (URL: {target_url})")
                elif e.code in (401, 403):
                    errors.append(f"HTTP {e.code} 鉴权失败，Token 无效或权限不足以读取私有仓库 {repo}")
                else:
                    errors.append(f"HTTP {e.code}: {e.reason}")
            except Exception as e:
                errors.append(str(e))

    raise RuntimeError("\n".join(errors))


def main():
    token, repo, branch, file_path, proxy = get_credentials()

    if not token:
        print_missing_token_banner(repo)
        sys.exit(1)

    print(f"🚀 [Voer Loader] 正在从私有仓库 ({repo}@{branch}:{file_path}) 动态加载核心引擎...")

    try:
        core_code = fetch_core_script(token, repo, branch, file_path, proxy)
        print(f"✅ [Voer Loader] 核心引擎加载成功 ({len(core_code):,} 字节)，准备执行！\n")
    except Exception as e:
        print(f"\n❌ [Voer Loader] 无法拉取核心脚本: {e}")
        print_missing_token_banner(repo)
        sys.exit(1)

    compiled_code = compile(core_code, "voer_renew_core.py", "exec")
    exec_scope = dict(globals())
    exec_scope.update({
        "__name__": "__main__",
        "__file__": os.path.abspath(__file__),
        "__builtins__": __builtins__,
    })
    exec(compiled_code, exec_scope, exec_scope)


if __name__ == "__main__":
    main()
