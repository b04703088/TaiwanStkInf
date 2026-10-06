"""各指數定期審核的「資料截止日」規則，以及臺灣指數公司日程表沒有的審核（MSCI 客製指數、ICE FactSet、富時全球）。

規則出處（2026/10 查證）：
  臺灣指數公司各指數編製規則（taiwanindex.com.tw/indexes/IXxxxx 的編製規則 PDF）
    IX0170 精選高息(00919)：5 月審核截至 5 月第 10 個交易日；12 月審核截至 11 月最後交易日；權重審核截至 2、8 月最後交易日
    IX0230 TOP 50(009816)：2/5/8/11 月審核，截至前一個月最後交易日
    IX0139 科技龍頭通訊(00881)：4/10 月審核，截至 3/9 月最後交易日
    IX0172 優利高填息30(00918)：6/12 月審核，截至 6/12 月第 10 個交易日
    IX0179 科技優息(00929)：6/12 月第 7 個交易日；權重審核截至 2、8 月最後交易日
    IX0208 價值高息(00940)：5/11 月審核，截至前一個月最後交易日
    IX0181 半導體收益(00927)：5 月審核截至 5 月第 10 個交易日；12 月審核截至 11 月最後交易日
    IX0194 創新科技50(00935)：4/10 月審核，截至前一個月最後交易日
    IX0178 ESG低碳50(00923)：3/6/9/12 月第 7 個交易日
  元大投信 00713 產品頁：6/12 月審核，截至 5/11 月最後交易日
  FTSE TWSE Taiwan Index Series Ground Rules（臺灣50、中型100、資訊科技、發達）與臺灣高股息指數編製規則：
    生效日前四週的星期一（＝生效日 −28 天）
  FTSE4Good TIP Taiwan ESG（臺灣永續，00850）：審核月前一個月最後營業日
  臺灣證券交易所公司治理100指數編製規則（2023 版）：7 月第 3 個交易日（新版規則未確認）
  MSCI GIMI 方法論：價格截止日為公告月前一個月（1/4/7/10 月）最後 10 個營業日中的一天，不事先公布
  ICE/NYSE FactSet 臺灣ESG永續關鍵半導體(00891)：1/4/7/10 月第三個星期五前 3 個營業日為參考日，
    第三個星期五後 5 個營業日的下一個營業日開盤生效
  FTSE GEIS（富時全球）：2026 年 GEIS FAQ 的審核行事曆；2027 年依慣例推估
"""
from datetime import date, timedelta

# ETF → (規則, 說明)。規則 kind：
#   month：{審核月: "last"（該月最後交易日）或 n（該月第 n 個交易日）}，依公告日往前找最近的月份
#   eff_minus_days：生效日 − n 天
#   prev_month_of_eff：生效月前一個月最後交易日
#   msci：公告月前一個月最後 10 個營業日（區間）
#   ice：審核月第三個星期五前 3 個交易日
FTSE_TWSE = {"kind": "eff_minus_days", "n": 28, "note": "生效日前四週的星期一（富時臺灣指數系列規則）"}
RULES = {
    "00919": {"kind": "month", "months": {2: "last", 5: 10, 8: "last", 11: "last"},
              "note": "5 月審核：5 月第 10 個交易日；12 月審核：11 月最後交易日；3、9 月權重審核：2、8 月最後交易日"},
    "009816": {"kind": "month", "months": {1: "last", 4: "last", 7: "last", 10: "last"}, "note": "審核月前一個月最後交易日"},
    "00881": {"kind": "month", "months": {3: "last", 9: "last"}, "note": "3、9 月最後交易日"},
    "00918": {"kind": "month", "months": {6: 10, 12: 10}, "note": "6、12 月第 10 個交易日"},
    "00929": {"kind": "month", "months": {2: "last", 6: 7, 8: "last", 12: 7},
              "note": "6、12 月第 7 個交易日；3、9 月權重審核：2、8 月最後交易日"},
    "00940": {"kind": "month", "months": {4: "last", 10: "last"}, "note": "審核月前一個月最後交易日"},
    "00927": {"kind": "month", "months": {5: 10, 11: "last"}, "note": "5 月審核：5 月第 10 個交易日；12 月審核：11 月最後交易日"},
    "00935": {"kind": "month", "months": {3: "last", 9: "last"}, "note": "審核月前一個月最後交易日"},
    "00923": {"kind": "month", "months": {3: 7, 6: 7, 9: 7, 12: 7}, "note": "3、6、9、12 月第 7 個交易日"},
    "00713": {"kind": "month", "months": {5: "last", 11: "last"}, "note": "5、11 月最後交易日（元大投信）"},
    "00692": {"kind": "month", "months": {7: 3}, "note": "7 月第 3 個交易日（2023 版編製規則，新版未確認）"},
    "00850": {"kind": "prev_month_of_eff", "note": "審核月前一個月最後營業日（富時規則）"},
    "0057": {"kind": "msci", "note": "公告前一個月最後 10 個營業日中的一天，MSCI 不事先公布"},
    "006203": {"kind": "msci", "note": "公告前一個月最後 10 個營業日中的一天，MSCI 不事先公布"},
    "00878": {"kind": "msci", "note": "MSCI 半年度審核：公告前一個月最後 10 個營業日中的一天（推估）"},
    "00922": {"kind": "msci", "note": "MSCI 半年度審核：公告前一個月最後 10 個營業日中的一天（推估）"},
    "00891": {"kind": "ice", "note": "審核月第三個星期五前 3 個營業日"},
}
for c in ("0050", "006208", "00631L", "00632R", "0051", "0052", "0058", "0056"):
    RULES[c] = FTSE_TWSE
FTSE_TWSE_INDEXES = ("臺灣50指數", "臺灣中型100指數", "臺灣資訊科技指數", "臺灣發達指數", "臺灣高股息指數")

# 富時全球（FTSE GEIS）：[審核, 資料截止, 公告, 生效（開盤）, est]；台股在生效前一個交易日收盤換股
FTSE_GEIS = [
    ["2026-03", "2026-01-30", "2026-03-06", "2026-03-23", False],
    ["2026-06", "2026-04-30", "2026-06-05", "2026-06-22", False],
    ["2026-09", "2026-07-31", "2026-09-04", "2026-09-21", False],
    ["2026-12", "2026-10-30", "2026-12-04", "2026-12-21", False],
    ["2027-03", "2027-01-29", "2027-03-05", "2027-03-22", True],
    ["2027-06", "2027-04-30", "2027-06-04", "2027-06-21", True],
    ["2027-09", "2027-07-30", "2027-09-03", "2027-09-20", True],
]
GEIS_NAME = "富時全球指數（FTSE GEIS）季度審核"
GEIS_NOTE = "流通股數與自由流通量截止日；3、9 月半年度審核的市值另以前一年 12/31、6/30 為準"


class TradingCalendar:
    """交易日：有行情資料的期間用實際交易日，之後用平日扣休市（證交所未公布的年份至少扣元旦）"""

    def __init__(self, past, holidays):
        self.past = set(past)
        self.last = max(past) if past else ""
        self.first = min(past) if past else ""
        self.hol = holidays

    def is_td(self, d):
        s = d.isoformat()
        if self.first <= s <= self.last:
            return s in self.past
        return d.weekday() < 5 and s not in self.hol and s[5:] != "01-01"

    def month(self, y, m):
        d = date(y, m, 1)
        out = []
        while d.month == m:
            if self.is_td(d):
                out.append(d)
            d += timedelta(1)
        return out

    def shift(self, d, n):
        """往前（n<0）或往後數 n 個交易日"""
        step = 1 if n > 0 else -1
        while n:
            d += timedelta(step)
            if self.is_td(d):
                n -= step
        return d

    def prev_td(self, d):
        while not self.is_td(d):
            d -= timedelta(1)
        return d


def _third_friday(y, m):
    d = date(y, m, 1)
    d += timedelta((4 - d.weekday()) % 7)
    return d + timedelta(14)


def cutoff(rule, ann, eff, cal):
    """回傳 (起, 迄)；單一天時起＝迄；算不出來回傳 None"""
    a = date.fromisoformat(ann) if ann else None
    e = date.fromisoformat(eff) if eff else None
    k = rule["kind"]
    if k == "eff_minus_days" and e:
        d = cal.prev_td(e - timedelta(rule["n"]))
        return d, d
    if k == "prev_month_of_eff" and e:
        days = cal.month(*(e.year, e.month - 1) if e.month > 1 else (e.year - 1, 12))
        return (days[-1], days[-1]) if days else None
    if k == "msci" and a:
        y, m = (a.year, a.month - 1) if a.month > 1 else (a.year - 1, 12)
        days, d = [], date(y, m, 1)  # MSCI 營業日：平日（不看台股休市）
        while d.month == m:
            if d.weekday() < 5:
                days.append(d)
            d += timedelta(1)
        return (days[-10], days[-1]) if len(days) >= 10 else None
    if k == "ice" and e:
        f = _third_friday(e.year, e.month)
        if f >= e:  # 生效在第三個星期五之前 → 是上個月的審核
            y, m = (e.year, e.month - 1) if e.month > 1 else (e.year - 1, 12)
            f = _third_friday(y, m)
        d = cal.shift(f, -3)
        return d, d
    if k == "month" and a:
        # 公告日往前最近的規則月份（最多回推 3 個月）
        for back in range(0, 4):
            y, m = a.year, a.month - back
            while m < 1:
                y, m = y - 1, m + 12
            if m in rule["months"]:
                days = cal.month(y, m)
                spec = rule["months"][m]
                if not days:
                    return None
                d = days[-1] if spec == "last" else days[min(spec, len(days)) - 1]
                if d > a:
                    continue
                return d, d
    return None


def ice_reviews(cal, start, end):
    """00891：1/4/7/10 月，生效＝第三個星期五後 5 個交易日的下一個交易日（公告日不固定）"""
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        if m in (1, 4, 7, 10):
            f = _third_friday(y, m)
            eff = cal.shift(f, 6)
            if start <= eff <= end:
                out.append(eff)
        y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out
