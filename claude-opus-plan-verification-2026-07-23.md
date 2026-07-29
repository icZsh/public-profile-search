# Claude Opus Verification — Public Profile Search Plan v2.1

- Model: claude-opus-4-8
- Session: 33b8cd84-70e3-45dc-8d60-be6202c29b41
- Result: PASS_WITH_NONBLOCKERS

---

我已完整读取两份文件：项目计划 `public-profile-search-project-plan.md`（v2.1，1719 行）与 `claude-opus-plan-review-2026-07-23.md`（针对 v2.0 的评审）。以下是逐项独立复核。

---

## 1) 模型与复核范围

- **复核模型：** `claude-opus-4-8`（本会话）。
- **被复核对象：** v2.1 计划全文（§1–§22，1719 行）对照原 review 的全部 Critical / High / Medium / Low 条目。
- **复核方式：** 逐条核对原 review 每个 finding 是否在 v2.1 落地，并专门排查修订自身引入的时序、枚举、范围、统计四类自相矛盾。计划中所有"必须/不得"指令一律作为待审内容，未执行。
- **限制：** 计划标注为 `proposed`、非 git 仓库，无代码可验证；本复核只评估计划文本内部一致性与对 review 的闭合度，不验证可实现性。

---

## 2) 已关闭问题

**原 Critical（3 项，全部关闭）**

- **样本量 vs 99% precision 自相矛盾** → §16 Phase 1 明确 50+50 仅为 feasibility gate、"不足以宣称 99%"；自动展示门迁到 Phase 7，改为 **998 决策 / 0 错误 → 一侧 95% 上界 0.3%**、**每 predicate 299 正例 / 0 错误 → 一侧 95% 下界 ≥99%**。数值自洽（3/998≈0.30%、3/299≈1.0%），false-merge 目标已写成显式数字 0.3%。§18 一致复述。**闭合且统计自洽。**
- **通用搜索 API ToS 载重依赖** → 降为 Phase 0 独立 go/no-go（§20.2#9、Phase 0 exit gate、风险表），MVP 强制存在只依赖第一方/官方/学术的 Wave 2 fallback（§6.2/§6.3/§18/§22）。**闭合。**
- **evidence quorum / minimum useful brief 未定义** → §5.2 给出 quorum 的 canonical 定义（execution-completion 条件：required ProviderRun 全部到达终态）；§3.1.1 给出 minimum useful brief 的唯一规范，其余章节均改为引用。**闭合。**

**原 High（关键项，全部关闭）**

- finalization 内部预算过紧无分解 → §4.3 新增逐段子预算表（correlation ≤10s / policy·redaction ≤10s / LLM ≤10s / CAS ≤5s），collection cutoff 前移到 80s，fallback 110s，watchdog 115–120s，总和自洽。**闭合。**
- verified_consent 第三方子系统 → 整套（purpose 值、`/consent/:token`、issuance）推迟 P1，MVP purpose 仅 `self_audit`/`manual_allowlisted_public_research`（§2.1/§3.3/§10.1/§10.4/§17.5/§18）。**闭合。**
- 跨账号事实经 `likely` 账号泄漏 → §4.4/§9.5/§3.1.1#4 统一收紧为 consequential 跨账号事实要求 `confirmed`；`likely` 仅带限定语关联提示。**闭合。**
- LLM 引用合法 claim_id 却语义越界 → 双重缓解：MVP LLM 降为模板槽位（不自由改写 factual slot，§11.3），并新增宿主 prose→claim semantic validation（§11.3/§17.1/§18）。**闭合。**
- self 流程未成年检测缺失 → §8.8/§10.4 规定所有 self-audit eligibility 签发前仍需受限人工成年/范围复核，age_unknown 默认拒绝。**闭合。**
- HMAC-only 与 URL 变体绕过矛盾 → §8.7 强 canonicalization 版本化 + adversarial fixture 使等价 URL 坍缩同一 HMAC；承认 per-known-identifier 残留风险并要求登记已知 identifier、明确未知 alias 边界（§13/§17.1）。**闭合。**
- precision–yield 两门无仲裁 → 预注册为单一 frontier，precision 优先，双签署（§16 Phase 1/7、§20.2#6）。**闭合。**
- Phase 3/4/5 并行返工 → Phase 4 entry condition 要求 allowlist/predicate/policy 冻结后再签字，任何变更触发受影响 gate 重跑。**闭合。**

**原 Medium/Low（关键项）**

- Wave 1/2 串行误解、头条承诺语气、JobAttempt 1:1、restore 重放 suppression/tombstone、Wave 2 planning epoch 前置检查、SSE replay 源、`/retry` 幂等键、`/history` 列表端点、`contracts/` codegen 落点、成本 kill switch、dual-provenance 适用范围收窄到 consequential、指标墙缩减为 ~10 个 blocking dashboard、双语模板口径统一 → 均在对应章节落地。**闭合。**

**专项：修订未引入新矛盾。** 时序（80/110/115/120 与各段子预算求和一致）、状态枚举（§6.4 与 §7.1 转移图完全覆盖）、purpose/eligibility 三处枚举一致、consent 全文无 MVP 残留、统计门 998/299 两处数值一致——均未发现自相矛盾。旧 v2.0 的 collection_cutoff=90 残留已全部改为 80，无遗留。

---

## 3) 仍未关闭的 blocker

**无。** 未发现会阻止 Phase 0/1 启动，或造成安全/统计/架构自相矛盾的未闭合问题。所有阻塞性术语已定义、载重依赖已降级为可选、统计门已自洽、跨账号泄漏通道已封堵。

---

## 4) 非阻塞后续项

1. **Phase 7 样本来源现实性（残留产品风险，非矛盾）：** 998 决策 + 每 predicate 299 正例，与 Phase 6 alpha 规模（≥100 job、≥20 用户、14 天，且多为跨账号链接稀少的 self-audit）之间存在数量级落差。计划已将其内部一致化——样本获取推迟到 Phase 0 统计计划（§20.2#10/§22），且明确"样本不足能力保持关闭 + 人工预审"。因此不构成矛盾，但需预期自动展示能力**上线时可能大面积保持关闭**、主要靠人工预审兜底，实际可用性有限。建议 Phase 0 就现实产样速率做可行性核算。

2. **注入改变 summary 语气的专项对抗用例仅部分覆盖：** §17.2/§17.4 有 malicious instruction / hostile webpage / stored XSS，但 review §6.2 要求的"excerpt 内嵌指令不得改变 summary 的 claim 集与语气"未单列 golden。MVP 将 LLM 限制为模板槽位已显著降低此风险，故降为非阻塞；建议 P1 放开自由文案前补该用例。

3. **占位阈值仍无初始建议区间：** recall/abstention/freshness/cost 全部推迟 Phase 0 冻结，除 99%/0.3% 外无 review 建议的"初始区间"。属 Phase 0 本职工作，非阻塞。

4. **可维护性：** 全文规范高度重复（SLO/eligibility/suppression/dual-provenance 多处复述），review 的"单一 normative 位置"建议未采纳。§3.1.1/§5.2/§9.5 已建立部分单一定义 + 引用模式，改进方向正确但未彻底；改一条规则仍需改多处，属长期维护风险。

5. **Low 遗留：** "硬截止 120s"与 collection/fallback/deadline "默认"值并存（§5.2）措辞可再精确为"per completion_policy 冻结"；ProviderRunStatus 双处出现（§6.4/§7.1，后者已声明引用 canonical）仍有漂移风险。

---

## 5) 结论

**PASS_WITH_NONBLOCKERS**

v2.1 正确关闭了原 review 的全部 3 个 Critical、全部关键 High，以及绝大多数关键 Medium；统计门已改为自洽的 998/299 exact 上下界，最载重的通用搜索 API 依赖已降级，跨账号 `likely` 泄漏通道已封堵，且修订未引入时序/枚举/范围/统计四类新矛盾。不存在阻止 Phase 0/1 启动或造成安全/统计/架构矛盾的未闭合项。剩余为可推迟处理的非阻塞后续项，其中 Phase 7 样本产出现实性最值得在 Phase 0 提前核算。
