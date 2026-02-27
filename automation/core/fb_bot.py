import json
import logging
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time

logger = logging.getLogger(__name__)

class FacebookBot:
    def __init__(self, headless=True):
        self.headless = headless

    def _load_cookies(self, context, cookies_json_str):
        if not cookies_json_str:
            return
        
        try:
            cookies = json.loads(cookies_json_str)
            # Ensure cookies have the correct domain if not provided
            for cookie in cookies:
                if 'domain' not in cookie:
                    cookie['domain'] = '.facebook.com'
                if 'sameSite' in cookie and cookie['sameSite'] not in ['Strict', 'Lax', 'None']:
                    del cookie['sameSite']
            context.add_cookies(cookies)
        except json.JSONDecodeError:
            logger.error("Invalid JSON cookie format")
        except Exception as e:
            logger.error(f"Error loading cookies: {e}")

    def share_post_to_group(self, account_cookies, group_url, link_to_share, comment_content=None):
        """
        Navigates to the group, shares a link, and optionally comments on it.
        Returns (success: bool, error_message: str, shared_post_url: str)
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless, args=['--disable-notifications'])
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800}
            )
            
            self._load_cookies(context, account_cookies)
            page = context.new_page()

            try:
                # 1. Navigate to Group
                page.goto(group_url, wait_until='domcontentloaded')
                time.sleep(3) # Wait for FB to stabilize
                
                # Verify login status
                if "login" in page.url or page.title() == "Log in to Facebook":
                    return False, "Not logged in or cookies expired.", None

                # 2. Click on Composer
                # Find the create post button. Usually has aria-label like "Create a public post..." or role="button" with text "Write something..."
                composer_selectors = [
                    "div[role='button']:has-text('Write something...')",
                    "div[role='button']:has-text('Tạo bài viết công khai...')",
                    "div[aria-label^='Create a public post']",
                    "div[aria-label^='Tạo bài viết công khai']",
                ]
                
                clicked_composer = False
                for selector in composer_selectors:
                    try:
                        element = page.wait_for_selector(selector, timeout=5000)
                        if element and element.is_visible():
                            element.click()
                            clicked_composer = True
                            break
                    except PlaywrightTimeoutError:
                        continue
                
                if not clicked_composer:
                    # Let's try more generic approach
                    page.get_by_text("Write something...").first.click(timeout=5000)
                
                time.sleep(2)
                
                # 3. Enter the link
                # The compose modal input. Usually a contenteditable div with specific aria-label
                editor = page.locator("div[role='textbox'][contenteditable='true']").last
                editor.wait_for(state="visible", timeout=10000)
                editor.click()
                editor.type(link_to_share, delay=50)
                
                # Wait for link preview to fetch
                time.sleep(5)
                
                # 4. Click Post Button
                post_btn_selectors = [
                    "div[aria-label='Post']",
                    "div[aria-label='Đăng']",
                    "span:has-text('Post'):not(:has-text('Create a public post'))",
                    "span:has-text('Đăng')"
                ]
                
                posted = False
                for selector in post_btn_selectors:
                    try:
                        btn = page.locator(selector).last
                        if btn.is_visible():
                            btn.click()
                            posted = True
                            break
                    except:
                        continue
                
                if not posted:
                    return False, "Could not find or click the Post button.", None

                # Wait for the posting UI to disappear and the post to appear
                time.sleep(8)
                
                # Optional: Handle commenting
                if comment_content:
                    time.sleep(2) # Give it extra time for post to be fully rendered
                    try:
                        # Try to find the comment box on the most recent post
                        comment_box = page.locator("div[role='textbox'][aria-label*='comment']").first
                        if comment_box.is_visible():
                            comment_box.click()
                            comment_box.type(comment_content, delay=30)
                            page.keyboard.press("Enter")
                            time.sleep(3)
                    except Exception as e:
                        logger.warning(f"Failed to leave comment: {e}")
                        # We still consider the share successful even if comment failed

                return True, "", page.url

            except Exception as e:
                return False, str(e), None
            finally:
                context.close()
                browser.close()
