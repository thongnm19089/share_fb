path = '/home/lit/prj/share_fb/automation/templates/automation/task_manager.html'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'c_task.run_at|date' in line:
        # We found the broken line. Let's look at the previous line
        if '{{' in lines[i-1]:
            # Merge them
            lines[i-1] = lines[i-1].rstrip() + ' ' + line.lstrip()
            lines[i] = ''

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
