# Final report: DSH 原生插件路线独立初探

## Outcome

已完成独立分支初探，详见 exploration.md。前一研究目录完全未改动，结论不并入、不替换。

结论：纯 DSH 原生路线技术可行，架构契合度高；适合将 agent-team 重构为交付治理领域服务，以 Cordis 插件、Session 事实事件/投影、受控工具和官方 subagent 组合，而非包装跨工具 CLI。

推荐原型以单 owner Session 和自有交付领域状态为权威；官方 Team 可作可选投影。若希望直接以官方任务板为权威，需要明确 completed 与验收通过的区别，或补足所有 mutation 的公开策略 seam。

## Findings

- 保留角色、门禁、所有权、验证与独立评审，允许放弃多 target/Python CLI/run.toml 的逐项兼容。
- workflow 是有界执行引擎，不是持久 run 状态机；storageDomain 是宿主设置/索引，不应替代模型相关事实的 Session 事件。
- 工具 guard 不是全局 sandbox；确定性政策应落在 service，并明确受管执行范围。
- intent/activation/persistence 的未知结果、重启/fork/配置漂移、卸载和并发 admission 是真正的工程难点。
- 若只需要多 agent 与任务板，官方 Team 已很接近，重复开发价值有限；原生路线须证明交付治理的增量。

## Verification

15 个固定官方源码路径已核对存在；前研究目录相对 HEAD 无差异。run/project validation、staged/unstaged whitespace 检查均已通过；可记录的命令结果见 run verification evidence。

本轮没有实施、安装、模型调用或故障恢复实测；不宣称生产兼容。仅文档变更，不运行与结论无关的完整单元测试/Nix 构建。

## Defaults

solo、max_workers=0、沿用当前工作区、复用固定只读源码；无 worker、无实现、未创建未接受的实施 todo。全部产物位于独立 run。
