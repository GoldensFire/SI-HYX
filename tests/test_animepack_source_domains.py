# -*- coding: utf-8 -*-
"""Домен определяется по host URL, а не вхождению текста."""
import pytest

from si_hyx_parts.animepack.exact_repeat import _host_matches, _source_keys, pixiv_links


@pytest.mark.parametrize("domain", ["pixiv.net", "fandom.com"])
@pytest.mark.parametrize("url", [
    "https://{domain}/page", "https://www.{domain}/page",
    "https://sub.{domain}:443/page", "https://{domain}./page",
])
def test_real_domains_and_subdomains_are_recognized(domain, url):
    assert _host_matches(url.format(domain=domain), domain)


@pytest.mark.parametrize("domain", ["pixiv.net", "fandom.com"])
@pytest.mark.parametrize("url", [
    "https://evil.example/{domain}/page",
    "https://evil.example/?url=https://{domain}/page",
    "https://{domain}.evil.example/page", "https://fake{domain}/page",
    "https://{domain}@evil.example/page", "ftp://{domain}/page",
    "https://[broken/{domain}/page",
])
def test_domain_in_path_query_userinfo_or_another_host_is_rejected(domain, url):
    assert not _host_matches(url.format(domain=domain), domain)


def test_pixiv_repeat_links_do_not_include_spoofed_urls():
    valid = "https://www.pixiv.net/artworks/123"
    fake = "https://evil.example/pixiv.net/artworks/123"
    assert pixiv_links({("source", valid), ("source", fake)}) == {valid}


def test_only_real_fandom_and_youtube_sources_are_excluded():
    fake = "https://evil.example/fandom.com/page"
    assert _source_keys(["https://a.fandom.com/wiki/X",
                         "https://www.youtube.com/watch?v=123", fake]) == {("source", fake)}
