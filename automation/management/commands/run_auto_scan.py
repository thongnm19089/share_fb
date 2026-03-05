from django.core.management.base import BaseCommand
from automation.models import ObservedPage, FacebookAccount
from automation.tasks import scrape_page_background_task
from django.contrib.auth.models import User
from django.utils import timezone
import uuid

class Command(BaseCommand):
    help = 'Tự động quét HotPosts cho các Page bật is_auto_scan của toàn bộ User.'

    def handle(self, *args, **options):
        self.stdout.write("Bắt đầu Cronjob Auto Scan...")
        users = User.objects.all()
        
        now = timezone.localtime()
        
        for user in users:
            account = FacebookAccount.objects.filter(user=user, status='live').first()
            if not account:
                self.stdout.write(f"User {user.username} - Bỏ qua (không có tài khoản FB Live).")
                continue
                
            pages = ObservedPage.objects.filter(user=user, is_auto_scan=True)
            if not pages.exists():
                self.stdout.write(f"User {user.username} - Bỏ qua (không có page nào Tự Động Quét).")
                continue
            
            page_ids = []
            for page in pages:
                should_scan = False
                last_scraped = timezone.localtime(page.last_scraped_at) if page.last_scraped_at else None
                
                if page.auto_scan_time:
                    # Chạy theo giờ người dùng thiết lập trên giao diện
                    if now.time() >= page.auto_scan_time:
                        if not last_scraped or (now - last_scraped).total_seconds() > 3000:
                            should_scan = True
                else:
                    # Chạy 3000 giây (50 phút) một lần để hỗ trợ quét hàng giờ
                    if not last_scraped or (now - last_scraped).total_seconds() > 3000:
                        should_scan = True
                            
                if should_scan:
                    page_ids.append(page.id)
            
            if not page_ids:
                self.stdout.write(f"User {user.username} - Chưa đến giờ chạy auto-scan kế tiếp.")
                continue
                
            self.stdout.write(f"User {user.username} - Đang thêm {len(page_ids)} page vào hàng đợi (Background tasks): {page_ids}")
            
            for pid in page_ids:
                scrape_page_background_task(pid, user.id)
                
            ObservedPage.objects.filter(id__in=page_ids).update(scrape_status='queued')
            
            self.stdout.write(self.style.SUCCESS(f"User {user.username} - Đã Lên Lịch thành công!"))
            
        self.stdout.write(self.style.SUCCESS("Cronjob Auto Scan hoàn tất 100%!"))
