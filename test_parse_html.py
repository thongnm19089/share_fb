from playwright.sync_api import sync_playwright
import re

def parse_number(text):
    if not text:
        return 0
    s = str(text).strip()
    s = re.sub(r',(?=\d{1,2}\s*[kKmMtT])', '.', s)
    s = re.sub(r'\.(?=\d{3}(?!\d)(?!\s*[kKmMtT]))', '', s)
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

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto('file:///home/lit/prj/share_fb/a.html')
        
        raw_text = page.locator("body").inner_text()
        
        likes = 0
        labeled = page.locator("[aria-label]").all()
        for el in labeled:
            label = (el.get_attribute("aria-label") or "").lower()
            if any(x in label for x in ['cảm xúc', 'react', 'lượt thích', 'likes', 'người thích', 'thích:', 'yêu thích:']):
                if label in ['bày tỏ cảm xúc', 'thích', 'yêu thích', 'xem ai đã bày tỏ cảm xúc về tin này', 'xem ai đã bày tỏ cảm xúc về bình luận này']:
                    continue
                n = parse_number(label)
                if n > likes:
                    likes = n

        print(f"Likes after label check: {likes}")

        if likes == 0:
            m = re.search(r'Tất cả cảm xúc:\s*([\d.,]+[kKmM]?)', raw_text, re.IGNORECASE)
            if m:
                likes = parse_number(m.group(1))

        # Check in HTML for the new structure
        if likes == 0:
            # Sometime it's in a hidden div
            all_rx = page.locator("text=Tất cả cảm xúc:")
            if all_rx.count() > 0:
                parent = all_rx.locator("..")
                m = re.search(r'([\d.,]+[kKmM]?)', parent.inner_text())
                if m:
                    likes = parse_number(m.group(1))

        print(f"Likes final: {likes}")
        
        comments = 0
        for el in labeled:
            label = (el.get_attribute("aria-label") or "").lower()
            if 'bình luận' in label or 'comment' in label:
                if label not in ['bình luận', 'viết bình luận', 'comment', 'write a comment', 'ẩn hoặc báo cáo bình luận này', 'trả lời']:
                    # We might parse "171 bình luận" from the aria-label
                    # Or "Bình luận dưới tên abc" - we don't want those
                    if 'dưới tên' in label:
                        continue
                    n = parse_number(label)
                    if n > comments:
                        comments = n

        if comments == 0:
            m = re.search(r'([\d.,]+[kKmM]?)\s*bình luận', raw_text, re.IGNORECASE)
            if m:
                comments = parse_number(m.group(1))
            else:
                m = re.search(r'([\d.,]+[kKmM]?)\s*comment', raw_text, re.IGNORECASE)
                if m:
                    comments = parse_number(m.group(1))
        
        print(f"Comments: {comments}")

        shares = 0
        for el in labeled:
            label = (el.get_attribute("aria-label") or "").lower()
            if ('chia sẻ' in label or 'share' in label):
                if label not in ['chia sẻ', 'share', 'chia sẻ bài viết', 'share post', 'góp ý cho chia sẻ']:
                    if 'gửi nội dung' in label:
                        continue
                    n = parse_number(label)
                    if n > shares:
                        shares = n
        if shares == 0:
            for pattern in [
                r'([\d.,]+[kKmM]?)\s*lượt chia sẻ',
                r'([\d.,]+[kKmM]?)\s*chia sẻ',
                r'([\d.,]+[kKmM]?)\s*share',
            ]:
                m = re.search(pattern, raw_text, re.IGNORECASE)
                if m:
                    shares = parse_number(m.group(1))
                    if shares > 0:
                        break

        print(f"Shares: {shares}")
        browser.close()

if __name__ == '__main__':
    test()
