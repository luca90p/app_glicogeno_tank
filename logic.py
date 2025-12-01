import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState

# ... (Funzioni helper base rimangono invariate) ...

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
    return estimated_depletion_factor

def calculate_filling_factor_from_diet(weight_kg, cho_d1, cho_d2, s_fatigue, s_sleep, steps_m1, min_act_m1, steps_m2, min_act_m2):
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    cho_d1_gk = max(cho_d1, 1.0) / weight_kg
    cho_d2_gk = max(cho_d2, 1.0) / weight_kg
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
    depletion = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue)
    final_filling = diet_factor * depletion * s_sleep.factor
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
        "fill_pct": (total_actual_glycogen / max_total_capacity) * 100 if max_total_capacity > 0 else 0
    }

def calculate_rer_polynomial(intensity_factor):
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.67948706 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))

# --- NUOVA FUNZIONE INTERPOLAZIONE ---
def interpolate_consumption(current_val, curve_data):
    """
    Interpola il consumo CHO/FAT basandosi sul valore corrente (Watt o FC) e la curva a 3 punti.
    """
    p1 = curve_data['z2']
    p2 = curve_data['z3']
    p3 = curve_data['z4']
    
    # Sotto Z2 (Estensione lineare o flat)
    if current_val <= p1['hr']:
        return p1['cho'], p1['fat']
        
    # Tra Z2 e Z3
    elif p1['hr'] < current_val <= p2['hr']:
        slope_cho = (p2['cho'] - p1['cho']) / (p2['hr'] - p1['hr'])
        slope_fat = (p2['fat'] - p1['fat']) / (p2['hr'] - p1['hr'])
        delta = current_val - p1['hr']
        return p1['cho'] + (slope_cho * delta), p1['fat'] + (slope_fat * delta)
        
    # Tra Z3 e Z4
    elif p2['hr'] < current_val <= p3['hr']:
        slope_cho = (p3['cho'] - p2['cho']) / (p3['hr'] - p2['hr'])
        slope_fat = (p3['fat'] - p2['fat']) / (p3['hr'] - p2['hr'])
        delta = current_val - p2['hr']
        return p2['cho'] + (slope_cho * delta), p2['fat'] + (slope_fat * delta)
        
    # Sopra Z4 (Fuorigiri)
    else:
        # Aumentiamo CHO drasticamente, FAT a zero
        extra = current_val - p3['hr']
        return p3['cho'] + (extra * 3.0), max(0, p3['fat'] - extra)

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        mix_type_input=ChoMixType.GLUCOSE_ONLY, intensity_series=None, metabolic_curve=None):
    
    results = []
    initial_muscle = subject_data['muscle_glycogen_g']
    current_muscle = initial_muscle
    current_liver = subject_data['liver_glycogen_g']
    
    avg_hr = activity_params.get('avg_hr', 150)
    avg_watts = activity_params.get('avg_watts', 200)
    
    # Determina il valore base di intensità per la curva (se non c'è serie)
    base_val = avg_watts if activity_params.get('mode') == 'cycling' else avg_hr
    
    # Dati esogeni
    base_rate = 0.8 
    if subject_obj.height_cm > 170: base_rate += (subject_obj.height_cm - 170) * 0.015
    max_exo_rate_g_min = min(base_rate * mix_type_input.ox_factor, mix_type_input.max_rate_gh / 60)
    
    gut_accumulation = 0.0
    current_exo_ox_rate = 0.0 
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    total_fat_burned = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_per_hour > 0 else duration_min + 1
    
    for t in range(int(duration_min) + 1):
        # 1. INTENSITÀ ISTANTANEA
        current_val = base_val
        if intensity_series is not None and t < len(intensity_series):
            current_val = intensity_series[t]
        
        # 2. CONSUMO (CURVA O MODELLO)
        if metabolic_curve:
            cho_rate_gh, fat_rate_gh = interpolate_consumption(current_val, metabolic_curve)
            
            # --- FIX: DERIVA FISIOLOGICA (EFFICIENCY DRIFT) ---
            # Dopo 60min, a parità di Watt/FC, il costo in CHO aumenta (reclutamento fibre II)
            if t > 45:
                # Drift: +4% costo CHO ogni ora extra (0.06% al minuto)
                drift_factor = 1.0 + ((t - 45) * 0.0007)
                cho_rate_gh *= drift_factor
                # I grassi tendono a calare leggermente per fatica mitocondriale se non si rallenta
                fat_rate_gh *= (1.0 - ((t - 45) * 0.0002)) 
            
            total_cho_demand = cho_rate_gh / 60.0
            fat_burned = fat_rate_gh / 60.0
        else:
            # Fallback Modello Teorico (semplificato)
            # Qui usiamo la logica base se non c'è curva
            ftp = activity_params.get('ftp_watts', 250)
            if_ratio = current_val / ftp if activity_params.get('mode') == 'cycling' else current_val / 170
            
            # Drift teorico
            drift = 1.0 + ((t - 60) * 0.0005) if t > 60 else 1.0
            kcal_demand = (if_ratio * ftp * 60 / 4184 / 0.22) if ftp > 0 else 10.0
            kcal_demand *= drift
            
            # RER teorico
            rer = calculate_rer_polynomial(if_ratio)
            cho_pct = (rer - 0.7) / 0.3
            cho_pct = max(0.1, min(1.0, cho_pct))
            
            total_cho_demand = (kcal_demand * cho_pct) / 4.1
            fat_burned = (kcal_demand * (1-cho_pct)) / 9.3

        # 3. GESTIONE INTAKE
        instant_input_g = 0.0 
        if constant_carb_intake_g_h > 0 and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instant_input_g = cho_per_unit_g 
            
        target_exo = max_exo_rate_g_min * oxidation_efficiency_input
        if t > 0:
            if constant_carb_intake_g_h == 0: current_exo_ox_rate *= (1 - alpha) 
            else: current_exo_ox_rate += alpha * (target_exo - current_exo_ox_rate)
            current_exo_ox_rate = max(0.0, current_exo_ox_rate)
            
            gut_accumulation += (instant_input_g * oxidation_efficiency_input) - current_exo_ox_rate
            if gut_accumulation < 0: gut_accumulation = 0 

        # 4. BILANCIO FONTI
        blood_demand = total_cho_demand 
        
        from_exogenous = min(blood_demand, current_exo_ox_rate)
        remaining_demand = blood_demand - from_exogenous
        
        from_liver = min(remaining_demand, 1.2) # Max epatico ~1.2 g/min
        if current_liver <= 0: from_liver = 0
        
        from_muscle = remaining_demand - from_liver
        if current_muscle <= 0: from_muscle = 0
        
        if t > 0:
            current_liver = max(0, current_liver - from_liver)
            current_muscle = max(0, current_muscle - from_muscle)
            total_fat_burned += fat_burned
            total_muscle_used += from_muscle
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": from_muscle * 60,
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": from_exogenous * 60,
            "Ossidazione Lipidica (g)": fat_burned * 60,
            "Residuo Muscolare": current_muscle,
            "Residuo Epatico": current_liver,
            "Gut Load": gut_accumulation,
            "Intensity": current_val
        })
        
    stats = {
        "final_glycogen": current_muscle + current_liver,
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned,
        "intensity_factor": current_val / 200.0 # Indicativo
    }
    return pd.DataFrame(results), stats

# ... (Funzioni calculate_tapering_trajectory rimangono invariate) ...
def calculate_tapering_trajectory(subject, days_data, start_state: GlycogenState = GlycogenState.NORMAL):
    # (Inserisci qui la funzione calculate_tapering_trajectory definita nella risposta precedente)
    # Per brevità non la ricopio, usa quella dell'ultimo aggiornamento
    LIVER_DRAIN_24H = 4.0 * 24 
    NEAT_CHO_24H = 1.5 * subject.weight_kg 
    MAX_SYNTHESIS_RATE_G_KG = 10.0 
    tank = calculate_tank(subject)
    MAX_MUSCLE = tank['max_capacity_g'] - 120 
    MAX_LIVER = 120.0
    start_factor = start_state.factor
    current_muscle = MAX_MUSCLE * start_factor 
    current_liver = MAX_LIVER * start_factor
    current_muscle = min(current_muscle, MAX_MUSCLE)
    current_liver = min(current_liver, MAX_LIVER)
    trajectory = []
    for day in days_data:
        duration = day['duration']
        intensity_if = day.get('calculated_if', 0.0) 
        cho_in = day['cho_in']
        sleep_factor = day['sleep_factor']
        exercise_drain_muscle = 0
        exercise_drain_liver = 0
        if duration > 0 and intensity_if > 0:
            max_vo2_ml = (subject.vo2max_absolute_l_min * 1000) / subject.weight_kg
            pct_vo2 = min(1.0, intensity_if * 0.95) 
            if intensity_if <= 0.55: cho_ox_pct = 0.20
            elif intensity_if <= 0.75: cho_ox_pct = 0.50 + (intensity_if - 0.55) * 1.5
            elif intensity_if <= 0.90: cho_ox_pct = 0.80 + (intensity_if - 0.75) * 1.0
            else: cho_ox_pct = 1.0 
            kcal_min = (max_vo2_ml * pct_vo2 * subject.weight_kg / 1000) * 5.0
            total_kcal = kcal_min * duration
            total_cho_burned = (total_kcal * cho_ox_pct) / 4.0
            liver_ratio = 0.15 if intensity_if < 0.75 else 0.05
            exercise_drain_liver = total_cho_burned * liver_ratio
            exercise_drain_muscle = total_cho_burned * (1 - liver_ratio)
        absorption_efficiency = 0.95 * sleep_factor
        workout_bonus = 1.0
        if duration > 30 and intensity_if > 0.6:
            workout_bonus = 1.2 
        net_cho_available = cho_in * absorption_efficiency
        liver_maintenance_cost = LIVER_DRAIN_24H 
        neat_cost = NEAT_CHO_24H
        daily_obligatory_drain = liver_maintenance_cost + (neat_cost * 0.5)
        remaining_cho = net_cho_available - daily_obligatory_drain
        current_liver -= exercise_drain_liver
        current_muscle -= exercise_drain_muscle
        current_liver = max(0, current_liver)
        current_muscle = max(0, current_muscle)
        if remaining_cho > 0:
            liver_space = MAX_LIVER - current_liver
            to_liver = min(remaining_cho, liver_space)
            current_liver += to_liver
            remaining_cho -= to_liver
            if remaining_cho > 0:
                muscle_space = MAX_MUSCLE - current_muscle
                max_daily_synthesis = subject.weight_kg * MAX_SYNTHESIS_RATE_G_KG * workout_bonus
                fill_level = current_muscle / MAX_MUSCLE
                if fill_level > 0.8:
                    max_daily_synthesis *= 0.6 
                real_synthesis = min(remaining_cho, max_daily_synthesis)
                to_muscle = min(real_synthesis, muscle_space)
                current_muscle += to_muscle
        else:
            deficit = abs(remaining_cho)
            current_liver -= deficit
            if current_liver < 0:
                muscle_debt = abs(current_liver)
                current_liver = 0
                current_muscle -= muscle_debt
        current_muscle = max(0, min(current_muscle, MAX_MUSCLE))
        current_liver = max(0, min(current_liver, MAX_LIVER))
        trajectory.append({
            "Giorno": day['label'], "Muscolare": int(current_muscle), "Epatico": int(current_liver),
            "Totale": int(current_muscle + current_liver), "Pct": (current_muscle + current_liver) / (MAX_MUSCLE + MAX_LIVER) * 100,
            "Input CHO": cho_in, "IF": intensity_if, "Sleep": day['sleep_factor']
        })
    final_state = trajectory[-1]
    updated_tank = tank.copy()
    updated_tank['muscle_glycogen_g'] = final_state['Muscolare']
    updated_tank['liver_glycogen_g'] = final_state['Epatico']
    updated_tank['actual_available_g'] = final_state['Totale']
    updated_tank['fill_pct'] = final_state['Pct']
    return pd.DataFrame(trajectory), updated_tank
