import requests
session = requests.Session()
response = session.post('http://127.0.0.1:5002/login', data={'username': 'Mike1825', 'password': 'password'})
print("Login status:", response.status_code)

res = session.get('http://127.0.0.1:5002/api/game_data/1')
print("API status:", res.status_code)
if res.status_code != 200:
    print(res.text)

rot_data = {
    'title': 'Test Rotation',
    'innings': {'1': {}},
    'associated_game_id': 1
}
res2 = session.post('http://127.0.0.1:5002/save_rotation', json=rot_data)
print("Save rotation status:", res2.status_code)
if res2.status_code != 200:
    print(res2.text)
