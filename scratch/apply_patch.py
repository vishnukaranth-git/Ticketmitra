import os

path = r'Ticketmitra\movies\admin_views.py'
with open(path, 'r', encoding='utf-8') as f:
    orig = f.read()

start_marker = '@staff_member_required\ndef visual_seat_map_view(request, theater_id=None, screen_id=None):'
end_marker = "def parse_analytics_date_filters(request):"

start_idx = orig.find(start_marker)
assert start_idx != -1, "start_marker not found"

end_idx = orig.find(end_marker, start_idx)
assert end_idx != -1, "end_marker not found"

with open(r'Ticketmitra\scratch\patch_seat_mgmt.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Extract new_code
s_pos = text.find("new_code = '''") + len("new_code = '''")
e_pos = text.find("'''\n\npath = r'Ticketmitra", s_pos)
new_code = text[s_pos:e_pos].strip()

updated = orig[:start_idx] + new_code + "\n\n\n" + orig[end_idx:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(updated)

print("admin_views.py successfully replaced!")
