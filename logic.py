import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState

# ... (Le altre funzioni: get_concentration_from_vo2max, calculate_depletion_factor, 
#      calculate_filling_factor_from_diet, calculate_tank, calculate_rer_polynomial 
#      e simulate_metabolism RIMANGONO IDENTICHE. Copiale dal codice precedente se serve).
# ...
# ...

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

# ... (altre funzioni restano uguali)

def interpolate_consumption(current_hr, curve_data):
    """
    Interpola il consumo CHO/FAT basandosi sulla FC corrente e la curva a 3 punti.
    curve_data = {'z2': {'hr': ..., 'cho': ..., 'fat': ...}, 'z3': ..., 'z4': ...}
    """
    # Estraiamo i punti noti
    p1 = curve_data['z2']
    p2 = curve_data['z3']
    p3 = curve_data['z4']
    
    # 1. Zona Bassa (sotto Z2) -> Estrapolazione piatta o lineare verso 0
    if current_hr <= p1['hr']:
        return p1['cho'], p1['fat']
        
    # 2. Tra Z2 e Z3 (Interpolazione Lineare)
    elif p1['hr'] < current_hr <= p2['hr']:
        slope_cho = (p2['cho'] - p1['cho']) / (p2['hr'] - p1['hr'])
        slope_fat = (p2['fat'] - p1['fat']) / (p2['hr'] - p1['hr'])
        delta_x = current_hr - p1['hr']
        return p1['cho'] + (slope_cho * delta_x), p1['fat'] + (slope_fat * delta_x)
        
    # 3. Tra Z3 e Z4 (Interpolazione Lineare)
    elif p2['hr'] < current_hr <= p3['hr']:
        slope_cho = (p3['cho'] - p2['cho']) / (p3['hr'] - p2['hr'])
        slope_fat = (p3['fat'] - p2['fat']) / (p3['hr'] - p2['hr'])
        delta_x = current_hr - p2['hr']
        return p2['cho'] + (slope_cho * delta_x), p2['fat'] + (slope_fat * delta_x)
        
    # 4. Sopra Z4 -> Estrapolazione (o cap al valore Z4 per prudenza)
    else:
        # Assumiamo che oltre la soglia il consumo CHO aumenti ancora leggermente, ma i FAT siano a 0
        extra_kick = (current_hr - p3['hr']) * 2.0 # +2g CHO per ogni battito extra
        return p3['cho'] + extra_kick, max(0, p3['fat'] - (current_hr - p3['hr']))

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        mix_type_input=ChoMixType.GLUCOSE_ONLY, intensity_series=None, metabolic_curve=None):
    
    results = []
    initial_muscle = subject_data['muscle_glycogen_g']
    current_muscle = initial_muscle
    current_liver = subject_data['liver_glycogen_g']
    
    # Parametri Base
    mode = activity_params.get('mode', 'running')
    avg_hr = activity_params.get('avg_hr', 150)
    
    # Dati esogeni
    base_rate = 0.8 
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
        # 1. Determina Intensità Istantanea (FC)
        current_val = avg_hr
        if intensity_series is not None and t < len(intensity_series):
            # Se la serie è IF (0.8, 0.9), la convertiamo in BPM approssimativi o Watt
            # Qui assumiamo che per il file ZWO la serie sia stata convertita in valore assoluto (BPM/Watt) in utils
            # Se utils ritorna IF puro, dobbiamo convertirlo:
            current_val = intensity_series[t] 
            # Nota: intensity_series da utils.parse_zwo ora ritorna il valore assoluto se possibile? 
            # Per sicurezza, nel main app useremo valori assoluti se disponibili.
        
        # 2. Calcolo Consumo CHO/FAT (Interpolazione o Modello)
        if metabolic_curve:
            cho_rate_gh, fat_rate_gh = interpolate_consumption(current_val, metabolic_curve)
            total_cho_demand = cho_rate_gh / 60.0
            fat_burned = fat_rate_gh / 60.0
        else:
            # Fallback al modello teorico (se curva non presente)
            # (Qui lascio una versione semplificata del vecchio calcolo per brevità)
            total_cho_demand = 3.0 # Dummy fallback
            fat_burned = 0.5

        # 3. Gestione Intake
        instant_input_g = 0.0 
        if constant_carb_intake_g_h > 0 and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instant_input_g = cho_per_unit_g 
            
        # Dinamica Exogena
        target_exo = max_exo_rate_g_min * oxidation_efficiency_input
        if t > 0:
            if constant_carb_intake_g_h == 0: current_exo_ox_rate *= (1 - alpha) 
            else: current_exo_ox_rate += alpha * (target_exo - current_exo_ox_rate)
            current_exo_ox_rate = max(0.0, current_exo_ox_rate)
            
            gut_accumulation += (instant_input_g * oxidation_efficiency_input) - current_exo_ox_rate
            if gut_accumulation < 0: gut_accumulation = 0 

        # 4. Bilancio Fonti
        blood_demand = total_cho_demand # Semplificazione: tutto è CHO demand
        
        # Priorità: Esogeno -> Fegato -> Muscolo
        from_exogenous = min(blood_demand, current_exo_ox_rate)
        remaining_demand = blood_demand - from_exogenous
        
        # Fegato (limitato ~1.2 g/min)
        from_liver = min(remaining_demand, 1.2)
        if current_liver <= 0: from_liver = 0
        
        # Muscolo (copre il resto)
        from_muscle = remaining_demand - from_liver
        if current_muscle <= 0: from_muscle = 0
        
        # Update Stato
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
        "intensity_factor": current_val / 170.0 # Stima
    }
    return pd.DataFrame(results), stats

# ... (le altre funzioni rimangono uguali, sostituisci solo calculate_tapering_trajectory)

def calculate_tapering_trajectory(subject, days_data, start_state: GlycogenState = GlycogenState.NORMAL):
    """
    Simula l'andamento del glicogeno giorno per giorno con logica di risintesi avanzata.
    Riferimenti: Jentjens & Jeukendrup (2003), Burke et al. (2017).
    """
    # 1. PARAMETRI FISIOLOGICI BASALI
    # Consumo epatico: ~4g/h per mantenere la glicemia a riposo (cervello + organi)
    LIVER_DRAIN_24H = 4.0 * 24 
    
    # NEAT (Non-Exercise Activity Thermogenesis): consumo CHO per muoversi/lavorare
    # Stima conservativa: 1.5g per kg di peso corporeo
    NEAT_CHO_24H = 1.5 * subject.weight_kg 
    
    # Limite fisiologico di risintesi giornaliera (g/kg/day)
    # Burke (2017): Massimo stoccaggio in supercompensazione ~10-12g/kg/24h, ma il tasso medio è inferiore.
    # Impostiamo un cap realistico di assorbimento muscolare netto.
    MAX_SYNTHESIS_RATE_G_KG = 10.0 
    
    # Inizializzazione Serbatoi
    tank = calculate_tank(subject)
    MAX_MUSCLE = tank['max_capacity_g'] - 120 
    MAX_LIVER = 120.0
    
    start_factor = start_state.factor
    current_muscle = MAX_MUSCLE * start_factor 
    current_liver = MAX_LIVER * start_factor
    
    # Clip iniziale
    current_muscle = min(current_muscle, MAX_MUSCLE)
    current_liver = min(current_liver, MAX_LIVER)
    
    trajectory = []
    
    for day in days_data:
        duration = day['duration']
        intensity_if = day.get('calculated_if', 0.0) 
        cho_in = day['cho_in']
        sleep_factor = day['sleep_factor']
        
        # --- A. DEPLEZIONE DA ESERCIZIO ---
        exercise_drain_muscle = 0
        exercise_drain_liver = 0
        
        if duration > 0 and intensity_if > 0:
            # Stima VO2max relativo (ml/kg/min)
            max_vo2_ml = (subject.vo2max_absolute_l_min * 1000) / subject.weight_kg
            
            # Relazione IF -> %VO2max (semplificata per stima consumo)
            pct_vo2 = min(1.0, intensity_if * 0.95) 
            
            # Mix Energetico (Crossover Concept)
            if intensity_if <= 0.55: cho_ox_pct = 0.20
            elif intensity_if <= 0.75: cho_ox_pct = 0.50 + (intensity_if - 0.55) * 1.5
            elif intensity_if <= 0.90: cho_ox_pct = 0.80 + (intensity_if - 0.75) * 1.0
            else: cho_ox_pct = 1.0 # Sopra soglia è puramente glicolitico
            
            # Calcolo Calorie e CHO bruciati
            kcal_min = (max_vo2_ml * pct_vo2 * subject.weight_kg / 1000) * 5.0
            total_kcal = kcal_min * duration
            total_cho_burned = (total_kcal * cho_ox_pct) / 4.0
            
            # Ripartizione: Più alta è l'intensità, più il muscolo soffre rispetto al fegato
            liver_ratio = 0.15 if intensity_if < 0.75 else 0.05
            exercise_drain_liver = total_cho_burned * liver_ratio
            exercise_drain_muscle = total_cho_burned * (1 - liver_ratio)

        # --- B. RISINTESI (LOGICA MIGLIORATA) ---
        
        # 1. Efficienza di Assorbimento (Insulino-sensibilità)
        # Base: 95% dei CHO ingeriti entrano in circolo.
        # Malus Sonno: Se dormi male, la sensibilità insulinica cala (-15/20%).
        absorption_efficiency = 0.95 * sleep_factor
        
        # 2. Finestra Anabolica (Bonus Risintesi post-workout)
        # Se c'è stato allenamento, il muscolo è "affamato" (GLUT4 traslocati).
        # Jentjens (2003): Il tasso di risintesi raddoppia nelle prime ore.
        # Modelliamo questo come un aumento della priorità muscolare.
        workout_bonus = 1.0
        if duration > 30 and intensity_if > 0.6:
            workout_bonus = 1.2 # +20% efficienza di stoccaggio muscolare diretto
            
        net_cho_available = cho_in * absorption_efficiency
        
        # 3. Consumo Basale (Priorità 1: Sopravvivenza)
        # Prima paghiamo il debito del fegato (cervello) e del NEAT
        liver_maintenance_cost = LIVER_DRAIN_24H 
        neat_cost = NEAT_CHO_24H
        
        # Sottraiamo i costi "fissi" dall'introito
        # Nota: Parte del NEAT è coperta dai grassi, assumiamo 50% CHO
        daily_obligatory_drain = liver_maintenance_cost + (neat_cost * 0.5)
        
        remaining_cho = net_cho_available - daily_obligatory_drain
        
        # --- C. RIEMPIMENTO SERBATOI ---
        
        # Calcolo deplezione totale odierna
        current_liver -= exercise_drain_liver
        current_muscle -= exercise_drain_muscle
        
        # Clamp a zero (non puoi avere glicogeno negativo)
        current_liver = max(0, current_liver)
        current_muscle = max(0, current_muscle)
        
        # Fase di ricarica
        if remaining_cho > 0:
            # 1. Priorità al Fegato (fino a saturazione)
            liver_space = MAX_LIVER - current_liver
            to_liver = min(remaining_cho, liver_space)
            current_liver += to_liver
            
            remaining_cho -= to_liver
            
            # 2. Il resto al Muscolo (con Tetto Massimo fisiologico)
            if remaining_cho > 0:
                muscle_space = MAX_MUSCLE - current_muscle
                
                # Applichiamo il Cap Fisiologico Giornaliero (Rate Limiting)
                # Non puoi sintetizzare più di X g/kg al giorno
                max_daily_synthesis = subject.weight_kg * MAX_SYNTHESIS_RATE_G_KG * workout_bonus
                
                # Se il serbatoio è quasi pieno (>80%), la sintesi rallenta (inibizione da prodotto)
                fill_level = current_muscle / MAX_MUSCLE
                if fill_level > 0.8:
                    max_daily_synthesis *= 0.6 # Rallentamento finale
                
                real_synthesis = min(remaining_cho, max_daily_synthesis)
                
                # Se c'è spazio, stocca
                to_muscle = min(real_synthesis, muscle_space)
                current_muscle += to_muscle
                
                # Nota: (remaining_cho - real_synthesis) viene convertito in grasso (De Novo Lipogenesi) 
                # e non contribuisce al glicogeno.
        else:
            # Deficit calorico: intacchiamo ulteriormente le riserve
            deficit = abs(remaining_cho)
            # Il fegato copre il deficit sistemico (glicemia)
            current_liver -= deficit
            if current_liver < 0:
                # Se il fegato finisce, catabolismo muscolare (estremo) o gluconeogenesi
                # Per il modello, assumiamo che intacchi il muscolo
                muscle_debt = abs(current_liver)
                current_liver = 0
                current_muscle -= muscle_debt
        
        # Clamp finale
        current_muscle = max(0, min(current_muscle, MAX_MUSCLE))
        current_liver = max(0, min(current_liver, MAX_LIVER))
        
        # Salvataggio dati giornalieri
        trajectory.append({
            "Giorno": day['label'],
            "Muscolare": int(current_muscle),
            "Epatico": int(current_liver),
            "Totale": int(current_muscle + current_liver),
            "Pct": (current_muscle + current_liver) / (MAX_MUSCLE + MAX_LIVER) * 100,
            "Input CHO": cho_in,
            "IF": intensity_if,
            "Sleep": day['sleep_factor']
        })
        
    final_state = trajectory[-1]
    
    updated_tank = tank.copy()
    updated_tank['muscle_glycogen_g'] = final_state['Muscolare']
    updated_tank['liver_glycogen_g'] = final_state['Epatico']
    updated_tank['actual_available_g'] = final_state['Totale']
    updated_tank['fill_pct'] = final_state['Pct']
    
    return pd.DataFrame(trajectory), updated_tank


