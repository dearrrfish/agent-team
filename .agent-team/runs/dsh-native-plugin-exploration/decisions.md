# Decisions

- 独立分支研究，不改变 .agent-team/runs/dsh-tui-feasibility 的任何产物或结论。
- 纯 DSH 原生路线可重新选择事实存储和 API，保留治理价值而非保持 Python CLI/文件布局的逐项兼容。
- 推荐自有交付领域服务 + Session events/projection，任务权威归领域服务；复用官方 subagent。官方 Team 可选显示投影，不同时作为可写任务权威；若未来复用其任务权威，必须先补齐所有 mutation 入口策略 seam。
- workflow 只作有界执行批次，不作持久工作流引擎；storageDomain 只存不进入模型上下文的宿主索引/设置。
- 门禁落在服务方法与明确的执行入口；tool guard 不能防止直接服务调用、任意 shell 或卸载插件。
- solo、当前工作区、仅文档，无 worker，无安装或外部代码运行。临时源码沿用上一轮 /tmp checkout。
