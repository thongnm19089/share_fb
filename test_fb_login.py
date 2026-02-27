import sys
import logging

logging.basicConfig(level=logging.INFO)
from automation.core.fb_login import FBAutoLogin

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python test_fb_login.py <uid> <pass> <2fa>")
        sys.exit(1)
        
    uid = sys.argv[1]
    pwd = sys.argv[2]
    two_fa = sys.argv[3]
    
    bot = FBAutoLogin(headless=True)
    success, res = bot.login_and_get_cookies(uid, pwd, two_fa)
    print(f"Success: {success}")
    if success:
        print(f"Cookies snippet: {res[:100]}...")
    else:
        print(f"Error: {res}")
