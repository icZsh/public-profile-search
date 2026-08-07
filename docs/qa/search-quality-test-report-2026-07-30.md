# Public Profile Search 搜索质量测试报告与修改建议

- 测试日期：2026-07-30
- 测试环境：本地开发环境
- Web：`http://localhost:3417`
- API：`http://localhost:8800`
- 仓库：`public-profile-search`
- 计划版本：v3.4
- 测试方式：浏览器端到端操作、API 读取、PostgreSQL 只读核验、代码走查、完整测试与构建
- 代码修改：本报告生成前未修改项目源码；测试产生的合成 job 已删除

> **v3.4 OpenRouter integration addendum:** Deep composition can now select a
> snapshotted `openrouter` or `openai` gateway. OpenRouter uses the fixed stateless
> Responses endpoint, strict JSON Schema, `require_parameters=true`, and
> `data_collection=deny`; web-search plugins remain disabled so all rendered citations
> still originate in the frozen evidence ledger. The local provider is set to
> OpenRouter, but no `OPENROUTER_API_KEY` is present, so a live authenticated story
> run remains pending that credential. Full verification: 197 Python tests + 6 Web
> tests, contracts, Ruff, ESLint, TypeScript, and Next production build.
> A no-charge end-to-end smoke run (`3081d3f5-d4a4-47dd-a8af-627f9566e503`)
> confirmed the frozen gateway `openrouter`, model `openai/gpt-5.6-sol`, terminal
> `ready_partial`, and explicit `openrouter_api_key_missing` fallback.

> **v3.3 implementation addendum（2026-07-30 20:55 PDT）：** 下文第 1–17
> 节保留为修改前基线。本轮实现后，Quick 与 Deep 已共享 adaptive professional
> retrieval；Deep 另有严格 source-grounded LLM story pass。当前机器未配置
> `OPENAI_API_KEY`，因此 live Deep 结果会明确显示 Quick-grade partial fallback，
> 不能把 fallback 当成新 story 质量样本。

### v3.3 live recheck

| 项目 | 结果 |
|---|---|
| Quick `octaviyao` job | `4864ed0e-9ebf-467e-9775-afe5d150a1fe` |
| Deep `octaviyao` job | `2933ad3d-1518-4e58-ac28-bb87befa448b` |
| Catalog | 20 / 20 complete；4 claimed；13 available；3 channel-limited |
| Quick professional retrieval | 3 GitHub runs，均记录 `retrieval_mode=adaptive` |
| Current brief | 8 assessed accounts；23 deterministic claims；account-centric / unverified |
| Deep composer | prompt `grounded-footprint-v2`；6,000 output-token budget；因缺 key 记录 `openai_api_key_missing` |
| Fallback UX | 明确显示 “Deep story unavailable · Quick-grade fallback” |
| Verification | 186 Python tests + 6 Web tests；contracts、Ruff、ESLint、TypeScript 与 Next build 全部通过 |

与 `octaviyao` golden fixture 的剩余差距现在更清晰：

1. **检索缺口：** 当前 live run 没有 fixture 所依赖的 LinkedIn professional-index
   证据，因此不能合法重建 TikTok role、UIUC education 或 `person_centric / likely`
   结论。
2. **配置缺口：** 本机没有 OpenAI key，所以无法对真实 evidence packet 执行 live
   v2 story composition。
3. **已完成的产品缺口：** v2 schema/UI 已能承载 one-sentence conclusion、identity
   snapshot、account insights、narrative chapters、curated findings、excluded
   candidates、channel coverage、evidence index 与 reassessment conditions；LLM
   输出中的每个事实块必须引用已冻结的 source ID，且不得提升 deterministic identity
   status。
4. **已完成的边界修复：** Deep 若未实际执行 synthesis 会终止为 `ready_partial`；
   `medium_high` claim confidence 可完整通过 provider、API 与 UI；嵌套 narrative、
   account、claim、coverage 与 reassessment citations 均会渲染并进入 evidence index。

## 1. 执行摘要

当前 Web 应用能够稳定完成一个快速、可审计的 Maigret 用户名候选扫描，但尚不能复现 `public-profile-osint` 的人物调查质量。

当前实际链路为：

```text
platform + handle
→ 固定 18 站 Maigret quick scan
→ MaigretSiteCheck
→ AccountNode / DiscoveryEdge / DiscoveredIdentifier
→ unresolved candidate cards
→ 结束
```

目标链路应为：

```text
seed resolution
→ bounded candidate discovery
→ first-party candidate verification
→ identity resolution / competing hypotheses
→ SourceObservation / Claim / ClaimEvidence
→ account-centric or person-centric Fast Brief
→ optional evidence map and Deep Report
```

根本差距不是单一 provider 故障，而是新 footprint discovery 管线停在“候选发现”，没有进入证据快照、身份聚类、Claim、置信度决策和报告生成。旧 Fast Brief 虽然已有 `SourceObservation → Claim → ReportRevision` 基础设施，但仅服务于旧 GitHub eligibility 流程，两条管线尚未连接。

**核心产品建议：默认结果恢复为 Fast Brief；identity graph 保留为二级“证据地图 / 高级探索”视图。**

## 2. 测试范围与方法

### 2.1 Live 测试用例

| 用例 | 输入 | 目标 |
|---|---|---|
| 已知账号基准 | `Instagram · im_cc_c7` | 与既有深度调查结果比较召回、身份边界和报告完整度 |
| 高碰撞用户名 | `GitHub · torvalds` | 检查同 handle 不同人的隔离、来源语义和误报 |
| 明显不存在 | `Platform unknown · zzzz_tracebrief_nohit_20260730` | 检查 no-hit、channel-limited 和 invalid 的区别 |
| 另一不存在用例 | `GitHub · zzzxqvnosuchprofile20260730` | 独立复核空状态与平台限制 |
| 不存在 job | 随机不存在的 footprint UUID | 检查 404、轮询终止和错误 UX |
| 输入边界 | 空值、三个空格 | 检查规范化与可见验证反馈 |

测试完成后，上述合成/QA job 已删除；`im_cc_c7` 基准 job 保留用于复查。

### 2.2 代码与数据核验

核验了：

- 首页表单和结果页轮询；
- `/v1/footprint-jobs`、candidates、events 和 deletion API；
- Maigret catalog、adapter、site-check 归一化；
- PostgreSQL 中的 `SearchJob`、`ProviderRun`、`MaigretSiteCheck`、`AccountNode`、`DiscoveryEdge`、`DiscoveredIdentifier`；
- 旧 Fast Brief 的 `SourceDocument`、`SourceObservation`、`CollectionSnapshot`、`Claim`、`ClaimEvidence`、`ReportRevision`；
- OpenAPI、generated client、provider tests 和 Web tests。

### 2.3 验证命令

```bash
make check
```

结果：

- Contracts：通过；
- Ruff：通过；
- ESLint：通过；
- Python：85 passed；
- Web：6 passed；
- Next.js production build：通过；
- 已知非阻断 warning：Starlette TestClient/httpx deprecation。

现有测试证明 lifecycle、队列、持久化、删除和 UI plumbing 能工作；它们尚未证明身份解析、误报隔离、报告质量或真实 Fast Brief SLA。

## 3. Live 测试结果

### 3.1 `im_cc_c7`

运行结果：

- 18/18 站点调度完成；
- 约 3.56 秒进入终态；
- 只产生一个 Instagram candidate；
- 页面状态为 `ready_partial`；
- API 已存储 display name、bio、公开计数等解析字段，但 UI 基本未展示；
- Threads、Penn 关联边界、AI creator 内容信号、排除候选和人物摘要均未生成。

与既有人工调查基准相比，当前 Web 缺失：

- Instagram 与 Threads 的第一方账号簇；
- `SF/Bay` 作为公开自述；
- `@uofpenn` 仅支持“likely affiliation，关系类型未知”的边界；
- AI/creator 内容信号；
- real name / degree / employer 为 unknown；
- channel-limited 与 excluded 候选；
- claim-level source IDs。

本次底层站点状态还显示：

- LinkedIn 返回 HTTP 429，但被归为 `not_found`；
- ProductHunt 返回 429 / bot protection；
- Reddit 返回 403 / CAPTCHA；
- GitHub 因 handle 格式不支持而 `inapplicable`。

### 3.2 `torvalds`

独立 QA 观察到：

- 18/18 站点完成；
- 11 个 `CLAIMED` candidate；
- GitHub 显示名为 Linus Torvalds；
- Instagram/Pinterest 显示名为 Marco Migozzi；
- Medium 显示名为 Patricia Torvalds；
- 所有候选仍统一为 `relationship=unresolved`、`identity_tier=possible`、`selection_state=undecided`。

明显来源语义问题：

- StackOverflow candidate 指向用户搜索页，而不是具体账号，应该 `excluded`；
- “Twitch”candidate 实际来自第三方 TwitchTracker，应该标为 `derivative`，不能作为独立第一方来源；
- `Why this appeared` 仅显示 `username catalog probe · CLAIMED`，不足以审计账号存在或人物归属。

该 footprint job 在以下表中均没有记录：

- `collection_snapshot`；
- `analysis_revision`；
- `claim`；
- `report_revision`。

这证明新 discovery 管线尚未进入分析与报告阶段。

### 3.3 不存在用户名

观察到：

- 扫描调度完成 18/18；
- 约 3 秒进入终态；
- 页面同时存在 `100%`、`PARTIAL DISCOVERY COMPLETE` 和 `Some sites could not be checked`；
- 空状态写 `No candidates found`；
- 页面不列出 unknown / invalid 对应站点和原因。

更准确的用户文案应为：

> No exact candidates were found in the conclusive checks. Some channels were limited or did not support this handle format.

不应暗示“公开网络不存在该账号”。

### 3.4 不存在 job

直接访问不存在的 footprint UUID 时，页面同时显示：

- `CONNECTING`；
- `The discovery job was not found. Retrying automatically.`；
- `Waiting for the first catalog match…`。

轮询不会稳定终止，也没有手动重试、重新搜索或错误终态。这会让永久 404 看起来像仍在运行的任务。

### 3.5 输入边界

- 空输入依赖浏览器原生 `required`；
- 三个空格可通过 `required`，提交后无跳转，也无可见错误；
- 没有展示规范化后的 handle；
- 没有平台字符规则或 URL/`@handle` 输入提示。

### 3.6 浏览器稳定性

- 正常搜索和异常路径均未发现 JavaScript exception；
- UI 视觉层级清楚，深色风格可保留；
- 问题集中在产品语义、错误状态和结果信息架构，而非渲染稳定性。

## 4. 当前架构与断点

### 4.1 新 Footprint Discovery

```text
FootprintSearchForm
→ POST /v1/footprint-jobs
→ SearchJob + JobAttempt
→ 18 sites / 3 Maigret ProviderRun shards
→ OutboxMessage
→ Celery maigret_scan queue
→ MaigretDiscoveryAdapter
→ MaigretSiteCheck
→ AccountNode / DiscoveryEdge / DiscoveredIdentifier
→ candidate count determines ready / ready_partial
→ GET candidates
→ Web polling and candidate cards
```

关键文件：

- `apps/web/components/FootprintSearchForm.tsx`；
- `apps/web/components/FootprintJobExperience.tsx`；
- `apps/web/components/CandidateResults.tsx`；
- `apps/api/app/services/discovery_jobs.py`；
- `apps/api/app/services/maigret_runs.py`；
- `apps/api/app/services/candidates.py`；
- `workers/providers/maigret_adapter.py`；
- `config/maigret-catalog-v0.6.3.json`。

### 4.2 旧 Fast Brief

```text
POST /v1/search-jobs
→ GitHub/fixture provider
→ SourceDocument / SourceObservation
→ CollectionSnapshot
→ correlate_explicit_link
→ Claim / ClaimEvidence
→ deterministic FastBrief
→ ReportRevision
```

关键文件：

- `apps/api/app/services/provider_runs.py`；
- `apps/api/app/services/finalization.py`；
- `workers/correlator/explicit_link.py`；
- `workers/summarizer/deterministic.py`；
- `apps/api/app/policy/display.py`。

### 4.3 主要断点

1. 新管线不创建 SourceObservation、snapshot、Claim 或 Report；
2. 旧管线不消费 AccountNode、MaigretSiteCheck 或 DiscoveredIdentifier；
3. `relationship` 在 candidates API 中固定为 `unresolved`；
4. `identity_confidence_tier` 实际只映射 exact/similar handle，不是人物置信度模型；
5. 没有 PersonHypothesis、ClusterMembership、AssociationEdge、EvidenceSignal 或 graph revision 实现；
6. extracted identifiers 被持久化为 `scheduled=False`，未执行安全递归；
7. 平台选择只被持久化，不改变 provider plan。

## 5. 根因与严重度

### S0：阻断产品目标

#### S0-1 新搜索不进入分析与报告

`finalize_discovery_if_complete()` 只依据 provider 终态和 AccountNode 数量决定 job 状态，没有生成冻结快照、分析 revision、Claim 或 ReportRevision。

#### S0-2 没有人物假设与身份聚类

账号存在性和人物归属尚未建模。当前 `possible/weak` 只是 Maigret exact/similar handle 映射。

### S1：严重影响准确率和可信度

#### S1-1 Scanner 状态覆盖渠道错误

`AVAILABLE` 在 HTTP 429/403/999、CAPTCHA、auth 和 timeout 之前被映射为 `not_found`。渠道失败必须保留为 `channel_limited`。

#### S1-2 起始平台不驱动 native resolver

Instagram、GitHub、LinkedIn 等平台选择不会改变执行计划。平台控件目前是元数据，不是搜索上下文。

#### S1-3 任何 `found` 都可直接创建 AccountNode

缺少：

- 第一方账号页与搜索页区分；
- mirror / derivative / aggregator 分类；
- soft 404 和 generic 200 验证；
- source lineage 和 independence group；
- 稳定 UID、显示名和强冲突检查。

#### S1-4 Coverage 只有 18 站静态 Maigret

当前 quick profile 缺少 Threads、通用 web search、专业/教育、学术、个人域名、大陆平台和高价值 native enrichers。ProductHunt/Reddit 等已知受限站点还会让几乎所有 job 结构性 `ready_partial`。

#### S1-5 证据抽屉不足以支持审计

candidate evidence 未显示实际 probe URL、source type、HTTP/channel 状态、命中规则、摘录、独立证据 ID、positive/negative signals 或 association confidence。

#### S1-6 不存在 job 无限重试

永久 404 没有终止轮询和稳定错误页。

### S2：数据治理和体验问题

#### S2-1 `profile_data` 任意字段直接返回浏览器

Maigret `ids_data` 原样进入 `profile_data.fields`，实测可包含内部平台 ID、Facebook UID、extractor 字段、签名头像 URL、hash 和其他任意属性。

#### S2-2 Root-equivalent pivot 被算作新线索

`im_cc_c7` 的“1 additional identifier”实际还是 root seed 自己。root 和祖先等价 pivot 应 cycle-suppressed。

#### S2-3 Job terminal state 语义过敏

任何可选站点失败都可能让整个 job `ready_partial`。应根据 required-provider quorum 和 minimum useful brief 决定终态。

#### S2-4 输入与空状态反馈不足

需要 trim、格式规范化、行内错误和更准确的 coverage 文案。

#### S2-5 旧报告输出仍过窄

旧 display policy 只允许 display name、verified input profile、explicitly linked profile 等极少 predicate，且 deterministic summary 主要是英文静态句子。

## 6. 建议目标架构

```text
Input normalization
  ↓
Native seed resolver (required for platform-scoped seed)
  ↓
Bounded candidate discovery (Maigret + web/provider fan-out)
  ↓
Source policy and first-party verification
  ↓
AccountCandidate / SourceObservation
  ↓
PersonHypothesis + AssociationEdge + EvidenceSignal
  ↓
Deterministic identity and claim rules
  ↓
CollectionSnapshot / AnalysisRevision / Claim / ClaimEvidence
  ↓
Fast Brief (≤120s, ready or ready_partial)
  ↓
Evidence Map / User decisions / Deep Report
```

### 6.1 分离状态轴

不要用单一 `normalized_status` 同时表达传输、账号存在和人物归属。

```text
scanner_status:
  CLAIMED | AVAILABLE | UNKNOWN | ILLEGAL

channel_status:
  success | rate_limited | captcha_blocked | auth_required |
  timeout | provider_error | unsupported

existence_status:
  exact_verified | claimed_unverified | no_exact_hit |
  channel_limited | excluded

identity_status:
  confirmed | likely | unverified | conflicting | excluded

selection_state:
  undecided | included | excluded
```

### 6.2 来源类型

```text
first_party_profile
first_party_api
official_organization
search_index
availability_endpoint
derivative_mirror
aggregator
search_page
user_supplied
```

默认规则：

- 搜索页和 query echo：`excluded`；
- mirror/aggregator：`derivative`，共享 independence group；
- availability endpoint：只能证明 occupancy/existence signal；
- generic 200：必须检查精确 profile object/metadata；
- Maigret `CLAIMED`：candidate discovery，不是 same-person 证据。

### 6.3 最低可用 Fast Brief

Fast Brief 应至少包含：

- account-centric 或 person-centric 类型；
- likely identity/display name，或明确 `real name unknown`；
- confirmed / likely / unverified / excluded accounts；
- broad location、institution、role、content focus 等可支持 claim；
- identity-resolution reasons；
- contradictions 和 unknowns；
- channel limitations；
- 每个展示事实的 source IDs。

## 7. 修改建议与实施切片

### P0：结果必须先“诚实”

涉及文件：

- `workers/providers/maigret_adapter.py`；
- `apps/api/app/services/maigret_runs.py`；
- `apps/api/app/services/candidates.py`；
- `contracts/openapi.yaml`；
- `packages/generated-api-client/src/index.ts`；
- `apps/web/components/CandidateResults.tsx`；
- `apps/web/components/FootprintJobExperience.tsx`；
- `apps/web/components/FootprintSearchForm.tsx`。

交付：

1. 403/429/999/CAPTCHA/auth/timeout 永不折算为 no hit；
2. 增加 per-site channel results；
3. 增加 source type，并排除搜索页；
4. derivative/mirror 不算独立证据；
5. provider-specific public-field allowlist；
6. root/ancestor pivot cycle suppression；
7. 404 停止轮询；5xx/网络错误使用有限重试；
8. 输入 trim、`@` 规范化和行内错误；
9. 重写 100%/partial/no-candidate 文案；
10. optional catalog failures 不再自动决定 job `ready_partial`。

P0 验收：

- `AVAILABLE + HTTP 429` → `channel_limited`；
- StackOverflow 搜索页 → `excluded`；
- TwitchTracker → `derivative`；
- candidates API 不出现内部 UID、hash、extractor 字段或签名头像 URL；
- 不存在 UUID 在一次 404 后进入稳定错误页；
- 三个空格显示行内错误；
- root-equivalent extracted ID 不计入 expansion count。

### P1：一个真正的 Instagram/Threads 垂直切片

以 `im_cc_c7` 作为 golden fixture：

```text
Instagram seed
→ Instagram first-party exact verification
→ Threads same-handle first-party probe
→ Meta account cluster
→ bio/public metrics/content signals
→ broad location + institution signals
→ identity boundary
→ sourced account-centric Fast Brief
```

交付：

1. `seed_platform=instagram` 调度 native resolver；
2. Instagram first-party adapter；
3. Threads public-page adapter；
4. native observations 进入 SourceObservation；
5. account existence 与 same-person association 分离；
6. deterministic account-centric claim builder；
7. Fast Brief 页面首屏。

P1 验收：

- Instagram 和 Threads 正确进入账号簇；
- `SF/Bay` 标为 self-description；
- Penn 只能输出 `likely affiliation; relationship type unknown`；
- real name、degree、employer 保持 unknown；
- LinkedIn 429 显示 channel-limited；
- 每个展示 claim 有 source IDs；
- 120 秒内返回 `ready` 或 `ready_partial`。

### P2：连接统一 Claim/Evidence/Report 管线

复用现有：

- `SourceDocument`；
- `SourceObservation`；
- `CollectionSnapshot`；
- `AnalysisRevision`；
- `Claim` / `ClaimEvidence`；
- `ReportRevision`。

扩展 display predicates：

```text
identity.display_name
identity.alias
account.exact_profile
account.association
location.broad_self_description
institution.affiliation
role.current_or_recent
content.focus
project.authorship
publication.authorship
candidate.excluded
channel.limited
```

要求：

- identity/employer/exact degree/current location/publication attribution 通常需要两个支持信号；
- 单一 public index 必须标记可能 stale；
- contradiction 可阻止 promotion；
- 模型只能叙述已有 claim/source IDs；
- schema 失败时使用 deterministic fallback。

### P3：Evidence Map、用户决策与 Deep Report

在默认 Fast Brief 之后实现：

- include / exclude；
- merge / split；
- expand；
- quarantined pivot；
- immutable graph revision；
- report rebuild；
- asynchronous Deep Report。

不建议在 P0/P1 前优先构建完整图编辑器。图是解释和修正工具，不应成为用户取得第一份答案的前置条件。

## 8. 推荐页面信息架构

### 8.1 首页

- 平台；
- handle 或公开 profile URL；
- 可选 hints：known name、organization、broad location；
- 模式：Fast Brief / Deep Report；
- 公开来源和预计时间说明；
- 输入规范化预览。

在完整 footprint 尚未实现前，首页承诺应从：

> Map a person's public digital footprint.

收窄为：

> Find possible public profiles connected to a handle.

### 8.2 结果页

1. **Identity summary**：人物或账号型、整体 confidence、明确 unknowns；
2. **Account cluster**：confirmed / likely / unverified；
3. **Public claims**：教育、职业、项目、内容、宽泛地点；
4. **Identity reasons**：正向、负向、冲突信号；
5. **Excluded candidates**；
6. **Channel coverage**：no exact hit / channel limited / unsupported；
7. **Evidence map**：高级视图；
8. **Deep Report**：异步操作。

### 8.3 等待和错误状态

- 显示阶段、已耗时、deadline；
- 显示 completed / limited / error provider 数；
- 支持取消、手动重试、停止自动重试；
- 404 永久终止；
- 网络/5xx 使用有限退避；
- `ready_partial` 必须解释缺失的 required evidence。

## 9. 测试建议

### 9.1 Golden fixtures

| Fixture | 主要风险 | 期望 |
|---|---|---|
| `im_cc_c7` | 实名缺失、Meta 账号簇、Penn 边界 | account-centric；不补全实名 |
| `octaviyao` | 显示名差异、职业索引时效 | likely person-centric；非 confirmed |
| `delia.zhao` | 短 alias 递归污染 | 弱 pivot quarantine |
| `torvalds` | 同 handle 多人、搜索页、镜像 | 不自动聚类；搜索页 excluded |
| nonexistent handle | no hit 与 channel-limited 并存 | 精确覆盖说明 |
| common alias | 高用户名碰撞 | competing hypotheses |

### 9.2 Provider contract tests

必须覆盖：

- `AVAILABLE + 429/403/999`；
- `UNKNOWN + 403`；
- generic 200；
- soft 404；
- search page/query echo；
- mirror/derivative；
- schema drift；
- timeout/captcha/auth；
- internal-field redaction；
- exact-handle first-party verification。

### 9.3 Browser-to-worker E2E

当前 Web tests 主要读取源码字符串，需要增加真正的 Playwright E2E：

1. 输入平台 + handle；
2. 确认平台选择改变 provider plan；
3. 观察 discovery → verifying → summarizing；
4. 检查 per-provider channel state；
5. 检查 claim 和 source IDs；
6. 检查 competing candidates；
7. 检查 404 终止；
8. 检查 partial/deadline fallback；
9. 删除 job 并验证不可读取。

## 10. 可保留的现有能力

以下基础不建议推倒重做：

- FastAPI + Next.js；
- PostgreSQL durable state；
- Celery / Redis / outbox；
- 3 秒级常见 Maigret quick scan；
- catalog checksum 和版本 provenance；
- progressive candidate persistence；
- deletion、retention、suppression；
- no-store、noindex、no-referrer；
- Safe Fetch 和 provider boundary；
- SourceObservation / Claim / ReportRevision 基础模型；
- 当前深色视觉系统。

## 11. 对外部署风险

本报告针对 localhost 原型。若从本地页面变成可共享网站，以下是 release gates：

- 正式登录和 per-user/IP rate limit；
- 禁止 bulk enumeration；
- removal/deletion 和 cache expiry；
- provider terms/legal review；
- secrets 与 server-only token；
- egress isolation；
- 敏感字段双重 redaction；
- 不输出私人电话、私人邮箱、家庭住址或实时精确位置；
- 不绕过登录、验证码、付费墙或私密账号；
- 不做人脸识别。

## 12. 推荐的下一实施目标

最短价值路径：

```text
P0 truthfulness fixes
→ Instagram/Threads native vertical slice
→ account-centric Fast Brief
→ shared Claim/Evidence pipeline
→ evidence map and graph editing
```

第一里程碑应以以下结果为准，而不是候选数量：

> 给定一个 Instagram handle，系统能在 120 秒内返回一份 source-linked、边界清晰、不补全未知实名的账号型 Fast Brief，并把所有未验证账号、排除项和受限渠道明确分组。

## 13. 附录：报告样例

以下两个 Markdown 样例可同时用于产品设计、golden fixture 和 E2E 预期：

- [Account-centric sample：im_cc_c7](../report-samples/im_cc_c7-account-centric.md)
- [Person-centric sample：octaviyao](../report-samples/octaviyao-person-centric.md)

样例来自此前已完成的公开资料调查。它们展示的是目标输出结构，不表示当前 localhost 已具备这些能力。
