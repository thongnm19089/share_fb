import threading
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from .models import FacebookAccount, FacebookGroup, ShareCampaign, ShareLog, ObservedPage, HotPost
from .core.fb_bot import FacebookBot
from .core.hot_post_scraper import HotPostScraper

def dashboard(request):
    accounts = FacebookAccount.objects.all()
    groups = FacebookGroup.objects.all()
    campaigns = ShareCampaign.objects.all()
    recent_logs = ShareLog.objects.order_by('-created_at')[:10]
    return render(request, 'automation/dashboard.html', {
        'accounts': accounts,
        'groups': groups,
        'campaigns': campaigns,
        'recent_logs': recent_logs
    })

def add_account(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        cookies = request.POST.get('cookies')
        status = request.POST.get('status', 'live')
        FacebookAccount.objects.create(name=name, cookies=cookies, status=status)
        messages.success(request, 'Thêm tài khoản thành công!')
        return redirect('dashboard')
    return render(request, 'automation/add_account.html')

def group_list(request):
    groups = FacebookGroup.objects.all()
    return render(request, 'automation/group_list.html', {'groups': groups})

def add_group(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        group_id = request.POST.get('group_id')
        url = request.POST.get('url')
        FacebookGroup.objects.create(name=name, group_id=group_id, url=url)
        messages.success(request, 'Thêm group thành công!')
        return redirect('group_list')
    return render(request, 'automation/add_group.html')

def campaign_list(request):
    campaigns = ShareCampaign.objects.all()
    return render(request, 'automation/campaign_list.html', {'campaigns': campaigns})

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
            comment_content=comment_content
        )
        if account_ids:
            campaign.accounts.set(account_ids)
        if group_ids:
            campaign.groups.set(group_ids)
            
        messages.success(request, 'Tạo chiến dịch thành công!')
        return redirect('campaign_list')
        
    accounts = FacebookAccount.objects.filter(status='live')
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

def run_campaign(request, campaign_id):
    campaign = get_object_or_404(ShareCampaign, id=campaign_id)
    # Start the campaign in a background thread to avoid blocking the HTTP response
    thread = threading.Thread(target=check_and_run_campaign, args=(campaign.id,))
    thread.daemon = True
    thread.start()
    
    messages.info(request, f'Chiến dịch "{campaign.name}" đang được chạy ngầm. Vui lòng theo dõi Dashboard để xem log.')
    return redirect('campaign_list')

# --- Hot Posts Feature Views ---

def page_list(request):
    pages = ObservedPage.objects.all()
    return render(request, 'automation/page_list.html', {'pages': pages})

def add_page(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        url = request.POST.get('url')
        ObservedPage.objects.create(name=name, url=url)
        messages.success(request, 'Thêm Page thành công!')
        return redirect('page_list')
    return render(request, 'automation/add_page.html')

import uuid
from django.http import JsonResponse

# Global in-memory store for scraping jobs
# Format: { 'job_id': { 'status': 'running'|'completed'|'error', 'progress': 0..100, 'results': [], 'error': '' } }
SCRAPE_JOBS = {}

def run_scrape_job_thread(job_id, page_ids, account_cookies):
    job = SCRAPE_JOBS[job_id]
    total_pages = len(page_ids)
    
    try:
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

                results = scraper.scrape_page(account_cookies, page.url, progress_callback=progress_cb)
                
                for p in results:
                    p['page_name'] = page.name # attach page info for the frontend
                    p['content_snippet'] = p.get('caption', '') # pass caption to frontend
                    # Convert datetime to ISO string for JSON serialization
                    if p.get('posted_at'):
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

def api_start_scrape(request):
    account = FacebookAccount.objects.filter(status='live').first()
    if not account:
        return JsonResponse({'status': 'error', 'message': 'Cần ít nhất 1 tài khoản FB Live để cào dữ liệu!'}, status=400)
    
    page_id_to_scrape = request.GET.get('page_id')
    pages_to_scrape = []
    if page_id_to_scrape:
        pages_to_scrape = [int(page_id_to_scrape)]
    else:
        pages_to_scrape = list(ObservedPage.objects.values_list('id', flat=True))
        
    if not pages_to_scrape:
        return JsonResponse({'status': 'error', 'message': 'Không có Page nào để quét!'}, status=400)
        
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

def api_scrape_status(request, job_id):
    if job_id not in SCRAPE_JOBS:
        return JsonResponse({'status': 'error', 'message': 'Invalid Job ID'}, status=404)
        
    job = SCRAPE_JOBS[job_id]
    
    response_data = {
        'status': job['status'],
        'progress': job['progress'],
    }
    
    if job['status'] in ('completed', 'error'):
        # Send results and then we can optionally delete from memory after some time
        # For simplicity, we just return them and let them live loosely in dict
        if job['status'] == 'completed':
            # Sort results by total_engagement descending
            sorted_results = sorted(job['results'], key=lambda x: x.get('total_engagement', 0), reverse=True)
            response_data['results'] = sorted_results
        else:
            response_data['error'] = job['error']
            
    return JsonResponse(response_data)

# Kept for simple page redirects but now unused fundamentally
def scrape_page_view(request, page_id):
    return redirect('hot_post_list')

def scrape_all_pages_view(request):
    return redirect('hot_post_list')

def hot_post_list(request):
    # Posts are now fetched live via frontend JS and API.
    return render(request, 'automation/hot_post_list.html')
