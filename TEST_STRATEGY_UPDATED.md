# テスト戦略：単体テストと結合テスト

## 📋 概要

pyscraperプロジェクトでは、一般的なソフトウェアテストの標準に従い、**2種類のテスト**を明確に分けて管理しています。

| テスト種別 | 外部依存 | 実行速度 | デフォルト実行 | 用途 |
|-----------|---------|---------|--------------|------|
| **単体テスト (Unit Test)** | なし（モック） | 高速（< 2秒） | ✅ はい | 日常開発、CI/CD |
| **結合テスト (Integration Test)** | あり（実環境） | 遅い（数分） | ❌ いいえ | リリース前検証 |

---

## ✅ 単体テスト（Unit Test）

### 特徴

- ✅ **外部依存なし**: すべての外部サービスをモック化
- ✅ **高速実行**: 全テスト < 2秒で完了
- ✅ **オフライン実行可能**: インターネット接続不要
- ✅ **再現性100%**: 環境に依存しない
- ✅ **CI/CDフレンドリー**: すべてのコミットで実行可能

### マーカー

マーカーなし（デフォルト）

### 実行方法

```bash
# デフォルト実行（単体テストのみ）
pytest tests/

# 明示的に指定
pytest tests/ -m "not integration"
```

### 対象テスト（130テスト）

#### WebFile - 47テスト ✅
- HTTPダウンロード（モック）
- Rangeリクエスト（モック）
- エラーハンドリング
- プログレスコールバック
- ファイルI/O操作

#### HLSFile - 27テスト ✅
- HLSストリーム解析（モック）
- 動画セグメントダウンロード（モック）
- FFmpeg統合（モック）
- キャッシュ管理

#### Utils - 14テスト ✅
- CachedGenerator
- LazyList

#### WebPage (Requests) - 31テスト ✅
- HTMLパース
- XPath処理
- エンコーディング

#### WebPage (Curl) - 11テスト ⚠️
- 一部失敗あり（既知の問題）

### 実行結果

```
119/130 passed (91.5%)
実行時間: 1.42秒
```

---

## 🌐 結合テスト（Integration Test）

### 特徴

- ⚠️ **実環境依存**: 実際のHTTP、FFmpeg、ブラウザを使用
- ⚠️ **低速実行**: 数秒〜数分かかる
- ⚠️ **ネットワーク必須**: インターネット接続が必要
- ⚠️ **環境依存**: ブラウザ、FFmpegのインストールが必要
- ⚠️ **選択的実行**: デフォルトでは除外

### マーカー

`@pytest.mark.integration`

### 実行方法

```bash
# 結合テストのみ実行
pytest tests/ -m integration -v

# 環境変数で制御
INTEGRATION_TEST=1 pytest tests/ -v

# すべてのテスト（単体 + 結合）
pytest tests/ -m "" -v
```

### 対象テスト（88テスト）

#### HTTP統合テスト - 11テスト
- 実際のHTTPリクエスト（httpbin.org）
- Rangeリクエスト
- リダイレクト処理
- タイムアウト処理
- Content-Type検出

**場所:** `tests/integration/test_webfile_integration.py`

#### ブラウザ統合テスト - 77テスト
- Firefox自動化テスト
- Chrome自動化テスト
- Selenium WebDriver操作
- JavaScript実行
- DOM操作

**場所:** `tests/test_webpage.py` (TestWebPageFirefox, TestWebPageChrome)

### 必要な環境

```bash
# ネットワーク接続
ping httpbin.org

# FFmpeg（HLS処理用）
sudo apt-get install ffmpeg  # Ubuntu/Debian
brew install ffmpeg          # macOS

# ブラウザドライバー（Selenium用）
# Firefox: geckodriver
# Chrome: chromedriver
```

---

## 🎯 実行戦略

### ローカル開発

```bash
# 通常の開発（単体テストのみ）
pytest tests/

# 特定モジュールのみ
pytest tests/test_webfile.py -v

# カバレッジ測定
pytest tests/ --cov=pyscraper --cov-report=html
```

### コミット前

```bash
# 単体テストが全て成功することを確認
pytest tests/ -v

# 成功したらコミット
git add -A
git commit -m "..."
```

### Pull Request (CI/CD)

```yaml
# GitHub Actions例
- name: Run unit tests
  run: pytest tests/ -v --cov=pyscraper
```

**実行されるテスト:**
- ✅ 単体テスト（130テスト）
- ❌ 結合テスト（除外）

### mainブランチマージ後

```yaml
# GitHub Actions例
- name: Run integration tests
  run: pytest tests/ -m integration -v
  if: github.ref == 'refs/heads/main'
```

**実行されるテスト:**
- ✅ 単体テスト（130テスト）
- ✅ 結合テスト（88テスト）

### リリース前

```bash
# すべてのテストを実行
pytest tests/ -m "" -v

# または
pytest tests/ --override-ini="addopts=" -v
```

**実行されるテスト:**
- ✅ 単体テスト（130テスト）
- ✅ 結合テスト（88テスト）

---

## 📊 テスト配分

```
総テスト数: 218

単体テスト（デフォルト）: 130 (60%)
├── WebFile: 47
├── HLSFile: 27
├── Utils: 14
├── WebPage (Requests): 31
└── WebPage (Curl): 11

結合テスト（選択実行）: 88 (40%)
├── HTTP統合: 11
├── Firefox: ~38
└── Chrome: ~39
```

---

## 💡 ベストプラクティス

### 1. 新機能開発時

```bash
# ステップ1: 単体テストを書く
# tests/test_*.py に追加（マーカーなし）

# ステップ2: 単体テストで開発
pytest tests/test_your_module.py -v

# ステップ3: 機能完成後、必要に応じて結合テストを追加
# tests/integration/test_your_module_integration.py
# @pytest.mark.integration を付ける
```

### 2. リファクタリング時

```bash
# 単体テストを高速実行しながらリファクタリング
pytest tests/ -v

# 完了後、結合テストでも検証
pytest tests/ -m integration -v
```

### 3. バグ修正時

```bash
# ステップ1: バグを再現する単体テストを書く
# ステップ2: テストが失敗することを確認
pytest tests/test_bugfix.py -v

# ステップ3: バグを修正
# ステップ4: テストが成功することを確認
pytest tests/test_bugfix.py -v
```

---

## 🔧 カスタマイズ

### 統合テストをデフォルトで含める

**pyproject.toml を編集:**
```toml
[tool.pytest.ini_options]
# addopts の行を削除またはコメントアウト
# addopts = "-m 'not integration'"
```

### 特定の統合テストのみ実行

```bash
# HTTPテストのみ
pytest tests/integration/ -v

# Firefoxテストのみ
pytest tests/ -m integration -k Firefox -v

# Chromeテストのみ
pytest tests/ -m integration -k Chrome -v
```

---

## ❓ よくある質問

### Q: なぜ単体テストと結合テストを分けるのか？

**A:** 開発速度と品質のバランスのためです。

- **単体テスト**: 高速なフィードバック（< 2秒）でTDD可能
- **結合テスト**: 本番環境との互換性を確認

両方があることで、開発は高速に、リリースは安全に行えます。

### Q: 統合テストとブラウザテストは別々にすべきでは？

**A:** いいえ、両方とも「実環境依存テスト」として同じカテゴリです。

- どちらも外部依存が必要
- どちらもデフォルトでは実行したくない
- 実行タイミングは同じ（リリース前、定期実行）

違いは依存の種類（HTTP vs ブラウザ）のみで、本質的には同じです。

### Q: すべてのテストを毎回実行すべきでは？

**A:** いいえ、状況に応じて使い分けます。

| 状況 | 実行すべきテスト | 理由 |
|------|----------------|------|
| 開発中 | 単体テストのみ | 高速フィードバック |
| コミット前 | 単体テストのみ | CI/CDコスト削減 |
| リリース前 | すべて | 本番互換性確認 |

---

## 📚 関連ドキュメント

- [TESTING_GUIDE.md](./TESTING_GUIDE.md) - 詳細な実行方法
- [TESTING_QUICK_REFERENCE.md](./TESTING_QUICK_REFERENCE.md) - コマンドリファレンス
- [TEST_LIST.md](./TEST_LIST.md) - 全テスト一覧
- [tests/integration/README.md](./tests/integration/README.md) - 結合テスト詳細

---

## ✅ まとめ

**単体テストと結合テストの2種類分類により:**

- ✅ **開発速度向上**: 単体テストで高速フィードバック（< 2秒）
- ✅ **品質保証**: 結合テストで本番互換性確認
- ✅ **CI/CDコスト削減**: デフォルトは単体テストのみ
- ✅ **明確な戦略**: いつ何を実行するか明確
- ✅ **標準的アプローチ**: 業界標準のテスト分類

この戦略により、高速な開発サイクルと高品質なリリースの両立が可能になります。
