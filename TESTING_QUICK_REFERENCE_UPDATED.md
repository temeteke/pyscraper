# テスト実行クイックリファレンス

## 基本コマンド

```bash
# 📦 単体テスト（デフォルト・推奨）
pytest tests/                           # すべての単体テスト（130テスト）
pytest tests/test_webfile.py           # 特定ファイル
pytest tests/ -k download              # キーワードフィルタ

# 🌐 結合テスト
pytest tests/ -m integration -v        # 結合テストのみ（88テスト）
INTEGRATION_TEST=1 pytest tests/ -v    # 環境変数で制御

# 🔬 すべて実行
pytest tests/ -m "" -v                 # 単体 + 結合（218テスト）
```

---

## テスト種別

| 種別 | コマンド | テスト数 | 実行時間 |
|------|---------|---------|---------|
| **単体テスト** | `pytest tests/` | 130 | < 2秒 |
| **結合テスト** | `pytest tests/ -m integration` | 88 | 数分 |
| **すべて** | `pytest tests/ -m ""` | 218 | 数分 |

---

## マーカー使用

### 単体テスト（デフォルト）
```python
# マーカー不要（デフォルトで単体テスト）
def test_something():
    # モックを使用
    ...
```

### 結合テスト
```python
# @pytest.mark.integration を付ける
@pytest.mark.integration
def test_real_http():
    # 実際のHTTPリクエスト
    ...

@pytest.mark.integration
class TestBrowserAutomation:
    # ブラウザ自動化テスト
    ...
```

---

## シーン別コマンド

| シーン | コマンド | 実行時間 |
|--------|---------|---------|
| **日常開発** | `pytest tests/` | < 2秒 |
| **コミット前** | `pytest tests/ -v` | < 2秒 |
| **リリース前** | `pytest tests/ -m ""` | 数分 |
| **CI/CD (PR)** | `pytest tests/` | < 2秒 |
| **CI/CD (main)** | `pytest tests/ -m integration` | 数分 |

---

## よく使うオプション

### 基本オプション
```bash
# 詳細出力
pytest tests/ -v                       # verbose
pytest tests/ -vv                      # more verbose

# 失敗時のデバッグ
pytest tests/ -x                       # 最初の失敗で停止
pytest tests/ -s                       # 標準出力を表示
pytest tests/ --lf                     # 最後に失敗したテストのみ
pytest tests/ --pdb                    # 失敗時にデバッガ起動

# 静かに実行
pytest tests/ -q                       # quiet
```

### カバレッジ
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

## 特定のテストを実行

### ファイル指定
```bash
# 単一ファイル
pytest tests/test_webfile.py

# 複数ファイル
pytest tests/test_webfile.py tests/test_hlsfile.py

# ディレクトリ
pytest tests/integration/
```

### クラス/関数指定
```bash
# 特定のクラス
pytest tests/test_webfile.py::TestWebFile

# 特定のテスト
pytest tests/test_webfile.py::TestWebFile::test_download_unlink

# パターンマッチ
pytest tests/ -k download              # 名前に"download"を含むテスト
pytest tests/ -k "not slow"            # "slow"を含まないテスト
```

### マーカー指定
```bash
# 結合テストのみ
pytest tests/ -m integration

# 結合テストを除外（デフォルト動作）
pytest tests/ -m "not integration"

# 複数マーカー
pytest tests/ -m "integration and slow"
pytest tests/ -m "integration or slow"
```

---

## 環境変数

```bash
# 結合テストを有効化
INTEGRATION_TEST=1 pytest tests/

# 通常の単体テスト（デフォルト）
INTEGRATION_TEST=0 pytest tests/  # または省略
pytest tests/
```

---

## トラブルシューティング

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

# 遅いテストをスキップ
pytest tests/ -m "not slow"
```

### 特定のテストだけ失敗
```bash
# 最後に失敗したテストのみ再実行
pytest tests/ --lf

# 失敗したテストのみ実行（成功したらすべて実行）
pytest tests/ --ff

# 詳細なスタックトレース
pytest tests/ --tb=long

# 簡潔なスタックトレース
pytest tests/ --tb=short

# スタックトレースなし
pytest tests/ --tb=no
```

---

## CI/CD での使用

### GitHub Actions

```yaml
# Pull Request: 単体テストのみ
- name: Run unit tests
  run: pytest tests/ -v --cov=pyscraper

# mainブランチ: 単体 + 結合
- name: Run all tests
  run: pytest tests/ -m integration -v
  if: github.ref == 'refs/heads/main'

# リリース: すべて
- name: Run all tests
  run: pytest tests/ -m "" -v
  if: startsWith(github.ref, 'refs/tags/')
```

### ローカルでCI環境を再現

```bash
# PRと同じ条件（単体テストのみ）
pytest tests/ -v --cov=pyscraper

# mainマージ後と同じ条件（結合テスト含む）
pytest tests/ -m integration -v

# リリース前と同じ条件（すべて）
pytest tests/ -m "" -v
```

---

## 便利なエイリアス

### .bashrc / .zshrc に追加

```bash
# 単体テスト
alias ptu='pytest tests/'

# 単体テスト（詳細）
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
ptuv       # 単体テスト（詳細出力）
pti        # 結合テストを実行
pta        # すべてのテストを実行
ptc        # カバレッジ測定
```

---

## まとめ

### 最もよく使うコマンド

```bash
# 1. 日常開発（最頻出）
pytest tests/

# 2. コミット前確認
pytest tests/ -v

# 3. リリース前確認
pytest tests/ -m "" -v

# 4. デバッグ
pytest tests/test_specific.py::test_func -vv -s

# 5. カバレッジ確認
pytest tests/ --cov=pyscraper --cov-report=html
```

### 覚えておくべきポイント

- ✅ **デフォルト = 単体テスト**: `pytest tests/` だけで日常開発OK
- ✅ **結合テストは明示的**: `-m integration` で実行
- ✅ **すべて実行は `-m ""`**: マーカーフィルタを無効化
- ✅ **環境変数でも制御可**: `INTEGRATION_TEST=1`

---

## 詳細ドキュメント

- **[TEST_STRATEGY_UPDATED.md](./TEST_STRATEGY_UPDATED.md)** - 戦略的な概要
- **[TESTING_GUIDE.md](./TESTING_GUIDE.md)** - 詳細な使い方ガイド
- **[TEST_LIST.md](./TEST_LIST.md)** - 全テスト一覧
- **[tests/integration/README.md](./tests/integration/README.md)** - 結合テスト詳細
