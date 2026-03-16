from datetime import date, timedelta, datetime
from collections import namedtuple
from utils import calculate_pitch_count_summary

MockPlayer = namedtuple('Player', ['id', 'name'])
MockOuting = namedtuple('Outing', ['player_id', 'date', 'pitches'])

today = date.today()
yesterday = today - timedelta(days=1)
day_before = today - timedelta(days=2)

players = [MockPlayer(1, "Player A"), MockPlayer(2, "Player B"), MockPlayer(3, "Player C")]
rules = {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]}

# A: Pitched yesterday 20, today 20. Expect required_rest = 1, next_available = tomorrow (resting today)
# B: Pitched yesterday 40. Expect required_rest = 2, next_available = tomorrow (resting today)
# C: Pitched today 20. Expect required_rest = 0, next_available = tomorrow (available today)

outings = [
    MockOuting(1, datetime.combine(yesterday, datetime.min.time()), 20),
    MockOuting(1, datetime.combine(today, datetime.min.time()), 20),
    MockOuting(2, datetime.combine(yesterday, datetime.min.time()), 40),
    MockOuting(3, datetime.combine(today, datetime.min.time()), 20),
]

summary = calculate_pitch_count_summary(players, outings, rules)

for name, s in summary.items():
    print(f"{name}: status={s['status']}, next_available={s['next_available']}, pitches_remaining={s['pitches_remaining_today']}")
