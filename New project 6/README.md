# Morning News Psychology Drafts

毎朝、日本向けニュースから経済・エンタメ・事件/犯罪を中心に10件を選び、心理学・行動心理学の切り口でX向けスレッド案を作ってDiscordへ投稿します。

## 使うもの

- GitHub Actions
- Discord Webhook
- OpenAI API key

## GitHub Secrets

GitHubのリポジトリで `Settings` → `Secrets and variables` → `Actions` を開き、以下を追加してください。

| Name | Value |
| --- | --- |
| `DISCORD_WEBHOOK_URL` | DiscordのWebhook URL |
| `OPENAI_API_KEY` | OpenAI APIキー |

任意で `Variables` に `OPENAI_MODEL` を追加するとモデルを変更できます。未設定時は `gpt-5.2` を使います。

## 実行タイミング

[`.github/workflows/morning-news.yml`](.github/workflows/morning-news.yml) は毎日 08:00 JST に動きます。

手動で試す場合は、GitHubの `Actions` タブから `Morning news psychology drafts` を選び、`Run workflow` を押してください。

## ローカル確認

Discordへ投稿せずに内容だけ確認できます。

```bash
python scripts/morning_news.py --dry-run
```

## 投稿フォーマット

各ニュースは以下の形になります。

```text
1. 経済｜ニュースタイトル
記事: https://...
① ニュース要点 + 感情フック + 理由は↓
② 心理学・行動心理学の概念と具体的な働き
③ 読者が使える見方や行動指針
```

事件・犯罪記事では、憶測、断定、個人攻撃、過度な煽りを避けるようにプロンプトで制御しています。
