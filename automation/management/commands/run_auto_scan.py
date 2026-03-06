from django.core.management.base import BaseCommand
from automation.models import ObservedPage, FacebookAccount
from automation.tasks import scrape_page_background_task
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Quét HotPosts cho tất cả Page của mỗi User (chạy như thủ công).'

    def handle(self, *args, **options):
        self.stdout.write("Bắt đầu Auto Scan (Background Task)...")
        users = User.objects.all()

        for user in users:
            account = FacebookAccount.objects.filter(user=user, status='live').first()
            if not account:
                self.stdout.write(f"User {user.username} - Bỏ qua (không có tài khoản FB Live).")
                continue

            pages = ObservedPage.objects.filter(user=user)
            if not pages.exists():
                self.stdout.write(f"User {user.username} - Bỏ qua (không có page nào).")
                continue

            # KIỂM TRA: Nếu user đang có bất kỳ page nào đang queued/running, bỏ qua hoàn toàn
            has_active = pages.filter(scrape_status__in=['queued', 'running']).exists()
            if has_active:
                self.stdout.write(f"User {user.username} - Bỏ qua (đang có tiến trình quét diễn ra).")
                continue

            # Đưa TẤT CẢ page vào hàng đợi
            page_ids = list(pages.values_list('id', flat=True))

            self.stdout.write(f"User {user.username} - Đưa {len(page_ids)} page vào hàng đợi: {page_ids}")

            for pid in page_ids:
                scrape_page_background_task(pid, user.id)

            pages.update(scrape_status='queued')

            self.stdout.write(self.style.SUCCESS(f"User {user.username} - Đã lên lịch thành công!"))

        self.stdout.write(self.style.SUCCESS("Auto Scan hoàn tất!"))
