from background_task import background
from automation.models import ObservedPage, FacebookAccount, HotPost
from automation.core.hot_post_scraper import HotPostScraper
from django.utils import timezone
import logging
import threading
import signal

logger = logging.getLogger(__name__)

# Thời gian tối đa cho 1 lần quét 1 page (giây). Sau thời gian này tự động abort.
SCRAPE_TIMEOUT_SECONDS = 600  # 10 phút


class _TimeoutError(Exception):
    pass


def _run_with_timeout(fn, timeout):
    """Chạy fn() trong thread riêng với timeout. Raise _TimeoutError nếu quá hạn."""
    result = [None]
    exc = [None]

    def target():
        try:
            result[0] = fn()
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise _TimeoutError(f"Scrape timed out after {timeout}s")
    if exc[0]:
        raise exc[0]
    return result[0]


@background(schedule=0)
def scrape_page_background_task(page_id, user_id):
    """
    Background Task chạy bằng `python manage.py process_tasks`
    Tự động abort nếu quét quá SCRAPE_TIMEOUT_SECONDS giây.
    """
    page = None
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

        account_cookies = account.cookies
        scraper = HotPostScraper(headless=True)

        from datetime import timedelta
        twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        existing_urls = list(
            HotPost.objects.filter(page=page, posted_at__lt=twenty_four_hours_ago)
            .order_by('-posted_at')
            .values_list('post_url', flat=True)[:100]
        )

        def do_scrape():
            return scraper.scrape_page(
                account_cookies, page.url,
                stop_urls=existing_urls,
                max_days=1.5,
                max_posts=50
            )

        # ── Chạy với timeout tổng thể ────────────────────────────────────────
        results = _run_with_timeout(do_scrape, SCRAPE_TIMEOUT_SECONDS)

        # Save results using update_or_create
        for p in results:
            try:
                HotPost.objects.update_or_create(
                    post_url=p['post_url'],
                    defaults={
                        'page': page,
                        'content_snippet': p.get('caption', ''),
                        'posted_at': p['posted_at'],
                        'likes_count': p['likes'],
                        'comments_count': p['comments'],
                        'shares_count': p['shares'],
                        'video_url': p.get('video_url'),
                    }
                )
            except Exception as e:
                logger.error(f"Error saving hotpost to DB: {e}")

        page.scrape_status = 'completed'
        page.last_scraped_at = timezone.now()
        page.save()
        logger.info(f"Background Task for {page.name} completed successfully.")

    except _TimeoutError as e:
        logger.error(f"TIMEOUT: Task for page_id={page_id} exceeded {SCRAPE_TIMEOUT_SECONDS}s. Aborting.")
        if page:
            page.scrape_status = 'error'
            page.save()

    except Exception as e:
        logger.error(f"Task Failed for page_id={page_id}: {e}")
        if page:
            try:
                page.scrape_status = 'error'
                page.save()
            except Exception:
                pass
