import re

def _parse_time_string(raw):
    s = (raw or '').lower().strip()
    print(f"Testing: {s}")
    
    m = re.search(r'(\d+)\s*(giờ|gr|hrs?|h)\b', s)
    if m:
        print(f"Matched hour: {m.group(1)}")
    else:
        print("No hour match")
        
_parse_time_string("5 giờ·phim hay kể dễ nhớ")
_parse_time_string("5 giờ")
_parse_time_string("15h")
