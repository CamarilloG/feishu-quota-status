"""本机查询 Codex 订阅额度。查询本身在 lark_status.agents.codex_usage（问官方 Codex CLI 的 app-server）。"""
import json

from lark_status import agents


def fetch(codex_cli="codex"):
    return agents.codex_usage(codex_cli)


if __name__ == "__main__":
    print(json.dumps(fetch(), ensure_ascii=False))
