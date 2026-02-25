from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('accounts/add/', views.add_account, name='add_account'),
    path('groups/', views.group_list, name='group_list'),
    path('groups/add/', views.add_group, name='add_group'),
    path('campaigns/', views.campaign_list, name='campaign_list'),
    path('campaigns/add/', views.add_campaign, name='add_campaign'),
    path('campaigns/<int:campaign_id>/run/', views.run_campaign, name='run_campaign'),
    
    # Hot Posts feature
    path('pages/', views.page_list, name='page_list'),
    path('pages/add/', views.add_page, name='add_page'),
    path('pages/<int:page_id>/scrape/', views.scrape_page_view, name='scrape_page'),
    path('pages/scrape-all/', views.scrape_all_pages_view, name='scrape_all_pages'),
    path('hot-posts/', views.hot_post_list, name='hot_post_list'),
    
    # API Endpoints
    path('api/scrape/start/', views.api_start_scrape, name='api_start_scrape'),
    path('api/scrape/status/<str:job_id>/', views.api_scrape_status, name='api_scrape_status'),
]
