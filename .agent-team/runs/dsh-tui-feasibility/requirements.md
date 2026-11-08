# Requirements: dsh-TUI 支持可行性与插件生态研究

- Run: `dsh-tui-feasibility`
- Tier: `solo`
- Created: `2026-11-08T05:01:59Z`
- Updated: `2026-11-08T05:04:00Z`

## Summary

研究 agent-team 纳入 dsh-TUI 支持的可行性、契约映射、插件依赖与分阶段路径，以源码和一手文档核实用户提出的起始假设。

## Users and use cases

面向在 dsh-TUI 中使用 agent-team 的开发者及适配器维护者；覆盖独立协调、只读委派、隔离并发写入、跨会话恢复和跨工具迁移。

## Functional requirements

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| FR-001 | 核实 agent-team 核心定位与软硬约束边界 | 本仓库实现与文档定位 |
| FR-002 | 核实 DSH/dsh-TUI 的关系、上下文加载、技能、角色、模型、委派、隔离、恢复 | 固定 revision 的一手源码 |
| FR-003 | 与 Pi、Claude Code、Codex、Antigravity 横向比较 | 标注证据等级及未知项的矩阵 |
| FR-004 | 深入评估官方与相关社区插件，提出复用/结合/替代边界 | 许可证、维护信号、API 和冲突分析 |
| FR-005 | 给出适配架构、支持等级、验收条件和分阶段建议 | 完整研究报告 |

## Non-functional requirements

| ID | Requirement | Acceptance evidence |
| --- | --- | --- |
| NFR-001 | 区分源码静态结论、文档声明、推断与未验证运行行为 | 来源索引与验证限制 |
| NFR-002 | 不安装或执行外部项目代码、不修改用户配置 | 研究采用只读源码检索 |
| NFR-003 | 结果可复核且持久化 | 固定 Git revision、源码链接、本地报告 |

## Constraints and assumptions

用户授权的是研究，未授权实现、安装或发布。以指定的 ccch1mneyyy/dsh-TUI 为主要目标，兼顾官方 DSH；不把同名仓库当作同一项目。插件选择优先官方，其次结合活跃程度与契约覆盖判断，不能仅按 star 排名。solo 用于协调者统一完成源码调查，不启动 worker。

## Failure cases

检索过时、README 与实现不同、配置存在但未加载、子 agent 未继承上下文、跨 backend 错配、插件动态变更和 worktree 回收失败均需明确暴露；未知能力不能作为已支持能力。

## Non-goals

本轮不开发 adapter 或插件，不改变公开接口，不安装 dsh，不执行模型付费调用，不宣称真实 TUI 运行验收通过。

## Open questions

运行时兼容性与真实模型验收留作报告中的准入条件，不阻塞本轮研究交付。

## Sources

本仓库 README、src/agent_team、docs；https://github.com/ccch1mneyyy/dsh-TUI；https://github.com/deepseek-ai/deepseek-harness；检索发现的相关插件原始仓库。固定 revision 与具体路径在 research.md 中记录。
