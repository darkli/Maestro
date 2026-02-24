"""
命令行入口模块

支持的命令：
  maestro run "需求"          后台启动任务
  maestro run -f "需求"       前台同步运行
  maestro list                查看任务列表
  maestro status <id>         查看任务详情
  maestro ask <id> "消息"     给任务注入反馈
  maestro chat <id> "问题"    与 Manager 直接对话
  maestro abort <id>          终止任务
  maestro resume <id>         恢复崩溃的任务
  maestro report <id>         查看任务报告
  maestro daemon start|stop|status  Telegram Daemon 管理
  maestro _worker <id> <dir> <req>  内部命令（不在帮助中显示）
"""

import os
import sys
import signal
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

from maestro.config import load_config, AppConfig
from maestro.registry import TaskRegistry
from maestro.state import read_json_safe
from maestro.orchestrator import setup_logging, _write_inbox


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(
        prog="maestro",
        description="用 Manager Agent 自动驱动编码工具完成开发任务",
    )
    subparsers = parser.add_subparsers(dest="command")

    # ============================================================
    # run 子命令
    # ============================================================
    run_parser = subparsers.add_parser("run", help="启动一个新任务")
    run_parser.add_argument("requirement", nargs="?", help="需求描述")
    run_parser.add_argument(
        "-c", "--config", default="config.yaml", help="配置文件路径"
    )
    run_parser.add_argument(
        "-f", "--foreground", action="store_true",
        help="前台同步运行（默认后台）"
    )
    run_parser.add_argument(
        "-w", "--working-dir", default=None,
        help="工作目录（默认当前目录）"
    )
    run_parser.add_argument(
        "--no-zellij", action="store_true", help="禁用 Zellij 界面"
    )
    run_parser.add_argument("--provider", help="覆盖 Manager provider")
    run_parser.add_argument("--model", help="覆盖 Manager 模型")

    # ============================================================
    # list 子命令
    # ============================================================
    subparsers.add_parser("list", help="查看任务列表")

    # ============================================================
    # status 子命令
    # ============================================================
    status_parser = subparsers.add_parser("status", help="查看任务详情")
    status_parser.add_argument("task_id", help="任务 ID")

    # ============================================================
    # ask 子命令
    # ============================================================
    ask_parser = subparsers.add_parser("ask", help="给任务注入反馈")
    ask_parser.add_argument("task_id", help="任务 ID")
    ask_parser.add_argument("message", help="反馈消息")

    # ============================================================
    # chat 子命令
    # ============================================================
    chat_parser = subparsers.add_parser(
        "chat", help="与任务的 Manager Agent 直接对话"
    )
    chat_parser.add_argument("task_id", help="任务 ID")
    chat_parser.add_argument("message", help="提问内容")
    chat_parser.add_argument(
        "-c", "--config", default="config.yaml", help="配置文件路径"
    )

    # ============================================================
    # abort 子命令
    # ============================================================
    abort_parser = subparsers.add_parser("abort", help="终止任务")
    abort_parser.add_argument("task_id", help="任务 ID")

    # ============================================================
    # resume 子命令
    # ============================================================
    resume_parser = subparsers.add_parser("resume", help="恢复崩溃的任务")
    resume_parser.add_argument("task_id", help="任务 ID")
    resume_parser.add_argument(
        "-c", "--config", default="config.yaml", help="配置文件路径"
    )
    resume_parser.add_argument(
        "-f", "--foreground", action="store_true",
        help="前台同步运行（默认后台）"
    )

    # ============================================================
    # report 子命令
    # ============================================================
    report_parser = subparsers.add_parser("report", help="查看任务报告")
    report_parser.add_argument("task_id", help="任务 ID")

    # ============================================================
    # daemon 子命令
    # ============================================================
    daemon_parser = subparsers.add_parser(
        "daemon", help="Telegram Daemon 管理"
    )
    daemon_parser.add_argument(
        "action", choices=["start", "stop", "status"],
        help="start: 启动 | stop: 停止 | status: 查看状态"
    )
    daemon_parser.add_argument(
        "-c", "--config", default="config.yaml", help="配置文件路径"
    )

    # ============================================================
    # _worker 内部命令（不在帮助中显示）
    # ============================================================
    worker_parser = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("task_id")
    worker_parser.add_argument("working_dir")
    worker_parser.add_argument("requirement")
    worker_parser.add_argument(
        "-c", "--config", default="config.yaml", help=argparse.SUPPRESS
    )

    # ============================================================
    # 解析参数
    # ============================================================
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # 路由到对应处理函数
    handlers = {
        "run": _handle_run,
        "list": _handle_list,
        "status": _handle_status,
        "ask": _handle_ask,
        "chat": _handle_chat,
        "abort": _handle_abort,
        "resume": _handle_resume,
        "report": _handle_report,
        "daemon": _handle_daemon,
        "_worker": _handle_worker,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


# ============================================================
# 命令处理函数
# ============================================================

def _handle_run(args):
    """处理 run 命令"""
    config = load_config(args.config)

    # 命令行参数覆盖配置
    if args.no_zellij:
        config.zellij.enabled = False
    if args.provider:
        config.manager.provider = args.provider
    if args.model:
        config.manager.model = args.model

    # 获取需求
    requirement = args.requirement
    if not requirement:
        print("请输入需求（输入完成后按两次 Enter）：")
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
        print("错误：需求不能为空")
        sys.exit(1)

    # 工作目录
    working_dir = args.working_dir or os.getcwd()

    # 注册表
    registry = TaskRegistry(
        max_parallel_tasks=config.safety.max_parallel_tasks
    )

    # 并发检查
    can_start, reason = registry.can_start_new_task()
    if not can_start:
        print(f"无法启动新任务: {reason}")
        sys.exit(1)

    # 生成任务 ID
    task_id = TaskRegistry.generate_task_id()
    registry.create_task(task_id, requirement, working_dir)

    if args.foreground:
        # 前台同步运行
        setup_logging(config, task_id)
        from maestro.orchestrator import Orchestrator
        os.chdir(working_dir)
        orchestrator = Orchestrator(config, task_id=task_id)
        orchestrator.run(requirement)
        registry.sync_from_state(task_id)
    else:
        # 后台运行：在 Zellij Session 中启动 worker
        _launch_worker_background(
            config, task_id, working_dir, requirement, args.config
        )
        print(f"任务 [{task_id}] 已启动")
        print(f"  查看进度: maestro status {task_id}")
        print(f"  实时观看: zellij attach maestro-{task_id}")
        print(f"  发送反馈: maestro ask {task_id} \"消息\"")
        print(f"  终止任务: maestro abort {task_id}")


def _handle_list(args):
    """处理 list 命令"""
    registry = TaskRegistry()
    tasks = registry.list_tasks()
    if not tasks:
        print("暂无任务")
        return

    # 状态图标
    status_icons = {
        "pending": "...",
        "executing": ">>>",
        "waiting_user": "???",
        "completed": "[OK]",
        "failed": "[!!]",
        "aborted": "[XX]",
    }

    print(f"{'ID':>10}  {'状态':<12}  {'需求':<40}  {'创建时间':<20}")
    print("-" * 90)
    for t in tasks:
        icon = status_icons.get(t.get("status", ""), "   ")
        req = t.get("requirement", "")[:38]
        created = t.get("created_at", "")[:19]
        print(f"{t['task_id']:>10}  {icon} {t.get('status', ''):9}  {req:<40}  {created}")


def _handle_status(args):
    """处理 status 命令"""
    state_path = (
        Path("~/.maestro/sessions").expanduser()
        / args.task_id / "state.json"
    )
    state = read_json_safe(str(state_path))
    if not state:
        print(f"任务 {args.task_id} 不存在或无状态信息")
        return

    print(f"\n  [{state['task_id']}] {state.get('requirement', '')[:60]}")
    print()
    print(f"  状态   : {state.get('status', '未知')}")
    print(f"  进度   : Turn {state.get('current_turn', 0)}/{state.get('max_turns', 0)}")
    print(f"  费用   : ${state.get('total_cost_usd', 0):.2f}")
    print(f"  目录   : {state.get('working_dir', '')}")
    print(f"  工具   : {state.get('coding_tool_type', '')}")

    if state.get("last_instruction"):
        print(f"\n  上一轮指令:")
        print(f"    {state['last_instruction'][:200]}")

    if state.get("last_output_summary"):
        print(f"\n  最近输出:")
        # 显示最后几行
        lines = state["last_output_summary"].strip().split("\n")
        for line in lines[-5:]:
            print(f"    {line[:100]}")

    if state.get("last_manager_reasoning"):
        print(f"\n  Manager 思路:")
        print(f"    {state['last_manager_reasoning'][:200]}")

    if state.get("error_message"):
        print(f"\n  错误信息: {state['error_message']}")

    print()


def _handle_ask(args):
    """处理 ask 命令"""
    inbox_path = (
        Path("~/.maestro/sessions").expanduser()
        / args.task_id / "inbox.txt"
    )
    if not inbox_path.parent.exists():
        print(f"任务 {args.task_id} 不存在")
        return

    _write_inbox(str(inbox_path), "cli", args.message)
    print(f"已向任务 [{args.task_id}] 发送反馈: {args.message}")


def _handle_chat(args):
    """处理 chat 命令"""
    config = load_config(args.config)

    # 读取任务状态
    state_path = (
        Path("~/.maestro/sessions").expanduser()
        / args.task_id / "state.json"
    )
    state = read_json_safe(str(state_path))
    if not state:
        print(f"任务 {args.task_id} 不存在")
        return

    # 构建上下文
    context_summary = (
        f"当前任务: {state.get('requirement', '')}\n"
        f"状态: {state.get('status', '')}, "
        f"第 {state.get('current_turn', 0)}/{state.get('max_turns', 0)} 轮\n"
        f"费用: ${state.get('total_cost_usd', 0):.2f}\n"
        f"最近 Manager 决策: {state.get('last_manager_action', '')}\n"
        f"Manager 思路: {state.get('last_manager_reasoning', '')}\n"
    )
    if state.get("last_output_summary"):
        context_summary += f"\n最近编码工具输出:\n{state['last_output_summary'][-300:]}\n"

    # 调用 Manager LLM 做独立问答
    from maestro.manager_agent import ManagerAgent
    manager = ManagerAgent(config.manager)
    reply = manager.standalone_chat(context_summary, args.message)
    print(f"\n  [{args.task_id}] Manager 回复:\n")
    print(f"  {reply}\n")


def _handle_abort(args):
    """处理 abort 命令"""
    session_dir = (
        Path("~/.maestro/sessions").expanduser() / args.task_id
    )
    if not session_dir.exists():
        print(f"任务 {args.task_id} 不存在")
        return

    # 创建 abort 信号文件
    abort_file = session_dir / "abort"
    abort_file.touch()

    # 同时更新 registry
    registry = TaskRegistry()
    registry.update_task(args.task_id, status="aborted")

    print(f"已发送终止信号到任务 [{args.task_id}]")
    print("任务将在当前轮次结束后停止")


def _handle_resume(args):
    """处理 resume 命令"""
    config = load_config(args.config)

    session_dir = (
        Path("~/.maestro/sessions").expanduser() / args.task_id
    )
    checkpoint_path = session_dir / "checkpoint.json"
    if not checkpoint_path.exists():
        print(f"找不到任务 [{args.task_id}] 的 checkpoint")
        return

    if args.foreground:
        setup_logging(config, args.task_id)
        from maestro.orchestrator import Orchestrator
        state = read_json_safe(str(session_dir / "state.json"))
        if state and state.get("working_dir"):
            os.chdir(state["working_dir"])
        orchestrator = Orchestrator(config, task_id=args.task_id)
        orchestrator.resume()
    else:
        # 后台恢复
        state = read_json_safe(str(session_dir / "state.json"))
        working_dir = state.get("working_dir", os.getcwd()) if state else os.getcwd()
        requirement = state.get("requirement", "") if state else ""

        _launch_resume_background(config, args.task_id, working_dir, args.config)
        print(f"任务 [{args.task_id}] 正在恢复...")


def _handle_report(args):
    """处理 report 命令"""
    report_path = (
        Path("~/.maestro/sessions").expanduser()
        / args.task_id / "report.md"
    )
    if not report_path.exists():
        print(f"任务 [{args.task_id}] 暂无报告")
        return

    with open(report_path, "r", encoding="utf-8") as f:
        print(f.read())


def _handle_daemon(args):
    """处理 daemon 命令"""
    maestro_dir = Path("~/.maestro").expanduser()
    maestro_dir.mkdir(parents=True, exist_ok=True)
    pid_file = maestro_dir / "daemon.pid"
    log_file = maestro_dir / "logs" / "daemon.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    if args.action == "start":
        # 检查是否已在运行
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 0)
                print(f"Daemon 已在运行 (PID: {pid})")
                return
            except (ProcessLookupError, ValueError):
                pid_file.unlink()

        # 启动 Daemon
        cmd = [
            sys.executable, "-m", "maestro.telegram_bot",
            "--config", args.config,
        ]
        with open(log_file, "a") as log_f:
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=log_f,
                start_new_session=True,
            )
        pid_file.write_text(str(proc.pid))
        print(f"Daemon 已启动 (PID: {proc.pid})")
        print(f"日志: {log_file}")

    elif args.action == "stop":
        if not pid_file.exists():
            print("Daemon 未运行")
            return
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, signal.SIGTERM)
            pid_file.unlink()
            print(f"Daemon 已停止 (PID: {pid})")
        except ProcessLookupError:
            pid_file.unlink()
            print("Daemon 进程不存在，已清理 PID 文件")
        except ValueError:
            pid_file.unlink()
            print("PID 文件损坏，已清理")

    elif args.action == "status":
        if not pid_file.exists():
            print("Daemon 未运行")
            return
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            print(f"Daemon 运行中 (PID: {pid})")
        except ProcessLookupError:
            print("Daemon 未运行（PID 文件已过期）")
            pid_file.unlink()


def _handle_worker(args):
    """处理 _worker 内部命令"""
    config = load_config(args.config)
    setup_logging(config, args.task_id)

    from maestro.orchestrator import Orchestrator
    os.chdir(args.working_dir)
    orchestrator = Orchestrator(config, task_id=args.task_id)
    orchestrator.run(args.requirement)

    # 同步状态到 registry
    registry = TaskRegistry(
        max_parallel_tasks=config.safety.max_parallel_tasks
    )
    registry.sync_from_state(args.task_id)


# ============================================================
# 后台启动辅助函数
# ============================================================

def _launch_worker_background(config: AppConfig, task_id: str,
                               working_dir: str, requirement: str,
                               config_path: str):
    """在后台（Zellij Session）启动 worker"""
    cmd = [
        sys.executable, "-m", "maestro.cli",
        "_worker", task_id, working_dir, requirement,
        "-c", config_path,
    ]

    if config.zellij.enabled:
        # 通过 Zellij Session 启动
        import shutil
        zellij = shutil.which("zellij")
        if zellij:
            zellij_cmd = [
                zellij, "--session", f"maestro-{task_id}",
                "--", *cmd,
            ]
            subprocess.Popen(
                zellij_cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

    # Fallback: 使用 nohup 启动
    log_dir = Path(config.logging.dir).expanduser() / "tasks" / task_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "worker.log"

    with open(log_file, "a") as f:
        subprocess.Popen(
            cmd,
            stdout=f,
            stderr=f,
            start_new_session=True,
            cwd=working_dir,
        )


def _launch_resume_background(config: AppConfig, task_id: str,
                               working_dir: str, config_path: str):
    """在后台恢复任务"""
    cmd = [
        sys.executable, "-m", "maestro.cli",
        "resume", task_id, "-f",
        "-c", config_path,
    ]

    log_dir = Path(config.logging.dir).expanduser() / "tasks" / task_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "worker.log"

    with open(log_file, "a") as f:
        subprocess.Popen(
            cmd,
            stdout=f,
            stderr=f,
            start_new_session=True,
            cwd=working_dir,
        )


if __name__ == "__main__":
    main()
