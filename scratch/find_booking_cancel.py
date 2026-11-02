with open('Ticketmitra/movies/models.py', 'r', encoding='utf-8') as f:
    text = f.read()
target = 'def cancel('
idx = text.find(target)
if idx != -1:
    print(text[idx:idx+1000])

