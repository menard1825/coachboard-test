from collections import defaultdict
from datetime import datetime


def calculate_actual_position_game_stats(roster_players, rotations, rotation_events, games):
    """Count games in which each player appeared at each position.

    Live Game events are authoritative. Older games that predate Live Game can
    fall back to the saved rotation only after the game date has passed. Future
    plans and unassigned templates are never counted as games played.
    """
    stats = {player.name: {} for player in roster_players}
    events_by_game = defaultdict(list)
    rotations_by_game = {}
    games_by_id = {game.id: game for game in (games or [])}

    for event in rotation_events or []:
        if event.game_id and not event.reverted:
            events_by_game[event.game_id].append(event)
    for game_events in events_by_game.values():
        game_events.sort(key=lambda event: (event.sequence or 0, event.id or 0))

    for rotation in rotations or []:
        if rotation.associated_game_id:
            rotations_by_game.setdefault(rotation.associated_game_id, rotation)

    today = datetime.now().date()
    game_ids = set(events_by_game) | set(rotations_by_game)

    for game_id in game_ids:
        alignments = []
        game_events = events_by_game.get(game_id, [])

        if game_events:
            # The audit trail tells us what actually existed on the field. Include
            # both sides of changes so a position played before a substitution is
            # not lost when only the final alignment remains.
            for event in game_events:
                if isinstance(event.before_alignment, dict) and event.before_alignment:
                    alignments.append(event.before_alignment)
                if isinstance(event.after_alignment, dict) and event.after_alignment:
                    alignments.append(event.after_alignment)
        else:
            # Legacy fallback only. A game with no live history is not considered
            # played until its calendar date is in the past.
            game = games_by_id.get(game_id)
            rotation = rotations_by_game.get(game_id)
            if not game or not rotation or not game.date or game.date.date() >= today:
                continue
            innings = rotation.innings or {}
            if isinstance(innings, dict):
                alignments.extend(
                    alignment for alignment in innings.values()
                    if isinstance(alignment, dict) and alignment
                )

        seen_this_game = set()
        for alignment in alignments:
            for position, player_name in alignment.items():
                if not player_name or player_name not in stats:
                    continue
                key = (player_name, position)
                if key in seen_this_game:
                    continue
                stats[player_name][position] = stats[player_name].get(position, 0) + 1
                seen_this_game.add(key)

    return stats
