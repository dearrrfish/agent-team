# DSH 原生 agent-team：独立路线初探

本报告回应新增的分支问题：**不考虑跨工具兼容性，只针对 DSH 生态，完整遵循插件哲学，agent-team 应如何存在？** 它不改写、不并入上一份《dsh-TUI 支持可行性研究》。此前“跨工具 run 文件为权威、薄适配”的结论仍适用于此前问题；本报告允许重新选择状态和执行契约。

证据为官方 DSH revision `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159` 的架构、服务源码和文档。本轮不安装、不开发、不执行外部代码，也没有真实模型或故障恢复验收。下面的插件划分、事件名和 API 都是**设计建议，不是已存在的功能**。

## 1. 判断：技术可行，哲学契合度高，但产品边界必须收窄

最自然的形态不是把 Python CLI 封装成一个工具，而是**一个 DSH 原生的交付治理插件族**：管理“什么工作获得授权、谁可以执行、何时可以进入下一阶段、什么证据足以认定完成”。DSH 继续拥有模型循环、子会话、工具系统和宿主能力。

这条路线与官方架构高度契合。官方明确要求产品层以 Cordis 插件、服务与可逆 effects 组合；新增领域应拥有自己的事实事件、投影和面向调用者的工具，而不是修改一个特权核心。[S1–S3] agent-team 的阶段、所有权、预算、评审和验收恰好是可以独立建模的领域。

但若目标只是“多个 agent、任务依赖、互相发消息”，官方 Team + subagent 已覆盖大部分价值，另写一个 agent-team 的必要性低。真正值得引入的是**交付治理**：需求与计划门禁、明确的写入所有权、证据随 revision 失效、独立评审、异常恢复和可解释的结束条件。

| 判断维度 | 原生路线评价 | 原因 |
| --- | --- | --- |
| 架构契合 | 高 | 领域 service、Session events/projections、tools 是官方扩展范式 |
| 基础执行可行性 | 高 | 官方已有子 agent、路由、工具和可选 workflow |
| 完整治理可直接复用程度 | 中低 | 官方 Team 不是交付状态机，workflow 不是持久引擎 |
| 需要新增的核心复杂度 | 明确存在 | admission、状态转换、证据、异常一致性和恢复 |
| 初步产品价值 | 有条件成立 | 必须超出任务板，并接受 DSH 专用与 RC API 演进成本 |
| 当前可认证程度 | 仅源码初探 | 无原型、运行或恢复实测 |

“哲学一致”不会自动消除复杂度。放弃跨工具兼容可以去掉适配器层与文件协议负担，但分布在多次模型调用中的副作用、任务所有权和恢复依然需要设计。

## 2. 保留什么，放弃什么

保留 agent-team 的**语义价值**：角色分工、solo/assisted/team 的协调政策、任务依赖、所有权与预算、需求/设计/计划/实现/评审阶段、验证证据和恢复规则。

允许放弃其**跨工具包装**：不必保留多 target 生成器、客户端原生目录映射、Python CLI 作为唯一控制面、所有状态必须写 run.toml、每个契约都靠 Markdown 提示执行。Markdown 仍适合需求、设计、理由和报告，但不能作为插件必须从头解析的唯一机器状态。

在纯原生方案中，确定性的门禁应进入 service 方法；技能负责教模型如何使用服务。报告、设计文档可以作为有 hash 的外部工件，事件记录它们的身份与摘要。用户能从 UI、工具或 API 操作同一服务，行为应一致。

这属于一个新的原生实现，而非低成本把现有 Python 包换个入口。可复用流程规范、测试场景和文案，不能假设直接复用其状态模型就自然符合 DSH 的 Session 权威。

## 3. DSH 已提供哪些基础，缺口在哪里

| 官方能力 | 可复用部分 | 不能推断具备的部分 |
| --- | --- | --- |
| Team | lead 根会话、任务 ID、CAS revision、依赖校验、成员与消息关系 | 完整阶段门禁、验证证据、独立评审、文件锁、跨进程事务 |
| subagent | spawn/fork、provider、activation、控制与会话延续 | 自动 run admission、所有写路径限制、所有 provider 同等持久性 |
| workflow / workflow-ptc | 有界脚本 fan-out、取消、内部 child 收集 | 持久调度/断点恢复、严格配额、网络隔离、可重放外部副作用 |
| Session projections | 领域事件到确定性状态、checkpoint、asOfSeq | 跨会话/跨文件事务、自动业务 migration 或任务存活证明 |
| storageDomain | schema 校验的宿主设置/索引、域内写入序列 | 模型事实的会话日志、跨表事务、跨进程可见性 |
| tools guard/restrict | 原生与 PTC inner tool pipeline 的拒绝与可见性 | shell/direct Node/直接服务调用的全局拦截、OS sandbox |
| plugin-manager | 安装/启用/配置/卸载、依赖与部分热更新 | 插件已装就一定有效、卸载后治理继续成立、全局单例锁 |

这些差异来自官方实现边界，而非本项目的命名选择。[S3–S9]

## 4. 推荐形态：一个领域服务，多个可组合入口

建议先把生命周期做成一个语义完整的服务插件；提示、执行桥和 UI 可以分离。无须一开始拆成十几个包，也无需新的通用插件框架。

| 组件（建议名称） | 职责 | 依赖/限制 |
| --- | --- | --- |
| delivery-domain | run/task/ownership/admission、阶段转换、证据与评审 verdict；注册事件和投影 | Session persistence/projections，服务唯一写入口 |
| delivery-tools | 向模型暴露有 schema 的 plan/claim/start/report/verify/advance 等操作 | 调领域服务，不自行改状态 |
| delivery-execution | 绑定 task 与 subagent activation，实施并发 admission、报告收集、取消与恢复核验 | 官方 subagent，workflow 可选 |
| delivery-presets 与 skills | 注册六角色，绑定模型、工具与委派深度，描述协作协议 | preset/skills registry，不能仅靠正文只读声明 |
| delivery-tui（可选） | 门禁、任务和当前证据的只读视图或受控操作入口 | TUI 插件 API；UI 不构成另一套状态 |
| delivery-bundle/profile | 组合依赖、默认能力和可选组件 | 官方 profile 启动，不另写绕过宿主的运行器 |

配置遵循 DSH 的 bundle/profile/patch 层级。整行 config replacement 与 scope 的真实语义需要体现在安装与预检里；不要假设无条件深合并。service 通过 Cordis inject 等待依赖，从 `agent.ctx` 解析正确 scope，禁止直接跨插件读取私有内存或 monkeypatch 官方 taskboard。

这比“everything is a prompt”更符合 DSH，也比“所有功能集中到一个万能工具”更易于验证。

## 5. 最关键的设计选择：只保留一个可写事实源

纯原生路线可以选择两种权威，不能两边都写。

### 方案 A：官方 Team 是任务权威，插件只做交付政策

优点是复用官方任务 ID、成员权限、CAS 和 UI，避免重复任务板。领域服务只保存阶段、证据与评审，并在 task ID 上关联。

阻碍是**官方 Team 当前没有足够的公开策略拦截 seam**：成员、工具和内部 service 可以通过其合法 API 更新任务。只包装几个工具不能保证所有 mutation 都经过交付门禁，也不能把“completed”稳定定义成“验证/评审已通过”。[S3、S6]

适用两种条件：接受 completed 仅表示“工作者报告结束”、交付批准是另一个清楚区分的状态；或者先向上游增加公开的 mutation policy/扩展协议，并证明所有入口遵循。不要依赖私有 taskboard 或覆盖方法。

### 方案 B：原生交付领域服务拥有 run/task，官方 Team 可选投影

它能定义完整状态机、权限与失败语义；subagent 仍复用官方，不启用第二套可写任务板。模型和 UI 通过交付服务操作，官方 Team 若要展示只做单向投影并标识新鲜度。

代价是需要实现任务 ID、依赖、CAS 和恢复等领域逻辑，不能声称“原样复用全部官方 Team”。但这不是违反插件哲学：官方支持新增独立领域服务，哲学要求职责与事实权威清晰，并非所有团队应用都必须把官方任务板作为数据库。

**本次初探推荐 B 作为严格治理的原型基线。** 若未来上游提供足够策略 seam，再重新评估 A。若产品愿意降低强制治理要求，A 也可以是更轻的“官方 Team 治理助手”，但应使用不同的支持承诺。

## 6. Session 原生持久化：事实、投影与工件各归其位

建议每个 delivery run 显式绑定一个 owner/root Session，模型相关的 run 创建、任务分配、执行 intent、结果、检查和阶段变更都成为该会话的领域事件。投影用纯同步 reducer 推导状态，暴露 snapshot + asOfSeq，携带 stateVersion。注册必须 await；无关事件保持原对象，避免无效 checkpoint。[S2、S4]

示意事件可以包括 run-opened、plan-accepted、task-admitted、activation-bound、task-result-recorded、check-recorded、review-recorded、phase-advanced；这些名称尚不存在。事件应携带足够重建状态的业务事实和版本，而不是要求恢复时查询已经消失的临时对象。

| 信息 | 建议位置 |
| --- | --- |
| 模型必须知道的任务/门禁/验收事实 | owner Session 领域事件 + 投影 |
| 需求、设计、完整报告、测试原始日志 | 受管理工件；事件保留 path/URI、hash、摘要与版本 |
| 宿主私有设置、run 索引、用户 UI 偏好 | storageDomain；必要时索引可重建 |
| worker 即时进度、动画、通知 | live events；不能单独作为完成证据 |
| 活跃进程句柄、取消 signal | 内存资源；恢复后重新核验 |

storageDomain 官方定义就是不属于模型上下文的 host domain state；它先持久化再发布内存和变更通知，但没有跨表事务和跨进程同步。遇到 unknown-state 会隔离域直到重新打开。[S8] 因而不适合把交付事实只存这里，再向模型临时注入一份“看起来同步”的状态。

会话 fork 复制历史不等于授予同一 run 的写权。worker 分支只能向 owner 提交授权范围的报告；fork 新协调者、owner 不可恢复、删除会话、截断/撤销历史都需要明确规则。原型先限定单 owner、单协调进程，缺失 owner 即暂停；不要未经设计把继承来的 task-admitted 事件当作当前有效执行许可。

## 7. 一致性与副作用：日志不是魔法事务

Session append/flush 与外部任务启动并非同一个事务。应先提交可识别的 dispatch intent，分配稳定 attempt ID，再调用 subagent，随后绑定 activation；恢复时对“intent 已记但 activation 未确认”查询和核对，不能直接再启动一次。若官方 provider 不提供足够查询或幂等键，必须保留 unknown 并人工/显式恢复；不能承诺 exactly-once。

官方 Team 已暴露 `TEAM_TASK_PERSISTENCE_UNCONFIRMED` 这类“可见但未确认持久”的失败，说明连任务板本身也需要读后核对，不能一律重试。原生领域服务也应区分 not-written、confirmed、unknown；返回失败不等于没有副作用。

同样，运行检查完成到记录 hash 之间仓库可能变化。检查应绑定实际观测 revision、tracked/untracked diff 和工件 hash；观测前后不一致就标 unbound/stale。不能仅相信 worker 发来的“all tests passed”。评审 verdict 也绑定同一对象，修改后按政策失效。

并发控制至少两层：领域服务在提交 task-admitted 时检查 run.max_workers/ownership；执行层在实际启动时核对宿主 capacity。不能先启动四个 child 再写两份 admission。初版单进程用串行状态转换与 expectedRevision；多进程不是增加一个内存 mutex 就能支持，需要另外的 owner lease/锁及一致性机制。

## 8. 门禁应该多硬：服务内保证，执行路径明确

每个公开 mutation 方法都应检查身份、角色、run 状态、expectedRevision、所有权和所需证据，拒绝非法转换。工具、TUI、RPC 只是这些方法的入口，不能各自实现一份政策。

工具层仍有用：`ctx.tools.guard` 在可重排 pre-execute 后执行，shared pipeline 中的 deny 不会被后来的 listener 撤销；restrict 用于减少工具可见性。[S6] 但它无法阻止直接调用 service、shell 读写、任意 Node 插件或主动绕过 pipeline 的 executor。`when` 主要按步骤评估可见性，不适合代替执行时事务检查。

因此支持承诺应明确为：**通过受管服务/执行路径的交付操作有确定性门禁**。如果要“禁止未获批的任何文件写入”，需要宿主工具策略和 sandbox 的额外保障，角色 prompt 及工具 guard 都不足以单独证明。

只读 reviewer 的权限在它自身 preset 中配置，不能只依赖父 agent 的局部限制。禁止递归委派、模型路由、cwd/worktree 和预算同样通过实际 child scope 与 admission 约束。对独立评审，还需验证 reviewer 不是实现者同一 activation、自评不能满足门禁、证据身份一致；不是把自动 action-risk 审批叫作代码评审。

官方 experimental auto-review 评估工具风险，并非交付独立评审；它卸载时 live Auto 会迁往 Full access 的行为也不适合照搬为治理降级默认。[S10] 可以借鉴插件组合方式，不能直接作为 review gate。

## 9. workflow 能加速执行，但不应该拥有长生命周期

官方 workflow 适合固定、受审脚本发起有界 fan-out；caller 持有 start handle、signal 和 dispose 职责。result 不拒绝 Promise，而以 stopReason=error/cancelled 编码；调用者必须检查并最终 await dispose。observer events 不拥有取消权。[S7]

workflow-ptc 没有持久恢复、总时长计时器或网络策略；helper 的并发/总 agent 数限制是合作式边界，不是跨全部执行路径的安全 quota。脚本的子 agent 在内部收集，不必发普通 subagent 相同的父会话完成通知。cwd 在启动时捕获，后续父目录切换不自动改变子执行位置。

因此它可以作为某个 admitted task 下的“执行批次”，但不能直接当作整个 run 的 durable engine。为避免两套 admission，初版优先普通 subagent；若引入 workflow，领域服务必须看见其预算、child 身份和失败，不能让脚本的 maxConcurrentAgents 与 run.max_workers 独立放大。

官方 tool-ralph 是不改 core、组合 workflow 与作者控制脚本的例子；本轮只研究，不触发其循环或把其自述完成作为验证证据。[S11]

## 10. 插件启停、失败与信任边界

profile plugin scope 为会话共享，设置可能 HMR，也可能要求重启；“安装记录存在”“插件已启用”“依赖满足并真正 active”是三件事。[S9] 在可逆 effect 中关闭 owned resources，不能把一个后台任务塞进 apply 后不管理取消。

卸载流程建议：停止新 admission → 标记并处理本插件拥有的执行 → 持久确认状态 → 释放订阅/句柄。不能取消无归属的会话。崩溃后恢复为 unknown，重新检查；不要默认自动再跑。

对绑定治理的 session，若服务缺失/版本不兼容，受管入口应 fail closed，明确“当前无法受管执行”。但用户有权从配置移除插件，或者使用其他 shell；插件不能承诺阻止卸载后的一切操作。若需要绝对强制，是宿主部署与 sandbox 策略问题，超出普通插件权限。

checkpoint stateVersion 不兼容可触发重建，不代表事件 schema 自动迁移。应分别设计事件 version、可重放兼容和配置升级；不支持的旧事件/未知 schema 先阻止继续，不悄悄丢弃。模型可见摘要和 UI snapshot 还要显示 asOfSeq，避免把过期投影当最新状态。

## 11. 最小原型与继续研究条件

这是一条未来备选路线，不需要现在启动实现。若以后选择验证，应先证明最难的领域契约，而不是先做完整 UI。

1. **单 owner 的最小闭环。** 一个 service、一个投影、少量工具，完成 run → plan → 一名只读 child → 真实检查 → review → complete；无 UI、无多进程、无多 provider、无自动 merge。
2. **确定性拒绝。** 直接 service、工具和可选 RPC 的越权转换均拒绝；同 revision 并发只有合法一次成功；worker 自报不能满足检查/评审门禁。
3. **故障恢复。** 在 intent、spawn、activation-bound、结果记录与 flush 各处杀进程；重复通知、fork/reload、owner 缺失、配置漂移不会重复副作用或静默放行。
4. **受管执行边界。** 明确哪些写工具/路径被阻止，直接服务与自定义 executor 是否一致；不把 sandbox 外的操作写成已保护。
5. **隔离和 UI。** 最后加入工作树、多个 writer、TUI 视图；脏文件/未合并提交保留，UI 无效不破坏运行。

继续投入的条件是：上述垂直切片证明状态权威、门禁与恢复可行，且相对“官方 Team + 几个技能”有明确价值。若实现只剩 task CRUD 和提示词，应该优先贡献上游或使用现有组合；若要做完整可靠调度系统，也应承认其规模已超过一个薄适配插件。

## 12. 与前一研究的关系

| 问题 | 前一研究 | 本分支 |
| --- | --- | --- |
| 目标 | 多客户端体系新增 DSH/TUI 支持 | 纯 DSH 原生交付治理 |
| 权威 | 现有 run 文件与 CLI | 建议 owner Session 领域服务与投影 |
| 主要工程 | target/preset/能力适配、验证与桥接 | 领域状态机、事件/一致性、执行与恢复 |
| 官方 Team | 默认不叠加可写状态 | 可选任务权威但受 seam 限制；推荐原型自有领域状态 |
| 价值 | 可迁移的统一工作流 | 更紧密的宿主集成和服务层政策 |
| 代价 | 多 target 能力差异 | DSH 专用、版本耦合、更多领域实现 |

两条路线解决不同问题。本报告认为原生路线在架构上更贴合 DSH，但不是前一路线的替代结论，也不能据此修改前一份支持建议。

## 13. 固定来源

以下均为官方仓库固定 revision，可在本轮只读 checkout 中复核。源码/documentation 描述的是能力边界，建议架构与验收仍未实现。

- [S1 architecture](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/architecture.md)
- [S2 Cordis primer](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/cordis-primer.md)
- [S3 Team subsystem](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/subsystems/agent-team.md)，[service implementation](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/team/agent-team/src/index.ts)
- [S4 Session projection](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/session/session-projection/README.md)
- [S5 tool execution pipeline](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/docs/tool-execution-pipeline.md)
- [S6 tools service](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/core/tools/README.md)
- [S7 workflow](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/workflow/workflow/README.md)，[workflow-ptc](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/workflow/workflow-ptc/README.md)
- [S8 storageDomain](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/storage/storage-domain/README.md)
- [S9 plugin-manager](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/boot/plugin-manager/README.md)
- [S10 auto-review](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/experimental/auto-review/README.md)
- [S11 Ralph](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/experimental/tool-ralph/README.md)
- [S12 subagent](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/subagent/subagent/README.md)，[spawn provider](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/subagent/subagent-spawn-in-process/README.md)
