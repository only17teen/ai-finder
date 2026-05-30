"""Tests for linux.do collector pure parsers (no browser)."""
from ai_finder.collectors.linux_do import (
    ai_topic_ids,
    extract_topic_links,
    parse_discourse_json,
)


def test_parse_discourse_json_from_rendered():
    html = '<html><body><pre>{"a": 1, "b": [2, 3]}</pre></body></html>'
    assert parse_discourse_json(html) == {"a": 1, "b": [2, 3]}


def test_parse_discourse_json_graceful_on_non_json():
    # Cloudflare challenge page -> no usable JSON -> {}
    assert parse_discourse_json("<html><body>Just a moment...</body></html>") == {}
    assert parse_discourse_json("") == {}


def test_ai_topic_ids_filters():
    latest = {"topic_list": {"topics": [
        {"id": 1, "title": "现在性价比最高的GPT是哪个"},
        {"id": 2, "title": "今天天气不错"},
        {"id": 3, "title": "New LLM API gateway"},
    ]}}
    ids = ai_topic_ids(latest)
    assert {i for i, _ in ids} == {1, 3}


def test_extract_topic_links_keeps_external_ai():
    topic = {"post_stream": {"posts": [
        {"cooked": '<p>试试 <a href="https://geekai.co">GeekAI</a> '
                   '和 <a href="https://github.com/x/y">repo</a> '
                   '<a href="https://cdn.x/a.png">img</a></p>'},
        {"cooked": '<a href="https://linux.do/t/123">internal</a>'},
    ]}}
    cands = extract_topic_links(topic, "GPT API 分享")
    domains = {c.domain for c in cands}
    assert "geekai.co" in domains
    assert "github.com" not in domains   # noise
    assert "linux.do" not in domains      # self
    assert not any(d.endswith(".png") for d in domains)  # asset


def test_extract_topic_links_dedup():
    topic = {"post_stream": {"posts": [
        {"cooked": '<a href="https://dup.ai/1">x</a>'},
        {"cooked": '<a href="https://dup.ai/2">y</a>'},
    ]}}
    cands = extract_topic_links(topic, "t")
    assert [c.domain for c in cands].count("dup.ai") == 1


def test_extract_topic_links_bare_domain():
    # services shared as plain text, not <a> links
    topic = {"post_stream": {"posts": [
        {"cooked": "<p>推荐这个免费站 chyqd.com 很好用</p>"},
        {"cooked": "<p>还有 my-llm.dev 也不错，网盘 pan.baidu.com 跳过</p>"},
    ]}}
    cands = extract_topic_links(topic, "GPT 公益站分享")
    domains = {c.domain for c in cands}
    assert "chyqd.com" in domains
    assert "my-llm.dev" in domains
    assert "pan.baidu.com" not in domains  # netdisk filtered
