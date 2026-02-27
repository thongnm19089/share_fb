import json
import logging
import time
import pyotp
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

class FBAutoLogin:
    def __init__(self, headless=True):
        self.headless = headless

    def get_2fa_code(self, secret):
        """Generate 2FA code from the secret via pyotp."""
        if not secret:
            return None
        # Remove spaces if any
        secret = secret.replace(' ', '').upper()
        try:
            totp = pyotp.TOTP(secret)
            return totp.now()
        except Exception as e:
            logger.error(f"Error generating 2FA code: {e}")
            return None

    def login_and_get_cookies(self, uid, password, two_fa_secret):
        """
        Logs into Facebook using uid, password, and 2fa secret.
        Returns (success: bool, cookies_json_str_or_error_msg: str)
        """
        import os
        with sync_playwright() as p:
            user_data_dir = os.path.join(os.getcwd(), 'fb_browser_profile')
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                args=['--disable-notifications', '--no-sandbox', '--disable-dev-shm-usage'],
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1366, 'height': 900},
                locale='vi-VN',
            )
            
            page = context.pages[0] if context.pages else context.new_page()
            try:
                logger.info(f"Navigating to Facebook login for UID: {uid}")
                page.goto('https://www.facebook.com/login', wait_until='domcontentloaded', timeout=30_000)
                
                # Input username
                page.fill('input[name="email"]', uid)
                # Input password
                page.fill('input[name="pass"]', password)
                # Click login
                if page.locator('button[name="login"]').is_visible():
                    page.click('button[name="login"]')
                else:
                    # Fallback to pressing Enter while focused on password
                    page.keyboard.press("Enter")
                
                # Wait for navigation or a bit
                time.sleep(5)
                
                # Check if it reached 2FA screen
                if 'checkpoint' in page.url or 'approvals_code' in page.url or page.locator('input[id="approvals_code"]').count() > 0:
                    logger.info("2FA screen detected. Inputting 2FA code...")
                    code = self.get_2fa_code(two_fa_secret)
                    if not code:
                        return False, "Failed to generate 2FA code from the secret provided."
                        
                    # Locate the 2FA input field (common ids: approvals_code)
                    if page.locator('input[name="approvals_code"]').count() > 0:
                        page.fill('input[name="approvals_code"]', code)
                        page.click('button[id="checkpointSubmitButton"]')
                    elif page.locator('input[id="approvals_code"]').count() > 0:
                        page.fill('input[id="approvals_code"]', code)
                        page.click('button[id="checkpointSubmitButton"]')
                    else:
                        # Sometimes Facebook asks for the code in a different format
                        code_input = page.locator('input[type="text"]').filter(has_text=re.compile(r'Mã|Code|Mã phê duyệt', re.I))
                        if code_input.count() > 0:
                             code_input.first.fill(code)
                             page.keyboard.press("Enter")
                        else:
                             # Just try filling any text input on checkpoint screen that looks like it's for 2fa
                             page.fill('input[type="text"]', code)
                             page.keyboard.press("Enter")
                    
                    time.sleep(5)
                    
                    # If there's a "Save Browser" step
                    if page.locator('input[value="dont_save"]').count() > 0 or page.locator('text="Không lưu"').count() > 0:
                        try:
                            page.click('input[value="dont_save"]')
                            page.click('button[id="checkpointSubmitButton"]')
                            time.sleep(3)
                        except:
                            pass
                            
                # Verify if we are logged in successfully
                # Normally we can check for elements that only exist on the homepage
                page.goto('https://www.facebook.com/', wait_until='domcontentloaded')
                time.sleep(4)
                
                if page.locator('form[data-testid="royal_login_form"]').count() > 0 or 'login' in page.url:
                    # Still on login page -> failed
                    error_msg_loc = page.locator('div[role="alert"]')
                    if error_msg_loc.count() > 0:
                        return False, f"Login Failed: {error_msg_loc.inner_text().strip()}"
                    return False, "Login failed. Wrong password, UID, or 2FA code."
                    
                # We are logged in. Extract cookies.
                raw_cookies = context.cookies()
                logger.info(f"Successfully logged in. Extracted {len(raw_cookies)} cookies.")
                return True, json.dumps(raw_cookies)
                
            except Exception as e:
                logger.error(f"Error during auto-login: {e}")
                return False, f"Error: {e}"
            finally:
                context.close()
