# Requirements: DSH 原生插件路线独立初探

用户通过上一任务 AskHuman 交接提出：忽略跨工具兼容性，仅针对 DSH 生态、遵循完整插件哲学，研究 agent-team 引入的可行性和契合度；仅作未来另一条路径初探，不改变、不并入前一研究结论。

## Scope and acceptance

- 说明 all-plugin 架构下的产品形态与本项目价值取舍。
- 比较官方 Team、workflow、Session projections、storageDomain、tools 与 plugin-manager 的实际契约。
- 给出唯一状态权威、事件/恢复、门禁/权限、卸载/崩溃和可选 TUI 的设计边界。
- 形成独立中文报告，固定源码 revision，区分事实与建议、静态结论与未验收运行行为。

## Constraints

solo，max_workers=0；不开发或安装插件，不执行外部代码，不修改用户配置，不重写前一报告。直接使用已固定的官方 DSH 源码；本轮不需要扩展新的社区插件全景调查。未授权的后续实施不加入 todo。

## Non-goals

没有跨工具迁移要求；没有生产就绪、性能、可靠恢复或真实模型运行的认证；没有实施估时承诺。
