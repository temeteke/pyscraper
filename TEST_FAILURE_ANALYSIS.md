# テスト失敗分析と改善提案

## 現状の問題点

### 失敗テストの分類

**合計50テスト失敗** （全体の約26%）

#### 1. 外部HTTP依存の失敗（47テスト）

**httpbin.org 依存（19テスト）**
- WebFile: read, seek, download系テスト（15テスト）
- 原因: `403 Forbidden` エラー
- 影響: Range request、進捗コールバック、ダウンロード機能のテスト不可

**temeteke.github.io 依存（24テスト）**
- WebPageRequests: XPath、HTML取得系テスト（13テスト）
- WebPageCurl: 同様のテスト（11テスト）
- 原因: `403 Access denied` エラー
- 影響: ページパース、要素取得のテスト不可

**URL変更テスト（4テスト）**
- リダイレクトのテスト
- 原因: 同じく外部サービスへのアクセス拒否

#### 2. FFmpeg依存の失敗（4テスト）

- HlsFile: download系テスト（4テスト）
- 原因: `FileNotFoundError: 'ffmpeg'`
- 影響: HLS動画のマージ機能がテスト不可

---

## 改善案の比較検討

### 案1: モックベースのユニットテスト（推奨）

#### 概要
外部依存をモック化し、HTTPレスポンスをシミュレート

#### メリット
- ✅ **外部依存ゼロ**: ネットワークやサービス状態に影響されない
- ✅ **高速**: 実際のHTTPリクエストなし
- ✅ **再現性**: 常に同じ結果
- ✅ **テスト容易**: エッジケース（タイムアウト、403等）を簡単にテスト可能
- ✅ **CI/CD対応**: どの環境でも動作
- ✅ **即座に実装可能**: コード変更のみで対応可能

#### デメリット
- ⚠️ 実際のHTTPクライアントの動作は検証できない
- ⚠️ モックコードの記述が必要（初期工数）

#### 実装例
```python
from unittest.mock import Mock, patch
import pytest

def test_read_0_with_mock(webfile):
    # レスポンスをモック
    mock_response = Mock()
    mock_response.status_code = 206
    mock_response.headers = {
        'Content-Range': 'bytes 0-127/1024',
        'Content-Type': 'application/octet-stream'
    }
    mock_response.content = b'x' * 128

    with patch.object(webfile.session, 'get', return_value=mock_response):
        with webfile:
            webfile.seek(0)
            data = webfile.read(128)
            assert len(data) == 128
```

#### 工数見積もり
- **モック実装**: 8-12時間
- **既存テストの書き換え**: 4-6時間
- **合計**: 12-18時間

---

### 案2: ローカルテストサーバー構築

#### 概要
pytest-httpdやFlaskでローカルHTTPサーバーを立ち上げ

#### メリット
- ✅ **実際のHTTP通信**: 本物のHTTPクライアント動作を検証
- ✅ **外部依存なし**: ローカルで完結
- ✅ **柔軟性**: レスポンスを自由にカスタマイズ可能

#### デメリット
- ⚠️ **実装コスト高**: サーバー実装とテストデータ準備が必要
- ⚠️ **保守コスト**: テストサーバーのメンテナンスが必要
- ⚠️ **複雑性**: ポート管理、起動/停止の制御が必要

#### 実装例
```python
import pytest
from flask import Flask, send_file

@pytest.fixture(scope="session")
def test_server():
    app = Flask(__name__)

    @app.route('/range/<int:size>')
    def range_endpoint(size):
        # Range requestに対応
        ...

    server = threading.Thread(target=app.run, kwargs={'port': 5555})
    server.daemon = True
    server.start()
    yield "http://localhost:5555"
```

#### 工数見積もり
- **サーバー実装**: 16-20時間
- **テストデータ準備**: 4-6時間
- **テスト書き換え**: 6-8時間
- **合計**: 26-34時間

---

### 案3: VCR.py（リクエスト記録・再生）

#### 概要
実際のHTTPリクエスト/レスポンスを記録し、再生

#### メリット
- ✅ **初回は実HTTP**: 最初は実際のサービスと通信
- ✅ **2回目以降は高速**: キャッシュから再生
- ✅ **リアルなレスポンス**: 実際のサービスの応答を保存

#### デメリット
- ⚠️ **初回の外部依存**: 記録時は外部サービスが必要
- ⚠️ **カセットの管理**: YAMLファイルの保守が必要
- ⚠️ **現在は動作不可**: httpbin.orgが403を返しているため記録できない

#### 実装例
```python
import vcr

@vcr.use_cassette('fixtures/vcr_cassettes/webfile_read.yaml')
def test_read_0(webfile):
    with webfile:
        data = webfile.read(128)
        assert len(data) == 128
```

#### 工数見積もり
- **VCR.py導入**: 2-3時間
- **カセット記録**: 3-4時間（外部サービスが利用可能な場合）
- **テスト書き換え**: 4-5時間
- **合計**: 9-12時間

**⚠️ 注意**: 現在は外部サービスが403を返すため実施不可

---

### 案4: Docker環境でFFmpeg含む統合環境構築

#### 概要
Dockerコンテナでテスト環境を統一化

#### メリット
- ✅ **環境統一**: 全ての依存関係を含む
- ✅ **FFmpeg対応**: コンテナにインストール
- ✅ **CI/CD対応**: Dockerイメージで統一

#### デメリット
- ⚠️ **HTTP問題は未解決**: 外部サービス依存は残る
- ⚠️ **Docker必須**: 開発者全員がDockerを使う必要
- ⚠️ **実装コスト**: Dockerfile作成とCI設定

#### 実装例
```dockerfile
FROM python:3.11
RUN apt-get update && apt-get install -y ffmpeg
COPY requirements.txt .
RUN pip install -r requirements.txt
```

#### 工数見積もり
- **Dockerfile作成**: 2-3時間
- **CI/CD設定**: 3-4時間
- **合計**: 5-7時間

**⚠️ 注意**: 外部HTTP依存は別途対応が必要

---

### 案5: pytest.mark.skip で外部依存テストを条件付きスキップ

#### 概要
外部サービスが利用不可の場合はテストをスキップ

#### メリット
- ✅ **即座に実装可能**: 1-2時間で完了
- ✅ **最小限の変更**: 既存テストにデコレータ追加のみ

#### デメリット
- ❌ **問題の先送り**: 根本的な解決にならない
- ❌ **テストカバレッジ低下**: 外部依存機能がテストされない

#### 実装例
```python
import pytest
import requests

def check_httpbin():
    try:
        r = requests.get("https://httpbin.org/get", timeout=2)
        return r.status_code == 200
    except:
        return False

httpbin_available = pytest.mark.skipif(
    not check_httpbin(),
    reason="httpbin.org is not available"
)

@httpbin_available
def test_read_0(webfile):
    ...
```

#### 工数見積もり
- **デコレータ実装**: 1-2時間

---

## 推奨方針

### 短期（今すぐ実施）- 案1を採用

**理由**:
1. ✅ 最もコスパが良い（12-18時間で完了）
2. ✅ 外部依存を完全に排除
3. ✅ CI/CD対応が容易
4. ✅ リファクタリング前のテスト整備として最適
5. ✅ テストの高速化にも貢献

**実装ステップ**:
1. **Phase 1**: WebFileのモック化（4-5時間）
   - Range requestのモック
   - Download系のモック

2. **Phase 2**: WebPageのモック化（4-5時間）
   - HTMLレスポンスのモック
   - XPath動作の検証

3. **Phase 3**: HlsFileのモック化（4-6時間）
   - FFmpegコマンドのモック
   - m3u8パースの検証

### 中期（リファクタリング後）- 案4を併用

**理由**:
- Docker環境でFFmpegを含む統合テストを実施
- CI/CDでの自動テストを完全化

### 長期（余力があれば）- 案2を追加

**理由**:
- 統合テストとして実際のHTTP通信を検証
- モックでカバーできない部分を補完

---

## 案1の詳細実装計画

### Step 1: pytest-mockの導入

```bash
pip install pytest-mock
```

### Step 2: ベースモックフィクスチャの作成

```python
# tests/conftest.py

import pytest
from unittest.mock import Mock

@pytest.fixture
def mock_http_response():
    """HTTPレスポンスのモックファクトリー"""
    def _make_response(status_code=200, content=b"", headers=None):
        response = Mock()
        response.status_code = status_code
        response.content = content
        response.headers = headers or {}
        response.raise_for_status = Mock()
        if 400 <= status_code < 600:
            from requests.exceptions import HTTPError
            response.raise_for_status.side_effect = HTTPError()
        return response
    return _make_response

@pytest.fixture
def mock_range_response(mock_http_response):
    """Range requestのレスポンスモック"""
    def _make(start=0, end=127, total=1024):
        content = b'x' * (end - start + 1)
        headers = {
            'Content-Range': f'bytes {start}-{end}/{total}',
            'Accept-Ranges': 'bytes'
        }
        return mock_http_response(206, content, headers)
    return _make
```

### Step 3: 既存テストの書き換え例

```python
# tests/test_webfile.py

def test_read_0_mocked(mocker, url, filename, mock_range_response):
    """モックを使ったtest_read_0の書き換え"""
    wf = WebFile(url, filename=filename)

    # session.getをモック
    mock_get = mocker.patch.object(wf.session, 'get')
    mock_get.return_value = mock_range_response(0, 127, 1024)

    with wf:
        wf.seek(0)
        data = wf.read(128)
        assert len(data) == 128
        assert data == b'x' * 128
```

---

## FFmpeg問題の対処

### オプションA: FFmpegコマンドをモック化

```python
@pytest.fixture
def mock_ffmpeg(mocker):
    """FFmpegコマンドのモック"""
    mock_run = mocker.patch('subprocess.run')
    mock_run.return_value = Mock(returncode=0, stdout=b'', stderr=b'')
    return mock_run

def test_hls_download_with_mock(hls_file, mock_ffmpeg):
    f = hls_file.download()
    assert f.exists()
    mock_ffmpeg.assert_called_once()
```

### オプションB: pytest.mark.skipif でFFmpeg不在時スキップ

```python
import shutil

ffmpeg_available = pytest.mark.skipif(
    shutil.which('ffmpeg') is None,
    reason="FFmpeg is not installed"
)

@ffmpeg_available
def test_hls_download_real(hls_file):
    f = hls_file.download()
    assert f.exists()
```

---

## 期待される効果

### 案1実施後

**改善されるテスト**:
- WebFile: 19テスト ✅
- WebPage: 24テスト ✅
- HlsFile: 4テスト ✅
- **合計**: 47テスト

**テスト成功率**:
- 現在: 80/157 = **51%**
- 実施後: 127/157 = **81%** (+30%向上)

**副次的効果**:
- テスト実行時間の短縮（ネットワークI/O削減）
- CI/CDでの安定性向上
- 開発者体験の向上（ローカルテストの高速化）

---

## まとめ

### 推奨実装順序

1. **今すぐ**: 案1（モックベースのユニットテスト）- 12-18時間
2. **リファクタリング後**: 案4（Docker環境）- 5-7時間
3. **余力があれば**: 案2（ローカルテストサーバー）- 26-34時間

### 最優先アクション

✅ **モックベースのテスト整備を実施**
- リファクタリングの安全性が大幅に向上
- テストの信頼性と速度が向上
- 外部依存の問題を根本的に解決
# テスト改善案の比較表

## 5つの改善案の比較

| 項目 | 案1: モック | 案2: ローカルサーバー | 案3: VCR.py | 案4: Docker | 案5: Skip |
|------|------------|---------------------|-------------|------------|-----------|
| **外部依存排除** | ✅ 完全 | ✅ 完全 | ⚠️ 初回のみ必要 | ❌ 残る | ❌ 残る |
| **実装工数** | ⭐⭐⭐ 12-18h | ⭐ 26-34h | ⭐⭐ 9-12h* | ⭐⭐⭐ 5-7h | ⭐⭐⭐⭐⭐ 1-2h |
| **テスト速度** | ✅ 高速 | ⚠️ 中速 | ✅ 高速 | ⚠️ 中速 | ✅ 高速 |
| **保守コスト** | ⭐⭐⭐ 低 | ⭐ 高 | ⭐⭐ 中 | ⭐⭐ 中 | ⭐⭐⭐ 低 |
| **CI/CD対応** | ✅ 完璧 | ✅ 良好 | ✅ 良好 | ✅ 完璧 | ⚠️ 不完全 |
| **即座に実施可能** | ✅ はい | ✅ はい | ❌ いいえ** | ✅ はい | ✅ はい |
| **テストカバレッジ** | ✅ 高 | ✅ 最高 | ✅ 高 | ✅ 高 | ❌ 低下 |
| **実HTTP検証** | ❌ なし | ✅ あり | ✅ あり | ✅ あり | ⚠️ 条件付き |
| **FFmpeg対応** | ✅ モック可 | ⚠️ 別途必要 | ⚠️ 別途必要 | ✅ 内包 | ❌ なし |
| **推奨度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ |

*現在は外部サービスが403を返すため実施不可
**記録用のHTTPアクセスが現在不可能

## 組み合わせ推奨パターン

### パターンA: 最速アプローチ（推奨）
1. **今**: 案1（モック）- 12-18時間
2. **後**: 案4（Docker）- 5-7時間
- **合計**: 17-25時間
- **カバレッジ**: 81% → 最高
- **信頼性**: ★★★★★

### パターンB: 完璧主義アプローチ
1. **今**: 案1（モック）- 12-18時間
2. **後**: 案2（ローカルサーバー）- 26-34時間
3. **最後**: 案4（Docker）- 5-7時間
- **合計**: 43-59時間
- **カバレッジ**: 81% → 最高
- **信頼性**: ★★★★★
- **統合テスト**: 完璧

### パターンC: 応急処置（非推奨）
1. **今**: 案5（Skip）- 1-2時間
- **合計**: 1-2時間
- **カバレッジ**: 51% → 変わらず
- **信頼性**: ★★
- **問題**: 根本解決なし

## スコアリング

各案を以下の基準でスコアリング（10点満点）:

| 案 | 実装容易性 | 効果 | 保守性 | CI/CD | 合計 |
|----|-----------|------|--------|-------|------|
| 案1: モック | 8 | 9 | 9 | 10 | **36/40** ⭐⭐⭐⭐⭐ |
| 案2: ローカルサーバー | 4 | 10 | 6 | 9 | **29/40** ⭐⭐⭐ |
| 案3: VCR.py | 3* | 8 | 7 | 9 | **27/40** ⭐⭐ |
| 案4: Docker | 8 | 7 | 7 | 10 | **32/40** ⭐⭐⭐⭐ |
| 案5: Skip | 10 | 2 | 8 | 3 | **23/40** ⭐ |

*現在実施不可のため低評価

## 結論

### 最優先: 案1（モックベースのユニットテスト）

**理由**:
1. ✅ コストパフォーマンスが最高（12-18時間で47テスト改善）
2. ✅ 外部依存を完全排除
3. ✅ CI/CDで安定動作
4. ✅ テスト高速化
5. ✅ リファクタリング前の準備として最適

**即座に着手可能な具体的な実装内容**:
- `tests/conftest.py`にモックフィクスチャを追加
- `test_webfile.py`の47テストをモック化
- `test_hlsfile.py`のFFmpegをモック化
- 既存のテストロジックは変更せず、HTTPレスポンスのみモック

**期待される効果**:
- テスト成功率: 51% → **81%** (30%向上)
- 実行時間: 約10秒 → 約2秒（推定）
- CI/CDでの安定性: 大幅向上
