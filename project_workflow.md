# FB Auto-Share & Scraper Tool - Dev Workflow

Dự án tự động hóa quản lý Account, Auto Share/Comment Group, và Auto Scrape (Cào bài Hot) từ Fanpage bằng `Django` + `Playwright`.

## 1. Kiến trúc thư mục cốt lõi
- `fb_tool/`: Config chính của Django (`settings.py`, `urls.py`).
- `automation/`: App chính chứa Models, Views, Background Tasks.
  - `models.py`: Database Schema (DB).
  - `views.py`: API (AJAX endpoints) & Web UI Controller.
  - `tasks.py`: Các process chạy ngầm dồn vào Queue.
  - `core/`: (⚠️ QUAN TRỌNG) Chứa core logic điều khiển bot Playwright.
  - `management/commands/`: CLI command (vd: cronjob tự động quét).

---

## 2. Các Tính Năng & Logic Hàm Liên Quan

### Feature 1: Quản Trị Account & Group
* **Mô tả:** Thêm Fanpage cần theo dõi, cấu hình nhóm, thêm Account FB bằng list thẻ JSON Cookies.
* **Database Models:** `FacebookAccount`, `FacebookGroup`, `ObservedPage`.
* **Hàm liên quan:** `views.py` (`add_account`, `add_group`, `add_page`).
* **Lưu ý Fix Bug:** Bot không dùng Pass/User mà load trực tiếp Token/Cookie bằng JSON để qua mặt Checkpoint. Khi check lỗi Auth, xem lại hàm parse vòng lập bên `_load_cookies()`.

### Feature 2: Auto Share & Comment (Campaign V1)
* **Mô tả:** Share 1 bài viết có sẵn vào nhiều nhóm, sau đó tự động bình luận link vừa share.
* **Database Models:** `ShareCampaign`, `ShareLog`.
* **Hàm liên quan:** 
  - `views.py` > `run_campaign()`
  - `automation/core/fb_bot.py` > `FacebookBot.share_post_to_group()`
* **Cách Debug:** Tool chạy trình duyệt ẩn tạo log lưu vào `ShareLog` (Pending -> Success/Failed). Nếu share lỗi, xem traceback exception bên trong method `share_post_to_group()`.

### Feature 3: Auto Scrape Hot Posts (Cào Bài Viết Tìm Tương Tác)
* **Mô tả:** Lọc ra tất cả các bài Post trên Page trong 5 ngày gần nhất. Click từng bài đọc Time, Like, Comment, Share. Trả về Frontend Realtime qua API.
* **Database Models:** `HotPost`, `ObservedPage(scrape_status)`
* **Hàm liên quan:**
  - `views.py` > `api_start_scrape()`, `api_scrape_status()`, `api_get_posts()`
  - `automation/core/hot_post_scraper.py` > `HotPostScraper.scrape_page()`: (Core Controller).
  - `HotPostScraper._collect_post_links()`: Lướt Newsfeed của Page gom link bài viết + đoán thời gian gốc `posted_at`.
  - `HotPostScraper._parse_popup()`: Mở link bài viết đơn lẻ để thu thập tương tác. Nơi chứa logic `if/else` cực kỳ khắt khe nhằm chống lại sự thay đổi Layout liên tục của giao diện Facebook:
     - **Time (Đăng lúc nào):** Thử nghiệm lấy Thuộc tính `data-utime` trên thẻ `<abbr>`. Nếu không có, `fallback` sang tìm RegEx chữ (VD: `15 giờ`). Nếu vẫn không có, lấy ngày giờ tạm đã trích xuất ở bước `_collect_post_links` truyền sang.
     - **Likes (Lượt thích):** Ưu tiên bóc tách từ các thẻ chứa class/aria-label là `reactions`, `cảm xúc`, `lượt thích`. Nếu không tìm thấy thẻ HTML trùng khớp, rơi vào Fallback lấy toàn bộ chữ trên màn hình (`inner_text()`) và dùng tìm kiếm cụm RegEx trước chữ `bình luận`.
     - **Comments (Bình luận):** Sử dụng RegEx text thô quét toàn màn hình `inner_text()` tìm chuỗi `(số_lượng) bình luận` hoặc `(số_lượng) comment`.
     - **Shares (Chia sẻ):** Tương tự comment, dùng RegEx quét toàn màn hình tìm `(số_lượng) lượt chia sẻ` hoặc `share`. 
     - **Lưu ý ép kiểu (`_parse_number`)**: Mọi chuỗi số liệu (VD: `1,2K`, `1.5 triệu`, `2 nghìn`) đều được đưa qua hàm `_parse_number` ở đầu file để nhân hệ số (k*, m*, nghìn*) trả lại một số Integer (Int) sạch sẽ nhất.
* **Cách Debug:** Mọi thứ nằm trong `_parse_popup`. Nếu bắt hụt Like/CMT/Share, hãy chép source HTML lúc tool lỗi nạp vào AI và yêu cầu viết lại đoạn RegEx `inner_text` hoặc bộ đếm `locator` trong hàm này. 

### Feature 4: Kịch Bản Tự Động Hóa Scrape (Auto Scan Job / Background Queue)
* **Mô tả:** Schedule quét Auto theo giờ (vd mỗi 2 tiếng quét 1 lần). Chạy ngầm không ảnh hưởng Web.
* **Hàm liên quan:**
  - `tasks.py` > `@background scrape_page_background_task`
  - `views.py` > `global_auto_scan_task`
  - `automation/management/commands/run_auto_scan.py` (Script để tạo cron check hàng chờ `Task.objects.count() == 0`).
* **Cách Debug:** 
  - Chạy local cmd: `python manage.py process_tasks`.
  - Nếu DB báo trạng thái Page bị kẹt chữ "Running", `run_auto_scan.py` sẽ tự động check `Task Queue`. Nếu Queue rỗng mà Page ghi Running, Script sẽ tự Reset về `Idle` chống lỗi kẹt vòng lặp ảo.

---

## 3. Tool Tùy Chỉnh (Playwright Chromium)
Tất cả kịch bản giả lập ngầm xài `sync_playwright()` (tại `/automation/core/`). Trình duyệt đang được cấu hình:
- Tránh Detection: Load Profile Folder tĩnh (`user_data_dir='fb_browser_profile'`) thay vì Incognito Context để lưu session lâu dài, kèm options `--disable-blink-features=AutomationControlled`.
- Xử lý Cookie lỗi: Tool sẽ tự Catch JSON JSONDecodeError nếu user nhập cookie sai format vào trang Web.  - **Xảy ra khi:** Dữ liệu chèn vào Admin Panel không phải định dạng JSON Array `[{"name":..}, ...]`.
   - **Cách debug:** Luôn parse cẩn thận ở hàm `_load_cookies` (`hot_post_scraper.py`) để loại bỏ Cookie bị thiếu thông tin hoặc sai JSON (Hiện dự án đã được AI cover logic này, tham khảo phần Try-Catch tại code).
3. **Tiến trình cào không chịu chạy (Mắc kẹt ở Running vĩnh viễn):**
   - Rơi vào trường hợp DB báo running, còn Background Process (`process_tasks`) đã ngưng.
   - Nếu nhấn nút Dừng khẩn cấp trên UI không tác dụng (Action: `cancel_all_active`), cần vào hệ điều hành `pkill -f "manage.py process_tasks" && python manage.py process_tasks` để dọn Memory rác, rồi update thủ công DB cho các `ObservedPage(scrape_status='idle')`.

## 4. Tóm Lược Kiến Trúc (Architecture)
- **Framework**: Django (Python 3.10+)
- **Database**: SQLite3 (hoặc PostgreSQL tuỳ config).
- **Core Automation**: Thư viện Playwright (`sync_playwright`), xử lý Browser headless không giao diện trên Ubuntu Server.
- **Frontend**: Bootstrap 5, Javascript Fetch API dùng Ajax.
- **Scheduler**: Thư viện `django-background-tasks` dùng db table `background_task` làm CSDL hàng đợi tiến trình.
