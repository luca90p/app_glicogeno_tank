import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState

# --- 1. FUNZIONI HELPER (VERSIONE BACKUP) ---

def get_concentration_from_vo2max(vo2_max):
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

def calculate_depletion_factor(steps, activity_min, s_fatigue):
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
        return s_fatigue.factor
    else:
        return estimated_depletion_factor

def calculate_filling_factor_from_diet(weight_kg, cho_d1, cho_d2, s_fatigue, s_sleep, steps_m1, min_act_m1, steps_m2, min_act_m2):
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    
    cho_d1_gk = max(cho_d1, 1.0) / weight_kg
    cho_d2_gk = max(cho_d2, 1.0) / weight_kg
    
    depletion_m1 = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue)
    depletion_m2 = calculate_depletion_factor(steps_m2, min_act_m2, s_fatigue)
    
    recovery_factor = (depletion_m1 * 0.7) + (depletion_m2 * 0.3)
    avg_cho_gk = (cho_d1_gk * 0.7) + (cho_d2_gk * 0.3)
    
    if avg_cho_gk >= CHO_MAX_GK:
        diet_factor = 1.25
    elif avg_cho_gk >= CHO_BASE_GK:
        diet_factor = 1.0 + (avg_cho_gk - CHO_BASE_GK) * (0.25 / (CHO_MAX_GK - CHO_BASE_GK))
    elif avg_cho_gk > CHO_MIN_GK:
        diet_factor = 0.5 + (avg_cho_gk - CHO_MIN_GK) * (0.5 / (CHO_BASE_GK - CHO_MIN_GK))
    else: 
        diet_factor = 0.5
    
    diet_factor = min(1.25, max(0.5, diet_factor))
    
    final_filling = diet_factor * recovery_factor * s_sleep.factor
    return final_filling, diet_factor, avg_cho_gk, cho_d1_gk, cho_d2_gk

def calculate_tank(subject: Subject):
    if subject.muscle_mass_kg is not None and subject.muscle_mass_kg > 0:
        total_muscle = subject.muscle_mass_kg
    else:
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
    
    if subject.filling_factor <= 0.6: liver_fill_factor = 0.6
    if subject.glucose_mg_dl is not None:
        if subject.glucose_mg_dl < 70: liver_fill_factor = 0.2
        elif subject.glucose_mg_dl < 85: liver_fill_factor = min(liver_fill_factor, 0.5)
    
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
        "muscle_source_note": "Standard"
    }

def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts, mix_type: ChoMixType):
    base_rate = 0.8 
    if height_cm > 170: base_rate += (height_cm - 170) * 0.015
    if ftp_watts > 200: base_rate += (ftp_watts - 200) * 0.0015
    
    estimated_rate_gh = base_rate * 60 * mix_type.ox_factor
    final_rate_g_min = min(estimated_rate_gh / 60, mix_type.max_rate_gh / 60)
    return final_rate_g_min

def calculate_rer_polynomial(intensity_factor):
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.67948706 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))


# --- 2. MOTORE SIMULAZIONE (VERSIONE BACKUP RESTAURATA) ---

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, 
                        intensity_series=None, metabolic_curve=None):
    
    # NOTA: 'metabolic_curve' è presente per compatibilità ma viene IGNORATO come richiesto.
    
    results = []
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = subject_data['liver_glycogen_g']
    
    mode = activity_params.get('mode', 'cycling')
    gross_efficiency = activity_params.get('efficiency', 22.0)
    
    avg_power = activity_params.get('avg_watts', 200)
    ftp_watts = activity_params.get('ftp_watts', 250) 
    avg_hr = activity_params.get('avg_hr', 150)
    threshold_hr = activity_params.get('threshold_hr', 170)
    
    # Selezione soglia corretta
    threshold_ref = ftp_watts if mode == 'cycling' else threshold_hr
    base_val = avg_watts if mode == 'cycling' else avg_hr
    
    # Calcolo IF di riferimento base
    intensity_factor_reference = base_val / threshold_ref if threshold_ref > 0 else 0.8
    
    # Base kcal/min
    if mode == 'cycling':
        kcal_per_min_base = (avg_power * 60) / 4184 / (gross_efficiency / 100.0)
    else:
        # Stima semplice per corsa/altro
        kcal_per_min_base = (subject_obj.weight_kg * 0.2 * intensity_factor_reference * 3.5) / 5.0

    is_lab_data = activity_params.get('use_lab_data', False)
    lab_cho_rate = activity_params.get('lab_cho_g_h', 0) / 60.0
    lab_fat_rate = activity_params.get('lab_fat_g_h', 0) / 60.0
    
    # Calcolo Max Exo
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate 
    else:
        max_exo_rate_g_min = estimate_max_exogenous_oxidation(
            subject_obj.height_cm, subject_obj.weight_kg, ftp_watts, mix_type_input
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
        
        current_intensity_factor = intensity_factor_reference
        current_val = base_val # Valore assoluto (W o bpm)

        if intensity_series is not None and t < len(intensity_series):
            # intensity_series contiene valori assoluti (W o BPM) in questa versione dell'app
            current_val = intensity_series[t]
            current_intensity_factor = current_val / threshold_ref if threshold_ref > 0 else 0.8
        
        current_kcal_demand = 0.0
        
        if mode == 'cycling':
            instant_power = current_val # Watt
            current_eff = gross_efficiency
            if t > 60: 
                current_eff = max(15.0, gross_efficiency - ((t - 60) * 0.02))
            current_kcal_demand = (instant_power * 60) / 4184 / (current_eff / 100.0)
        else: 
            drift_factor = 1.0 + ((t - 60) * 0.0005) if t > 60 else 1.0
            # Ricalcolo kcal su IF dinamico
            current_kcal_demand = (subject_obj.weight_kg * 0.2 * current_intensity_factor * 3.5) / 5.0 * drift_factor
        
        instantaneous_input_g_min = 0.0 
        if not is_input_zero and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instantaneous_input_g_min = cho_per_unit_g 
        
        target_exo_oxidation_limit_g_min = max_exo_rate_g_min * oxidation_efficiency_input
        
        if t > 0:
            if is_input_zero:
                current_exo_oxidation_g_min *= (1 - alpha) 
            else:
                current_exo_oxidation_g_min += alpha * (target_exo_oxidation_limit_g_min - current_exo_oxidation_g_min)
            
            current_exo_oxidation_g_min = max(0.0, current_exo_oxidation_g_min)
            
            gut_accumulation_total += (instantaneous_input_g_min * oxidation_efficiency_input) - current_exo_oxidation_g_min
            if gut_accumulation_total < 0: gut_accumulation_total = 0 
            
            total_intake_cumulative += instantaneous_input_g_min
            total_exo_oxidation_cumulative += current_exo_oxidation_g_min
        
        # --- LOGICA ORIGINALE (Backup) ---
        if is_lab_data:
            # Se si usano i dati manuali (non la curva, ma i campi input singoli)
            fatigue_mult = 1.0 + ((t - 30) * 0.0005) if t > 30 else 1.0 
            total_cho_demand = lab_cho_rate * fatigue_mult 
            kcal_cho_demand = total_cho_demand * 4.1
            
            glycogen_burned_per_min = total_cho_demand - current_exo_oxidation_g_min
            min_endo = total_cho_demand * 0.2 
            if glycogen_burned_per_min < min_endo: glycogen_burned_per_min = min_endo
            
            cho_ratio = total_cho_demand / (total_cho_demand + lab_fat_rate) if (total_cho_demand + lab_fat_rate) > 0 else 0
            rer = 0.7 + (0.3 * cho_ratio) 
        
        else:
            # Modello Teorico
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
            kcal_cho_demand = current_kcal_demand * cho_ratio
        
        total_cho_g_min = kcal_cho_demand / 4.1
        
        # --- LOGICA "VECCHIA" (RAMPA COGGAN) ---
        # Questa è la parte chiave che volevi ripristinare
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
            
            fat_ratio_used = 1.0 - cho_ratio
            fat_g = (current_kcal_demand * fat_ratio_used) / 9.0
            total_fat_burned_g += fat_g
            
            total_muscle_used += muscle_usage_g_min
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        status_label = "Ottimale"
        if current_liver_glycogen < 20: status_label = "CRITICO (Ipoglicemia)"
        elif current_muscle_glycogen < 100: status_label = "Warning (Gambe Vuote)"
        
        g_fat = (current_kcal_demand * (1-cho_ratio) / 9.0) if current_kcal_demand > 0 else 0
        
        # Totale per calcolo percentuali
        total_g_min = max(1.0, muscle_usage_g_min + from_liver + from_exogenous + g_fat)

        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": muscle_usage_g_min * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": from_exogenous * 60, 
            "Ossidazione Lipidica (g)": g_fat * 60,
            
            "Pct_Muscle": f"{(muscle_usage_g_min / total_g_min * 100):.1f}%",
            "Pct_Liver": f"{(from_liver / total_g_min * 100):.1f}%",
            "Pct_Exo": f"{(from_exogenous / total_g_min * 100):.1f}%",
            "Pct_Fat": f"{(g_fat / total_g_min * 100):.1f}%",

            "Residuo Muscolare": current_muscle_glycogen,
            "Residuo Epatico": current_liver_glycogen,
            "Residuo Totale": current_muscle_glycogen + current_liver_glycogen,
            "Gut Load": gut_accumulation_total,
            "Stato": status_label,
            "CHO %": cho_ratio * 100,
            "Intake Cumulativo (g)": total_intake_cumulative,
            "Ossidazione Cumulativa (g)": total_exo_oxidation_cumulative,
            "Intensity Factor (IF)": current_intensity_factor 
        })
    
    total_kcal_final = 0 # Placeholder
    final_total_glycogen = current_muscle_glycogen + current_liver_glycogen

    stats = {
        "final_glycogen": final_total_glycogen,
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "intensity_factor": intensity_factor_reference,
        "avg_rer": rer if 'rer' in locals() else 0.85,
        "cho_pct": cho_ratio * 100
    }
    return pd.DataFrame(results), stats

# --- MOTORE TAPERING COMPATIBILE ---
def calculate_tapering_trajectory(subject, days_data, start_state: GlycogenState = GlycogenState.NORMAL):
    # Logica semplificata per compatibilità con Tab 2
    LIVER_DRAIN_24H = 4.0 * 24 
    NEAT_CHO_24H = 1.0 * subject.weight_kg 
    MAX_SYNTHESIS_RATE_G_KG = 10.0 
    
    tank = calculate_tank(subject)
    MAX_MUSCLE = tank['max_capacity_g'] - 120 
    MAX_LIVER = 120.0
    
    start_factor = start_state.factor
    current_muscle = min(MAX_MUSCLE * start_factor, MAX_MUSCLE)
    current_liver = min(MAX_LIVER * start_factor, MAX_LIVER)
    trajectory = []
    
    for day in days_data:
        cho_in = day['cho_in']
        sleep_factor = day['sleep_factor']
        
        # Stima consumo
        duration = day['duration']
        intensity = day.get('calculated_if', 0)
        
        # Consumo rozzo per tapering
        consumption = 0
        if duration > 0:
            consumption = (duration/60) * 600 * intensity # Kcal approx
        
        net = (cho_in * sleep_factor) - (LIVER_DRAIN_24H + NEAT_CHO_24H + (consumption/4))
        
        # Ripartizione semplice
        if net > 0:
            current_liver = min(MAX_LIVER, current_liver + (net * 0.3))
            current_muscle = min(MAX_MUSCLE, current_muscle + (net * 0.7))
        else:
            current_liver = max(0, current_liver + (net * 0.5))
            current_muscle = max(0, current_muscle + (net * 0.5))
            
        trajectory.append({
            "Giorno": day['label'], "Muscolare": int(current_muscle), "Epatico": int(current_liver),
            "Totale": int(current_muscle + current_liver), "Pct": 0, "Input CHO": cho_in, "IF": intensity
        })
        
    final_tank = tank.copy()
    final_tank['muscle_glycogen_g'] = current_muscle
    final_tank['liver_glycogen_g'] = current_liver
    final_tank['actual_available_g'] = current_muscle + current_liver
    final_tank['fill_pct'] = (current_muscle + current_liver) / (MAX_MUSCLE + MAX_LIVER) * 100
    return pd.DataFrame(trajectory), final_tank
