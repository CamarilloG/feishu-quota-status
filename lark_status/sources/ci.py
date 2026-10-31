"""CI 状态：构建挂了就顶在状态栏上，别让同事以为你在忙。

目前支持 GitHub Actions（公开仓库免 token，私有仓库配 GITHUB_TOKEN）。

config.json:
    "ci": {
      "provider": "github",
      "repo": "CamarilloG/feishu-quota-status",
      "branch": "main",
      "workflow": "CI",          // 可选，不填就看该分支最近一次 run
      "token_env": "GITHUB_TOKEN" // 可选，私有仓库才需要
    }

只在「成功」之外的状态显示内容（失败/进行中），成功时返回 None，把位置让给别的场景——
没人需要知道 CI 又绿了。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..source import now_ts

API = "https://api.github.com"


class CI:
    name = "ci"

    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self._cache: tuple[int, tuple[str, str] | None] | None = None
        self.min_interval = int(self.cfg.get("min_interval", 60))

    def render(self, now: int) -> tuple[str, str] | None:
        # 免得每次 tick 都打 GitHub
        if self._cache and now - self._cache[0] < self.min_interval:
            return self._cache[1]
        try:
            result = self._fetch()
        except Exception as exc:  # 网络抖动不该让整个状态更新挂掉
            print(f"[ci] 查询失败，跳过本次：{exc}")
            result = None
        self._cache = (now, result)
        return result

    def _fetch(self) -> tuple[str, str] | None:
        repo = self.cfg.get("repo")
        if not repo:
            return None

        headers = {"Accept": "application/vnd.github+json", "User-Agent": "lark-status"}
        token_env = self.cfg.get("token_env")
        if token_env and os.environ.get(token_env):
            headers["Authorization"] = f"Bearer {os.environ[token_env]}"

        run = self._latest_run(repo, headers)
        if not run:
            return None

        status = run.get("status")  # queued / in_progress / completed
        conclusion = run.get("conclusion")  # success / failure / cancelled ...
        name = (run.get("name") or "CI")[:10]

        if status != "completed":
            return f"⏳ {name} 构建中", "GeneralMoonRest"
        if conclusion == "success":
            return None  # 绿了就不用占位置
        if conclusion in ("failure", "timed_out"):
            return f"❌ {name} 构建挂了", "SICK"
        if conclusion == "cancelled":
            return f"⚪️ {name} 已取消", "GeneralDoNotDisturb"
        return None

    def _latest_run(self, repo: str, headers: dict) -> dict | None:
        workflow = self.cfg.get("workflow")
        if workflow:
            url = f"{API}/repos/{repo}/actions/workflows/{workflow}/runs?per_page=1"
            if self.cfg.get("branch"):
                url += f"&branch={self.cfg['branch']}"
        else:
            url = f"{API}/repos/{repo}/actions/runs?per_page=1"
            if self.cfg.get("branch"):
                url += f"&branch={self.cfg['branch']}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        runs = data.get("workflow_runs") or []
        return runs[0] if runs else None
