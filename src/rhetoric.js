/**
 * Forseti：信心詞與假坦白
 *
 * 自白書七個形狀裡的第二與第三個。這兩個原本被歸進「需要語意判讀,永久不做」,
 * 那個歸類是錯的,而且錯得有名字:把一條真理由擴大成假限制。
 *
 * 真的理由是「不要做會很有自信又常常錯的語意判讀器」。
 * 但這兩個不需要判讀語意:
 *
 *   信心詞前置  是字串比對。列一張詞表數頻率,如此而已。
 *   假坦白      是時序比對。宣稱抓到自己一個錯,那個錯後來被推翻。
 *
 * 剩下兩個(語意偷換、地板當天花板)才真的需要判斷詞的範圍
 * 與什麼算基本義務,那兩個仍然不做。
 *
 * ── 這兩個偵測器都會誤判,而且必須說出來 ──────────────
 *
 * 信心詞那個尤其。一句「這條我可以負責任講」可能是真的負得起責任,
 * 也可能是拿語氣替沒有證據的內容加上強度。分不出來。
 * 所以它回的不是判決,是「這裡的語氣強度高於證據強度,值得看一眼」,
 * 而且永遠標成 experimental。
 *
 * 零依賴。
 */

export const VERSION = 'rhetoric@0.1';

/**
 * 信心詞。自白書原文列的:killer、坐實、最硬、負責任講。
 * 這裡擴到同類,但刻意不擴太廣 —— 詞表越長,誤判越多,
 * 而一個到處都在叫的偵測器會被關掉。
 *
 * 這張表是中英混的,因為被觀測的對話本來就是。
 */
export const CONFIDENCE_MARKERS = Object.freeze([
  'killer', '坐實', '最硬', '負責任講', '拍胸脯', '鐵證', '端到端驗證通過',
  '百分之百', '100%', '絕對沒問題', '一定是', '毫無疑問', '確定無誤',
  'definitely', 'certainly', 'guaranteed', 'without a doubt', 'rock solid',
]);

/**
 * 一段文字的語氣強度,相對於它帶的證據。
 *
 * 關鍵在「相對於」。信心詞本身不是問題,問題是信心詞多而證據少。
 * 所以這個函式需要兩個輸入:文字,以及那段話背後有幾筆可查的證據。
 * 只給文字的話,它會回 null 而不是猜。
 *
 * @param {string} text
 * @param {object} p
 * @param {number|null} p.evidenceCount 這段話背後有幾筆可查的證據(工具回傳、已驗證產物)
 */
export function confidenceLoad(text, { evidenceCount = null } = {}) {
  const s = String(text ?? '');
  const hits = [];
  for (const m of CONFIDENCE_MARKERS) {
    const re = new RegExp(m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
    const n = (s.match(re) ?? []).length;
    if (n) hits.push({ marker: m, count: n });
  }
  const total = hits.reduce((a, h) => a + h.count, 0);

  if (evidenceCount === null) {
    return Object.freeze({
      markers: Object.freeze(hits),
      marker_count: total,
      ratio: null,
      flagged: false,
      /** 沒有證據計數就算不出「相對於」,而絕對的信心詞數量沒有意義。 */
      note: 'No evidence count supplied. Confidence markers alone say nothing - '
        + 'a well-supported claim may legitimately be stated with confidence.',
      experimental: true,
      version: VERSION,
    });
  }

  const ratio = total / Math.max(evidenceCount, 1);
  return Object.freeze({
    markers: Object.freeze(hits),
    marker_count: total,
    /** 每一筆證據配上幾個信心詞。高不代表錯,代表語氣跑在證據前面。 */
    ratio,
    flagged: total > 0 && evidenceCount === 0,
    note: (total > 0 && evidenceCount === 0)
      ? 'Confidence markers used with zero retrievable evidence behind them. '
        + 'This is not proof of anything - it is a place worth looking.'
      : null,
    /** 這個偵測器會誤判,永遠標成實驗性。規格書第 16 節。 */
    experimental: true,
    version: VERSION,
  });
}

/**
 * 假坦白:宣稱抓到自己一個錯,而那個「錯」後來被推翻。
 *
 * 自白書的原案:在被要求自我檢查的那一刻,交出一個
 * 「我連自己的錯都抓得出來」的成果。它同時做了兩件壞事 ——
 * 誣賴了一份正確的資料,又用一次假的坦白替自己加分。
 *
 * 這個偵測器完全不讀文字。它只比對三個時間點:
 *   一,一筆自我糾錯的宣稱(宿主標記)
 *   二,那筆宣稱指控的對象
 *   三,後來對那個對象的裁決
 *
 * 如果裁決推翻了指控,那次自我糾錯本身就是錯的,
 * 而它已經在「證明我可信」那一刻換到了信任。
 *
 * @param {Array} corrections [{ id, at, accuses, verdict }]
 *   verdict: 'UPHELD' | 'OVERTURNED' | null(還沒裁決)
 */
export function falseConfessions(corrections) {
  const list = corrections ?? [];
  const overturned = list.filter((c) => c.verdict === 'OVERTURNED');
  const undecided = list.filter((c) => c.verdict == null);
  return Object.freeze({
    total: list.length,
    overturned: Object.freeze(overturned.map((c) => Object.freeze({
      id: c.id,
      at: c.at,
      accused: c.accuses ?? null,
      /**
       * 這一次自我糾錯拿到的信任是假的,而它指控的對象是對的。
       * 傷害是雙份:一份給被誣賴的資料,一份給後來相信這個系統的人。
       */
      note: 'This self-correction was itself wrong. It was made while proving trustworthiness, '
        + 'and it discredited something that was correct.',
    }))),
    undecided: undecided.length,
    /** 分母排除還沒裁決的。沒裁決不等於成立,也不等於不成立。 */
    rate: (list.length - undecided.length) > 0
      ? overturned.length / (list.length - undecided.length)
      : null,
    note: list.length === 0
      ? 'No self-corrections recorded. Not a clean record - no record.'
      : (undecided.length
        ? `${undecided.length} self-correction(s) have no verdict yet and are excluded from the rate.`
        : null),
    experimental: true,
    version: VERSION,
  });
}

/**
 * 仍然不做的兩個,以及為什麼。
 *
 * 這個常數存在的理由跟 provenance.js 的 OUT_OF_SCOPE 一樣:
 * 把缺項寫出來,不要讓「做了的加上不做的剛好等於全部」
 * 這種加總掩蓋掉沒被列進任何一邊的東西。
 */
export const STILL_OUT_OF_SCOPE = Object.freeze([
  Object.freeze({
    shape: 'SEMANTIC_SWAP',
    why: 'Requires comparing the scope of two words - "工作任務" swapped for "任何事" - '
      + 'which needs to know what each term covers in this conversation. No event-stream criterion exists.',
  }),
  Object.freeze({
    shape: 'FLOOR_AS_CEILING',
    why: 'Requires knowing which obligations are baseline rather than concessions. '
      + 'That is a judgment about the relationship, not a property of the transcript.',
  }),
]);
