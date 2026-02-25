import json
import logging
import time
import re
from datetime import datetime, timedelta
from django.utils import timezone
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

class HotPostScraper:
    def __init__(self, headless=True):
        self.headless = headless

    def _load_cookies(self, context, cookies_json_str):
        if not cookies_json_str:
            return
        try:
            cookies = json.loads(cookies_json_str)
            if not isinstance(cookies, list):
                logger.error(f"Expected a list of cookies, got {type(cookies)}")
                return
            for cookie in cookies:
                if isinstance(cookie, dict) and 'domain' not in cookie:
                    cookie['domain'] = '.facebook.com'
            context.add_cookies(cookies)
        except Exception as e:
            logger.error(f"Cookie error: {e}")

    def _parse_time_string(self, time_str):
        """
        Parses Facebook's relative time string (e.g. "2 h", "Vừa xong", "10 phút", "Hôm qua lúc 10:00")
        Returns a datetime object if within 24h, else None.
        """
        now = timezone.now()
        time_str = time_str.lower().strip()
        
        if any(x in time_str for x in ['vừa xong', 'just now', 'phút', 'm']):
            # Assume it's very recent, less than an hour
            nums = re.findall(r'\d+', time_str)
            mins = int(nums[0]) if nums else 1
            return now - timedelta(minutes=mins)
            
        if any(x in time_str for x in ['giờ', 'h']):
            nums = re.findall(r'\d+', time_str)
            hours = int(nums[0]) if nums else 1
            if hours <= 24:
                return now - timedelta(hours=hours)
            return None
            
        if 'hôm qua' in time_str or 'yesterday' in time_str:
            # It's yesterday. Technically could be slightly over 24h depending on exact time, but let's include it.
            return now - timedelta(days=1)
            
        # If it's a date like "20 tháng 10" or "October 20", it's likely older than 24h
        return None

    def _parse_number(self, text):
        """ Converts '1,2K' or '1.2K' or '15' to integer 1200 / 15 """
        if not text:
            return 0
        text = str(text).lower().replace(',', '.').strip()
        
        match = re.search(r'(?i)([\d.]+)\s*(k|m|b|tr|triệu|nghìn)?\b', text)
        if not match:
            return 0
            
        num_str = match.group(1).rstrip('.')
        if not num_str:
            return 0
            
        unit = match.group(2)
        try:
            if unit:
                val = float(num_str)
                if unit in ['k', 'nghìn']: val *= 1000
                elif unit in ['m', 'tr', 'triệu']: val *= 1000000
                elif unit == 'b': val *= 1000000000
                return int(val)
            else:
                num_str = num_str.replace('.', '')
                return int(num_str)
        except:
            return 0

    def scrape_page(self, account_cookies, page_url, progress_callback=None):
        """
        Scrapes a Facebook page for posts.
        Returns a list of dicts.
        """
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=['--disable-notifications'])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800}
            )
            
            self._load_cookies(context, account_cookies)
            page = context.new_page()

            try:
                page.goto(page_url, wait_until='domcontentloaded')
                time.sleep(5)

                # Scroll somewhat to load a few posts
                scrolls = 15
                for i in range(scrolls):
                    page.mouse.wheel(0, 3000)
                    time.sleep(3)
                    if progress_callback:
                        progress_callback(int((i / scrolls) * 50)) # scrolling is first 50%
                
                # Locate post containers
                # Facebook changes classes often. `div[role="article"]` or `div[data-pagelet^="FeedUnit"]` are common.
                articles = page.locator("div[role='article']").all()
                
                # If we don't find articles with role='article', fallback to another common structure
                if not articles:
                    articles = page.locator("div[data-ad-preview='message']").locator("..").locator("..").locator("..").locator("..").locator("..").all()

                if progress_callback:
                    progress_callback(55) # Start parsing
                
                total_articles = len(articles)
                for idx, article in enumerate(articles):
                    if progress_callback:
                        progress_callback(55 + int((idx / max(total_articles, 1)) * 45))
                        
                    try:
                        # 1. Extract Time and Link
                        # Usually time is inside a link to the post itself
                        time_links = article.locator("a[role='link']").all()
                        post_url = None
                        posted_at = None
                        
                        for link in time_links:
                            # Time text is usually short
                            text = link.inner_text().strip()
                            href = link.get_attribute("href")
                            
                            # Check if text looks like a time string AND href points to a post
                            if len(text) < 20 and href and any(x in href for x in ['/posts/', '/videos/', '/photos/', 'fbid=', '/permalink/']):
                                parsed_time = self._parse_time_string(text)
                                if parsed_time:
                                    posted_at = parsed_time
                                    post_url = href
                                    if post_url.startswith('/'):
                                        post_url = "https://www.facebook.com" + post_url
                                    
                                    # Normalize URL to remove tracking params to prevent duplicates
                                    if '?' in post_url and 'fbid=' not in post_url:
                                        post_url = post_url.split('?')[0]
                                    break
                        
                        # If not within 24h or couldn't parse, skip this post
                        if not posted_at or not post_url:
                            continue

                        # 2. Extract Text Snippet
                        # Try to find the inner message text
                        content_snippet = ""
                        try:
                            # `data-ad-preview="message"` is occasionally used by FB for the text body
                            msg_el = article.locator("div[data-ad-preview='message']")
                            if msg_el.count() > 0:
                                content_snippet = msg_el.first.inner_text()
                            else:
                                # Fallback: grab all text and take a heuristic snippet
                                all_text = article.inner_text()
                                lines = [line for line in all_text.split('\n') if len(line) > 10 and "Like" not in line and "Comment" not in line]
                                if lines:
                                    content_snippet = lines[0]
                        except:
                            pass
                            
                        content_snippet = (content_snippet[:200] + '...') if len(content_snippet) > 200 else content_snippet

                        # 3. Extract Engagements
                        likes = 0
                        comments = 0
                        shares = 0
                        
                        try:
                            # Search through ALL interactive elements inside the article
                            # To find likes/reactions, comments, shares reliably
                            interactive_els = article.locator("div[role='button'], a[role='link'], span[role='toolbar']").all()
                            
                            for el in interactive_els:
                                text_val = (el.text_content() or "").lower()
                                label_val = (el.get_attribute("aria-label") or "").lower()
                                combined_text = f"{text_val} {label_val}"
                                
                                # Comments
                                if any(x in combined_text for x in ['bình luận', 'comment']):
                                    if re.search(r'\d', combined_text):
                                        num = self._parse_number(combined_text)
                                        if num > comments: comments = num
                                        
                                # Shares
                                if any(x in combined_text for x in ['chia sẻ', 'share']):
                                    if re.search(r'\d', combined_text):
                                        num = self._parse_number(combined_text)
                                        if num > shares: shares = num
                                        
                                # Likes / Reactions
                                if any(x in combined_text for x in ['thích', 'react', 'like', 'cảm xúc', 'người khác', 'others']):
                                    if re.search(r'\d', combined_text):
                                        num = self._parse_number(combined_text)
                                        if num > likes: likes = num
                                        
                            # Global fallback for likes if 0
                            if likes == 0:
                                txt_global = article.text_content().lower()
                                for m in re.finditer(r'([\d.,]+)\s*(k|m|tr|triệu)?\s*(lượt thích|likes?)', txt_global):
                                    num = self._parse_number(m.group(0))
                                    if num > likes: likes = num
                        except Exception as parse_e:
                            logger.warning(f"Engagement parsing fallback needed: {parse_e}")

                        # Sometimes FB groups counts like "1.2K Likes, 30 Comments"
                        
                        results.append({
                            'post_url': post_url,
                            'content_snippet': content_snippet,
                            'posted_at': posted_at,
                            'likes': likes,
                            'comments': comments,
                            'shares': shares
                        })

                    except Exception as e:
                        logger.warning(f"Error parsing an article: {e}")
                        continue
                        
                if progress_callback:
                    progress_callback(100) # Done

                return results

            except Exception as e:
                logger.error(f"Error scraping {page_url}: {e}")
                return results
            finally:
                context.close()
                browser.close()
