import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import io
from datetime import date, timedelta, datetime
import time

# ────────────────────────────────────────────────────────────
# 定数
# ────────────────────────────────────────────────────────────
BASE_URL = "https://web-kohyo.occto.or.jp/kks-web-public/download/downloadCsv"

# jhSybt コード
DATA_TYPES = {
    "広域予備率ブロック情報（翌日・当日）": "02",
    "広域予備率ブロック情報（週間）":       "01",
    "広域予備率ブロック情報（翌々日）":     "06",
}

AREAS = ["北海道", "東北", "東京", "中部", "北陸", "関西", "中国", "四国", "九州", "沖縄"]

# 警戒ライン
ALERT_LINES = {
    "予備率3%（需給逼迫注意）": 3.0,
    "予備率5%（安定供給下限）": 5.0,
    "予備率8%（適正水準）":     8.0,
}

# ────────────────────────────────────────────────────────────
# データ取得
# ────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_occto_csv(data_type_code: str, date_from: str, date_to: str) -> pd.DataFrame | None:
    """OCCTOから広域予備率CSVを取得してDataFrameを返す"""
    params = {
        "jhSybt":     data_type_code,
        "tgtYmdFrom": date_from,
        "tgtYmdTo":   date_to,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":    "https://web-kohyo.occto.or.jp/kks-web-public/download",
    }
    try:
        resp = requests.get(BASE_URL, params=params, headers=headers, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "text/csv" not in content_type and "application/octet-stream" not in content_type:
            # HTML が返ってきた場合はサービス側の問題
            return None
        # エンコーディング検出
        for enc in ("shift_jis", "utf-8", "cp932"):
            try:
                text = resp.content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = resp.content.decode("shift_jis", errors="replace")

        df = pd.read_csv(io.StringIO(text))
        df.columns = df.columns.str.strip().str.replace('"', '')
        # 文字列の引用符除去
        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str).str.strip().str.replace('"', '')
        return df
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
        return None


def build_datetime(row) -> datetime | None:
    """対象年月日 + 時刻 → datetime"""
    try:
        dt_str = f"{str(row['対象年月日']).strip()} {str(row['時刻']).strip()}"
        return datetime.strptime(dt_str, "%Y/%m/%d %H:%M")
    except Exception:
        return None


def load_data(data_type_code: str, date_from: date, date_to: date) -> pd.DataFrame | None:
    df = fetch_occto_csv(
        data_type_code,
        date_from.strftime("%Y/%m/%d"),
        date_to.strftime("%Y/%m/%d"),
    )
    if df is None or df.empty:
        return None
    if "対象年月日" not in df.columns or "時刻" not in df.columns:
        return None
    df["datetime"] = df.apply(build_datetime, axis=1)
    df = df.dropna(subset=["datetime"])
    # 数値列変換
    for col in ["広域予備率(%)", "広域使用率(%)", "広域ブロック需要(MW)", "広域ブロック供給力(MW)"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ────────────────────────────────────────────────────────────
# サンプルデータ（オフライン時のフォールバック）
# ────────────────────────────────────────────────────────────
def make_sample_data(target_date: date, area: str) -> pd.DataFrame:
    import numpy as np
    rng = np.random.default_rng(hash(str(target_date) + area) % (2**32))
    times = pd.date_range(
        start=datetime.combine(target_date, datetime.min.time()) + timedelta(minutes=30),
        periods=48, freq="30min"
    )
    base = 12 + 8 * np.sin(np.linspace(0, 2 * np.pi, 48) - np.pi / 2)
    noise = rng.normal(0, 0.8, 48)
    values = np.clip(base + noise, 3, 40)
    return pd.DataFrame({
        "datetime": times,
        "対象年月日": [target_date.strftime("%Y/%m/%d")] * 48,
        "時刻": [t.strftime("%H:%M") for t in times],
        "エリア名": area,
        "広域予備率(%)": values.round(2),
        "広域使用率(%)": (100 - values).round(2),
        "広域ブロック需要(MW)": (rng.uniform(5000, 50000, 48)).round(0),
        "広域ブロック供給力(MW)": (rng.uniform(6000, 60000, 48)).round(0),
    })


# ────────────────────────────────────────────────────────────
# メイン UI
# ────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="OCCTO 広域予備率モニター",
        page_icon="⚡",
        layout="wide",
    )

    # ─── カスタム CSS ───
    st.markdown("""
    <style>
      .metric-card {
        background: linear-gradient(135deg, #1e3a5f 0%, #0d1b2a 100%);
        border-radius: 12px;
        padding: 16px 20px;
        border-left: 4px solid #00aaff;
        margin-bottom: 8px;
      }
      .metric-title { color: #8eb4d8; font-size: 0.78rem; margin-bottom: 4px; }
      .metric-value { color: #ffffff; font-size: 1.6rem; font-weight: bold; }
      .metric-sub   { color: #8eb4d8; font-size: 0.75rem; }
      .header-band {
        background: linear-gradient(90deg, #003366, #005599);
        padding: 18px 28px;
        border-radius: 10px;
        margin-bottom: 20px;
      }
      .header-band h1 { color: white; margin: 0; font-size: 1.7rem; }
      .header-band p  { color: #aad4ff; margin: 4px 0 0 0; font-size: 0.9rem; }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="header-band">
      <h1>⚡ OCCTO 広域予備率モニター</h1>
      <p>電力広域的運営推進機関（OCCTO）の広域予備率をリアルタイムに可視化します</p>
    </div>
    """, unsafe_allow_html=True)

    # ─── サイドバー ───
    with st.sidebar:
        st.header("🔧 表示設定")

        # データ種別
        data_type_label = st.selectbox("データ種別", list(DATA_TYPES.keys()), index=0)
        data_type_code  = DATA_TYPES[data_type_label]

        # エリア選択
        selected_areas = st.multiselect(
            "エリア選択（複数可）",
            AREAS,
            default=["東京", "関西"],
        )

        st.divider()
        st.subheader("📅 対象日・ピリオド指定")

        target_date = st.date_input(
            "対象日（特定ピリオドの履歴を追う日）",
            value=date.today() - timedelta(days=1),
            max_value=date.today(),
        )

        # 時刻（30分刻み）
        time_options = [
            f"{h:02d}:{m:02d}"
            for h in range(24)
            for m in (0, 30)
            if not (h == 0 and m == 0)
        ] + ["24:00"]

        selected_time = st.selectbox(
            "ピリオド（30分ごと）",
            time_options,
            index=time_options.index("09:00") if "09:00" in time_options else 0,
        )

        st.divider()
        st.subheader("📊 過去履歴の範囲")

        history_days = st.slider(
            "遡る日数", min_value=3, max_value=31, value=14, step=1,
        )

        st.divider()
        st.subheader("⚠️ 警戒ライン")
        show_alerts = {k: st.checkbox(k, value=True) for k in ALERT_LINES}

        st.divider()
        use_sample = st.checkbox(
            "📦 サンプルデータを使用（OCCTOサイト未接続時）",
            value=False,
            help="OCCTOサイトへの接続ができない環境でも動作確認できます",
        )

    if not selected_areas:
        st.warning("エリアを1つ以上選択してください。")
        return

    # ─── タブ ───
    tab_current, tab_history, tab_table = st.tabs(
        ["📡 当日リアルタイム", "📈 ピリオド別履歴推移", "📋 データテーブル"]
    )

    # ════════════════════════════════════════
    # TAB 1: 当日リアルタイム
    # ════════════════════════════════════════
    with tab_current:
        st.subheader(f"📡 {target_date.strftime('%Y年%m月%d日')} 全時刻の広域予備率")

        with st.spinner("データを取得中..."):
            if use_sample:
                dfs = [make_sample_data(target_date, a) for a in selected_areas]
                df_today = pd.concat(dfs, ignore_index=True)
                st.info("サンプルデータを表示しています。")
            else:
                df_raw = load_data(data_type_code, target_date, target_date)
                if df_raw is not None:
                    df_today = df_raw[df_raw["エリア名"].isin(selected_areas)].copy()
                else:
                    st.warning(
                        "OCCTOからのデータ取得に失敗しました。"
                        "サイドバーの「サンプルデータを使用」をONにすることで動作を確認できます。"
                    )
                    df_today = pd.DataFrame()

        if not df_today.empty:
            # KPI カード
            cols = st.columns(len(selected_areas))
            for i, area in enumerate(selected_areas):
                adf = df_today[df_today["エリア名"] == area]
                if adf.empty:
                    continue
                latest = adf.sort_values("datetime").iloc[-1]
                val = latest.get("広域予備率(%)", float("nan"))
                color = "#ff4444" if val < 5 else "#ffaa00" if val < 8 else "#00cc66"
                with cols[i]:
                    st.markdown(f"""
                    <div class="metric-card" style="border-left-color:{color}">
                      <div class="metric-title">最新 広域予備率 — {area}</div>
                      <div class="metric-value" style="color:{color}">{val:.2f} %</div>
                      <div class="metric-sub">{latest['時刻']} 時点</div>
                    </div>""", unsafe_allow_html=True)

            # 折れ線グラフ
            fig = go.Figure()
            for area in selected_areas:
                adf = df_today[df_today["エリア名"] == area].sort_values("datetime")
                fig.add_trace(go.Scatter(
                    x=adf["datetime"], y=adf["広域予備率(%)"],
                    mode="lines+markers", name=area,
                    line=dict(width=2),
                    marker=dict(size=5),
                    hovertemplate=f"{area}<br>%{{x|%H:%M}}<br>予備率: %{{y:.2f}}%<extra></extra>",
                ))

            # 警戒ライン
            for label, val in ALERT_LINES.items():
                if show_alerts.get(label):
                    color = "#ff4444" if val <= 3 else "#ffaa00" if val <= 5 else "#88cc88"
                    fig.add_hline(
                        y=val, line_dash="dash", line_color=color, line_width=1.5,
                        annotation_text=label,
                        annotation_position="top right",
                        annotation_font_color=color,
                    )

            fig.update_layout(
                title=f"広域予備率（{target_date.strftime('%Y/%m/%d')}）",
                xaxis_title="時刻",
                yaxis_title="広域予備率 (%)",
                template="plotly_dark",
                height=450,
                legend=dict(orientation="h", y=-0.2),
                hovermode="x unified",
            )
            st.plotly_chart(fig, use_container_width=True)

    # ════════════════════════════════════════
    # TAB 2: ピリオド別履歴
    # ════════════════════════════════════════
    with tab_history:
        st.subheader(
            f"📈 {selected_time} ピリオドの広域予備率推移（過去 {history_days} 日間）"
        )

        end_date   = target_date
        start_date = target_date - timedelta(days=history_days - 1)

        date_range = [start_date + timedelta(days=i) for i in range(history_days)]

        with st.spinner(f"過去 {history_days} 日分のデータを取得中..."):
            all_rows = []

            if use_sample:
                for d in date_range:
                    for area in selected_areas:
                        sdf = make_sample_data(d, area)
                        row = sdf[sdf["時刻"] == selected_time]
                        if not row.empty:
                            all_rows.append(row.iloc[0])
                st.info("サンプルデータを表示しています。")
            else:
                # 1回のAPIコールで全期間取得（最大31日）
                df_all = load_data(data_type_code, start_date, end_date)
                if df_all is not None:
                    mask = (
                        df_all["エリア名"].isin(selected_areas) &
                        (df_all["時刻"] == selected_time)
                    )
                    filtered = df_all[mask]
                    for _, r in filtered.iterrows():
                        all_rows.append(r)
                else:
                    st.warning(
                        "データ取得に失敗しました。「サンプルデータを使用」を試してください。"
                    )

        if all_rows:
            hist_df = pd.DataFrame(all_rows).reset_index(drop=True)
            hist_df["date"] = pd.to_datetime(hist_df["対象年月日"].str.strip(), format="%Y/%m/%d")
            hist_df = hist_df.sort_values("date")

            fig2 = go.Figure()
            for area in selected_areas:
                adf = hist_df[hist_df["エリア名"] == area]
                if adf.empty:
                    continue
                fig2.add_trace(go.Scatter(
                    x=adf["date"], y=adf["広域予備率(%)"],
                    mode="lines+markers+text",
                    name=area,
                    text=adf["広域予備率(%)"].round(1).astype(str) + "%",
                    textposition="top center",
                    textfont=dict(size=9),
                    marker=dict(size=8),
                    line=dict(width=2.5),
                    hovertemplate=(
                        f"{area}<br>%{{x|%Y/%m/%d}}<br>"
                        "予備率: %{y:.2f}%<extra></extra>"
                    ),
                ))

            # 警戒ライン
            for label, val in ALERT_LINES.items():
                if show_alerts.get(label):
                    color = "#ff4444" if val <= 3 else "#ffaa00" if val <= 5 else "#88cc88"
                    fig2.add_hline(
                        y=val, line_dash="dot", line_color=color, line_width=1.5,
                        annotation_text=label,
                        annotation_position="top right",
                        annotation_font_color=color,
                    )

            fig2.update_layout(
                title=f"広域予備率 履歴推移（{selected_time} ピリオド）",
                xaxis_title="日付",
                yaxis_title="広域予備率 (%)",
                template="plotly_dark",
                height=480,
                legend=dict(orientation="h", y=-0.2),
                hovermode="x unified",
            )
            st.plotly_chart(fig2, use_container_width=True)

            # 統計サマリー
            st.subheader("📊 統計サマリー")
            summary_rows = []
            for area in selected_areas:
                adf = hist_df[hist_df["エリア名"] == area]["広域予備率(%)"].dropna()
                if adf.empty:
                    continue
                summary_rows.append({
                    "エリア": area,
                    "平均 (%)":   round(adf.mean(), 2),
                    "最小 (%)":   round(adf.min(),  2),
                    "最大 (%)":   round(adf.max(),  2),
                    "標準偏差":   round(adf.std(),  2),
                    "3%未満の日数": int((adf < 3).sum()),
                    "5%未満の日数": int((adf < 5).sum()),
                })
            if summary_rows:
                st.dataframe(
                    pd.DataFrame(summary_rows).set_index("エリア"),
                    use_container_width=True,
                )
        else:
            st.info("指定ピリオドのデータが見つかりませんでした。")

    # ════════════════════════════════════════
    # TAB 3: データテーブル
    # ════════════════════════════════════════
    with tab_table:
        st.subheader("📋 生データテーブル")

        with st.spinner("データを取得中..."):
            if use_sample:
                dfs = [make_sample_data(target_date, a) for a in selected_areas]
                df_tbl = pd.concat(dfs, ignore_index=True)
            else:
                df_raw2 = load_data(data_type_code, target_date, target_date)
                if df_raw2 is not None:
                    df_tbl = df_raw2[df_raw2["エリア名"].isin(selected_areas)].copy()
                else:
                    df_tbl = pd.DataFrame()

        if not df_tbl.empty:
            display_cols = [
                c for c in [
                    "対象年月日", "時刻", "エリア名",
                    "広域予備率(%)", "広域使用率(%)",
                    "広域ブロック需要(MW)", "広域ブロック供給力(MW)", "広域ブロック予備力(MW)"
                ] if c in df_tbl.columns
            ]
            show_df = df_tbl[display_cols].sort_values(["エリア名", "時刻"])

            # カラーマップ付き表示
            def color_rate(val):
                try:
                    v = float(val)
                    if v < 3:   return "background-color: #7f0000; color: white"
                    if v < 5:   return "background-color: #804000; color: white"
                    if v < 8:   return "background-color: #806000; color: white"
                    return ""
                except Exception:
                    return ""

            styled = show_df.style.applymap(color_rate, subset=["広域予備率(%)"])
            st.dataframe(styled, use_container_width=True, height=500)

            # CSVダウンロード
            csv_data = show_df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                "⬇️ CSVダウンロード",
                data=csv_data,
                file_name=f"occto_reserve_{target_date.strftime('%Y%m%d')}.csv",
                mime="text/csv",
            )
        else:
            st.info("データがありません。")

    # ─── フッター ───
    st.divider()
    st.caption(
        "データソース: [電力広域的運営推進機関（OCCTO）広域予備率Web公表システム]"
        "(https://web-kohyo.occto.or.jp/kks-web-public/)　"
        f"最終更新: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


if __name__ == "__main__":
    main()
