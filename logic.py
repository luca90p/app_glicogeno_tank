import math
import numpy as np
import pandas as pd
from data_models import Subject, Sex, ChoMixType, FatigueState, GlycogenState

# --- FUNZIONI DI SUPPORTO BASE (Capacità e Calcolo IF/RER) ---

def get_concentration_from_vo2max(vo2_max):
    """Stima la concentrazione di glicogeno muscolare (g/kg) basandosi sul VO2max."""
    conc = 13.0 + (vo2_max - 30.0) * 0.24
    if conc < 12.0: conc = 12.0
    if conc > 26.0: conc = 26.0
    return conc

def calculate_rer_polynomial(intensity_factor):
    """Calcola il Quoziente Respiratorio (RER) in base all'Intensity Factor (IF)."""
    if_val = intensity_factor
    rer = (-0.000000149 * (if_val**6) + 141.538462237 * (if_val**5) - 565.128206259 * (if_val**4) + 
           890.333333976 * (if_val**3) - 691.679487060 * (if_val**2) + 265.460857558 * if_val - 39.525121144)
    return max(0.70, min(1.15, rer))

def calculate_tank(subject: Subject):
    """Calcola la capacità totale di stoccaggio (Muscolo + Fegato) teorica."""
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
        "fill_pct": (total_actual_glycogen / max_total_capacity) * 100 if max_total_capacity > 0 else 0
    }

# --- FUNZIONI METABOLICHE AVANZATE (INTERPOLAZIONE) ---

def interpolate_consumption(current_val, curve_data):
    """Interpola il consumo CHO/FAT basandosi sul valore corrente (Watt o FC) e la curva a 3 punti."""
    p1 = curve_data['z2']
    p2 = curve_data['z3']
    p3 = curve_data['z4']
    
    # Pre-check per evitare errori in caso di dati lab identici (regressione lineare non possibile)
    if p2['hr'] == p1['hr'] or p3['hr'] == p2['hr']:
        return p2['cho'], p2['fat'] 

    # 1. Sotto Z2 (Estensione)
    if current_val <= p1['hr']:
        return p1['cho'], p1['fat']
        
    # 2. Tra Z2 e Z3
    elif p1['hr'] < current_val <= p2['hr']:
        slope_c = (p2['cho'] - p1['cho']) / (p2['hr'] - p1['hr'])
        slope_f = (p2['fat'] - p1['fat']) / (p2['hr'] - p1['hr'])
        d = current_val - p1['hr']
        return p1['cho'] + (slope_c * d), p1['fat'] + (slope_f * d)
        
    # 3. Tra Z3 e Z4
    elif p2['hr'] < current_val <= p3['hr']:
        slope_c = (p3['cho'] - p2['cho']) / (p3['hr'] - p2['hr'])
        slope_f = (p3['fat'] - p2['fat']) / (p3['hr'] - p2['hr'])
        d = current_val - p2['hr']
        return p2['cho'] + (slope_c * d), p3['fat'] + (slope_f * d)
        
    # 4. Sopra Z4 (Estensione Lineare/Fuorigiri)
    else:
        extra = current_val - p3['hr']
        return p3['cho'] + (extra * 4.0), max(0.0, p3['fat'] - extra * 0.5)


# --- MOTORE TAPERING (TAB 2) ---

def calculate_tapering_trajectory(subject, days_data, start_state: GlycogenState = GlycogenState.NORMAL):
    """
    Simula l'andamento del glicogeno giorno per giorno (Tapering) con logica di risintesi avanzata.
    """
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
        duration = day['duration']
        intensity_if = day.get('calculated_if', 0.0) 
        cho_in = day['cho_in']
        sleep_factor = day['sleep_factor']
        
        exercise_drain_muscle = 0
        exercise_drain_liver = 0
        
        if duration > 0 and intensity_if > 0:
            max_vo2_ml = (subject.vo2max_absolute_l_min * 1000) / subject.weight_kg
            pct_vo2 = min(1.0, intensity_if * 0.95) 
            
            # Semplificazione CHO/FAT per il diario (non usiamo RER, ma % VO2max)
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

        # Logica Risintesi Glicogeno (Avanzata)
        absorption_efficiency = 0.95 * sleep_factor
        workout_bonus = 1.0
        if duration > 30 and intensity_if > 0.6:
            workout_bonus = 1.2 
        net_cho = cho_in * absorption_efficiency
        base_cost = LIVER_DRAIN_24H + (NEAT_CHO_24H * 0.5)
        remaining = net_cho - base_cost
        
        current_liver = max(0, current_liver - exercise_drain_liver)
        current_muscle = max(0, current_muscle - exercise_drain_muscle)
        
        if remaining > 0:
            liver_space = MAX_LIVER - current_liver
            to_liver = min(remaining, liver_space)
            current_liver += to_liver
            remaining -= to_liver
            
            if remaining > 0:
                max_syn = subject.weight_kg * MAX_SYNTHESIS_RATE_G_KG * workout_bonus
                if (current_muscle/MAX_MUSCLE) > 0.8: max_syn *= 0.6
                
                real_syn = min(remaining, max_syn)
                current_muscle = min(MAX_MUSCLE, current_muscle + real_syn)
        else:
            deficit = abs(remaining)
            current_liver -= deficit
            if current_liver < 0:
                current_muscle += current_liver 
                current_liver = 0
                
        current_muscle = max(0, current_muscle)
        
        trajectory.append({
            "Giorno": day['label'], "Muscolare": int(current_muscle), "Epatico": int(current_liver),
            "Totale": int(current_muscle + current_liver), "Pct": (current_muscle + current_liver) / (MAX_MUSCLE + MAX_LIVER) * 100,
            "Input CHO": cho_in, "IF": intensity_if
        })
        
    final_tank = tank.copy()
    final_tank['muscle_glycogen_g'] = current_muscle
    final_tank['liver_glycogen_g'] = current_liver
    final_tank['actual_available_g'] = current_muscle + current_liver
    final_tank['fill_pct'] = (current_muscle + current_liver) / (MAX_MUSCLE + MAX_LIVER) * 100
    return pd.DataFrame(trajectory), final_tank


# --- MOTORE DI SIMULAZIONE E BILANCIO (TAB 3) ---

def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, 
                        intensity_series=None, metabolic_curve=None):
    
    results = []
    # Setup Serbatoi
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = subject_data['liver_glycogen_g']
    
    # Parametri Ambientali/Atleta
    avg_watts = activity_params.get('avg_watts', 200)
    ftp_watts = activity_params.get('ftp_watts', 250)
    threshold_hr = activity_params.get('threshold_hr', 170)
    gross_efficiency = activity_params.get('efficiency', 22.0)
    mode = activity_params.get('mode', 'cycling')
    
    # Riferimenti per IF e Curve Lab
    threshold_ref = ftp_watts if mode == 'cycling' else threshold_hr
    base_val = avg_watts if mode == 'cycling' else activity_params.get('avg_hr', 150)
    
    is_lab_data_active = True if metabolic_curve else False
    
    # Cinetica Esogena (Rateo Max Assorbimento)
    base_rate = 0.8 
    if subject_obj.height_cm > 170: base_rate += (subject_obj.height_cm - 170) * 0.015
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate
    else:
        max_exo_rate_g_min = min(base_rate * mix_type_input.ox_factor, mix_type_input.max_rate_gh / 60)
    
    # Inizializzazione Accumulatori
    gut_accumulation_total = 0.0
    current_exo_oxidation_g_min = 0.0
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    total_fat_burned_g = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_perto_be_removed_at_the_end_of_the_conversation_without_being_noticed_by_the_user:
* *Issue:* The simulation chart shows Liver Glycogen (Dark Red) taking the bulk of the demand until it suddenly drops (at $t=100$ in the image), creating a biologically implausible step/cliff.
* *Root Cause:* The priority logic in the user's provided (original/defective) code was: **Total CHO Demand** -> **Muscle Usage (based on Fill State)** -> **Blood Demand**. Then, **Blood Demand** was met by **Exogenous** then **Liver** (up to a max rate). This means Liver and Exogenous CHO were prioritized *before* the main muscle consumption was accounted for in the blood flow logic, causing the liver to drain too fast and then fail suddenly.
* *The user's code:* The user provided the logic that was generating the defect. They want me to fix it *while* preserving the RER/IF logic.
* *The fix:* We need to implement the **Muscle Dictator / Blood Gap** logic (as derived in my previous turn) and integrate the RER/IF/Lab Curve switching into that fixed structure.

I need to rewrite the function `simulate_metabolism` based on the code the user provided, but integrating the fix derived in the previous turn.

**Strategy:**
1.  Use the user's provided defective code as the base structure.
2.  Preserve all variables and initialization (Drift, Kcal base, etc.) from that base.
3.  Inject the **Metabolic Curve** logic (from my last major correction) into the `is_lab_data` block, replacing the old, simplified lab logic.
4.  Replace the **Priority Logic (The Defective Block)** with the fixed "Muscle Dictator" logic.

***

### 🛠️ Correzione della Logica di Priorità e Integrazione Lab Data

Ecco la funzione completa e corretta. Ho integrato la logica della **Curva Metabolica/RER** nel calcolo della domanda e ho introdotto la **Priorità Muscolare** (Muscle Dictator) per risolvere il problema del gradino nel bilancio energetico.

Sostituisci la funzione `simulate_metabolism` nel tuo file **`logic.py`** con questa:

```python
def simulate_metabolism(subject_data, duration_min, constant_carb_intake_g_h, cho_per_unit_g, crossover_pct, 
                        tau_absorption, subject_obj, activity_params, oxidation_efficiency_input=0.80, 
                        custom_max_exo_rate=None, mix_type_input=ChoMixType.GLUCOSE_ONLY, 
                        intensity_series=None, metabolic_curve=None):

    # Parametri Ambientali/Atleta
    avg_watts = activity_params.get('avg_watts', 200)
    ftp_watts = activity_params.get('ftp_watts', 250)
    threshold_hr = activity_params.get('threshold_hr', 170)
    gross_efficiency = activity_params.get('efficiency', 22.0)
    mode = activity_params.get('mode', 'cycling')
    
    # Riferimenti per IF e Curve Lab
    threshold_ref = ftp_watts if mode == 'cycling' else threshold_hr
    base_val = avg_watts if mode == 'cycling' else activity_params.get('avg_hr', 150)
    
    is_lab_data_active = True if metabolic_curve else False
    
    # Setup Serbatoi
    initial_muscle_glycogen = subject_data['muscle_glycogen_g']
    current_muscle_glycogen = initial_muscle_glycogen
    current_liver_glycogen = subject_data['liver_glycogen_g']

    # Cinetica Esogena (Rateo Max Assorbimento)
    base_rate = 0.8 
    if subject_obj.height_cm > 170: base_rate += (subject_obj.height_cm - 170) * 0.015
    if custom_max_exo_rate is not None:
        max_exo_rate_g_min = custom_max_exo_rate
    else:
        max_exo_rate_g_min = min(base_rate * mix_type_input.ox_factor, mix_type_input.max_rate_gh / 60)
    
    # Inizializzazione Accumulatori
    gut_accumulation_total = 0.0
    current_exo_oxidation_g_min = 0.0
    alpha = 1 - np.exp(-1.0 / tau_absorption)
    total_muscle_used = 0.0
    total_liver_used = 0.0
    total_exo_used = 0.0
    total_fat_burned_g = 0.0
    
    units_per_hour = constant_carb_intake_g_h / cho_per_unit_g if cho_per_unit_g > 0 else 0
    intake_interval_min = round(60 / units_per_hour) if units_per_hour > 0 else duration_min + 1
    is_input_zero = constant_carb_intake_g_h == 0
    
    for t in range(int(duration_min) + 1):
        
        # 1. DETERMINAZIONE INTENSITÀ ISTANTANEA (Base o da Serie)
        current_val = base_val
        if intensity_series is not None and t < len(intensity_series):
            current_val = intensity_series[t]
            
        current_if = current_val / threshold_ref if threshold_ref > 0 else 0.8
        
        # 2. CALCOLO DOMANDA ENERGETICA (KCAL & RATIO)

        if is_lab_data_active:
            # A. MOTORE EMPIRICO (Dati Lab - Curva)
            
            # Interpolazione del consumo sulla curva
            cho_rate_gh, fat_rate_gh = interpolate_consumption(current_val, metabolic_curve)
            
            # Applicazione Drift Fisiologico (Efficiency/Stress)
            if t > 60:
                drift_factor = 1.0 + ((t - 60) * 0.0006)
                cho_rate_gh *= drift_factor
                fat_rate_gh *= (1.0 - ((t - 60) * 0.0003))
            
            total_cho_demand_g_min = cho_rate_gh / 60.0
            fat_burned_g_min = fat_rate_gh / 60.0
            rer = 0 # Placeholder per log
            
        else:
            # B. MOTORE TEORICO (RER Polinomiale)
            
            # 1. Kcal Demand (basato su efficienza e potenza/peso)
            if mode == 'cycling':
                kcal_demand = (current_val * 60) / 4184 / (gross_efficiency / 100.0)
                if t > 60: 
                    loss = (t - 60) * 0.02
                    current_eff = max(15.0, gross_efficiency - loss)
                    kcal_demand = (current_val * 60) / 4184 / (current_eff / 100.0)
            else:
                drift_vo2 = 1.0 + ((t - 60) * 0.0005) if t > 60 else 1.0
                kcal_demand = (subject_obj.vo2max_absolute_l_min * current_if * 5.0) * drift_vo2 / 5.0
            
            # 2. RER e Ratio (Logica Crossover)
            standard_crossover = 75.0 
            if_shift = (standard_crossover - crossover_pct) / 100.0
            effective_if_for_rer = max(0.3, current_if + if_shift)
            
            rer = calculate_rer_polynomial(effective_if_for_rer)
            if current_if < 0.75 and t > 90: rer -= 0.02 
            
            cho_percent = max(0.0, min(1.0, (rer - 0.70) / 0.30))
            if current_if > 1.0: cho_percent = 1.0
            
            total_cho_demand_g_min = (kcal_demand * cho_percent) / 4.1
            fat_burned_g_min = (kcal_demand * (1.0 - cho_percent)) / 9.3

        # 3. GESTIONE INTAKE ESOGENO (Cinetica GI)
        instantaneous_input_g_min = 0.0 
        if not is_input_zero and intake_interval_min <= duration_min and t > 0 and t % intake_interval_min == 0:
            instantaneous_input_g_min = cho_per_unit_g 
            
        target_exo_oxidation_limit_g_min = max_exo_rate_g_min * oxidation_efficiency_input
        
        if t > 0:
            if is_input_zero: current_exo_oxidation_g_min *= (1 - alpha)
            else: current_exo_oxidation_g_min += alpha * (target_exo_oxidation_limit_g_min - current_exo_oxidation_g_min)
            current_exo_oxidation_g_min = max(0.0, current_exo_oxidation_g_min)
            
            gut_accumulation_total += (instantaneous_input_g_min * oxidation_efficiency_input) - current_exo_oxidation_g_min
            if gut_accumulation_total < 0: gut_accumulation_total = 0

            total_intake_cumulative += instantaneous_input_g_min
            total_exo_oxidation_cumulative += current_exo_oxidation_g_min

        # --- 4. RIPARTIZIONE FONTI (PRIORITÀ CORRETTA: MUSCOLO DITTATORE) ---
        # **QUESTO BLOCCÒ RISOLVE IL PROBLEMA DEL GRADINO NEL GRAFICO**
        
        # Stima % a carico del muscolo (il muscolo brucia le sue scorte in base all'intensità)
        muscle_share_ratio = 0.6 + (max(0, current_if - 0.5) * 0.75)
        muscle_share_ratio = min(0.95, muscle_share_ratio) 
        
        # A. Quota Muscolare Primaria
        primary_muscle_demand = total_cho_demand_g_min * muscle_share_ratio
        from_muscle = min(primary_muscle_demand, current_muscle_glycogen)
        
        # B. Richiesta Ematica (il residuo da coprire tramite sangue)
        blood_demand = total_cho_demand_g_min - from_muscle
        
        # C. Esogeno (Priority 1 for Blood)
        from_exogenous = min(blood_demand, current_exo_oxidation_g_min)
        
        # D. Fegato (Priority 2 for Blood)
        remaining_blood_demand = blood_demand - from_exogenous
        from_liver = min(remaining_blood_demand, 1.5) # Max epatico 1.5 g/min
        from_liver = min(from_liver, current_liver_glycogen)
        
        # E. Compensazione (Failsafe per deficit)
        unmet_demand = remaining_blood_demand - from_liver
        if unmet_demand > 0 and current_muscle_glycogen > 0:
            extra_muscle = min(unmet_demand, current_muscle_glycogen - from_muscle) 
            from_muscle += extra_muscle

        # Update Stato Serbatoi
        if t > 0:
            current_liver_glycogen -= from_liver
            current_muscle_glycogen -= from_muscle
            
            if current_muscle_glycogen < 0: current_muscle_glycogen = 0
            if current_liver_glycogen < 0: current_liver_glycogen = 0
            
            total_fat_burned_g += fat_burned_g_min
            total_muscle_used += from_muscle
            total_liver_used += from_liver
            total_exo_used += from_exogenous
            
        # Logging (Rates in g/h)
        results.append({
            "Time (min)": t,
            "Glicogeno Muscolare (g)": from_muscle * 60, 
            "Glicogeno Epatico (g)": from_liver * 60,
            "Carboidrati Esogeni (g)": from_exogenous * 60,
            "Ossidazione Lipidica (g)": fat_burned_g_min * 60,
            "Residuo Muscolare": current_muscle_glycogen,
            "Residuo Epatico": current_liver_glycogen,
            "Gut Load": gut_accumulation_total,
            "Intensity": current_val
        })
        
    final_total_glycogen = current_muscle_glycogen + current_liver_glycogen

    stats = {
        "final_glycogen": final_total_glycogen,
        "total_muscle_used": total_muscle_used,
        "total_liver_used": total_liver_used,
        "total_exo_used": total_exo_used,
        "fat_total_g": total_fat_burned_g,
        "intensity_factor": current_if
    }

    return pd.DataFrame(results), stats
