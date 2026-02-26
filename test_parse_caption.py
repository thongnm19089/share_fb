from playwright.sync_api import sync_playwright

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto('file:///home/lit/prj/share_fb/a.html')
        
        dialog = page.locator("body")
        
        caption = ""
        try:
            msg_el = dialog.locator("div[data-ad-preview='message']")
            if msg_el.count() > 0:
                caption = msg_el.first.inner_text().strip()
                print("FOUND VIA data-ad-preview='message':", repr(caption))
        except Exception as e:
            print("ERROR 1:", e)
            
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
                print("FOUND VIA fallback:", repr(caption))
            except Exception as e:
                print("ERROR 2:", e)
                
        print("FINAL:", repr(caption))

        browser.close()

if __name__ == '__main__':
    test()
