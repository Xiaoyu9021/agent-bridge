from __future__ import annotations

import argparse
from pathlib import Path

from codex_bridge.config import Settings
from codex_bridge.services.identity import local_device


def main():
    parser = argparse.ArgumentParser(description="Codex Bridge 开发任务交接工具")
    parser.add_argument("--data-dir", type=Path, help="独立实例的数据目录")
    parser.add_argument("--name", help="本机名称")
    parser.add_argument("--headless", action="store_true", help="仅运行 Host 服务，以本地控制台确认配对")
    parser.add_argument("--host", help="Host 明确监听的私有 IP（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, help="Host 端口（默认 47821）")
    parser.add_argument("--self-check", type=Path, help="在临时目录执行 GUI/API 打包自检，写入 JSON 报告后退出")
    args = parser.parse_args()
    if args.self_check:
        from codex_bridge.services.selfcheck import self_check
        try:
            self_check(args.self_check)
        except Exception as error:
            import json
            import traceback
            args.self_check.parent.mkdir(parents=True, exist_ok=True)
            args.self_check.write_text(json.dumps({"passed": False, "error": type(error).__name__,
                                                   "traceback": traceback.format_exc()}, indent=2), encoding="utf-8")
            raise SystemExit(1) from None
        return
    settings = Settings.from_env()
    if args.data_dir:
        settings.data_dir = args.data_dir.resolve()
    if args.host:
        settings.host = args.host
    if args.port:
        settings.port = args.port
    device = local_device(settings.data_dir, args.name)
    if not args.headless:
        from codex_bridge.ui.app import run_gui
        raise SystemExit(run_gui(settings, device))
    from codex_bridge.server.runtime import HostRuntime
    from codex_bridge.storage.store import BridgeError
    runtime = HostRuntime(settings, device)
    try:
        runtime.start()
        print(f"Host: {runtime.url}\n数据: {settings.data_dir}\n仅限可信 LAN 或私有网络；HTTP 不提供加密。")
        print("本地命令: pair | pending | approve <序号> | reject <序号> | devices | revoke <设备UUID> | quit")
        while True:
            try:
                command = input("bridge> ").strip().split()
            except (EOFError, KeyboardInterrupt):
                break
            if not command:
                continue
            try:
                if command[0] == "quit":
                    break
                if command[0] == "pair":
                    print("一次性配对码（10分钟有效）:", runtime.control.open_pairing())
                elif command[0] == "pending":
                    for index, request in enumerate(runtime.control.pending()):
                        print(index, request["display_name"], request["platform"])
                elif command[0] in {"approve", "reject"}:
                    req = runtime.control.pending()[int(command[1])]
                    runtime.control.approve(req["request_id"], command[0] == "approve")
                    print("已处理")
                elif command[0] == "devices":
                    for item in runtime.control.store.devices():
                        print(item["id"], item["display_name"])
                elif command[0] == "revoke":
                    runtime.control.store.revoke(command[1])
                    print("已撤销")
                else:
                    print("未知命令")
            except (ValueError, IndexError, RuntimeError, BridgeError) as error:
                print("命令失败:", str(error))
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
