from app import create_app
from models import db, Rotation, Game

def clean_orphan_rotations():
    """
    Finds and deletes rotations that are associated with a game that no longer exists.
    """
    app = create_app()
    with app.app_context():
        # Get all game IDs that exist in the database
        existing_game_ids = {game.id for game in db.session.query(Game.id).all()}

        # Find all rotations that have an associated_game_id
        rotations_with_games = db.session.query(Rotation).filter(Rotation.associated_game_id.isnot(None)).all()

        orphans_found = []
        for rotation in rotations_with_games:
            if rotation.associated_game_id not in existing_game_ids:
                orphans_found.append(rotation)

        if not orphans_found:
            print("No orphan rotations found. Your database is clean!")
            return

        print(f"Found {len(orphans_found)} orphan rotation(s) to delete:")
        for orphan in orphans_found:
            print(f"  - Deleting Rotation ID: {orphan.id}, Title: '{orphan.title}', (was associated with non-existent Game ID: {orphan.associated_game_id})")
            db.session.delete(orphan)

        db.session.commit()
        print("\nOrphan rotations have been successfully deleted.")

if __name__ == '__main__':
    clean_orphan_rotations()