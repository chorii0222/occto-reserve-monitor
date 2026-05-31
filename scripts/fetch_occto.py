"""
GitHub Actions から実行される OCCTO データ取得スクリプト。
OCCTO CSV を取得して JSON に変換し data/ に保存する。
Streamlit Cloud は raw.githubusercontent.com 経由でこのJSONを読む。
"""
import urllib.request
import urllib.error
import json
import sys
import time
from datetime import date, timedelta, datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

OCCTO_URL = (
    "https://web-kohyo.occto.or.jp/kks-web-public/download/downloadCsv"
    "?jhSybt=02&tgtYmdFrom={start}&tgtYmdTo={end}"
)
AREAS = ["北海道","東北","東京","中部","北陸","関西","中国","四国","九州","沖縄"]
MAX_RETRY = 3


def fetch_raw(start_str: str, end_str: str) -> str | None:
    url = OCCTO_URL.format(start=start_str, end=end_str)
    print(f"  [GET] {url}")
    for attempt in range(1, MAX_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; ICS-Tool/1.0)",
                "Accept":     "text/csv,*/*",
                "Referer":    "https://web-kohyo.occto.or.jp/kks-web-public/download",
            })
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("cp932", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < MAX_RETRY:
                print(f"  [WAIT] 503 → 30秒後リトライ ({attempt}/{MAX_RETRY})")
                time.sleep(30)
            else:
                print(f"  [ERR] HTTP {e.code}")
                return None
        except Exception as ex:
            print(f"  [ERR] {ex}")
            return None
    return None


def _time_to_period(t: str) -> int | None:
    try:
        h, m = map(int, t.strip().split(":"))
        if h == 24: return 48
        return h * 2 + (1 if m == 30 else 0) if m in (0, 30) else None
    except Exception:
        return None


def parse_csv(csv_text: str) -> list[dict]:
    rows = []
    for line in csv_text.splitlines():
        line = line.strip().strip('"')
        if not line or "対象年月日" in line:
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 9:
            continue
        try:
            date_str  = parts[0]
            time_str  = parts[1]
            area_name = parts[3]
            if area_name not in AREAS:
                continue
            period = _time_to_period(time_str)
            if period is None:
                continue
            def f(v):
                try: return float(v)
                except: return None
            rows.append({
                "date":    date_str,
                "time":    time_str,
                "period":  period,
                "area":    area_name,
                "b_demand":  f(parts[4]),
                "b_supply":  f(parts[5]),
                "b_reserve": f(parts[6]),
                "rate":      f(parts[7]),   # 広域予備率(%)
                "usage":     f(parts[8]),   # 広域使用率(%)
                "a_demand":  f(parts[9])  if len(parts) > 9  else None,
                "a_supply":  f(parts[10]) if len(parts) > 10 else None,
                "a_reserve": f(parts[11]) if len(parts) > 11 else None,
            })
        except (ValueError, IndexError):
            continue
    return rows


def main():
    today       = date.today()
    month_start = today.replace(day=1)
    prev_end    = month_start - timedelta(days=1)
    prev_start  = prev_end.replace(day=1)

    targets = [
        (prev_start, prev_end,  f"block_{prev_start.strftime('%Y%m')}.json"),
        (month_start, today,    f"block_{today.strftime('%Y%m')}.json"),
    ]

    errors = []
    for d_from, d_to, fname in targets:
        print(f"\n取得中: {d_from} ～ {d_to} → {fname}")
        raw = fetch_raw(d_from.strftime("%Y/%m/%d"), d_to.strftime("%Y/%m/%d"))
        if not raw:
            print(f"  ❌ 取得失敗")
            errors.append(fname)
            continue
        rows = parse_csv(raw)
        if not rows:
            print(f"  ❌ パース結果が空")
            errors.append(fname)
            continue
        path = DATA_DIR / fname
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"  ✅ {len(rows):,} 行 → {path}")

    # メタ情報
    meta = {
        "updated_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "updated_at_jst": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": [t[2] for t in targets],
    }
    (DATA_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nmeta.json 更新: {meta['updated_at_jst']}")

    if errors:
        print(f"\n⚠️ {len(errors)}件失敗: {errors}")
        sys.exit(1)
    print("\n✅ 完了")


if __name__ == "__main__":
    main()
