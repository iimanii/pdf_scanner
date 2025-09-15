import os
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# SQLAlchemy
engine = None
SessionLocal = None     # session factory
Base = declarative_base()

def init_database_url(url):
    """Set database URL directly"""
    global engine, SessionLocal
    engine = create_engine(url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    print(f"Connected to PostgreSQL")

# Task model (matches the init.sql schema)
class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    user_description = Column(String(500), nullable=False)
    original_filename = Column(String(255), nullable=False)
    stored_file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=False, unique=True, index=True)
    file_size_bytes = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    error_message = Column(Text, nullable=True)
    scan_report_path = Column(String(500), nullable=True)
    virustotal_id = Column(String(100), nullable=True)
    virustotal_url = Column(String(500), nullable=True)
    worker_heartbeat = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def get_db():
    """
    Get database session for FastAPI dependency injection.
    Creates a new session for each request and ensures it gets closed.
    """
    db = SessionLocal()  # Create new session
    try:
        yield db  # Provide session to the request
    finally:
        db.close()  # Always close session when request is done

def get_db_session():
    """
    Get database session directly (for worker or other non-FastAPI code).
    Remember to close the session manually!
    """
    return SessionLocal()