import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState

def get_concentration_from_vo2max(vo2_max):
    """Stima la concentrazione di glicogeno muscolare (g/kg) basandosi sul VO2max."""
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

def calculate_depletion_factor(steps, activity_min, s_fatigue):
    """Calcola il fattore di deplezione basato sull'attività pregressa."""
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
    """Determina il fattore di riempimento del serbatoio (Filling Factor) basato su dieta e recupero."""
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
    """Calcola la capacità totale di stoccaggio (Muscolo + Fegato)."""
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
    if subject.filling_factor <= 0.6: 
        liver_fill_factor = 0.6
        
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
    """Stima RER basato sull'intensità."""
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.67948706 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        mix_type_input=ChoMixType.GLUCOSE_ONLY, intensity_series=None):
    """Simula il metabolismo minuto per minuto."""
    results = []
    initial_muscle = subject_data['muscle_glycogen_g']
    current_muscle = initial_muscle
    current_liver = subject_data['liver_glycogen_g']
    
    mode = activity_params.get('mode', 'cycling')
    gross_efficiency = activity_params.get('efficiency', 22.0)
    avg_power = activity_params.get('avg_watts', 200)
    ftp_watts = activity_params.get('ftp_watts', 250) 
    intensity_factor_reference = activity_params.get('intensity_factor', 0.8)
    
    if mode == 'cycling':
        kcal_per_min_base = (avg_power * 60) / 4184 / (gross_efficiency / 100.0)
    elif mode == 'running':
        speed_kmh = activity_params.get('speed_kmh', 10.0)
        kcal_per_hour = 1.0 * subject_obj.weight_kg * speed_kmh
        kcal_per_min_base = kcal_per_hour / 60.0
    else:
        vo2_operating = subject_obj.vo2max_absolute_l_min * intensity_factor_reference
        kcal_per_min_base = vo2_operating * 5.0
        
    is_lab_data = activity_params.get('use_lab_data', False)
    lab_cho_rate = activity_params.get('lab_cho_g_h', 0) / 60.0
    lab_fat_rate = activity_params.get('lab_fat_g_h', 0) / 60.0
    
    base_rate = 0.8 
    if subject_obj.height_cm > 170: base_rate += (subject_obj.height_cm - 170) * 0.015
    if ftp_watts > 200: base_rate += (ftp_watts - 200) * 0.0015
    max_exo_rate_g_min = min(base_rate * mix_type_input.ox_factor, mix_type_input.max_rate_gh / 60)

    total_fat_burned = 0.0
    gut_accumulation = 0.0
    current_exo_ox_rate = 0.0 
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    cumulative_intake = 0.0
    cumulative_ox = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_per_hour > 0 else duration_min + 1
    
    for t in range(int(duration_min) + 1):
        current_if = intensity_factor_reference
        if intensity_series is not None and t < len(intensity_series):
            current_if = intensity_series[t]
        
        if mode == 'cycling':
            instant_power = current_if * ftp_watts
            curr_eff = max(15.0, gross_efficiency - ((t - 60) * 0.02)) if t > 60 else gross_efficiency
            current_kcal_demand = (instant_power * 60) / 4184 / (curr_eff / 100.0)
        else: 
            drift = 1.0 + ((t - 60) * 0.0005) if t > 60 else 1.0
            demand_scaling = current_if / intensity_factor_reference if intensity_factor_reference > 0 else 1.0
            current_kcal_demand = kcal_per_min_base * drift * demand_scaling
        
        instant_input_g = 0.0 
        if constant_carb_intake_g_h > 0 and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instant_input_g = cho_per_unit_g 
        
        target_exo = max_exo_rate_g_min * oxidation_efficiency_input
        if t > 0:
            if constant_carb_intake_g_h == 0: current_exo_ox_rate *= (1 - alpha) 
            else: current_exo_ox_rate += alpha * (target_exo - current_exo_ox_rate)
            current_exo_ox_rate = max(0.0, current_exo_ox_rate)
        
        if t > 0:
            gut_accumulation += (instant_input_g * oxidation_efficiency_input) - current_exo_ox_rate
            if gut_accumulation < 0: gut_accumulation = 0 
            cumulative_intake += instant_input_g 
            cumulative_ox += current_exo_ox_rate
        
        if is_lab_data:
            total_cho_demand = lab_cho_rate * (1.0 + ((t - 30) * 0.0005) if t > 30 else 1.0)
            kcal_cho_demand = total_cho_demand * 4.1
            cho_ratio = total_cho_demand / (total_cho_demand + (lab_fat_rate/60)) if (total_cho_demand + lab_fat_rate) > 0 else 0
            rer = 0.85
        else:
            eff_if_rer = max(0.3, current_if + ((75.0 - crossover_pct) / 100.0))
            rer = calculate_rer_polynomial(eff_if_rer)
            base_cho_ratio = max(0.0, min(1.0, (rer - 0.70) * 3.45))
            if current_if < 0.85 and t > 60:
                base_cho_ratio = max(0.05, base_cho_ratio - (0.05 * (((t - 60) / 60.0) ** 1.2)))
            cho_ratio = base_cho_ratio
            kcal_cho_demand = current_kcal_demand * cho_ratio
        
        total_cho_g_min = kcal_cho_demand / 4.1
        
        muscle_fill_state = current_muscle / initial_muscle if initial_muscle > 0 else 0
        muscle_contrib = math.pow(muscle_fill_state, 0.6) 
        muscle_usage = total_cho_g_min * muscle_contrib
        if current_muscle <= 0: muscle_usage = 0
        
        blood_demand = total_cho_g_min - muscle_usage
        from_exogenous = min(blood_demand, current_exo_ox_rate)
        from_liver = min(blood_demand - from_exogenous, 1.2)
        if current_liver <= 0: from_liver = 0
        
        if t > 0:
            current_muscle = max(0, current_muscle - muscle_usage)
            current_liver = max(0, current_liver - from_liver)
            
            fat_burned = lab_fat_rate if is_lab_data else (current_kcal_demand * (1.0 - cho_ratio)) / 9.0
            total_fat_burned += fat_burned
            
            total_muscle_used += muscle_usage
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        g_fat = (current_kcal_demand * (1.0 - cho_ratio) / 9.0) if not is_lab_data else lab_fat_rate/60
        
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": muscle_usage * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": from_exogenous * 60, 
            "Ossidazione Lipidica (g)": g_fat * 60,
            "Residuo Muscolare": current_muscle,
            "Residuo Epatico": current_liver,
            "Gut Load": gut_accumulation,
            "Intake Cumulativo (g)": cumulative_intake,
            "Ossidazione Cumulativa (g)": cumulative_ox,
            "Intensity Factor (IF)": current_if 
        })
        
    stats = {
        "final_glycogen": current_muscle + current_liver, 
        "final_liver": current_liver,
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned,
        "intensity_factor": intensity_factor_reference,
        "avg_rer": rer if 'rer' in locals() else 0.85
    }
    return pd.DataFrame(results), stats

# --- NUOVA FUNZIONE PER IL TAB 2 ---
def calculate_tapering_trajectory(subject, days_data):
    """
    Simula l'andamento del glicogeno.
    ORA USA L'INTENSITY FACTOR (IF) CALCOLATO PER DETERMINARE IL CONSUMO.
    """
    LIVER_DRAIN_RATE_GH = 4.5 
    DAILY_NEAT_CHO = 1.0 * subject.weight_kg 
    
    tank = calculate_tank(subject)
    MAX_MUSCLE = tank['max_capacity_g'] - 120 
    MAX_LIVER = 120.0
    
    current_muscle = MAX_MUSCLE * 0.55 
    current_liver = MAX_LIVER * 0.50
    
    trajectory = []
    
    for day in days_data:
        duration = day['duration']
        # Qui ora ci aspettiamo un valore numerico di IF (es. 0.75), non una stringa
        intensity_if = day.get('calculated_if', 0.0) 
        cho_in = day['cho_in']
        sleep_factor = day['sleep_factor']
        
        exercise_drain_muscle = 0
        exercise_drain_liver = 0
        
        # Calcolo consumo basato su IF preciso
        if duration > 0 and intensity_if > 0:
            max_vo2_ml = (subject.vo2max_absolute_l_min * 1000) / subject.weight_kg
            
            # Stima della % del VO2max utilizzata basata sull'IF
            # (Approssimazione: IF 1.0 ~= 90% VO2max per un'ora, IF 0.6 ~= 50% VO2max)
            # Usiamo una relazione lineare semplificata per il tapering
            pct_vo2 = min(1.0, intensity_if * 0.95) 
            
            # Determina il mix energetico (CHO vs FAT) basato sull'IF
            # IF < 0.60 -> Prevalenza grassi (CHO ratio basso)
            # IF > 0.90 -> Prevalenza zuccheri (CHO ratio alto)
            if intensity_if <= 0.55:
                cho_ox_pct = 0.20
            elif intensity_if <= 0.75: # Z2/Z3
                cho_ox_pct = 0.50 + (intensity_if - 0.55) * 1.5 # Scala lineare
            elif intensity_if <= 0.90: # Z3/Z4
                cho_ox_pct = 0.80 + (intensity_if - 0.75) * 1.0
            else: # Sopra soglia
                cho_ox_pct = 1.0
            
            # Calcolo Calorie
            kcal_min = (max_vo2_ml * pct_vo2 * subject.weight_kg / 1000) * 5.0
            total_kcal = kcal_min * duration
            total_cho_burned = (total_kcal * cho_ox_pct) / 4.0
            
            # Ripartizione fegato/muscolo
            liver_ratio = 0.20 if intensity_if < 0.7 else 0.10
            exercise_drain_liver = total_cho_burned * liver_ratio
            exercise_drain_muscle = total_cho_burned * (1 - liver_ratio)

        daily_liver_drain = (LIVER_DRAIN_RATE_GH * 24) + DAILY_NEAT_CHO
        base_efficiency = 0.96 
        synthesis_efficiency = base_efficiency * sleep_factor
        effective_cho_available = cho_in * synthesis_efficiency
        
        liver_net = effective_cho_available - daily_liver_drain - exercise_drain_liver
        surplus_for_muscle = 0
        
        if liver_net >= 0:
            space_in_liver = MAX_LIVER - current_liver
            if liver_net >= space_in_liver:
                current_liver = MAX_LIVER
                surplus_for_muscle = liver_net - space_in_liver
            else:
                current_liver += liver_net
        else:
            current_liver += liver_net 
            if current_liver < 0: current_liver = 0
            
        current_muscle = current_muscle - exercise_drain_muscle + surplus_for_muscle
        
        if current_muscle > MAX_MUSCLE: current_muscle = MAX_MUSCLE
        if current_muscle < 0: current_muscle = 0
        
        trajectory.append({
            "Giorno": day['label'],
            "Muscolare": int(current_muscle),
            "Epatico": int(current_liver),
            "Totale": int(current_muscle + current_liver),
            "Pct": (current_muscle + current_liver) / (MAX_MUSCLE + MAX_LIVER) * 100,
            "Input CHO": cho_in,
            "IF": intensity_if
        })
        
    final_state = trajectory[-1]
    
    updated_tank = tank.copy()
    updated_tank['muscle_glycogen_g'] = final_state['Muscolare']
    updated_tank['liver_glycogen_g'] = final_state['Epatico']
    updated_tank['actual_available_g'] = final_state['Totale']
    updated_tank['fill_pct'] = final_state['Pct']
    
    return pd.DataFrame(trajectory), updated_tank
