from news_provider import parse_gdelt_payload


def test_parse_gdelt_payload_deduplicates_and_scores():
    payload = {
        "articles": [
            {"title": "Company wins major contract", "url": "https://a.example/1", "domain": "a.example", "seendate": "20260714"},
            {"title": "Company faces fraud probe", "url": "https://b.example/2", "domain": "b.example", "seendate": "20260714"},
            {"title": "Duplicate", "url": "https://a.example/1", "domain": "a.example"},
        ]
    }
    result = parse_gdelt_payload(payload, "TEST")
    assert result["available"] is True
    assert result["article_count"] == 2
    assert result["source_count"] == 2
    assert -1 <= result["sentiment"] <= 1


def test_empty_news_is_still_a_completed_check():
    result = parse_gdelt_payload({"articles": []}, "TEST")
    assert result["available"] is True
    assert result["status"] == "no_recent_headlines"


def test_parse_google_news_rss():
    from news_provider import parse_google_news_rss

    xml = b'''<?xml version="1.0"?><rss><channel><item><title>Company reports major contract win</title><link>https://example.com/a</link><pubDate>Tue, 14 Jul 2026 10:00:00 GMT</pubDate><source>Example</source></item></channel></rss>'''
    result = parse_google_news_rss(xml, "TEST")
    assert result["provider"] == "google_news_rss"
    assert result["article_count"] == 1
    assert result["sentiment"] > 0
