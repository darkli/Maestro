# 原始需求输入

**功能名称**: deploy-prompt-refactor
**提交时间**: 2026-02-25 12:22
**用户描述**:

方案1：分层部署脚本改造 + 方案3：配置与代码分离（Prompt 外置化）。具体需求：1) deploy.sh 支持 deploy.sh init 和 deploy.sh update 参数模式，同时在交互菜单中也将'业务逻辑更新'拆为独立菜单项；2) manager_agent.py 中的 system prompt、action 协议、决策策略等抽成外部配置文件（prompt 文件），支持热加载无需重启服务。

**附加上下文**:

上游 Workspace: .claude/workspace/design-20260225-deploy-prompt-refactor
