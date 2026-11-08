# Research Plan: dsh-TUI 支持可行性与插件生态研究

- Run: `dsh-tui-feasibility`
- Tier: `solo`
- Model preset: `balanced`
- Updated: `2026-11-08T05:04:00Z`

## Outcome

交付中文 research.md，包含事实核实、横向比较、插件深度评估、架构建议及可执行验收标准；不实现支持。

## Entry gates

- [x] Requirements approved：用户研究请求已授权上述范围
- [x] Worktree decision recorded：本地起始工作区干净；仅写研究产物，沿用当前工作区
- [x] Design approved or explicitly not required：不修改运行代码，不需要实现设计审批

## Changes

1. 固定 agent-team、dsh-TUI、官方 DSH 及候选插件 revision。
2. 阅读能力拥有层的源码，区分服务、provider、tool、默认组合和 UI 呈现。
3. 核实指令/技能发现、优先级、子会话继承与恢复；对比现有 adapter。
4. 对官方与社区插件给出复用边界和依赖风险。
5. 汇总研究与建议，记录限制，验证产物结构与来源，按本仓库约定提交持久报告。

## Public interfaces and types

无接口变更。文中所有新 target 名、插件和命令均标注为建议，不冒充现有实现。

## Failure, migration, and rollback

外部检索失败时记录未知与替代一手来源。研究不触发安装、迁移或配置写入；本轮没有运行时 rollback。后续实施需独立处理配置备份、安装归属及恢复。

## Verification matrix

| Requirement | Verification |
| --- | --- |
| FR-001 | 本仓库 adapter/config/run/installer 源码与 README 交叉核对 |
| FR-002 | 固定 revision 的 DSH/dsh-TUI 源码及文档定位 |
| FR-003 | 区分本仓库验证状态、官方文档与本轮实测 |
| FR-004 | GitHub 元数据、许可证、源码及 API 兼容核对 |
| FR-005 | 对照需求逐项检查报告；不把建议当成已实现 |
| NFR-001/002/003 | 来源索引、限制说明、git diff --check、PYTHONPATH=src python3 -m agent_team validate |

## Documentation

研究、来源与最终报告均写入 .agent-team/runs/dsh-tui-feasibility/，避免在 docs 下制造第二套执行记录。

## Assumptions and defaults

默认采用 solo，减少纯研究协调开销。优先读取官方包和被指定仓库实际源码，不运行其脚本。比较商业客户端时使用本仓库现有适配证据并补充官方文档，不依据开闭源标签推断运行机制。
