from django.db import models
from django.contrib.auth.models import User


class FacebookAccount(models.Model):
    STATUS_CHOICES = (
        ('live', 'Live'),
        ('die', 'Die'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255, help_text="Tên hoặc User_ID để nhận diện")
    cookies = models.TextField(help_text="Chuỗi JSON cookie của tài khoản")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='live')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.status}"


class FacebookGroup(models.Model):
    name = models.CharField(max_length=255)
    group_id = models.CharField(max_length=100, help_text="ID của group hoặc đường dẫn")
    url = models.URLField(max_length=500, help_text="Link dẫn đến group")

    def __str__(self):
        return f"{self.name} ({self.group_id})"


class ShareCampaign(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255, help_text="Tên chiến dịch")
    link_to_share = models.URLField(max_length=1000, help_text="Link bài viết hoặc trang web cần share")
    comment_content = models.TextField(blank=True, null=True, help_text="Nội dung sẽ comment vào bài sau khi share")
    accounts = models.ManyToManyField(FacebookAccount, related_name='campaigns')
    groups = models.ManyToManyField(FacebookGroup, related_name='campaigns')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Campaign: {self.name}"


class ShareLog(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    )
    campaign = models.ForeignKey(ShareCampaign, on_delete=models.CASCADE, related_name='logs')
    account = models.ForeignKey(FacebookAccount, on_delete=models.SET_NULL, null=True)
    group = models.ForeignKey(FacebookGroup, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    shared_post_url = models.URLField(max_length=1000, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.campaign.name} - {self.account} -> {self.group}: {self.status}"

class ObservedPage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255, help_text="Tên Fanpage")
    url = models.URLField(max_length=1000, help_text="Link đến Fanpage")
    is_auto_scan = models.BooleanField(default=False, help_text="Bật để tự động quét 2 lần/ngày bằng Cron")
    auto_scan_time = models.TimeField(null=True, blank=True, help_text="Bỏ trống để chạy mặc định (00:00 & 12:00) hoặc đặt giờ quét cụ thể")
    scrape_status = models.CharField(max_length=20, default='idle', help_text="idle, running, completed, error")
    last_scraped_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class HotPost(models.Model):
    page = models.ForeignKey(ObservedPage, on_delete=models.CASCADE, related_name='posts')
    post_url = models.URLField(max_length=1000, help_text="Link bài viết")
    content_snippet = models.TextField(blank=True, null=True, help_text="Một đoạn nội dung bài viết")
    posted_at = models.DateTimeField(help_text="Thời gian đăng bài ước tính")
    
    likes_count = models.IntegerField(default=0)
    comments_count = models.IntegerField(default=0)
    shares_count = models.IntegerField(default=0)
    total_engagement = models.IntegerField(default=0, help_text="Tổng lượt tương tác (Like + Cmt + Share)")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['page', 'post_url'], name='unique_post_per_page')
        ]

    def save(self, *args, **kwargs):
        self.total_engagement = self.likes_count + self.comments_count + self.shares_count
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.page.name} - {self.total_engagement} engagements"

