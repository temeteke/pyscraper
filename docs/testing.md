# Testing Guide

このガイドでは、pyscraperプロジェクトのテスト実行方法を説明します。

## 📋 概要

pyscraperでは、**単体テスト（Unit Test）** と **結合テスト（Integration Test）** の2種類を明確に分けて管理しています。

| テスト種別 | 外部依存 | 実行速度 | デフォルト実行 | 用途 |
|-----------|---------|---------|--------------|------|
| **単体テスト** | なし（モック） | 高速（~1秒） | ✅ はい | 日常開発、CI/CD |
| **結合テスト** | あり（実環境） | 遅い（数分） | ❌ いいえ | リリース前検証 |

```
総テスト数: 218

単体テスト（デフォルト）: 114 (52%)
├── WebFile: 47
├── HLSFile: 27
├── Utils: 14
└── WebPage (Requests): 26

結合テスト（選択実行）: 104 (48%)
├── WebFile (HTTP): 11
├── WebPageCurl: 16
├── Selenium Firefox: 39
└── Selenium Chrome: 38
```

---

## クイックスタート

```bash
# 単体テストのみ（デフォルト・推奨）
pytest tests/

# 結合テストのみ
pytest tests/ -m integration -v

# すべてのテスト
pytest tests/ -m "" -v
```

---

## ✅ 単体テスト（Unit Test）

### 特徴

- ✅ **外部依存なし**: すべての外部サービスをモック化
- ✅ **高速実行**: 全テスト ~1.2秒で完了
- ✅ **オフライン実行可能**: インターネット接続不要
- ✅ **再現性100%**: 環境に依存しない
- ✅ **CI/CDフレンドリー**: すべてのコミットで実行可能

### 実行方法

```bash
# デフォルト実行（単体テストのみ）
pytest tests/

# 明示的に指定
pytest tests/ -m "not integration"

# 詳細出力
pytest tests/ -v

# カバレッジ測定
pytest tests/ --cov=pyscraper --cov-report=html
```

### 対象テスト（114テスト）

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

#### WebPage (Requests) - 26テスト ✅
- HTMLパース
- XPath処理
- エンコーディング
- HTTP通信（モック）

### 実行結果

```
114/114 passed (100%)
実行時間: 1.22秒
```

---

## 🌐 結合テスト（Integration Test）

### 特徴

- ⚠️ **実環境依存**: 実際のHTTP、Curl、Selenium を使用
- ⚠️ **低速実行**: 数秒〜数分かかる
- ⚠️ **ネットワーク必須**: インターネット接続が必要
- ⚠️ **環境依存**: ブラウザ、curlのインストールが必要
- ⚠️ **選択的実行**: デフォルトでは除外

### 実行方法

```bash
# 結合テストのみ実行
pytest tests/ -m integration -v

# 環境変数で制御
INTEGRATION_TEST=1 pytest tests/ -v

# すべてのテスト（単体 + 結合）
pytest tests/ -m "" -v
```

### 対象テスト（104テスト）

#### WebFile HTTP結合テスト - 11テスト
- 実際のHTTPリクエスト（httpbin.org）
- Rangeリクエスト
- リダイレクト処理
- タイムアウト処理
- Content-Type検出

**場所:** `tests/test_webfile.py::TestWebFileIntegration`

#### WebPageCurl 結合テスト - 16テスト
- 実際のcurlコマンド実行
- HTMLダウンロードと解析
- XPath処理

**場所:** `tests/test_webpage.py::TestWebPageCurl`

**注意:** curl コマンドが実際に実行されます。環境によってはアクセス制限でテストが失敗する可能性があります。

#### Selenium結合テスト - 77テスト
- **Firefox自動化テスト (39個)**
- **Chrome自動化テスト (38個)**
- Selenium WebDriver操作
- JavaScript実行
- DOM操作

**場所:** `tests/test_webpage.py::TestWebPageFirefox`, `TestWebPageChrome`

### 必要な環境

```bash
# ネットワーク接続
ping httpbin.org
ping temeteke.github.io

# curlコマンド
curl --version

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
- ✅ 単体テスト（114テスト）
- ❌ 結合テスト（除外）

### mainブランチマージ後

```yaml
# GitHub Actions例
- name: Run integration tests
  run: pytest tests/ -m integration -v
  if: github.ref == 'refs/heads/main'
```

**実行されるテスト:**
- ✅ 結合テスト（104テスト）

### リリース前

```bash
# すべてのテストを実行
pytest tests/ -m "" -v

# または
pytest tests/ --override-ini="addopts=" -v
```

**実行されるテスト:**
- ✅ 単体テスト（114テスト）
- ✅ 結合テスト（104テスト）

---

## 💡 実践的な使い方

### 特定のテストを実行

```bash
# ファイル指定
pytest tests/test_webfile.py

# クラス指定
pytest tests/test_webfile.py::TestWebFile

# メソッド指定
pytest tests/test_webfile.py::TestWebFile::test_download_unlink

# パターンマッチ
pytest tests/ -k download              # 名前に"download"を含むテスト
pytest tests/ -k "not slow"            # "slow"を含まないテスト
```

### デバッグオプション

```bash
# 詳細出力
pytest tests/ -v                       # verbose
pytest tests/ -vv                      # more verbose

# 失敗時のデバッグ
pytest tests/ -x                       # 最初の失敗で停止
pytest tests/ -s                       # 標準出力を表示
pytest tests/ --lf                     # 最後に失敗したテストのみ
pytest tests/ --pdb                    # 失敗時にデバッガ起動

# スタックトレース制御
pytest tests/ --tb=short               # 簡潔なトレース
pytest tests/ --tb=no                  # トレースなし
```

### カバレッジ測定

```bash
# カバレッジ測定
pytest tests/ --cov=pyscraper

# HTMLレポート生成
pytest tests/ --cov=pyscraper --cov-report=html
open htmlcov/index.html

# カバレッジを表示しながら実行
pytest tests/ --cov=pyscraper --cov-report=term-missing
```

### 並列実行

```bash
# 並列実行（要 pytest-xdist）
pip install pytest-xdist

# 4プロセスで並列化
pytest tests/ -n 4

# 自動でCPUコア数を検出
pytest tests/ -n auto
```

---

## 📝 新しいテストの追加

### 単体テスト（推奨）

```python
# tests/test_your_module.py

def test_new_feature():
    """新機能のテスト（モック使用）"""
    # マーカー不要（デフォルトで単体テスト）
    # 外部依存は自動的にモック化される
    ...
```

### 結合テスト

```python
# tests/test_your_module.py

@pytest.mark.integration
def test_new_feature_integration():
    """新機能の結合テスト（実際のHTTP）"""
    # @pytest.mark.integration を付ける
    # 実際の外部依存を使用
    ...

@pytest.mark.integration
class TestRealNetworkAccess:
    """実際のネットワークアクセスを行うテストクラス"""

    @pytest.mark.integration
    def test_real_download(self):
        # 実際のHTTPリクエスト
        ...
```

---

## ❓ よくある質問

### Q: なぜ単体テストと結合テストを分けるのか？

**A:** 開発速度と品質のバランスのためです。

- **単体テスト**: 高速なフィードバック（~1秒）でTDD可能
- **結合テスト**: 本番環境との互換性を確認

両方があることで、開発は高速に、リリースは安全に行えます。

### Q: curlテストとSeleniumテストは別々にすべきでは？

**A:** いいえ、両方とも「実環境依存テスト」として同じカテゴリです。

- どちらも外部依存が必要
- どちらもデフォルトでは実行したくない
- 実行タイミングは同じ（リリース前、定期実行）

違いは依存の種類（HTTP vs Curl vs Browser）のみで、本質的には同じです。

### Q: すべてのテストを毎回実行すべきでは？

**A:** いいえ、状況に応じて使い分けます。

| 状況 | 実行すべきテスト | 理由 |
|------|----------------|------|
| 開発中 | 単体テストのみ | 高速フィードバック |
| コミット前 | 単体テストのみ | CI/CDコスト削減 |
| リリース前 | すべて | 本番互換性確認 |

---

## 🔧 トラブルシューティング

### テストが見つからない

```bash
# 収集されるテストを確認
pytest tests/ --collect-only

# 詳細に表示
pytest tests/ --collect-only -v

# マーカーを確認
pytest --markers
```

### テストが遅い

```bash
# 最も遅いテストを特定
pytest tests/ --durations=10

# 並列実行
pytest tests/ -n auto
```

### モックが効かない

```bash
# フィクスチャを確認
pytest tests/ --fixtures | grep mock

# マーカーを確認
pytest --markers

# 環境変数を確認
echo $INTEGRATION_TEST
```

### 結合テストが失敗する

```bash
# ネットワーク接続を確認
curl https://httpbin.org/get

# curlコマンドを確認
curl --version

# タイムアウトを延長
pytest tests/ -m integration -v --timeout=300
```

---

## 便利なエイリアス

`.bashrc` または `.zshrc` に追加:

```bash
# 単体テスト
alias ptu='pytest tests/'
alias ptuv='pytest tests/ -v'

# 結合テスト
alias pti='pytest tests/ -m integration -v'

# すべてのテスト
alias pta='pytest tests/ -m "" -v'

# カバレッジ付き単体テスト
alias ptc='pytest tests/ --cov=pyscraper --cov-report=html'

# 最後に失敗したテストのみ
alias ptlf='pytest tests/ --lf -v'
```

使用例:
```bash
ptu        # 単体テストを実行
pti        # 結合テストを実行
pta        # すべてのテストを実行
ptc        # カバレッジ測定
```

---

## ✅ まとめ

**単体テストと結合テストの2種類分類により:**

- ✅ **開発速度向上**: 単体テストで高速フィードバック（~1秒）
- ✅ **品質保証**: 結合テストで本番互換性確認
- ✅ **CI/CDコスト削減**: デフォルトは単体テストのみ
- ✅ **明確な戦略**: いつ何を実行するか明確
- ✅ **標準的アプローチ**: 業界標準のテスト分類

この戦略により、高速な開発サイクルと高品質なリリースの両立が可能になります。

---

## 参考リンク

- [pytest 公式ドキュメント](https://docs.pytest.org/)
- [pytest-cov プラグイン](https://pytest-cov.readthedocs.io/)
- [pytest-xdist プラグイン](https://pytest-xdist.readthedocs.io/)
