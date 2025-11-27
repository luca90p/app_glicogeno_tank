import streamlit as st
import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum

# --- 1. PARAMETRI FISIOLOGICI ---

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
    CYCLING = (0.63, "Ciclismo (Prevalenza arti inferiori)")
    RUNNING = (0.75, "Corsa (Arti inferiori + Core)")
    TRIATHLON = (0.85, "Triathlon (Multidisciplinare)")
    XC_SKIING = (0.95, "Sci di Fondo (Whole Body)")
    SWIMMING = (0.80, "Nuoto (Arti sup. + inf.)")

    def __init__(self, val, label):
        self.val = val
        self.label = label

# --- PARAMETRI STATO FISIOLOGICO ---
class DietType(Enum):
    # (factor, label, g_kg_reference)
    HIGH_CARB = (1.0, "Carico Carboidrati (High CHO)", 8.0)
    NORMAL = (0.85, "Regime Normocalorico Misto", 5.0)
    LOW_CARB = (0.50, "Restrizione Glucidica / Low Carb", 2.5)

    def __init__(self, factor, label, ref_value):
        self.factor = factor
        self.label = label
        self.ref_value = ref_value

class FatigueState(Enum):
    RESTED = (1.0, "Riposo / Tapering (Pieno Recupero)")
    ACTIVE = (0.9, "Carico di lavoro moderato (24h prec.)")
    TIRED = (0.65, "Carico di lavoro elevato (Recupero incompleto)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class SleepQuality(Enum):
    GOOD = (1.0, "Ottimale (>7h, ristoratore)")
    AVERAGE = (0.95, "Sufficiente (6-7h)")
    POOR = (0.85, "Insufficiente / Disturbato (<6h)")

    def __init__(self, factor, label):
        self.factor = factor
        self.label = label

class MenstrualPhase(Enum):
    NONE = (1.0, "Non applicabile")
    FOLLICULAR = (1.0, "Fase Follicolare")
    LUTEAL = (0.95, "Fase Luteale (Premestruale)")

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
    
    # Biomarker
    glucose_mg_dl: float = None # Dato opzionale

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        base = 0.50 if self.sex == Sex.MALE else 0.42
        if self.glycogen_conc_g_kg >= 22.0:
            base += 0.03
        return base

# --- 2. LOGICA DI CALCOLO ---

def get_concentration_from_vo2max(vo2_max):
    """
    Stima lineare della concentrazione di glicogeno muscolare (g/kg ww) basata sul VO2max.
    Rif: Areta & Hopkins (2018).
    """
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

def calculate_tank(subject: Subject):
    lbm = subject.lean_body_mass
    total_muscle = lbm * subject.muscle_fraction
    active_muscle = total_muscle * subject.sport.val
    
    # 1. Capacità Teorica Massima
    creatine_multiplier = 1.10 if subject.uses_creatine else 1.0
    max_muscle_glycogen = active_muscle * subject.glycogen_conc_g_kg * creatine_multiplier
    
    # 2. Riempimento Reale (Muscolo)
    final_filling_factor = subject.filling_factor * subject.menstrual_phase.factor
    current_muscle_glycogen = max_muscle_glycogen * final_filling_factor
    
    # 3. Riempimento Reale (Fegato) con Logica Biomarker (Glicemia)
    liver_fill_factor = 1.0
    liver_correction_note = None
    
    # A. Correzione base da dieta/filling
    if final_filling_factor <= 0.6: 
        liver_fill_factor = 0.6
        
    # B. Override da Biomarker (Glicemia)
    if subject.glucose_mg_dl is not None:
        if subject.glucose_mg_dl < 70:
            liver_fill_factor = 0.2 # Ipoglicemia a digiuno = fegato vuoto
            liver_correction_note = "Criticità Epatica (Glicemia < 70)"
        elif subject.glucose_mg_dl < 85:
            liver_fill_factor = min(liver_fill_factor, 0.5) # Riserve compromesse
            liver_correction_note = "Riduzione Epatica (Glicemia 70-85)"
    
    current_liver_glycogen = subject.liver_glycogen_g * liver_fill_factor
        
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
        "creatine_bonus": subject.uses_creatine,
        "liver_note": liver_correction_note
    }

def simulate_metabolism(tank_g, ftp_watts, avg_power, duration_min, carb_intake_g_h, crossover_pct):
    results = []
    current_glycogen = tank_g
    
    intensity_factor = avg_power / ftp_watts if ftp_watts > 0 else 0
    crossover_if = crossover_pct / 100.0
    
    # Efficienza meccanica lorda standard (Gross Efficiency) ~22%
    kcal_per_min_total = (avg_power * 60) / 4184 / 0.22
    
    slope_k = 12.0
    
    if intensity_factor <= 0.2:
        cho_ratio = 0.10
    else:
        # Funzione Sigmoide per la transizione metabolica
        cho_ratio = 1 / (1 + np.exp(-slope_k * (intensity_factor - crossover_if)))
        if cho_ratio < 0.10: cho_ratio = 0.10
        if cho_ratio > 1.0: cho_ratio = 1.0
        # Sopra soglia (FTP), contributo anaerobico preponderante
        if intensity_factor > 1.05:
            cho_ratio = 1.0

    fat_ratio = 1.0 - cho_ratio
    kcal_cho = kcal_per_min_total * cho_ratio
    kcal_fat = kcal_per_min_total * fat_ratio
    
    # Conversione energetica substrati (4.1 kcal/g CHO, 9.0 kcal/g FAT)
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
            "Glicogeno Residuo (g)": current_glycogen,
            "Lipidi Ossidati (g)": total_fat_burned_g,
            "CHO %": cho_ratio * 100,
            "FAT %": fat_ratio * 100
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

st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")

st.title("Glycogen Simulator Pro")
st.markdown("Strumento di stima delle riserve energetiche e simulazione del metabolismo sotto sforzo.")

tab1, tab2 = st.tabs(["Analisi Riserve (Tank)", "Simulazione Metabolica (Burn)"])

# --- TAB 1: CALCOLO SERBATOIO ---
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("Parametri Antropometrici")
        weight = st.slider("Peso Corporeo (kg)", 45.0, 100.0, 70.0, 0.5)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 15.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        st.markdown("---")
        st.write("**Stima Glicogeno Muscolare**")
        estimation_method = st.radio("Metodo di calcolo:", ["Basato su Livello", "Basato su VO2max"], label_visibility="collapsed")
        
        if estimation_method == "Basato su Livello":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello Atletico", list(status_map.keys()), index=2)]
            calculated_conc = s_status.val
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 55, step=1)
            calculated_conc = get_concentration_from_vo2max(vo2_input)
            
            lvl = ""
            if calculated_conc < 15: lvl = "Sedentario"
            elif calculated_conc < 18: lvl = "Amatore"
            elif calculated_conc < 22: lvl = "Allenato"
            elif calculated_conc < 24: lvl = "Avanzato"
            else: lvl = "Elite"
            st.caption(f"Concentrazione stimata: **{calculated_conc:.1f} g/kg** ({lvl})")

        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina Sportiva", list(sport_map.keys()))]
        
        # PARAMETRI AVANZATI (Include ora anche la Glicemia)
        with st.expander("Parametri Avanzati (Supplementazione, Sonno, Ciclo, Biomarker)"):
            use_creatine = st.checkbox("Supplementazione Creatina", help="Aumento volume cellulare e capacità di stoccaggio stimata (+10%).")
            
            sleep_map = {s.label: s for s in SleepQuality}
            s_sleep = sleep_map[st.selectbox("Qualità del Sonno (24h prec.)", list(sleep_map.keys()), index=0)]
            
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                menstrual_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = menstrual_map[st.selectbox("Fase Ciclo Mestruale", list(menstrual_map.keys()), index=0)]
                
            st.markdown("---")
            st.write("**Biomarker (Glicemia)**")
            has_glucose = st.checkbox("Dispongo di misurazione Glicemia", help="Utile per valutare lo stato acuto del fegato.")
            glucose_val = None
            if has_glucose:
                glucose_val = st.number_input("Glicemia Capillare a Digiuno (mg/dL)", 40, 200, 90, 1)
                if glucose_val < 70:
                    st.error("Rilevata Ipoglicemia: Riserve epatiche critiche.")
                elif glucose_val < 85:
                    st.warning("Glicemia bassa: Riserve epatiche ridotte.")

        st.markdown("---")
        st.subheader("Stato Nutrizionale e di Recupero")
        
        diet_options_map = {}
        for d in DietType:
            daily_cho = int(weight * d.ref_value)
            sign = ">" if d == DietType.HIGH_CARB else ("<" if d == DietType.LOW_CARB else "~")
            label = f"{d.label} ({sign}{d.ref_value} g/kg/die) [~{daily_cho}g tot]"
            diet_options_map[label] = d
        
        selected_diet_label = st.selectbox("Introito Glucidico (48h prec.)", list(diet_options_map.keys()), index=1)
        s_diet = diet_options_map[selected_diet_label]
        
        fatigue_map = {f.label: f for f in FatigueState}
        s_fatigue = fatigue_map[st.selectbox("Carico di Lavoro (24h prec.)", list(fatigue_map.keys()), index=0)]
        
        # Checkbox Digiuno: visibile SOLO se NON abbiamo la glicemia (che è più precisa)
        is_fasted = False
        if not has_glucose:
            is_fasted = st.checkbox("Allenamento a Digiuno (Morning Fasted)", help="Riduzione fisiologica delle riserve epatiche post-riposo notturno.")
        
        combined_filling = s_diet.factor * s_fatigue.factor * s_sleep.factor
        
        liver_val = 100.0
        if is_fasted:
            liver_val = 40.0 # Valore default se digiuno senza glucometro
        
        subject = Subject(
            weight_kg=weight, body_fat_pct=bf, sex=s_sex, 
            glycogen_conc_g_kg=calculated_conc, sport=s_sport, 
            liver_glycogen_g=liver_val,
            filling_factor=combined_filling,
            uses_creatine=use_creatine,
            menstrual_phase=s_menstrual,
            glucose_mg_dl=glucose_val
        )
        
        tank_data = calculate_tank(subject)
        st.session_state['tank_g'] = tank_data['actual_available_g']

    with col_res:
        st.subheader("Bilancio Riserve Energetiche")
        
        fill_pct = tank_data['fill_pct']
        st.write(f"**Livello di Riempimento Attuale:** {fill_pct:.1f}%")
        st.progress(int(fill_pct))
        
        if fill_pct < 60:
            st.warning("Attenzione: Riserve di glicogeno ridotte (<60%).")
        elif fill_pct < 90:
            st.info("Stato nutrizionale nella norma.")
        else:
            st.success("Condizione ottimale (Tapering/Carico).")

        c1, c2, c3 = st.columns(3)
        c1.metric("Glicogeno Disponibile", f"{int(tank_data['actual_available_g'])} g", 
                  help="Quantità totale stimata disponibile per l'attività.")
        c2.metric("Capacità di Stoccaggio", f"{int(tank_data['max_capacity_g'])} g",
                  delta=f"{int(tank_data['actual_available_g'] - tank_data['max_capacity_g'])} g",
                  help="Capacità massima teorica in condizioni ideali.")
        c3.metric("Energia Disponibile (CHO)", f"{int(tank_data['actual_available_g'] * 4.1)} kcal")
        
        st.caption("Analisi comparativa: Capacità Teorica vs Disponibilità Reale")
        chart_df = pd.DataFrame({
            "Stato": ["Capacità Teorica", "Disponibilità Reale"],
            "Glicogeno (g)": [tank_data['max_capacity_g'], tank_data['actual_available_g']]
        })
        st.bar_chart(chart_df, x="Stato", y="Glicogeno (g)", color="Stato")
        
        st.markdown("---")
        
        factors_text = []
        if combined_filling < 1.0: factors_text.append(f"Riduzione da fattori nutrizionali/recupero (Disponibilità: {int(combined_filling*100)}%)")
        if use_creatine: factors_text.append("Bonus volume plasmatico/creatina (+10% Cap)")
        if s_menstrual == MenstrualPhase.LUTEAL: factors_text.append("Fase Luteale (-5% filling)")
        if tank_data.get('liver_note'): factors_text.append(f"**{tank_data['liver_note']}**")
        
        if factors_text:
            st.caption(f"**Fattori correttivi applicati:** {'; '.join(factors_text)}")

# --- TAB 2: SIMULAZIONE CONSUMO ---
with tab2:
    if 'tank_g' not in st.session_state:
        st.warning("Calcolare prima le riserve nel Tab 'Analisi Riserve'.")
    else:
        start_tank = st.session_state['tank_g']
        
        col_param, col_meta = st.columns([1, 1])
        
        with col_param:
            st.subheader("Protocollo di Carico")
            ftp = st.number_input("Functional Threshold Power (FTP) [Watt]", 100, 600, 250, step=5)
            avg_w = st.number_input("Potenza Media Prevista [Watt]", 50, 600, 200, step=5)
            duration = st.slider("Durata Attività (min)", 30, 420, 120, step=10)
            carb_intake = st.slider("Integrazione CHO esogena (g/h)", 0, 120, 30, step=10)
            
        with col_meta:
            st.subheader("Profilo Metabolico")
            crossover = st.slider("Crossover Point (Soglia Aerobica) [% FTP]", 50, 85, 70, 5)
            
            if crossover > 75: st.caption("Profilo: Alta efficienza lipolitica (Diesel)")
            elif crossover < 60: st.caption("Profilo: Prevalenza glicolitica (Turbo)")
            else: st.caption("Profilo: Bilanciato / Misto")

        df_sim, stats = simulate_metabolism(start_tank, ftp, avg_w, duration, carb_intake, crossover)
        
        st.markdown("---")
        st.subheader("Analisi Cinetica e Substrati")
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Glicogeno Residuo", f"{int(stats['final_glycogen'])} g", 
                  delta=f"{int(stats['final_glycogen'] - start_tank)} g")
        m2.metric("Ripartizione Substrati", f"{int(stats['cho_pct'])}% CHO")
        m3.metric("Tasso Ossidazione CHO", f"{int(stats['cho_rate_g_h'])} g/h")
        m4.metric("Tasso Ossidazione Lipidi", f"{int(stats['fat_rate_g_h'])} g/h")

        g1, g2 = st.columns([2, 1])
        with g1:
            st.caption("Cinetica di Deplezione Glicogeno")
            st.area_chart(df_sim.set_index("Time (min)")["Glicogeno Residuo (g)"], color="#FF4B4B")
        with g2:
            st.caption("Ossidazione Lipidica Cumulativa")
            st.line_chart(df_sim.set_index("Time (min)")["Lipidi Ossidati (g)"], color="#FFA500")
        
        final_g = stats['final_glycogen']
        if final_g <= 0:
            st.error(f"**DEPLETIONE TOTALE:** Esaurimento riserve (Bonk) stimato al minuto {df_sim[df_sim['Glicogeno Residuo (g)'] <= 0].index[0]}.")
        elif final_g < 150:
            st.warning("**RISERVA CRITICA:** Livelli di glicogeno sub-ottimali. Possibile calo di prestazione.")
        else:
            st.success("**RISERVA ADEGUATA:** Completamento attività senza deplezione critica.")
