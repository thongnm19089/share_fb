import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fb_tool.settings')
django.setup()

from automation.models import FacebookAccount, ObservedPage
from automation.core.hot_post_scraper import HotPostScraper

def run_test():
    account = FacebookAccount.objects.filter(status='live').first()
    if not account:
        print("No live account found in DB.")
        return
        
    print(f"Using account: {account.name} - Cookies length: {len(account.cookies)}")
    
    page = ObservedPage.objects.first()
    if not page:
        print("No observed page found in DB.")
        page_url = "https://www.facebook.com/groups/laptrinhpython" # Default fallback
        print(f"Using fallback page: {page_url}")
    else:
        page_url = page.url
        print(f"Testing scrape on page: {page_url}")
    
    scraper = HotPostScraper(headless=True)
    try:
        def progress(p):
            print(f"Progress: {p}%")
            
        results = scraper.scrape_page(account.cookies, page_url, progress_callback=progress)
        print(f"Scraped {len(results)} posts.")
        for r in results:
            print(r.get('post_url'))
    except Exception as e:
        print(f"Exception during scrape: {e}")

if __name__ == '__main__':
    run_test()
