# db.py
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import MetaData

# Define a naming convention for constraints.
# This is crucial for Alembic's batch mode with SQLite.
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Create a MetaData instance with the naming convention
metadata = MetaData(naming_convention=convention)

# Pass the metadata to the SQLAlchemy constructor
db = SQLAlchemy(metadata=metadata)