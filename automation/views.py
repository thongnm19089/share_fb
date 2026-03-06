import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from .models import FacebookAccount, FacebookGroup, ShareCampaign, ShareLog, ObservedPage, HotPost
from .core.fb_bot import FacebookBot
from .core.hot_post_scraper import HotPostScraper
import uuid
from django.http import JsonResponse
import logging
from automation.tasks import scrape_page_background_task
from background_task.models import Task, CompletedTask
from django.core.management import call_command
from background_task import background
from django.db.models.functions import TruncDate
from django.db.models import F

logger = logging.getLogger(__name__)

@background(schedule=0)
def global_auto_scan_task():
    """
    Task chạy ngầm để gọi kịch bản quét toàn bộ như Cronjob
    """
    call_command('run_auto_scan')

@login_required
def dashboard(request):
    accounts = FacebookAccount.objects.filter(user=request.user)
    groups = FacebookGroup.objects.all()
    campaigns = ShareCampaign.objects.filter(user=request.user)
    recent_logs = ShareLog.objects.filter(campaign__user=request.user).order_by('-created_at')[:10]
    return render(request, 'automation/dashboard.html', {
        'accounts': accounts,
        'groups': groups,
        'campaigns': campaigns,
        'recent_logs': recent_logs
    })

@login_required
def add_account(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        cookies = request.POST.get('cookies')
        status = request.POST.get('status', 'live')
        FacebookAccount.objects.create(name=name, cookies=cookies, status=status, user=request.user)
        messages.success(request, 'Thêm tài khoản thành công!')
        return redirect('dashboard')
    return render(request, 'automation/add_account.html')

@login_required
def auto_login(request):
    if request.method == 'POST':
        uid = request.POST.get('uid')
        password = request.POST.get('password')
        two_fa = request.POST.get('two_fa')
        
        from .core.fb_login import FBAutoLogin
        auto_logger = FBAutoLogin(headless=True)
        success, result = auto_logger.login_and_get_cookies(uid, password, two_fa)
        
        if success:
            FacebookAccount.objects.create(name=f"{uid} (Auto)", cookies=result, status='live', user=request.user)
            messages.success(request, 'Đăng nhập tự động thành công và đã lưu Cookies!')
            return redirect('dashboard')
        else:
            messages.error(request, f'Lỗi đăng nhập: {result}')
            return redirect('auto_login')

    return render(request, 'automation/auto_login.html')

@login_required
def group_list(request):
    groups = FacebookGroup.objects.all()
    return render(request, 'automation/group_list.html', {'groups': groups})

@login_required
def add_group(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        group_id = request.POST.get('group_id')
        url = request.POST.get('url')
        FacebookGroup.objects.create(name=name, group_id=group_id, url=url)
        messages.success(request, 'Thêm group thành công!')
        return redirect('group_list')
    return render(request, 'automation/add_group.html')

@login_required
def campaign_list(request):
    campaigns = ShareCampaign.objects.filter(user=request.user)
    return render(request, 'automation/campaign_list.html', {'campaigns': campaigns})

@login_required
def add_campaign(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        link_to_share = request.POST.get('link_to_share')
        comment_content = request.POST.get('comment_content')
        account_ids = request.POST.getlist('accounts')
        group_ids = request.POST.getlist('groups')
        
        campaign = ShareCampaign.objects.create(
            name=name, 
            link_to_share=link_to_share, 
            comment_content=comment_content,
            user=request.user
        )
        if account_ids:
            campaign.accounts.set(account_ids)
        if group_ids:
            campaign.groups.set(group_ids)
            
        messages.success(request, 'Tạo chiến dịch thành công!')
        return redirect('campaign_list')
        
    accounts = FacebookAccount.objects.filter(status='live', user=request.user)
    groups = FacebookGroup.objects.all()
    initial_link = request.GET.get('link', '')
    return render(request, 'automation/add_campaign.html', {
        'accounts': accounts, 
        'groups': groups,
        'initial_link': initial_link
    })

def check_and_run_campaign(campaign_id):
    try:
        from django.db import connection
        connection.close() # Ensure fresh db connection in thread
        
        campaign = ShareCampaign.objects.get(id=campaign_id)
        bot = FacebookBot(headless=True)
        
        for account in campaign.accounts.all():
            for group in campaign.groups.all():
                log = ShareLog.objects.create(
                    campaign=campaign,
                    account=account,
                    group=group,
                    status='pending'
                )
                
                success, error_msg, shared_url = bot.share_post_to_group(
                    account.cookies, 
                    group.url, 
                    campaign.link_to_share, 
                    campaign.comment_content
                )
                
                if success:
                    log.status = 'success'
                    log.shared_post_url = shared_url
                else:
                    log.status = 'failed'
                    log.error_message = error_msg
                log.save()
    except Exception as e:
        print(f"Error running campaign thread: {e}")

@login_required
def run_campaign(request, campaign_id):
    campaign = get_object_or_404(ShareCampaign, id=campaign_id, user=request.user)
    # Start the campaign in a background thread to avoid blocking the HTTP response
    thread = threading.Thread(target=check_and_run_campaign, args=(campaign.id,))
    thread.daemon = True
    thread.start()
    
    messages.info(request, f'Chiến dịch "{campaign.name}" đang được chạy ngầm. Vui lòng theo dõi Dashboard để xem log.')
    return redirect('campaign_list')

# --- Hot Posts Feature Views ---

@login_required
def page_list(request):
    pages = ObservedPage.objects.filter(user=request.user)
    return render(request, 'automation/page_list.html', {'pages': pages})

@login_required
def add_page(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        url = request.POST.get('url')
        is_auto_scan = request.POST.get('is_auto_scan') == 'on'
        auto_scan_time = request.POST.get('auto_scan_time')
        if not auto_scan_time: 
            auto_scan_time = None
            
        ObservedPage.objects.create(name=name, url=url, user=request.user, is_auto_scan=is_auto_scan, auto_scan_time=auto_scan_time)
        messages.success(request, 'Thêm Page thành công!')
        return redirect('page_list')
    return render(request, 'automation/add_page.html')

@login_required
def api_start_scrape(request):
    try:
        pages = ObservedPage.objects.filter(user=request.user)
        if not pages.exists():
            return JsonResponse({'status': 'error', 'message': 'Không có Fanpage nào để quét. Vui lòng thêm Fanpage trước.'})
            
        account = FacebookAccount.objects.filter(user=request.user, status='live').first()
        if not account:
            return JsonResponse({'status': 'error', 'message': 'Không có tài khoản Facebook Live nào để quét.'})

        # Dùng 'queued' để phân biệt: "đã đưa vào queue nhưng chưa bắt đầu"
        # Chỉ xếp hàng cho các page chưa ở trạng thái queued hoặc running
        count_enqueued = 0
        for p in pages:
            if p.scrape_status not in ['queued', 'running']:
                p.scrape_status = 'queued'
                p.save()
                scrape_page_background_task(p.id, request.user.id)
                count_enqueued += 1
            
        if count_enqueued == 0:
            return JsonResponse({'status': 'success', 'message': 'Các Fanpage đã nằm trong hàng đợi hoặc đang quét rồi.', 'job_id': 'global'})

        return JsonResponse({'status': 'success', 'job_id': 'global'})
            
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def api_scrape_status(request, job_id):
    # Tính % tiến độ dựa trên scrape_status trong Database
    try:
        pages = ObservedPage.objects.filter(user=request.user)
        total_pages = pages.count()
        if total_pages == 0:
            return JsonResponse({'status': 'completed', 'progress': 100})
        
        # In progress = queued + running
        in_progress = pages.filter(scrape_status__in=['queued', 'running']).count()
        pages_done = total_pages - in_progress
        progress = int((pages_done / total_pages) * 100)
        
        status = 'running' if in_progress > 0 else 'completed'
            
        return JsonResponse({
            'status': status,
            'progress': progress,
            'total_pages': total_pages,
            'pages_done': pages_done
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'error': str(e)})

@login_required
def api_cancel_scrape(request):
    """
    Hủy khẩn cấp toàn bộ các tiến trình quét đang chạy cho User hiện tại từ Dashboard.
    """
    if request.method == 'POST':
        try:
            import subprocess
            user_pages = ObservedPage.objects.filter(user=request.user, scrape_status__in=['queued', 'running'])
            if user_pages.exists():
                user_pages.update(scrape_status='error')
                
                # Dọn dẹp background tasks queue
                Task.objects.all().delete()
                
                # Ép đóng worker giống như ở Task Manager
                cmd = "pkill -9 -f 'manage.py process_tasks'; pkill -9 -f 'chrome-headless'; pkill -9 -f 'playwright'; sleep 1; nohup /root/app/share_fb/venv/bin/python /root/app/share_fb/manage.py process_tasks > /var/log/process_tasks.log 2>&1 &"
                subprocess.Popen(cmd, shell=True, executable='/bin/bash')
                
            return JsonResponse({'status': 'success', 'message': 'Đã hủy thành công tiến trình quét.'})
        except Exception as e:
            logger.error(f"Error canceling scrape: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)})
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'})

@login_required
def scrape_page_view(request, page_id):
    return redirect('hot_post_list')

@login_required
def scrape_all_pages_view(request):
    return redirect('hot_post_list')

@login_required
def hot_post_list(request):
    latest_page = ObservedPage.objects.order_by('-last_scraped_at').first()
    is_scraping_active = ObservedPage.objects.filter(user=request.user, scrape_status__in=['queued', 'running']).exists()
    context = {
        'latest_scraped_at': latest_page.last_scraped_at if latest_page else None,
        'is_scraping_active': is_scraping_active
    }
    return render(request, 'automation/hot_post_list.html', context)

@login_required
def api_get_posts(request):
    try:
        page = int(request.GET.get('page', 1))
    except ValueError:
        page = 1
    
    sort_by = request.GET.get('sort', 'engagement')
    
    limit = 12
    offset = (page - 1) * limit
    
    posts_qs = HotPost.objects.filter(page__user=request.user)
    
    # Annotate with post_date for grouping
    posts_qs = posts_qs.annotate(
        post_date=TruncDate('posted_at')
    )
    
    if sort_by == 'time':
        # Sort by newest day first, then newest post
        posts_qs = posts_qs.order_by(F('post_date').desc(nulls_last=True), '-posted_at')
    else: 
        # Default: Sort by newest day first, then highest engagement
        posts_qs = posts_qs.order_by(F('post_date').desc(nulls_last=True), '-total_engagement')
        
    total_posts = posts_qs.count()
    posts_slice = posts_qs[offset:offset+limit]
    
    results = []
    for p in posts_slice:
        date_str = None
        if hasattr(p, 'post_date') and p.post_date:
            date_str = p.post_date.isoformat()
        elif p.posted_at:
            date_str = p.posted_at.date().isoformat()
            
        results.append({
            'page_name': p.page.name,
            'content_snippet': p.content_snippet,
            'post_url': p.post_url,
            'posted_at': p.posted_at.isoformat() if p.posted_at else None,
            'post_date': date_str, # Ngày đã rút gọn để Frontend nhóm
            'likes': p.likes_count,
            'comments': p.comments_count,
            'shares': p.shares_count,
            'total_engagement': p.total_engagement
        })
        
    return JsonResponse({
        'status': 'ok',
        'results': results,
        'has_next': (offset + limit) < total_posts
    })

@login_required
def task_manager(request):
    """
    Giao diện Quản lý Background Task: Lên lịch và Xem Danh sách Tác vụ.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        schedule_time = request.POST.get('schedule_time') # YYYY-MM-DDTHH:MM
        repeat_option = request.POST.get('repeat_option') # e.g 'never', '3600' (hourly), '86400' (daily)
        
        if action == 'add_task':
            try:
                run_at = 0
                if schedule_time:
                    try:
                        run_at = timezone.datetime.fromisoformat(schedule_time)
                        if timezone.is_naive(run_at):
                            run_at = timezone.make_aware(run_at)
                    except ValueError:
                        pass
                
                # Check repeat option (in seconds)
                repeat_seconds = Task.NEVER
                if repeat_option and repeat_option.isdigit():
                    repeat_seconds = int(repeat_option)
                    
                global_auto_scan_task(schedule=run_at, repeat=repeat_seconds)
                
                messages.success(request, f"Đã lên lịch quét toàn bộ hệ thống thành công!")
            except Exception as e:
                messages.error(request, f"Lỗi tạo Job: {str(e)}")
                
        elif action == 'delete_task':
            task_id = request.POST.get('task_id')
            if task_id:
                try:
                    Task.objects.filter(id=task_id).delete()
                    messages.success(request, f"Đã xóa Task #{task_id} thành công!")
                except Exception as e:
                    messages.error(request, f"Lỗi xóa Task: {str(e)}")
                    
        elif action == 'update_task':
            task_id = request.POST.get('task_id')
            update_time = request.POST.get('update_schedule_time')
            update_repeat = request.POST.get('update_repeat_option')
            if task_id and update_time:
                try:
                    task = Task.objects.get(id=task_id)
                    run_at = timezone.datetime.fromisoformat(update_time)
                    if timezone.is_naive(run_at):
                        run_at = timezone.make_aware(run_at)
                    task.run_at = run_at
                    
                    if update_repeat and update_repeat.isdigit():
                        task.repeat = int(update_repeat)
                    else:
                        task.repeat = Task.NEVER
                        
                    task.save()
                    messages.success(request, f"Đã cập nhật cấu hình cho Task #{task_id} thành công!")
                except Exception as e:
                    messages.error(request, f"Lỗi cập nhật Task: {str(e)}")
                    
        elif action == 'cancel_all_active':
            try:
                import subprocess
                # 1. Đưa các page đang treo về trạng thái lỗi/hủy
                ObservedPage.objects.filter(scrape_status__in=['queued', 'running']).update(scrape_status='error')
                
                # 2. Xóa trắng hàng đợi Background Tasks
                Task.objects.all().delete()
                
                # 3. Ép đóng (Kill) worker đang bị kẹt cùng với các tab Chrome ngầm, sau đó khởi động lại worker
                cmd = "pkill -9 -f 'manage.py process_tasks'; pkill -9 -f 'chrome-headless'; pkill -9 -f 'playwright'; sleep 1; nohup /root/app/share_fb/venv/bin/python /root/app/share_fb/manage.py process_tasks > /var/log/process_tasks.log 2>&1 &"
                subprocess.Popen(cmd, shell=True, executable='/bin/bash')
                
                messages.success(request, "Đã DỪNG KHẨN CẤP toàn bộ tiến trình quét đang chạy và làm mới hàng đợi!")
            except Exception as e:
                messages.error(request, f"Lỗi khi hủy tiến trình: {str(e)}")
        
        return redirect('task_manager')

    user_pages = ObservedPage.objects.filter(user=request.user).order_by('name')
    
    pending_tasks = Task.objects.all().order_by('run_at')
    completed_tasks = CompletedTask.objects.all().order_by('-run_at')[:20]
    
    # Get local aware server time and convert to Javascript-friendly ISO format
    server_time = timezone.localtime(timezone.now())
    
    context = {
        'user_pages': user_pages,
        'pending_tasks': pending_tasks,
        'completed_tasks': completed_tasks,
        'server_time_iso': server_time.isoformat()
    }
    return render(request, 'automation/task_manager.html', context)
