from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from config import DATABASE_URI

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    discord_id = Column(String(255), unique=True, nullable=False)  # Specify length for VARCHAR
    username = Column(String(255), nullable=False)  # Specify length for VARCHAR

class Deck(Base):
    __tablename__ = 'decks'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    name = Column(String(255), nullable=False)
    archetype_id = Column(Integer, ForeignKey('deck_archetypes.id'))
    archetype = relationship('DeckArchetype')
    user = relationship('User', back_populates='decks')
class DeckArchetype(Base):
    __tablename__ = 'deck_archetypes'
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    key_cards = Column(String(2000), nullable=False) #Seperate cards by commas
class Match(Base):
    __tablename__ = 'matches'
    id = Column(Integer, primary_key=True)
    deck_id = Column(Integer, ForeignKey('decks.id'))
    result = Column(String(255), nullable=False)
    opponent_archetype = Column(String(255), nullable=False)  
    player = Column(String(255), nullable=False)  
    deck = relationship('Deck', back_populates='matches')
    
User.decks = relationship('Deck', order_by=Deck.id, back_populates='user')
Deck.matches = relationship('Match', order_by=Match.id, back_populates='deck')

engine = create_engine(DATABASE_URI)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
