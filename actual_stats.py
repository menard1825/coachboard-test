from collections import defaultdict


def calculate_actual_position_game_stats(roster_players, rotations, rotation_events):
    """Count games in which each player actually appeared at each position.

    Live Game events are preferred when a game has them. Older games that have no
    live history fall back to their saved defensive rotation. Unassigned rotation
    templates are never counted as games.
    """
    stats = {player.name: {} for player in roster_players}
    events_by_game = defaultdict(list)
    for event in rotation_events or []:
        if event.game_id and not event.reverted:
            events_by_game[event.game_id].append(event)

    for game_events in events_by_game.values():
        game_events.sort(key=lambda event: (event.sequence or 0, event.id or 0))

    counted_games = set()
    for rotation in rotations or []:
        game_id = rotation.associated_game_id
        if not game_id or game_id in counted_games:
            continue

        alignments = []
        game_events = events_by_game.get(game_id, [])
        if game_events:
            for event in game_events:
                if isinstance(event.before_alignment, dict) and event.before_alignment:
                    alignments.append(event.before_alignment)
                if isinstance(event.after_alignment, dict) and event.after_alignment:
                    alignments.append(event.after_alignment)
        else:
            innings = rotation.innings or {}
            if isinstance(innings, dict):
                alignments.extend(
                    alignment for alignment in innings.values()
                    if isinstance(alignment, dict) and alignment
                )

        # A player-position pair counts once per game, matching the existing
        # "Games Played by Position" table rather than counting innings.
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

        counted_games.add(game_id)

    return stats
