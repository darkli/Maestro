"""
命令行入口
"""

import sys
import argparse
from autopilot.orchestrator import Orchestrator
from autopilot.config import load_config


def main():
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="用 Meta-Agent 自动驱动 Claude Code 完成需求",
    )

    subparsers = parser.add_subparsers(dest="command")

    # run 子命令
    run_parser = subparsers.add_parser("run", help="执行一个需求")
    run_parser.add_argument("requirement", nargs="?", help="需求描述（不填则进入交互模式）")
    run_parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    run_parser.add_argument("--no-zellij", action="store_true", help="禁用 Zellij 界面")
    run_parser.add_argument("--provider", help="覆盖 Meta-Agent provider")
    run_parser.add_argument("--model", help="覆盖 Meta-Agent 模型")

    # list 子命令（查看历史任务）
    list_parser = subparsers.add_parser("list", help="查看历史任务")

    args = parser.parse_args()

    if args.command == "run" or args.command is None:
        config = load_config(getattr(args, "config", "config.yaml"))

        # 命令行参数覆盖配置
        if hasattr(args, "no_zellij") and args.no_zellij:
            config.zellij.enabled = False
        if hasattr(args, "provider") and args.provider:
            config.meta_agent.provider = args.provider
        if hasattr(args, "model") and args.model:
            config.meta_agent.model = args.model

        # 获取需求
        requirement = getattr(args, "requirement", None)
        if not requirement:
            print("📝 请输入需求（输入完成后按两次 Enter）：")
            lines = []
            try:
                while True:
                    line = input()
                    if line == "" and lines and lines[-1] == "":
                        break
                    lines.append(line)
            except EOFError:
                pass
            requirement = "\n".join(lines).strip()

        if not requirement:
            print("❌ 需求不能为空")
            sys.exit(1)

        orchestrator = Orchestrator(config)
        result = orchestrator.run(requirement)

        # 根据结果设置退出码
        if result["status"] == "done":
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.command == "list":
        from pathlib import Path
        import glob
        log_dir = Path("~/.autopilot/logs").expanduser()
        logs = sorted(glob.glob(str(log_dir / "*-meta.log")))
        if not logs:
            print("暂无历史任务")
        else:
            print(f"历史任务（{len(logs)} 个）：")
            for log in logs[-10:]:  # 显示最近 10 个
                task_id = Path(log).name.replace("-meta.log", "")
                print(f"  - {task_id}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
