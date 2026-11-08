# Final report: dsh-TUI 支持可行性与插件生态研究

## Outcome

研究已完成，详细中文报告见同目录 research.md。结论：可行，建议作为实验性支持目标，优先开发 DSH 原生适配并认证指定 dsh-TUI 的 DSH backend；先 solo，再 assisted，最后验证隔离与恢复后开放 team。

本轮使用 team-workflow、team-plan 技能组织 solo 研究；没有子 agent、安装、实现或真实模型调用。沿用干净起始工作区，运行文件保持项目默认目录。

## Findings

- 当前官方 DSH 已有 subagent 服务、spawn/fork 等 provider、实验性 worktree 和同名 Team；“全部需要社区插件”不成立。
- 指令与技能有官方默认加载，但角色 preset 不自动扫描 agent Markdown 目录；工具、模型与 cwd 是否可用取决于有效 profile/preset 和权限。
- 指定 dsh-TUI 已有多个 backend，DSH 插件不自动跨 Claude/Codex backend 生效。
- 官方同名 dsh-agent-team 与本项目不是同一系统；会话日志任务板不能未经协议设计与 run 文件并列为可写权威。
- 五个社区插件逐项评估后，未发现必须依赖的候选；有旧 API、独立 DAG、自动收集提交及清理风险。风险描述有固定源码依据，未冒充运行复现。

## Deliverables

research.md：核心定位、起始假设核实、指令/技能/模型/委派/隔离/恢复映射、五类客户端横向比较、五个社区插件分析、架构建议、分阶段准入和固定 revision 来源。
requirements.md、plan.md、decisions.md、run.toml：本轮范围、计划、决策与状态。

## Verification

已核对 23 个固定 revision 来源路径，均存在于对应仓库 Git objects。`PYTHONPATH=src python3 -m agent_team validate` 已通过；初次检查发现研究 run 的 worktree_decision 使用了非枚举值，已改成 current-checkout 后重新通过，失败记录予以保留。`git diff --cached --check` 已通过，最终 unstaged whitespace check 也通过。仅研究产物变更，不需要通过完整单元测试或 Nix 构建来证明宿主兼容。没有运行 DSH/TUI 集成、插件测试或真实模型验收。

## Limitations and follow-up

正式支持需要单独实施 DSH target，并按 research.md 阶段 A–D 真实验收。模型路由、子 scope 权限、异步完成、worktree 实际写入与恢复仍是运行时未知项。用户本轮没有接受实施或延期事项，因此没有擅自创建项目 todo。

## Rollback

本轮仅新增研究工件，无配置、安装或公开接口变更；没有运行时迁移或回滚要求。
