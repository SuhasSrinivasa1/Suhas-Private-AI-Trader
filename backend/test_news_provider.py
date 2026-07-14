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
