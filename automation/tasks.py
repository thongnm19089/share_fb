from background_task import background
from automation.models import ObservedPage, FacebookAccount, HotPost
from automation.core.hot_post_scraper import HotPostScraper
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@background(schedule=0)
def scrape_page_background_task(page_id, user_id):
    """
    Background Task chạy bằng `python manage.py process_tasks`
    """
    try:
        page = ObservedPage.objects.get(id=page_id)
        account = FacebookAccount.objects.filter(user_id=user_id, status='live').first()
        
        if not account:
            logger.error(f"Cannot run job for Page {page.name}: User {user_id} has no live FB account.")
            page.scrape_status = 'error'
            page.save()
            return
            
        page.scrape_status = 'running'
        page.save()

        # Init tool
        account_cookies = account.cookies
        scraper = HotPostScraper(user_data_dir=f"fb_browser_profile_{user_id}")
        
        # Stop on existing entries
        existing_urls = list(HotPost.objects.filter(page=page).values_list('post_url', flat=True)[:100])
        
        results = scraper.scrape_page(account_cookies, page.url, stop_urls=existing_urls)
        
        # Save results using update_or_create to preserve history
        for p in results:
            try:
                HotPost.objects.update_or_create(
                    page=page,
                    post_url=p['post_url'],
                    defaults={
                        'content_snippet': p['content_snippet'],
                        'posted_at': p['posted_at'],
                        'likes_count': p['likes'],
                        'comments_count': p['comments'],
                        'shares_count': p['shares']
                    }
                )
            except Exception as e:
                logger.error(f"Error saving hotpost to DB: {e}")

        page.scrape_status = 'completed'
        page.last_scraped_at = timezone.now()
        page.save()
        logger.info(f"Background Task for {page.name} completed successfully.")
        
    except Exception as e:
        logger.error(f"Task Failed: {e}")
        try:
            p = ObservedPage.objects.get(id=page_id)
            p.scrape_status = 'error'
            p.save()
        except:
            pass
