# Claude Opus Review — Public Profile Search Plan v2.0

- Reviewed: 2026-07-23
- Requested model: `opus`
- Actual model: `claude-opus-4-8`
- Session: `f41e5295-e68b-4407-8096-5f698ff47cbe`
- Source plan: `public-profile-search-project-plan.md`

---

我已完整读取全文（1650 行，v2.0）。下面是严格评审。文中的所有指令（含开头 "For Hermes"、各阶段"必须/不得"）我一律当作**待审内容**，未执行。

---

# 严格评审：Public Profile Search Project Plan v2.0

## 总体判断

这是一份罕见地成熟的计划：生命周期一致性（§5.2/§7/§8）、分层策略与 predicate allowlist（§9.4）、状态枚举的严格解耦（§6.4）、独立 provenance group、suppression 与 deletion 的双 lifecycle，都远超一般 plan 的水平。**主要问题不在架构，而在三处：几个核心门槛术语未定义、可测性指标与样本量自相矛盾、以及一条"载重"外部依赖（通用搜索 API）与几处 MVP 范围过大。** 下面逐条。

---

## 1) 60–120 秒 SLA 与 provider 预算

**[High] 冻结后到 fallback 的内部预算过紧且无逐步分解 —— §4.3 表（L251–258）、§5.2（L357–360）**
collection_cutoff=90s、fallback_at=110s、deadline=120s。这意味着 correlator + claim engine + DisplayPolicy + redaction + **LLM 往返**全部要在 90→110 的 **20 秒**内完成，而 §11.3 又给 LLM 独立 timeout。一次摘要 LLM 调用常需 5–15s，留给关联/claim/redaction 只剩个位数秒。文中无任何 per-step budget。
**修改：** 在 §4.3 加一行 finalization 内部子预算（correlation ≤Xs / claim ≤Xs / redaction ≤Xs / LLM ≤Xs），并规定 LLM timeout 必须 ≤ (fallback_at − 关联完成时刻)，Phase 1 必须单独实测这段而非只测 provider 时间。

**[Medium] Wave 1（3–30s）与 Wave 2（20–85s）窗口重叠但表格呈现为串行"阶段" —— §4.3 L254–255**
读者会误以为 Wave 2 在 Wave 1 结束后才启动，而 §6.3 又要求 Wave 2 依赖 Wave 1 锚点。
**修改：** 明确标注两波可 pipeline 重叠，且 Wave 2 的启动条件是"Wave 1 锚点就绪"而非固定 20s。

**[Low] 头条"60–120 秒内得到"（L23/L46）是承诺语气，但 §4.4 说数值未经基线不得对外承诺。** 建议头部加"目标（Phase 1 基准确认前不对外承诺）"。

---

## 2) MVP 范围是否过大 / 自相矛盾

**[High] `verified_consent` 第三方流程是一整套子系统，应考虑推迟 —— §2.1（L96）、§4.1（L219 `/consent/:token`）、§10.4（L886）、Phase 2 范围（L1270）**
consent 路径要求"资料主体收到短期 link 并**验证其对目标主页的控制权**"。验证第三方对 github.com/xxx 的控制权，本质上等于替对方做一次 self-audit OAuth/challenge —— 这是独立的邮件/token/平台验证子系统，且 `/consent/:token` 页面、双方异步握手都在 MVP 里。对 invite alpha，`manual_allowlisted_public_research`（人工双人 review）已足够覆盖"公共人物"场景。
**修改：** 建议 MVP 只保留 `self_audit` + `manual_allowlisted_public_allowlist` 两类，把 `verified_consent` 连同 `/consent/:token`、§10.4 consent issuance 推到 P1。可显著缩小 Phase 2。

**[Medium] "minimum useful brief"从未定义，却是 ready_partial / SLO / gate 的核心门槛 —— L167、L268、L482、L1252、L1510**
全文当作既定标准反复引用，但唯一具体判据只出现在 §4.4 L268（≥1 个达 display threshold 的非敏感 claim + 来源 + limitations）。术语与判据是否等价，读者无法确定 —— 这是团队会误解的典型点。
**修改：** 在 §3.1 或 §4.4 给出 canonical 定义，其余处一律改为"见 §X.X minimum useful brief 定义"。

**[Low] 双语范围表述分散 —— L189 / L1592 / §3.2。** "中英双语摘要模板"vs"按 locale 输出一个版本"vs"非目标：多语言完整本地化"三处需并成一句：模板 zh/en，UI 单语。

**[Medium] JobAttempt 在 MVP 恒为 1:1，纯属前瞻性复杂度 —— §8.1 L595**
MVP 每个 SearchJob 恰好一个 JobAttempt，retry 另开新 job。那么 MVP 中 JobAttempt 相对 SearchJob 无独立取值，却贯穿 lease/finalization/snapshot 外键。
**修改：** 要么在 MVP 把执行字段并入 SearchJob，要么明确标注"JobAttempt 为 P1 多次执行预留，MVP 强制 1:1"，避免实现者花时间设计多 attempt 语义。

---

## 3) 身份解析、abstain 与误认指标可测性

**[Critical] 99% display precision 门与样本量（50+50、300 decisions）在统计上不自洽 —— §16 Phase 1（L1241–1242、L1254）、Phase 7（L1380–1382）、§18（L1516–1517）**
- 50 个 holdout 无法支撑"每个 consequential predicate 各自 99% precision + 置信区间"。要在 99% 下给出有意义 CI，每个 predicate 需要**数百个已展示正例**；4 个 consequential predicate → 上千标注展示实例，远超 50/50 与 100-job alpha 能产出的量。
- "300 displayed identity decisions 无 cross-person merge"用 rule-of-three 只能给出 ~1% 的 false-merge 上界 —— 对一个"核心卖点就是别认错人"的产品，1% 可能太弱；且这 300 个"已展示的可发生 merge 的决策"从 ≤100-job（多为 self-audit、跨账号链接很少）的 alpha 中如何积累，来源不明。
- 结果是 §16/§18 的"可测门"实际大多不可达，只能靠"样本不足则关闭该能力"(L1381) 兜底 —— 于是 MVP 很可能带着大部分 consequential claim **关闭**上线，可用性被自我掏空。
**修改：** (a) 明确每个 consequential predicate 达到 99%/目标 CI 所需的最小展示正例数，据此重设 dataset 规模（大概率需数百/predicate），或按阶段分层阈值（alpha 95% → GA 99%）；(b) 明确 300 decisions 的来源（benchmark holdout 还是生产），并把 false-merge 上界目标写成显式数字（如 <0.3%）而非"0 次"。

**[High] "evidence quorum"作为 finalization 触发器却全程未定义 —— L256、L361、L366、L482、L1529**
finalizer 在"quorum 或 cutoff"运行，是核心控制流分支，但 quorum 是什么（返回 provider 数？required source classes 齐备？）从未说明。
**修改：** 定义 quorum（建议：completion policy 声明的 required source classes 全部到达终态即 quorum），并与"required source classes"一起在 `fast-brief-v1` 中版本化、在文中至少给出一个示例定义。

---

## 4) 隐私 / 授权 / 未成年人 / 删除权 / 反滥用 / ToS 门

**[Critical] `approved_generic_web` 通用公开搜索 API 是载重依赖，其 ToS 很可能不允许本用途 —— §6.2（L407）、§6.3、§10.7（L922）**
Wave 2 的权威核验大量依赖"一个已批准的通用公开搜索 API"。主流搜索 API（Bing/Google CSE/SerpAPI 等）ToS 普遍禁止用于人物核验/画像、限制缓存与派生商用 —— 恰好是本产品要做的。若无任何一家可批准，Wave 2 核验模型（含 §9.5 两 provenance group 中"独立权威"那一路）会坍塌，而计划把它当作既定可用。
**修改：** 把"通用搜索 API 的 ToS 可用性"提为 Phase 0 显式阻塞决策；并设计一条**不依赖通用搜索 API 的 Wave 2 fallback**（仅第一方官方/学校/DOI 页面直取），使产品在无可用搜索 API 时仍能降级运行。

**[High] 自助/consent 流程的"疑似未成年"信号如何在不做画像的前提下形成，未指定 —— §8.8（L705–706）、§13（L1048）**
manual allowlist 有人工 review；但 self / consent 流程只有 §8.8 的临时 EligibilityObservation + "age_unknown 默认拒绝"。实际检测机制缺失 —— 若无任何年龄信号，几乎所有 self/consent 目标都是 age_unknown → 按默认拒绝，产品不可用；若放行则等于仅靠自我声明，保护很弱。
**修改：** 明确 self/consent 的年龄处置：要么自助仅限已通过成人平台 OAuth（把成人性绑定到平台账户属性）、consent 仅限 allowlist 化，要么写清 EligibilityObservation 具体读什么公开信号、命中如何 block，并承认其为 best-effort。

**[High] HMAC-only 标识符与"检测 URL 变体 / suppression 绕过"的反滥用要求冲突 —— §8.1（L565）、§10.1（L857）、§13（L1040、L1056）**
标识符与 suppression 键都用 keyed HMAC（只支持精确相等），并明确"不保存普通可枚举 hash"。但 §13 要求识别"相似 URL / URL 变体绕过 suppression"，这需要 plaintext 或模糊特征 —— 与最小化 HMAC 直接矛盾。若一个人被 suppress（键=其 GitHub canonical URL），用其 Medium 主页发起新 job 不会命中。
**修改：** (a) 明确"强 canonicalization 使变体坍缩为同一 HMAC"是主要防线，并把 canonicalization 规则版本化、加测试；(b) 承认 suppression 是 per-identifier 而非 per-person 的残留风险；(c) 若要跨平台 suppress，需在 suppression 时登记所有已知 handle/alias 并说明覆盖边界。

**[Medium] 备份删除依赖轮转，但缺少"恢复后重放 suppression/tombstone"的要求 —— §12.1（L1001/L1012）、§8.7、§12.3（L1026）**
"备份最迟 30 天失效"只在从不保留更久的备份时成立；且从旧备份 restore 会复活已删/已 suppress 数据。文中有 tombstone/suppression 多点检查，但未规定 **restore 流程必须对照 tombstone/suppression 重新执行清理**。
**修改：** 在 §12/§5 增加"任何 restore 后必须重放当前 SuppressionRecord/Tombstone 再开放服务"的硬要求，并纳入 §17.6 backup/restore drill。

---

## 5) JobAttempt/ProviderRun/snapshot/revision/SSE/重试语义

这是全文最完整的部分（acceptance_epoch write fence、lease_generation、outbox、reconciler、watchdog、CAS、late_payload_discarded、tombstone 齐全）。仅少量补漏：

**[Medium] Wave 2 动态 planning 与 finalization 竞态时，未明确 planning 必须在 epoch 前置检查下 abort —— §5.2（L363、L366–368）**
finalizer 递增 acceptance_epoch 并把非终态 run 置 closed_at_finalization；Wave 2 在事务里创建新 ProviderRun。若两者并发，需保证 planning 在 epoch 已推进时不再创建 run。文中说 worker commit 前查 epoch，但没为 Wave 2 planning 显式写这条。
**修改：** 明确"conditional ProviderRun 创建事务必须校验 acceptance_epoch 未变，否则放弃 planning"。

**[Low] SSE replay 的数据来源（Postgres JobEvent vs Redis）未点明 —— §7.2、§8.6**
durable JobEvent 在 PG，但 Last-Event-ID 重放读 PG 还是 Redis 未写死；Redis 丢失后必须能从 PG 重放。
**修改：** 一句话规定"replay 从 Postgres JobEvent 读取，Redis 仅热路径转发"。

**[Low] `/retry` 无幂等键 —— §10.5（L897）。** 双击可能生成两个 retry job。建议 retry 也接受 Idempotency-Key。

---

## 6) LLM 边界与 prompt injection

边界整体很强（只润色、严格 JSON、claim-ID membership、确定性 fallback、无副作用）。但有一处真实漏洞：

**[High] LLM 散文可在"引用合法 claim_id"的同时语义越界，而校验只查 claim_id 是否存在 —— §11.3（L975–977）、§9.5 citation entailment（针对 claim→source，非 summary→claim）**
校验保证引用的 claim_id 属于当前 revision 且可展示，但**不保证生成的自然语言不夸大置信度、不把两条 claim 合成第三条推断、不把 `likely` 说成确定**。citation entailment（§9.5）审的是 claim 对 source 的支持，不审 prose 对 claim 集的蕴含。
**修改：** 增加 **prose→claim 蕴含/NLI 校验**（摘要每句必须被引用 claim 集蕴含，否则拒绝并 fallback），或把 LLM 限制为填充固定模板槽位而非自由成句；并把"summary 越界"纳入回归测试。

**[Medium] excerpt 仍以自由文本进入 LLM，injection 改变摘要语气的对抗测试缺失 —— §11.1/§11.2**
§17.4 有 hostile-webpage golden，但没有"注入试图改变 summary 结论/语气"的专项。
**修改：** 在 §17.2/§17.4 增加"excerpt 内嵌指令不得改变 summary 的 claim 集与语气"的对抗用例。

---

## 7) 阶段依赖、vertical slice、exit gate 与测试具体度

**[High] 99% precision（abstain-first）门 与 useful-brief-yield 门相互拉扯，但两个 launch gate 未连结、无仲裁 —— §16 Phase 1（L1251/L1254）、Phase 6（L1360）、Phase 7（L1382–1383）**
99% 门推动大量 abstain → `insufficient_evidence` 增多 → useful-yield 门（也是 launch gate）下降。这正是本产品的核心可行性 frontier，却被拆到两个 gate、彼此不引用、没人裁决取舍点。
**修改：** 增加一段显式的 precision–yield 权衡说明：把二者作为一条 frontier，规定当冲突时的决策规则（默认优先 precision）、以及谁（Isaac + privacy DRI）在什么数据下批准取舍点。

**[Medium] "安全能力 Phase 2 实现、Phase 5 才 gate"，中间 Phase 3/4 并行修改会让安全/UX 结论失效 —— L1206–1207、Phase 5（L1328）**
Phase 3 provider 扩充改变证据形态，会使 Phase 4 的理解度测试与 Phase 5 的 policy 语料需重跑；三者并行有返工风险。
**修改：** 规定 Phase 4/5 的 exit gate 必须在"参与 gate 的 provider 集冻结"之后跑，或明确任何 provider 变更触发 Phase 4/5 关键测试回归。

**[Medium] 几乎所有量化门都指向"Phase 0 冻结阈值"，当前 plan 的 gate 除 99% 外均为占位 —— §16 多处、§20.2**
这是诚实的，但意味着现在无法判断门是否合理；唯一硬编码的 99% 又可能不可达（见 §3）。
**修改：** 至少给出各阈值的**初始建议区间**（recall/abstention/freshness/cost），供 Phase 0 收敛，避免 Phase 0 从零起。

---

## 8) 仓库结构、API、数据模型、运维与成本缺口

**[Medium] 缺少 `/history` 的列表端点 —— §4.1（L221）有 `/history` 页面，§10.2（L861–865）只有 get-by-id**
无 `GET /v1/search-jobs`（分页/游标）列表端点，前端 history 无法取数。
**修改：** 补 `GET /v1/search-jobs?cursor=&status=` 列表端点及分页契约。

**[Medium] 声称 Python/TS 共享 OpenAPI/JSON Schema，但仓库树无 codegen 落点 —— §5 storage boundary、§15（L1161–1164）**
`packages/` 只有 evidence-schema/policy-schema，无 `openapi/` 或生成产物目录，"共用契约、避免手写双份类型"缺执行位置。
**修改：** 在 §15 增加 `contracts/`（OpenAPI + JSON Schema 源）与生成脚本、生成产物落点，并说明 CI 校验双端类型同步。

**[Low] error_code 目录未枚举 —— §10.6（L914）**。§7.4 只覆盖 job outcome，4xx 的 error_code 无清单。建议附 error_code enum 表。

**[Medium] 无显式成本 kill switch / 花费上限 —— §5.3、§13、§14.1（`search_job_cost`）**
kill switch 覆盖 provider/user/global，但没有基于"每日 $ 花费"的运行时熔断；LLM+浏览器+搜索 API 成本可尖峰。
**修改：** 增加 per-day 全局与 per-user 花费上限熔断，接入 admission control。

**[Medium] `ready_partial` 允许展示来自仅 `likely`（非 confirmed）账号的跨账号事实，这是用户可见误认的主要通道 —— §4.4（L268）、§9.5**
"跨账号事实要求 association ≥ likely"允许把 merely-likely 账号的自述信息并入主体 brief —— 与"0 false merge"目标张力最大之处。
**修改：** 对 consequential 跨账号事实要求 `confirmed`（明确互链）才展示；`likely` 账号的事实只作非 consequential 或标注"疑似同一人的关联账号所述"，不并入主体确定事实。

---

## 9) 重复 / 模糊 / 难执行 / 易误解

- **[Medium] "两个独立 provenance group"的适用范围模糊 —— L273 "每条 consequential claim" vs 整体语气**。§9.4 有 ~10 个 predicate，仅 4 个 consequential；非 consequential claim 单来源是否可展示？请明确：dual-provenance 仅适用于 §9.5 四类，其余按 ready_partial 单来源规则。
- **[Low] ProviderRunStatus 在 §6.4 与 §7.1 两处出现**（后者已声明"使用 §6.4 canonical"，可接受，但仍是漂移风险）。建议单一 enum 源 + 单一转移图。
- **[Low] 全文高度重复**（SLO/eligibility/suppression/dual-provenance 在近乎每节复述）。这是维护性风险：改一条规则要改多处。建议每条规范设**单一 normative 位置**，其余引用。
- **[Low] "硬截止 120s"与 collection/fallback/deadline 均为"默认"值并存**（§5.2）。若 per-policy 可配，"硬"应改为"per completion_policy 冻结"。

---

## 最值得保留的优点

1. **生命周期/一致性机制（§5.2/§7/§8）**：outbox、reconciler、deadline watchdog、acceptance_epoch write fence、lease_generation、CAS finalizer、late_payload_discarded、tombstone —— 直接解决 at-least-once 下的重复/回退/迟到写入，业界少见的完备。
2. **状态枚举严格解耦（§6.4/§7.4）**：ProviderRunStatus / CandidateStatus / ObservationDisposition / job outcome / claim confidence / account association 各自独立，杜绝"timeout→no account""score 混用"这类经典 bug。
3. **分层策略 + 默认拒绝 predicate allowlist（§9.4）**：Collection/Correlation/Display/Logging 四层 + value 级敏感分类，且内部消歧 observation 永不外流。
4. **不可变 snapshot→analysis revision→report revision + 确定性 fallback 永远可交付、LLM 可选（§8.6/§11）**。
5. **独立 provenance group / lineage_key 防同源重复计数（§8.3/§9.5）**。
6. **suppression 与 deletion 双 lifecycle、subject request 无需账户（§8.7/§8.9）**；隐私与主体权利前置为 Phase 0 阻塞门。
7. **vertical slice 先于 provider 广度、benchmark 门控 go/no-go、"无基线不对外承诺数字"**（§16/§21）—— 交付纪律优秀。
8. **明确的非目标与禁止用途（§2.3/§3.2）**，反招聘/反监控/反生物特征立场清晰。

## 建议删除 / 推迟的范围

1. **`verified_consent` 第三方流程 + `/consent/:token` + §10.4 consent issuance → 推迟到 P1**。MVP 仅 self-audit + manual allowlist，砍掉一整套第三方主页控制权验证子系统。
2. **JobAttempt 多 attempt 语义 → MVP 折叠为 1:1 或明确标注 P1 预留**，勿在 MVP 设计多 attempt。
3. **§14.1 约 35 个指标 → alpha 先留核心 ~12 个**（latency SLO、useful yield、false_merge、abstention、claim_precision、citation_entailment、sensitive_leak、cost、browser_seconds、provider_timeout、suppression_completion、abuse_block），其余诊断用后补。
4. **对通用搜索 API 的架构承诺 → 先在 Phase 0 验 ToS**；未通过则走"仅第一方权威页"的 Wave 2 fallback，把搜索 API 降为可选增强。
5. **双语摘要模板**可考虑先单语，降低模板/redaction 双份维护（次要）。

## 按优先级排序的前 10 项修改

1. **[Critical] 校准样本量 vs 99% precision / false-merge 上界**（§16 Phase 1/7、§18）：按每 predicate 所需最小展示正例重设 dataset（远大于 50/50）或分阶段阈值；把 false-merge 目标写成显式数字，明确 300 decisions 来源。
2. **[Critical] 定义 "evidence quorum" 与 "minimum useful brief"**（§4.4/§5.2/§7/§3.1）：给 canonical 定义，其余处一律引用。
3. **[Critical] 把"通用搜索 API 的 ToS 可用性"提为 Phase 0 阻塞决策，并设计不依赖它的 Wave 2 第一方 fallback**（§6.2/§6.3/§20.2）。
4. **[High] 连结 precision 门与 useful-yield 门为单一 frontier + 冲突仲裁规则**（§16 Phase 1/6/7）。
5. **[High] 收紧跨账号事实展示：consequential 跨账号事实要求 `confirmed`，`likely` 账号事实不并入主体确定事实**（§4.4 L268、§9.5）。
6. **[High] 增加 LLM prose→claim 蕴含校验或模板槽位化**，防止引用合法 claim_id 却语义越界（§11.3、§9.5）。
7. **[High] 明确 self/consent 流程的未成年人检测机制**（绑定成人平台 OAuth 或 allowlist 化），或写清 EligibilityObservation 具体信号与 block 规则（§8.8/§13）。
8. **[High] 解决 HMAC-only 标识符与"URL 变体/suppression 绕过检测"的矛盾**：将强 canonicalization 定为主要防线并版本化+测试，承认 per-identifier suppression 的残留风险（§8.1/§10.1/§13）。
9. **[Medium] 缩范围：`verified_consent` 第三方流程与 `/consent/:token` 推迟到 P1**，MVP 仅 self-audit + manual allowlist（§2.1/§10.4/§16 Phase 2）。
10. **[Medium] 补齐 API/仓库缺口**：`GET /v1/search-jobs` 列表端点 + 分页、error_code 目录、`contracts/` codegen 落点、restore 后重放 suppression/tombstone 的硬要求、成本 kill switch（§10.2/§10.6/§15/§12/§5.3）。

---

需要的话，我可以就其中任一条（如 quorum/minimum-useful-brief 的精确定义草案、或样本量→99% 门的数值推导、或 Wave 2 第一方 fallback 设计）给出可直接落到文档的具体措辞。
