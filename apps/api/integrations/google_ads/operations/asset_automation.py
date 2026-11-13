# apps/api/integrations/google_ads/operations/asset_automation.py

"""A campaign's asset automation settings, and the pages Google may take videos from."""

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

VIDEO_CRAWL = "AUTOMATED_VIDEO_CRAWL"
# The sites Google reads as an advertiser's social profiles.
_SOCIAL_HOSTS = (
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
)
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def _on(host: str, sites: Sequence[str]) -> bool:
    return any(host == site or host.endswith(f".{site}") for site in sites)


def video_source_platform(url: str) -> str:
    """Google's source platform for a page: a YouTube channel, a social profile, or a landing page."""
    host = (urlsplit(url).hostname or "").lower()
    if _on(host, _YOUTUBE_HOSTS):
        return "YOUTUBE"
    return "SOCIAL" if _on(host, _SOCIAL_HOSTS) else "LANDING_PAGE"


def video_crawl_setting(urls: Sequence[str]) -> dict[str, Any]:
    """The setting that lets Google find videos on these pages."""
    return {
        "assetAutomationType": VIDEO_CRAWL,
        "assetAutomationStatus": "OPTED_IN",
        "automatedVideoCrawlSetting": {
            "automatedVideoCrawlInfos": [
                {"url": url, "sourcePlatform": video_source_platform(url), "enabled": True}
                for url in sorted(urls)
            ]
        },
    }


def live_automation(value: Any) -> list[dict[str, Any]]:
    """The settings Google returned, ordered so equal settings compare equal."""
    settings = []
    for item in value if isinstance(value, list) else ():
        if not isinstance(item, Mapping) or not isinstance(item.get("assetAutomationType"), str):
            continue
        setting = dict(item)
        crawl = setting.get("automatedVideoCrawlSetting")
        infos = crawl.get("automatedVideoCrawlInfos") if isinstance(crawl, Mapping) else None
        pages = [
            # A page Google leaves `enabled` off is one the advertiser hasn't approved.
            {**info, "enabled": info.get("enabled") is True}
            for info in infos or ()
            if isinstance(info, Mapping) and isinstance(info.get("url"), str)
        ]
        if pages:
            pages.sort(key=lambda info: info["url"])
            setting["automatedVideoCrawlSetting"] = {"automatedVideoCrawlInfos": pages}
        else:
            setting.pop("automatedVideoCrawlSetting", None)
        settings.append(setting)
    return sorted(settings, key=lambda setting: setting["assetAutomationType"])


def video_pages(settings: Any) -> list[str]:
    """The pages Google may take videos from now; none when video crawl is off."""
    for setting in live_automation(settings):
        if setting["assetAutomationType"] != VIDEO_CRAWL:
            continue
        if setting.get("assetAutomationStatus") != "OPTED_IN":
            return []
        infos = setting.get("automatedVideoCrawlSetting", {}).get("automatedVideoCrawlInfos", ())
        return [info["url"] for info in infos if info["enabled"]]
    return []


def with_video_pages(settings: Any, urls: Sequence[str]) -> list[dict[str, Any]]:
    """The campaign's whole settings list with video crawl on for these pages, or off for none.

    Google replaces the list on an update, so every other setting is sent back as it is.
    A campaign already on these pages keeps its list unchanged.
    """
    live = live_automation(settings)
    if video_pages(live) == sorted(urls):
        return live
    rest = [setting for setting in live if setting["assetAutomationType"] != VIDEO_CRAWL]
    crawl = (
        video_crawl_setting(urls)
        if urls
        else {"assetAutomationType": VIDEO_CRAWL, "assetAutomationStatus": "OPTED_OUT"}
    )
    return sorted([*rest, crawl], key=lambda setting: setting["assetAutomationType"])
