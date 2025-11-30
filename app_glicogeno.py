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

# --- NUOVO ENUM: TIPO DI MIX CARBOIDRATI ---
class ChoMixType(Enum):
    GLUCOSE_ONLY = (1.0, 60.0, "Solo Glucosio/Maltodestrine (Standard)")
    MIX_2_1 = (1.5, 90.0, "Mix 2:1 (Maltodestrine:Fruttosio)")
    MIX_1_08 = (1.7, 105.0, "Mix 1:0.8 (High Frructose)")

    def __init__(self, ox_factor, max_rate_gh, label):
        self.ox_factor = ox_factor # Fattore moltiplicativo rispetto al glucosio
        self.max_rate_gh = max_rate_gh # Tasso massimo teorico g/h
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
    muscle_mass_kg: float = None # Nuovo campo per l'input reale

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

def calculate_depletion_factor(steps, activity_min, s_fatigue):
    # Passi: 10k passi = neutro (0.0). Ogni 5k in più/meno -> +/- 0.1 di fattore.
    # Attività: 60 min intensi = neutro (0.0). Ogni 60 min in più -> -0.1.
    
    # Fattore basato sui passi (peso 0.4)
    # 5k passi -> -0.1, 15k passi -> 0.1, 20k passi -> 0.2
    steps_base = 10000 
    steps_factor = (steps - steps_base) / 5000 * 0.1 * 0.4
    
    # Fattore basato sull'attività (peso 0.6)
    # 0 min -> -0.1, 120 min -> 0.0, 180 min -> -0.1
    activity_base = 120 # min/die
    if activity_min < 60: # Se l'attività è molto bassa, c'è un piccolo bonus di recupero
        activity_factor = (1 - (activity_min / 60)) * 0.05 * 0.6
    else:
        activity_factor = (activity_min - activity_base) / 60 * -0.1 * 0.6
        
    depletion_impact = steps_factor + activity_factor
    
    # Mappiamo l'impatto sul fattore di fatica qualitativo
    # Base 1.0 (RESTED) + impatto
    estimated_depletion_factor = max(0.6, min(1.0, 1.0 + depletion_impact))
    
    # Usiamo il fattore qualitativo s_fatigue se l'utente non ha inserito dati precisi
    if steps == 0 and activity_min == 0:
        return s_fatigue.factor
    else:
        return estimated_depletion_factor

def calculate_filling_factor_from_diet(weight_kg, cho_day_minus_1_g, cho_day_minus_2_g, s_fatigue, s_sleep, steps_m1, min_act_m1, steps_m2, min_act_m2):
    
    # Logica ispirata agli studi Bergström/Sherman: il riempimento è dettato
    # dall'introito degli ultimi 2 giorni.
    
    # Range di assunzione CHO (g/kg/die)
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    
    # Conversione da Grammi Totali a Grammi/Kg
    cho_day_minus_1_g = max(cho_day_minus_1_g, 1.0) # Protezione da divisione per zero
    cho_day_minus_2_g = max(cho_day_minus_2_g, 1.0) # Protezione da divisione per zero
    
    cho_day_minus_1_gk = cho_day_minus_1_g / weight_kg
    cho_day_minus_2_gk = cho_day_minus_2_g / weight_kg
    
    # --- NUOVA LOGICA: FATTORI DI DEPLEZIONE QUANTITATIVI ---
    
    # Calcola il fattore di deplezione (che viene applicato come sottrazione dal riempimento teorico)
    # Se l'utente non ha inserito passi/minuti, il risultato è 1.0 (RESTED) o il fattore qualitativo di default.
    depletion_m1_factor = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue)
    depletion_m2_factor = calculate_depletion_factor(steps_m2, min_act_m2, s_fatigue)
    
    # Per il fattore combinato, pesiamo l'effetto recupero/fatica
    recovery_factor = (depletion_m1_factor * 0.7) + (depletion_m2_factor * 0.3)
    
    # 1. Calcolo del fattore di riempimento muscolare basato sul CHO ingerito (g/kg)
    
    # Peso dell'introito: Day -1 ha un impatto maggiore di Day -2
    avg_cho_gk = (cho_day_minus_1_gk * 0.7) + (cho_day_minus_2_gk * 0.3)
    
    if avg_cho_gk >= CHO_MAX_GK:
        diet_factor_base = 1.25
    elif avg_cho_gk >= CHO_BASE_GK:
        diet_factor_base = 1.0 + (avg_cho_gk - CHO_BASE_GK) * (0.25 / (CHO_MAX_GK - CHO_BASE_GK))
    elif avg_cho_gk > CHO_MIN_GK:
        diet_factor_base = 0.5 + (avg_cho_gk - CHO_MIN_GK) * (0.5 / (CHO_BASE_GK - CHO_MIN_GK))
        diet_factor_base = max(0.5, diet_factor_base)
    else: # Sotto CHO_MIN_GK o 2.5 g/kg
        diet_factor_base = 0.5
    
    diet_factor_base = min(1.25, max(0.5, diet_factor_base)) # Clamp tra 0.5 e 1.25
    
    # Calcolo finale: Il fattore di riempimento viene moderato dal fattore di recupero/deplezione (recovery_factor)
    # L'impatto di s_sleep è gestito separatamente nel combined_filling finale.
    final_diet_depletion_factor = diet_factor_base * recovery_factor 

    # 2. Applicazione dei fattori di recupero
    combined_filling = final_diet_depletion_factor * s_sleep.factor
    
    # Restituiamo il fattore combinato e il fattore dieta base calcolato e il rateo g/kg effettivo
    return combined_filling, final_diet_depletion_factor, avg_cho_gk, cho_day_minus_1_gk, cho_day_minus_2_gk


def calculate_tank(subject: Subject):
    # Nuova logica: Se muscle_mass_kg è fornito, usiamo quello per la massa muscolare totale.
    if subject.muscle_mass_kg is not None and subject.muscle_mass_kg > 0:
        total_muscle = subject.muscle_mass_kg
        muscle_source_note = "Massa Muscolare Totale (SMM) fornita dall'utente."
    else:
        # Calcolo standard basato su LBM e frazione muscolare stimata
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

# Aggiornato per accettare il mix type
def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts, mix_type: ChoMixType):
    # Base rate per GLUCOSIO
    base_rate_glucose = 1.0 # g/min (ca 60 g/h) standard per glucosio
    
    # Aggiustamenti individuali fini (come da Podlogar et al.)
    if height_cm > 175:
        base_rate_glucose += 0.1
    if ftp_watts > 250:
        base_rate_glucose += 0.1
        
    # Limite fisiologico per il solo glucosio (SGLT1 saturo)
    limit_glucose = 1.1 
    estimated_glucose_rate = min(base_rate_glucose, limit_glucose)
    
    # Se usiamo un mix, il limite si alza grazie a GLUT5 (fruttosio)
    if mix_type == ChoMixType.MIX_2_1:
        # Mix 2:1 permette fino a ~90g/h (1.5 g/min)
        return min(estimated_glucose_rate * 1.5, 1.5)
    elif mix_type == ChoMixType.MIX_1_08:
        # Mix 1:0.8 permette fino a ~105g/h (1.75 g/min)
        return min(estimated_glucose_rate * 1.75, 1.75)
    else:
        return estimated_glucose_rate

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

def simulate_metabolism(
    subject_data, 
    duration_min, 
    constant_carb_intake_g_h, 
    cho_per_unit_g, 
    crossover_pct, 
    tau_absorption, 
    subject_obj, 
    activity_params,
    oxidation_efficiency_input=0.80, 
    custom_max_exo_rate=None,
    mix_type_input=ChoMixType.GLUCOSE_ONLY # Nuovo parametro
):
    tank_g = subject_data['actual_available_g']
    results = []
    
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
    
    # --- STIMA O USO DEL TASSO MASSIMO DI OSSIDAZIONE ESOGENA ---
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate 
    else:
        # Passiamo il mix_type alla funzione di stima
        max_exo_rate_g_min = estimate_max_exogenous_oxidation(
            subject_obj.height_cm, 
            subject_obj.weight_kg, 
            ftp_watts,
            mix_type_input
        )
    
    oxidation_efficiency = oxidation_efficiency_input
    
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

        instantaneous_input_g_min = 0.0 
        
        if not is_input_zero and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instantaneous_input_g_min = cho_per_unit_g 
        
        target_exo_oxidation_limit_g_min = max_exo_rate_g_min * oxidation_efficiency
        
        if t > 0:
            if is_input_zero:
                current_exo_oxidation_g_min *= (1 - alpha) 
            else:
                current_exo_oxidation_g_min += alpha * (target_exo_oxidation_limit_g_min - current_exo_oxidation_g_min)
            
            if current_exo_oxidation_g_min < 0:
                current_exo_oxidation_g_min = 0.0
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
            fat_burned_per_min = lab_fat_rate 
            cho_ratio = total_cho_demand / (total_cho_demand + fat_burned_per_min) if (total_cho_demand + fat_burned_per_min) > 0 else 0
            rer = 0.7 + (0.3 * cho_ratio) 
        
        else:
            rer = calculate_rer_polynomial(effective_if_for_rer)
            base_cho_ratio = (rer - 0.70) * 3.45
            base_cho_ratio = max(0.0, min(1.0, base_cho_ratio))
            
            current_cho_ratio = base_cho_ratio
            if intensity_factor < 0.85 and t > 60:
                hours_past = (t - 60) / 60.0
                metabolic_shift = 0.05 * (hours_past ** 1.2) 
                current_cho_ratio = max(0.05, base_cho_ratio - metabolic_shift)
            
            cho_ratio = current_cho_ratio
            fat_ratio = 1.0 - cho_ratio
            
            kcal_cho_demand = current_kcal_demand * cho_ratio
        
        total_cho_g_min = kcal_cho_demand / 4.1
        kcal_from_exo = current_exo_oxidation_g_min * 3.75 
        
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
        
        # --- CALCOLO % TOTALE ENERGIA FORNITA (per tooltip) ---
        # Calcoliamo i grammi totali usati in questo minuto da tutte le fonti
        g_muscle = muscle_usage_g_min
        g_liver = from_liver
        g_exo = from_exogenous
        # Assicurati che fat_ratio_used sia definito anche se !is_lab_data e t>0 non è vero
        fat_ratio_used_local = 1.0 - cho_ratio if not is_lab_data else (lab_fat_rate * 9.0) / current_kcal_demand if current_kcal_demand > 0 else 0.0
        g_fat = (current_kcal_demand * fat_ratio_used_local / 9.0)
        
        total_g_min = g_muscle + g_liver + g_exo + g_fat
        if total_g_min == 0: total_g_min = 1.0 # Evita divisione per zero
        
        # Aggiungiamo le percentuali al dizionario results
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": muscle_usage_g_min * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": exo_oxidation_g_h, 
            "Ossidazione Lipidica (g)": lab_fat_rate * 60 if is_lab_data else ((current_kcal_demand * (1.0 - cho_ratio)) / 9.0) * 60,
            
            # Campi Percentuali per Tooltip
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
            "Ossidazione Cumulativa (g)": total_exo_oxidation_cumulative
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

# --- NOTE TECNICHE REINTRODOTTE ---
with st.expander("📘 Note Tecniche & Fonti Scientifiche"):
    st.info("""
    **1. Stima Riserve & Capacità di Stoccaggio**
    * **Stima della Concentrazione (g/kg):** Si basa sulla correlazione tra il fitness aerobico (VO2max) e la densità di stoccaggio muscolare, riflettendo la capacità di adattamento cellulare (Burke et al., 2017).
    * **Capacità Massima (Fattore 1.25):** La supercompensazione del glicogeno si ottiene con carichi di CHO $>8 \text{ g/kg/die}$ in $36-48$ ore, portando le riserve totali oltre i livelli basali (Bergström et al., 1967; Burke et al., 2017).
    * **Creatina:** La supplementazione di creatina (tipicamente con protocolli di carico acuto di $20 \text{ g/die}$ per $5-6$ giorni o mantenimento di $3-5 \text{ g/die}$) è associata a un aumento aggiuntivo ($\sim 10\%$) nella capacità totale di stoccaggio del glicogeno, a condizione che la saturazione muscolare sia stata raggiunta (Roberts et al., 2016; Burke et al., 2017).
    
    ---
    
    **2. Sviluppi Recenti & Personalizzazione**
    
    * **A) Efficienza Metabolica Individuale:** Studi recenti (Podlogar et al., 2025) evidenziano un'alta variabilità nell'ossidazione dei CHO esogeni ($0.5-1.5 \text{ g/min}$). L'app permette ora di personalizzare questo parametro.
    * **B) Rischio Gastrointestinale:** L'accumulo di CHO non ossidati è il predittore principale di distress GI. Il modello stima questo rischio calcolando il delta tra assunzione e ossidazione (Podlogar et al., 2025).
    * **C) Mix di Carboidrati:** L'uso di miscele Glucosio:Fruttosio (es. 2:1 o 1:0.8) sfrutta trasportatori multipli (SGLT1 e GLUT5), aumentando il limite di ossidazione fino a $1.5-1.7 \text{ g/min}$ (Jeukendrup, 2004).
    """)
# --- FINE NOTE TECNICHE REINTRODOTTE ---

tab1, tab2 = st.tabs(["Analisi Riserve (Tank)", "Simulazione Metabolica (Burn)"])

# --- TAB 1: CALCOLO SERBATOIO ---
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        # =========================================================================
        # SEZIONE 1: DATI ANTROPOMETRICI E BASE
        # =========================================================================
        st.subheader("1. Dati Antropometrici")
        weight = st.slider("Peso Corporeo (kg)", 45.0, 100.0, 70.0, 0.5)
        height = st.slider("Altezza (cm)", 150, 210, 175, 1)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 15.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        # --- NUOVO INPUT PER MASSA MUSCOLARE REALE ---
        use_smm = st.checkbox("Usa Massa Muscolare (SMM) da esame strumentale (Impedenziometria/DEXA)",
                              help="Seleziona questa opzione per sostituire la stima interna (basata su Peso/BF/Sesso) con un valore misurato direttamente.")
        muscle_mass_input = None
        if use_smm:
            muscle_mass_input = st.number_input(
                "Massa Muscolare Totale (SMM) [kg]",
                min_value=10.0, max_value=60.0, value=weight * 0.45, step=0.1,
                help="Inserire la massa muscolare scheletrica totale misurata (es. da DEXA o BIA)."
            )
        # --- FINE NUOVO INPUT ---
        
        st.markdown("---")
        
        # =========================================================================
        # SEZIONE 2: CAPACITÀ MASSIMA DI STOCCAGGIO (Tank Max)
        # =========================================================================
        st.subheader("2. Capacità di Stoccaggio Massima (Tank)")
        
        # 2a. Metodo di calcolo della concentrazione
        st.write("**Stima Concentrazione Glicogeno Muscolare**")
        estimation_method = st.radio("Metodo di calcolo:", ["Basato su Livello", "Basato su VO2max"], label_visibility="collapsed")
        
        # Inizializzazione variabili per sicurezza scope
        vo2_input = 55.0 
        calculated_conc = 15.0 
        
        if estimation_method == "Basato su Livello":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello Atletico", list(status_map.keys()), index=2, key='lvl_status')]
            calculated_conc = s_status.val
            # Calcoliamo il vo2_input come proxy per la visualizzazione (non usato per il calcolo ma utile per la UI)
            vo2_input = 30 + ((calculated_conc - 13.0) / 0.24)
        else:
            # Se basato su VO2max, prendiamo il valore dallo slider
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 55, step=1)
            calculated_conc = get_concentration_from_vo2max(vo2_input)
            
        # Mostra il risultato della stima
        lvl_desc = ""
        if calculated_conc < 15: lvl_desc = "Sedentario"
        elif calculated_conc < 18: lvl_desc = "Amatore"
        elif calculated_conc < 22: lvl_desc = "Allenato"
        elif calculated_conc < 24: lvl_desc = "Avanzato"
        else: lvl_desc = "Elite"
        st.caption(f"Concentrazione stimata: **{calculated_conc:.1f} g/kg** ({lvl_desc})")

        # 2b. Disciplina Sportiva
        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina Sportiva", list(sport_map.keys()))]
        
        # =========================================================================
        # SEZIONE 3: FATTORI AVANZATI DI CAPACITÀ
        # =========================================================================
        with st.expander("Fattori Avanzati di Capacità (Aumento potenziale Max)"):
            use_creatine = st.checkbox("Supplementazione Creatina", help="Aumento volume cellulare e capacità di stoccaggio stimata (+10%).")
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                menstrual_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = menstrual_map[st.selectbox("Fase Ciclo Mestruale", list(menstrual_map.keys()), index=0)]
        
        st.markdown("---")
        
        # Inizializza i dizionari per la selezione
        fatigue_map = {f.label: f for f in FatigueState}
        sleep_map = {s.label: s for s in SleepQuality}
        
        # Variabili necessarie per il calcolo finale (inizializzate)
        combined_filling = 1.0 
        diet_factor = 1.0
        avg_cho_gk = 5.0
        steps_m1, min_act_m1, steps_m2, min_act_m2 = 0, 0, 0, 0 

        # Variabili CHO Inizializzate per prevenire NameError
        cho_g1 = weight * DietType.NORMAL.ref_value
        cho_g2 = weight * DietType.NORMAL.ref_value
        
        # =========================================================================
        # SEZIONE 4: STATO NUTRIZIONALE (Fattore Dieta)
        # =========================================================================
        st.subheader("3. Stato Nutrizionale (Introito CHO 48h)")
        
        diet_method = st.radio(
            "Metodo di Calcolo Ripristino Glicogeno:", 
            ["1. Seleziona Tipo di Dieta (Veloce)", "2. Inserisci CHO Totale (g) dei 2 giorni precedenti"], 
            key='diet_calc_method'
        )
        
        # --- METODO 1: TIPO DI DIETA ---
        if diet_method == "1. Seleziona Tipo di Dieta (Veloce)":
            diet_options_map = {}
            for d in DietType:
                daily_cho = int(weight * d.ref_value)
                sign = ">" if d == DietType.HIGH_CARB else ("<" if d == DietType.LOW_CARB else "~")
                label = f"{d.label} ({sign}{d.ref_value} g/kg/die) [~{daily_cho}g tot]"
                diet_options_map[label] = d
            
            selected_diet_label = st.selectbox("Introito Glucidico (48h prec.)", list(diet_options_map.keys()), index=1, key='diet_type_select')
            
            # Recupera l'enum corretto dal label completo
            s_diet = DietType.NORMAL
            for d in DietType:
                if selected_diet_label.startswith(d.label):
                    s_diet = d
                    break
            
            # Ora calcoliamo i CHO fittizi e li assegnamo a cho_g1/g2
            cho_g1 = weight * s_diet.ref_value
            cho_g2 = weight * s_diet.ref_value 
            
            # I fattori di recupero sono gestiti più avanti (Punto 5)
            temp_fatigue = FatigueState.RESTED
            temp_sleep = SleepQuality.GOOD
            
            # Calcoliamo il diet_factor in base ai CHO fittizi (per la visualizzazione)
            _, diet_factor, avg_cho_gk, _, _ = calculate_filling_factor_from_diet(
                weight_kg=weight,
                cho_day_minus_1_g=cho_g1,
                cho_day_minus_2_g=cho_g2,
                s_fatigue=temp_fatigue, # Neutro
                s_sleep=temp_sleep,     # Neutro
                steps_m1=0, min_act_m1=0, steps_m2=0, min_act_m2=0 # Neutro
            )
            
            st.caption(f"Fattore di Riempimento base da Dieta: **{s_diet.factor:.2f}**")
            s_fatigue = FatigueState.RESTED 
            s_sleep = SleepQuality.GOOD     
        
        # --- METODO 2: INPUT DI CHO (g totali) ---
        else:
            st.markdown("#### Input Glicogeno Totale (g/die)")
            col_d2, col_d1 = st.columns(2)
            
            cho_day_minus_2_g = col_d2.number_input(
                "Grammi CHO Giorno -2 (g)", 
                min_value=50, max_value=800, value=int(weight * 5.0), step=10,
                help="Apporto totale di CHO del penultimo giorno."
            )
            
            cho_day_minus_1_g = col_d1.number_input(
                "Grammi CHO Giorno -1 (g)", 
                min_value=50, max_value=800, value=int(weight * 5.0), step=10,
                help="Apporto totale di CHO del giorno precedente."
            )
            
            # Assegna i valori reali agli output
            cho_g1 = cho_day_minus_1_g
            cho_g2 = cho_day_minus_2_g

            cho_day_minus_2_gk = cho_day_minus_2_g / weight
            cho_day_minus_1_gk = cho_day_minus_1_g / weight

            col_d2.caption(f"$\sim$ **{cho_day_minus_2_gk:.1f} g/kg/die**")
            col_d1.caption(f"$\sim$ **{cho_day_minus_1_gk:.1f} g/kg/die**")
            
            temp_fatigue = FatigueState.RESTED
            temp_sleep = SleepQuality.GOOD
            
            _, diet_factor, avg_cho_gk, _, _ = calculate_filling_factor_from_diet(
                weight_kg=weight,
                cho_day_minus_1_g=cho_day_minus_1_g,
                cho_day_minus_2_g=cho_day_minus_2_g,
                s_fatigue=temp_fatigue, # Neutro
                s_sleep=temp_sleep,     # Neutro
                steps_m1=0, min_act_m1=0, steps_m2=0, min_act_m2=0 # Neutro
            )
            s_fatigue = FatigueState.RESTED 
            s_sleep = SleepQuality.GOOD     
            
            st.caption(f"Fattore di Riempimento Base (calcolato): **{diet_factor:.2f}** (Media pesata $\sim{avg_cho_gk:.1f} \text{{ g/kg/die}}$)")

        st.markdown("---")
        
        # =========================================================================
        # SEZIONE 5: FATTORI DI RECUPERO (FATICA E SONNO)
        # =========================================================================
        st.subheader("4. Condizione di Recupero (Fattori di Sottrazione)")
        
        # Selezione qualitativa per default
        s_fatigue = fatigue_map[st.selectbox("Carico di Lavoro (24h prec.)", list(fatigue_map.keys()), index=0, key='fatigue_final')]
        s_sleep = sleep_map[st.selectbox("Qualità del Sonno (24h prec.)", list(sleep_map.keys()), index=0, key='sleep_final')]
        
        
        # --- INPUT ATTIVITÀ MOTORIA SPECIFICA (Opzionale) ---
        with st.expander("Attività Motorio/Sportiva Effettuata (Giorno -1 e -2)"):
            st.markdown("#### Fornisci dati oggettivi per calibrare il Fattore Fatica:")
            
            col_m2_steps, col_m2_act = st.columns(2)
            steps_m2 = col_m2_steps.number_input("Passi Giorno -2", min_value=0, value=10000, step=500)
            min_act_m2 = col_m2_act.number_input("Minuti Attività Sportiva Giorno -2", min_value=0, value=60, step=10)

            col_m1_steps, col_m1_act = st.columns(2)
            steps_m1 = col_m1_steps.number_input("Passi Giorno -1", min_value=0, value=5000, step=500)
            min_act_m1 = col_m1_act.number_input("Minuti Attività Sportiva Giorno -1", min_value=0, value=30, step=10)
            
            st.caption("Nota: Se l'attività è inserita, il fattore di deplezione (Carico di Lavoro) sarà calcolato oggettivamente. Altrimenti, viene usato il valore qualitativo selezionato sopra.")

        # --- RICONTROLLO FATTORE DI RIEMPIMENTO CON EVENTUALE ATTIVITÀ ---
        
        # Calcolo finale del combined_filling, che ora include la deplezione oggettiva
        # Visto che cho_g1/g2 sono definiti in entrambi i rami, possiamo chiamare la funzione qui:
        combined_filling, diet_factor, avg_cho_gk, _, _ = calculate_filling_factor_from_diet(
            weight_kg=weight,
            cho_day_minus_1_g=cho_g1,
            cho_day_minus_2_g=cho_g2,
            s_fatigue=s_fatigue, 
            s_sleep=s_sleep,
            steps_m1=steps_m1, min_act_m1=min_act_m1, steps_m2=steps_m2, min_act_m2=min_act_m2
        )
        
        st.markdown("---")
        
        # =========================================================================
        # SEZIONE 6: PARAMETRI EPATICI/BIOMARKER (Acuti)
        # =========================================================================
        st.subheader("5. Stato Metabolico Acuto (Fegato/Glicemia)")
        
        has_glucose = st.checkbox("Dispongo di misurazione Glicemia", help="Utile per valutare lo stato acuto del fegato.")
        
        glucose_val = None
        is_fasted = False
        
        with st.expander("Dettagli Fegato/Glicemia"):
            if has_glucose:
                glucose_val = st.number_input("Glicemia Capillare a Digiuno (mg/dL)", 40, 200, 90, 1)

            if not has_glucose:
                is_fasted = st.checkbox("Allenamento a Digiuno (Morning Fasted)", help="Riduzione fisiologica delle riserve epatiche post-riposo notturno.")
        
        # Logica Fegato
        liver_val = 100.0
        if is_fasted:
            liver_val = 40.0 
        
        # Creazione Struttura Subject e Calcolo finale del Tank
        vo2_abs = (vo2_input * weight) / 1000
        
        subject = Subject(
            weight_kg=weight, 
            height_cm=height,
            body_fat_pct=bf, sex=s_sex, 
            glycogen_conc_g_kg=calculated_conc, sport=s_sport, 
            liver_glycogen_g=liver_val,
            filling_factor=combined_filling, # Usa il fattore che include la deplezione oggettiva/qualitativa
            uses_creatine=use_creatine,
            menstrual_phase=s_menstrual,
            glucose_mg_dl=glucose_val,
            vo2max_absolute_l_min=vo2_abs,
            muscle_mass_kg=muscle_mass_input # Passa il nuovo input qui
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
        
        # Logica di visualizzazione dei fattori
        if diet_method == "1. Seleziona Tipo di Dieta (Veloce)": 
            temp_diet_map = {d.label: d for d in DietType}
            s_diet_label = st.session_state.get('diet_type_select', list(temp_diet_map.keys())[1])
            
            # Recupera l'enum corretto (qui si usano i cho fittizi)
            s_diet = DietType.NORMAL
            for d in DietType:
                if selected_diet_label.startswith(d.label):
                    s_diet = d
                    break

            if s_diet == DietType.HIGH_CARB: factors_text.append("Supercompensazione Attiva (+25%)")
            
        elif diet_method == "2. Inserisci CHO Totale (g) dei 2 giorni precedenti": factors_text.append(f"Fattore dieta calcolato: {diet_factor:.2f} (Media $\sim{avg_cho_gk:.1f} \text{{ g/kg/die}}$)")

        if combined_filling < 1.0: factors_text.append(f"Riduzione da fattori nutrizionali/recupero (Disponibilità: {int(combined_filling*100)}%)")
        if use_creatine: factors_text.append("Bonus volume plasmatico/creatina (+10% Cap)")
        if s_menstrual == MenstrualPhase.LUTEAL: factors_text.append("Fase Luteale (-5% filling)")
        if tank_data.get('liver_note'): factors_text.append(f"**{tank_data['liver_note']}**")
        
        factors_text.append(f"Fonte Massa Muscolare: {tank_data['muscle_source_note']}")

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
            
            # NUOVO SELETTORE MIX CHO
            mix_type_options = list(ChoMixType)
            selected_mix_type = st.selectbox(
                "Tipologia Mix Carboidrati", 
                options=mix_type_options, 
                format_func=lambda x: x.label,
                index=0,
                help="Il tipo di carboidrati influenza il tasso massimo di ossidazione esogena."
            )

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
            
            st.markdown("---")
            st.subheader("Parametri Cinetici Avanzati")

            # CHECKBOX PER PARAMETRI AVANZATI
            use_custom_kinetic = st.checkbox(
                "Usa parametri cinetici/fisiologici personalizzati (Utenti Esperti)",
                help="Attiva questa opzione per calibrare τ (assorbimento), Rischio GI, Efficienza Ossidativa e Picco Ossidazione.",
                value=False
            )
            
            TAU_DEFAULT = 20.0
            RISK_THRESHOLD_DEFAULT = 30
            EFFICIENCY_DEFAULT = 0.80
            
            tau_absorption_input = TAU_DEFAULT
            risk_threshold_input = RISK_THRESHOLD_DEFAULT
            oxidation_efficiency_input = EFFICIENCY_DEFAULT
            custom_max_exo_rate = None 

            if use_custom_kinetic:
                col_tau, col_risk = st.columns(2)
                with col_tau:
                    tau_absorption_input = st.slider(
                        "Tau (τ) Cinetica Assorbimento (min)", 
                        5.0, 60.0, TAU_DEFAULT, 2.5, 
                        help="Tempo di 'smussamento'. Minore è il valore, più veloce è l'assorbimento."
                    )
                with col_risk:
                    risk_threshold_input = st.slider(
                        "Soglia di Rischio GI (g)", 
                        10, 80, RISK_THRESHOLD_DEFAULT, 5, 
                        help="Massimo accumulo tollerabile prima che insorgano sintomi GI."
                    )
                
                st.markdown("#### Fisiologia Ossidativa")
                oxidation_efficiency_input = st.slider(
                    "Efficienza di Ossidazione (%)",
                    0.50, 1.00, EFFICIENCY_DEFAULT, 0.01,
                    format="%.2f",
                    help="Percentuale di CHO ingeriti che viene effettivamente ossidata (Podlogar et al., 2025: 58-83%)."
                )
                
                use_manual_peak = st.checkbox("Inserisci manualmente il Picco Ossidazione Esogena (g/min)")
                if use_manual_peak:
                    custom_max_exo_rate = st.slider(
                        "Picco Ossidazione Esogena (g/min)",
                        0.5, 2.0, 1.0, 0.1,
                        help="Massimo tasso di ossidazione di glucosio esogeno (Standard: ~1.0 g/min)."
                    )

            else:
                 st.caption(f"Utilizzo parametri standard: τ={TAU_DEFAULT:.0f}m, Rischio={RISK_THRESHOLD_DEFAULT}g, Eff={EFFICIENCY_DEFAULT*100:.0f}%")


        h_cm = subj.height_cm 
        
        df_sim, stats = simulate_metabolism(
            tank_data, duration, carb_intake, cho_per_unit, crossover, 
            tau_absorption_input, subj, act_params,
            oxidation_efficiency_input=oxidation_efficiency_input,
            custom_max_exo_rate=custom_max_exo_rate,
            mix_type_input=selected_mix_type 
        )
        df_sim["Scenario"] = "Con Integrazione (Strategia)"
        
        df_no_cho, stats_no_cho = simulate_metabolism(
            tank_data, duration, 0, cho_per_unit, crossover, 
            tau_absorption_input, subj, act_params,
            oxidation_efficiency_input=oxidation_efficiency_input,
            custom_max_exo_rate=custom_max_exo_rate,
            mix_type_input=selected_mix_type
        )
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

        
        st.markdown("### 📊 Bilancio Energetico: Richiesta vs. Fonti di Ossidazione")
        
        # Didascalia Esplicativa Aggiunta
        st.caption("""
        **Guida alla Lettura:** L'altezza totale del grafico (linea tratteggiata nera) rappresenta il consumo energetico orario (g/h) richiesto dallo sforzo. Le aree colorate mostrano come il corpo miscela i diversi substrati per soddisfare esattamente quella richiesta.
        """)

        color_map = {
            'Glicogeno Epatico (g)': '#B71C1C',    # Rosso Scuro (1) - BASE
            'Carboidrati Esogeni (g)': '#1976D2', # Blu (2)
            'Ossidazione Lipidica (g)': '#FFC107', # Giallo Intenso (3)
            'Glicogeno Muscolare (g)': '#E57373', # Rosso Tenue (4) - CIMA
        }
        
        stack_order = [
            'Glicogeno Epatico (g)',     # 1. BASE (indice 0)
            'Carboidrati Esogeni (g)',   # 2. Sopra 1 (indice 1)
            'Ossidazione Lipidica (g)',  # 3. Sopra 2 (indice 2)
            'Glicogeno Muscolare (g)'      # 4. CIMA (indice 3)
        ]
        
        df_long = df_sim.melt('Time (min)', value_vars=stack_order, 
                              var_name='Source', value_name='Rate (g/h)')
        
        df_long_rich = pd.merge(df_long, df_sim[['Time (min)', 'Pct_Muscle', 'Pct_Liver', 'Pct_Exo', 'Pct_Fat', 'Scenario']], on='Time (min)')
        
        conditions = [
            (df_long_rich['Source'] == 'Glicogeno Muscolare (g)'),
            (df_long_rich['Source'] == 'Glicogeno Epatico (g)'),
            (df_long_rich['Source'] == 'Carboidrati Esogeni (g)'),
            (df_long_rich['Source'] == 'Ossidazione Lipidica (g)')
        ]
        choices = [df_long_rich['Pct_Muscle'], df_long_rich['Pct_Liver'], df_long_rich['Pct_Exo'], df_long_rich['Pct_Fat']]
        df_long_rich['Percentuale'] = np.select(conditions, choices, default='0%')

        
        sort_map = {
            'Glicogeno Epatico (g)': 0,
            'Carboidrati Esogeni (g)': 1,
            'Ossidazione Lipidica (g)': 2,
            'Glicogeno Muscolare (g)': 3
        }
        df_long_rich['sort_index'] = df_long_rich['Source'].map(sort_map)
        
        color_domain = stack_order
        color_range = [color_map[source] for source in stack_order]
        
        df_total_demand = df_sim.copy()
        df_total_demand['Total Demand'] = df_total_demand['Glicogeno Muscolare (g)'] + df_total_demand['Glicogeno Epatico (g)'] + df_total_demand['Carboidrati Esogeni (g)'] + df_total_demand['Ossidazione Lipidica (g)']

        chart_stack = alt.Chart(df_long_rich).mark_area().encode(
            x=alt.X('Time (min)'),
            y=alt.Y('Rate (g/h)', stack="zero"), # Usiamo stack="zero" per maggiore chiarezza
            color=alt.Color('Source', 
                            scale=alt.Scale(domain=color_domain,  
                                            range=color_range),
                            sort=alt.SortField(field='sort_index', order='ascending') 
                           ),
            tooltip=[
                alt.Tooltip('Time (min)', title='Minuto'), 
                alt.Tooltip('Source', title='Fonte'), 
                alt.Tooltip('Rate (g/h)', title='Contributo (g/h)', format='.1f'),
                alt.Tooltip('Percentuale', title='% del Totale')
            ]
        )
        
        line_demand = alt.Chart(df_total_demand).mark_line(color='black', strokeDash=[5,5], size=2).encode(
            x='Time (min)',
            y='Total Demand'
        )

        final_combo_chart = (chart_stack + line_demand).properties(
            title="Bilancio Energetico: Richiesta vs. Fonti di Ossidazione" 
        ).interactive()
        
        st.altair_chart(final_combo_chart, use_container_width=True)
        
        st.markdown("---")
        st.markdown("### 📉 Confronto Riserve Nette (Svuotamento Serbatio)")
        
        st.caption("Confronto: Deplezione Glicogeno Totale (Muscolo + Fegato) con Zone di Rischio")
        
        # --- LOGICA PER GRAFICO CON BANDE DI RISCHIO BASATO SU TOTALE GLICOGENO ---
        
        initial_total_glycogen = tank_data['muscle_glycogen_g'] + tank_data['liver_glycogen_g']
        max_total = initial_total_glycogen * 1.05 # Max per l'asse Y
        
        # Definisce i campi da mostrare nel grafico a pila delle riserve
        reserve_fields = ['Residuo Muscolare', 'Residuo Epatico']

        # Melt dei dati per la visualizzazione stacked
        df_reserve_long = combined_df.melt(
            id_vars=['Time (min)', 'Scenario', 'Stato'], 
            value_vars=reserve_fields, 
            var_name='Tipo Glicogeno', 
            value_name='Residuo (g)'
        )
        
        # Mappatura colori specifica per le riserve (chiaro per Muscolo, scuro per Fegato critico)
        reserve_color_map = {
            'Residuo Muscolare': '#E57373', # Rosso tenue
            'Residuo Epatico': '#B71C1C',   # Rosso scuro/critico
        }
        
        # 1. Definizione delle zone di rischio (Basato su Riserva Totale)
        zones_df = pd.DataFrame({
            'Zone': ['Sicurezza (Verde)', 'Warning (Giallo)', 'Critico (Rosso)'],
            'Start': [initial_total_glycogen * 0.65, initial_total_glycogen * 0.30, 0],
            'End': [initial_total_glycogen * 1.05, initial_total_glycogen * 0.65, initial_total_glycogen * 0.30],
            'Color': ['#4CAF50', '#FFC107', '#F44336'], 
        })
        
        # Creiamo un DataFrame per lo sfondo con la colonna 'Scenario' duplicata
        scenarios_df = pd.DataFrame({'Scenario': combined_df['Scenario'].unique()})
        zones_with_scenario_df = pd.merge(zones_df.assign(key=1), scenarios_df.assign(key=1), on='key').drop('key', axis=1)

        # Background sfaccettato
        background_facet = alt.Chart(zones_with_scenario_df).mark_rect(opacity=0.15).encode(
            x=alt.X('Time (min)', title='Durata (min)'), # Aggiunto x encoding per faceting
            y=alt.Y('Start', title='Glicogeno Residuo (g)', axis=None), 
            y2=alt.Y2('End'),         
            color=alt.Color('Color', scale=None), 
            tooltip=['Zone']
        ).properties(
             height=350 # Altezza fissa per i rettangoli
        )

        # Grafico ad area accatastata (Stacked Area Chart) per ogni Scenario
        area_chart = alt.Chart(df_reserve_long).mark_area().encode(
            x=alt.X('Time (min)', title='Durata (min)'),
            y=alt.Y('Residuo (g)', title='Glicogeno Residuo (g)', stack="zero", scale=alt.Scale(domain=[0, max_total])),
            color=alt.Color('Tipo Glicogeno', scale=alt.Scale(domain=reserve_fields, range=[reserve_color_map[f] for f in reserve_fields])),
            order=alt.Order('Tipo Glicogeno', sort='ascending'), # Epatico in basso, Muscolare sopra
            tooltip=['Time (min)', 'Scenario', 'Tipo Glicogeno', 'Residuo (g)', 'Stato']
        ).interactive()
        
        # Layering (Sfondo + Aree Accatastate)
        # Qui uniamo background_facet e area_chart e poi sfaccettiamo.
        
        final_reserve_chart = alt.layer(background_facet, area_chart).facet(
            column=alt.Column('Scenario', header=alt.Header(titleOrient="bottom", labelOrient="bottom"))
        ).resolve_scale(
            y='shared' # Risoluzione della scala Y condivisa
        ).properties(
            title="Confronto: Deplezione del Serbatoio (Muscolo vs Fegato) per Strategia"
        ).configure_facet(
            spacing=20
        ).configure_title(
            anchor='start'
        ).interactive()

        st.altair_chart(final_reserve_chart, use_container_width=True)
        # --- FINE LOGICA GRAFICO RISERVE NETTE ---
        
        st.markdown("---")
        
        st.markdown("### ⚠️ Accumulo Intestinale (Rischio GI) & Flusso CHO")
        
        st.caption(f"""
        **Interpretazione:** La distanza verticale tra la Linea Blu (Ingerito) e la Linea Verde (Ossidato) crea l'**Accumulo CHO (g)**, ovvero il carico intestinale istantaneo. Se l'area supera la Soglia di Rischio GI ({risk_threshold_input} g), la strategia di assunzione è troppo aggressiva.
        """)

        with st.expander("Dettagli Modello Flusso CHO e Rischio GI"):
            st.markdown(f"""
            Questo grafico visualizza il **bilancio dinamico** tra ciò che ingerisci e ciò che il tuo corpo riesce ad ossidare (bruciare), indicando il rischio di *Distress Gastrointestinale (GI)*.
            
            **Linee Cumulative (Asse Destro):**
            * **Linea Blu (Intake):** Apporto totale di CHO (a gradini, riflette le assunzioni discrete).
            * **Linea Verde (Ossidazione):** CHO totale bruciato (curva smussata, limitata dalla cinetica di assorbimento).
            
            **Area di Rischio (Asse Sinistro):**
            * L'area sottesa è l'**Accumulo Intestinale (Gut Load)**: $\\text{{Intake}} - \\text{{Ossidazione}}$.
            * **τ Cinetica (Tempo di Smussamento):** {tau_absorption_input:.1f} min. Determina quanto velocemente la curva di Ossidazione (Verde) risponde all'Ingestione (Blu).
            * **Soglia di Rischio GI:** {risk_threshold_input} g (Linea Rossa Tratteggiata). Superarla indica un alto rischio di sintomi GI.
            """)
        
        RISK_THRESHOLD = risk_threshold_input
        
        df_sim['Rischio'] = np.where(df_sim['Gut Load'] >= RISK_THRESHOLD, 'Alto Rischio', 'Basso Rischio')
        
        max_gut_load = df_sim['Gut Load'].max()
        max_gut_load_time = df_sim[df_sim['Gut Load'] == max_gut_load]['Time (min)'].iloc[0] if max_gut_load > 0 else 0
        max_df = pd.DataFrame([{'Time (min)': max_gut_load_time, 'Gut Load': max_gut_load}])

        gut_area = alt.Chart(df_sim).mark_area(opacity=0.8, color='#8D6E63').encode(
            x=alt.X('Time (min)'), 
            y=alt.Y('Gut Load', title='Accumulo CHO (g)', axis=alt.Axis(titleColor='#8D6E63')),
            tooltip=['Time (min)', 'Gut Load', 'Rischio']
        )
        
        risk_line = alt.Chart(pd.DataFrame({'y': [RISK_THRESHOLD]})).mark_rule(color='#F44336', strokeDash=[4,4], size=2).encode(
            y=alt.Y('y', axis=None)
        )
        
        max_point = alt.Chart(max_df).mark_circle(size=80, color='black').encode(
            x=alt.X('Time (min)'), 
            y=alt.Y('Gut Load'),
            tooltip=[alt.Tooltip('Time (min)', title='Max Time'), alt.Tooltip('Gut Load', title='Max Accumulo')]
        )
        
        gut_layer_base = alt.layer(gut_area, risk_line, max_point)

        df_cumulative = df_sim.melt('Time (min)', value_vars=['Intake Cumulativo (g)', 'Ossidazione Cumulativa (g)'],
                                   var_name='Flusso', value_name='Grammi')

        intake_oxidation_lines = alt.Chart(df_cumulative).mark_line(strokeWidth=3.5).encode(
            x=alt.X('Time (min)'), 
            y=alt.Y('Grammi', title='G Ingeriti/Ossidati (g)', axis=alt.Axis(titleColor='#1976D2')),
            color=alt.Color('Flusso', 
                            scale=alt.Scale(domain=['Intake Cumulativo (g)', 'Ossidazione Cumulativa (g)'],
                                            range=['#1976D2', '#4CAF50'])
                           ),
            strokeDash=alt.condition(alt.datum.Flusso == 'Ossidazione Cumulativa (g)', alt.value([5, 5]), alt.value([0])),
            tooltip=['Time (min)', 'Flusso', 'Grammi']
        )

        cumulative_layer = intake_oxidation_lines.encode(
            y=alt.Y('Grammi', 
                    axis=alt.Axis(title='G Ingeriti/Ossidati (g)', titleColor='#1976D2', orient='right'), 
                    scale=alt.Scale(domain=[0, df_sim['Intake Cumulativo (g)'].max() * 1.1])
                    )
        )
        
        final_gut_chart = alt.layer(
            gut_layer_base,
            cumulative_layer
        ).resolve_scale(
            y='independent'
        ).properties(
            title="Accumulo Intestinale vs Flusso CHO (Doppio Asse Y)"
        )


        st.altair_chart(final_gut_chart, use_container_width=True)
        
        st.caption("Ossidazione Lipidica (Tasso Orario)")
        st.line_chart(df_sim.set_index("Time (min)")["Ossidazione Lipidica (g)"], color="#FFA500")
        
        st.markdown("---")
        
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
