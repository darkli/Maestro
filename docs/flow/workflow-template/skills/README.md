# Skills 速查手册

本目录包含所有可用的 Skill 命令。每个 Skill 是一个独立的自动化工作流，在 Claude Code 对话中通过 `/命令名` 调用。

---

## 快速选择

```
任务规模大、需要完整文档      → /feature-dev
任务中等、希望少确认          → /quick-dev
小功能、UI 小改动             → /light-dev
有 Bug 需要修复               → /fix-bug
只需要方案不需要代码          → /design
跑测试、补充测试、覆盖率     → /test
保存/查看跨对话上下文         → /context
查看/清理 workspace 目录      → /workspace
文档/模板/工作流文件修改      → /doc-dev
上次中断的任务                → 继续做
```

---

## 命令一览

| 命令 | 用途 | 阶段 | 确认点 |
|------|------|------|--------|
| `/feature-dev` | 端到端完整功能开发（TDD 驱动） | 7 | 5 |
| `/quick-dev` | 快速功能开发（完整流程，少确认） | 7 | 2 |
| `/light-dev` | 轻量功能开发（精简流程） | 4 | 2 |
| `/fix-bug` | Bug 诊断与修复 | 4 | 1 |
| `/design` | 需求分析与系统设计（只出方案） | 2 | 2 |
| `/test` | 独立测试（运行/覆盖率/补充测试） | — | 按需 |
| `/context` | 跨对话上下文管理 | — | — |
| `/workspace` | Workspace 目录查看与清理 | — | 按需 |
| `/doc-dev` | 文档与模板开发（含一致性扫描） | 5 | 2 |
| `/init-workflow` | 工作流初始化（安装与配置） | — | 按需 |

---

## 详细说明

### `/design` — 需求分析与系统设计

**触发词**：分析需求、设计方案、可行性分析、技术选型

**流程**：
1. **需求分析** → 输出 `01-requirements.md` → *用户确认*
2. **系统设计** → 输出 `02-design.md` → *用户确认*

**特点**：
- 只做方案不写代码，专注于高质量的需求文档和设计方案
- 产出可直接衔接 `/feature-dev` 或 `/light-dev` 继续开发
- 子代理：Requirements Analyst (Opus) + System Designer (Opus)

**Workspace**：`.claude/workspace/design-YYYYMMDD-$NAME/`

**使用示例**：
```
/design 评估将前端状态管理从 Context 迁移到 Zustand 的方案
```

---

### `/feature-dev` — 端到端完整功能开发

**触发词**：开发新功能、创建模块、完整开发流程

**流程**：
1. **需求分析** (Requirements Analyst) → *用户确认*
2. **系统设计** (System Designer) → *用户确认*
3. **TDD 测试设计** (Test Engineer) → 自动流转
4. **编码实现** (Code Engineer) → *用户确认*
5. **代码审查** (Code Reviewer) → *用户确认*
6. **集成验证** (Integration Validator) → *用户确认*
7. **文档交付** (Documentation Writer) → 自动流转

**特点**：
- TDD 驱动：先写失败的测试，再写实现代码
- 5 个确认点，每步都可以审查和调整
- 完整的文档交付（API 文档、变更日志）
- 支持中断后从任意阶段恢复

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

**使用示例**：
```
/feature-dev 添加用户角色权限系统，支持管理员、编辑、只读三种角色
```

---

### `/quick-dev` — 快速功能开发

**触发词**：快速开发、快速模式

**流程**：与 `/feature-dev` 相同的 7 个阶段，但只在 2 个关键节点暂停：
- ⏸ 阶段 2（设计确认）
- ⏸ 阶段 6（验证确认）
- 其余阶段自动流转

**特点**：
- 完整流程但最少交互
- 代码审查发现 Critical/High 问题时自动返回修复
- 适合信任流程、想快速推进的场景

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

**使用示例**：
```
/quick-dev 给列表页面添加标签筛选功能
```

---

### `/light-dev` — 轻量功能开发

**触发词**：小功能、简单修改、轻量开发

**流程**：
1. **分析与设计** (System Designer, 合并需求+设计) → *用户确认*
2. **编码与测试** (Code Engineer, 边写边测) → 自动流转
3. **代码审查** (Code Reviewer) → *用户确认*
4. **集成验证** (Integration Validator) → 自动流转

**特点**：
- 4 阶段精简，减少子代理调用
- 非 TDD（边写代码边写测试）
- 无文档生成阶段
- 支持升级到 `/feature-dev` 完整模式

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

**使用示例**：
```
/light-dev 给文件管理器添加批量删除按钮
```

---

### `/fix-bug` — Bug 修复

**触发词**：修复 Bug、调试、报错、异常

**流程**：
1. **诊断分析** (System Designer, Opus) → *用户确认*
2. **修复与测试** (Code Engineer) → 自动流转
3. **代码审查** (Code Reviewer) → 自动流转
4. **集成验证** (Integration Validator) → 自动流转

**特点**：
- 只有 1 个确认点（诊断确认），后续自动流转
- 使用 Opus 模型进行诊断（强推理能力定位根因）
- 核心流程：复现 → 定位根因 → 修复 → 回归测试
- 审查重点：是否修复了根因而非症状

**Workspace**：`.claude/workspace/bugfix-YYYYMMDD-$NAME/`

**使用示例**：
```
/fix-bug 上传文件超时后没有显示错误提示
```

---

### `/test` — 独立测试

**触发词**：跑测试、运行测试、补充测试、测试覆盖率

**子命令**：

| 命令 | 用途 |
|------|------|
| `/test run [范围]` | 运行测试并报告结果（支持 frontend/backend/文件路径/模块名） |
| `/test cover [范围]` | 分析覆盖率，找出薄弱环节，可衔接补充测试 |
| `/test write [目标]` | 为已有代码编写测试（核心功能） |

**特点**：
- 独立于开发流程，可单独调用
- `run` 支持按范围（前端/后端/文件）和类型（unit/integration/e2e）灵活组合
- `write` 调用 Test Engineer 子代理设计测试用例，遵循项目测试规范
- `cover` 分析覆盖率后可直接衔接 `write` 补充测试
- 无 Workspace 目录，测试结果直接输出

**使用示例**：
```
/test run                      # 全量测试
/test run frontend             # 前端测试
/test run backend unit         # 后端单元测试
/test cover                    # 全量覆盖率
/test cover frontend           # 前端覆盖率
/test write src/services/api.ts  # 为指定文件补充测试
/test write                    # 自动选择覆盖率最低的文件补充
```

---

### `/context` — 上下文管理

**触发词**：保存上下文、加载上下文、查看上下文、清理对话记录

**子命令**：

| 命令 | 用途 |
|------|------|
| `/context save [名称]` | 保存当前对话上下文到 `.claude/context/<名称>.md` |
| `/context load [名称]` | 加载指定上下文到当前对话（新 session 的第一步） |
| `/context list` | 列出所有长期任务上下文（表格展示） |
| `/context remove [名称]` | 删除指定的上下文文件 |
| `/context clean` | 清理未被上下文引用的对话记录（transcript） |

**特点**：
- 解决跨对话的上下文丢失问题
- `load` 在新对话中显式恢复上下文，无名称时自动选择唯一上下文或让用户选
- 会话日志只追加不改写，当前状态每次覆盖
- `save` 无名称时自动建议名称
- `clean` 会保护当前对话和被引用的 transcript
- 同一对话多次 `save` 自动去重

**存储位置**：`.claude/context/<名称>.md`

**使用示例**：
```
/context save my-feature        # 保存上下文
/context load my-feature        # 新对话中加载上下文
/context list                   # 查看所有上下文
/context remove my-feature      # 删除不再需要的上下文
/context clean                  # 清理旧对话记录
```

---

### `/workspace` — Workspace 管理

**触发词**：查看 workspace、清理 workspace、workspace 列表

**子命令**：

| 命令 | 用途 |
|------|------|
| `/workspace list` | 列出所有 workspace，显示类型、日期、进度、大小、状态 |
| `/workspace clean` | 交互式清理已完成且未被引用的 workspace 目录 |

**特点**：
- 管理 `.claude/workspace/` 下的工作流产物目录
- `list` 自动识别目录类型（feature/bugfix/design）、推算进度阶段
- `clean` 保护进行中/待执行/已阻塞的任务目录，仅清理可安全删除的
- 已完成任务的 workspace 可以被清理（即使被 `_progress` 文件引用）
- `_progress-*.md` 文件和散文件不在清理范围内

**使用示例**：
```
/workspace list                 # 查看所有 workspace 目录
/workspace clean                # 交互式清理可清理的目录
```

---

### `/doc-dev` — 文档与模板开发

**触发词**：修改模板、更新文档、编写 Skill、修改工作流

**流程**：
1. **需求分析**（内联） → 自动流转
2. **设计计划**（内联） → *用户确认*
3. **编写实现**（内联） → 自动流转
4. **一致性扫描** (Doc Consistency Checker) → 自动流转
5. **文档审查** (Doc Reviewer) → *用户确认*

**特点**：
- 阶段 1-3 由主协调器内联执行，不调用子代理
- 阶段 4 一致性扫描是核心差异化（7 类跨文件一致性检查）
- 一致性检查 Agent 拥有修复权限，可自动修复 CRITICAL/HIGH 问题
- 阶段 5 文档审查聚焦内容质量（清晰度、准确性），而非代码质量

**Workspace**：`.claude/workspace/doc-YYYYMMDD-$NAME/`

**使用示例**：
```
/doc-dev 为工作流模板系统新增 doc-dev Skill
/doc-dev 更新 README 中的文件计数和命令列表
/doc-dev 优化 code-reviewer Agent 的 prompt
```

---

### `/init-workflow` — 工作流初始化

**触发词**：初始化工作流、安装工作流

**初始化模式**（`/init-workflow`）：
- **Phase 0**: 自动探测项目环境（语言、框架、工具）
- **Phase 0.5**: 如缺失 CLAUDE.md，自动生成并预填探测结果
- **Phase 0.7**: 验证 CLAUDE.md 完整性，引导补全缺失部分
- **Phase 1**: 扫描 CLAUDE.md + 推断 Capabilities（能力标签）
- **Phase 2**: 验证 CLAUDE.md 必需部分完整性，确认 Capabilities 节已存在且标签值合理
- **Phase 3**: 两遍处理生成定制化文件（Pass 1: IF 条件裁剪 → Pass 2: PROJECT-SPECIFIC 替换）
- **Phase 4**: 验证残留标记
- **Phase 5**: 输出报告

**升级模式**（`/init-workflow -u`）：
- **U0.5**: 配置同步（检测/生成/更新 Capabilities 节，不一致时交互询问用户）
- **U1-U5**: 版本对比 + 变更计划 + 语义合并 + 验证 + 报告

**特点**：
- 全自动项目环境探测，覆盖主流语言和框架的标志文件识别
- Capabilities 能力标签驱动条件化模板裁剪
- 升级模式支持增量更新，不覆盖用户定制内容

**使用示例**：
```
/init-workflow          # 首次初始化
/init-workflow -u       # 升级到新版本工作流
```

---

## 通用机制

### Workspace（工作记忆）

所有开发类 Skill 都使用 `.claude/workspace/` 目录存放阶段产物。每个任务一个独立目录，互不干扰。

### 中断恢复

每个阶段完成后会自动 `git commit`。恢复时指定 Workspace 路径和阶段号：
```
从阶段 4 恢复 feature-20260225-user-auth 的开发
```

### 多任务追踪

大型任务被 `/design` 拆分为多个子任务时，进度记录在 `.claude/workspace/_progress-$PROJECT.md`。说"继续做"会自动读取进度文件。

### 子代理模型

- System Designer 使用 **Opus**（架构设计和 Bug 诊断需要强推理）
- 其他子代理使用 **Sonnet**（含 Doc Consistency Checker 和 Doc Reviewer）
- 如无 Opus 权限，修改子代理文件中的 `model` 字段
