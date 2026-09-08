/**
 * Forseti v2.0 — P11 Incident Aggregator / Warning Storm
 *
 * 規格來源:`docs/spec-v2.0.md` §21(FS-FP-002)、§24、§28.4。
 * 對應 CT-033、CT-034、CT-035、CT-036。
 *
 * ── 這個模組防的是 Forseti 自己 ─────────────────────────
 *
 * 規格書最後一句:
 *
 *   「Forseti 如果讓使用者從『AI 的 QA』變成『Forseti warning 的 QA』,
 *     就是失敗。」
 *
 * §24 的來源是 owner 回報:另一個正在開發 Forseti 的 AI,開發過程中
 * 出現超過 25 次 warning。那 25 條的原始清單目前沒有,所以無法判斷
 * 每一條對不對 —— 但這件事本身就足以暴露一個產品級需求:
 * 即使每個 detector 都有效,warning flood 仍然會摧毀生產力。
 *
 * FS-IMP-002 講得更硬:在這個 aggregator 完成之前,禁止把所有
 * detector hits 直接推給使用者。
 *
 * ── 三層,不是一層 ───────────────────────────────────
 *
 *   detector hit        偵測器每次命中。可以有幾百個。
 *   root incident       同一個根因聚合起來的一件事。應該只有幾個。
 *   user-visible warning 真的打斷人的那一個。應該極少。
 *
 * FS-ALR-001 要求三層必須分開。混在一起的時候,一百個 hit 就會變成
 * 一百次打斷,而那正是 owner 遇到的 25 次。
 *
 * 零依賴。
 */

export const VERSION = 'incident@2.0';

/** FS-ALR-001 的三層。 */
export const LAYERS = Object.freeze(['DETECTOR_HIT', 'ROOT_INCIDENT', 'USER_VISIBLE_WARNING']);

/**
 * FS-ALR-003 的四個升級理由。純時間經過刻意不在裡面。
 *
 * 這張表是白名單:不在表上的理由,一律不足以再打斷人一次。
 */
export const ESCALATION_REASONS = Object.freeze([
  'NEW_EVIDENCE',
  'SEVERITY_CROSSING',
  'SCOPE_EXPANSION',
  'RECURRENCE_AFTER_RECOVERY',
]);

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 【§24.1 的兩個門檻都是 POC calibration candidate,不是 STABLE 常數。】
   * 規格書原文說要「用你目前那 >25 warning 的開發 session 立刻校準」,
   * 而那份原始清單目前拿不到,所以這兩個數字仍然未校準。
   */
  maxVisibleWarningsPer10Min: 5,
  maxSameRootRepeatWithoutStateChange: 2,
});

/**
 * 從一組 findings 算出 root incident key。
 *
 * FS-FP-002:多個 primitive 可以共用同一 root cause。這個函式決定
 * 「共用」的判準,而判準必須是可重播的,不能靠模型看一眼覺得像。
 *
 * 判準:受影響的資源。同一個資源上的問題就是同一件事,
 * severity 取最嚴重的,命中的 primitive 全部列進去。
 *
 * ── 這裡錯過兩次,兩次都是同一個毛病,留著當紀錄 ──────────
 *
 * 第一版把 severity_family 放進 key。錯的:嚴重度是 finding 的屬性,
 * 不是根因的身分。同一個檔案上一個 A 級加一個 C 級會被拆成兩件事,
 * 而那正是 FS-FP-002 要防的東西。放進去的理由是「怕 C 級被稀釋」,
 * 擔心對但解法錯 —— 不被稀釋靠的是 aggregate 對 severity 取 max。
 *
 * 第二版把 evidence_refs 放進 key。也是錯的,而且更難發現:
 * CT-034 用人造資料測,那批 findings 共用同一組 evidence_refs,
 * 所以 25 個 hit 漂亮地收斂成 3 件事。真實資料上每一筆證據的時間戳
 * 都不同,key 就每次都不同 —— 掃 40 個真實 session 時,63 個 hit
 * 變成 63 個 incident,壓縮率是 0,聚合層等於不存在。
 *
 * FS-ALR-002 其實已經講清楚了:它把「同一 evidence state」列為
 * **去重的判斷條件**,不是 key 的一部分。證據是 incident 的內容,
 * 不是它的身分。內容變了要重新評估要不要再說一次(shouldSurface),
 * 但它從頭到尾都是同一件事。
 *
 * 兩次的共同毛病:把不屬於身分的東西放進身分。
 */
export function rootIncidentKey(finding) {
  return String(
    finding?.resource ?? finding?.synthetic_claim_ref ?? finding?.task_id ?? 'unknown',
  );
}

/**
 * 把一堆 detector hit 聚合成 root incident。
 *
 * CT-034:25 個 detector hits 對應 3 個 root cause 時,使用者應該看到
 * 3 件事,不是 25 個 warning。
 */
export function aggregate(findings = []) {
  const byKey = new Map();
  for (const f of findings) {
    const key = rootIncidentKey(f);
    if (!byKey.has(key)) {
      byKey.set(key, {
        root_incident_key: key,
        severity_family: f.severity_family ?? 'A',
        primitives: new Set(),
        findings: [],
        evidence_refs: new Set(),
      });
    }
    const inc = byKey.get(key);
    inc.primitives.add(f.primitive_id ?? 'unknown');
    inc.findings.push(f);
    for (const r of (f.evidence_refs ?? [])) inc.evidence_refs.add(r);
    // family 取最嚴重的。C > B > A。
    const rank = { A: 0, B: 1, C: 2 };
    if (rank[f.severity_family ?? 'A'] > rank[inc.severity_family]) {
      inc.severity_family = f.severity_family;
    }
  }

  const incidents = [...byKey.values()].map((inc) => Object.freeze({
    root_incident_key: inc.root_incident_key,
    severity_family: inc.severity_family,
    /** 一個 incident 底下有哪些 primitive 命中。UI 顯示的是 incident,不是這些。 */
    primitives: Object.freeze([...inc.primitives].sort()),
    detector_hit_count: inc.findings.length,
    evidence_refs: Object.freeze([...inc.evidence_refs].sort()),
    findings: Object.freeze([...inc.findings]),
  }));

  // 最嚴重的排前面。C 一定在最上面,因為它可以繞過溫度計。
  const rank = { C: 0, B: 1, A: 2 };
  incidents.sort((a, b) => rank[a.severity_family] - rank[b.severity_family]
    || b.detector_hit_count - a.detector_hit_count);

  return Object.freeze({
    detector_hits: findings.length,
    root_incidents: Object.freeze(incidents),
    /** CT-034 的數字對比。這兩個數字擺在一起,是為了讓比例看得見。 */
    compression: findings.length === 0 ? null : incidents.length / findings.length,
    version: VERSION,
  });
}

/**
 * 這件事該不該再打斷使用者一次。
 *
 * FS-ALR-002:同一 root_incident_key、同一 evidence state、沒有新的
 * downstream impact 時,MUST deduplicate。
 * FS-ALR-003:升級需要四個理由之一。純時間經過不是理由。
 *
 * @param {object} incident 現在這一件
 * @param {object|null} previous 上次對這個 key 顯示過的狀態
 */
export function shouldSurface(incident, previous = null) {
  if (!previous) {
    return Object.freeze({
      surface: true,
      reason: 'FIRST_OCCURRENCE',
      version: VERSION,
    });
  }

  const evidenceChanged = JSON.stringify([...(incident.evidence_refs ?? [])])
    !== JSON.stringify([...(previous.evidence_refs ?? [])]);
  const severityRank = { A: 0, B: 1, C: 2 };
  const severityCrossed = severityRank[incident.severity_family]
    > severityRank[previous.severity_family];
  const scopeExpanded = (incident.detector_hit_count ?? 0) > (previous.detector_hit_count ?? 0)
    && evidenceChanged;
  const recurredAfterRecovery = previous.recovered === true;

  const reasons = [
    evidenceChanged ? 'NEW_EVIDENCE' : null,
    severityCrossed ? 'SEVERITY_CROSSING' : null,
    scopeExpanded ? 'SCOPE_EXPANSION' : null,
    recurredAfterRecovery ? 'RECURRENCE_AFTER_RECOVERY' : null,
  ].filter(Boolean);

  if (!reasons.length) {
    return Object.freeze({
      surface: false,
      reason: 'DEDUPLICATED',
      /** CT-033:同一個根因、同樣的證據、沒有狀態改變 = 同一件事,不再打斷。 */
      note: 'Same root incident, same evidence, no new downstream impact. Time passing is '
        + 'not a reason to interrupt again (FS-ALR-003).',
      version: VERSION,
    });
  }
  return Object.freeze({
    surface: true,
    reason: 'ESCALATION',
    escalation_reasons: Object.freeze(reasons),
    /** CT-035:嚴重度上升時更新既有的卡片,而不是開新的。 */
    updates_existing_card: true,
    version: VERSION,
  });
}

/**
 * §24.1 Warning Storm candidate detector。
 *
 * ```
 * visible_warning_rate  = visible_warning_count / time_window
 * same_root_repeat      = warnings_same_root_without_state_change
 * warning_actionability = warnings_with_distinct_action / total_visible_warnings
 * ```
 */
export function warningStorm({
  visibleWarnings = [],
  windowMs = 10 * 60 * 1000,
  config = DEFAULT_CONFIG,
} = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  if (!visibleWarnings.length) {
    return Object.freeze({
      verdict: 'OK', visible_warning_count: 0, actionability: null,
      version: VERSION,
    });
  }

  const per10Min = visibleWarnings.length / (windowMs / (10 * 60 * 1000));
  const byRoot = new Map();
  for (const w of visibleWarnings) {
    const k = w.root_incident_key ?? 'unknown';
    if (!byRoot.has(k)) byRoot.set(k, []);
    byRoot.get(k).push(w);
  }
  const sameRootRepeats = [...byRoot.entries()]
    .map(([k, list]) => ({ key: k, repeats: list.filter((w) => w.state_changed !== true).length }))
    .filter((x) => x.repeats > c.maxSameRootRepeatWithoutStateChange);

  const distinctActions = new Set(
    visibleWarnings.map((w) => w.suggested_action).filter(Boolean),
  );
  const actionability = distinctActions.size / visibleWarnings.length;

  const storm = per10Min > c.maxVisibleWarningsPer10Min || sameRootRepeats.length > 0;

  return Object.freeze({
    verdict: storm ? 'WARNING_STORM_CANDIDATE' : 'OK',
    visible_warning_count: visibleWarnings.length,
    visible_warning_rate_per_10min: per10Min,
    same_root_repeats: Object.freeze(sameRootRepeats.map((x) => Object.freeze(x))),
    /** 低 actionability 是最壞的一種:很多警告,而它們要人做的事是同一件。 */
    actionability,
    distinct_actions: distinctActions.size,
    /** CT-036:進入 storm 時 UI 切換成 Incident Summary Mode。 */
    ui_mode: storm ? 'INCIDENT_SUMMARY' : 'NORMAL',
    primitive_id: 'FP-23',
    thresholds_uncalibrated: true,
    note: storm
      ? 'Forseti is generating warnings faster than a person can act on them. This is the '
        + 'failure mode where the governance system becomes the thing that needs governing '
        + '(FP-23).'
      : null,
    version: VERSION,
  });
}

/**
 * §24.2 Governance Overhead。
 *
 * ```
 * GovernanceOverheadRatio = interruption_time_caused_by_forseti / active_work_time
 * ```
 *
 * FS-ALR-005:如果 Forseti 需要使用者反覆判斷「哪個 warning 要管」,
 * 它正在重演 Human-as-QA。治理系統本身也要接受自我監測。
 */
export function governanceOverhead({
  interruptionTimeMs = null,
  activeWorkTimeMs = null,
  userTriageDecisions = null,
} = {}) {
  if (interruptionTimeMs === null || !activeWorkTimeMs) {
    return Object.freeze({
      ratio: null,
      note: 'Governance overhead is unmeasured. A tool that does not measure its own cost '
        + 'cannot claim to be worth it.',
      version: VERSION,
    });
  }
  const ratio = interruptionTimeMs / activeWorkTimeMs;
  return Object.freeze({
    ratio,
    interruption_time_ms: interruptionTimeMs,
    active_work_time_ms: activeWorkTimeMs,
    user_triage_decisions: userTriageDecisions,
    /** 使用者被迫分診 warning 的次數,本身就是 Human-as-QA 的證據。 */
    self_hcd_signal: userTriageDecisions !== null && userTriageDecisions > 0,
    note: (userTriageDecisions ?? 0) > 0
      ? 'The user is triaging Forseti\'s own warnings. That is Human-as-QA with Forseti in '
        + 'the role of the failing agent (FS-ALR-005).'
      : null,
    version: VERSION,
  });
}

/**
 * FS-ALR-004:UI 必須優先回答的四個問題。
 *
 * 這個函式把它們做成一個結構,而不是留給介面層自己決定要顯示什麼。
 * 理由是那四個問題的順序本身就是規格 —— 先問「有幾件事」,
 * 再問「哪一件最可能讓工作失敗」,是為了防止介面按時間倒序排一長串。
 */
export function incidentSummary(aggregated, { needsDecision = [] } = {}) {
  const incidents = aggregated?.root_incidents ?? [];
  const rank = { C: 0, B: 1, A: 2 };
  const worst = incidents.length
    ? incidents.reduce((a, b) => (rank[b.severity_family] < rank[a.severity_family] ? b : a))
    : null;

  return Object.freeze({
    /** 一,現在真正有幾個 root incidents? */
    root_incident_count: incidents.length,
    /** 二,哪一個最可能讓工作失敗? */
    most_likely_to_break_work: worst
      ? Object.freeze({
        root_incident_key: worst.root_incident_key,
        severity_family: worst.severity_family,
        primitives: worst.primitives,
      })
      : null,
    /** 三,哪一個現在需要人做決定? */
    needs_human_decision: Object.freeze([...needsDecision]),
    /** 四,其他 warning 是不是同一個根因的症狀? */
    symptoms_of_same_root: Object.freeze(incidents.map((i) => Object.freeze({
      root_incident_key: i.root_incident_key,
      detector_hits_collapsed: i.detector_hit_count,
    }))),
    detector_hits_total: aggregated?.detector_hits ?? 0,
    version: VERSION,
  });
}
