# Plan: DSH 原生插件路线独立初探

## Decision-complete research plan

1. 固定 DSH fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159，读取 architecture/Cordis primer、Team、workflow、Session projections、domain storage、tools 与 plugin-manager 的能力拥有层文档。
2. 把 agent-team 的角色、任务、阶段、验证和恢复分别映射到这些能力；区分可直接组合、需新增领域服务、需上游 seam 的部分。
3. 比较复用官方 Team 与自有领域任务状态的边界，提出本分支内部唯一权威方案；无需与前研究方案一致。
4. 写独立 exploration.md，包含异常语义、原型验证切口、取舍和固定来源；只作初探，不编写插件。
5. 核对固定源码路径、run/project validation、git diff whitespace；按规则本地提交并通过 AskHuman 附件交付。

## Defaults and gates

用户研究请求即范围授权；solo 无 worker、无需独立 reviewer。沿用当前干净起始工作区，只新增独立 run 研究工件。无生产代码/公开接口变更，无实施设计审批。外部代码只读不执行。

## Verification limits

live_validation 仅指本轮研究产物的实际路径/结构/whitespace 检查；不代表 DSH 运行验证。完整单元测试、Nix check 无法证明原生插件可运行，因此不作此轮适用检查。
