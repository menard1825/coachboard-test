# db.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine('sqlite:///app.db', echo=False) # Changed to app.db
SessionLocal = sessionmaker(bind=engine)
