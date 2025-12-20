import streamlit as st
from sqlalchemy.orm import Session
from database_models import User, AthleteProfile, init_db, SportTypeEnum, SexEnum, RunLogicModeEnum

class DBManager:
    def __init__(self):
        # Inizializza il motore (crea il file .db se non esiste)
        self.engine = init_db("sqlite:///glicogeno.db")
    
    def get_session(self):
        return Session(self.engine)

    def get_or_create_user_profile(self, email: str):
        """
        Recupera il profilo dal DB. Se non esiste, crea un utente 'vergine' 
        con i default che avevi nel codice originale.
        """
        with self.get_session() as session:
            user = session.query(User).filter_by(email=email).first()
            
            if not user:
                # CREAZIONE NUOVO UTENTE (Se è la prima volta)
                user = User(email=email)
                # Profilo con i tuoi DEFAULT originali
                profile = AthleteProfile(
                    weight_kg=70.0, height_cm=175, body_fat_pct=12.0,
                    ftp_watts=250, threshold_hr=170, max_hr=185,
                    vo2_max=55.0, vla_max=0.5,
                    preferred_sport=SportTypeEnum.CYCLING
                )
                user.profile = profile
                session.add(user)
                session.commit()
                # Ricarichiamo per averlo pulito
                user = session.query(User).filter_by(email=email).first()
            
            # Restituiamo un dizionario (più facile da gestire in Streamlit)
            # Nota: SQLAlchemy restituisce oggetti, ma per Streamlit è meglio lavorare con dict
            # per evitare problemi di sessione chiusa.
            p = user.profile
            return {
                "id": user.id,
                "weight": p.weight_kg,
                "height": p.height_cm,
                "fat": p.body_fat_pct,
                "ftp": p.ftp_watts,
                "vo2": p.vo2_max,
                "vla": p.vla_max,
                "sport": p.preferred_sport.value, # Stringa
                "run_mode": p.run_logic_mode.value
                # ... aggiungi qui gli altri campi se servono
            }

    def update_profile(self, user_id, data_dict):
        """Salva le modifiche nel DB"""
        with self.get_session() as session:
            profile = session.query(AthleteProfile).filter_by(user_id=user_id).first()
            if profile:
                profile.weight_kg = data_dict.get('weight')
                profile.height_cm = data_dict.get('height')
                profile.body_fat_pct = data_dict.get('fat')
                profile.ftp_watts = data_dict.get('ftp')
                profile.vo2_max = data_dict.get('vo2')
                profile.vla_max = data_dict.get('vla')
                
                # Conversione Enum
                if 'sport' in data_dict:
                    profile.preferred_sport = SportTypeEnum(data_dict['sport'])
                
                session.commit()
                return True
        return False
