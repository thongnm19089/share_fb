import re
path = '/home/lit/prj/share_fb/automation/templates/automation/hot_post_list.html'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Make the header text responsive and shorten the date format
new_header = '<h5 class="mb-0 fw-bold d-flex align-items-center">🔥 <span class="d-none d-sm-inline me-1">Bài Viết</span> Nổi Bật <span class="badge bg-light text-dark ms-2 border fw-normal shadow-sm text-truncate" style="font-size: 0.8rem; letter-spacing: -0.2px;"><i class="fas fa-clock text-muted"></i> <span class="d-none d-sm-inline">Cập nhật: </span>{% if latest_scraped_at %}{{ latest_scraped_at|date:"d/m H:i" }}{% else %}---{% endif %}</span></h5>'

# Extract the block to replace
content = re.sub(
    r'<h5 class="mb-0 fw-bold">🔥 Bài Viết Nổi Bật\s*<span\s*class="badge[^>]+>.*?</span></h5>',
    new_header,
    content,
    flags=re.DOTALL
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

