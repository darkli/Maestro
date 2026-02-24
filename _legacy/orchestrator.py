"""
Orchestrator（调度核心）
协调 Meta-Agent 和 Claude Code Driver 完成任务
"""

import uuid
import time
import logging
from pathlib import Path
from typing import Optional

from autopilot.config import AppConfig, load_config
from autopilot.meta_agent import MetaAgent, SIGNAL_DONE, SIGNAL_BLOCKED
from autopilot.claude_driver import ClaudeCodeDriver
from autopilot.zellij_session import ZellijSession

logger = logging.getLogger(__name__)


def _setup_logging(config: AppConfig):
    log_dir = Path(config.logging.dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "autopilot.log", encoding="utf-8"),
        ]
    )


class Orchestrator:
    """
    任务调度核心

    流程：
    1. 创建 Zellij 会话（可选）
    2. 启动 Claude Code 进程
    3. Meta-Agent 生成第一条指令
    4. 循环：发送指令 → 读取输出 → Meta-Agent 决策 → 重复
    5. 检测到 DONE/BLOCKED/超轮次 时结束
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or load_config()
        _setup_logging(self.config)
        self.task_id = str(uuid.uuid4())[:8]

    def run(self, requirement: str) -> dict:
        """
        执行一个需求，返回任务结果摘要

        result = {
            "status": "done" | "blocked" | "timeout",
            "turns": int,
            "task_id": str,
            "blocked_reason": str (if blocked),
        }
        """
        logger.info(f"🎯 开始任务 [{self.task_id}]: {requirement[:80]}")

        # 初始化 Zellij 会话
        session = ZellijSession(
            task_id=self.task_id,
            log_dir=self.config.logging.dir
        )
        use_zellij = self.config.zellij.enabled and session.launch()

        if use_zellij:
            print(f"\n✅ Zellij 界面已启动，在另一个终端运行以下命令观看进度：")
            print(f"   zellij attach {session.session_name}\n")

        # Meta-Agent 输出回调
        def on_meta_log(msg: str):
            if use_zellij:
                session.write_meta_log(msg)
            else:
                print(f"[Meta-Agent] {msg}")

        # Claude Code 输出回调
        def on_claude_output(text: str):
            if use_zellij:
                session.write_claude_output(text)
            # 不在 zellij 模式时不重复打印（driver 内部已处理）

        # 初始化组件
        meta_agent = MetaAgent(self.config.meta_agent)
        driver = ClaudeCodeDriver(self.config.claude_code, output_callback=on_claude_output)

        result = {"task_id": self.task_id, "status": "unknown", "turns": 0}

        try:
            # 启动 Claude Code
            session.update_status("🚀 启动 Claude Code...")
            driver.start()
            session.update_status("⚙️  运行中...")

            # Meta-Agent 开始任务
            meta_agent.start_task(requirement)
            on_meta_log(f"📋 需求: {requirement}")
            on_meta_log("🤔 Meta-Agent 正在分析需求，生成第一条指令...")

            # 获取第一条指令（不需要 Claude 输出作为输入）
            first_instruction = meta_agent.decide("")
            on_meta_log(f"📤 指令 #1: {first_instruction[:100]}")

            # 主循环
            for turn in range(1, self.config.meta_agent.max_turns + 1):
                result["turns"] = turn

                # 发送指令
                instruction = first_instruction if turn == 1 else None
                if instruction is None:
                    break

                print(f"\n{'='*60}")
                print(f"Turn {turn}/{self.config.meta_agent.max_turns}")
                print(f"{'='*60}")

                # 执行指令
                output = driver.send_instruction(instruction)
                on_claude_output(output)

                # Meta-Agent 决策下一步
                on_meta_log(f"🔍 分析 Turn {turn} 输出...")
                decision = meta_agent.decide(output)
                on_meta_log(f"💡 决策: {decision[:100]}")

                if meta_agent.is_done(decision):
                    logger.info(f"✅ 任务完成！共 {turn} 轮")
                    result["status"] = "done"
                    session.update_status(f"✅ 完成（{turn} 轮）")
                    on_meta_log("🎉 任务已完成！")
                    break

                if meta_agent.is_blocked(decision):
                    blocked_reason = decision.replace(SIGNAL_BLOCKED, "").strip()
                    logger.warning(f"🚫 任务阻塞: {blocked_reason}")
                    result["status"] = "blocked"
                    result["blocked_reason"] = blocked_reason
                    session.update_status(f"🚫 阻塞: {blocked_reason[:50]}")
                    on_meta_log(f"⛔ 阻塞原因: {blocked_reason}")
                    break

                first_instruction = decision  # 下一轮的指令

            else:
                # 超过最大轮数
                logger.warning(f"⏰ 超过最大轮数 {self.config.meta_agent.max_turns}")
                result["status"] = "timeout"
                session.update_status(f"⏰ 超过最大轮数")

        except KeyboardInterrupt:
            logger.info("⚡ 用户中断")
            result["status"] = "interrupted"

        except Exception as e:
            logger.error(f"❌ 运行出错: {e}", exc_info=True)
            result["status"] = "error"
            result["error"] = str(e)

        finally:
            driver.stop()
            self._print_summary(result)

        return result

    def _print_summary(self, result: dict):
        print(f"\n{'='*60}")
        print(f"📊 任务总结")
        print(f"{'='*60}")
        print(f"任务 ID : {result['task_id']}")
        print(f"状态    : {result['status']}")
        print(f"轮数    : {result.get('turns', 0)}")
        if "blocked_reason" in result:
            print(f"阻塞原因: {result['blocked_reason']}")
        if "error" in result:
            print(f"错误    : {result['error']}")
        print(f"{'='*60}\n")
