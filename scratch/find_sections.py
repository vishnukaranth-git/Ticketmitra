import os

home_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'home.html')
with open(home_path, 'r', encoding='utf-8') as f:
    content = f.read()

s1 = content.find('id="moviesSection"')
s2 = content.find('id="cinemas-around-you"')
s3 = content.find('id="upcomingSection"')
s4 = content.find('id="nowStreamingSection"')

print(f"moviesSection: {s1}, cinemas: {s2}, upcoming: {s3}, nowStreaming: {s4}")

