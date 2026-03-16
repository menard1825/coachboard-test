with open('blueprints/api.py', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith('from utils import model_to_dict'):
        line = 'from utils import model_to_dict, pitching_outing_to_dict, get_pitching_rules_for_team, calculate_pitch_count_summary, calculate_cumulative_pitching_stats, calculate_cumulative_position_stats\n'
    new_lines.append(line)

with open('blueprints/api.py', 'w') as f:
    f.writelines(new_lines)
