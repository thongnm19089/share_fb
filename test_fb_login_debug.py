import sys
import logging
from playwright.sync_api import sync_playwright

def test(uid, pwd):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            viewport={'width': 1366, 'height': 900},
            locale='vi-VN'
        )
        page = context.new_page()
        page.goto('https://www.facebook.com/login', wait_until='domcontentloaded')
        
        # Fill
        page.fill('input[name="email"]', uid)
        page.fill('input[name="pass"]', pwd)
        
        # Force submit button to be enabled
        page.evaluate('document.querySelectorAll("input[type=submit], button[type=submit], button[name=login]").forEach(b => b.removeAttribute("disabled"))')
        
        print("Buttons after force enable:")
        for el in page.locator('button').all():
            print(" -", el.get_attribute('name'), el.text_content())
        for el in page.locator('input[type="submit"]').all():
            print(" - input submit", el.get_attribute('value'))
            
        browser.close()

if __name__ == "__main__":
    test(sys.argv[1], sys.argv[2])
