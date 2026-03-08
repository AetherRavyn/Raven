import time

from playwright.sync_api import sync_playwright

SONG_NAME = "Imagine Dragons Believer"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()

    # Open YouTube
    page.goto("https://www.youtube.com")

    # Wait for search box
    page.wait_for_selector("input#search")

    # Type song name
    page.fill("input#search", SONG_NAME)
    page.press("input#search", "Enter")

    # Wait for results
    page.wait_for_selector("ytd-video-renderer", timeout=15000)

    # Click first video
    page.click("ytd-video-renderer a#thumbnail")

    # Let song play
    time.sleep(60)

    browser.close()
