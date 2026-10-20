# Trello の再現ページ（模型）

Chrome ウェブストアのスクリーンショット素材を撮るために作った、Trello のボード画面とカード詳細の再現ページです。
`store-assets/tools/capture_raw.py` がこのページを `https://trello.com/...` として表示し、本物のトレひろ（リポジトリの拡張機能そのもの）を当てて撮影します。

- 実際の Trello（2026-10-04 時点、build-241517）で測った寸法・色・余白・日本語の文言をもとに、HTML・CSS・JavaScript をすべて自分で書いています。
- Trello / Atlassian のロゴ・ワードマーク・CSS ファイル・アイコン・背景写真・フォントは使っていません。アイコンは `mock.js` で描いた簡単な SVG、フォントは OS の標準フォント（macOS では日本語がヒラギノ角ゴシックで表示されます）、ボードの背景は自作のグラデーションです。
- 内容はすべて架空です（ボード「Webサイト リニューアル」、メンバー 佐藤 美咲／鈴木 健／高橋 さくら）。
- 再現ページ自身は、トレひろが付ける印（拡張専用の data 属性や CSS 変数）を書きも読みもしません。幅の拡張やカードの色付けは、撮影時に読み込んだ本物の拡張機能だけが行います（`capture_raw.py` は、このフォルダのファイルに印の名前が出てこないこと、拡張を読み込む前は印が付かないことも確かめて `raw/manifest.json` に記録します）。

## ファイル

| ファイル | 内容 |
| --- | --- |
| `board.html` | ボード画面（`/b/<id>/<slug>` で返す） |
| `card.html` | ボードの上にカード詳細を開いた画面（`/c/<id>/<slug>` で返す） |
| `mock.css` | 見た目。Trello 標準の制約（下記）もここで再現 |
| `mock.js` | 架空のデータと描画。コメント欄の開閉、カードのクリックでカード詳細へ移動、閉じるボタン |
| `serve.py` | 手元で確かめるための小さなサーバー（下記） |

`board.html` と `card.html` は `/__mock/mock.css` と `/__mock/mock.js` を読み込みます（`/__mock/<path>` はこのフォルダのファイルに対応します）。

## 手元で見る

```sh
python3 store-assets/tools/mock/serve.py
```

ブラウザで次の URL を開きます（拡張を当てていない「Trello 標準」の見た目です）。

- ボード: http://127.0.0.1:8730/b/Mk7Wb2Qa/web-renewal
- カード詳細: http://127.0.0.1:8730/c/Hr8dT0pK/14-top-page-design
- カード詳細（コメント欄を閉じた状態）: http://127.0.0.1:8730/c/Hr8dT0pK/14-top-page-design?comments=closed

`file://` で直接開くと `/__mock/...` が読めないので、このサーバーを使ってください。トレひろのコンテンツスクリプトは `https://trello.com/*` にしか入らないため、拡張を当てた見た目は `capture_raw.py` で確かめます。

## トレひろが頼る目印（実物と同じ入れ子）

ボード:

```
li[data-testid="list-card"]
  div
    div[data-testid="list-card-wrapper"]
      div[data-testid="trello-card"]          白・角丸 8（同じ大きさの白い要素が 3 重）
        div                                   白
          div                                 白・padding 8 12 4（トレひろが塗る要素）
            div > div > button[data-testid="compact-card-label"][data-color]   ラベル（40×8）
            a[data-testid="card-name"][href="/c/<id>/<n>-<slug>"]
            div[data-testid="card-front-badges"]
        div                                   空
```

カード詳細:

```
div#layer-manager-card-back
  div（暗幕 rgba(0,0,0,.75)、fixed）
    div#overlay-contents（上 48px）
      div > div[role="dialog"][data-testid="card-back-name"]   幅 1080px（コメント欄を閉じると 584px）、高さ 100vh − 128px、角丸 12
        div > div > div（白の枠）
          header（高さ 56 + 下線 1px）
          div（main と aside の横並び。overflow hidden）
            main（min-width 460px、flex 1 1 460px）
              section[data-testid="card-back-header"] > hgroup（max-width 544px）
              div（max-width 620px、padding 0 40 16 20）… ボタン行・メンバー／ラベル／期限・説明（横に長い表）・チェックリスト
            div[role="slider"]（幅 8・左右 −4px）
            aside（幅 460px、min-width 460px、背景 #F0F1F2、左に 1px の線）… コメントとアクティビティ
        nav（ダイアログの下 16px に浮く）> div[role="group"]
          button[aria-pressed]「Power-Up」 / button[aria-pressed]「自動化」 / button[data-testid="card-back-activity-button"][role="checkbox"][aria-checked]「コメント」
.atlaskit-portal-container > .atlaskit-portal > div > section[role="dialog"]   「自動化」を押すと body の直下に出る（幅 304、角丸 8）
  section > hgroup（h2「自動化」・編集ボタン）
            ul > li > button × 6（架空のカードボタン。アイコンは黒い図形の data: URL の画像を背景に敷く）
               > button[title="ボタンを追加"]（li に入っていない）
```

コメント欄を閉じた状態は、Trello と同じく main が全幅（`flex: 1 0 100%`）、aside は右へ押し出されて見えなくなります。

「自動化」のポップオーバーは、2026-10-20 にログインした実際の Trello で確かめた振る舞いのうち、トレひろの自動化ボタンが頼るものを再現しています。

- トグルの `aria-pressed` は、クリックした直後ではなく次のマイクロタスクで変わる
- 開くと中の編集ボタンにフォーカスが入る。外を押すか、トグルをもう一度押すと閉じる（Esc でも閉じる。カード詳細は閉じない）
- カードボタンを押すとアイコンが `[data-testid="spinner-wrapper"]` に変わり、0.9 秒後に元に戻って、画面の左下に「成功！」が出る（ポップオーバーは開いたまま）
- カード詳細を開くと、ダイアログ（`tabindex="-1"`）にフォーカスを置く

架空のカードボタンは「レビュー依頼」「確認待ちへ移動」「完了にする」「担当を自分に」「期限を今週末に」「公開前チェックを追加」の 6 個で、押しても何も変わりません（スピナーと「成功！」が出るだけ）。
