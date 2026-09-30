"""ETF 持股抓取共用工具：HTTP（含 cookie）、數字/日期解析、代號正規化。"""
import http.cookiejar
import io
import ssl
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

TPE = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 同一次執行共用 cookie（統一、安聯、兆豐需要 session）
_cookies = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookies))
# 憑證鏈不完整的投信網站（伺服器沒送中繼憑證，瀏覽器會自動補、Python 不會）才用；只讀公開資料。
_insecure_opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(_cookies),
    urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))


class AdapterError(Exception):
    pass


def http(url, params=None, body=None, form=None, as_json=True, raw=False,
         headers=None, retries=3, max_bytes=None, insecure=False):
    """GET / POST。body=JSON、form=表單；raw=True 回 bytes；max_bytes 只讀前 N bytes。
    JSON 回應若本身是字串（中信、第一金的雙層編碼）會自動再 parse 一次。"""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    for attempt in range(retries):
        try:
            with (_insecure_opener if insecure else _opener).open(req, timeout=30) as resp:
                content = resp.read(max_bytes) if max_bytes else resp.read()
            if raw:
                return content
            text = content.decode("utf-8", errors="replace")
            if not as_json:
                return text
            d = json.loads(text)
            while isinstance(d, str) and d[:1] in "[{":
                d = json.loads(d)
            return d
        except Exception as e:  # noqa: BLE001
            if attempt == retries - 1:
                raise AdapterError(f"{url[:120]}: {e!r}") from e
            time.sleep(5 * (attempt + 1))


def num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def iso(s):
    """各種日期寫法 → 'YYYY-MM-DD'：20260924、2026/09/24、2026-09-24T00:00:00、
    1150924、115/09/24（民國）、/Date(1727107200000)/（.NET）。"""
    s = str(s).strip()
    m = re.search(r"/Date\((-?\d+)", s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000, TPE).strftime("%Y-%m-%d")
    m = re.match(r"^(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})", s)
    if m:
        y = int(m.group(1))
        return f"{y + 1911 if y < 1911 else y}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    s = re.sub(r"\D", "", s)
    if len(s) == 7:
        return f"{int(s[:3]) + 1911}-{s[3:5]}-{s[5:7]}"
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    raise AdapterError(f"無法解析日期：{s!r}")


def code_of(raw):
    """代號正規化：台股去掉 Bloomberg 式後綴（'2330 TT' → '2330'），海外保留（'NVDA US'）。"""
    c = re.sub(r"\s+", " ", str(raw or "")).strip().upper()
    c = re.sub(r"^(\d{4,6}[A-Z]?)(?:\s+(?:TT|TW)|\.TW|\.TWO)$", r"\1", c)
    return c


def is_security(code):
    """是股票代號（台股或海外），不是現金、期貨、小計等列。"""
    if not code or code in ("-", "--"):
        return False
    if re.match(r"^\d{4,6}[A-Z]?$", code):
        return True
    return bool(re.match(r"^[A-Z0-9.\-/]{1,12} [A-Z]{2}$", code))  # 海外：'NVDA US'、'005930 KS'


def holding(code, name, shares, weight):
    return {"code": code_of(code), "name": re.sub(r"\s+", " ", str(name or "")).strip(),
            "shares": None if shares is None else int(round(shares)),
            "weight": None if weight is None else round(float(weight), 4)}


def recent_days(n=10, start=None):
    """今天（台北）往前 n 天，週末略過。投信的 API 常要求「剛好是公告日」，要逐日往回試。"""
    d = start or datetime.now(TPE).date()
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out


def find_key(obj, key):
    """在巢狀 dict/list 裡找第一個叫 key 的值（各投信包裝層數不同）。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                r = find_key(v, key)
                if r is not None:
                    return r
    return None


def xlsx_rows(content, sheet=1):
    """不靠 openpyxl 讀 xlsx：回傳第 sheet 張工作表的列（字串 list）。"""
    z = zipfile.ZipFile(io.BytesIO(content))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = z.read("xl/sharedStrings.xml").decode("utf-8")
        for si in re.findall(r"<si>(.*?)</si>", ss, re.S):
            shared.append("".join(re.findall(r"<t[^>]*>(.*?)</t>", si, re.S)))
    xml = z.read(f"xl/worksheets/sheet{sheet}.xml").decode("utf-8")
    rows = []
    for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
        cells = {}
        for ref, attrs, inner in re.findall(r'<c r="([A-Z]+)\d+"([^>]*)>(.*?)</c>', row, re.S):
            v = re.search(r"<v>(.*?)</v>", inner, re.S)
            t = re.search(r"<t[^>]*>(.*?)</t>", inner, re.S)
            if 't="s"' in attrs and v:
                val = shared[int(v.group(1))]
            elif v:
                val = v.group(1)
            elif t:
                val = t.group(1)
            else:
                val = ""
            cells[ref] = unescape_xml(val)
        if cells:
            width = max(col_index(c) for c in cells) + 1
            rows.append([cells.get(col_name(i), "") for i in range(width)])
    return rows


def col_index(c):
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n - 1


def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def unescape_xml(s):
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
             .replace("&apos;", "'").replace("&amp;", "&"))


def isin_for(code):
    """台灣 ETF 的 ISIN：'TW000' + 代號 + 檢查碼（字母轉數字後跑 Luhn）。00404A → TW00000404A5。"""
    body = "TW000" + code
    digits = "".join(str(int(ch, 36)) for ch in body)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n // 10 + n % 10
    return body + str((10 - total % 10) % 10)
