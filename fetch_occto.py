"""
GitHub Actions から実行される OCCTO データ取得スクリプト。
取得したCSVを data/ ディレクトリに保存する。
参考コードの _fetch_occto_csv / _parse_occto_csv ロジックをそのまま流用。
"""
import urllib.request
import urllib.error
import os
import sys
from datetime import date, timedelta, datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

OCCTO_URL = (
    "https://web-kohyo.occto.or.jp/kks-web-public/download/downloadCsv"
    "?jhSybt=02&tgtYmdFrom={start}&tgtYmdTo={end}"
)

AREAS = ["北海道","東北","東京","中部","北陸","関西","中国","四国","九州","沖縄"]

MAX_RETRY      = 5
RETRY_INTERVAL = 30


def fetch_raw(start_str: str, end_str: str) -> str | None:
    """参考コードの _fetch_occto_csv と同一ロジック"""
    url = OCCTO_URL.format(start=start_str, end=end_str)
    print(f"  [GET] {url}")
    import time
    for attempt in range(1, MAX_RETRY + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; ICS-Tool/1.0)",
                    "Accept":     "text/csv,*/*",
                    "Referer":    "https://web-kohyo.occto.or.jp/kks-web-public/download",
                }
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("cp932", errors="replace")
                return raw
        except urllib.error.HTTPError as e:
            if e.code == 204:
                print(f"  [SKIP] 204: データなし")
                return None
            elif e.code == 503:
                print(f"  [WAIT] 503: {RETRY_INTERVAL}秒後リトライ ({attempt}/{MAX_RETRY})")
                if attempt < MAX_RETRY:
                    time.sleep(RETRY_INTERVAL)
                else:
                    return None
            else:
                print(f"  [ERR] HTTP {e.code}: {e.reason}")
                return None
        except Exception as ex:
            print(f"  [ERR] {ex}")
            return None
    return None


def validate_csv(csv_text: str) -> bool:
    """CSVに実データが含まれているか確認"""
    for line in csv_text.splitlines():
        line = line.strip().strip('"')
        if not line or "対象年月日" in line:
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 8:
            return True
    return False


def main():
    today = date.today()

    # 当月 + 前月
    month_start = today.replace(day=1)
    prev_end    = month_start - timedelta(days=1)
    prev_start  = prev_end.replace(day=1)

    targets = [
        (prev_start, prev_end,   f"block_{prev_start.strftime('%Y%m')}.csv"),
        (month_start, today,     f"block_{today.strftime('%Y%m')}.csv"),
    ]

    errors = []
    for d_from, d_to, fname in targets:
        print(f"\n取得中: {d_from} ～ {d_to} → {fname}")
        raw = fetch_raw(
            d_from.strftime("%Y/%m/%d"),
            d_to.strftime("%Y/%m/%d"),
        )
        if raw and validate_csv(raw):
            path = DATA_DIR / fname
            path.write_text(raw, encoding="utf-8")
            size = len(raw.encode("utf-8"))
            print(f"  ✅ 保存: {path} ({size:,} bytes)")
        else:
            print(f"  ❌ 取得失敗または空データ: {fname}")
            errors.append(fname)

    # 最終更新時刻を記録
    meta = DATA_DIR / "last_updated.txt"
    meta.write_text(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        encoding="utf-8"
    )

    if errors:
        print(f"\n⚠️ {len(errors)}件失敗: {errors}")
        sys.exit(1)
    else:
        print("\n✅ 全データ取得完了")


if __name__ == "__main__":
    main()
