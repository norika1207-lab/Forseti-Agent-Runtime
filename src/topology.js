/**
 * Forseti v2.0 — P8:X-Ray Topology
 *
 * 規格來源:`docs/spec-v2.0.md` §11。
 * Exit gate(§26 P8):Mercury framework-substitution path 要能重建。
 *
 * ── 為什麼要圖,而不是一串警告 ──────────────────────────
 *
 * §11 的來源是 owner 對 Nexus 的描述:價值在於把 agent 執行過程中的
 * 節點、路徑與任務交集畫出來。Forseti 借這個概念,但把節點擴張到
 * Goal、Decision、Claim、Evidence、Correction 與 Unknown。
 *
 * FS-TOP-002 講的是這張圖唯一非做不可的能力:
 * 要能顯示「所有 artifact 都做了,但 action path 與 Goal 的交集逐步下降」。
 *
 * 那正是 CASE-D。一串警告顯示不出那件事,因為每一則警告單看都不成立 ——
 * 每一步都有產出、每一步都可辯護。只有把路徑攤開,才看得見它一直在
 * 遠離起點。
 *
 * ── FS-TOP-001 是這個模組的紀律 ─────────────────────────
 *
 * 看不到 sub-agent 的 prompt 時,必須標 UNKNOWN_EDGE,禁止模型補一段
 * 「大概的 prompt」。一張補過的圖比沒有圖更危險,因為它看起來完整。
 *
 * 零依賴。
 */

export const VERSION = 'topology@2.0';

/** §11.1 的節點型別。 */
export const NODE_TYPES = Object.freeze([
  'GOAL', 'NORTH_STAR', 'TASK', 'REQUIREMENT', 'CONSTRAINT', 'DECISION',
  'AGENT', 'SUB_AGENT', 'TOOL', 'RUNNING_TASK', 'PROCESS',
  'PLAN', 'PLAN_STEP', 'CLAIM', 'EVIDENCE_RECEIPT', 'CORRECTION',
  'ARTIFACT', 'FILE', 'COMMIT', 'DIAGNOSTIC_WINDOW', 'INCIDENT',
]);

/** §11.2 的邊型別。UNKNOWN_EDGE 是一等公民,不是錯誤狀態。 */
export const EDGE_TYPES = Object.freeze([
  'DEPENDS_ON', 'SUPPORTS', 'REFUTES', 'SUPERSEDES', 'CLAIMS',
  'VERIFIES', 'SPAWNS', 'DELEGATES_TO', 'IMPLEMENTS', 'UNKNOWN_EDGE',
]);

export function createGraph() {
  const nodes = new Map();
  const edges = [];

  return Object.freeze({
    addNode({ id, type, label = null, ...rest }) {
      if (!NODE_TYPES.includes(type)) {
        throw new TypeError(`Unknown node type: ${type}. See NODE_TYPES.`);
      }
      const n = Object.freeze({ id, type, label, ...rest });
      nodes.set(id, n);
      return n;
    },

    /**
     * 加一條邊。
     *
     * FS-TOP-001:關係存在但看不到內容時,型別必須是 UNKNOWN_EDGE,
     * 而且要說出為什麼看不到。這裡強制要求 `unobservable_reason`,
     * 因為一條沒有理由的 UNKNOWN_EDGE 過幾天就會被當成漏填。
     */
    addEdge({ from, to, type, unobservableReason = null, ...rest }) {
      if (!EDGE_TYPES.includes(type)) {
        throw new TypeError(`Unknown edge type: ${type}. See EDGE_TYPES.`);
      }
      if (type === 'UNKNOWN_EDGE' && !unobservableReason) {
        throw new TypeError(
          'An UNKNOWN_EDGE must say why it is unknown. Without a reason it reads as an '
          + 'omission, and the next reader will be tempted to fill it in (FS-TOP-001).',
        );
      }
      const e = Object.freeze({
        from, to, type, unobservable_reason: unobservableReason, ...rest,
      });
      edges.push(e);
      return e;
    },

    nodes: () => Object.freeze([...nodes.values()]),
    edges: () => Object.freeze([...edges]),

    /** 某個節點往外的邊。 */
    from(id) {
      return Object.freeze(edges.filter((e) => e.from === id));
    },

    /**
     * FS-TOP-002:action path 與 Goal 的交集隨時間怎麼變。
     *
     * 對每個時間窗算「有多少 action 有一條路連到 Goal」。
     * 這個比例下降,就是 CASE-D 那個形狀 —— 東西都做了,只是不再
     * 通往原本要去的地方。
     */
    goalIntersection(goalId, { windows = [] } = {}) {
      const reachable = reachableTo(edges, goalId);
      const series = windows.map((w) => {
        const actions = w.actionNodeIds ?? [];
        if (!actions.length) return null;
        const connected = actions.filter((a) => reachable.has(a));
        return connected.length / actions.length;
      });

      const measured = series.filter((s) => s !== null);
      return Object.freeze({
        series: Object.freeze(series),
        trend: measured.length >= 2
          ? (measured[measured.length - 1] - measured[0]) / (measured.length - 1)
          : null,
        /** FS-TOP-002 要的那句話:全部做完了,但交集在掉。 */
        declining: measured.length >= 2 && measured[measured.length - 1] < measured[0],
        windows_measured: measured.length,
        note: measured.length < 2
          ? 'Fewer than two measurable windows; a direction needs two points.'
          : null,
        version: VERSION,
      });
    },

    /** 有幾條邊是看不到內容的。這個比例本身就是一個健康訊號。 */
    observability() {
      const unknown = edges.filter((e) => e.type === 'UNKNOWN_EDGE');
      return Object.freeze({
        total_edges: edges.length,
        unknown_edges: unknown.length,
        ratio: edges.length ? unknown.length / edges.length : null,
        reasons: Object.freeze([...new Set(unknown.map((e) => e.unobservable_reason))]),
        /** 高比例不是失敗,是「這張圖有多少是猜不到的」的誠實刻度。 */
        note: edges.length && unknown.length / edges.length > 0.3
          ? 'A large share of this graph is unobservable. Conclusions drawn from it are '
            + 'correspondingly weaker, and MUST be labelled so.'
          : null,
        version: VERSION,
      });
    },
  });
}

/** 反向可達:哪些節點可以沿著邊走到 target。 */
function reachableTo(edges, target) {
  const incoming = new Map();
  for (const e of edges) {
    if (e.type === 'UNKNOWN_EDGE') continue;      // 看不到的邊不能拿來證明連通
    if (!incoming.has(e.to)) incoming.set(e.to, []);
    incoming.get(e.to).push(e.from);
  }
  const seen = new Set([target]);
  const stack = [target];
  while (stack.length) {
    const cur = stack.pop();
    for (const prev of (incoming.get(cur) ?? [])) {
      if (seen.has(prev)) continue;
      seen.add(prev);
      stack.push(prev);
    }
  }
  seen.delete(target);
  return seen;
}

/**
 * §26 P8 的 exit gate:重建一條 framework substitution 的路徑。
 *
 * CASE-D 的形狀:acceleration → observation grid → more models →
 * atlas/viz/paper。每一步都從前一步長出來,每一步都做完了,
 * 而最後那些節點沒有一條邊回到原本的 Goal。
 */
export function reconstructSubstitutionPath(graph, { goalId, terminalNodeId } = {}) {
  const edges = graph.edges();
  const chain = [];
  let cur = terminalNodeId;
  const guard = new Set();

  while (cur && !guard.has(cur)) {
    guard.add(cur);
    chain.unshift(cur);
    const parent = edges.find((e) => e.to === cur
      && ['DEPENDS_ON', 'SUPERSEDES', 'IMPLEMENTS'].includes(e.type));
    cur = parent?.from ?? null;
  }

  const reachable = reachableTo(edges, goalId);
  const connectedToGoal = chain.filter((n) => reachable.has(n));

  return Object.freeze({
    path: Object.freeze(chain),
    /** 這條鏈上有幾個節點還連得回 Goal。CASE-D 的末端是 0。 */
    still_connected_to_goal: Object.freeze(connectedToGoal),
    disconnected_tail: Object.freeze(chain.filter((n) => !reachable.has(n))),
    /**
     * FS-DET-FSD-001 的圖版本:每個節點都可能執行成功,而整條鏈
     * 已經離開 Goal。執行成功與否不在這個判定裡。
     */
    substitution_detected: chain.length >= 3 && connectedToGoal.length === 0,
    note: chain.length >= 3 && connectedToGoal.length === 0
      ? 'Every node on this chain derives from the previous one, and none of them has a '
        + 'path back to the goal. Each step was defensible; the chain is not.'
      : null,
    version: VERSION,
  });
}
