import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType

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

def calculate_filling_factor_from_diet(weight_kg, cho_day_minus_1_g, cho_day_minus_2_g, s_fatigue, s_sleep, steps_m1, min_act_m1, steps_m2, min_act_m2):
    CHO_BASE_GK = 5.0
    CHO_MAX_GK = 10.0
    CHO_MIN_GK = 2.5
    
    cho_day_minus_1_g = max(cho_day_minus_1_g, 1.0) 
    cho_day_minus_2_g = max(cho_day_minus_2_g, 1.0) 
    
    cho_day_minus_1_gk = cho_day_minus_1_g / weight_kg
    cho_day_minus_2_gk = cho_day_minus_2_g / weight_kg
    
    depletion_m1_factor = calculate_depletion_factor(steps_m1, min_act_m1, s_fatigue)
    depletion_m2_factor = calculate_depletion_factor(steps_m2, min_act_m2, s_fatigue)
    
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
    combined_filling = final_diet_depletion_factor * s_sleep.factor
    
    return combined_filling, final_diet_depletion_factor, avg_cho_gk, cho_day_minus_1_gk, cho_day_minus_2_gk

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

def estimate_max_exogenous_oxidation(height_cm, weight_kg, ftp_watts, mix_type: ChoMixType):
    base_rate = 0.8 
    if height_cm > 170: base_rate += (height_cm - 170) * 0.015
    if ftp_watts > 200: base_rate += (ftp_watts - 200) * 0.0015
    ox_factor = mix_type.ox_factor
    max_rate_gh = mix_type.max_rate_gh
    estimated_rate_gh = base_rate * 60 * ox_factor
    final_rate_g_min = min(estimated_rate_gh / 60, max_rate_gh / 60)
    return final_rate_g_min

def calculate_rer_polynomial(intensity_factor):
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.67948706 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, intensity_series=None):
    
    results = []
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = subject_data['liver_glycogen_g']
    
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
    
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate 
    else:
        max_exo_rate_g_min = estimate_max_exogenous_oxidation(subject_obj.height_cm, subject_obj.weight_kg, ftp_watts, mix_type_input)
    
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
        if intensity_series is not None and t < len(intensity_series):
            current_intensity_factor = intensity_series[t]
        
        current_kcal_demand = 0.0
        if mode == 'cycling':
            instant_power = current_intensity_factor * ftp_watts
            current_eff = gross_efficiency
            if t > 60: current_eff = max(15.0, gross_efficiency - ((t - 60) * 0.02))
            current_kcal_demand = (instant_power * 60) / 4184 / (current_eff / 100.0)
        else: 
            demand_scaling = current_intensity_factor / intensity_factor_reference if intensity_factor_reference > 0 else 1.0
            drift_factor = 1.0 + ((t - 60) * 0.0005) if t > 60 else 1.0
            current_kcal_demand = kcal_per_min_base * drift_factor * demand_scaling
        
        instantaneous_input_g_min = 0.0 
        if not is_input_zero and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instantaneous_input_g_min = cho_per_unit_g 
        
        target_exo_oxidation_limit_g_min = max_exo_rate_g_min * oxidation_efficiency_input
        
        if t > 0:
            if is_input_zero: current_exo_oxidation_g_min *= (1 - alpha) 
            else: current_exo_oxidation_g_min += alpha * (target_exo_oxidation_limit_g_min - current_exo_oxidation_g_min)
            if current_exo_oxidation_g_min < 0: current_exo_oxidation_g_min = 0.0
        
        if t > 0:
            gut_accumulation_total += (instantaneous_input_g_min * oxidation_efficiency_input) - current_exo_oxidation_g_min
            if gut_accumulation_total < 0: gut_accumulation_total = 0 
            total_intake_cumulative += instantaneous_input_g_min 
            total_exo_oxidation_cumulative += current_exo_oxidation_g_min
        
        rer = 0.85
        if is_lab_data:
            fatigue_mult = 1.0 + ((t - 30) * 0.0005) if t > 30 else 1.0 
            total_cho_demand = lab_cho_rate * fatigue_mult 
            kcal_cho_demand = total_cho_demand * 4.1
            cho_ratio = total_cho_demand / (total_cho_demand + (lab_fat_rate/60)) if (total_cho_demand + lab_fat_rate) > 0 else 0
        else:
            effective_if_for_rer = max(0.3, current_intensity_factor + ((75.0 - crossover_pct) / 100.0))
            rer = calculate_rer_polynomial(effective_if_for_rer)
            base_cho_ratio = max(0.0, min(1.0, (rer - 0.70) * 3.45))
            current_cho_ratio = base_cho_ratio
            if current_intensity_factor < 0.85 and t > 60:
                current_cho_ratio = max(0.05, base_cho_ratio - (0.05 * (((t - 60) / 60.0) ** 1.2)))
            cho_ratio = current_cho_ratio
            kcal_cho_demand = current_kcal_demand * cho_ratio
        
        total_cho_g_min = kcal_cho_demand / 4.1
        muscle_fill_state = current_muscle_glycogen / initial_muscle_glycogen if initial_muscle_glycogen > 0 else 0
        muscle_contribution_factor = math.pow(muscle_fill_state, 0.6) 
        muscle_usage_g_min = total_cho_g_min * muscle_contribution_factor
        if current_muscle_glycogen <= 0: muscle_usage_g_min = 0
        
        blood_glucose_demand_g_min = total_cho_g_min - muscle_usage_g_min
        from_exogenous = min(blood_glucose_demand_g_min, current_exo_oxidation_g_min)
        from_liver = min(blood_glucose_demand_g_min - from_exogenous, 1.2)
        if current_liver_glycogen <= 0: from_liver = 0
        
        if t > 0:
            current_muscle_glycogen = max(0, current_muscle_glycogen - muscle_usage_g_min)
            current_liver_glycogen = max(0, current_liver_glycogen - from_liver)
            
            if not is_lab_data:
                total_fat_burned_g += (current_kcal_demand * (1.0 - cho_ratio)) / 9.0
            else:
                total_fat_burned_g += lab_fat_rate
            
            total_muscle_used += muscle_usage_g_min
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        status_label = "Ottimale"
        if current_liver_glycogen < 20: status_label = "CRITICO (Ipoglicemia)"
        elif current_muscle_glycogen < 100: status_label = "Warning (Gambe Vuote)"
            
        g_fat = (current_kcal_demand * (1.0 - cho_ratio) / 9.0) if not is_lab_data else lab_fat_rate/60
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
            "Gut Load": gut_accumulation_total,
            "Stato": status_label,
            "CHO %": cho_ratio * 100,
            "Intake Cumulativo (g)": total_intake_cumulative,
            "Ossidazione Cumulativa (g)": total_exo_oxidation_cumulative,
            "Intensity Factor (IF)": current_intensity_factor 
        })
        
    stats = {
        "final_glycogen": current_muscle_glycogen + current_liver_glycogen, 
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "intensity_factor": intensity_factor_reference,
        "avg_rer": rer,
        "cho_pct": cho_ratio * 100
    }
    return pd.DataFrame(results), stats

def calculate_weekly_balance(initial_muscle, initial_liver, max_muscle, max_liver, weekly_schedule, subject_weight, vo2max):
    LIVER_DRAIN_RATE = 4.5 
    DAILY_NEAT_CHO = 1.2 * subject_weight
    SYNTHESIS_EFFICIENCY = 0.95
    daily_status = []
    current_muscle = initial_muscle
    current_liver = initial_liver
    
    for day_data in weekly_schedule:
        activity_type = day_data['activity']
        duration = day_data['duration']
        cho_in = day_data['cho_in']
        
        total_basal_drain = (24 * LIVER_DRAIN_RATE) + DAILY_NEAT_CHO
        exercise_drain_muscle = 0
        exercise_drain_liver = 0
        
        if activity_type != "Riposo" and duration > 0:
            intensity = day_data['intensity']
            if intensity == "Bassa (Z1-Z2)": rel_intensity, cho_pct = 0.5, 0.25 
            elif intensity == "Media (Z3)": rel_intensity, cho_pct = 0.7, 0.65 
            else: rel_intensity, cho_pct = 0.85, 0.95 
                
            kcal_min = (vo2max * rel_intensity * subject_weight / 1000) * 5.0
            total_cho_burned = (kcal_min * duration * cho_pct) / 4.0 
            exercise_drain_liver = total_cho_burned * 0.15 
            exercise_drain_muscle = total_cho_burned * 0.85
            
        effective_input = cho_in * SYNTHESIS_EFFICIENCY
        drain_liver_total = total_basal_drain + exercise_drain_liver
        
        if effective_input >= drain_liver_total:
            surplus = effective_input - drain_liver_total
            if surplus >= (max_liver - current_liver):
                current_liver = max_liver
                surplus_for_muscle = surplus - (max_liver - current_liver)
            else:
                current_liver += surplus
                surplus_for_muscle = 0
        else:
            current_liver -= (drain_liver_total - effective_input)
            surplus_for_muscle = 0 
            
        current_muscle = min(max_muscle, max(0, current_muscle - exercise_drain_muscle + surplus_for_muscle))
        current_liver = min(max_liver, max(0, current_liver))
            
        daily_status.append({
            "Giorno": day_data['day'],
            "Glicogeno Muscolare": round(current_muscle),
            "Glicogeno Epatico": round(current_liver),
            "Totale": round(current_muscle + current_liver),
            "Bilancio Netto": round(effective_input - (drain_liver_total + exercise_drain_muscle))
        })
    return pd.DataFrame(daily_status)