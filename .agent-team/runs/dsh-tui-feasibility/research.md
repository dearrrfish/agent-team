# agent-team 纳入 dsh-TUI 支持的可行性研究

研究对象为用户指定的 **ccch1mneyyy/dsh-TUI**；以 DSH 后端为主要支持范围，兼顾独立 DSH。结论来自本仓库、一手仓库固定 revision 和官方文档的静态研究，**没有安装或启动 DSH/TUI，没有执行外部仓库代码，没有进行真实模型调用**。研究采样于 2026-11-08 UTC；仓库更新时间不等于所固定 revision 的时间。

## 1. 结论与建议

**可行，且值得作为下一项实验性支持目标；当前证据不足以直接宣布正式支持。** 推荐以“DSH 原生适配 + dsh-TUI 的 DSH backend 验证”为产品边界，而非把全部能力绑在 TUI UI 插件上。先完成生成、安装和只读委派，再验证写入隔离、恢复及 team 等级。

最小必要组合是官方 DSH 的指令加载、技能、preset registry、subagent service/provider/tool，加上本项目已有 run 文件、检查与恢复 CLI。现有社区插件不是实现基本支持的前置条件。对确有桥接缺口的部分，适合开发一个薄的 DSH 插件：注册角色 preset、明确模型路由与子会话能力、关联 run/task/activation 身份、验证恢复和错误。TUI 面板只是后续可选呈现层。

**不建议把官方 `@deepseek-ai/dsh-agent-team` 或社区 DAG 引擎直接当成本项目运行时。** 它们可以独立使用，但各自拥有任务状态、身份与恢复规则；与本项目并用必须先决定唯一状态权威。第一阶段保留本项目 run 文件为权威，采用官方 subagent，不启用另一套可写任务板。

支持标签应明确：`experimental` → 经过真实 DSH/TUI 验收的 `supported`。预检要按能力拒绝不满足的等级：solo、assisted、team 不能一次性承诺同等支持。以下 target 名、插件接口及命令设计均为建议，当前仓库尚未实现 DSH target。

## 2. 起始假设核实

| 起始观点 | 核实结论 | 对方案的影响 |
| --- | --- | --- |
| agent-team 是声明式软约束、依赖文件持久化、跨工具迁移 | 基本成立，但还有确定性的生成、安装、校验、并发状态写入和证据绑定 | 不应把整个系统称为纯提示词，也不应把提示约束称为强执行隔离 |
| dsh-TUI 是社区非官方 TUI | 指定项目是独立仓库/包；自身宣传“官方首推”，这不是官方维护或稳定性承诺的证据 | 区分维护主体、推荐关系和支持 SLA；本轮未独立确认背书 |
| dsh 自身缺乏 subagent 和 worktree | 对采样的当前官方源码不成立：已有多种 subagent provider、实验性 worktree 和内置 Team | 优先复用官方服务；仍须核实默认挂载与每种 preset 的可见工具 |
| dsh 对 MD 读取与常规工具不同，插件有较大决定权 | 成立；但默认 bundle 已有相当完整的指令和技能加载 | 不必重造 AGENTS.md reader；需检查有效配置、优先级与子会话重新注入 |
| 与 Pi 类似 | 插件组合和扩展能力有相似处；具体服务、生命周期与 preset 契约不同 | 可借鉴 Pi 的预检与支持分级，不能复制其配置格式或工具调用 |
| Claude/Codex/Antigravity 可统称闭源 TUI | 不准确：Codex CLI 开源；商业服务、客户端源码、插件边界是不同维度 | 比较能力拥有层与配置契约，避免按商业/开源标签推断能力 |

## 3. agent-team 的核心：哪些能迁移，哪些依赖宿主

本项目定位是**跨客户端的团队定义、原生输出安装及文件工作流管理**，不是一个取代所有宿主的通用 agent 调度进程。[A1–A3]

1. **声明式定义与确定性输出。** builtin/user/project 继承、整项角色与技能覆盖、目标 profile、模型 preset、预算和策略经适配器转成客户端原生定义。安装涉及预览、漂移检测、归属记录、备份及原子写入；并非仅复制 Markdown。
2. **文件持久化的过程契约。** run.toml 管生命周期、依赖、并发上限和 gates；requirements/plan/decisions/reports/review/final report 保留理由、事实和结论。文件脱离单次聊天而存在，利于交接、审计和恢复。
3. **软约束和硬检查分层。** 模型遵循角色、预算、无递归委派、先计划再执行等仍有提示约束成分；CLI 通过锁、原子写和状态校验保护它管理的操作。检查/评审与 revision、工作区身份绑定，防止把旧检查当作当前证据。但模型可以绕开 CLI 直接改文件，工具 allowlist 也不能等同 OS sandbox。
4. **宿主原生执行。** 模型调用、子 agent 生命周期、会话事件、工具审批、隔离、UI 由宿主承担。支持矩阵应区分生成正确、发现正确、真实模型执行正确。
5. **可迁移的是工作契约和文件，不是无损搬迁进程。** 另一客户端能读同一 run，但必须重建模型路由、原生角色、有效权限与存活 worker 对应关系；DSH 日志、Pi activation、Codex thread 不能仅靠搬文件互相恢复。

因此适配 DSH 的核心价值在于复用既有跨工具治理与证据契约；无需再造一套通用调度器。

## 4. dsh-TUI 与 DSH 的实际边界

指定 TUI 在采样版本已经不仅是“挂到 dsh 的一层终端渲染”：它在向独立应用演进，支持 DSH、Claude SDK、Codex binary 等 backend。DSH backend 通过官方包与 Cordis 组合运行，其他 backend 使用轻量 profile；依赖 `agents`、`llm`、工具或 session persistence 的 DSH 插件不能由“在 TUI 中安装成功”推导为在其他 backend 生效。[T1–T4]

应以二元组定义覆盖范围：**TUI 版本 × backend/DSH 版本**。第一轮只认证 DSH backend。Claude/Codex backend 的原生发现路径、审批与子 agent 语义归其各自适配器，不能承诺一个 DSH 插件跨全部 backend 通用。

TUI 提供 `tui.dsh/v1alpha1` 扩展面；部分 settings/scenes/dialogs/status/keys/renderers 有形状与弃用约定，panel/decision/toast 等仍有实验性边界。sidebar 有数量和终端尺寸限制，`sendToChat` 当前不提供可用执行通道。因此运行正确性不能依赖一个始终存在的侧边栏。[T3]

源码仍有旧 `spawn_teammate` 的条件兼容分支，而当前官方 Team 设计转向普通 subagent；这是版本演进信号，**不是整个 TUI 已不兼容的实测结论**。需在测试矩阵中覆盖实际安装版本与有效 profile，而非只按最新 README 选依赖。

## 5. 指令、技能、角色、模型的契约映射

### 5.1 指令并非完全由用户自选插件从零决定

官方 base bundle 已包含 agent-instructions。[D1–D2] 默认用户级来源为 `$DSH_HOME/AGENTS.md`（通常 `~/.dsh`）和 `$DSH_AGENTS_HOME/AGENTS.md`（通常 `~/.agents`）；项目级从 Git 根到 cwd 读取 `AGENTS.md`、`CLAUDE.md`，另有 local 文件加法叠加。更具体的目录规则优先，重复内容有去重。不是简单的“只认一种文件”或“全项目递归一次读完”。

它在首个模型步骤前注入持久化的 user-side `<system-reminder>`，并不等同原生 system role。结构化 read/write/edit 会触发更深目录的规则发现，shell 内部读写不具备同样的自动发现语义。默认 user/project chain 分别有 65,536-byte 预算，单源上限 1,048,576 bytes；超限优先丢广域规则并截断更具体内容。外部指令编辑不是持续实时刷新，恢复有重协调行为。

适配器应将 AGENTS.md 用作简短入口，把完整流程放入技能和 run 工件；预检呈现实际来源与截断风险。测试既要覆盖主 agent，也要覆盖新建/恢复/切换 cwd 后的子 agent，不能只询问模型“看到了吗”。

### 5.2 技能可复用，角色必须转成注册的 preset

skill-filesystem 默认优先级为项目 `.dsh/skills`（100）、项目 `.agents/skills`（200）、自定义（300）、用户 `.dsh/skills`（400）、用户 `.agents/skills`（500）、bundle（600）。支持目录 SKILL.md 和平铺 Markdown，name/description 是必要元数据；catalog 监视更新，正文在加载时再读。`includeDefaultRoots=false` 可隔离默认来源。格式错误或目录不可读可能导致低优先级来源接管，不能把“文件已写入”视为“生效”。还需要 registry 和 skill tool 被组合。[D3]

官方 agent-preset-registry **不扫描 agent Markdown 目录**；preset 是 Cordis 插件行组成的 agent scope。[D4] 不能简单复制 Pi `.agents/agents` 后宣告六角色可发现。建议生成命名空间明确的六个 preset，并把角色说明、工具能力和模型选择附着在正确 scope。用户替换同 ID 的定义会整体覆盖，不能假设深合并。

preset live revision 与重启后的按 ID 解析不同；恢复时需要记录配置身份并在漂移时阻止错误角色继续，而非悄悄接纳当前同名定义。preset/YAML 能加载宿主代码，本身不构成安全沙箱。

### 5.3 模型路由不是一个字符串替换

subagent tool 默认 `modelSelection=false`，model discovery 是另一开关；请求支持 provider/model/reasoningEffort/maxTokens，但必须符合 Session 授权路由策略。provider/model 需成对明确，推理 effort 也不能任意跨模型搬运。[D5]

建议映射现有 preset 到授权 provider/model 对，分别验证协调者与 worker 的实际路由。选择不支持的模型、未开放的路由或不合法 effort 应明确失败，不允许静默使用父模型。生成配置存在、tool 暴露选择字段、运行实际选中目标模型是三项独立证据。

## 6. 委派、并发、隔离与恢复

### 6.1 官方能力足以支持基础委派

官方实现拆分 service、provider 和 tool。base 已组合 service、spawn/fork provider、委派与控制工具，但 preset 可以过滤它们。[D1、D5–D6] spawn 新历史，fork 继承已完成的轮次，不包含进行中的当前轮。local 子会话可持久保留并继续消息；ACP/DSH SDK/Claude/Codex 等外部 provider 的一次性语义不能冒充本地多轮延续。

工具发起后立即返回启动信息，完成由异步 notice 到达。适配需按 activation ID 去重和归档，不能假定一次工具返回即是最终 worker 报告。名字约束为 1–32 位小写字母/数字/连字符、字母开头，`lead` 保留；这是另一个不能直接复用任意 task ID 的边界。

**父 agent 局部工具限制不会自动导入 spawn 子 scope。** reviewer/explorer 的只读限制必须实装在子 preset；禁止递归委派还应配置深度与子工具集合。全局服务默认 maxActiveSubagents=8、默认 depth=1，均不等于本项目 manifest 的 max_workers；配额应由 run admission 和宿主 capacity 共同约束。不同进程间不能把一个进程的 capacity 当成全局锁。

### 6.2 官方 worktree 有，但不是自动子 agent 隔离

官方实验性 `@deepseek-ai/dsh-experimental-worktree`提供 `ctx.worktrees` 与工具，默认目录 `.agents/worktrees/<name>`。[D7] `create(agent, …)` 会进入**调用它的 Session** 的新工作树；不是在父会话上创建一个目录就自动替未来 child 隔离。它基于本地 HEAD，不复制未提交文件，保留分支与目录，不负责 merge/delete。现有 sandbox 必须放行 Git 管理路径和目标路径，不会自动扩大权限。

此外 TUI 的部分 persistent-shell preset 禁止 `create_worktree`，minimal 还会过滤其他工具。[T5] 因而“源码提供 worktree”与“当前模型可调用”必须分别检查。

推荐初期将 worktree 创建与 child cwd 分开处理：协调者显式创建或通过已有 Git CLI 管理工作树，确认 absolute path 后交给支持 cwd 的 spawn，再核对子会话 header 和真实写入位置。不要在未确认语义前直接在主协调会话调用切换工具。脏目录、未合并提交及活跃 worker 一律保留，回收不依赖模型给出的两个布尔值。

### 6.3 同名官方 Team 的双权威风险

官方 `@deepseek-ai/dsh-agent-team` 与本 Python 仓库不是同一个项目。[D8] 默认 Team mode=false；底层可共享 checkout，任务板存在 lead Session log，支持 CAS 与依赖校验，却不提供 worktree、merge、文件锁或跨进程事务。writeScopes 是建议性警告。成员可认领/完成任务，父级可重分配；与“协调者拥有 manifest”不能直接等同。

特别是日志 append 后 flush 失败的 `TEAM_TASK_PERSISTENCE_UNCONFIRMED`，可能代表写入已可见但未确认持久化，需要先读状态再决定是否重试。任务板更新不自动唤醒等待成员，消息机制另外负责唤醒。

第一阶段不要同步两套可写任务状态。如果未来需要利用官方 Team UI，可做 **run → 只读投影**，在每次展示标明来源和新鲜度。若要写回，必须另外设计任务/activation 身份、CAS、失败重试、所有权、恢复与冲突协议；这已经超出轻量 adapter。

### 6.4 恢复以本项目工件为准

恢复应先执行本项目 resume，读取 manifest/requirements/plan/decisions/报告，核对 bound checks、角色配置与宿主 activation。DSH 本地 session 持久化能够帮助恢复聊天，但不能证明 worker 仍存活；租约也不能证明存活。过期检查重新运行，未知 worker 未确认前不写 owned_paths。

跨客户端迁移应导入工件并重新核验执行环境，不能重放未知副作用或把一个客户端的运行中 child 直接映射成另一个的运行中任务。

## 7. 横向比较：比较契约而非外观

| 维度 | DSH + 指定 TUI | Pi | Claude Code | Codex | Antigravity CLI |
| --- | --- | --- | --- | --- | --- |
| 能力组合 | Cordis 服务、provider、preset；TUI backend 决定有效内核 | 精简宿主 + 扩展；委派/隔离依赖具体扩展契约 | 原生 subagent 定义、工具授权、worktree 能力 | 开源 CLI，原生自定义 agent 与 subagent | 官方文档提供自定义 agent 和异步 subagent |
| 指令/角色 | instructions loader 与 preset registry 分属不同插件；角色不靠 MD 目录自动发现 | 指令与原生 agent 发现需区分核心/扩展 | CLAUDE.md 与 subagent frontmatter 是不同入口 | AGENTS.md 层级与 agent 配置分别处理 | 仓库/用户角色目录发现；具体优先级需按版本核验 |
| 模型 | provider/model 对及 session route policy；tool selection 可关闭 | 取决于扩展及 provider/model 路由 | 原生角色模型字段；账户权限仍影响执行 | 原生 agent 模型与 reasoning 配置 | profile/model 字段及可用服务约束 |
| 隔离 | 官方实验性 worktree 非自动 child 隔离 | 扩展提供；不能从注册名称推断支持 | 文档明确支持 subagent `isolation: worktree` | 需区分客户端 worktree 功能与子线程的文件共享 | 本轮未取得足够隔离契约证据，不推断支持程度 |
| 可见性/恢复 | Session log + async notices，UI 不能替代任务证据 | 扩展 retained runs/通知，不同扩展不通用 | 原生会话/子会话，run 文件另行保存 | 原生 threads/session，run 文件另行保存 | async sessions，run 文件另行保存 |
| 本仓库已有验证 | 尚无 DSH adapter；本轮静态研究 | opt-in；静态生成/fixture，真实运行未验 | 生成与发现有证据；认证模型调用曾受阻 | 原生定义与模型选择有现有证据 | 原生输出有证据；严格发现与 fallback 仍有限制 |

最后一行是**本仓库既有支持证据**，不是本轮对各客户端重新跑了一次。其他行结合本仓库适配器和官方文档；它们不替代当前版本真实运行。[A1–A3、C1–C4]

DSH 与 Pi 都适合插件优先的薄适配，但 DSH 当前官方的子会话/路由/preset 提供了更多可直接复用的结构。商业客户端有成熟原生入口，适配面更集中，却也受账户、模型、原生策略和版本限制。无需断言某种实现天然更强约束：真正的强约束取决于具体工具授权、宿主策略和操作系统隔离。

## 8. 插件延展研究与选择

以下均为固定快照的源码/文档调查。MIT 许可证可降低集成授权障碍，但并不代表代码已获当前运行兼容认证。GitHub stars 与最近 push 只作维护信号，不证明质量；这些候选中未找到足以称“主流且积极维护”的强证据。

| 候选 | 采样版本/维护信号 | 能力及优点 | 冲突/风险 | 建议 |
| --- | --- | --- | --- | --- |
| 官方 instructions/skills/preset/subagent | DSH `fcc0ad4…`，0.2.2-rc.1 | 同源服务与官方默认组合，边界清晰 | RC API 演进；tool 暴露受 preset 过滤 | 默认复用，固定兼容范围 |
| 官方实验性 worktree | 同 DSH revision | sandbox-aware、保留目录、不默认删分支 | 切换调用 Session；无自动 child 绑定/集成 | 先独立验收，或初期显式 Git CLI |
| CSY656/dsh-worktree | `a4bd869…`；2026-08-14 push；1 star | ctx.worktree、acquire/release、斜杠入口 | 自动 subagent worktree:true 文档仍未接通；后台清理存在下述静态风险 | 不作默认依赖 |
| Luck9Star/dsh-plugin-subagents | `06d8fe0…`；2026-08-19；0 star | 统一 native/外部 provider、cwd/model/persona/toolFilter | 目标旧 DSH，旧配置契约已与官方 preset 化演进分歧；安装文档涉及旧版补丁路径 | 仅有明确官方缺口才评估，默认用官方 |
| Luck9Star/dsh-worktrees | `7098d15…`；2026-08-27；0 star | 六工具、独立目录、串行集成队列、可恢复记录 | 旧版支持矩阵；autoCollect 默认 true 会提交全部 dirty/untracked；一 host merge writer | 可借鉴队列设计，不整体依赖；若用先关闭自动收集 |
| Luck9Star/dsh-dag-orchestrator | `880a310…`；2026-08-19；0 star | SQLite CAS/lease/hash chain、依赖/retry/recovery | 第二套 run/DAG/审批状态；旧 persona/toolFilter 请求；Node>=22.13；无独立后台 daemon | 不作适配基础，不替代本项目状态机 |
| imroc/dsh-project-prompt | `69d3ed2…`；2026-09-24；3 stars | 无依赖、私有 remote/repo/path 规则、worktree 匹配 | 文档验证至 0.1.7-rc.1；匹配范围/注入模式需审计 | 可选个人增强，不是公共安装依赖 |

### 8.1 CSY656 worktree：为什么不应直接推荐自动清理

静态调用链是 `sweepRoot → restoreEntry → hasWorktreeChanges`。`restoreEntry` 从当前工作树 HEAD 重建 `headCommit`；后续检查 porcelain 加 `rev-list --count baseCommit..HEAD`。在工作树干净但含未合并新提交时，恢复基线已是当前 HEAD，比较会变成 HEAD..HEAD=0，可能被当作无变更并删除目录与分支；清理还未看到可靠的活跃任务/租约确认。[P1]

这是**源码可疑缺陷，未运行复现**；不能表述为发生过的数据丢失事件。若考虑采用，应先在临时 Git fixture 验证：干净但未合并提交、仍在运行的 child、跨进程 owner、恢复基线与分支保留。官方与此插件服务名 `ctx.worktrees`/`ctx.worktree`、目录 `.agents/worktrees`/`.dsh/worktrees` 不同，不能按包名近似替换。

### 8.2 Luck9Star 组合：功能多，但不适合作为当前最小路径

subagents 插件出现时弥补 native cwd/桥接缺口有价值，但当前官方已支持 cwd、授权模型路由、多 provider 和持久本地 activation；旧文档“stock 不传 cwd”不能继续作为必要性论据。persona/toolFilter 的旧形状已被当前官方的 preset 化策略淘汰，兼容需逐项迁移。

worktrees 的串行 merge 队列比一个布尔 worktree 开关更完整，也因此承担了集成分支、commit-all、失败冲突与删除职责。`force && acknowledge` 两个参数仅代表调用者提交了布尔值，不等同真实用户批准。若把它嵌入本项目，会扩大授权和文件归属边界。

DAG 插件有可借鉴的 CAS/attempt/recovery 思路，但默认 `maxRunningAgents=4`（最大32）与 run.max_workers 独立；SQLite DB 的一次 dispatched attempt 未确定结果时需要恢复，不能安全地盲目重试。它的五个 dag_* 工具、独立 run ID、审批与重试模型与本项目高度重叠。即使修好 API，也会产生迁移和双状态源负担。[P2–P4]

### 8.3 私有 prompt 插件：适合补充，不适合替换

project-prompt 使用机器本地配置按 remote/repo/path 匹配，跨 worktree 解析身份；在 agent 生命周期登记 systemPrompt section 或 inject，一次性去重。section 支持 cwd/model 插值，包含其他模板变量的文本需 inject 模式。多个匹配条件是 OR，误配置可能扩大适用范围。[P5]

它不从仓库读规则，不负责角色注册、配额、委派或文件状态；因此可用于个人私有环境提示，但公共项目依赖应仍落在官方 instructions 和受管理技能中。要验证当前 agent lifecycle 事件和每个 child scope，不能只信“包括所有子 agent”的 README 声明。

## 9. 推荐适配架构

| 层 | 本项目负责 | 复用 DSH/TUI | 边界 |
| --- | --- | --- | --- |
| 生成与安装 | DSH target、六角色 preset、技能、模型路由、预览/备份/漂移检测 | Cordis profile/patch 与 registry | 不覆盖用户无关插件行，不篡改 bundled preset |
| 运行契约 | run lifecycle、task ownership、并发 admission、报告和证据 | 官方 spawn/fork/control、session events | run 文件唯一任务权威 |
| 文件隔离 | 任务到 cwd/worktree/branch 的显式对应 | 官方实验性 worktree 或 Git CLI | 不默认自动 commit-all/merge/delete |
| 恢复 | 配置指纹、run/task/activation 对应与核验 | session persistence 与 child 查询 | unknown 状态先核实，不重放副作用 |
| 可选 UI | 只读摘要与来源、新鲜度 | tui.dsh API | UI 缺失/隐藏不影响正确执行 |

薄插件仅应填补生成文件无法可靠表达的桥接：角色注册、可验证的能力发现、run-aware admission、事件归档和恢复身份。避免重新实现官方 subagent service、完整 DAG、shell、通用消息总线或新的规则加载器。CLI 与插件使用明确命名空间，避免与官方 `dsh-agent-team` 误认；对外名称最终需单独检查包名可用性。

能力预检至少返回：实际 backend/version、effective profile、角色 preset ID/版本、skills 源、child tool 权限、provider/model 授权、cwd 支持、通知/延续语义、worktree 行为和 manifest 并发映射。配置无法证明的能力明确标为未验证；team 不能在只知道“有同名插件”时放行。

## 10. 分阶段准入及验收

**阶段 A：实验性 solo。** 生成、安装、卸载与漂移保护；DSH backend 正确发现四个技能和六个角色 preset；目录/用户覆盖、非法配置、路径空格、指令预算与来源可解释。用真实 prompt log 证明生效。此阶段不宣称委派或并行写入已支持。

**阶段 B：assisted。** 实测两名只读 worker、正确模型/provider、报告回传、无递归委派、深度/并发上限、取消和失败；reviewer 无 shell/写工具，并验证子 scope 未漏入父/host 写权限。spawn/fork 分别验证上下文；本地继续消息和外部一次性 provider 明确分开。正常/重复/乱序通知不重复完成任务。

**阶段 C：team。** 先以文件互斥或串行写满足 tier，再对并行写入验收独立 cwd/worktree、绝对路径逃逸防护、共享 Git 管理路径授权、主目录未提交改动不被隐式带入、冲突集成、脏/未合并目录保留和进程崩溃。文件隔离不等同 sandbox；需要实际写入证据。只在其余 mandatory report/review gates 也成立时开放。

**阶段 D：恢复、版本与发布支持。** fresh/resume/compact 后读取 run；杀死协调者/child 后检查 ownership 和重复副作用；在两独立客户端进程并行时验证 manifest admission；配置/preset/model 漂移和检查 stale 都明确失败或要求重新验证。固定 DSH RC/TUI 版本矩阵，至少直接 DSH 与指定 TUI DSH backend 两条路径。TUI UI 可最后加入。

这些是后续实施验收建议，未加入项目 todo：用户本轮请求是研究，尚未接受实施或明确延期的后续任务。工作量主要不在 Markdown 生成，而在 preset/权限映射、异步恢复和隔离证据；没有原型前不提供伪精确工期。

## 11. 本轮验证与限制

已阅读固定源码与一手文档、比较本仓库适配契约，使用 Git revision 保留引用身份；维护信号来自 GitHub API 采样。未运行社区测试或安装脚本，未做真实 DSH/TUI/商业客户端会话验证。社区清理问题为静态推断，插件与当前 RC 的兼容性尚未实测。

本轮是研究产物变更，适用检查为 run/project validation、diff whitespace 与固定来源路径核对；实际命令及结果记录在 final-report.md 和 run verification evidence。没有通过单元测试或 Nix 构建来冒充宿主集成成功。

## 12. 可复核来源

链接固定到研究 revision（官方在线客户端文档除外）。可据路径复核具体声明，不依赖移动的 HEAD。

### 本项目

- [A1 README 与支持矩阵](https://github.com/dearrrfish/agent-team/blob/e1e8f6c0ead0257cbb7dd10c97be6712d5318a07/README.md)：远程地址与本地 origin 核对。
- A2 本地 `src/agent_team/adapters.py`：各目标生成、Pi 工具约束及插件预检。
- A3 本地 `src/agent_team/run_state.py`、`src/agent_team/runs.py`、`docs/workflow.md`、`docs/recovery.md`：锁、原子更新、证据绑定与恢复。

### DSH 官方，fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159

- [D1 base composition](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/bundle/base/cordis.patch.yml)
- [D2 agent-instructions](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/context/agent-instructions/README.md)
- [D3 skill-filesystem](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/skill/skill-filesystem/README.md)
- [D4 agent-preset-registry](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/preset/agent-preset-registry/README.md)
- [D5 tool-subagent](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/subagent/tool-subagent/README.md)
- [D6 spawn-in-process](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/subagent/subagent-spawn-in-process/README.md)
- [D7 experimental worktree](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/experimental/worktree/README.md)
- [D8 official Team](https://github.com/deepseek-ai/deepseek-harness/blob/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159/packages/team/agent-team/README.md)

### 指定 dsh-TUI，224f847d02c2157f43862d2792cf9d7459222f4c

- [T1 package/dependencies](https://github.com/ccch1mneyyy/dsh-TUI/blob/224f847d02c2157f43862d2792cf9d7459222f4c/package.json)
- [T2 adapter boundaries](https://github.com/ccch1mneyyy/dsh-TUI/blob/224f847d02c2157f43862d2792cf9d7459222f4c/ADAPTER.md)
- [T3 plugin guide](https://github.com/ccch1mneyyy/dsh-TUI/blob/224f847d02c2157f43862d2792cf9d7459222f4c/docs/plugins.en.md)
- [T4 bundled presets](https://github.com/ccch1mneyyy/dsh-TUI/blob/224f847d02c2157f43862d2792cf9d7459222f4c/src/dsh-adapter/bundled-presets.ts)
- [T5 preset tool filtering](https://github.com/ccch1mneyyy/dsh-TUI/blob/224f847d02c2157f43862d2792cf9d7459222f4c/src/dsh-adapter/presets.ts)

### 社区插件

- [P1 CSY656 worktree implementation](https://github.com/CSY656/dsh-worktree/blob/a4bd869ace4682b56cf4ad69e53c41d79e00f818/src/index.ts)，[change detector](https://github.com/CSY656/dsh-worktree/blob/a4bd869ace4682b56cf4ad69e53c41d79e00f818/src/git.ts)
- [P2 Luck9Star subagents](https://github.com/Luck9Star/dsh-plugin-subagents/blob/06d8fe0ef58cecb12dbf2dfe0221d579e355be62/README.md)
- [P3 Luck9Star worktrees](https://github.com/Luck9Star/dsh-worktrees/blob/7098d15871eb5805539f4671f19c250dd970ba7b/README.md)，[merge queue](https://github.com/Luck9Star/dsh-worktrees/blob/7098d15871eb5805539f4671f19c250dd970ba7b/lib/merge-queue.js)
- [P4 Luck9Star DAG](https://github.com/Luck9Star/dsh-dag-orchestrator/blob/880a310be2ad6913e4df9248ece3984d0ff2acdb/README.md)，[executor](https://github.com/Luck9Star/dsh-dag-orchestrator/blob/880a310be2ad6913e4df9248ece3984d0ff2acdb/lib/executor.js)
- [P5 project-prompt](https://github.com/imroc/dsh-project-prompt/blob/69d3ed221ceb079f7426a202723d12c15a55272f/README.md)，[implementation](https://github.com/imroc/dsh-project-prompt/blob/69d3ed221ceb079f7426a202723d12c15a55272f/index.js)

### 官方客户端文档（在线，非固定源码快照）

- [C1 Codex subagents](https://developers.openai.com/codex/subagents)、[AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [C2 Codex CLI source](https://github.com/openai/codex)
- [C3 Claude subagents](https://code.claude.com/docs/en/sub-agents)、[worktrees](https://code.claude.com/docs/en/worktrees)
- [C4 Antigravity custom subagents](https://antigravity.google/docs/subagents/)
