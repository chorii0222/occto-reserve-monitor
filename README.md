# ⚡ OCCTO 広域予備率モニター

電力広域的運営推進機関（OCCTO）が公表する**広域予備率**をリアルタイムに可視化するWebアプリです。

🔗 **[アプリを開く](https://your-app-url.streamlit.app)** ← デプロイ後にURLを更新してください

---

## 📋 機能

| タブ | 内容 |
|------|------|
| 📡 当日リアルタイム | 指定日の全時刻の予備率グラフ＋KPIカード |
| 📈 ピリオド別履歴推移 | 指定ピリオドが過去N日間でどう変化したかのトレンド |
| 📋 データテーブル | 生データ表示（色分け）＋CSVダウンロード |

- エリア複数選択（北海道〜沖縄）
- 警戒ライン（3% / 5% / 8%）の表示
- オフライン時はサンプルデータで動作確認可能

## 🚀 ローカルで動かす

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 📦 デプロイ (Streamlit Community Cloud)

1. このリポジトリを GitHub に push
2. [share.streamlit.io](https://share.streamlit.io) にアクセスしてGitHubでログイン
3. **New app** → リポジトリ・ブランチ・`app.py` を選択
4. **Deploy!**

## 📊 データソース

[電力広域的運営推進機関（OCCTO）広域予備率Web公表システム](https://web-kohyo.occto.or.jp/kks-web-public/)
