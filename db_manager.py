import streamlit as st
from sqlalchemy.orm import Session
from database_models import User, AthleteProfile, init_db, SportTypeEnum, SexEnum, RunLogicModeEnum
import os

class DBManager:
    def __init__(self):
        # 1. Cerchiamo la connessione nei Segreti di Streamlit
        if "general" in st.secrets and "DATABASE_URL" in st.secrets["general"]:
            db_url = st.secrets["general"]["DATABASE_URL"]
            
            # FIX PER SQLALCHEMY:
            # Le stringhe moderne usano 'postgres://', ma SQLAlchemy vuole 'postgresql://'
            if db_url.startswith("postgres://"):
                db_url = db_url.replace("postgres://", "postgresql://", 1)
                
            print("🔌 Connessione al Database Cloud (Neon/Postgres)...")
        else:
            # Fallback locale se non configurato
            db_url = "sqlite:///glicogeno.db"
            print("⚠️ Nessun Cloud DB trovato. Uso Database Locale (sqlite).")

        self.engine = init_db(db_url)
    
    def get_session(self):
        return Session(self.engine)

    def get_or_create_user_profile(self, email: str):
        with self.get_session() as session:
            user = session.query(User).filter_by(email=email).first()
            
            if not user:
                # CREAZIONE NUOVO UTENTE
                user = User(email=email)
                # Profilo con DEFAULT
                profile = AthleteProfile(
                    weight_kg=70.0, height_cm=175, body_fat_pct=12.0,
                    ftp_watts=250, threshold_hr=170, max_hr=185,
                    vo2_max=55.0, vla_max=0.5,
                    preferred_sport=SportTypeEnum.CYCLING
                )
                user.profile = profile
                session.add(user)
                session.commit()
                # Ricarica
                user = session.query(User).filter_by(email=email).first()
            
            p = user.profile
            return {
                "id": user.id,
                "weight": p.weight_kg,
                "height": p.height_cm,
                "fat": p.body_fat_pct,
                "ftp": p.ftp_watts,
                "vo2": p.vo2_max,
                "vla": p.vla_max,
                "sport": p.preferred_sport.value,
                "run_mode": p.run_logic_mode.value,
                # Aggiungiamo anche questi se servono per il salvataggio
                "sex": p.sex.value
            }

    def update_profile(self, user_id, data_dict):
        with self.get_session() as session:
            profile = session.query(AthleteProfile).filter_by(user_id=user_id).first()
            if profile:
                if 'weight' in data_dict: profile.weight_kg = data_dict['weight']
                if 'height' in data_dict: profile.height_cm = data_dict['height']
                if 'fat' in data_dict: profile.body_fat_pct = data_dict['fat']
                if 'ftp' in data_dict: profile.ftp_watts = data_dict['ftp']
                if 'vo2' in data_dict: profile.vo2_max = data_dict['vo2']
                if 'vla' in data_dict: profile.vla_max = data_dict['vla']
                
                if 'sport' in data_dict: 
                    profile.preferred_sport = SportTypeEnum(data_dict['sport'])
                if 'sex' in data_dict:
                    profile.sex = SexEnum(data_dict['sex'])
                
                session.commit()
                return True
        return False
