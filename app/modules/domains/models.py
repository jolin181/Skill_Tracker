
from sqlalchemy import Column, Integer, String, Boolean, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from app.core.database import Base
from datetime import datetime

class Track(Base):
    __tablename__ = 'tracks'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    description = Column(Text)
    is_active = Column(Boolean, default=True)

class Level(Base):
    __tablename__ = 'levels'
    id = Column(Integer, primary_key=True)
    track_id = Column(Integer, ForeignKey('tracks.id'))
    level_no = Column(Integer)
    name = Column(String)
    description = Column(Text)

class Topic(Base):
    __tablename__ = 'topics'
    id = Column(Integer, primary_key=True)
    level_id = Column(Integer, ForeignKey('levels.id'))
    name = Column(String)
    description = Column(Text)
    sequence_no = Column(Integer)
    is_optional = Column(Boolean, default=False)

class Subtopic(Base):
    __tablename__ = 'subtopics'
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey('topics.id'))
    name = Column(String)
    description = Column(Text)
    sequence_no = Column(Integer)

class TrackSyllabus(Base):
    """
    Stores uploaded syllabus PDFs and their extracted text content for tracks.

    A track can have multiple syllabi over time (version history).
    Only one syllabus per track is marked as current (is_current=True).
    """
    __tablename__ = 'track_syllabi'

    # Primary key
    id = Column(Integer, primary_key=True)

    # Foreign keys
    track_id = Column(Integer, ForeignKey('tracks.id'), nullable=False, index=True)
    uploaded_by = Column(Integer, ForeignKey('users.id'), nullable=False)

    # File metadata
    file_name = Column(String(255), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    page_count = Column(Integer, nullable=True)

    # Extracted content (CORE FIELD for AI consumption)
    raw_text = Column(Text, nullable=False)

    # Version tracking
    is_current = Column(Boolean, default=True, nullable=False, index=True)
    status = Column(String(50), default='active', nullable=False)  # active, replaced, archived

    # Timestamps
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    replaced_at = Column(DateTime, nullable=True)

    # Optional notes
    notes = Column(Text, nullable=True)

    # Relationships (for querying, using string names to avoid circular imports)
    track = relationship("Track", backref="syllabi")
    # uploader relationship would reference User model from app.modules.users
