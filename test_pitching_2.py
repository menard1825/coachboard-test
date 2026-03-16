from datetime import date, timedelta, datetime
from collections import namedtuple
from utils import calculate_pitch_count_summary

MockPlayer = namedtuple('Player', ['id', 'name'])
MockOuting = namedtuple('Outing', ['player_id', 'date', 'pitches'])

today = date.today()
yesterday = today - timedelta(days=1)
day_before = today - timedelta(days=2)
tomorrow = today + timedelta(days=1)

players = [MockPlayer(1, "Player A"), MockPlayer(2, "Player B"), MockPlayer(3, "Player C"), MockPlayer(4, "Player D")]
rules = {'max_daily': 85, 'rest_thresholds': [(20, 0), (35, 1), (50, 2), (65, 3), (85, 4)]}

outings = [
    # A pitched yesterday 20, today 20.
    # Because of consecutive rule, tomorrow they require 1 day rest (so not available tomorrow). Today they ARE available.
    MockOuting(1, datetime.combine(yesterday, datetime.min.time()), 20),
    MockOuting(1, datetime.combine(today, datetime.min.time()), 20),

    # B pitched yesterday 40. Requires 2 days rest. Today they should be resting.
    MockOuting(2, datetime.combine(yesterday, datetime.min.time()), 40),

    # C pitched yesterday 85. Requires 4 days rest. Today they should be resting.
    MockOuting(3, datetime.combine(yesterday, datetime.min.time()), 85),

    # D pitches 85 today. Should be Resting today (0 pitches left).
    MockOuting(4, datetime.combine(today, datetime.min.time()), 85),
]

summary = calculate_pitch_count_summary(players, outings, rules)

for name, s in summary.items():
    print(f"{name}: status={s['status']}, next_available={s['next_available']}, pitches_remaining={s['pitches_remaining_today']}")
