"""
OCCTO 広域予備率モニター
────────────────────────────────────────────────────────────
動作モード:
  A) ローカルPC実行時   → OCCTO API から直接 CSV を取得
  B) Streamlit Cloud   → GitHub Actions が保存した data/*.csv を参照
────────────────────────────────────────────────────────────
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import urllib.request
import urllib.error
import io
import os
from datetime import date, timedelta, datetime
from pathlib import Path

# ────────────────────────────────────────────────────────────
# 定数
# ────────────────────────────────────────────────────────────
DATA_DIR  = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

OCCTO_URL = (
    "https://web-kohyo.occto.or.jp/kks-web-public/download/downloadCsv"
    "?jhSybt=02&tgtYmdFrom={start}&tgtYmdTo={end}"
)

AREAS = ["北海道","東北","東京","中部","北陸","関西","中国","四国","九州","沖縄"]

ALERT_LINES = {
    "3%（需給逼迫注意）": (3.0, "#ff4444"),
    "5%（安定供給下限）": (5.0, "#ffaa00"),
    "8%（適正水準）":     (8.0, "#66cc88"),
}


# ────────────────────────────────────────────────────────────
# 時刻 → コマ番号変換（参考コードの_time_to_period を移植）
# OCCTO の時刻は「30分間の終了時刻」で記録
#   00:30 → コマ1 / 01:00 → コマ2 / ... / 24:00 → コマ48
# ────────────────────────────────────────────────────────────
def _time_to_period(time_str: str) -> int | None:
    try:
        h, m = map(int, time_str.strip().split(":"))
        if h == 24:
            return 48
        return h * 2 + (1 if m == 30 else 0) if m in (0, 30) else None
    except Exception:
        return None


def _period_to_label(period: int) -> str:
    """コマ番号 → 時刻ラベル（コマ開始時刻）"""
    h = (period - 1) * 30 // 60
    m = (period - 1) * 30 % 60
    return f"{h:02d}:{m:02d}"


# ────────────────────────────────────────────────────────────
# OCCTO CSV 取得（参考コードの_fetch_occto_csv/_parse_occto_csvを移植）
# ────────────────────────────────────────────────────────────
def _fetch_occto_raw(start_str: str, end_str: str) -> str | None:
    """OCCTO API から CSV テキストを取得する（ローカルPC用）"""
    url = OCCTO_URL.format(start=start_str, end=end_str)
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
        if e.code == 403:
            return None   # ホワイトリスト外（Streamlit Cloud 等）
        return None
    except Exception:
        return None


def _parse_occto_csv(csv_text: str) -> pd.DataFrame:
    """
    OCCTO CSV テキストを DataFrame に変換する。
    CSV 形式（参考コード確認済み）:
      "対象年月日","時刻","ブロックNo","エリア名","広域ブロック需要(MW)",
      "広域ブロック供給力(MW)","広域ブロック予備力(MW)","広域予備率(%)",
      "広域使用率(%)","エリア需要(MW)","エリア供給力(MW)","エリア予備力(MW)"
    """
    rows = []
    for line in csv_text.splitlines():
        line = line.strip().strip('"')
        if not line or "対象年月日" in line:
            continue
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 9:
            continue
        try:
            date_str    = parts[0]   # YYYY/MM/DD
            time_str    = parts[1]   # HH:MM
            area_name   = parts[3]   # エリア名
            broad_demand = parts[4]  # 広域ブロック需要(MW)
            broad_supply = parts[5]  # 広域ブロック供給力(MW)
            broad_reserve= parts[6]  # 広域ブロック予備力(MW)
            broad_rate   = parts[7]  # 広域予備率(%)
            broad_usage  = parts[8]  # 広域使用率(%)
            area_demand  = parts[9]  if len(parts) > 9  else ""
            area_supply  = parts[10] if len(parts) > 10 else ""
            area_reserve = parts[11] if len(parts) > 11 else ""

            if area_name not in AREAS:
                continue

            period = _time_to_period(time_str)
            if period is None:
                continue

            dt = datetime.strptime(date_str, "%Y/%m/%d").date()

            def _f(v):
                try:    return float(v)
                except: return float("nan")

            rows.append({
                "date":              dt,
                "対象年月日":        date_str,
                "時刻":              time_str,
                "period":            period,
                "エリア名":          area_name,
                "広域ブロック需要(MW)":   _f(broad_demand),
                "広域ブロック供給力(MW)": _f(broad_supply),
                "広域ブロック予備力(MW)": _f(broad_reserve),
                "広域予備率(%)":     _f(broad_rate),
                "広域使用率(%)":     _f(broad_usage),
                "エリア需要(MW)":    _f(area_demand),
                "エリア供給力(MW)":  _f(area_supply),
                "エリア予備力(MW)":  _f(area_reserve),
            })
        except (ValueError, IndexError):
            continue

    if not rows:
        return pd.DataFrame()

    df = (pd.DataFrame(rows)
          .drop_duplicates(["date", "period", "エリア名"])
          .sort_values(["date", "エリア名", "period"])
          .reset_index(drop=True))
    return df


# ────────────────────────────────────────────────────────────
# キャッシュ CSV 読み込み（GitHub Actions が保存したファイル）
# ────────────────────────────────────────────────────────────
def _decode_cached_csv(content: bytes) -> pd.DataFrame:
    for enc in ("cp932", "shift_jis", "utf-8"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = content.decode("cp932", errors="replace")
    return _parse_occto_csv(text)


@st.cache_data(ttl=120)
def load_from_cache() -> pd.DataFrame | None:
    """data/ ディレクトリの CSV を結合して返す"""
    csv_files = sorted(DATA_DIR.glob("block_*.csv"))
    if not csv_files:
        return None
    frames = []
    for f in csv_files:
        try:
            df = _decode_cached_csv(f.read_bytes())
            if not df.empty:
                frames.append(df)
        except Exception:
            pass
    if not frames:
        return None
    return (pd.concat(frames, ignore_index=True)
              .drop_duplicates(["date","period","エリア名"])
              .reset_index(drop=True))


@st.cache_data(ttl=300)
def load_from_occto(start: date, end: date) -> pd.DataFrame | None:
    """ローカルPC実行時: OCCTO から直接取得"""
    raw = _fetch_occto_raw(
        start.strftime("%Y/%m/%d"),
        end.strftime("%Y/%m/%d"),
    )
    if not raw:
        return None
    df = _parse_occto_csv(raw)
    return df if not df.empty else None


def get_last_updated() -> str:
    p = DATA_DIR / "last_updated.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else "不明"


# ────────────────────────────────────────────────────────────
# UI ヘルパー
# ────────────────────────────────────────────────────────────
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
                annotation_text=label,
                annotation_position="top right",
                annotation_font_color=color,
            )


# ────────────────────────────────────────────────────────────
# メイン
# ────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="OCCTO 広域予備率モニター",
        page_icon="⚡",
        layout="wide",
    )

    st.markdown("""
    <style>
      [data-testid="stAppViewContainer"] { background: #0d1117; }
      .kpi-card {
        background: linear-gradient(135deg,#112240,#0d1b2a);
        border-radius:12px; padding:16px 20px;
        border-left:4px solid #00aaff; margin-bottom:8px;
      }
      .kpi-title { color:#7eaed0; font-size:.78rem; margin-bottom:4px; }
      .kpi-val   { font-size:1.6rem; font-weight:700; }
      .kpi-sub   { color:#7eaed0; font-size:.72rem; }
      .header {
        background:linear-gradient(90deg,#003366,#005599);
        padding:18px 28px; border-radius:10px; margin-bottom:20px;
      }
      .header h1 { color:#fff; margin:0; font-size:1.7rem; }
      .header p  { color:#aad4ff; margin:4px 0 0; font-size:.88rem; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="header">
      <h1>⚡ OCCTO 広域予備率モニター</h1>
      <p>電力広域的運営推進機関（OCCTO）の広域予備率を可視化します</p>
    </div>
    """, unsafe_allow_html=True)

    # ── データ取得 ──────────────────────────────────────────────
    df_all = load_from_cache()
    data_source = "cache"

    if df_all is None or df_all.empty:
        # ローカル実行時: 直接取得
        today      = date.today()
        month_start = today.replace(day=1)
        prev_end    = month_start - timedelta(days=1)
        prev_start  = prev_end.replace(day=1)

        with st.spinner("OCCTO から直接データを取得中..."):
            frames = []
            for d_from, d_to in [(prev_start, prev_end), (month_start, today)]:
                df_tmp = load_from_occto(d_from, d_to)
                if df_tmp is not None:
                    frames.append(df_tmp)

        if frames:
            df_all = (pd.concat(frames, ignore_index=True)
                        .drop_duplicates(["date","period","エリア名"])
                        .reset_index(drop=True))
            data_source = "direct"
        else:
            st.error(
                "### ⚠️ データを取得できませんでした\n\n"
                "**原因**: Streamlit Cloud などのクラウドサーバーからは "
                "OCCTOのサイトへのアクセスがブロックされています。\n\n"
                "**解決方法 ①（推奨）**: "
                "GitHubリポジトリの **Actions** タブ → "
                "「OCCTO データ自動取得」→ **「Run workflow」** で手動実行し、"
                "しばらく待ってからページをリロードしてください。\n\n"
                "**解決方法 ②**: "
                "ローカルPCで `streamlit run app.py` として実行してください。"
            )
            return

    # ── サイドバー ──────────────────────────────────────────────
    with st.sidebar:
        st.header("🔧 表示設定")

        # データ範囲表示
        dmin = df_all["date"].min()
        dmax = df_all["date"].max()
        icon = "📁" if data_source == "cache" else "🌐"
        src  = "GitHub Actions キャッシュ" if data_source == "cache" else "OCCTO 直接取得"
        st.success(f"{icon} {src}\n\n{dmin} ～ {dmax}")
        if data_source == "cache":
            st.caption(f"最終更新: {get_last_updated()}")

        selected_areas = st.multiselect(
            "エリア選択（複数可）",
            AREAS,
            default=["東京", "関西"],
        )

        st.divider()
        st.subheader("📅 対象日・ピリオド")

        available_dates = sorted(df_all["date"].unique(), reverse=True)
        target_date = st.selectbox(
            "対象日",
            available_dates,
            format_func=lambda d: (
                d.strftime("%Y/%m/%d (%a)")
                if hasattr(d, "strftime") else str(d)
            ),
        )

        # ピリオド選択（コマ番号 1〜48 → 時刻ラベルで表示）
        period_options = list(range(1, 49))
        period_labels  = {p: _period_to_label(p) for p in period_options}
        selected_period = st.selectbox(
            "ピリオド（30分ごと）",
            period_options,
            format_func=lambda p: f"{period_labels[p]}（コマ{p}）",
            index=17,   # デフォルト: コマ18 = 08:30
        )
        selected_time_label = period_labels[selected_period]

        st.divider()
        st.subheader("📊 履歴の範囲")
        history_days = st.slider("遡る日数", 3, 31, 14)

        st.divider()
        st.subheader("⚠️ 警戒ライン")
        show_alerts = {k: st.checkbox(k, value=True) for k in ALERT_LINES}

    if not selected_areas:
        st.warning("エリアを1つ以上選択してください。")
        return

    # target_date を date 型に統一
    if not isinstance(target_date, date):
        target_date = pd.to_datetime(target_date).date()

    # ── タブ ────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(
        ["📡 当日リアルタイム", "📈 ピリオド別履歴推移", "📋 データテーブル"]
    )

    # ══════════════════════════════════════════════════════════
    # TAB 1: 当日リアルタイム
    # ══════════════════════════════════════════════════════════
    with tab1:
        st.subheader(
            f"📡 {target_date.strftime('%Y年%m月%d日')} 全コマの広域予備率"
        )

        df_today = df_all[
            (df_all["date"] == target_date) &
            (df_all["エリア名"].isin(selected_areas))
        ].copy()

        if df_today.empty:
            st.warning(
                "この日のデータがありません。\n\n"
                "GitHub Actions が実行済みか確認してください。"
            )
        else:
            # KPI カード
            cols = st.columns(len(selected_areas))
            for i, area in enumerate(selected_areas):
                adf = df_today[df_today["エリア名"] == area].sort_values("period")
                if adf.empty:
                    continue
                latest = adf.iloc[-1]
                val    = float(latest.get("広域予備率(%)", float("nan")))
                color  = rate_color(val)
                with cols[i]:
                    st.markdown(f"""
                    <div class="kpi-card" style="border-left-color:{color}">
                      <div class="kpi-title">広域予備率 — {area}</div>
                      <div class="kpi-val" style="color:{color}">{val:.2f}%</div>
                      <div class="kpi-sub">コマ{int(latest['period'])} ({latest['時刻']}) 時点</div>
                    </div>""", unsafe_allow_html=True)

            # 折れ線グラフ
            fig = go.Figure()
            for area in selected_areas:
                adf = df_today[df_today["エリア名"] == area].sort_values("period")
                fig.add_trace(go.Scatter(
                    x=adf["period"],
                    y=adf["広域予備率(%)"],
                    mode="lines+markers",
                    name=area,
                    line=dict(width=2),
                    marker=dict(size=5),
                    customdata=adf["時刻"],
                    hovertemplate=(
                        f"{area}<br>コマ%{{x}} (%{{customdata}})<br>"
                        "予備率: %{y:.2f}%<extra></extra>"
                    ),
                ))
            add_alert_lines(fig, show_alerts)

            # X軸を時刻ラベルに
            tick_vals   = list(range(1, 49, 4))
            tick_labels = [_period_to_label(p) for p in tick_vals]
            fig.update_layout(
                title=f"広域予備率（{target_date.strftime('%Y/%m/%d')}）",
                xaxis=dict(
                    title="時刻",
                    tickvals=tick_vals,
                    ticktext=tick_labels,
                ),
                yaxis_title="広域予備率 (%)",
                template="plotly_dark",
                height=450,
                legend=dict(orientation="h", y=-0.2),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

            # 追加グラフ: 広域ブロック需要・供給力
            with st.expander("📊 需要・供給力の推移も表示"):
                fig2 = go.Figure()
                for area in selected_areas:
                    adf = df_today[df_today["エリア名"] == area].sort_values("period")
                    for col, dash in [
                        ("広域ブロック需要(MW)",   "solid"),
                        ("広域ブロック供給力(MW)",  "dash"),
                    ]:
                        if col in adf.columns:
                            fig2.add_trace(go.Scatter(
                                x=adf["period"], y=adf[col],
                                mode="lines", name=f"{area} {col}",
                                line=dict(width=1.5, dash=dash),
                                customdata=adf["時刻"],
                                hovertemplate=(
                                    f"{area} {col}<br>コマ%{{x}} (%{{customdata}})<br>"
                                    "%{y:,.0f} MW<extra></extra>"
                                ),
                            ))
                fig2.update_layout(
                    xaxis=dict(tickvals=tick_vals, ticktext=tick_labels),
                    yaxis_title="MW",
                    template="plotly_dark",
                    height=350,
                    legend=dict(orientation="h", y=-0.3),
                )
                st.plotly_chart(fig2, use_container_width=True)

    # ══════════════════════════════════════════════════════════
    # TAB 2: ピリオド別履歴推移
    # ══════════════════════════════════════════════════════════
    with tab2:
        st.subheader(
            f"📈 コマ{selected_period}（{selected_time_label}）の"
            f"広域予備率推移（過去 {history_days} 日間）"
        )

        end_date   = target_date
        start_date = target_date - timedelta(days=history_days - 1)

        # date 型比較用に変換
        df_all["date_obj"] = pd.to_datetime(df_all["date"]).dt.date

        hist_df = df_all[
            (df_all["date_obj"] >= start_date) &
            (df_all["date_obj"] <= end_date) &
            (df_all["エリア名"].isin(selected_areas)) &
            (df_all["period"] == selected_period)
        ].copy()

        if hist_df.empty:
            st.warning(
                f"指定期間（{start_date} ～ {end_date}）の "
                f"コマ{selected_period}（{selected_time_label}）"
                "のデータがありません。"
            )
        else:
            hist_df["date_obj"] = pd.to_datetime(hist_df["date"]).dt.date
            hist_df = hist_df.sort_values("date_obj")

            fig3 = go.Figure()
            for area in selected_areas:
                adf = hist_df[hist_df["エリア名"] == area]
                if adf.empty:
                    continue
                fig3.add_trace(go.Scatter(
                    x=adf["date_obj"],
                    y=adf["広域予備率(%)"],
                    mode="lines+markers+text",
                    name=area,
                    text=adf["広域予備率(%)"].round(1).astype(str) + "%",
                    textposition="top center",
                    textfont=dict(size=9),
                    marker=dict(size=8),
                    line=dict(width=2.5),
                    hovertemplate=(
                        f"{area}<br>%{{x}}<br>予備率: %{{y:.2f}}%<extra></extra>"
                    ),
                ))
            add_alert_lines(fig3, show_alerts)
            fig3.update_layout(
                title=(
                    f"広域予備率 履歴推移 "
                    f"（コマ{selected_period} = {selected_time_label}）"
                ),
                xaxis_title="日付",
                yaxis_title="広域予備率 (%)",
                template="plotly_dark",
                height=480,
                legend=dict(orientation="h", y=-0.2),
                hovermode="x unified",
            )
            st.plotly_chart(fig3, use_container_width=True)

            # 統計サマリー
            st.subheader("📊 統計サマリー")
            rows = []
            for area in selected_areas:
                vals = (hist_df[hist_df["エリア名"] == area]["広域予備率(%)"]
                        .dropna())
                if vals.empty:
                    continue
                rows.append({
                    "エリア":          area,
                    "平均 (%)":        round(vals.mean(), 2),
                    "最小 (%)":        round(vals.min(),  2),
                    "最大 (%)":        round(vals.max(),  2),
                    "標準偏差":        round(vals.std(),  2),
                    "3%未満の日数":    int((vals < 3).sum()),
                    "5%未満の日数":    int((vals < 5).sum()),
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
            (df_all["date"] == target_date) &
            (df_all["エリア名"].isin(selected_areas))
        ].copy()

        if df_tbl.empty:
            st.info("この日のデータがありません。")
        else:
            disp_cols = [c for c in [
                "対象年月日", "時刻", "period", "エリア名",
                "広域予備率(%)", "広域使用率(%)",
                "広域ブロック需要(MW)", "広域ブロック供給力(MW)", "広域ブロック予備力(MW)",
                "エリア需要(MW)", "エリア供給力(MW)", "エリア予備力(MW)",
            ] if c in df_tbl.columns]

            show_df = df_tbl[disp_cols].rename(columns={"period": "コマ番号"})\
                                        .sort_values(["エリア名","コマ番号"])

            def _color_cell(val):
                try:
                    v = float(val)
                    if v < 3: return "background-color:#7f0000;color:white"
                    if v < 5: return "background-color:#7f4000;color:white"
                    if v < 8: return "background-color:#7f6000;color:white"
                    return ""
                except Exception:
                    return ""

            styled = show_df.style.map(_color_cell, subset=["広域予備率(%)"])
            st.dataframe(styled, use_container_width=True, height=500)

            csv_bytes = show_df.to_csv(index=False, encoding="utf-8-sig")\
                                .encode("utf-8-sig")
            st.download_button(
                "⬇️ CSVダウンロード",
                data=csv_bytes,
                file_name=f"occto_{target_date.strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )

    # ── フッター ─────────────────────────────────────────────
    st.divider()
    st.caption(
        "データソース: [OCCTO 広域予備率Web公表システム]"
        "(https://web-kohyo.occto.or.jp/kks-web-public/)　"
        f"キャッシュ最終更新: {get_last_updated()}"
    )


if __name__ == "__main__":
    main()
