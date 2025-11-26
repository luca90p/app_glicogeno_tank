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
    # Rimosso CARBO_LOADED come richiesto
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

@dataclass
class Subject:
    weight_kg: float
    body_fat_pct: float
    sex: Sex
    glycogen_conc_g_kg: float # Ora passiamo il valore calcolato (da Status o VO2max)
    sport: SportType
    liver_glycogen_g: float = 100.0

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        base = 0.50 if self.sex == Sex.MALE else 0.42
        # Bonus muscolare per atleti molto ottimizzati (>22 g/kg)
        if self.glycogen_conc_g_kg >= 22.0:
            base += 0.03
        return base

# --- 2. MOTORE DI CALCOLO ---

def get_concentration_from_vo2max(vo2_max):
    """
    Stima la concentrazione di glicogeno (g/kg umido) in base al VO2max.
    Modello lineare interpolato su dati di biopsia:
    VO2 30 -> 13 g/kg
    VO2 80 -> 25 g/kg
    """
    # Formula: y = mx + q
    # Slope (m) = (25 - 13) / (80 - 30) = 12 / 50 = 0.24
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    
    # Limiti fisiologici
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0 # Limite fisiologico umano standard
    
    return conc

def calculate_tank(subject: Subject):
    lbm = subject.lean_body_mass
    total_muscle = lbm * subject.muscle_fraction
    active_muscle = total_muscle * subject.sport.val
    
    # Uso diretto della concentrazione passata nel Subject
    muscle_glycogen = active_muscle * subject.glycogen_conc_g_kg
    
    total_glycogen = muscle_glycogen + subject.liver_glycogen_g
    
    return {
        "active_muscle_kg": active_muscle,
        "total_glycogen_g": total_glycogen,
        "muscle_glycogen_g": muscle_glycogen,
        "liver_glycogen_g": subject.liver_glycogen_g,
        "concentration_used": subject.glycogen_conc_g_kg
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
st.markdown("Stima il serbatoio iniziale e simula il consumo metabolico.")

tab1, tab2 = st.tabs(["1️⃣ Il Serbatoio (Tank)", "2️⃣ Simulazione Metabolica (Burn)"])

# --- TAB 1: CALCOLO SERBATOIO ---
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("Profilo Atleta")
        weight = st.slider("Peso (kg)", 45.0, 100.0, 70.0, 0.5)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 15.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        is_fasted = st.checkbox("Allenamento a Digiuno (Morning Fasted)", 
                                help="Simula l'allenamento al risveglio senza colazione.")
        
        st.markdown("---")
        st.write("📊 **Metodo Stima Glicogeno Muscolare**")
        
        estimation_method = st.radio(
            "Scegli il metodo:",
            ["Per Livello (Qualitativo)", "Per VO2max (Quantitativo)"],
            label_visibility="collapsed"
        )
        
        if estimation_method == "Per Livello (Qualitativo)":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello Fitness", list(status_map.keys()), index=2)]
            calculated_conc = s_status.val
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 55, step=1, 
                                  help="Valore di massimo consumo di ossigeno. Più è alto, maggiori sono le scorte.")
            calculated_conc = get_concentration_from_vo2max(vo2_input)
            
            # Feedback visivo del livello corrispondente
            if calculated_conc < 15: lvl = "Sedentario"
            elif calculated_conc < 18: lvl = "Amatore"
            elif calculated_conc < 22: lvl = "Allenato"
            elif calculated_conc < 24: lvl = "Avanzato"
            else: lvl = "Elite"
            st.caption(f"Densità stimata: **{calculated_conc:.1f} g/kg** ({lvl})")

        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Sport", list(sport_map.keys()))]

        liver_val = 40.0 if is_fasted else 100.0
        
        # Subject ora prende la concentrazione calcolata, non l'Enum
        subject = Subject(
            weight_kg=weight, 
            body_fat_pct=bf, 
            sex=s_sex, 
            glycogen_conc_g_kg=calculated_conc, # NUOVO
            sport=s_sport, 
            liver_glycogen_g=liver_val
        )
        
        tank_data = calculate_tank(subject)
        st.session_state['tank_g'] = tank_data['total_glycogen_g']

    with col_res:
        st.subheader("Capacità di Stoccaggio")
        
        if is_fasted:
            st.warning("⚠️ Stato: DIGIUNO (-60g fegato)")
        else:
            st.success("✅ Stato: FED (Nutrito)")

        c1, c2, c3 = st.columns(3)
        c1.metric("Glicogeno Totale", f"{int(tank_data['total_glycogen_g'])} g", 
                  delta="-60g" if is_fasted else None, delta_color="inverse")
        c2.metric("Concentrazione", f"{tank_data['concentration_used']:.1f} g/kg", 
                  help="Densità di glicogeno nel tessuto muscolare")
        c3.metric("Muscoli Attivi", f"{tank_data['active_muscle_kg']:.1f} kg")
        
        chart_data = pd.DataFrame({
            "Fonte": ["Fegato", "Muscoli Attivi"],
            "Grammi": [tank_data['liver_glycogen_g'], tank_data['muscle_glycogen_g']]
        })
        st.bar_chart(chart_data, x="Fonte", y="Grammi", color="#00CC96", horizontal=True)
        
        st.info(f"**Nota:** Questo atleta ha **{tank_data['muscle_glycogen_g']:.0f}g** di carburante direttamente nei muscoli usati per il {s_sport.label}.")

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
            
            crossover = st.slider(
                "Soglia Aerobica / Crossover (% FTP)", 
                min_value=50, max_value=85, value=70, step=5,
                help="Basso (50-60%): Atleta esplosivo/principiante. Alto (75-80%): Atleta Endurance/Diesel."
            )
            
            if crossover > 75:
                st.caption("🏃 **Motore Diesel:** Brucia grassi a ritmi alti.")
            elif crossover < 60:
                st.caption("🏎️ **Motore Turbo:** Brucia zuccheri presto.")
            else:
                st.caption("⚖️ **Bilanciato:** Profilo standard.")

        df_sim, stats = simulate_metabolism(start_tank, ftp, avg_w, duration, carb_intake, crossover)
        
        st.markdown("---")
        st.subheader("🔥 Analisi Consumi")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Glicogeno Finale", f"{int(stats['final_glycogen'])} g", 
                  delta=f"{int(stats['final_glycogen'] - start_tank)} g")
        
        m2.metric("Mix Energetico", f"{int(stats['cho_pct'])}% CHO", 
                  delta=f"{100-int(stats['cho_pct'])}% FAT", delta_color="off")
        
        m3.metric("Consumo Zuccheri", f"{int(stats['cho_rate_g_h'])} g/h", help="Rateo ossidazione CHO")
        m4.metric("Consumo Grassi", f"{int(stats['fat_rate_g_h'])} g/h", help="Rateo ossidazione FAT")

        g1, g2 = st.columns([2, 1])
        
        with g1:
            st.caption("📉 Svuotamento Serbatoio Glicogeno")
            st.area_chart(df_sim.set_index("Time (min)")["Glycogen (g)"], color="#FF4B4B")
            
        with g2:
            st.caption("🥩 Grassi Totali Bruciati (g)")
            st.line_chart(df_sim.set_index("Time (min)")["Fat Burned (cumul)"], color="#FFA500")

        final_g = stats['final_glycogen']
        if final_g <= 0:
            st.error(f"🚨 **BONK!** Glicogeno esaurito al minuto {df_sim[df_sim['Glycogen (g)'] <= 0].index[0]}.")
        elif final_g < 150:
            st.warning("⚠️ **Riserva BASSA.**")
        else:
            st.success("✅ **Riserva OK.**")
