"""URL / domain normalization and noise filtering.

Pure utilities, no I/O. Kept separate from storage so collectors and the
verifier can depend on domain logic without pulling in SQLite.
"""
from __future__ import annotations

import tldextract

# Subdomain labels that denote the same service (collapsed for dedup).
_COMMON_SUBDOMAINS = {
    "www", "app", "apps", "docs", "doc", "api", "dev", "developer",
    "developers", "get", "go", "my", "beta", "dashboard", "console",
    "portal", "platform", "try", "start", "home", "web",
}

# Offline extractor backed by the bundled Public Suffix List snapshot.
_TLD = tldextract.TLDExtract(suffix_list_urls=())


def domain_of(url: str) -> str:
    """Normalize a URL to its registrable host using the Public Suffix List,
    with common service subdomains stripped (www/app/docs/api/...).

    - Multi-level suffixes are handled correctly (``foo.com.cn`` →
      ``foo.com.cn``, ``app.foo.com.cn`` → ``foo.com.cn``).
    - Near-duplicates collapse (``app.klingai.com`` → ``klingai.com``).
    - Meaningful subdomains are kept (``jimeng.jianying.com`` stays whole).
    """
    if "://" not in url:
        url = "http://" + url
    ext = _TLD(url)
    registrable = ext.top_domain_under_public_suffix  # e.g. foo.com.cn
    if not registrable:
        # no recognizable public suffix — fall back to the raw host
        from urllib.parse import urlparse
        return (urlparse(url).hostname or "").lower()
    # strip only the *leading* common-service labels from the subdomain part
    sub_labels = [s for s in ext.subdomain.split(".") if s]
    while sub_labels and sub_labels[0] in _COMMON_SUBDOMAINS:
        sub_labels.pop(0)
    host = ".".join(sub_labels + [registrable])
    return host.lower()


# Generic/infra domains that are never the niche AI service we want to track.
NOISE_DOMAINS = {
    "github.com", "gitlab.com", "bitbucket.org", "google.com", "youtube.com",
    "youtu.be", "twitter.com", "x.com", "facebook.com", "linkedin.com",
    "instagram.com", "reddit.com", "wikipedia.org", "medium.com",
    "substack.com", "apple.com", "microsoft.com", "amazon.com",
    "producthunt.com", "news.ycombinator.com",
}

# News/media outlets — they report on AI, they aren't the service itself.
NEWS_DOMAINS = {
    "arstechnica.com", "techcrunch.com", "theverge.com", "wired.com",
    "nytimes.com", "bbc.com", "cnbc.com", "fastcompany.com", "gizmodo.com",
    "theinformation.com", "harvardmagazine.com", "lesswrong.com", "ign.com",
    "store.steampowered.com", "steamcommunity.com", "gadgetreview.com",
    "legiscan.com", "bloomberg.com", "reuters.com", "wsj.com", "forbes.com",
    "businessinsider.com", "engadget.com", "venturebeat.com", "zdnet.com",
    "cnet.com", "axios.com", "aljazeera.com", "theguardian.com", "cnn.com",
    "tomshardware.com", "sfstandard.com", "tiktok.com", "arxiv.org",
    "404media.co", "theregister.com", "thurrott.com", "neowin.net",
    "scientificamerican.com", "boredpanda.com", "nature.com",
    "spectrum.ieee.org", "phys.org", "sciencedaily.com",
}


def is_noise_domain(domain: str) -> bool:
    """True for generic/infra/news hosts that aren't a discoverable service."""
    if not domain:
        return True
    # Non-public hosts: localhost, IPs, systemd targets, no-dot/TLD-less names.
    if domain in ("localhost",) or domain.startswith("127.") or \
            domain.replace(".", "").isdigit() or "." not in domain or \
            domain.endswith((".local", ".target", ".service", ".lan")):
        return True
    return any(domain == n or domain.endswith("." + n)
               for n in NOISE_DOMAINS | NEWS_DOMAINS)
