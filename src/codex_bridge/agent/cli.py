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


def failure(command, error, delivery_id=None):
    detail = safe_error(error)
    code = detail["code"]
    result = {"ok": False, "error": detail}
    if delivery_id is not None:
        result["delivery_id"] = delivery_id
    if code in {"not_running", "stale_state"}:
        result["action"] = "在当前配置运行 start。首次使用可以运行 setup。"
    elif code == "credential_store_unavailable":
        result["action"] = "启用或解锁本机系统凭据库，再重试当前命令。"
    elif code == "not_paired":
        result["action"] = "先查询 peers。正在等待批准时请接收端核对申请。没有配对时请接收端生成邀请。"
    elif code in {"offline", "timeout", "disconnected"}:
        if command in {"send", "retry", "delivery-status", "join"}:
            action = (
                "请接收端运行 status，若进程停止则运行 start。确认两端联网。"
                "若接收地址已变更，请在接收端 stop 后 start，再用新邀请重新配对。"
            )
            if command in {"send", "retry"}:
                action += " 先用 outbox 核对原交付 ID，恢复连接后查询 delivery-status，必要时用原 ID retry。"
            result["action"] = action
        else:
            result["action"] = "请用 status 检查当前端点，再重试当前命令。"
    elif code == "not_found" and command in {"retry", "delivery-status"}:
        result["action"] = "先用 outbox 核对原交付 ID。若记录存在且尚未确认送达，可用原 ID retry。"
    return result


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
            return failure(command, error, delivery_id)
    if command == "retry":
        delivery_id = validate_id(args.delivery_id)
        try:
            return control_request(root, "POST", "/retry/" + delivery_id)
        except Exception as error:
            return failure(command, error, delivery_id)
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
        result = failure(args.command, error)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and result.get("ok") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
