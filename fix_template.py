import os

path = '/home/lit/prj/share_fb/automation/templates/automation/task_manager.html'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the multi-line template code with single line
old_str = """                            <td><span class="text-success"><i class="fas fa-check me-1"></i> {{
                                    c_task.run_at|date:"d/m/Y H:i" }}</span></td>"""

new_str = """                            <td><span class="text-success"><i class="fas fa-check me-1"></i> {{ c_task.run_at|date:"d/m/Y H:i" }}</span></td>"""

if old_str in content:
    content = content.replace(old_str, new_str)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed via full match!")
else:
    # Try more aggressive replace
    import re
    content = re.sub(
        r'<td><span class="text-success"><i class="fas fa-check me-1"></i> \{\{\s*c_task\.run_at\|date:"d/m/Y H:i"\s*\}\}</span></td>',
        r'<td><span class="text-success"><i class="fas fa-check me-1"></i> {{ c_task.run_at|date:"d/m/Y H:i" }}</span></td>',
        content,
        flags=re.MULTILINE | re.DOTALL
    )
    # Also handle the broken state if sed messed it up
    content = re.sub(
        r'c_task\.run_at\|date:"d/m/Y H:i" \}\}</span></td>\n?',
        r'',
        content,
        flags=re.MULTILINE
    )
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("Fixed via regex!")

