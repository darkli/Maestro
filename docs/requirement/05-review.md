# 代码审查报告 — Codex 字段修复验证

**审查日期**: 2026-02-27
**审查范围**: CodingToolConfig Codex 专用字段（本轮修复）
**审查文件**:
- `src/maestro/config.py` — CodingToolConfig dataclass 新增字段
- `config.example.yaml` — Codex 配置文档
- `src/maestro/tool_runner.py` — 字段实际使用处（参考）

---

## 审查摘要表

| 级别 | 数量 | 说明 |
|------|------|------|
| Critical | 0 | — |
| High | 0 | 旧 HIGH 问题已确认修复 |
| Medium | 2 | `getattr` 防御性写法残留、`model` 字段命名冲突隐患 |
| Low | 1 | `config.example.yaml` Codex 专用模式示例缺失 `skip_git_check` |
| Info | 2 | 省略字段理由分析、定价表更新建议 |

**整体评估**: APPROVE WITH COMMENTS

---

## 一、旧 HIGH 问题确认

### 原问题：CodingToolConfig 缺少 6 个 Codex 字段

上一轮标记为 HIGH 的 6 个字段（sandbox, approval_mode, model, output_schema, skip_git_check, ephemeral），本轮修复结论如下：

| 字段 | 处置方式 | 确认状态 |
|------|----------|----------|
| `sandbox` | 新增到 dataclass，类型 `str`，默认 `""` | **已修复，正确** |
| `model` | 新增到 dataclass，类型 `str`，默认 `""` | **已修复，正确**（见 Medium 问题 [CR-002]）|
| `skip_git_check` | 新增到 dataclass，类型 `bool`，默认 `False` | **已修复，正确** |
| `approval_mode` | 省略，理由：Codex `--full-auto` 已由现有 `auto_approve` 字段覆盖 | **省略合理**（见 Info [CR-004]）|
| `output_schema` | 省略，理由：Codex CLI 无 `--output-schema` 参数 | **省略合理** |
| `ephemeral` | 省略，理由：Codex CLI 无 `--ephemeral` 参数 | **省略合理** |

**结论：HIGH 问题已修复。3 个字段正确添加，3 个省略理由成立。**

---

## 二、详细发现

### [CR-001] Medium — `getattr` 防御性写法冗余，掩盖潜在逻辑错误

**文件**: `src/maestro/tool_runner.py` 第 533-537 行

**问题描述**:

```python
if getattr(self.config, 'sandbox', '') and self.config.sandbox:
    cmd.extend(["--sandbox", self.config.sandbox])
if getattr(self.config, 'model', '') and self.config.model:
    cmd.extend(["--model", self.config.model])
if getattr(self.config, 'skip_git_check', False) and self.config.skip_git_check:
    cmd.append("--skip-git-check")
```

`getattr` 的存在说明这段代码编写时，三个字段尚未在 `CodingToolConfig` 中定义，属于向前兼容的临时写法。现在三个字段已正式加入 dataclass，`getattr` 包装层已无必要，且产生了两个负面效果：

1. **双重求值**：`getattr(self.config, 'sandbox', '')` 和 `self.config.sandbox` 连续取同一属性，代码啰嗦。
2. **逻辑冗余遮蔽**：若未来开发者删除 dataclass 字段时，`getattr` 的默认值会静默吞掉 AttributeError，导致参数无声失效，极难排查。

**影响**: 纯代码质量问题，当前无功能 Bug，但会积累技术债。

**修复建议**（`tool_runner.py` 不在本次配置审查范围，作为建议记录）:

```python
if self.config.sandbox:
    cmd.extend(["--sandbox", self.config.sandbox])
if self.config.model:
    cmd.extend(["--model", self.config.model])
if self.config.skip_git_check:
    cmd.append("--skip-git-check")
```

---

### [CR-002] Medium — `model` 字段与 `ManagerConfig.model` 存在命名语义歧义

**文件**: `src/maestro/config.py` 第 89 行

**问题描述**:

`CodingToolConfig.model` 与 `ManagerConfig.model` 字段同名，含义不同：

- `ManagerConfig.model`：Manager Agent 所用的 LLM 模型（如 `deepseek-chat`）
- `CodingToolConfig.model`：Codex CLI 所用的编码模型（如 `codex-mini-latest`）

在以下场景中存在混淆风险：

1. **阅读 `_estimate_codex_cost`**（tool_runner.py 第 741 行）时，`self.config.model` 查定价表，但读者需要额外确认这是 coding tool 的 config 而非 manager 的 config。
2. **日志/调试**：若日志系统将配置序列化输出，两个 `model` 字段并列出现，调试时容易混淆。
3. **未来扩展**：若将来在 `CodingToolConfig` 中加入 `manager_model_override` 等字段，`model` 的含义会更加模糊。

**当前代码中无 Bug**，但命名清晰性值得改进。

**修复建议（可选）**: 若未来 Codex 以外的 generic 工具也需要指定模型，可考虑将字段名改为 `codex_model` 以明确作用域。但考虑到与 Codex CLI 参数名 `--model` 的对应关系，当前命名亦有合理性，可保持现状但在注释中加以区分。

---

### [CR-003] Low — config.example.yaml Codex 专用模式示例缺少 `skip_git_check`

**文件**: `config.example.yaml` 第 127-133 行

**问题描述**:

Codex CLI 专用模式的注释示例：

```yaml
# OpenAI Codex CLI（推荐：专用模式，支持 JSONL 输出解析、会话恢复、费用估算）:
# type: codex
# command: codex
# auto_approve: true       # 对应 --full-auto
# sandbox: net-disabled    # 沙箱级别
# model: codex-mini-latest # 模型名
# timeout: 600
```

该示例展示了 `sandbox` 和 `model`，但遗漏了 `skip_git_check`。虽然 `skip_git_check` 在独立的注释块中已说明（第 122-123 行），但用户在复制示例配置时可能遗漏此字段，且示例的完整性有助于理解可用配置组合。

**修复建议**:

```yaml
# OpenAI Codex CLI（推荐：专用模式）:
# type: codex
# command: codex
# auto_approve: true        # 对应 --full-auto
# sandbox: net-disabled     # 沙箱级别
# model: codex-mini-latest  # 模型名
# skip_git_check: false     # 是否跳过 git 仓库检查
# timeout: 600
```

---

### [CR-004] Info — `approval_mode` 省略理由确认

**问题**: 上一轮标记的 `approval_mode` 字段是否需要单独实现。

**分析**:

Codex CLI 的 `--approval-mode` 参数（可选值 `full-auto` / `auto-edit` / `suggest`）与 Maestro 的 `auto_approve` 字段存在以下映射关系：

- `auto_approve: true` → 传递 `--full-auto`（对应 `approval_mode=full-auto`）
- `auto_approve: false` → 不传递 `--full-auto`（Codex 默认为交互模式）

当前实现中，`tool_runner.py` 第 531-532 行：

```python
if self.config.auto_approve:
    cmd.append("--full-auto")
```

这覆盖了 Codex 最常用的自动化场景（Maestro 作为无人值守 Agent，几乎总需 full-auto）。`auto-edit` 和 `suggest` 模式在 Maestro 自动化场景中无实际用途（需要人工交互）。

**结论**: 省略 `approval_mode` 独立字段合理，现有 `auto_approve` 布尔值已满足需求。如未来需要精细控制，可届时扩展为枚举字段。

---

### [CR-005] Info — Codex 定价表可能需要更新

**文件**: `src/maestro/tool_runner.py` 第 724-730 行

**问题描述**:

```python
_CODEX_PRICING = {
    "codex-mini-latest": (1.50, 6.00),
    "codex-mini":        (1.50, 6.00),
    "o3":                (2.00, 8.00),
    "o4-mini":           (1.10, 4.40),
}
```

此定价表为硬编码，OpenAI 定价随时可能调整。目前 `o3` 定价（$2.00/$8.00 per M tokens）与 OpenAI 官方页面的实际定价存在差异（o3 实际定价为 $10.00/$40.00 per M tokens，属于推理模型高价位）。这会导致费用估算严重低估。

**注意**: 这是 `tool_runner.py` 的问题，不在本次配置字段审查范围内，仅作信息记录。

---

## 三、`_dict_to_dataclass` 兼容性确认

**文件**: `src/maestro/config.py` 第 144-150 行

```python
def _dict_to_dataclass(dc_class, data: dict):
    """将字典映射到 dataclass，忽略未知字段"""
    if not data:
        return dc_class()
    valid_fields = {f.name for f in dc_class.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return dc_class(**filtered)
```

**确认结论**: 可以正确处理新增的三个字段。

- 若用户在 `config.yaml` 中填写了 `sandbox`、`model`、`skip_git_check`，它们会出现在 `data` 字典中，通过 `valid_fields` 过滤后传入 `CodingToolConfig(**filtered)`，正确赋值。
- 若用户未填写，`filtered` 中无对应键，dataclass 使用字段默认值（`""`, `""`, `False`），行为正确。
- `skip_git_check` 从 YAML 读取时为 Python `bool`（PyYAML 会将 `false` 解析为 `False`），与 dataclass 字段类型匹配，无需额外转换。

**无问题。**

---

## 四、新增字段定义逐项核对

| 字段 | 类型 | 默认值 | 注释准确性 | 结论 |
|------|------|--------|-----------|------|
| `sandbox` | `str` | `""` | "Codex 沙箱级别: full \| net-disabled \| off（空=使用 Codex 默认）" — 准确 | 正确 |
| `model` | `str` | `""` | "Codex 模型名（如 codex-mini-latest, o3, o4-mini；空=使用 Codex 默认）" — 准确 | 正确 |
| `skip_git_check` | `bool` | `False` | "Codex: --skip-git-check（跳过 git 仓库检查）" — 准确 | 正确 |

**三个字段的类型、默认值、注释均正确无误。**

---

## 五、config.example.yaml 文档质量核对

| 检查项 | 结论 |
|--------|------|
| `sandbox` 说明（full/net-disabled/off 枚举值）| 完整，正确 |
| `model` 说明（可选值示例）| 完整，正确 |
| `skip_git_check` 说明 | 存在但过于简单（仅一行注释）|
| Codex 专用模式完整示例 | 缺少 `skip_git_check`（Low [CR-003]）|
| `auto_approve` 注释与 Codex 的对应关系 | 第 104 行注释"Claude Code 专用"，未提及 Codex 也使用此字段，存在误导性 |

**补充发现 [CR-006] Low**: `config.example.yaml` 第 104-105 行注释：

```yaml
# Claude Code 专用: 自动跳过权限确认（--dangerously-skip-permissions）
auto_approve: true
```

此注释将 `auto_approve` 标记为"Claude Code 专用"，但实际上 Codex 模式下 `auto_approve: true` 会触发 `--full-auto` 参数。建议将注释改为：

```yaml
# 自动批准模式:
#   Claude Code: --dangerously-skip-permissions
#   Codex CLI:   --full-auto
auto_approve: true
```

---

## 六、修复优先级建议

| 优先级 | 问题 | 操作 |
|--------|------|------|
| 1（建议）| [CR-001] `getattr` 冗余写法 | 在 `tool_runner.py` 中直接使用 `self.config.sandbox` 等字段 |
| 2（建议）| [CR-006] `auto_approve` 注释误导 | 更新 `config.example.yaml` 注释 |
| 3（建议）| [CR-003] 示例缺 `skip_git_check` | 补充到 Codex 专用示例 |
| 4（可选）| [CR-002] `model` 字段命名歧义 | 视未来扩展决定是否重命名 |
| 5（参考）| [CR-005] 定价表错误 | 校对 o3 定价数据 |

---

## 下游摘要

### 整体评估
APPROVE WITH COMMENTS

### 未修复问题
#### Critical
无

#### High
无（上一轮 HIGH 问题已全部修复或合理省略）

#### Medium
- [CR-001] `tool_runner.py` 中 `getattr` 防御性写法冗余，新字段正式落地后应清理
- [CR-002] `CodingToolConfig.model` 与 `ManagerConfig.model` 同名，语义歧义，建议注释明确或未来重命名

### 修复建议
无 REQUEST CHANGES 项。以下为可选改进，不阻塞合并：

1. 在 `tool_runner.py` 将 `getattr(self.config, 'sandbox', '')` 等三处替换为直接属性访问（需在下一次修改 `tool_runner.py` 时顺手处理）
2. 在 `config.example.yaml` 的 `auto_approve` 注释中补充 Codex CLI 对应参数 `--full-auto`，避免用户误以为该字段仅 Claude 生效
3. 在 Codex 专用模式示例中补充 `skip_git_check: false`
