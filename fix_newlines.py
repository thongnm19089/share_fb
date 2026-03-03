path = '/home/lit/prj/share_fb/automation/templates/automation/task_manager.html'
with open(path, 'rb') as f:
    content = f.read().decode('utf-8')

import re
# Replace any whitespace/newlines between {{ and c_task with just a space
content = re.sub(
    r'\{\{\s*c_task\.run_at\|date:"d/m/Y H:i"\s*\}\}',
    r'{{ c_task.run_at|date:"d/m/Y H:i" }}',
    content
)

with open(path, 'wb') as f:
    f.write(content.encode('utf-8'))
