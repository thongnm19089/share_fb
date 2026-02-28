from django.contrib import admin
from .models import FacebookAccount, FacebookGroup, ShareCampaign, ShareLog, ObservedPage, HotPost
from .tasks import scrape_page_background_task
from django.contrib import messages

@admin.register(FacebookAccount)
class FacebookAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'created_at', 'updated_at')
    list_filter = ('status',)
    search_fields = ('name',)

@admin.register(FacebookGroup)
class FacebookGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'group_id', 'url')
    search_fields = ('name', 'group_id')

@admin.register(ShareCampaign)
class ShareCampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'link_to_share', 'created_at')
    search_fields = ('name', 'link_to_share')
    filter_horizontal = ('accounts', 'groups')

@admin.register(ShareLog)
class ShareLogAdmin(admin.ModelAdmin):
    list_display = ('campaign', 'account', 'group', 'status', 'created_at')
    list_filter = ('status', 'campaign')
    search_fields = ('campaign__name', 'account__name', 'group__name')

@admin.action(description='Lên Lịch Quét Bài Viết (Background Task)')
def queue_scan_tasks(modeladmin, request, queryset):
    count = 0
    for page in queryset:
        if page.user:
            scrape_page_background_task(page.id, page.user.id)
            page.scrape_status = 'queued'
            page.save()
            count += 1
    messages.success(request, f"Đã đưa {count} Fanpage vào hàng chờ Quét (Background Tasks).")

@admin.register(ObservedPage)
class ObservedPageAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'is_auto_scan', 'auto_scan_time', 'scrape_status', 'last_scraped_at')
    list_filter = ('is_auto_scan', 'scrape_status', 'user')
    search_fields = ('name', 'url')
    actions = [queue_scan_tasks]

@admin.register(HotPost)
class HotPostAdmin(admin.ModelAdmin):
    list_display = ('page', 'posted_at', 'total_engagement', 'likes_count', 'comments_count', 'shares_count')
    list_filter = ('page',)
    ordering = ('-total_engagement',)
