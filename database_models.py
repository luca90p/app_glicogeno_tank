from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

# --- ENUMS ---
class SportTypeEnum(enum.Enum):
    CYCLING = "Cycling"
    RUNNING = "Running"

class SexEnum(enum.Enum):
    MALE = "Male"
    FEMALE = "Female"

class MenstrualPhaseEnum(enum.Enum):
    NONE = "None"
    FOLLICULAR = "Follicular"
    LUTEAL = "Luteal"

class RunLogicModeEnum(enum.Enum):
    PHYSIOLOGICAL = "Physiological"
    MECHANICAL = "Mechanical"

# --- TABELLA UTENTI ---
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True) 
    source_app = Column(String, default="standalone") 
    external_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    profile = relationship("AthleteProfile", back_populates="user", uselist=False)

# --- TABELLA PROFILO ATLETA ---
class AthleteProfile(Base):
    __tablename__ = 'athlete_profiles'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Sidebar
    preferred_sport = Column(Enum(SportTypeEnum), default=SportTypeEnum.CYCLING)
    run_logic_mode = Column(Enum(RunLogicModeEnum), default=RunLogicModeEnum.MECHANICAL)

    # Tab 1
    weight_kg = Column(Float, nullable=False)
    height_cm = Column(Integer, nullable=False)
    body_fat_pct = Column(Float, nullable=False)
    sex = Column(Enum(SexEnum), default=SexEnum.MALE)
    
    use_custom_muscle_mass = Column(Boolean, default=False)
    muscle_mass_kg = Column(Float, nullable=True)
    use_creatine = Column(Boolean, default=False)
    menstrual_phase = Column(Enum(MenstrualPhaseEnum), default=MenstrualPhaseEnum.NONE)

    # Performance
    ftp_watts = Column(Integer, default=250)
    threshold_hr = Column(Integer, default=170)
    max_hr = Column(Integer, default=185)

    # Morton
    cp_watts = Column(Integer, default=250)
    w_prime_joules = Column(Integer, default=20000)

    # Fisiologia
    vo2_max = Column(Float, default=55.0)
    vla_max = Column(Float, default=0.5)
    calculation_method = Column(String, default="manual")

    # Lab Data
    use_lab_data = Column(Boolean, default=False)
    lab_curve_json = Column(JSON, nullable=True) 

    user = relationship("User", back_populates="profile")

def init_db(db_url="sqlite:///glicogeno.db"):
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)
    return engine
