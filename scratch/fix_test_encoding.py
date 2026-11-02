with open('Ticketmitra/scratch/test_theatre_admin_system.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace("₹", "Rs. ")

with open('Ticketmitra/scratch/test_theatre_admin_system.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Replaced currency symbol in test script")

