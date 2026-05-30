# AI Finder

[![tests](https://github.com/only17teen/ai-finder/actions/workflows/tests.yml/badge.svg)](https://github.com/only17teen/ai-finder/actions/workflows/tests.yml)

Discover **niche AI services with APIs and referral programs** (like geekai.co) by
crawling sources the mainstream crowd ignores — Chinese/Japanese/Korean dev
communities, European directories, FOSS/self-hosted hubs, and ultra-early launch
platforms. Verifies each site for an API + affiliate program, scores it, stores it
in SQLite, and can notify you on Telegram.

## Sources (13 collectors)

| Collector | Coverage |
|-----------|----------|
| `hackernews` | Show HN (Firebase API) |
| `linux_forums` | LWN, Phoronix, ItsFOSS |
| `apify_sources` | ProductHunt + IndieHackers (needs Apify token) |
| `ai_directories` | theresanaiforthat / toolify / futurepedia (two-level crawl) |
| `github_trending` | trending AI repos → their SaaS homepages |
| `hidden_gems` | 🇨🇳 ai-bot.cn, aigc.cn · 🇫🇷 aixploria, intelligence-artificielle · rankmyai (CN/KR/JP/TW/SG) · HuggingFace Spaces |
| `foss_sources` | Lobsters, Slashdot, HN-newest, HN Algolia, self-hosted lists |
| `forums` | Lemmy (federated FOSS) + dev.to |
| `asian_dev` | 🇨🇳 V2EX · 🇯🇵 Qiita, Zenn |
| `launch` | MicroLaunch, TinyLaunch (days-old indie launches) |
| `reddit_rss` | LocalLLaMA, selfhosted, StableDiffusion, ollama, comfyui, … |
| `intl_forums` | 🇰🇷 Korean GeekNews (news.hada.io) |
| `telegram_channels` | public AI channels (needs Telegram API creds) |

## Pipeline

```
collect (12 sources, concurrent) → dedup by domain → verify (1 shared browser)
→ score + categorize → SQLite → CSV export + Telegram alerts
```

- **Verification** (`verifier.py`): detects API docs, referral program, pricing, and
  the commission %. Bilingual — English **and** Chinese patterns (开放平台, 分销, 返佣…).
- **Scoring** (`scorer.py`): +30 API, +25 referral, +20 commission>20%, +15 multi-platform,
  +10 free tier, +5/100 upvotes (capped at +15). **Niche bonus** (+15) for monetizable
  services that are still under the radar (single platform, <100 upvotes) — keeps niche
  finds from being buried by viral generic tools.
- **Noise filtering** (`db.py`): drops infra/news/social hosts and non-public hosts
  (localhost, IPs, TLD-less) globally.

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
python -m playwright install chromium     # for JS-rendered sites
cp config.toml.example config.toml        # then edit / set env vars

python -m ai_finder.main run              # full pipeline (all enabled sources)
python -m ai_finder.main run --source reddit
python -m ai_finder.main sources          # list collectors and on/off state
python -m ai_finder.main top --limit 30   # highest-scoring finds
python -m ai_finder.main export --out ai_services.csv          # API + referral
python -m ai_finder.main export --format md --out top.md       # Markdown table
python -m ai_finder.main export --format json --all --min-score 30  # JSON, API-only
python -m ai_finder.main status
python -m ai_finder.main verify --url geekai.co
python -m ai_finder.main search --keyword video --category video --min-score 30
python -m ai_finder.main recheck --max-age-days 7   # re-verify stale services
python -m ai_finder.main history --domain geekai.co # change log
python -m ai_finder.main prune                      # drop unreachable services
python -m ai_finder.main digest --limit 10          # Telegram top-N digest
python -m ai_finder.main links --limit 25           # copy-friendly referral+API URLs
python -m ai_finder.main report                     # per-source collector stats
```

Cron (every 6h):
```cron
0 */6 * * * cd /path/to/ai-finder && .venv/bin/python -m ai_finder.main run
```

## Configuration

Edit `config.toml` (toggle sources, rate limits, score threshold). **Secrets** are read
from env vars and never committed:

| Env var | Used by |
|---------|---------|
| `APIFY_TOKEN` | ProductHunt / IndieHackers |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | notifications |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` | reading public channels |

## Tests

```bash
python -m pytest        # 132 tests
```

Parsing/scoring logic is written as pure functions, unit-tested with fixtures (no
network). Live fetches are best-effort and degrade gracefully.

## Ethics

Only public content. Respects rate limits (per-domain throttle + retry/backoff).
Tokens via env vars, never hardcoded.
