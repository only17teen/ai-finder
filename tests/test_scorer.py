"""Tests for scoring + categorization (pure) and rescore_all."""
from ai_finder.db import DB, Candidate
from ai_finder.scorer import categorize, rescore_all, score_service


def test_score_full_stack():
    row = {"has_api": 1, "has_referral": 1, "referral_commission": "30%",
           "platforms": "hn,producthunt", "pricing_info": "found",
           "pricing_model": "free tier", "upvotes": 250}
    # 30 + 25 + 20 + 15 + 10 + 5*2 = 110
    assert score_service(row) == 110


def test_score_minimal():
    row = {"has_api": 0, "has_referral": 0, "referral_commission": "",
           "platforms": "hn", "upvotes": 0}
    assert score_service(row) == 0


def test_score_low_commission_no_bonus():
    row = {"has_api": 1, "has_referral": 1, "referral_commission": "10%",
           "platforms": "hn", "upvotes": 0}
    # 30 + 25, no commission bonus (<=20), single platform,
    # + 15 niche bonus (monetizable, 1 platform, <100 upvotes) = 70
    assert score_service(row) == 70


def test_niche_bonus_applies_to_under_the_radar():
    niche = {"has_api": 1, "has_referral": 0, "platforms": "reddit",
             "upvotes": 5}
    # 30 api + 15 niche bonus = 45
    assert score_service(niche) == 45


def test_no_niche_bonus_when_popular_or_multiplatform():
    multi = {"has_api": 1, "platforms": "hn,producthunt", "upvotes": 5}
    assert score_service(multi) == 30 + 15  # multi-platform bonus, no niche
    popular = {"has_api": 1, "platforms": "hn", "upvotes": 500}
    assert score_service(popular) == 30 + 15  # capped popularity, no niche


def test_popularity_bonus_capped():
    a = {"has_api": 0, "platforms": "hn", "upvotes": 1000}  # not monetizable
    assert score_service(a) == 15  # cap, no niche (not monetizable)


def test_categorize():
    assert categorize("CodeWhiz", "an AI coding assistant for developers") == "code"
    assert categorize("Painter", "AI image and art diffusion generator") == "image"
    assert categorize("VoiceGen", "text to speech voice audio") == "audio"
    assert categorize("Mystery", "a thing that does stuff") == "other"


def test_rescore_all_ranks(tmp_path):
    db = DB(tmp_path / "t.db")
    hi, _ = db.upsert_candidate(
        Candidate(url="https://hi.ai", name="CodeBot",
                  description="AI coding agent API", source_platform="hn"))
    db.update_service(hi, has_api=1, has_referral=1,
                      referral_commission="40%", upvotes=300)
    lo, _ = db.upsert_candidate(
        Candidate(url="https://lo.ai", name="Mystery",
                  description="some app", source_platform="hn"))
    n = rescore_all(db)
    assert n == 2
    top = db.top(1)[0]
    assert top["domain"] == "hi.ai"
    assert top["score"] > 0
    assert dict(db.get(hi))["category"] == "code"
    db.close()
