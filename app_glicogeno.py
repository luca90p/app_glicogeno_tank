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
    SEDENTARY = (13.0, "Sedentario / Low Carb")
    RECREATIONAL = (18.0, "Attivo / Amatore")
    ENDURANCE_TRAINED = (22.0, "Allenato (Endurance)")
    ELITE_OPTIMIZED = (25.0, "Elite / Pro")
    CARBO_LOADED = (32.0, "Carico Carboidrati (Supercompensazione)")

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
    status: TrainingStatus
    sport: SportType
    liver_glycogen_g: float = 100.0

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        base = 0.50 if self.sex == Sex.MALE else 0.42
        if self.status in [TrainingStatus.ELITE_OPTIMIZED, TrainingStatus.CARBO_LOADED]:
            base += 0.03
        return base

# --- 2. MOTORE DI CALCOLO ---

def calculate_tank(subject: Subject):
    lbm = subject.lean_body_mass
    total_muscle = lbm * subject.muscle_fraction
    active_muscle = total_muscle * subject.sport.val
    muscle_glycogen = active_muscle * subject.status.val
    
    total_glycogen = muscle_glycogen + subject.liver_glycogen_g
    
    return {
        "active_muscle_kg": active_muscle,
        "total_glycogen_g": total_glycogen,
        "muscle_glycogen_g": muscle_glycogen,
        "liver_glycogen_g": subject.liver_glycogen_g
    }

def simulate_activity(tank_g, ftp_watts, avg_power, duration_min, carb_intake_g_h):
    """
    Simula il consumo di glicogeno minuto per minuto.
    """
    results = []
    current_glycogen = tank_g
    
    # Intensità relativa (Intensity Factor)
    intensity_factor = avg_power / ftp_watts if ftp_watts > 0 else 0
    
    # 1. Stima Calorie Totali al minuto (Metodo Gross Efficiency ~22%)
    # 1 Watt = 1 J/s. 
    # Kcal/min = (Watts * 60) / 4184 / Efficiency
    kcal_per_min_total = (avg_power * 60) / 4184 / 0.22
    
    # 2. Stima Mix Energetico (% Carboidrati vs Grassi)
    if intensity_factor <= 0.3:
        cho_ratio = 0.10
    elif intensity_factor >= 1.1:
        cho_ratio = 1.0
    else:
        # Interpolazione quadratica tra 0.3 (10%) e 1.0 (100%)
        t = (intensity_factor - 0.3) / 0.7 
        cho_ratio = 0.10 + (0.90 * (t ** 2)) 

    kcal_from_cho_per_min = kcal_per_min_total * cho_ratio
    
    # 3. Conversione Kcal -> Grammi Glicogeno (4.1 kcal/g)
    glycogen_burned_per_min = kcal_from_cho_per_min / 4.1
    
    # 4. Reintegro (Carb Intake)
    glycogen_intake_per_min = carb_intake_g_h / 60.0

    # SIMULAZIONE LOOP
    for t in range(int(duration_min) + 1):
        if t > 0:
            net_change = glycogen_intake_per_min - glycogen_burned_per_min
            current_glycogen += net_change
        
        # Clamp a 0
        if current_glycogen < 0:
            current_glycogen = 0
            
        results.append({
            "Time (min)": t,
            "Glycogen (g)": current_glycogen,
            "Burned (g/h)": glycogen_burned_per_min * 60,
            "Cho %": cho_ratio * 100
        })

    return pd.DataFrame(results), cho_ratio * 100, kcal_per_min_total * 60

# --- 3. INTERFACCIA UTENTE ---

st.set_page_config(page_title="Glycogen Simulator", page_icon="⚡", layout="wide")

st.title("⚡ Glicogeno: Tank & Burn Simulator")
st.markdown("Stima il serbatoio iniziale e simula quanto dura durante lo sforzo fisico.")

# Divisione in Tab
tab1, tab2 = st.tabs(["1️⃣ Il Serbatoio (Tank)", "2️⃣ Simulazione Gara (Burn)"])

# --- TAB 1: CALCOLO SERBATOIO ---
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("Profilo Atleta")
        weight = st.slider("Peso (kg)", 45.0, 100.0, 70.0, 0.5)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 15.0, 0.5) / 100.0
        
        sex_map = {s.label: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        # --- NUOVA FUNZIONALITÀ DIGIUNO ---
        is_fasted = st.checkbox("Allenamento a Digiuno (Morning Fasted)", 
                                help="Simula l'allenamento al risveglio senza colazione. Le scorte epatiche sono ridotte.")
        
        status_map = {s.label: s for s in TrainingStatus}
        s_status = status_map[st.selectbox("Livello Fitness", list(status_map.keys()), index=2)]
        
        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Sport", list(sport_map.keys()))]

        # Logica Digiuno: Il fegato scende da ~100g a ~40g
        liver_val = 40.0 if is_fasted else 100.0

        # Creazione Oggetto Subject
        subject = Subject(weight, bf, s_sex, s_status, s_sport, liver_glycogen_g=liver_val)
        tank_data = calculate_tank(subject)
        
        # Salva nel session state per passare al Tab 2
        st.session_state['tank_g'] = tank_data['total_glycogen_g']

    with col_res:
        st.subheader("Capacità di Stoccaggio")
        
        # Feedback visivo per il digiuno
        if is_fasted:
            st.warning("⚠️ **Stato: DIGIUNO** - Il fegato è parzialmente scarico (-60g). Hai meno margine contro l'ipoglicemia.")
        else:
            st.success("✅ **Stato: FED (Nutrito)** - Scorte epatiche piene (100g).")

        c1, c2, c3 = st.columns(3)
        c1.metric("Glicogeno Totale", f"{int(tank_data['total_glycogen_g'])} g", 
                  delta="-60g" if is_fasted else "Pieno", delta_color="inverse" if is_fasted else "normal")
        c2.metric("Kcal Disponibili", f"{int(tank_data['total_glycogen_g'] * 4.1)} kcal")
        c3.metric("Muscoli Attivi", f"{tank_data['active_muscle_kg']:.1f} kg")
        
        # Grafico a barre orizzontali
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
        
        st.subheader("Parametri Sforzo")
        
        sc1, sc2, sc3, sc4 = st.columns(4)
        ftp = sc1.number_input("Tua FTP (Watt)", 100, 500, 250, step=5, help="La potenza che puoi tenere per 1 ora (Soglia)")
        avg_w = sc2.number_input("Potenza Media (Watt)", 50, 500, 200, step=5, help="Potenza media prevista per l'attività")
        duration = sc3.slider("Durata (min)", 30, 300, 120, step=10)
        carb_intake = sc4.slider("Integrazione CHO (g/h)", 0, 120, 30, step=10, help="Quanti carboidrati mangi all'ora (gel, borracce)")
        
        # Esegui simulazione
        df_sim, final_cho_pct, kcal_h_total = simulate_activity(start_tank, ftp, avg_w, duration, carb_intake)
        
        # Calcolo metriche finali
        final_glycogen = df_sim.iloc[-1]["Glycogen (g)"]
        
        # Layout Risultati Simulazione
        st.markdown("---")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Glicogeno Finale", f"{int(final_glycogen)} g", delta=f"{int(final_glycogen - start_tank)} g")
        m2.metric("Consumo CHO Stimato", f"{int(df_sim.iloc[-1]['Burned (g/h)'])} g/h")
        m3.metric("Dispendio Totale", f"{int(kcal_h_total)} kcal/h")
        m4.metric("Intensità (IF)", f"{(avg_w/ftp)*100:.0f}% ({int(final_cho_pct)}% CHO)")

        # Grafico Area
        st.subheader("Curva di Deplezione")
        
        danger_zone = 150 
        
        st.area_chart(df_sim.set_index("Time (min)")["Glycogen (g)"], color="#FF4B4B")
        
        # Analisi finale
        if final_glycogen <= 0:
            st.error(f"🚨 **BONK (Crisi di Fame)!** Hai esaurito il glicogeno prima della fine. Riduci la potenza o mangia di più.")
        elif final_glycogen < danger_zone:
            st.warning(f"⚠️ **Attenzione:** Hai finito con riserve scarse (<{danger_zone}g). La performance potrebbe calare negli ultimi minuti.")
        else:
            st.success(f"✅ **Ottimo:** Hai gestito bene le energie. Ti rimangono {int(final_glycogen)}g di scorta.")
