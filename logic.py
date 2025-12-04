import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState, IntakeMode

# --- 1. FUNZIONI DI SUPPORTO ---

def get_concentration_from_vo2max(vo2_max):
    """Stima la concentrazione di glicogeno muscolare (g/kg)."""
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    return max(12.0, min(26.0, conc))

def calculate_rer_polynomial(intensity_factor):
    """Calcola il Quoziente Respiratorio (RER) in base all'IF."""
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.679487060 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))

def calculate_depletion_factor(steps, activity_min, s_fatigue):
    steps_base = 10000 
    steps_factor = (steps - steps_base) / 5000 * 0.1 * 0.4
    activity_base = 120 
    if activity_min < 60: 
        activity_factor = (1 - (activity_min / 60)) * 0.05 * 0.6
    else:
        activity_factor = (activity_min - activity_base) / 60 * -0.1 * 0.6
    depletion_impact = steps_factor + activity_factor
    return max(0.6, min(1.0, 1.0 + depletion_impact))

def calculate_filling_factor_from_diet(weight_kg, cho_d1, cho_d2, s_fatigue, s_sleep, steps_m1, min_act_m1, steps_m2, min_act_m2):
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    cho_d1_gk = max(cho_d1, 1.0) / weight_kg
    cho_d2_gk = max(cho_d2, 1.0) / weight_kg
    avg_cho_gk = (cho_d1_gk * 0.7) + (cho_d2_gk * 0.3)
    
    if avg_cho_gk >= CHO_MAX_GK: diet_factor = 1.25
    elif avg_cho_gk >= CHO_BASE_GK: diet_factor = 1.0 + (avg_cho_gk - CHO_BASE_GK) * (0.25 / (CHO_MAX_GK - CHO_BASE_GK))
    elif avg_cho_gk > CHO_MIN_GK: diet_factor = 0.5 + (avg_cho_gk - CHO_MIN_GK) * (0.5 / (CHO_BASE_GK - CHO_MIN_GK))
    else: diet_factor = 0.5
    
    diet_factor = min(1.25, max(0.5, diet_factor))
    depletion = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue)
    final_filling = diet_factor * depletion * s_sleep.factor
    return final_filling, diet_factor, avg_cho_gk, cho_d1_gk, cho_d2_gk

def calculate_tank(subject: Subject):
    if subject.muscle_mass_kg is not None and subject.muscle_mass_kg > 0:
        total_muscle = subject.muscle_mass_kg
        muscle_source_note = "Massa Muscolare Misurata"
    else:
        lbm = subject.lean_body_mass
        total_muscle = lbm * subject.muscle_fraction
        muscle_source_note = "Massa Muscolare Stimata"

    active_muscle = total_muscle * subject.sport.val
    creatine_multiplier = 1.10 if subject.uses_creatine else 1.0
    base_muscle_glycogen = active_muscle * subject.glycogen_conc_g_kg
    max_total_capacity = (base_muscle_glycogen * 1.25 * creatine_multiplier) + 100.0
    final_filling_factor = subject.filling_factor * subject.menstrual_phase.factor
    current_muscle_glycogen = base_muscle_glycogen * creatine_multiplier * final_filling_factor
    max_physiological_limit = active_muscle * 35.0
    if current_muscle_glycogen > max_physiological_limit: current_muscle_glycogen = max_physiological_limit
    
    liver_fill_factor = 1.0
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
        "muscle_source_note": muscle_source_note
    }

def interpolate_consumption(current_val, curve_data):
    p1 = curve_data['z2']
    p2 = curve_data['z3']
    p3 = curve_data['z4']
    
    if p2['hr'] == p1['hr'] or p3['hr'] == p2['hr']: return p2['cho'], p2['fat'] 

    if current_val <= p1['hr']: return p1['cho'], p1['fat']
    elif p1['hr'] < current_val <= p2['hr']:
        slope_c = (p2['cho'] - p1['cho']) / (p2['hr'] - p1['hr'])
        slope_f = (p2['fat'] - p1['fat']) / (p2['hr'] - p1['hr'])
        d = current_val - p1['hr']
        return p1['cho'] + (slope_c * d), p1['fat'] + (slope_f * d)
    elif p2['hr'] < current_val <= p3['hr']:
        slope_c = (p3['cho'] - p2['cho']) / (p3['hr'] - p2['hr'])
        slope_f = (p3['fat'] - p2['fat']) / (p3['hr'] - p2['hr'])
        d = current_val - p2['hr']
        return p2['cho'] + (slope_c * d), p3['fat'] + (slope_f * d)
    else:
        extra = current_val - p3['hr']
        return p3['cho'] + (extra * 4.0), max(0.0, p3['fat'] - extra * 0.5)

def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts, mix_type: ChoMixType):
    base_rate = 0.8 
    if height_cm > 170: base_rate += (height_cm - 170) * 0.015
    if ftp_watts > 200: base_rate += (ftp_watts - 200) * 0.0015
    estimated_rate_gh = base_rate * 60 * mix_type.ox_factor
    final_rate_g_min = min(estimated_rate_gh / 60, mix_type.max_rate_gh / 60)
    return final_rate_g_min

# --- 2. MOTORE TAPERING ---

def calculate_tapering_trajectory(subject, days_data, start_state: GlycogenState = GlycogenState.NORMAL):
    LIVER_DRAIN_24H = 4.0 * 24 
    NEAT_CHO_24H = 1.0 * subject.weight_kg 
    MAX_SYNTHESIS_RATE_G_KG = 10.0 
    
    tank = calculate_tank(subject)
    MAX_MUSCLE = tank['max_capacity_g'] - 100 
    MAX_LIVER = 100.0
    
    start_factor = start_state.factor
    current_muscle = min(MAX_MUSCLE * start_factor, MAX_MUSCLE)
    current_liver = min(MAX_LIVER * start_factor, MAX_LIVER)
    trajectory = []
    
    for day in days_data:
        cho_in = day['cho_in']
        sleep_factor = day['sleep_factor']
        duration = day['duration']
        intensity = day.get('calculated_if', 0)
        consumption = 0
        if duration > 0: consumption = (duration/60) * 600 * intensity 
        net = (cho_in * sleep_factor) - (LIVER_DRAIN_24H + NEAT_CHO_24H + (consumption/4))
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

# --- 3. MOTORE SIMULAZIONE (CON CUTOFF) ---

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, 
                        intensity_series=None, metabolic_curve=None, 
                        intake_mode=IntakeMode.DISCRETE, intake_cutoff_min=0): # NUOVO PARAMETRO
    
    results = []
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = subject_data['liver_glycogen_g']
    
    avg_watts = activity_params.get('avg_watts', 200)
    ftp_watts = activity_params.get('ftp_watts', 250)
    threshold_hr = activity_params.get('threshold_hr', 170)
    gross_efficiency = activity_params.get('efficiency', 22.0)
    mode = activity_params.get('mode', 'cycling')
    avg_hr = activity_params.get('avg_hr', 150)
    
    threshold_ref = ftp_watts if mode == 'cycling' else threshold_hr
    base_val = avg_watts if mode == 'cycling' else avg_hr
    
    intensity_factor_reference = base_val / threshold_ref if threshold_ref > 0 else 0.8
    
    if mode == 'cycling':
        kcal_per_min_base = (avg_watts * 60) / 4184 / (gross_efficiency / 100.0)
    else:
        kcal_per_min_base = (subject_obj.weight_kg * 0.2 * intensity_factor_reference * 3.5) / 5.0

    is_lab_data = True if metabolic_curve else False
    lab_cho_rate = activity_params.get('lab_cho_g_h', 0) / 60.0
    lab_fat_rate = activity_params.get('lab_fat_g_h', 0) / 60.0
    
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate 
    else:
        max_exo_rate_g_min = estimate_max_exogenous_oxidation(
            subject_obj.height_cm, subject_obj.weight_kg, ftp_watts, mix_type_input
        )
    
    gut_accumulation_total = 0.0
    current_exo_oxidation_g_min = 0.0 
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    total_fat_burned_g = 0.0
    total_intake_cumulative = 0.0
    total_exo_oxidation_cumulative = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_per_hour > 0 else duration_min + 1
    is_input_zero = constant_carb_intake_g_h == 0
    
    for t in range(int(duration_min) + 1):
        
        # Intensità
        current_intensity_factor = intensity_factor_reference
        current_val = base_val
        if intensity_series is not None and t < len(intensity_series):
            current_val = intensity_series[t]
            current_intensity_factor = current_val / threshold_ref if threshold_ref > 0 else 0.8
        
        current_kcal_demand = 0.0
        if mode == 'cycling':
            instant_power = current_val
            current_eff = gross_efficiency
            if t > 60: 
                loss = (t - 60) * 0.02
                current_eff = max(15.0, gross_efficiency - loss)
            current_kcal_demand = (instant_power * 60) / 4184 / (current_eff / 100.0)
        else: 
            drift_factor = 1.0
            if t > 60: drift_factor += (t - 60) * 0.0005 
            demand_scaling = current_intensity_factor / intensity_factor_reference if intensity_factor_reference > 0 else 1.0
            current_kcal_demand = kcal_per_min_base * drift_factor * demand_scaling
        
        # --- GESTIONE INTAKE CON CUTOFF ---
        instantaneous_input_g_min = 0.0 
        
        # Se siamo nella finestra di Stop (es. ultimi 20 min), niente cibo.
        in_feeding_window = t <= (duration_min - intake_cutoff_min)
        
        if not is_input_zero and in_feeding_window:
            if intake_mode == IntakeMode.DISCRETE:
                if t == 0 or (t > 0 and intake_interval_min > 0 and t % intake_interval_min == 0):
                    instantaneous_input_g_min = cho_per_unit_g 
            else:
                instantaneous_input_g_min = constant_carb_intake_g_h / 60.0
        
        target_exo_oxidation_limit_g_min = max_exo_rate_g_min * oxidation_efficiency_input
        
        # Logica Target Sensibile
        user_intake_rate = constant_carb_intake_g_h / 60.0 
        effective_target = min(user_intake_rate, max_exo_rate_g_min) * oxidation_efficiency_input
        if is_input_zero: effective_target = 0.0

        if t > 0:
            if is_input_zero:
                current_exo_oxidation_g_min *= (1 - alpha) 
            else:
                current_exo_oxidation_g_min += alpha * (effective_target - current_exo_oxidation_g_min)
            
            current_exo_oxidation_g_min = max(0.0, current_exo_oxidation_g_min)
            
            gut_accumulation_total += (instantaneous_input_g_min * oxidation_efficiency_input)
            real_oxidation = min(current_exo_oxidation_g_min, gut_accumulation_total)
            current_exo_oxidation_g_min = real_oxidation
            gut_accumulation_total -= real_oxidation
            if gut_accumulation_total < 0: gut_accumulation_total = 0 
            
            total_intake_cumulative += instantaneous_input_g_min 
            total_exo_oxidation_cumulative += current_exo_oxidation_g_min
        
        # --- CONSUMO ---
        if is_lab_data:
            cho_rate_gh, fat_rate_gh = interpolate_consumption(current_val, metabolic_curve)
            if t > 60:
                drift = 1.0 + ((t - 60) * 0.0006)
                cho_rate_gh *= drift
                fat_rate_gh *= (1.0 - ((t - 60) * 0.0003))
            total_cho_demand = cho_rate_gh / 60.0
            g_fat = fat_rate_gh / 60.0
            kcal_cho_demand = total_cho_demand * 4.1
            cho_ratio = 1.0 
            rer = 0.85 
        else:
            standard_crossover = 75.0 
            crossover_val = crossover_pct if crossover_pct else standard_crossover
            if_shift = (standard_crossover - crossover_val) / 100.0
            effective_if_for_rer = max(0.3, current_intensity_factor + if_shift)
            
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
            total_cho_demand = kcal_cho_demand / 4.1
            g_fat = (current_kcal_demand * (1.0-cho_ratio) / 9.0) if current_kcal_demand > 0 else 0
        
        total_cho_g_min = total_cho_demand
        
        # --- RIPARTIZIONE ---
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
                total_fat_burned_g += g_fat
            
            total_muscle_used += muscle_usage_g_min
            total_liver_used += from_liver
            total_exo_used += from_exogenous
        
        status_label = "Ottimale"
        if current_liver_glycogen < 20: status_label = "CRITICO (Ipoglicemia)"
        elif current_muscle_glycogen < 100: status_label = "Warning (Gambe Vuote)"
        
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
            "Target Intake (g/h)": constant_carb_intake_g_h,
            "Gut Load": gut_accumulation_total,
            "Stato": status_label,
            "CHO %": cho_ratio * 100,
            "Intake Cumulativo (g)": total_intake_cumulative,
            "Ossidazione Cumulativa (g)": total_exo_oxidation_cumulative,
            "Intensity Factor (IF)": current_intensity_factor 
        })
    
    total_kcal_final = current_kcal_demand * 60 
    final_total_glycogen = current_muscle_glycogen + current_liver_glycogen
    
    stats = {
        "final_glycogen": final_total_glycogen,
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "kcal_total_h": total_kcal_final,
        "intensity_factor": intensity_factor_reference,
        "avg_rer": rer,
        "cho_pct": cho_ratio * 100
    }
    return pd.DataFrame(results), stats

# --- 4. CALCOLO REVERSE STRATEGY ---

def calculate_minimum_strategy(tank, duration, subj, params, curve_data, mix_type, intake_mode, intake_cutoff_min=0):
    """
    Trova l'intake minimo per finire la gara con riserve > 0.
    """
    optimal = None
    for intake in range(0, 125, 5):
        df, stats = simulate_metabolism(
            tank, duration, intake, 25, 75, 20, subj, params, 
            mix_type_input=mix_type, metabolic_curve=curve_data,
            intake_mode=intake_mode, intake_cutoff_min=intake_cutoff_min # Passa il cutoff
        )
        
        min_liver = df['Residuo Epatico'].min()
        min_muscle = df['Residuo Muscolare'].min()
        
        if min_liver > 5 and min_muscle > 20:
            optimal = intake
            break
            
    return optimal

# --- 4. CALCOLO STRATEGIA MINIMA ---

# Modifica la definizione per accettare intake_mode
def calculate_minimum_strategy(tank, duration, subj, params, curve_data, mix_type, intake_mode, intake_cutoff_min=0):
    """
    Trova l'intake minimo per finire la gara con riserve > 0.
    """
    optimal = None
    for intake in range(0, 125, 5):
        df, stats = simulate_metabolism(
            tank, duration, intake, 25, 75, 20, subj, params, 
            mix_type_input=mix_type, metabolic_curve=curve_data,
            intake_mode=intake_mode, intake_cutoff_min=intake_cutoff_min # Passa il cutoff
        )
        
        min_liver = df['Residuo Epatico'].min()
        min_muscle = df['Residuo Muscolare'].min()
        
        if min_liver > 5 and min_muscle > 20:
            optimal = intake
            break
            
    return optimal


