"""
OCCTO 広域予備率モニター
────────────────────────────────────────────────────────────────
データ取得の仕組み:
  GitHub Actions (毎時自動実行)
    → OCCTO CSV を取得
    → data/*.json に変換・保存
    → main ブランチに push

  Streamlit Cloud (このアプリ)
    → raw.githubusercontent.com から JSON を直接ダウンロード
    → グラフ表示
────────────────────────────────────────────────────────────────
初回セットアップ:
  GitHubリポジトリ → Actions → 「OCCTO データ自動取得」→ Run workflow
────────────────────────────────────────────────────────────────
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import json
from datetime import date, timedelta, datetime
from pathlib import Path

# ──────────────────────────────────────────────────────────────
# 設定: GitHubユーザー名・リポジトリ名をここに記入してください
# ──────────────────────────────────────────────────────────────
GITHUB_USER = st.secrets.get("GITHUB_USER", "YOUR_GITHUB_USERNAME")
GITHUB_REPO = st.secrets.get("GITHUB_REPO", "occto-reserve-monitor")
GITHUB_BRANCH = "main"

RAW_BASE = (
    f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}"
    f"/{GITHUB_BRANCH}/data"
)
# ──────────────────────────────────────────────────────────────

AREAS = ["北海道","東北","東京","中部","北陸","関西","中国","四国","九州","沖縄"]

ALERT_LINES = {
    "3%（需給逼迫注意）": (3.0, "#ff4444"),
    "5%（安定供給下限）": (5.0, "#ffaa00"),
    "8%（適正水準）":     (8.0, "#66cc88"),
}

# ローカル実行時はファイルも参照
LOCAL_DATA = Path(__file__).parent / "data"

# ──────────────────────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────────────────────
def _period_to_label(p: int) -> str:
    h = (p - 1) * 30 // 60
    m = (p - 1) * 30 % 60
    return f"{h:02d}:{m:02d}"


def _time_to_period(t: str) -> int | None:
    try:
        h, m = map(int, t.strip().split(":"))
        if h == 24: return 48
        return h * 2 + (1 if m == 30 else 0) if m in (0, 30) else None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────
# OCCTO CSV 直接取得（ローカルPC実行時のフォールバック）
# ──────────────────────────────────────────────────────────────
def _fetch_occto_direct(start_str: str, end_str: str) -> list[dict] | None:
    url = (
        "https://web-kohyo.occto.or.jp/kks-web-public/download/downloadCsv"
        f"?jhSybt=02&tgtYmdFrom={start_str}&tgtYmdTo={end_str}"
    )
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; ICS-Tool/1.0)",
            "Accept": "text/csv,*/*",
            "Referer": "https://web-kohyo.occto.or.jp/kks-web-public/download",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("cp932", errors="replace")
    except Exception:
        return None

    rows = []
    for line in raw.splitlines():
        line = line.strip().strip('"')
        if not line or "対象年月日" in line:
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 9:
            continue
        try:
            area = parts[3]
            if area not in AREAS:
                continue
            period = _time_to_period(parts[1])
            if period is None:
                continue
            def f(v):
                try: return float(v)
                except: return None
            rows.append({
                "date": parts[0], "time": parts[1], "period": period,
                "area": area,
                "b_demand": f(parts[4]), "b_supply": f(parts[5]),
                "b_reserve": f(parts[6]),
                "rate": f(parts[7]), "usage": f(parts[8]),
                "a_demand":  f(parts[9])  if len(parts) > 9  else None,
                "a_supply":  f(parts[10]) if len(parts) > 10 else None,
                "a_reserve": f(parts[11]) if len(parts) > 11 else None,
            })
        except Exception:
            continue
    return rows if rows else None


# ──────────────────────────────────────────────────────────────
# データ取得（GitHub raw → ローカルファイル → OCCTO直接 の順に試みる）
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def _fetch_json_from_github(url: str) -> list[dict] | None:
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def load_all_data(github_user: str, github_repo: str) -> tuple[pd.DataFrame | None, str]:
    """
    データを取得して DataFrame に変換する。
    返り値: (df, source_label)
    """
    today       = date.today()
    month_start = today.replace(day=1)
    prev_end    = month_start - timedelta(days=1)
    prev_start  = prev_end.replace(day=1)

    month_keys = [
        prev_start.strftime("%Y%m"),
        today.strftime("%Y%m"),
    ]

    # ── 1) GitHub raw から JSON を取得 ──────────────────────────
    if github_user and github_user != "YOUR_GITHUB_USERNAME":
        raw_base = (
            f"https://raw.githubusercontent.com/{github_user}/{github_repo}"
            f"/{GITHUB_BRANCH}/data"
        )
        all_rows = []
        for ym in month_keys:
            url = f"{raw_base}/block_{ym}.json"
            rows = _fetch_json_from_github(url)
            if rows:
                all_rows.extend(rows)
        if all_rows:
            return _to_df(all_rows), "📡 GitHub（自動更新）"

    # ── 2) ローカルファイル（data/*.json）を参照 ──────────────────
    if LOCAL_DATA.exists():
        all_rows = []
        for ym in month_keys:
            p = LOCAL_DATA / f"block_{ym}.json"
            if p.exists():
                try:
                    all_rows.extend(json.loads(p.read_text(encoding="utf-8")))
                except Exception:
                    pass
        if all_rows:
            return _to_df(all_rows), "📁 ローカルキャッシュ"

    # ── 3) OCCTO から直接取得（ローカルPC実行時のみ有効）──────────
    all_rows = []
    for d_from, d_to in [(prev_start, prev_end), (month_start, today)]:
        rows = _fetch_occto_direct(
            d_from.strftime("%Y/%m/%d"),
            d_to.strftime("%Y/%m/%d"),
        )
        if rows:
            all_rows.extend(rows)
    if all_rows:
        return _to_df(all_rows), "🌐 OCCTO 直接取得"

    return None, ""


def _to_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["date_obj"] = pd.to_datetime(df["date"], format="%Y/%m/%d", errors="coerce").dt.date
    df = df.dropna(subset=["date_obj", "period", "area"])
    df["period"] = df["period"].astype(int)
    df = df.drop_duplicates(["date_obj", "period", "area"]).reset_index(drop=True)
    return df


def get_meta(github_user: str, github_repo: str) -> dict:
    if github_user and github_user != "YOUR_GITHUB_USERNAME":
        raw_base = (
            f"https://raw.githubusercontent.com/{github_user}/{github_repo}"
            f"/{GITHUB_BRANCH}/data"
        )
        try:
            resp = requests.get(f"{raw_base}/meta.json", timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
    # ローカル
    p = LOCAL_DATA / "meta.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ──────────────────────────────────────────────────────────────
# グラフ共通ヘルパー
# ──────────────────────────────────────────────────────────────
def rate_color(v: float) -> str:
    if v < 3:  return "#ff4444"
    if v < 5:  return "#ffaa00"
    if v < 8:  return "#ffdd55"
    return "#44cc88"


def add_alert_lines(fig, show_alerts: dict):
    for label, (val, color) in ALERT_LINES.items():
        if show_alerts.get(label, True):
            fig.add_hline(
                y=val, line_dash="dash", line_color=color, line_width=1.5,
                annotation_text=label, annotation_position="top right",
                annotation_font_color=color,
            )


PERIOD_TICKS     = list(range(1, 49, 4))
PERIOD_TICK_LBLS = [_period_to_label(p) for p in PERIOD_TICKS]


# ──────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="OCCTO 広域予備率モニター",
        page_icon="⚡", layout="wide",
    )

    st.markdown("""
    <style>
      [data-testid="stAppViewContainer"] { background:#0d1117; }
      .kpi { background:linear-gradient(135deg,#112240,#0d1b2a);
             border-radius:12px; padding:16px 20px;
             border-left:4px solid #00aaff; margin-bottom:8px; }
      .kpi-title { color:#7eaed0; font-size:.78rem; margin-bottom:4px; }
      .kpi-val   { font-size:1.6rem; font-weight:700; }
      .kpi-sub   { color:#7eaed0; font-size:.72rem; }
      .hdr { background:linear-gradient(90deg,#003366,#005599);
             padding:18px 28px; border-radius:10px; margin-bottom:20px; }
      .hdr h1 { color:#fff; margin:0; font-size:1.7rem; }
      .hdr p  { color:#aad4ff; margin:4px 0 0; font-size:.88rem; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="hdr">
      <h1>⚡ OCCTO 広域予備率モニター</h1>
      <p>電力広域的運営推進機関（OCCTO）の広域予備率を可視化します</p>
    </div>
    """, unsafe_allow_html=True)

    # ── GitHub設定チェック ──────────────────────────────────────
    github_user = GITHUB_USER
    github_repo = GITHUB_REPO

    if github_user == "YOUR_GITHUB_USERNAME":
        st.warning(
            "### ⚙️ 初期設定が必要です\n\n"
            "Streamlit Cloud の **Settings → Secrets** に以下を追加してください：\n\n"
            "```toml\n"
            'GITHUB_USER = "あなたのGitHubユーザー名"\n'
            'GITHUB_REPO = "occto-reserve-monitor"\n'
            "```\n\n"
            "または `app.py` の先頭 `GITHUB_USER` / `GITHUB_REPO` を直接書き換えてください。"
        )

    # ── データ取得 ──────────────────────────────────────────────
    with st.spinner("データを読み込み中..."):
        df_all, source_label = load_all_data(github_user, github_repo)
        meta = get_meta(github_user, github_repo)

    if df_all is None or df_all.empty:
        st.error(
            "### ⚠️ データがまだありません\n\n"
            "**手順:**\n"
            "1. GitHubリポジトリの **Actions** タブを開く\n"
            "2. 「OCCTO データ自動取得」をクリック\n"
            "3. **「Run workflow」** ボタンで手動実行\n"
            "4. 緑チェックがついたらこのページをリロード"
        )
        return

    # ── サイドバー ──────────────────────────────────────────────
    with st.sidebar:
        st.header("🔧 表示設定")

        dmin = df_all["date_obj"].min()
        dmax = df_all["date_obj"].max()
        upd  = meta.get("updated_at_jst", "不明")
        st.success(f"{source_label}\n\n{dmin} ～ {dmax}\n\n更新: {upd}")

        selected_areas = st.multiselect(
            "エリア選択（複数可）", AREAS, default=["東京","関西"],
        )

        st.divider()
        st.subheader("📅 対象日・ピリオド")

        available_dates = sorted(df_all["date_obj"].unique(), reverse=True)
        target_date = st.selectbox(
            "対象日",
            available_dates,
            format_func=lambda d: d.strftime("%Y/%m/%d (%a)"),
        )

        period_opts = list(range(1, 49))
        sel_period  = st.selectbox(
            "ピリオド（コマ番号）",
            period_opts,
            format_func=lambda p: f"コマ{p}（{_period_to_label(p)}〜）",
            index=17,
        )

        st.divider()
        st.subheader("📊 履歴範囲")
        history_days = st.slider("遡る日数", 3, 31, 14)

        st.divider()
        st.subheader("⚠️ 警戒ライン")
        show_alerts = {k: st.checkbox(k, value=True) for k in ALERT_LINES}

    if not selected_areas:
        st.warning("エリアを1つ以上選択してください。")
        return

    # ── タブ ────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(
        ["📡 当日リアルタイム", "📈 ピリオド別履歴推移", "📋 データテーブル"]
    )

    # ══════════════════════════════════════════════════════════
    # TAB 1: 当日リアルタイム
    # ══════════════════════════════════════════════════════════
    with tab1:
        st.subheader(f"📡 {target_date.strftime('%Y年%m月%d日')} — 全コマの広域予備率")

        df_day = df_all[
            (df_all["date_obj"] == target_date) &
            (df_all["area"].isin(selected_areas))
        ].copy()

        if df_day.empty:
            st.warning("この日のデータがありません。Actions を実行してください。")
        else:
            # KPI カード
            cols = st.columns(len(selected_areas))
            for i, area in enumerate(selected_areas):
                adf  = df_day[df_day["area"] == area].sort_values("period")
                if adf.empty: continue
                last = adf.iloc[-1]
                val  = float(last.get("rate") or float("nan"))
                clr  = rate_color(val)
                with cols[i]:
                    st.markdown(f"""
                    <div class="kpi" style="border-left-color:{clr}">
                      <div class="kpi-title">広域予備率 — {area}</div>
                      <div class="kpi-val" style="color:{clr}">{val:.2f}%</div>
                      <div class="kpi-sub">コマ{int(last['period'])}（{last['time']}）</div>
                    </div>""", unsafe_allow_html=True)

            # 予備率グラフ
            fig = go.Figure()
            for area in selected_areas:
                adf = df_day[df_day["area"] == area].sort_values("period")
                fig.add_trace(go.Scatter(
                    x=adf["period"], y=adf["rate"],
                    mode="lines+markers", name=area,
                    line=dict(width=2), marker=dict(size=5),
                    customdata=adf["time"],
                    hovertemplate=(
                        f"{area}<br>コマ%{{x}}（%{{customdata}}）<br>"
                        "予備率: %{y:.2f}%<extra></extra>"
                    ),
                ))
            add_alert_lines(fig, show_alerts)
            fig.update_layout(
                title=f"広域予備率（{target_date.strftime('%Y/%m/%d')}）",
                xaxis=dict(title="時刻", tickvals=PERIOD_TICKS, ticktext=PERIOD_TICK_LBLS),
                yaxis_title="広域予備率 (%)",
                template="plotly_dark", height=450,
                legend=dict(orientation="h", y=-0.2),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

            # 需要・供給力グラフ
            with st.expander("📊 需要・供給力の推移も表示"):
                fig2 = go.Figure()
                for area in selected_areas:
                    adf = df_day[df_day["area"] == area].sort_values("period")
                    for col_key, col_name, dash in [
                        ("b_demand", "広域需要(MW)",  "solid"),
                        ("b_supply", "広域供給力(MW)", "dash"),
                    ]:
                        if col_key in adf.columns:
                            fig2.add_trace(go.Scatter(
                                x=adf["period"], y=adf[col_key],
                                mode="lines", name=f"{area} {col_name}",
                                line=dict(width=1.5, dash=dash),
                            ))
                fig2.update_layout(
                    xaxis=dict(tickvals=PERIOD_TICKS, ticktext=PERIOD_TICK_LBLS),
                    yaxis_title="MW", template="plotly_dark", height=320,
                    legend=dict(orientation="h", y=-0.3),
                )
                st.plotly_chart(fig2, use_container_width=True)

    # ══════════════════════════════════════════════════════════
    # TAB 2: ピリオド別履歴推移
    # ══════════════════════════════════════════════════════════
    with tab2:
        st.subheader(
            f"📈 コマ{sel_period}（{_period_to_label(sel_period)}〜）の"
            f"広域予備率推移（過去 {history_days} 日）"
        )

        end_dt   = target_date
        start_dt = target_date - timedelta(days=history_days - 1)

        hist_df = df_all[
            (df_all["date_obj"] >= start_dt) &
            (df_all["date_obj"] <= end_dt) &
            (df_all["area"].isin(selected_areas)) &
            (df_all["period"] == sel_period)
        ].copy().sort_values("date_obj")

        if hist_df.empty:
            st.warning(
                f"指定期間（{start_dt}〜{end_dt}）の"
                f"コマ{sel_period}データがありません。"
            )
        else:
            fig3 = go.Figure()
            for area in selected_areas:
                adf = hist_df[hist_df["area"] == area]
                if adf.empty: continue
                fig3.add_trace(go.Scatter(
                    x=adf["date_obj"], y=adf["rate"],
                    mode="lines+markers+text", name=area,
                    text=adf["rate"].round(1).astype(str) + "%",
                    textposition="top center", textfont=dict(size=9),
                    marker=dict(size=8), line=dict(width=2.5),
                    hovertemplate=(
                        f"{area}<br>%{{x}}<br>予備率: %{{y:.2f}}%<extra></extra>"
                    ),
                ))
            add_alert_lines(fig3, show_alerts)
            fig3.update_layout(
                title=f"広域予備率 履歴推移（コマ{sel_period} = {_period_to_label(sel_period)}〜）",
                xaxis_title="日付", yaxis_title="広域予備率 (%)",
                template="plotly_dark", height=480,
                legend=dict(orientation="h", y=-0.2),
                hovermode="x unified",
            )
            st.plotly_chart(fig3, use_container_width=True)

            # 統計
            st.subheader("📊 統計サマリー")
            rows = []
            for area in selected_areas:
                vals = hist_df[hist_df["area"] == area]["rate"].dropna()
                if vals.empty: continue
                rows.append({
                    "エリア":       area,
                    "平均 (%)":     round(vals.mean(), 2),
                    "最小 (%)":     round(vals.min(),  2),
                    "最大 (%)":     round(vals.max(),  2),
                    "標準偏差":     round(vals.std(),  2),
                    "3%未満の日数": int((vals < 3).sum()),
                    "5%未満の日数": int((vals < 5).sum()),
                })
            if rows:
                st.dataframe(
                    pd.DataFrame(rows).set_index("エリア"),
                    use_container_width=True,
                )

    # ══════════════════════════════════════════════════════════
    # TAB 3: データテーブル
    # ══════════════════════════════════════════════════════════
    with tab3:
        st.subheader("📋 生データテーブル")

        df_tbl = df_all[
            (df_all["date_obj"] == target_date) &
            (df_all["area"].isin(selected_areas))
        ].copy()

        if df_tbl.empty:
            st.info("この日のデータがありません。")
        else:
            rename = {
                "date":"対象年月日", "time":"時刻", "period":"コマ番号",
                "area":"エリア名",
                "rate":"広域予備率(%)", "usage":"広域使用率(%)",
                "b_demand":"広域需要(MW)", "b_supply":"広域供給力(MW)",
                "b_reserve":"広域予備力(MW)",
                "a_demand":"エリア需要(MW)", "a_supply":"エリア供給力(MW)",
                "a_reserve":"エリア予備力(MW)",
            }
            show_df = (df_tbl[[c for c in rename if c in df_tbl.columns]]
                       .rename(columns=rename)
                       .sort_values(["エリア名","コマ番号"]))

            def _clr(val):
                try:
                    v = float(val)
                    if v < 3: return "background-color:#7f0000;color:white"
                    if v < 5: return "background-color:#7f4000;color:white"
                    if v < 8: return "background-color:#7f6000;color:white"
                    return ""
                except Exception: return ""

            if "広域予備率(%)" in show_df.columns:
                styled = show_df.style.map(_clr, subset=["広域予備率(%)"])
                st.dataframe(styled, use_container_width=True, height=500)
            else:
                st.dataframe(show_df, use_container_width=True, height=500)

            csv_b = show_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "⬇️ CSVダウンロード", data=csv_b,
                file_name=f"occto_{target_date.strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )

    # フッター
    st.divider()
    st.caption(
        "データソース: [OCCTO 広域予備率Web公表システム]"
        "(https://web-kohyo.occto.or.jp/kks-web-public/)　"
        f"最終更新: {meta.get('updated_at_jst','不明')}"
    )


if __name__ == "__main__":
    main()
