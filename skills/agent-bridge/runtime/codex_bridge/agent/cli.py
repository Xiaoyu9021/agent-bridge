from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from codex_bridge import __version__
from codex_bridge.agent.broker import safe_error
from codex_bridge.agent.lifecycle import control_request, serve, start_receiver, stop_receiver
from codex_bridge.agent.local import profile_home
from codex_bridge.models import new_id, validate_id


def parser():
    result = argparse.ArgumentParser(description="Agent Bridge：在 Agent 对话中交接任务和文件")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--home", type=Path, help="独立数据目录（默认使用系统应用数据目录）")
    result.add_argument("--profile", default="default", help="同一电脑上不同 Agent 使用不同 profile")
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("setup", "start"):
        cmd = commands.add_parser(command, help="配置并启动后台接收进程")
        cmd.add_argument("--name", help="端点名称，如 windows-codex 或 mac-codex")
        cmd.add_argument("--listen", default="auto", help="自动选择私有地址，或明确指定 127.0.0.1/本机私有 IP")
        cmd.add_argument("--port", type=int, default=47821)
    for command in ("status", "invite", "pending", "peers", "outbox", "stop"):
        commands.add_parser(command)
    commands.add_parser("_serve", help=argparse.SUPPRESS)
    join = commands.add_parser("join", help="从标准输入读取另一端生成的连接信息")
    join.add_argument("--alias", required=True, help="用于后续发送的别名，如 windows")
    approve = commands.add_parser("approve")
    approve.add_argument("device_id")
    reject = commands.add_parser("reject")
    reject.add_argument("device_id")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("device_id")
    send = commands.add_parser("send", help="发送 UTF-8 报告及明确选择的附件")
    send.add_argument("--to", required=True)
    send.add_argument("--project", default="")
    send.add_argument("--title", required=True)
    send.add_argument("--report", type=Path, required=True)
    send.add_argument("--file", type=Path, action="append", default=[])
    send.add_argument("--id", help="可选固定 UUID；同一次交付重试须保持 ID")
    retry = commands.add_parser("retry")
    retry.add_argument("delivery_id")
    inbox = commands.add_parser("inbox")
    inbox.add_argument("--project", default="")
    receive = commands.add_parser("receive")
    receive.add_argument("--id")
    receive.add_argument("--project", default="")
    for command in ("read", "delivery-status"):
        cmd = commands.add_parser(command)
        cmd.add_argument("delivery_id")
    return result


def run(args):
    root = profile_home(args.profile, args.home)
    command = args.command
    if command in {"setup", "start"}:
        return start_receiver(root, name=args.name, listen=args.listen, port=args.port)
    if command == "_serve":
        serve(root)
        return {"status": "stopped"}
    if command == "stop":
        return stop_receiver(root)
    if command in {"status", "pending", "peers", "outbox"}:
        return control_request(root, "GET", "/" + command)
    if command == "invite":
        return control_request(root, "POST", "/invite")
    if command == "join":
        invitation = sys.stdin.read(2049).strip()
        return control_request(root, "POST", "/join", json={"alias": args.alias, "invitation": invitation})
    if command in {"approve", "reject"}:
        return control_request(root, "POST", "/approve", json={"device_id": validate_id(args.device_id),
                                                                 "accepted": command == "approve"})
    if command == "revoke":
        return control_request(root, "POST", "/revoke/" + validate_id(args.device_id))
    if command == "send":
        delivery_id = validate_id(args.id) if args.id else new_id()
        body = {"id": delivery_id, "peer": args.to, "project": args.project, "title": args.title,
                "report": str(args.report.expanduser().absolute()),
                "files": [str(item.expanduser().absolute()) for item in args.file]}
        try:
            return control_request(root, "POST", "/send", json=body)
        except Exception as error:
            return {"ok": False, "delivery_id": delivery_id, "error": safe_error(error),
                    "action": "查询 outbox；若已有此 ID 的记录，用 retry <交付ID> 重试"}
    if command == "retry":
        return control_request(root, "POST", "/retry/" + validate_id(args.delivery_id))
    if command == "inbox":
        return control_request(root, "GET", "/inbox", params={"project": args.project})
    if command == "receive":
        return control_request(root, "POST", "/receive", json={"id": args.id, "project": args.project})
    if command == "read":
        return control_request(root, "POST", "/read/" + validate_id(args.delivery_id))
    if command == "delivery-status":
        return control_request(root, "GET", "/delivery/" + validate_id(args.delivery_id))
    raise ValueError("未知命令")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        result = run(args)
    except Exception as error:
        result = {"ok": False, "error": safe_error(error)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("ok") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
