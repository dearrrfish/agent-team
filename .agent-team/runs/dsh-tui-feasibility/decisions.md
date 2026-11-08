# Decisions

- D1：按用户请求完成研究，不实现/安装 DSH 支持。使用 solo、当前干净起始工作区，max_workers=0，无 worker，独立评审不要求。
- D2：以指定 ccch1mneyyy/dsh-TUI 的 DSH backend 为主要支持对象，独立 DSH 为兼顾路径；同名其他 TUI 不混同，其他 backend 不默认继承 DSH 插件能力。
- D3：建议新增 DSH 原生适配，先复用官方 instructions/skills/preset/subagent，worktree 单独验收；必要时用薄插件弥合 admission、事件与身份，不重建通用调度。
- D4：本项目 run 文件保留唯一任务权威，不默认叠加官方同名 Team 或社区 DAG 的可写状态。
- D5：社区维护信号弱且 API 有演进；不把旧版插件设为必要依赖。CSY656 清理风险仅为静态源码判断，明确没有运行复现。
- D6：研究产物的有效验证为本地来源路径/固定 revision 核对、项目/run validation 与 whitespace check。live_validation gate 表示本轮研究产物的实际检查，不表示真实 DSH 运行已验证。
- D7：持久研究报告与执行摘要按仓库规则显式纳入 Git；临时外部源码位于 /tmp，仅用于只读研究，不复制入仓库、不执行、不安装。
