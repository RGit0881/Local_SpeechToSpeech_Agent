# server/db.py
import os, datetime, uuid
from typing import Optional
from sqlalchemy import create_engine, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DB_PATH = os.getenv("DB_PATH", "/data/npcs.db")
engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False, future=True)

class Base(DeclarativeBase):
    pass

class NPC(Base):
    __tablename__ = "npc"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=False, index=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    persona: Mapped[str] = mapped_column(Text)  # system prompt / roleplay
    tone: Mapped[Optional[str]] = mapped_column(String(120), default=None)
    language: Mapped[str] = mapped_column(String(8), default="en")
    voice_ref: Mapped[Optional[str]] = mapped_column(String(512), default=None) # filename in /app/voices or absolute
    voice_path: Mapped[Optional[str]] = mapped_column(String(512), default=None) # stored per-NPC under /data/voices/{id}/voice.wav
    api_key: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="npc", cascade="all, delete-orphan")

class ChatSession(Base):
    __tablename__ = "chat_session"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    npc_id: Mapped[int] = mapped_column(ForeignKey("npc.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    npc: Mapped["NPC"] = relationship(back_populates="sessions")
    messages: Mapped[list["Message"]] = relationship(back_populates="session", cascade="all, delete-orphan")

class Message(Base):
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_session_id: Mapped[int] = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # "system" | "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")

def init_db():
    Base.metadata.create_all(engine)

def new_api_key() -> str:
    return uuid.uuid4().hex
