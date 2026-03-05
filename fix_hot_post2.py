import re
path = '/home/lit/prj/share_fb/automation/templates/automation/hot_post_list.html'

with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# Replace any newlines inside {{ ... }} or {% ... %} associated with latest_scraped_at
text = re.sub(r'\{\{\s*latest_scraped_at\|date:"d/m H:i"\s*\}\}', '{{ latest_scraped_at|date:"d/m H:i" }}', text, flags=re.MULTILINE)
text = re.sub(r'\{\%\s*if latest_scraped_at\s*\%\}', '{% if latest_scraped_at %}', text, flags=re.MULTILINE)
text = re.sub(r'\{\%\s*else\s*\%\}', '{% else %}', text, flags=re.MULTILINE)
text = re.sub(r'\{\%\s*endif\s*\%\}', '{% endif %}', text, flags=re.MULTILINE)

# Just to be absolutely sure, let's smash lines 4 to 15 into a single line
lines = text.splitlines()
new_lines = []
in_h5 = False
h5_buf = ""
for l in lines:
    if '<h5' in l:
        in_h5 = True
        h5_buf = l.strip()
    elif in_h5:
        h5_buf += " " + l.strip()
        if '</h5>' in l:
            in_h5 = False
            new_lines.append("            " + h5_buf)
    else:
        new_lines.append(l)

with open(path, 'w', encoding='utf-8') as f:
    f.write('\n'.join(new_lines))

