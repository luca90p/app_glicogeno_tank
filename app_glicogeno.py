import streamlit as st
import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum

# --- 1. PARAMETRI FISIOLOGICI (TANK MODEL) ---

class Sex(Enum):
    MALE = "Uomo"
    FEMALE = "Donna"

class TrainingStatus(Enum):
    SEDENTARY = (13.0, "Sedentario / Principiante")
    RECREATIONAL = (16.0, "Attivo / Amatore")
    TRAINED = (19.0, "Allenato (Intermedio)")
    ADVANCED = (22.0, "Avanzato / Competitivo")
    ELITE = (25.0, "Elite / Pro")

    def __init__(self, val, label):
        self.val = val
        self.label = label

class SportType(Enum):
    CYCLING = (0.63, "Ciclismo (Gambe)")
    RUNNING = (0.75, "Corsa (Gambe + Core)")
    TRIATHLON = (0.85, "Triathlon")
    XC_SKIING = (0.95, "Sci di Fondo")
    SWIMMING = (0.80, "Nuoto")

    def __init__(self, val, label):
        self.val = val
        self.label = label

# --- PARAMETRI FASE 2 (RIEMPIMENTO & STATO) ---
class DietType(Enum):
    HIGH_CARB = (1.0, "High Carb / Carico (>8g/kg)")
    NORMAL = (0.85, "Dieta Mista Standard")
    LOW_CARB = (0.50, "Low Carb / Keto (<3g/kg)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class FatigueState(Enum):
    RESTED = (1.0, "Riposo / Scarico (Tapering)")
    ACTIVE = (0.9, "Allenamento Leggero ieri")
    TIRED = (0.65, "Allenamento Pesante ieri (Non recuperato)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

# NUOVI PARAMETRI AVANZATI
class SleepQuality(Enum):
    GOOD = (1.0, "Ottimo (>7h, ristoratore)")
    AVERAGE = (0.95, "Sufficiente (6-7h)")
    POOR = (0.85, "Insufficiente (<6h o disturbato)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class MenstrualPhase(Enum):
    NONE = (1.0, "Non applicabile / Amenorrea")
    FOLLICULAR = (1.0, "Fase Follicolare (Giorni 1-14)")
    LUTEAL = (0.95, "Fase Luteale/Premestruale (Giorni 15-28)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

@dataclass
class Subject:
    weight_kg: float
    body_fat_pct: float
    sex: Sex
    glycogen_conc_g_kg: float
    sport: SportType
    liver_glycogen_g: float = 100.0
    
    # Parametri riempimento
    filling_factor: float = 1.0 
    
    # Parametri avanzati
    uses_creatine: bool = False
    menstrual_phase: MenstrualPhase = MenstrualPhase.NONE

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        base = 0.50 if self.sex == Sex.MALE else 0.42
        if self.glycogen_conc_g_kg >= 22.0:
            base += 0.03
        return base

# --- 2. MOTORE DI CALCOLO ---

def get_concentration_from_vo2max(vo2_max):
    """Calcola la densità di glicogeno (g/kg) dal VO2max."""
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

def calculate_tank(subject: Subject):
    lbm = subject.lean_body_mass
    total_muscle = lbm * subject.muscle_fraction
    active_muscle = total_muscle * subject.sport.val
    
    # 1. Capacità Teorica Massima (100% Full)
    # Include Bonus Creatina se presente (+10% capacità stoccaggio)
    creatine_multiplier = 1.10 if subject.uses_creatine else 1.0
    max_muscle_glycogen = active_muscle * subject.glycogen_conc_g_kg * creatine_multiplier
    
    # 2. Riempimento Reale
    # Include penalità mestruale (solo fase Luteale) nel filling factor
    final_filling_factor = subject.filling_factor * subject.menstrual_phase.factor
    
    current_muscle_glycogen = max_muscle_glycogen * final_filling_factor
    
    # Fegato
    current_liver_glycogen = subject.liver_glycogen_g
    if final_filling_factor <= 0.6: 
        current_liver_glycogen *= 0.6 
        
    total_actual_glycogen = current_muscle_glycogen + current_liver_glycogen
    max_total_glycogen = max_muscle_glycogen + 100.0 

    return {
        "active_muscle_kg": active_muscle,
        "max_capacity_g": max_total_glycogen,          
        "actual_available_g": total_actual_glycogen,   
        "muscle_glycogen_g": current_muscle_glycogen,
        "liver_glycogen_g": current_liver_glycogen,
        "concentration_used": subject.glycogen_conc_g_kg,
        "fill_pct": (total_actual_glycogen / max_total_glycogen) * 100 if max_total_glycogen > 0 else 0,
        "creatine_bonus": subject.uses_creatine
    }

def simulate_metabolism(tank_g, ftp_watts, avg_power, duration_min, carb_intake_g_h, crossover_pct):
    results = []
    current_glycogen = tank_g
    
    intensity_factor = avg_power / ftp_watts if ftp_watts > 0 else 0
    crossover_if = crossover_pct / 100.0
    
    kcal_per_min_total = (avg_power * 60) / 4184 / 0.22
    
    slope_k = 12.0
    
    if intensity_factor <= 0.2:
        cho_ratio = 0.10
    else:
        cho_ratio = 1 / (1 + np.exp(-slope_k * (intensity_factor - crossover_if)))
        if cho_ratio < 0.10: cho_ratio = 0.10
        if cho_ratio > 1.0: cho_ratio = 1.0
        if intensity_factor > 1.05:
            cho_ratio = 1.0

    fat_ratio = 1.0 - cho_ratio
    kcal_cho = kcal_per_min_total * cho_ratio
    kcal_fat = kcal_per_min_total * fat_ratio
    
    glycogen_burned_per_min = kcal_cho / 4.1
    fat_burned_per_min = kcal_fat / 9.0
    glycogen_intake_per_min = carb_intake_g_h / 60.0

    total_fat_burned_g = 0.0
    
    for t in range(int(duration_min) + 1):
        if t > 0:
            net_change = glycogen_intake_per_min - glycogen_burned_per_min
            current_glycogen += net_change
            total_fat_burned_g += fat_burned_per_min
        
        if current_glycogen < 0:
            current_glycogen = 0
            
        results.append({
            "Time (min)": t,
            "Glycogen (g)": current_glycogen,
            "Fat Burned (cumul)": total_fat_burned_g,
            "Cho %": cho_ratio * 100,
            "Fat %": fat_ratio * 100
        })
        
    stats = {
        "final_glycogen": current_glycogen,
        "cho_rate_g_h": glycogen_burned_per_min * 60,
        "fat_rate_g_h": fat_burned_per_min * 60,
        "kcal_total_h": kcal_per_min_total * 60,
        "cho_pct": cho_ratio * 100,
        "total_fat_g": total_fat_burned_g
    }

    return pd.DataFrame(results), stats

# --- 3. INTERFACCIA UTENTE ---

st.set_page_config(page_title="Glycogen Simulator", page_icon="⚡", layout="wide")

st.title("⚡ Glicogeno: Tank & Burn Simulator")
st.markdown("Stima il serbatoio, il livello di riempimento e simula il consumo in gara.")

tab1, tab2 = st.tabs(["1️⃣ Analisi Serbatoio", "2️⃣ Simulazione Gara"])

# --- TAB 1: CALCOLO SERBATOIO ---
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("1. Profilo Strutturale")
        weight = st.slider("Peso (kg)", 45.0, 100.0, 70.0, 0.5)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 15.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        # Selezione Metodo Stima
        estimation_method = st.radio("Metodo Stima VO2/Glicogeno:", ["Per Livello", "Per VO2max"], label_visibility="collapsed")
        
        if estimation_method == "Per Livello":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello Fitness", list(status_map.keys()), index=2)]
            calculated_conc = s_status.val
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 55, step=1)
            calculated_conc = get_concentration_from_vo2max(vo2_input)
            
            if calculated_conc < 15: lvl = "Sedentario"
            elif calculated_conc < 18: lvl = "Amatore"
            elif calculated_conc < 22: lvl = "Allenato"
            elif calculated_conc < 24: lvl = "Avanzato"
            else: lvl = "Elite"
            st.caption(f"Densità stimata: **{calculated_conc:.1f} g/kg** ({lvl})")

        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Sport", list(sport_map.keys()))]
        
        # PARAMETRI AVANZATI (Nuova Sezione)
        with st.expander("🔬 Parametri Avanzati (Creatina, Sonno, Ciclo)"):
            use_creatine = st.checkbox("Uso di Creatina", help="La creatina aumenta la ritenzione idrica muscolare e lo stoccaggio di glicogeno (+10%).")
            
            sleep_map = {s.label: s for s in SleepQuality}
            s_sleep = sleep_map[st.selectbox("Qualità del Sonno (Ieri)", list(sleep_map.keys()), index=0)]
            
            # Mostra ciclo solo se Donna
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                menstrual_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = menstrual_map[st.selectbox("Fase Ciclo Mestruale", list(menstrual_map.keys()), index=0)]

        st.markdown("---")
        st.subheader("2. Stato Iniziale (Livello)")
        
        diet_map = {d.label: d for d in DietType}
        s_diet = diet_map[st.selectbox("Nutrizione (Ultime 48h)", list(diet_map.keys()), index=1)]
        
        fatigue_map = {f.label: f for f in FatigueState}
        s_fatigue = fatigue_map[st.selectbox("Attività (Ultime 24h)", list(fatigue_map.keys()), index=0)]
        
        is_fasted = st.checkbox("Allenamento a Digiuno", help="Riduce drasticamente le scorte epatiche.")
        
        # Calcolo combinato del Filling Factor (Diet * Fatigue * Sleep)
        combined_filling = s_diet.factor * s_fatigue.factor * s_sleep.factor
        
        liver_val = 40.0 if is_fasted else 100.0
        
        subject = Subject(
            weight_kg=weight, body_fat_pct=bf, sex=s_sex, 
            glycogen_conc_g_kg=calculated_conc, sport=s_sport, 
            liver_glycogen_g=liver_val,
            filling_factor=combined_filling,
            uses_creatine=use_creatine,
            menstrual_phase=s_menstrual
        )
        
        tank_data = calculate_tank(subject)
        st.session_state['tank_g'] = tank_data['actual_available_g']

    with col_res:
        st.subheader("Analisi Capacità vs Realtà")
        
        # Visualizzazione Barra di Progresso
        fill_pct = tank_data['fill_pct']
        st.write(f"**Livello di Riempimento Attuale:** {fill_pct:.1f}%")
        st.progress(int(fill_pct))
        
        if fill_pct < 60:
            st.error("⚠️ **Attenzione:** Parti con scorte molto basse. Rischio crisi precoce.")
        elif fill_pct < 90:
            st.info("ℹ️ **Normale:** Livello fisiologico standard.")
        else:
            st.success("🚀 **Ottimo:** Sei in condizione di Carico/Tapering.")

        c1, c2, c3 = st.columns(3)
        c1.metric("Disponibile Ora", f"{int(tank_data['actual_available_g'])} g", 
                  help="Glicogeno effettivamente presente ora")
        c2.metric("Capacità Massima", f"{int(tank_data['max_capacity_g'])} g",
                  delta=f"{int(tank_data['actual_available_g'] - tank_data['max_capacity_g'])} g",
                  help="Quanto potresti stoccare in condizioni perfette")
        c3.metric("Kcal Reali", f"{int(tank_data['actual_available_g'] * 4.1)} kcal")
        
        # Grafico Comparativo
        st.caption("Confronto: Potenziale vs Attuale")
        chart_df = pd.DataFrame({
            "Stato": ["Massimo Teorico", "Disponibile Ora"],
            "Glicogeno (g)": [tank_data['max_capacity_g'], tank_data['actual_available_g']]
        })
        st.bar_chart(chart_df, x="Stato", y="Glicogeno (g)", color="Stato")
        
        st.markdown("---")
        
        factors_text = []
        if combined_filling < 1.0: factors_text.append(f"Nutrizione/Sonno/Recupero ({int(combined_filling*100)}%)")
        if use_creatine: factors_text.append("Bonus Creatina (+10% Cap)")
        if s_menstrual == MenstrualPhase.LUTEAL: factors_text.append("Fase Luteale (-5%)")
        
        if factors_text:
            st.caption(f"**Fattori attivi:** {', '.join(factors_text)}")

# --- TAB 2: SIMULAZIONE CONSUMO ---
with tab2:
    if 'tank_g' not in st.session_state:
        st.warning("Vai prima nel Tab 1 per calcolare il serbatoio!")
    else:
        start_tank = st.session_state['tank_g']
        
        col_param, col_meta = st.columns([1, 1])
        
        with col_param:
            st.subheader("🛠️ Parametri Sforzo")
            ftp = st.number_input("Tua FTP (Watt)", 100, 600, 250, step=5)
            avg_w = st.number_input("Potenza Media Gara (Watt)", 50, 600, 200, step=5)
            duration = st.slider("Durata (min)", 30, 420, 120, step=10)
            carb_intake = st.slider("Integrazione (g/h)", 0, 120, 30, step=10)
            
        with col_meta:
            st.subheader("🧬 Profilo Metabolico")
            crossover = st.slider("Soglia Aerobica / Crossover (% FTP)", 50, 85, 70, 5)
            if crossover > 75: st.caption("🏃 **Diesel:** Brucia-grassi.")
            elif crossover < 60: st.caption("🏎️ **Turbo:** Brucia-zuccheri.")
            else: st.caption("⚖️ **Bilanciato.**")

        df_sim, stats = simulate_metabolism(start_tank, ftp, avg_w, duration, carb_intake, crossover)
        
        st.markdown("---")
        st.subheader("🔥 Analisi Consumi")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Glicogeno Finale", f"{int(stats['final_glycogen'])} g", 
                  delta=f"{int(stats['final_glycogen'] - start_tank)} g")
        m2.metric("Mix Energetico", f"{int(stats['cho_pct'])}% CHO")
        m3.metric("Consumo Zuccheri", f"{int(stats['cho_rate_g_h'])} g/h")
        m4.metric("Consumo Grassi", f"{int(stats['fat_rate_g_h'])} g/h")

        st.area_chart(df_sim.set_index("Time (min)")["Glycogen (g)"], color="#FF4B4B")
        
        final_g = stats['final_glycogen']
        if final_g <= 0:
            st.error(f"🚨 **BONK!** Glicogeno esaurito al minuto {df_sim[df_sim['Glycogen (g)'] <= 0].index[0]}.")
        elif final_g < 150:
            st.warning("⚠️ **Riserva BASSA.**")
        else:
            st.success("✅ **Riserva OK.**")
