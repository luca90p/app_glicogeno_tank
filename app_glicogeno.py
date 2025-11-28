import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from dataclasses import dataclass
from enum import Enum
import math

# --- 0. SISTEMA DI PROTEZIONE (LOGIN) ---
def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == "glicogeno2025": # <--- CAMBIA QUI LA TUA PASSWORD
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "🔐 Inserisci la Password per accedere al Simulatore", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input + error.
        st.text_input(
            "🔐 Inserisci la Password per accedere al Simulatore", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 Password errata. Riprova.")
        return False
    else:
        # Password correct.
        return True

# Se la password non è corretta, ferma tutto qui.
if not check_password():
    st.stop()

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
    HIGH_CARB = (1.25, "Carico Carboidrati (Supercompensazione)", 8.0)
    NORMAL = (1.00, "Regime Normocalorico Misto (Baseline)", 5.0)
    LOW_CARB = (0.50, "Restrizione Glucidica / Low Carb", 2.5)

    def __init__(self, factor, label, ref_value):
        self.factor = factor
        self.label = label
        self.ref_value = ref_value

class FatigueState(Enum):
    RESTED = (1.0, "Riposo / Tapering (Pieno Recupero)")
    ACTIVE = (0.9, "Carico di lavoro moderato (24h prec.)")
    TIRED = (0.60, "Alto carico o Danno Muscolare (EIMD)")

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
    height_cm: float 
    body_fat_pct: float
    sex: Sex
    glycogen_conc_g_kg: float
    sport: SportType
    liver_glycogen_g: float = 100.0
    filling_factor: float = 1.0 
    uses_creatine: bool = False
    menstrual_phase: MenstrualPhase = MenstrualPhase.NONE
    glucose_mg_dl: float = None
    vo2max_absolute_l_min: float = 3.5 

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
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

def calculate_tank(subject: Subject):
    lbm = subject.lean_body_mass
    total_muscle = lbm * subject.muscle_fraction
    active_muscle = total_muscle * subject.sport.val
    
    creatine_multiplier = 1.10 if subject.uses_creatine else 1.0
    base_muscle_glycogen = active_muscle * subject.glycogen_conc_g_kg
    max_total_capacity = (base_muscle_glycogen * 1.25 * creatine_multiplier) + 100.0
    
    final_filling_factor = subject.filling_factor * subject.menstrual_phase.factor
    current_muscle_glycogen = base_muscle_glycogen * creatine_multiplier * final_filling_factor
    
    max_physiological_limit = active_muscle * 35.0
    if current_muscle_glycogen > max_physiological_limit:
        current_muscle_glycogen = max_physiological_limit
    
    liver_fill_factor = 1.0
    liver_correction_note = None
    
    if subject.filling_factor <= 0.6: 
        liver_fill_factor = 0.6
        
    if subject.glucose_mg_dl is not None:
        if subject.glucose_mg_dl < 70:
            liver_fill_factor = 0.2
            liver_correction_note = "Criticità Epatica (Glicemia < 70 mg/dL)"
        elif subject.glucose_mg_dl < 85:
            liver_fill_factor = min(liver_fill_factor, 0.5)
            liver_correction_note = "Riduzione Epatica (Glicemia 70-85 mg/dL)"
    
    current_liver_glycogen = subject.liver_glycogen_g * liver_fill_factor
    total_actual_glycogen = current_muscle_glycogen + current_liver_glycogen

    return {
        "active_muscle_kg": active_muscle,
        "max_capacity_g": max_total_capacity,         
        "actual_available_g": total_actual_glycogen,   
        "muscle_glycogen_g": current_muscle_glycogen,
        "liver_glycogen_g": current_liver_glycogen,
        "concentration_used": subject.glycogen_conc_g_kg,
        "fill_pct": (total_actual_glycogen / max_total_capacity) * 100 if max_total_capacity > 0 else 0,
        "creatine_bonus": subject.uses_creatine,
        "liver_note": liver_correction_note
    }

def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts):
    base_rate = 0.8 
    if height_cm > 170:
        base_rate += (height_cm - 170) * 0.015
    if ftp_watts > 200:
        base_rate += (ftp_watts - 200) * 0.0015
    limit = 1.6 
    return min(base_rate, limit)

def calculate_rer_polynomial(intensity_factor):
    if_val = intensity_factor
    rer = (
        -0.000000149 * (if_val**6) + 
        141.538462237 * (if_val**5) - 
        565.128206259 * (if_val**4) + 
        890.333333976 * (if_val**3) - 
        691.67948706 * (if_val**2) + 
        265.460857558 * if_val - 
        39.525121144
    )
    return max(0.70, min(1.15, rer))

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, crossover_pct, subject_obj, activity_params):
    tank_g = subject_data['actual_available_g']
    results = []
    
    # Dati Iniziali
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    initial_liver_glycogen = subject_data['liver_glycogen_g']
    
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = initial_liver_glycogen
    
    mode = activity_params.get('mode', 'cycling')
    gross_efficiency = activity_params.get('efficiency', 22.0)
    
    avg_power = 0
    ftp_watts = 250 
    intensity_factor = 0.7
    kcal_per_min_base = 10.0
    
    # --- DETERMINAZIONE PARAMETRI SFORZO ---
    if mode == 'cycling':
        avg_power = activity_params['avg_watts']
        ftp_watts = activity_params['ftp_watts']
        intensity_factor = avg_power / ftp_watts if ftp_watts > 0 else 0
        
    elif mode == 'running':
        speed_kmh = activity_params['speed_kmh']
        weight = subject_obj.weight_kg
        kcal_per_hour = 1.0 * weight * speed_kmh
        kcal_per_min_base = kcal_per_hour / 60.0
        
        avg_hr = activity_params['avg_hr']
        threshold_hr = activity_params['threshold_hr']
        intensity_factor = avg_hr / threshold_hr if threshold_hr > 0 else 0.7
        
        ftp_watts = (subject_obj.vo2max_absolute_l_min * 1000) / 12 
        
    elif mode == 'other':
        avg_hr = activity_params['avg_hr']
        max_hr = activity_params['max_hr']
        hr_pct = avg_hr / max_hr if max_hr > 0 else 0.7
        vo2_operating = subject_obj.vo2max_absolute_l_min * hr_pct
        kcal_per_min_base = vo2_operating * 5.0 
        threshold_proxy = max_hr * 0.85
        intensity_factor = avg_hr / threshold_proxy 
        ftp_watts = 200 
        
    is_lab_data = activity_params.get('use_lab_data', False)
    lab_cho_rate = activity_params.get('lab_cho_g_h', 0) / 60.0
    lab_fat_rate = activity_params.get('lab_fat_g_h', 0) / 60.0
    
    crossover_if = crossover_pct / 100.0
    effective_if_for_rer = intensity_factor + ((75.0 - crossover_pct) / 100.0)
    if effective_if_for_rer < 0.3: effective_if_for_rer = 0.3
    
    max_exo_rate_g_min = estimate_max_exogenous_oxidation(subject_obj.height_cm, subject_obj.weight_kg, ftp_watts)
    oxidation_efficiency = 0.80 
    
    total_fat_burned_g = 0.0
    gut_accumulation_total = 0.0
    current_exo_oxidation_g_min = 0.0 
    tau_absorption = 20.0 
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    
    # Accumulatori per statistiche finali
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    
    for t in range(int(duration_min) + 1):
        # 1. Costo Energetico con Drift
        current_kcal_demand = 0.0
        if mode == 'cycling':
            current_eff = gross_efficiency
            if t > 60: 
                loss = (t - 60) * 0.02
                current_eff = max(15.0, gross_efficiency - loss)
            current_kcal_demand = (avg_power * 60) / 4184 / (current_eff / 100.0)
        else: 
            drift_factor = 1.0
            if t > 60:
                drift_factor += (t - 60) * 0.0005 
            current_kcal_demand = kcal_per_min_base * drift_factor

        # 2. Gestione Intake (Costante)
        current_intake_g_h = constant_carb_intake_g_h
        current_intake_g_min = current_intake_g_h / 60.0
        
        target_exo_g_min = min(current_intake_g_min, max_exo_rate_g_min) * oxidation_efficiency
        
        # Cinetica assorbimento (non lineare)
        if t > 0:
            current_exo_oxidation_g_min += alpha * (target_exo_g_min - current_exo_oxidation_g_min)
        else:
            current_exo_oxidation_g_min = 0.0
            
        if t > 0:
            delta_gut = (current_intake_g_min * oxidation_efficiency) - current_exo_oxidation_g_min
            gut_accumulation_total += delta_gut
            if gut_accumulation_total < 0: gut_accumulation_total = 0 
        
        # 3. Ripartizione Substrati
        if is_lab_data:
            fatigue_mult = 1.0 + ((t - 30) * 0.0005) if t > 30 else 1.0 
            total_cho_demand = lab_cho_rate * fatigue_mult # Questa è g/min

            # CORREZIONE 1: Definizione di kcal_cho_demand per evitare UnboundLocalError
            kcal_cho_demand = total_cho_demand * 4.1
            
            glycogen_burned_per_min = total_cho_demand - current_exo_oxidation_g_min
            min_endo = total_cho_demand * 0.2 
            if glycogen_burned_per_min < min_endo: glycogen_burned_per_min = min_endo
            fat_burned_per_min = lab_fat_rate 
            cho_ratio = total_cho_demand / (total_cho_demand + fat_burned_per_min) if (total_cho_demand + fat_burned_per_min) > 0 else 0
            rer = 0.7 + (0.3 * cho_ratio) 
        
        else:
            rer = calculate_rer_polynomial(effective_if_for_rer)
            base_cho_ratio = (rer - 0.70) * 3.45
            base_cho_ratio = max(0.0, min(1.0, base_cho_ratio))
            
            # --- SHIFT METABOLICO DINAMICO (King/Zanella) ---
            current_cho_ratio = base_cho_ratio
            if intensity_factor < 0.85 and t > 60:
                hours_past = (t - 60) / 60.0
                metabolic_shift = 0.05 * (hours_past ** 1.2) 
                current_cho_ratio = max(0.05, base_cho_ratio - metabolic_shift)
            
            cho_ratio = current_cho_ratio
            fat_ratio = 1.0 - cho_ratio
            
            kcal_cho_demand = current_kcal_demand * cho_ratio
        
        # Bilancio
        total_cho_g_min = kcal_cho_demand / 4.1
        kcal_from_exo = current_exo_oxidation_g_min * 3.75 
        
        # Modello Coggan: Deplezione Muscolare dipendente da stato riempimento
        muscle_fill_state = current_muscle_glycogen / initial_muscle_glycogen if initial_muscle_glycogen > 0 else 0
        muscle_contribution_factor = math.pow(muscle_fill_state, 0.6) 
        
        muscle_usage_g_min = total_cho_g_min * muscle_contribution_factor
        if current_muscle_glycogen <= 0: muscle_usage_g_min = 0
        
        blood_glucose_demand_g_min = total_cho_g_min - muscle_usage_g_min
        
        from_exogenous = min(blood_glucose_demand_g_min, current_exo_oxidation_g_min)
        
        remaining_blood_demand = blood_glucose_demand_g_min - from_exogenous
        max_liver_output = 1.2 
        from_liver = min(remaining_blood_demand, max_liver_output)
        if current_liver_glycogen <= 0: from_liver = 0
        
        # Aggiornamento
        if t > 0:
            current_muscle_glycogen -= muscle_usage_g_min
            current_liver_glycogen -= from_liver
            
            if current_muscle_glycogen < 0: current_muscle_glycogen = 0
            if current_liver_glycogen < 0: current_liver_glycogen = 0
            
            # Nota: fat_ratio viene definita solo nell'else, quindi la gestiamo qui per non is_lab_data
            if not is_lab_data:
                # Usa fat_ratio calcolato nel blocco else
                fat_ratio_used = 1.0 - cho_ratio
                total_fat_burned_g += (current_kcal_demand * fat_ratio_used) / 9.0
            else:
                # Usa lab_fat_rate (g/min) direttamente
                total_fat_burned_g += lab_fat_rate
            
            total_muscle_used += muscle_usage_g_min
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        status_label = "Ottimale"
        if current_liver_glycogen < 20: status_label = "CRITICO (Ipoglicemia)"
        elif current_muscle_glycogen < 100: status_label = "Warning (Gambe Vuote)"
            
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": muscle_usage_g_min * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": from_exogenous * 60,
            # Calcolo corretto dell'Ossidazione Lipidica (g/h)
            "Ossidazione Lipidica (g)": lab_fat_rate * 60 if is_lab_data else ((current_kcal_demand * (1.0 - cho_ratio)) / 9.0) * 60,
            "Residuo Muscolare": current_muscle_glycogen,
            "Residuo Epatico": current_liver_glycogen,
            "Residuo Totale": current_muscle_glycogen + current_liver_glycogen, # <--- MODIFICA 1
            "Target Intake (g/h)": current_intake_g_h, 
            "Gut Load": gut_accumulation_total,
            "Stato": status_label,
            "CHO %": cho_ratio * 100
        })
        
    total_kcal_final = current_kcal_demand * 60 
    
    final_total_glycogen = current_muscle_glycogen + current_liver_glycogen

    stats = {
        "final_muscle": current_muscle_glycogen,
        "final_liver": current_liver_glycogen,
        "final_glycogen": final_total_glycogen, 
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "kcal_total_h": total_kcal_final,
        "gut_accumulation": (gut_accumulation_total / duration_min) * 60 if duration_min > 0 else 0,
        "max_exo_capacity": max_exo_rate_g_min * 60,
        "intensity_factor": intensity_factor,
        "avg_rer": rer,
        "gross_efficiency": gross_efficiency,
        "intake_g_h": constant_carb_intake_g_h,
        "cho_pct": cho_ratio * 100
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
        height = st.slider("Altezza (cm)", 150, 210, 175, 1)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 15.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        st.markdown("---")
        st.write("**Stima Glicogeno Muscolare**")
        estimation_method = st.radio("Metodo di calcolo:", ["Basato su Livello", "Basato su VO2max"], label_visibility="collapsed")
        
        vo2_input = 55.0 
        if estimation_method == "Basato su Livello":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello Atletico", list(status_map.keys()), index=2)]
            calculated_conc = s_status.val
            vo2_input = 30 + ((calculated_conc - 13.0) / 0.24)
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
        
        with st.expander("📘 Note Tecniche & Fonti Scientifiche"):
            st.info("""
            **1. Stima Glicogeno da VO2max:**
            Basata sulla correlazione lineare osservata tra fitness aerobico e densità di stoccaggio (Areta & Hopkins, 2018).
            
            **2. Quantità Totale vs Frequenza (Costill et al., 1981):**
            Per il riempimento del serbatoio (24h pre-gara), è la quantità totale (g/kg) a determinare il livello finale, non la frequenza dei pasti.
            """)
            
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
        
        is_fasted = False
        if not has_glucose:
            is_fasted = st.checkbox("Allenamento a Digiuno (Morning Fasted)", help="Riduzione fisiologica delle riserve epatiche post-riposo notturno.")
        
        combined_filling = s_diet.factor * s_fatigue.factor * s_sleep.factor
        
        liver_val = 100.0
        if is_fasted:
            liver_val = 40.0 
        
        vo2_abs = (vo2_input * weight) / 1000
        
        subject = Subject(
            weight_kg=weight, 
            height_cm=height,
            body_fat_pct=bf, sex=s_sex, 
            glycogen_conc_g_kg=calculated_conc, sport=s_sport, 
            liver_glycogen_g=liver_val,
            filling_factor=combined_filling,
            uses_creatine=use_creatine,
            menstrual_phase=s_menstrual,
            glucose_mg_dl=glucose_val,
            vo2max_absolute_l_min=vo2_abs
        )
        
        tank_data = calculate_tank(subject)
        st.session_state['tank_data'] = tank_data # Salvo tank_data completo
        st.session_state['tank_g'] = tank_data['actual_available_g']
        st.session_state['subject_struct'] = subject 

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
                  help="Capacità massima teorica in condizioni di Supercompensazione.")
        c3.metric("Energia Disponibile (CHO)", f"{int(tank_data['actual_available_g'] * 4.1)} kcal")
        
        st.caption("Analisi comparativa: Capacità Teorica vs Disponibilità Reale")
        chart_df = pd.DataFrame({
            "Stato": ["Capacità Teorica (Carico)", "Disponibilità Reale"],
            "Glicogeno (g)": [tank_data['max_capacity_g'], tank_data['actual_available_g']]
        })
        st.bar_chart(chart_df, x="Stato", y="Glicogeno (g)", color="Stato")
        
        st.markdown("---")
        
        factors_text = []
        if s_diet == DietType.HIGH_CARB: factors_text.append("Supercompensazione Attiva (+25%)")
        if combined_filling < 1.0 and s_diet != DietType.HIGH_CARB: factors_text.append(f"Riduzione da fattori nutrizionali/recupero (Disponibilità: {int(combined_filling*100)}%)")
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
        # Recupero i dati completi
        tank_data = st.session_state['tank_data']
        start_tank = tank_data['actual_available_g']
        subj = st.session_state.get('subject_struct', None)
        
        sport_mode = 'cycling'
        if subj.sport == SportType.RUNNING:
            sport_mode = 'running'
        elif subj.sport in [SportType.SWIMMING, SportType.XC_SKIING, SportType.TRIATHLON]:
            sport_mode = 'other' 
            
        col_param, col_meta = st.columns([1, 1])
        
        act_params = {'mode': sport_mode}
        duration = 120 # Default
        cho_per_unit = 25 # Default
        carb_intake = 60  # Default
        
        with col_param:
            st.subheader(f"Parametri Sforzo ({sport_mode.capitalize()})")
            
            if sport_mode == 'cycling':
                ftp = st.number_input("Functional Threshold Power (FTP) [Watt]", 100, 600, 250, step=5)
                avg_w = st.number_input("Potenza Media Prevista [Watt]", 50, 600, 200, step=5)
                act_params['ftp_watts'] = ftp
                act_params['avg_watts'] = avg_w
                act_params['efficiency'] = st.slider("Efficienza Meccanica [%]", 16.0, 26.0, 22.0, 0.5)
                duration = st.slider("Durata Attività (min)", 30, 420, 120, step=10)
                
            elif sport_mode == 'running':
                run_input_mode = st.radio("Modalità Obiettivo:", ["Imposta Passo & Distanza", "Imposta Tempo & Distanza"], horizontal=True)
                c_dist, c_var = st.columns(2)
                distance_km = c_dist.number_input("Distanza (km)", 1.0, 100.0, 21.1, 0.1)
                paces_options = []
                for m in range(2, 16): 
                    for s in range(0, 60, 5):
                        paces_options.append(f"{m}:{s:02d}")

                if run_input_mode == "Imposta Passo & Distanza":
                    pace_str = c_var.select_slider("Passo Obiettivo (min/km)", options=paces_options, value="5:00")
                    pm, ps = map(int, pace_str.split(':'))
                    pace_decimal = pm + ps/60.0
                    duration = distance_km * pace_decimal
                    speed_kmh = 60.0 / pace_decimal
                    st.info(f"Tempo Stimato: **{int(duration // 60)}h {int(duration % 60)}m**")
                else:
                    target_h = c_var.number_input("Ore", 0, 24, 1)
                    target_m = c_var.number_input("Minuti", 0, 59, 45)
                    duration = (target_h * 60) + target_m
                    if duration == 0: duration = 1
                    pace_decimal = duration / distance_km
                    speed_kmh = 60.0 / pace_decimal
                    p_min = int(pace_decimal)
                    p_sec = int((pace_decimal - p_min) * 60)
                    st.info(f"Passo Richiesto: **{p_min}:{p_sec:02d} /km**")

                act_params['speed_kmh'] = speed_kmh
                c_hr1, c_hr2 = st.columns(2)
                thr_hr = c_hr1.number_input("Soglia Anaerobica (BPM)", 100, 220, 170, 1)
                avg_hr = c_hr2.number_input("Frequenza Cardiaca Media", 80, 220, 150, 1)
                act_params['avg_hr'] = avg_hr
                act_params['threshold_hr'] = thr_hr
                
            else: 
                max_hr = st.number_input("Frequenza Cardiaca Max (BPM)", 100, 220, 185, 1)
                avg_hr = st.number_input("Frequenza Cardiaca Media Gara", 80, 220, 140, 1)
                act_params['avg_hr'] = avg_hr
                act_params['max_hr'] = max_hr
                duration = st.slider("Durata Attività (min)", 30, 420, 120, step=10)
            
        with col_meta:
            st.subheader("Profilo Metabolico & Nutrizione")
            
            # NUTRIZIONE PRATICA
            st.subheader("Gestione Nutrizione Pratica")
            cho_per_unit = st.number_input("Contenuto CHO per Gel/Barretta (g)", 10, 100, 25, 5, help="Es. Un gel isotonico standard ha circa 22g, uno 'high carb' 40g.")
            carb_intake = st.slider("Target Integrazione (g/h)", 0, 120, 60, step=10, help="Quantità media di CHO da assumere ogni ora.")
            
            if carb_intake > 0 and cho_per_unit > 0:
                units_per_hour = carb_intake / cho_per_unit
                if units_per_hour > 0:
                    interval_min = 60 / units_per_hour
                    st.caption(f"Protocollo: {units_per_hour:.1f} unità/h (1 ogni **{int(interval_min)} min**)")
            
            st.markdown("---")

            use_lab = st.checkbox("Usa Dati Reali da Metabolimetro (Test)", help="Se hai fatto un test del gas in laboratorio, inserisci i dati reali per la massima precisione.")
            act_params['use_lab_data'] = use_lab
            
            if use_lab:
                st.info("Inserisci i consumi misurati al **Ritmo Gara** previsto.")
                lab_cho = st.number_input("Consumo CHO (g/h) da Test", 0, 400, 180, 5)
                lab_fat = st.number_input("Consumo Grassi (g/h) da Test", 0, 150, 30, 5)
                act_params['lab_cho_g_h'] = lab_cho
                act_params['lab_fat_g_h'] = lab_fat
                crossover = 75 
            else:
                crossover = st.slider("Crossover Point (Soglia Aerobica) [% Soglia]", 50, 85, 70, 5,
                                      help="Punto in cui il consumo di grassi e carboidrati è equivalente (RER ~0.85).")
                if crossover > 75: st.caption("Profilo: Alta efficienza lipolitica (Diesel)")
                elif crossover < 60: st.caption("Profilo: Prevalenza glicolitica (Turbo)")
                else: st.caption("Profilo: Bilanciato / Misto")
                
        h_cm = subj.height_cm 
        
        # Le due simulazioni devono usare gli stessi parametri di attività,
        # ma la simulazione "No Cho" ha intake=0.
        df_sim, stats = simulate_metabolism(tank_data, duration, carb_intake, crossover, subj, act_params)
        df_sim["Scenario"] = "Con Integrazione (Strategia)"
        
        df_no_cho, stats_no_cho = simulate_metabolism(tank_data, duration, 0, crossover, subj, act_params)
        df_no_cho["Scenario"] = "Senza Integrazione (Digiuno)"
        
        combined_df = pd.concat([df_sim, df_no_cho])
        
        st.markdown("---")
        st.subheader("Analisi Cinetica e Substrati")
        
        c_if, c_rer, c_mix, c_res = st.columns(4)
        
        if_val = stats['intensity_factor']
        c_if.metric("Intensity Factor (IF)", f"{if_val:.2f}", help="Indice di intensità normalizzato sulla soglia.")
        
        rer_val = stats['avg_rer']
        c_rer.metric("RER Stimato (RQ)", f"{rer_val:.2f}", help="Quoziente Respiratorio Metabolico.")
        
        c_mix.metric("Ripartizione Substrati", f"{int(stats['cho_pct'])}% CHO",
                      delta=f"{100-int(stats['cho_pct'])}% FAT", delta_color="off")
        
        c_res.metric("Glicogeno Residuo", f"{int(stats['final_glycogen'])} g", 
                      delta=f"{int(stats['final_glycogen'] - start_tank)} g")

        st.markdown("---")
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Uso Glicogeno Muscolare", f"{int(stats['total_muscle_used'])} g", help="Totale svuotato dalle gambe")
        m2.metric("Uso Glicogeno Epatico", f"{int(stats['total_liver_used'])} g", help="Totale prelevato dal fegato")
        m3.metric("Uso CHO Esogeno", f"{int(stats['total_exo_used'])} g", help="Totale energia da integrazione")

        g1, g2 = st.columns([2, 1])
        with g1:
            st.caption("Cinetica di Deplezione (Muscolo + Fegato)")
            
            # Mappatura colori richiesta dall'utente
            color_map = {
                'Glicogeno Muscolare (g)': '#E57373', # Rosso Tenue (4) - BASE
                'Ossidazione Lipidica (g)': '#FFC107', # Giallo Intenso (3)
                'Carboidrati Esogeni (g)': '#1976D2', # Blu (2)
                'Glicogeno Epatico (g)': '#B71C1C',    # Rosso Scuro (1) - CIMA
            }
            
            # Ordine RICHIESTO (dal basso verso l'alto): Muscolare (4), Lipidi (3), Esogeni (2), Epatico (1)
            stack_order = [
                'Glicogeno Muscolare (g)',   # 1. BASE (Posizione 4)
                'Ossidazione Lipidica (g)',  # 2. Sopra 1 (Posizione 3)
                'Carboidrati Esogeni (g)',   # 3. Sopra 2 (Posizione 2)
                'Glicogeno Epatico (g)'      # 4. CIMA (Posizione 1)
            ]
            
            # Stacked Area Chart per vedere le FONTI (con colori e ordine personalizzati)
            df_long = df_sim.melt('Time (min)', value_vars=stack_order, 
                                  var_name='Source', value_name='Rate (g/h)')
            
            # TRUCCO: Mappatura dell'indice numerico invertita per forzare l'ordinamento in modo DECRESCENTE
            # Questo è l'ordine desiderato: l'indice 3 è la base, l'indice 0 è la cima.
            sort_map = {
                'Glicogeno Muscolare (g)': 3,
                'Ossidazione Lipidica (g)': 2,
                'Carboidrati Esogeni (g)': 1,
                'Glicogeno Epatico (g)': 0
            }
            df_long['sort_index'] = df_long['Source'].map(sort_map)
            
            # Creazione del domain/range personalizzato basato sull'ordine di stack
            color_domain = stack_order
            color_range = [color_map[source] for source in stack_order]

            chart_stack = alt.Chart(df_long).mark_area().encode(
                x=alt.X('Time (min)'),
                y=alt.Y('Rate (g/h)', stack=True), 
                color=alt.Color('Source', 
                                scale=alt.Scale(domain=color_domain,  # Uso il domain ordinato
                                                range=color_range),
                                # FORZA L'ORDINE USANDO L'INDICE NUMERICO IN MODO DECRESCENTE
                                # L'indice 3 va in fondo, l'indice 0 va in cima.
                                sort=alt.SortField(field='sort_index', order='descending') 
                               ),
                tooltip=['Time (min)', 'Source', 'Rate (g/h)']
            ).interactive()
            
            st.altair_chart(chart_stack, use_container_width=True)
            
            # INSIGHT SCIENTIFICI BURN
            with st.expander("Note Tecniche: Cinetica Deplezione & Sparing"):
                st.info("""
                **Modello Fisiologico di Riferimento (Coggan & Coyle 1991; King 2018)**
                
                * **Non-Linearità (Fatigue Drift):** L'utilizzo del glicogeno muscolare non è costante, ma decade progressivamente man mano che le scorte intramuscolari diminuiscono, richiedendo un maggiore contributo dal glucosio ematico e dai lipidi (Gollnick et al., 1973). 
                * **Effetto Sparing:** L'ingestione di carboidrati esogeni non riduce significativamente l'uso del glicogeno muscolare nelle fasi iniziali, ma diventa critica per proteggere il glicogeno epatico e sostenere l'ossidazione dei carboidrati nelle fasi avanzate (King et al., 2018).
                """)
                
            # EXPANDER FRAYN RICHIESTO
            with st.expander("Note Metodologiche: Equazioni Metaboliche (Frayn)"):
                st.info("""
                **Calcolo Stechiometrico dei Substrati**
                
                Le stime dei tassi di ossidazione di carboidrati e lipidi si basano sulle equazioni standardizzate di *Frayn (1983)*, che derivano il consumo netto dei substrati dal Quoziente Respiratorio (RER/RQ) stimato. Questo approccio assume un modello di "ossidazione netta" che incorpora implicitamente i flussi gluconeogenici epatici nel bilancio complessivo.
                """)

            st.caption("Confronto: Deplezione Glicogeno Totale (Strategia vs Digiuno) ")
            
            # --- NUOVA LOGICA PER GRAFICO CON BANDE DI RISCHIO BASATO SU TOTALE GLICOGENO ---
            
            # 1. Calcola i livelli in base al serbatoio TOTALE iniziale
            initial_total_glycogen = tank_data['muscle_glycogen_g'] + tank_data['liver_glycogen_g']
            max_total = initial_total_glycogen * 1.05 # Max per l'asse Y
            
            # Definizioni delle soglie di rischio sul TOTALE GLICOGENO INIZIALE
            zone_green_end = initial_total_glycogen * 1.05 
            zone_yellow_end = initial_total_glycogen * 0.65 # Sotto il 65% si entra in zona gialla
            zone_red_end = initial_total_glycogen * 0.30 # Sotto il 30% si entra in zona critica
            
            # Si considerano 20g come limite minimo per la glicemia (rischio bonk)
            MIN_GLUCEMIA_LIMIT = 20
            
            zones_df = pd.DataFrame({
                'Zone': ['Sicurezza (Verde)', 'Warning (Giallo)', 'Critico (Rosso)'],
                # Gli intervalli sono definiti dal basso verso l'alto
                'Start': [zone_yellow_end, MIN_GLUCEMIA_LIMIT, 0],
                'End': [zone_green_end, zone_yellow_end, MIN_GLUCEMIA_LIMIT],
                'Color': ['#4CAF50', '#FFC107', '#F44336'] # Verde, Giallo, Rosso Scuro
            })

            # 2. Layer 1: Sfondo colorato (Bande)
            background = alt.Chart(zones_df).mark_rect(opacity=0.15).encode(
                y=alt.Y('Start', axis=None), 
                y2=alt.Y2('End'),         
                color=alt.Color('Color', scale=None), 
                tooltip=['Zone']
            )

            # 3. Layer 2: Linee di Deplezione. Usa 'Residuo Totale'.
            lines = alt.Chart(combined_df).mark_line(strokeWidth=3).encode(
                x=alt.X('Time (min)', title='Durata (min)'),
                y=alt.Y('Residuo Totale', title='Glicogeno Totale Residuo (g)', scale=alt.Scale(domain=[0, max_total])), # <--- MODIFICA 2: Usa Residuo Totale
                
                color=alt.Color('Scenario', 
                                scale=alt.Scale(domain=['Con Integrazione (Strategia)', 'Senza Integrazione (Digiuno)'], 
                                                range=['#D32F2F', '#757575']
                                                ),
                                legend=alt.Legend(title="Scenario")
                               ),
                tooltip=['Time (min)', 'Residuo Totale', 'Stato', 'Scenario']
            ).interactive()

            # 4. Combinazione dei Layer
            chart = (background + lines).properties(
                title="Confronto: Deplezione Glicogeno Totale (Strategia vs Digiuno)"
            ).resolve_scale(
                y='shared' 
            )

            st.altair_chart(chart, use_container_width=True)
            # --- FINE NUOVA LOGICA GRAFICO ---

        with g2:
            st.caption("Accumulo Intestinale (Rischio GI)")
            gut_chart = alt.Chart(df_sim).mark_area(color='#8D6E63', opacity=0.6).encode(
                x='Time (min)', y='Gut Load'
            )
            risk_line = alt.Chart(pd.DataFrame({'y': [30]})).mark_rule(color='red', strokeDash=[2,2]).encode(y='y')
            st.altair_chart((gut_chart + risk_line).properties(height=250), use_container_width=True)
            
            with st.expander("Note Tecniche: Tolleranza Gastrointestinale"):
                 st.info("""
                 **Limiti di Ossidazione e Distress GI**
                 Come evidenziato da *Podlogar et al. (2025)*, la capacità di ossidazione esogena non è illimitata ed è correlata alla taglia corporea e alla potenza metabolica. L'ingestione superiore alla capacità di ossidazione porta ad accumulo intestinale, aumentando il rischio di disturbi gastrointestinali (GI Distress). 
                 """)
            
            st.markdown("---")
            st.caption("Ossidazione Lipidica")
            st.line_chart(df_sim.set_index("Time (min)")["Ossidazione Lipidica (g)"], color="#FFA500")
        
        st.subheader("Strategia & Timing")
        
        liver_bonk_time = df_sim[df_sim['Residuo Epatico'] <= 0]['Time (min)'].min()
        muscle_bonk_time = df_sim[df_sim['Residuo Muscolare'] <= 20]['Time (min)'].min()
        bonk_time = min(filter(lambda x: not np.isnan(x), [liver_bonk_time, muscle_bonk_time]), default=None)
        
        s1, s2 = st.columns([2, 1])
        with s1:
            if bonk_time:
                st.error(f"CRITICITÀ RILEVATA AL MINUTO {int(bonk_time)}")
                if not np.isnan(liver_bonk_time) and liver_bonk_time == bonk_time:
                    st.write("Causa Primaria: **Esaurimento Glicogeno Epatico (Ipoglicemia)**.")
                else:
                    st.write("Causa Primaria: **Esaurimento Glicogeno Muscolare**.")
            else:
                st.success("STRATEGIA SOSTENIBILE")
                st.write("Il bilancio energetico stimato consente di completare la prova senza deplezione critica.")
        
        with s2:
            if bonk_time:
                st.metric("Tempo Limite Stimato", f"{int(bonk_time)} min", delta_color="inverse")
            else:
                st.metric("Buffer Energetico", "Adeguato")
        
        st.markdown("### 📋 Cronotabella di Integrazione")
        
        if carb_intake > 0 and cho_per_unit > 0:
            units_per_hour = carb_intake / cho_per_unit
            if units_per_hour > 0:
                interval_min = 60 / units_per_hour
                interval_int = int(interval_min)
                
                schedule = []
                current_time = interval_int
                total_cho_ingested = 0
                
                while current_time <= duration:
                    total_cho_ingested += cho_per_unit
                    schedule.append({
                        "Minuto": current_time,
                        "Azione": f"Assumere 1 unità ({cho_per_unit}g CHO)",
                        "Totale Ingerito": f"{total_cho_ingested}g"
                    })
                    current_time += interval_int
                
                if schedule:
                    st.table(pd.DataFrame(schedule))
                else:
                    st.info("Durata troppo breve per l'intervallo di assunzione calcolato.")
            else:
                st.warning("Verificare i parametri di integrazione.")
        else:
            st.info("Nessuna integrazione pianificata.")
