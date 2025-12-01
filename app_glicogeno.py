import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from dataclasses import dataclass, replace 
from enum import Enum
import math
import xml.etree.ElementTree as ET
import io
from datetime import datetime

# ==============================================================================
# 0. SISTEMA DI PROTEZIONE (LOGIN)
# ==============================================================================
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

# ==============================================================================
# 1. DEFINIZIONI E CLASSI (Dati Statici)
# ==============================================================================

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

class ChoMixType(Enum):
    GLUCOSE_ONLY = (1.0, 60.0, "Solo Glucosio/Maltodestrine (Standard)")
    MIX_2_1 = (1.5, 90.0, "Mix 2:1 (Maltodestrine:Fruttosio)")
    MIX_1_08 = (1.7, 105.0, "Mix 1:0.8 (High Fructose)")

    def __init__(self, ox_factor, max_rate_gh, label):
        self.ox_factor = ox_factor 
        self.max_rate_gh = max_rate_gh 
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
    muscle_mass_kg: float = None 

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        base = 0.50 if self.sex == Sex.MALE else 0.42
        if self.glycogen_conc_g_kg >= 22.0:
            base += 0.03
        return base

# ==============================================================================
# 2. FUNZIONI DI CALCOLO (Logica Core - Cached)
# ==============================================================================

@st.cache_data
def get_concentration_from_vo2max(vo2_max):
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

@st.cache_data
def calculate_depletion_factor(steps, activity_min, s_fatigue_factor):
    steps_base = 10000 
    steps_factor = (steps - steps_base) / 5000 * 0.1 * 0.4
    activity_base = 120 
    if activity_min < 60: 
        activity_factor = (1 - (activity_min / 60)) * 0.05 * 0.6
    else:
        activity_factor = (activity_min - activity_base) / 60 * -0.1 * 0.6
        
    depletion_impact = steps_factor + activity_factor
    estimated_depletion_factor = max(0.6, min(1.0, 1.0 + depletion_impact))
    
    if steps == 0 and activity_min == 0:
        return s_fatigue_factor
    else:
        return estimated_depletion_factor

@st.cache_data
def calculate_filling_factor_from_diet(weight_kg, cho_day_minus_1_g, cho_day_minus_2_g, s_fatigue_factor, s_sleep_factor, steps_m1, min_act_m1, steps_m2, min_act_m2):
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    
    cho_day_minus_1_g = max(cho_day_minus_1_g, 1.0) 
    cho_day_minus_2_g = max(cho_day_minus_2_g, 1.0) 
    
    cho_day_minus_1_gk = cho_day_minus_1_g / weight_kg
    cho_day_minus_2_gk = cho_day_minus_2_g / weight_kg
    
    depletion_m1_factor = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue_factor)
    depletion_m2_factor = calculate_depletion_factor(steps_m2, min_act_m2, s_fatigue_factor)
    
    recovery_factor = (depletion_m1_factor * 0.7) + (depletion_m2_factor * 0.3)
    avg_cho_gk = (cho_day_minus_1_gk * 0.7) + (cho_day_minus_2_gk * 0.3)
    
    if avg_cho_gk >= CHO_MAX_GK:
        diet_factor_base = 1.25
    elif avg_cho_gk >= CHO_BASE_GK:
        diet_factor_base = 1.0 + (avg_cho_gk - CHO_BASE_GK) * (0.25 / (CHO_MAX_GK - CHO_BASE_GK))
    elif avg_cho_gk > CHO_MIN_GK:
        diet_factor_base = 0.5 + (avg_cho_gk - CHO_MIN_GK) * (0.5 / (CHO_BASE_GK - CHO_MIN_GK))
        diet_factor_base = max(0.5, diet_factor_base)
    else: 
        diet_factor_base = 0.5
    
    diet_factor_base = min(1.25, max(0.5, diet_factor_base)) 
    final_diet_depletion_factor = diet_factor_base * recovery_factor 
    combined_filling = final_diet_depletion_factor * s_sleep_factor
    
    return combined_filling, final_diet_depletion_factor, avg_cho_gk

def calculate_tank(subject: Subject):
    if subject.muscle_mass_kg is not None and subject.muscle_mass_kg > 0:
        total_muscle = subject.muscle_mass_kg
        muscle_source_note = "Massa Muscolare Totale (SMM) fornita dall'utente."
    else:
        lbm = subject.lean_body_mass
        total_muscle = lbm * subject.muscle_fraction
        muscle_source_note = "Massa Muscolare Totale stimata da Peso/BF/Sesso."

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
        "liver_note": liver_correction_note,
        "muscle_source_note": muscle_source_note
    }

@st.cache_data
def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts, mix_type_val, mix_type_max_rate, mix_type_ox_factor):
    base_rate = 0.8 
    if height_cm > 170: base_rate += (height_cm - 170) * 0.015
    if ftp_watts > 200: base_rate += (ftp_watts - 200) * 0.0015
    
    estimated_rate_gh = base_rate * 60 * mix_type_ox_factor
    final_rate_g_min = min(estimated_rate_gh / 60, mix_type_max_rate / 60)
    return final_rate_g_min

@st.cache_data
def calculate_rer_polynomial(intensity_factor):
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 
           141.538462237 * (if_val**5) - 
           565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 
           691.67948706 * (if_val**2) + 
           265.460857558 * if_val - 
           39.525121144)
    return max(0.70, min(1.15, rer))

# Funzione di simulazione principale
@st.cache_data
def simulate_metabolism_cached(
    tank_g, initial_muscle_g, initial_liver_g,
    duration_min, constant_carb_intake_g_h, cho_per_unit_g,
    crossover_pct, tau_absorption,
    height_cm, weight_kg, vo2max_abs_l_min,
    mode, efficiency, avg_power, ftp_watts, avg_hr, max_hr, thr_hr,
    is_lab_data, lab_cho_rate, lab_fat_rate,
    oxidation_efficiency, custom_max_exo_rate, 
    mix_type_max_rate, mix_type_ox_factor,
    intensity_series, intensity_factor_ref, speed_kmh
):
    results = []
    current_muscle_glycogen = initial_muscle_g
    current_liver_glycogen = initial_liver_g
    
    kcal_per_min_base = 10.0
    if mode == 'cycling':
        kcal_per_min_base = (avg_power * 60) / 4184 / (efficiency / 100.0)
    elif mode == 'running':
        kcal_per_hour = 1.0 * weight_kg * speed_kmh
        kcal_per_min_base = kcal_per_hour / 60.0
    else:
        vo2_operating = vo2max_abs_l_min * intensity_factor_ref
        kcal_per_min_base = vo2_operating * 5.0

    crossover_if = crossover_pct / 100.0
    
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate 
    else:
        max_exo_rate_g_min = estimate_max_exogenous_oxidation(
            height_cm, weight_kg, ftp_watts, 
            None, mix_type_max_rate, mix_type_ox_factor 
        )
    
    total_fat_burned_g = 0.0
    gut_accumulation_total = 0.0
    current_exo_oxidation_g_min = 0.0 
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    total_intake_cumulative = 0.0
    total_exo_oxidation_cumulative = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_per_hour > 0 else duration_min + 1
    is_input_zero = constant_carb_intake_g_h == 0
    
    for t in range(int(duration_min) + 1):
        current_intensity_factor = intensity_factor_ref
        if intensity_series is not None and t < len(intensity_series):
            current_intensity_factor = intensity_series[t]
        
        current_kcal_demand = 0.0
        if mode == 'cycling':
            instant_power = current_intensity_factor * ftp_watts
            current_eff = efficiency
            if t > 60: 
                loss = (t - 60) * 0.02
                current_eff = max(15.0, efficiency - loss)
            current_kcal_demand = (instant_power * 60) / 4184 / (current_eff / 100.0)
        else: 
            demand_scaling = current_intensity_factor / intensity_factor_ref if intensity_factor_ref > 0 else 1.0
            drift_factor = 1.0
            if t > 60: drift_factor += (t - 60) * 0.0005 
            current_kcal_demand = kcal_per_min_base * drift_factor * demand_scaling
        
        instantaneous_input_g_min = 0.0 
        if not is_input_zero and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instantaneous_input_g_min = cho_per_unit_g 
        
        target_exo_oxidation_limit_g_min = max_exo_rate_g_min * oxidation_efficiency
        
        if t > 0:
            if is_input_zero:
                current_exo_oxidation_g_min *= (1 - alpha) 
            else:
                current_exo_oxidation_g_min += alpha * (target_exo_oxidation_limit_g_min - current_exo_oxidation_g_min)
            if current_exo_oxidation_g_min < 0: current_exo_oxidation_g_min = 0.0
        else:
            current_exo_oxidation_g_min = 0.0
            
        if t > 0:
            gut_accumulation_total += (instantaneous_input_g_min * oxidation_efficiency) - current_exo_oxidation_g_min
            if gut_accumulation_total < 0: gut_accumulation_total = 0 
            total_intake_cumulative += instantaneous_input_g_min 
            total_exo_oxidation_cumulative += current_exo_oxidation_g_min
        
        if is_lab_data:
            fatigue_mult = 1.0 + ((t - 30) * 0.0005) if t > 30 else 1.0 
            total_cho_demand = lab_cho_rate * fatigue_mult 
            kcal_cho_demand = total_cho_demand * 4.1
            glycogen_burned_per_min = total_cho_demand - current_exo_oxidation_g_min
            min_endo = total_cho_demand * 0.2 
            if glycogen_burned_per_min < min_endo: glycogen_burned_per_min = min_endo
            lab_fat_rate_min = lab_fat_rate / 60
            cho_ratio = total_cho_demand / (total_cho_demand + lab_fat_rate_min) if (total_cho_demand + lab_fat_rate_min) > 0 else 0
            rer = 0.7 + (0.3 * cho_ratio) 
        else:
            effective_if_for_rer = current_intensity_factor + ((75.0 - crossover_pct) / 100.0)
            if effective_if_for_rer < 0.3: effective_if_for_rer = 0.3
            rer = calculate_rer_polynomial(effective_if_for_rer)
            base_cho_ratio = (rer - 0.70) * 3.45
            base_cho_ratio = max(0.0, min(1.0, base_cho_ratio))
            current_cho_ratio = base_cho_ratio
            if current_intensity_factor < 0.85 and t > 60:
                hours_past = (t - 60) / 60.0
                metabolic_shift = 0.05 * (hours_past ** 1.2) 
                current_cho_ratio = max(0.05, base_cho_ratio - metabolic_shift)
            cho_ratio = current_cho_ratio
            fat_ratio = 1.0 - cho_ratio
            kcal_cho_demand = current_kcal_demand * cho_ratio
        
        total_cho_g_min = kcal_cho_demand / 4.1
        kcal_from_exo = current_exo_oxidation_g_min * 3.75 
        
        # CORREZIONE NAMEERROR: usa initial_muscle_g invece di initial_muscle_glycogen
        muscle_fill_state = current_muscle_glycogen / initial_muscle_g if initial_muscle_g > 0 else 0
        muscle_contribution_factor = math.pow(muscle_fill_state, 0.6) 
        
        muscle_usage_g_min = total_cho_g_min * muscle_contribution_factor
        if current_muscle_glycogen <= 0: muscle_usage_g_min = 0
        blood_glucose_demand_g_min = total_cho_g_min - muscle_usage_g_min
        from_exogenous = min(blood_glucose_demand_g_min, current_exo_oxidation_g_min)
        remaining_blood_demand = blood_glucose_demand_g_min - from_exogenous
        max_liver_output = 1.2 
        from_liver = min(remaining_blood_demand, max_liver_output)
        if current_liver_glycogen <= 0: from_liver = 0
        
        if t > 0:
            current_muscle_glycogen -= muscle_usage_g_min
            current_liver_glycogen -= from_liver
            if current_muscle_glycogen < 0: current_muscle_glycogen = 0
            if current_liver_glycogen < 0: current_liver_glycogen = 0
            if not is_lab_data:
                fat_ratio_used = 1.0 - cho_ratio
                total_fat_burned_g += (current_kcal_demand * fat_ratio_used) / 9.0
            else:
                total_fat_burned_g += lab_fat_rate
            
            total_muscle_used += muscle_usage_g_min
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        status_label = "Ottimale"
        if current_liver_glycogen < 20: status_label = "CRITICO (Ipoglicemia)"
        elif current_muscle_glycogen < 100: status_label = "Warning (Gambe Vuote)"
            
        exo_oxidation_g_h = from_exogenous * 60
        g_muscle = muscle_usage_g_min
        g_liver = from_liver
        g_exo = from_exogenous
        fat_ratio_used_local = 1.0 - cho_ratio if not is_lab_data else (lab_fat_rate / 60 * 9.0) / current_kcal_demand if current_kcal_demand > 0 else 0.0
        g_fat = (current_kcal_demand * fat_ratio_used_local / 9.0)
        total_g_min = g_muscle + g_liver + g_exo + g_fat
        if total_g_min == 0: total_g_min = 1.0 
        
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": muscle_usage_g_min * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": exo_oxidation_g_h, 
            "Ossidazione Lipidica (g)": lab_fat_rate * 60 if is_lab_data else ((current_kcal_demand * (1.0 - cho_ratio)) / 9.0) * 60,
            "Pct_Muscle": f"{(g_muscle / total_g_min * 100):.1f}%",
            "Pct_Liver": f"{(g_liver / total_g_min * 100):.1f}%",
            "Pct_Exo": f"{(g_exo / total_g_min * 100):.1f}%",
            "Pct_Fat": f"{(g_fat / total_g_min * 100):.1f}%",
            "Residuo Muscolare": current_muscle_glycogen,
            "Residuo Epatico": current_liver_glycogen,
            "Residuo Totale": current_muscle_glycogen + current_liver_glycogen, 
            "Target Intake (g/h)": constant_carb_intake_g_h, 
            "Gut Load": gut_accumulation_total,
            "Stato": status_label,
            "CHO %": cho_ratio * 100,
            "Intake Cumulativo (g)": total_intake_cumulative,
            "Ossidazione Cumulativa (g)": total_exo_oxidation_cumulative,
            "Intensity Factor (IF)": current_intensity_factor 
        })
        
    stats = {
        "final_muscle": current_muscle_glycogen,
        "final_liver": current_liver_glycogen,
        "final_glycogen": current_muscle_glycogen + current_liver_glycogen, 
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "kcal_total_h": current_kcal_demand * 60,
        "gut_accumulation": (gut_accumulation_total / duration_min) * 60 if duration_min > 0 else 0,
        "max_exo_capacity": max_exo_rate_g_min * 60,
        "intensity_factor": intensity_factor_ref,
        "avg_rer": rer,
        "gross_efficiency": gross_efficiency,
        "intake_g_h": constant_carb_intake_g_h,
        "cho_pct": cho_ratio * 100
    }
    return pd.DataFrame(results), stats

# --- PARSING FILE ---

@st.cache_data
def parse_zwo_file(file_content, ftp_watts, thr_hr, sport_type_val):
    try:
        root = ET.fromstring(file_content)
    except ET.ParseError:
        return [], 0, 0, 0, None

    zwo_sport_tag = root.findtext('sportType')
    sport_warning = None
    
    # La logica enum non è serializzabile facilmente, usiamo i valori
    if zwo_sport_tag:
        if zwo_sport_tag.lower() == 'bike' and sport_type_val != SportType.CYCLING.value:
            sport_warning = "ATTENZIONE: File BICI su profilo diverso."
        elif zwo_sport_tag.lower() == 'run' and sport_type_val != SportType.RUNNING.value:
            sport_warning = "ATTENZIONE: File CORSA su profilo diverso."

    intensity_series = [] 
    total_duration_sec = 0
    total_weighted_if = 0
    
    for steady_state in root.findall('.//SteadyState'):
        try:
            duration_sec = int(steady_state.get('Duration'))
            power_ratio = float(steady_state.get('Power'))
            duration_min_segment = math.ceil(duration_sec / 60)
            intensity_factor = power_ratio 
            
            for _ in range(duration_min_segment):
                intensity_series.append(intensity_factor)
            
            total_duration_sec += duration_sec
            total_weighted_if += intensity_factor * (duration_sec / 60) 
        except: continue

    total_duration_min = math.ceil(total_duration_sec / 60)
    avg_power = 0
    avg_hr = 0
    
    if total_duration_min > 0:
        avg_if = total_weighted_if / total_duration_min
        if sport_type_val == SportType.CYCLING.value:
            avg_power = avg_if * ftp_watts
        elif sport_type_val == SportType.RUNNING.value:
            avg_hr = avg_if * thr_hr
        else: 
            avg_hr = avg_if * 185 * 0.85 
            
    return intensity_series, total_duration_min, avg_power, avg_hr, sport_warning

# --- FUNZIONI AUSILIARIE UI ---

def calculate_zones_cycling(ftp):
    return [
        {"Zona": "Z1 - Recupero Attivo", "Range %": "< 55%", "Valore": f"< {int(ftp*0.55)} W"},
        {"Zona": "Z2 - Endurance (Fondo Lento)", "Range %": "56 - 75%", "Valore": f"{int(ftp*0.56)} - {int(ftp*0.75)} W"},
        {"Zona": "Z3 - Tempo (Medio)", "Range %": "76 - 90%", "Valore": f"{int(ftp*0.76)} - {int(ftp*0.90)} W"},
        {"Zona": "Z4 - Soglia (FTP)", "Range %": "91 - 105%", "Valore": f"{int(ftp*0.91)} - {int(ftp*1.05)} W"},
        {"Zona": "Z5 - VO2max", "Range %": "106 - 120%", "Valore": f"{int(ftp*1.06)} - {int(ftp*1.20)} W"},
        {"Zona": "Z6 - Capacità Anaerobica", "Range %": "121 - 150%", "Valore": f"{int(ftp*1.21)} - {int(ftp*1.50)} W"},
        {"Zona": "Z7 - Potenza Neuromuscolare", "Range %": "> 150%", "Valore": f"> {int(ftp*1.50)} W"}
    ]

def calculate_zones_running_hr(thr):
    return [
        {"Zona": "Z1 - Recupero", "Range %": "< 85% LTHR", "Valore": f"< {int(thr*0.85)} bpm"},
        {"Zona": "Z2 - Aerobico", "Range %": "85 - 89% LTHR", "Valore": f"{int(thr*0.85)} - {int(thr*0.89)} bpm"},
        {"Zona": "Z3 - Tempo", "Range %": "90 - 94% LTHR", "Valore": f"{int(thr*0.90)} - {int(thr*0.94)} bpm"},
        {"Zona": "Z4 - Sub-Soglia", "Range %": "95 - 99% LTHR", "Valore": f"{int(thr*0.95)} - {int(thr*0.99)} bpm"},
        {"Zona": "Z5a - Super-Soglia (FTP)", "Range %": "100 - 102% LTHR", "Valore": f"{int(thr*1.00)} - {int(thr*1.02)} bpm"},
        {"Zona": "Z5b - Capacità Aerobica", "Range %": "103 - 106% LTHR", "Valore": f"{int(thr*1.03)} - {int(thr*1.06)} bpm"},
        {"Zona": "Z5c - Potenza Anaerobica", "Range %": "> 106% LTHR", "Valore": f"> {int(thr*1.06)} bpm"}
    ]

# ==============================================================================
# 3. MAIN APPLICATION LOGIC
# ==============================================================================

def main():
    st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
    st.title("Glycogen Simulator Pro")
    st.markdown("Strumento di stima delle riserve energetiche e simulazione del metabolismo sotto sforzo.")

    # --- AUTH ---
    if not check_password():
        st.stop()

    # --- NOTE ---
    with st.expander("📘 Note Tecniche & Fonti Scientifiche"):
        st.info("""
        **1. Stima Riserve & Capacità di Stoccaggio**
        * **Stima della Concentrazione (g/kg):** Basata su correlazione fitness aerobico (VO2max) e densità stoccaggio (Burke et al., 2017).
        * **Capacità Massima:** Supercompensazione con carichi CHO >8 g/kg/die in 36-48h (Bergström et al., 1967).
        
        **2. Sviluppi Recenti (Rothschild et al., 2022)**
        * **Peso dei Fattori (RER):** Sesso e Durata sono determinanti. La Dieta CHO/Fat 48h ha influenza maggiore dell'assunzione in gara.
        * **Variabilità e Rischio GI:** Alta variabilità in ossidazione CHO esogeni. Accumulo è predittore distress GI (Podlogar et al., 2025).
        """)

    tab1, tab2, tab3 = st.tabs(["1. Profilo Base & Capacità", "2. Preparazione & Diario", "3. Simulazione & Strategia"])

    # --- TAB 1 ---
    with tab1:
        col_in, col_res = st.columns([1, 2])
        with col_in:
            st.subheader("1. Dati Antropometrici")
            weight = st.slider("Peso Corporeo (kg)", 45.0, 100.0, 74.0, 0.5)
            height = st.slider("Altezza (cm)", 150, 210, 187, 1)
            bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 11.0, 0.5) / 100.0
            sex_map = {s.value: s for s in Sex}
            s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
            
            use_smm = st.checkbox("Usa SMM (Impedenziometria/DEXA)")
            muscle_mass_input = st.number_input("SMM [kg]", 10.0, 60.0, 37.4, 0.1) if use_smm else None
            
            st.markdown("---")
            st.subheader("2. Capacità Stoccaggio")
            est_method = st.radio("Metodo stima:", ["Livello", "VO2max"], horizontal=True, label_visibility="collapsed")
            
            vo2_input = 60.0
            if est_method == "Livello":
                status_map = {s.label: s for s in TrainingStatus}
                s_status = status_map[st.selectbox("Livello", list(status_map.keys()), index=3)]
                calculated_conc = s_status.val
                vo2_input = 30 + ((calculated_conc - 13.0) / 0.24)
            else:
                vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, 1)
                calculated_conc = get_concentration_from_vo2max(vo2_input)
            
            st.caption(f"Conc. stimata: **{calculated_conc:.1f} g/kg**")

            sport_map = {s.label: s for s in SportType}
            s_sport = sport_map[st.selectbox("Disciplina", list(sport_map.keys()))]
            
            st.markdown("#### Dati di Soglia")
            ftp_watts_input = 265
            thr_hr_input = 170
            max_hr_input = 185
            
            with st.expander("Inserisci Soglie", expanded=True):
                if s_sport == SportType.CYCLING:
                    ftp_watts_input = st.number_input("FTP [Watt]", 100, 600, 265, 5)
                    zones_data = calculate_zones_cycling(ftp_watts_input)
                elif s_sport == SportType.RUNNING:
                    c1, c2 = st.columns(2)
                    thr_hr_input = c1.number_input("Soglia Anaerobica [BPM]", 100, 220, 170, 1)
                    max_hr_input = c2.number_input("FC Max [BPM]", 100, 220, 185, 1)
                    zones_data = calculate_zones_running_hr(thr_hr_input)
                else:
                    c1, c2 = st.columns(2)
                    max_hr_input = c2.number_input("FC Max [BPM]", 100, 220, 185, 1)
                    thr_hr_input = c1.number_input("Soglia Aerobica [BPM]", 80, max_hr_input, 150, 1)
                    zones_data = []

                if zones_data:
                    st.table(pd.DataFrame(zones_data))

            # Salviamo nello stato
            st.session_state['ftp'] = ftp_watts_input
            st.session_state['thr'] = thr_hr_input
            st.session_state['max_hr'] = max_hr_input

            with st.expander("Fattori Avanzati"):
                use_creatine = st.checkbox("Creatina")
                s_menstrual = MenstrualPhase.NONE
                if s_sex == Sex.FEMALE:
                    menstrual_map = {m.label: m for m in MenstrualPhase}
                    s_menstrual = menstrual_map[st.selectbox("Fase Ciclo", list(menstrual_map.keys()))]
            
            # Calcolo Tank
            subject = Subject(
                weight_kg=weight, height_cm=height, body_fat_pct=bf, sex=s_sex,
                glycogen_conc_g_kg=calculated_conc, sport=s_sport,
                liver_glycogen_g=100.0, filling_factor=1.0,
                uses_creatine=use_creatine, menstrual_phase=s_menstrual,
                glucose_mg_dl=None, vo2max_absolute_l_min=(vo2_input*weight)/1000,
                muscle_mass_kg=muscle_mass_input
            )
            tank_data = calculate_tank(subject)
            st.session_state['base_subject'] = subject
            st.session_state['tank_data_base'] = tank_data

        with col_res:
            st.subheader("Riepilogo Capacità Massima")
            st.metric("Capacità Teorica", f"{int(tank_data['max_capacity_g'])} g")
            st.progress(100)
            c1, c2 = st.columns(2)
            c1.metric("Massa Muscolare Attiva", f"{tank_data['active_muscle_kg']:.1f} kg")
            c2.metric("Energia Max (CHO)", f"{int(tank_data['max_capacity_g'] * 4.1)} kcal")

    # --- TAB 2 ---
    with tab2:
        if 'tank_data_base' not in st.session_state:
            st.warning("Vai al Tab 1 per configurare il profilo.")
            st.stop()

        subj = st.session_state['base_subject']
        col_in_2, col_res_2 = st.columns([1, 1])
        
        fatigue_map = {f.label: f for f in FatigueState}
        sleep_map = {s.label: s for s in SleepQuality}

        # --- INIZIALIZZAZIONE VARIABILI PER EVITARE NAMEERROR ---
        cho_g1 = subj.weight_kg * DietType.NORMAL.ref_value
        cho_g2 = subj.weight_kg * DietType.NORMAL.ref_value

        with col_in_2:
            st.markdown("**1. Nutrizione (48h)**")
            diet_method = st.radio("Metodo:", ["Veloce", "Preciso"], horizontal=True)
            
            if diet_method == "Veloce":
                diet_opts = {d.label: d for d in DietType}
                s_diet_label = st.selectbox("Introito", list(diet_opts.keys()), index=1)
                s_diet = diet_opts[s_diet_label]
                # Sovrascriviamo con i valori selezionati
                cho_g1 = subj.weight_kg * s_diet.ref_value
                cho_g2 = cho_g1
            else:
                c1, c2 = st.columns(2)
                # Sovrascriviamo con i valori manuali
                cho_g2 = c1.number_input("CHO G-2 (g)", 0, 1000, 370)
                cho_g1 = c2.number_input("CHO G-1 (g)", 0, 1000, 370)

            st.markdown("**2. Recupero**")
            s_fatigue = fatigue_map[st.selectbox("Carico Lavoro", list(fatigue_map.keys()))]
            s_sleep = sleep_map[st.selectbox("Sonno", list(sleep_map.keys()), index=1)]
            
            with st.expander("Attività Specifica (Opzionale)"):
                c1, c2 = st.columns(2)
                steps_m1 = c1.number_input("Passi G-1", 0, 30000, 5000)
                min_act_m1 = c2.number_input("Minuti Sport G-1", 0, 300, 30)
                steps_m2 = 0; min_act_m2 = 0
            
            st.markdown("**3. Metabolico Acuto**")
            has_gluc = st.checkbox("Misurazione Glicemia")
            gluc_val = st.number_input("mg/dL", 40, 200, 90) if has_gluc else None
            is_fasted = False
            if not has_gluc:
                is_fasted = st.checkbox("Allenamento a Digiuno")
            
            # Calcolo combinato filling (passando fattori enum)
            combined_filling, _, _ = calculate_filling_factor_from_diet(
                subj.weight_kg, cho_g1, cho_g2, 
                s_fatigue.factor, s_sleep.factor, 
                steps_m1, min_act_m1, steps_m2, min_act_m2
            )
            
            # Update Subject con copia corretta usando replace (FIXED ATTRIBUTE ERROR)
            subj_current = replace(subj)
            subj_current.filling_factor = combined_filling
            subj_current.glucose_mg_dl = gluc_val
            if is_fasted: 
                subj_current.liver_glycogen_g = 40.0
            
            tank_current = calculate_tank(subj_current)
            st.session_state['tank_current'] = tank_current
            st.session_state['subj_current'] = subj_current

        with col_res_2:
            st.subheader("Stato Pre-Evento")
            fill = tank_current['fill_pct']
            st.metric("Riempimento", f"{fill:.1f}%")
            st.progress(int(fill))
            
            if fill < 60: st.error("Riserve Critiche (<60%)")
            elif fill > 90: st.success("Ottimale")
            else: st.warning("Normale")
            
            c1, c2 = st.columns(2)
            c1.metric("Muscolo", f"{int(tank_current['muscle_glycogen_g'])} g")
            c2.metric("Fegato", f"{int(tank_current['liver_glycogen_g'])} g")

    # --- TAB 3 ---
    with tab3:
        if 'tank_current' not in st.session_state:
            st.warning("Completa i tab precedenti.")
            st.stop()
            
        tank = st.session_state['tank_current']
        subj = st.session_state['subj_current']
        
        c_param, c_res = st.columns([1, 1])
        
        # Defaults
        ftp = st.session_state['ftp']
        thr = st.session_state['thr']
        max_h = st.session_state['max_hr']
        
        avg_w = 200
        avg_hr = 150
        duration = 120
        int_series = None
        
        with c_param:
            st.subheader("1. Parametri Sforzo")
            source = st.radio("Dati:", ["Manuale", "File"], horizontal=True)
            
            if source == "File":
                f = st.file_uploader("File attività (.zwo/.gpx/.csv)")
                if f:
                    content = f.getvalue().decode("utf-8") # Read once
                    if f.name.endswith('.zwo'):
                        # Parsing ZWO cached logic would require extracting pure data, here we call direct
                        # Estraiamo sport type per passarlo come valore
                        int_series, dur, w, h, warn = parse_zwo_file(content, ftp, thr, subj.sport.val)
                        if warn: st.warning(warn)
                        if int_series:
                            duration = dur
                            if subj.sport == SportType.CYCLING: avg_w = w
                            else: avg_hr = h
                            st.success(f"ZWO Caricato: {dur} min")
                    else:
                        st.info("Supporto CSV/GPX semplificato.")
                        # Qui andrebbe il parsing CSV/GPX
            
            if subj.sport == SportType.CYCLING:
                avg_w = st.number_input("Watt Medi", 0, 1000, int(avg_w))
                if_ref = avg_w / ftp
            else:
                avg_hr = st.number_input("FC Media", 0, 220, int(avg_hr))
                if_ref = avg_hr / thr if thr > 0 else 0.7
                
            duration = st.slider("Durata (min)", 30, 600, int(duration))
            
            st.subheader("2. Strategia Integrazione")
            cho_dose = st.slider("Target CHO (g/h)", 0, 120, 60)
            cho_unit = st.number_input("g per Unità", 10, 100, 25)
            
            mix_opts = list(ChoMixType)
            mix = st.selectbox("Mix", mix_opts, format_func=lambda x: x.label)
            
            with st.expander("Avanzate"):
                eff = st.slider("Efficienza Ox %", 0.5, 1.0, 0.8)
                tau = st.slider("Tau Assorbimento", 5, 60, 20)

        # Calcolo Simulazione (Cached)
        # Preparazione argomenti per la funzione cached (devono essere hashable)
        # Scompatto oggetti complessi
        
        df_sim, stats = simulate_metabolism_cached(
            tank_g=tank['actual_available_g'],
            initial_muscle_g=tank['muscle_glycogen_g'],
            initial_liver_g=tank['liver_glycogen_g'],
            duration_min=duration,
            constant_carb_intake_g_h=cho_dose,
            cho_per_unit_g=cho_unit,
            crossover_pct=70, # Default
            tau_absorption=tau,
            height_cm=subj.height_cm,
            weight_kg=subj.weight_kg,
            vo2max_abs_l_min=subj.vo2max_absolute_l_min,
            mode='cycling' if subj.sport == SportType.CYCLING else 'running', # Stringa semplice
            efficiency=22.0, # Default
            avg_power=avg_w,
            ftp_watts=ftp,
            avg_hr=avg_hr,
            max_hr=max_h,
            thr_hr=thr,
            is_lab_data=False,
            lab_cho_rate=0, lab_fat_rate=0,
            oxidation_efficiency=eff,
            custom_max_exo_rate=None,
            mix_type_max_rate=mix.max_rate_gh,
            mix_type_ox_factor=mix.ox_factor,
            intensity_series=tuple(int_series) if int_series else None, # Tuple è hashable
            intensity_factor_ref=if_ref,
            speed_kmh=10.0 # Default
        )
        
        # Visualizzazione Risultati
        with c_res:
            st.subheader("Risultati Simulazione")
            rem = stats['final_glycogen']
            delta = rem - tank['actual_available_g']
            st.metric("Glicogeno Residuo", f"{int(rem)} g", f"{int(delta)} g")
            
            # Grafico Pila
            chart_data = df_sim.melt('Time (min)', value_vars=['Glicogeno Muscolare (g)', 'Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)'])
            
            # Ordine visivo
            # Nota: Altair stack order di default è inverso rispetto alla lista in legend se non specificato
            c = alt.Chart(chart_data).mark_area().encode(
                x='Time (min)',
                y='value',
                color='variable',
                tooltip=['Time (min)', 'variable', 'value']
            ).properties(height=300)
            st.altair_chart(c, use_container_width=True)
            
            st.caption("Il grafico mostra le fonti di energia usate nel tempo.")

if __name__ == "__main__":
    main()
