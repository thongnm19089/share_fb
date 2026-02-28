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

# Global in-memory store for scraping jobs
# Format: { 'job_id': { 'status': 'running'|'completed'|'error', 'progress': 0..100, 'results': [], 'error': '' } }
SCRAPE_JOBS = {}

def run_scrape_job_thread(job_id, page_ids, account_cookies):
    job = SCRAPE_JOBS[job_id]
    total_pages = len(page_ids)
    
    try:
        from django.db import connection, transaction
        connection.close() # Ensure fresh connection
        
        scraper = HotPostScraper(headless=True)
        # Update progress callback for scraper (we will pass a callable to the scraper to handle progress)
        for idx, page_id in enumerate(page_ids):
            # Update percentage per page
            base_progress = int((idx / total_pages) * 100)
            job['progress'] = base_progress
            
            try:
                page = ObservedPage.objects.get(id=page_id)
                page.scrape_status = 'running'
                page.save()
                
                # Setup a callback internally to let scraper update progress finely
                def progress_cb(pct):
                    # pct is 0-100 for this specific page
                    page_contribution = (pct / 100.0) * (100.0 / total_pages)
                    job['progress'] = base_progress + int(page_contribution)

                existing_urls = list(HotPost.objects.filter(page=page).values_list('post_url', flat=True)[:100])
                results = scraper.scrape_page(account_cookies, page.url, progress_callback=progress_cb, stop_urls=existing_urls)
                
                # Update saving logic to prevent dropping existing data and use update_or_create instead
                for p in results:
                    p['page_name'] = page.name # attach page info for the frontend
                    p['content_snippet'] = p.get('caption', '') # pass caption to frontend
                    # Convert datetime to ISO string for JSON serialization
                    if p.get('posted_at'):
                        try:
                            hot_post, created = HotPost.objects.update_or_create(
                                page=page,
                                post_url=p['post_url'],
                                defaults={
                                    'content_snippet': p['content_snippet'],
                                    'posted_at': p['posted_at'],
                                    'likes_count': p['likes'],
                                    'comments_count': p['comments'],
                                    'shares_count': p['shares']
                                }
                            )
                        except Exception as save_err:
                            print(f"Error saving hotpost: {save_err}")
                            
                        p['posted_at'] = p['posted_at'].isoformat()
                    # Calculate total
                    p['total_engagement'] = p['likes'] + p['comments'] + p['shares']
                    job['results'].append(p)
                    
                page.scrape_status = 'completed'
                page.last_scraped_at = timezone.now()
                page.save()
            except Exception as e:
                print(f"Error scraping individual page {page_id}: {e}")
                try:
                    p_err = ObservedPage.objects.get(id=page_id)
                    p_err.scrape_status = 'error'
                    p_err.save()
                except: pass

        job['progress'] = 100
        job['status'] = 'completed'
    except Exception as e:
        print(f"Scrape job error: {e}")
        job['status'] = 'error'
        job['error'] = str(e)

@login_required
def api_start_scrape(request):
    account = FacebookAccount.objects.filter(status='live', user=request.user).first()
    if not account:
        return JsonResponse({'status': 'error', 'message': 'Cần ít nhất 1 tài khoản FB Live để cào dữ liệu!'}, status=400)
    
    page_id_to_scrape = request.GET.get('page_id')
    pages_to_scrape = []
    if page_id_to_scrape:
        # verify page belongs to user
        page_obj = ObservedPage.objects.filter(id=int(page_id_to_scrape), user=request.user).first()
        if page_obj:
            pages_to_scrape = [page_obj.id]
    else:
        pages_to_scrape = list(ObservedPage.objects.filter(user=request.user).values_list('id', flat=True))
        
    if not pages_to_scrape:
        return JsonResponse({'status': 'error', 'message': 'Không có Page nào thuộc sở hữu của bạn!'}, status=400)
        
    job_id = str(uuid.uuid4())
    SCRAPE_JOBS[job_id] = {
        'status': 'running',
        'progress': 0,
        'results': [],
        'error': ''
    }
    
    thread = threading.Thread(target=run_scrape_job_thread, args=(job_id, pages_to_scrape, account.cookies))
    thread.daemon = True
    thread.start()
    
    return JsonResponse({'status': 'running', 'job_id': job_id})

@login_required
def api_scrape_status(request, job_id):
    if job_id not in SCRAPE_JOBS:
        return JsonResponse({'status': 'error', 'message': 'Invalid Job ID'}, status=404)
        
    job = SCRAPE_JOBS[job_id]
    
    response_data = {
        'status': job['status'],
        'progress': job['progress'],
    }
    
    if job['status'] in ('completed', 'error'):
        if job['status'] == 'completed':
            sorted_results = sorted(job['results'], key=lambda x: x.get('total_engagement', 0), reverse=True)
            response_data['results'] = sorted_results
        else:
            response_data['error'] = job['error']
            
    return JsonResponse(response_data)

@login_required
def scrape_page_view(request, page_id):
    return redirect('hot_post_list')

@login_required
def scrape_all_pages_view(request):
    return redirect('hot_post_list')

@login_required
def hot_post_list(request):
    return render(request, 'automation/hot_post_list.html')

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
        
        return redirect('task_manager')

    user_pages = ObservedPage.objects.filter(user=request.user).order_by('name')
    
    pending_tasks = Task.objects.all().order_by('run_at')
    completed_tasks = CompletedTask.objects.all().order_by('-run_at')[:20]
    
    context = {
        'user_pages': user_pages,
        'pending_tasks': pending_tasks,
        'completed_tasks': completed_tasks
    }
    return render(request, 'automation/task_manager.html', context)
