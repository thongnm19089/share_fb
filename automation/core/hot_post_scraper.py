import json
import logging
import time
import re
from datetime import timedelta
from django.utils import timezone
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


class HotPostScraper:
    def __init__(self, headless=True):
        self.headless = headless

    # ──────────────────────────────────────────────────────────────────────────
    # Cookie helpers
    # ──────────────────────────────────────────────────────────────────────────
    def _load_cookies(self, context, cookies_json_str):
        if not cookies_json_str:
            return
        try:
            cookies = json.loads(cookies_json_str)
            if isinstance(cookies, dict):
                cookies = [cookies]
            if not isinstance(cookies, list):
                logger.error(f"Expected list of cookies, got {type(cookies)}")
                return
            valid = []
            for c in cookies:
                if isinstance(c, dict) and 'name' in c and 'value' in c:
                    c.setdefault('domain', '.facebook.com')
                    c.setdefault('path', '/')
                    valid.append(c)
            if valid:
                context.add_cookies(valid)
                logger.info(f"Loaded {len(valid)} cookies.")
            else:
                logger.warning("No valid cookies found.")
        except Exception as e:
            logger.error(f"Cookie error: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Number parser  (1,2K → 1200 | 64 → 64 | 1.200 → 1200)
    # ──────────────────────────────────────────────────────────────────────────
    def _parse_number(self, text):
        if not text:
            return 0
        s = str(text).strip()

        # Dấu phẩy dạng thập phân (1,2K) → chấm
        s = re.sub(r',(?=\d{1,2}\s*[kKmMtT])', '.', s)
        # Dấu chấm phân hàng nghìn (1.200) → xóa (chỉ khi KHÔNG theo sau bởi K/M)
        s = re.sub(r'\.(?=\d{3}(?!\d)(?!\s*[kKmMtT]))', '', s)
        # Còn lại dấu phẩy là phân hàng nghìn
        s = s.replace(',', '')

        m = re.search(r'([\d.]+)\s*(k|m|b|tr|triệu|nghìn)?', s, re.IGNORECASE)
        if not m:
            return 0
        try:
            val = float(m.group(1).rstrip('.'))
            unit = (m.group(2) or '').lower()
            if unit in ('k', 'nghìn'):
                val *= 1_000
            elif unit in ('m', 'tr', 'triệu'):
                val *= 1_000_000
            elif unit == 'b':
                val *= 1_000_000_000
            return int(val)
        except Exception:
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Time parser  ("15 giờ" → datetime | "Vừa xong" → now | old → None)
    # ──────────────────────────────────────────────────────────────────────────
    def _parse_time_string(self, raw):
        """
        Returns (datetime, within_24h: bool).
        within_24h=True  → bài trong 24h trước
        within_24h=False → bài cũ hơn hoặc không parse được
        """
        now = timezone.now()
        s = (raw or '').lower().strip()
        if not s:
            return None, False

        # Vừa xong / just now
        if any(x in s for x in ['vừa xong', 'just now']):
            return now - timedelta(seconds=30), True

        # X giây
        m = re.search(r'(\d+)\s*(giây|sec)', s)
        if m:
            return now - timedelta(seconds=int(m.group(1))), True

        # X phút / X mins
        m = re.search(r'(\d+)\s*(phút|min)', s)
        if m:
            return now - timedelta(minutes=int(m.group(1))), True

        # X giờ / X hrs / Xh (Facebook EN thường viết "15h" hoặc "15 hrs")
        m = re.search(r'(\d+)\s*(giờ|gr|hrs?|h)\b', s)
        if m:
            hours = int(m.group(1))
            if hours <= 24:
                return now - timedelta(hours=hours), True
            return None, False

        # Hôm qua / yesterday (có thể kèm giờ)
        if 'hôm qua' in s or 'yesterday' in s:
            t = re.search(r'(\d{1,2}):(\d{2})', s)
            if t:
                hr, mn = int(t.group(1)), int(t.group(2))
                candidate = (now - timedelta(days=1)).replace(
                    hour=hr, minute=mn, second=0, microsecond=0)
                if (now - candidate).total_seconds() <= 86400:
                    return candidate, True
            return now - timedelta(days=1), True

        # Giờ hôm nay "10:30"
        m = re.match(r'^(\d{1,2}):(\d{2})$', s)
        if m:
            hr, mn = int(m.group(1)), int(m.group(2))
            candidate = now.replace(hour=hr, minute=mn, second=0, microsecond=0)
            if candidate > now:
                candidate -= timedelta(days=1)
            if (now - candidate).total_seconds() <= 86400:
                return candidate, True
            return None, False

        # Unix timestamp (data-utime attribute)
        m = re.match(r'^\d{10}$', s)
        if m:
            from datetime import datetime
            import pytz
            dt = datetime.fromtimestamp(int(s), tz=pytz.UTC)
            if (now - dt).total_seconds() <= 86400:
                return dt, True
            return dt, False

        return None, False

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 1: Collect post links from the page feed
    # ──────────────────────────────────────────────────────────────────────────
    def _collect_post_links(self, page, progress_callback=None):
        """
        Scroll qua feed, thu thập các link bài viết POST trong 24h.
        Trả về list[str] – danh sách URL bài viết không trùng.
        """
        post_links = {}   # url → posted_at  (hoặc None nếu chưa parse được time)
        seen = set()

        MAX_SCROLLS = 40
        SCROLL_STEP  = 2500
        SCROLL_PAUSE = 2.5
        MAX_OLD_STREAK = 4   # số bài cũ liên tiếp thì dừng
        no_new_count = 0
        last_count = 0
        old_streak = 0

        # Selector link bài viết
        LINK_SELECTOR = (
            "a[href*='/posts/'], a[href*='/videos/'], "
            "a[href*='/photos/'], a[href*='fbid='], a[href*='/permalink/']"
        )

        def _normalize(url):
            if not url:
                return url
            if url.startswith('/'):
                url = 'https://www.facebook.com' + url
            if '?' in url and 'fbid=' not in url:
                url = url.split('?')[0]
            return url.rstrip('/')

        def _scan_links():
            """Thu thập link & time từ DOM hiện tại."""
            nonlocal old_streak
            new_found = 0
            try:
                links = page.locator(LINK_SELECTOR).all()
                for link_el in links:
                    try:
                        href = link_el.get_attribute('href') or ''
                        url = _normalize(href)
                        if not url or url in seen:
                            continue
                        seen.add(url)

                        # Thử parse time từ text ngắn kế link
                        text = link_el.inner_text().strip()
                        posted_at = None
                        if text and len(text) < 20:
                            dt, ok = self._parse_time_string(text)
                            if ok:
                                posted_at = dt
                                old_streak = 0
                            elif dt is not None:
                                # Bài cũ hơn 24h → tăng streak
                                old_streak += 1
                                continue  # bỏ qua bài cũ
                        # Nếu không lấy được time từ text, vẫn thu thập URL để click sau
                        post_links[url] = posted_at
                        new_found += 1
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"_scan_links error: {e}")
            return new_found

        for i in range(MAX_SCROLLS):
            page.mouse.wheel(0, SCROLL_STEP)
            time.sleep(SCROLL_PAUSE)

            if progress_callback:
                progress_callback(min(45, int((i / MAX_SCROLLS) * 45)))

            new = _scan_links()
            current_count = len(post_links)

            if current_count == last_count:
                no_new_count += 1
                if no_new_count >= 3:
                    logger.info("No new links after 3 scrolls, stopping.")
                    break
            else:
                no_new_count = 0
                last_count = current_count

            if old_streak >= MAX_OLD_STREAK:
                logger.info(f"Hit {old_streak} old posts in a row, stopping scroll.")
                break

            logger.debug(f"Scroll {i+1}: total links={current_count}, old_streak={old_streak}")

        logger.info(f"Collected {len(post_links)} post links.")
        return list(post_links.keys())

    # ──────────────────────────────────────────────────────────────────────────
    # STEP 2: Click từng link → mở popup → parse chi tiết
    # ──────────────────────────────────────────────────────────────────────────
    def _parse_popup(self, page):
        """
        Sau khi popup bài viết mở, đọc thông tin từ popup.
        Trả về dict hoặc None.

        Cấu trúc popup dựa trên ảnh người dùng gửi:
        ┌─────────────────────────────────────────┐
        │  [Avatar] Tên trang  ·  15 giờ  ·  🌐   │
        │  Caption text...                         │
        │  [Ảnh/Video]                             │
        │  😍❤️ 1,2K          64 bình luận  130... │
        │  [Thích] [Bình luận] [Chia sẻ]          │
        └─────────────────────────────────────────┘
        """
        # Chờ popup load
        POPUP_SELECTOR = "div[role='dialog'], div[data-pagelet='MediaViewerPhoto']"
        try:
            page.wait_for_selector(POPUP_SELECTOR, timeout=8000)
        except PlaywrightTimeout:
            # Thử fallback: có thể navigate sang trang mới
            logger.debug("Dialog not found, reading current page directly.")

        # Lấy container chính của popup
        dialog = page.locator("div[role='dialog']")
        if dialog.count() == 0:
            # Không có dialog, đọc từ toàn trang (đã navigate)
            dialog = page.locator("body")

        posted_at = None
        time_raw = ""
        caption = ""
        likes = 0
        comments = 0
        shares = 0

        # ── Thời gian ────────────────────────────────────────────────────────
        # Thử data-utime (chính xác nhất)
        try:
            utime_el = dialog.locator("abbr[data-utime]").first
            if utime_el.count() > 0:
                utime = utime_el.get_attribute("data-utime")
                time_raw = utime  # sẽ parse bên dưới
                if utime:
                    from datetime import datetime
                    import pytz
                    dt = datetime.fromtimestamp(int(utime), tz=pytz.UTC)
                    posted_at = dt
        except Exception:
            pass

        # Fallback: tìm text dạng "15 giờ ·" gần tên trang
        if not posted_at:
            try:
                time_candidates = dialog.locator("a[role='link'] span, span[role='tooltip'], abbr").all()
                for el in time_candidates:
                    txt = el.inner_text().strip()
                    if txt and len(txt) < 25:
                        dt, ok = self._parse_time_string(txt)
                        if ok and dt:
                            posted_at = dt
                            time_raw = txt
                            break
            except Exception:
                pass

        # Fallback cuối: quét inner_text tìm pattern "X giờ" hoặc "X phút"
        if not posted_at:
            try:
                full_text = dialog.inner_text()
                for m in re.finditer(
                    r'(\d+)\s*(phút|giờ|mins?|hrs?|h)\b', full_text, re.IGNORECASE
                ):
                    dt, ok = self._parse_time_string(m.group(0))
                    if ok and dt:
                        posted_at = dt
                        time_raw = m.group(0)
                        break
            except Exception:
                pass

        # ── Caption ──────────────────────────────────────────────────────────
        try:
            # Thử selector chuẩn
            msg_el = dialog.locator("div[data-ad-preview='message']")
            if msg_el.count() > 0:
                caption = msg_el.first.inner_text().strip()
        except Exception:
            pass

        if not caption:
            try:
                # div[dir='auto'] dài nhất
                nodes = dialog.locator("div[dir='auto'], span[dir='auto']").all()
                skip_kw = ['bình luận', 'chia sẻ', 'thích', 'comment', 'share', 'like', 'reactions']
                best = ""
                for node in nodes:
                    t = node.inner_text().strip()
                    if (len(t) > len(best)
                            and not any(kw in t.lower() for kw in skip_kw)
                            and len(t) > 5):
                        best = t
                caption = best
            except Exception:
                pass

        caption = caption[:500] + ('...' if len(caption) > 500 else '')

        # ── Likes / Reactions ────────────────────────────────────────────────
        # Popup Facebook hiển thị count reactions dạng:
        #  <span aria-label="1,2K người bày tỏ cảm xúc">  hoặc text gọn "1,2K"
        try:
            labeled = dialog.locator("[aria-label]").all()
            for el in labeled:
                label = (el.get_attribute("aria-label") or "").lower()
                if any(x in label for x in ['cảm xúc', 'react', 'lượt thích', 'likes', 'người thích']):
                    n = self._parse_number(label)
                    if n > likes:
                        likes = n
        except Exception:
            pass

        # Fallback: số nhỏ cạnh emoji reactions
        if likes == 0:
            try:
                # Tìm span chứa số ngay sau khu vực emoji reactions
                # Facebook thường dùng: <span>1,2K</span> hoặc aria-label trực tiếp
                reaction_spans = dialog.locator(
                    "span[class*='reactions'], div[class*='reactions'], "
                    "span[aria-label*='cảm xúc'], span[aria-label*='like'], "
                    "div[aria-label*='lượt thích']"
                ).all()
                for sp in reaction_spans:
                    txt = sp.text_content() or ""
                    n = self._parse_number(txt)
                    if n > likes:
                        likes = n

                # Đọc text thô: tìm số ngay trước "bình luận"
                if likes == 0:
                    raw_text = dialog.inner_text()
                    # Pattern: "😍❤️ 1,2K    64 bình luận   130 lượt chia sẻ"
                    m = re.search(
                        r'([\d.,]+[kKmM]?)\s+[\d.,]+[kKmM]?\s+bình luận', raw_text
                    )
                    if m:
                        likes = self._parse_number(m.group(1))
            except Exception:
                pass

        # ── Comments ─────────────────────────────────────────────────────────
        try:
            # aria-label
            labeled = dialog.locator("[aria-label]").all()
            for el in labeled:
                label = (el.get_attribute("aria-label") or "").lower()
                if 'bình luận' in label or 'comment' in label:
                    if label not in ['bình luận', 'viết bình luận', 'comment', 'write a comment']:
                        n = self._parse_number(label)
                        if n > comments:
                            comments = n
        except Exception:
            pass

        if comments == 0:
            try:
                raw_text = dialog.inner_text()
                m = re.search(r'([\d.,]+[kKmM]?)\s*bình luận', raw_text, re.IGNORECASE)
                if m:
                    comments = self._parse_number(m.group(1))
                else:
                    m = re.search(r'([\d.,]+[kKmM]?)\s*comment', raw_text, re.IGNORECASE)
                    if m:
                        comments = self._parse_number(m.group(1))
            except Exception:
                pass

        # ── Shares ───────────────────────────────────────────────────────────
        try:
            labeled = dialog.locator("[aria-label]").all()
            for el in labeled:
                label = (el.get_attribute("aria-label") or "").lower()
                if ('chia sẻ' in label or 'share' in label):
                    if label not in ['chia sẻ', 'share', 'chia sẻ bài viết', 'share post']:
                        n = self._parse_number(label)
                        if n > shares:
                            shares = n
        except Exception:
            pass

        if shares == 0:
            try:
                raw_text = dialog.inner_text()
                for pattern in [
                    r'([\d.,]+[kKmM]?)\s*lượt chia sẻ',
                    r'([\d.,]+[kKmM]?)\s*chia sẻ',
                    r'([\d.,]+[kKmM]?)\s*share',
                ]:
                    m = re.search(pattern, raw_text, re.IGNORECASE)
                    if m:
                        shares = self._parse_number(m.group(1))
                        if shares > 0:
                            break
            except Exception:
                pass

        if not posted_at:
            return None

        return {
            'posted_at': posted_at,
            'time_raw': time_raw,
            'caption': caption,
            'likes': likes,
            'comments': comments,
            'shares': shares,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # MAIN: scrape_page
    # ──────────────────────────────────────────────────────────────────────────
    def scrape_page(self, account_cookies, page_url, progress_callback=None):
        """
        Luồng:
          1. Load trang, cuộn để lấy hết link bài viết trong 24h
          2. Với mỗi link: click → popup → parse chi tiết
          3. Trả về list[dict] đã sort theo tương tác (likes + comments + shares)
        """
        results = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=self.headless,
                args=['--disable-notifications', '--no-sandbox', '--disable-dev-shm-usage'],
            )
            context = browser.new_context(
                user_agent=(
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/122.0.0.0 Safari/537.36'
                ),
                viewport={'width': 1366, 'height': 900},
                locale='vi-VN',
            )
            self._load_cookies(context, account_cookies)
            page = context.new_page()

            try:
                logger.info(f"Navigating to {page_url}")
                page.goto(page_url, wait_until='domcontentloaded', timeout=30_000)
                time.sleep(4)

                # Đóng popup login nếu có
                try:
                    page.keyboard.press('Escape')
                    time.sleep(0.5)
                except Exception:
                    pass

                # ── BƯỚC 1: Thu thập link ─────────────────────────────────────
                post_links = self._collect_post_links(page, progress_callback)
                logger.info(f"Found {len(post_links)} post links to process.")

                if progress_callback:
                    progress_callback(48)

                total = len(post_links)

                # ── BƯỚC 2: Click từng link → parse popup ─────────────────────
                for idx, post_url in enumerate(post_links):
                    if progress_callback:
                        pct = 50 + int((idx / max(total, 1)) * 48)
                        progress_callback(pct)

                    logger.info(f"[{idx+1}/{total}] Opening {post_url}")
                    try:
                        # Điều hướng đến link bài viết
                        page.goto(post_url, wait_until='domcontentloaded', timeout=20_000)
                        time.sleep(3)

                        post_data = self._parse_popup(page)
                        if not post_data:
                            logger.warning(f"Could not parse popup for {post_url}")
                            continue

                        post_data['post_url'] = post_url
                        results.append(post_data)

                        logger.info(
                            f"  ✓ time={post_data.get('time_raw')} "
                            f"likes={post_data['likes']} "
                            f"comments={post_data['comments']} "
                            f"shares={post_data['shares']}"
                        )

                        # Quay lại trang fanpage
                        page.go_back(wait_until='domcontentloaded', timeout=15_000)
                        time.sleep(2)

                    except PlaywrightTimeout:
                        logger.warning(f"Timeout on {post_url}, skipping.")
                        try:
                            page.go_back(wait_until='domcontentloaded', timeout=10_000)
                            time.sleep(1)
                        except Exception:
                            page.goto(page_url, wait_until='domcontentloaded', timeout=20_000)
                            time.sleep(3)
                        continue
                    except Exception as e:
                        logger.warning(f"Error on {post_url}: {e}")
                        try:
                            page.goto(page_url, wait_until='domcontentloaded', timeout=20_000)
                            time.sleep(2)
                        except Exception:
                            pass
                        continue

                # ── BƯỚC 3: Sort by engagement ────────────────────────────────
                results.sort(
                    key=lambda r: r['likes'] + r['comments'] * 2 + r['shares'] * 3,
                    reverse=True,
                )

                if progress_callback:
                    progress_callback(100)

                logger.info(
                    f"Done. {len(results)} posts collected and sorted by engagement."
                )
                return results

            except Exception as e:
                logger.error(f"Fatal error scraping {page_url}: {e}")
                return results
            finally:
                context.close()
                browser.close()
