# ... (CODICE PRECEDENTE INVARIATO FINO A simulate_metabolism) ...

def simulate_metabolism(subject_data, ftp_watts, avg_power, duration_min, carb_intake_g_h, crossover_pct, height_cm, gross_efficiency):
    tank_g = subject_data['actual_available_g']
    results = []
    current_glycogen = tank_g
    
    # Calcolo IF Base
    base_intensity_factor = avg_power / ftp_watts if ftp_watts > 0 else 0
    
    # Adattamento Crossover
    standard_crossover_ref = 75.0 
    shift_factor = (standard_crossover_ref - crossover_pct) / 100.0
    effective_if_for_rer = base_intensity_factor + shift_factor
    if effective_if_for_rer < 0.3: effective_if_for_rer = 0.3
    
    # Target intake (teorico)
    max_exo_rate_g_min = estimate_max_exogenous_oxidation(height_cm, subject_data['active_muscle_kg']*2.2, ftp_watts)
    intake_g_min = carb_intake_g_h / 60.0
    oxidation_efficiency = 0.80 
    
    # Il target massimo che possiamo raggiungere a regime (steady state)
    target_steady_state_exo_g_min = min(intake_g_min, max_exo_rate_g_min) * oxidation_efficiency
    
    # Variabili per accumulo
    total_fat_burned_g = 0.0
    gut_accumulation_total = 0.0
    
    # Parametri Cinetica (King et al. 2018 / Podlogar 2025)
    # Time constant (tau): ~20-25 min per raggiungere il 63% del picco.
    # Raggiunge il 95% del picco in 3*tau (~60-75 min).
    tau_absorption = 20.0 
    
    for t in range(int(duration_min) + 1):
        # 1. DRIFT EFFICIENZA (Burnley & Jones 2018 - Slow Component)
        # L'efficienza cala leggermente nel tempo, aumentando il costo energetico
        # Simuliamo un calo lineare dopo i primi 30 min
        current_efficiency = gross_efficiency
        if t > 30:
            # Perdita di efficienza progressiva (es. 0.01% al minuto)
            efficiency_loss = (t - 30) * 0.02 
            current_efficiency = max(15.0, gross_efficiency - efficiency_loss)
            
        kcal_per_min_total = (avg_power * 60) / 4184 / (current_efficiency / 100.0)
        
        # 2. CINETICA OSSIDAZIONE ESOGENA (NON LINEARE)
        # Se non mangio, è 0. Se mangio, sale seguendo la curva esponenziale.
        if intake_g_min > 0 and t > 0:
            # Formula cinetica primo ordine: Rate(t) = Max * (1 - e^(-t/tau))
            # Questo simula il ritardo gastrico/assorbimento.
            # Al minuto 5: ossidiamo pochissimo. Al minuto 60: siamo a regime.
            actual_exo_oxidation_g_min = target_steady_state_exo_g_min * (1 - np.exp(-t / tau_absorption))
        else:
            actual_exo_oxidation_g_min = 0.0
            
        # Calcolo accumulo intestinale (quello che ho mangiato - quello che ho ossidato)
        # Nota: intake è costante (se l'utente lo imposta), l'ossidazione è ritardata.
        if t > 0:
            gut_accumulation_total += (intake_g_min * oxidation_efficiency) - actual_exo_oxidation_g_min
        
        # 3. BILANCIO ENERGETICO
        # RER (ricalcolato ogni step se volessimo variare IF, qui IF fisso ma costo sale)
        rer = calculate_rer_polynomial(effective_if_for_rer)
        cho_ratio = (rer - 0.70) * 3.45
        cho_ratio = max(0.0, min(1.0, cho_ratio))
        fat_ratio = 1.0 - cho_ratio
        
        kcal_cho_demand = kcal_per_min_total * cho_ratio
        
        # Energia fornita dall'esogeno (ritardato)
        kcal_from_exo = actual_exo_oxidation_g_min * 3.75
        
        # Obbligo glicogeno minimo (endogeno)
        min_glycogen_obligatory = 0.0
        if base_intensity_factor > 0.6:
            min_glycogen_obligatory = (kcal_cho_demand * 0.20) / 4.1 
            
        remaining_kcal_demand = kcal_cho_demand - kcal_from_exo
        
        glycogen_burned_per_min = remaining_kcal_demand / 4.1
        
        # Se l'esogeno copre tutto, rimane comunque il consumo minimo obbligatorio
        if glycogen_burned_per_min < min_glycogen_obligatory:
            glycogen_burned_per_min = min_glycogen_obligatory
            # L'esogeno "in più" non viene bruciato istantaneamente ma risparmiato o ossidato al posto dei grassi (qui semplificato)
        
        fat_burned_per_min = (kcal_per_min_total * fat_ratio) / 9.0
        
        if t > 0:
            current_glycogen -= glycogen_burned_per_min
            total_fat_burned_g += fat_burned_per_min
        
        if current_glycogen < 0:
            current_glycogen = 0
            
        results.append({
            "Time (min)": t,
            "Glicogeno Residuo (g)": current_glycogen,
            "Lipidi Ossidati (g)": total_fat_burned_g,
            "CHO Esogeni (g/min)": actual_exo_oxidation_g_min, # Per grafico cinetica
            "CHO %": cho_ratio * 100,
            "RER": rer
        })
        
    stats = {
        "final_glycogen": current_glycogen,
        "cho_rate_g_h": (glycogen_burned_per_min * 60) + (actual_exo_oxidation_g_min * 60),
        "endogenous_burn_rate": glycogen_burned_per_min * 60,
        "fat_rate_g_h": fat_burned_per_min * 60,
        "kcal_total_h": kcal_per_min_total * 60,
        "cho_pct": cho_ratio * 100,
        "gut_accumulation": (gut_accumulation_total / duration_min) * 60 if duration_min > 0 else 0, # Media oraria accumulo
        "max_exo_capacity": max_exo_rate_g_min * 60,
        "intensity_factor": base_intensity_factor,
        "avg_rer": rer,
        "gross_efficiency": gross_efficiency
    }

    return pd.DataFrame(results), stats

# ... (INTERFACCIA UTENTE INVARIATA FINO ALLA SEZIONE GRAFICI) ...

# SOSTITUISCI LA PARTE DEI GRAFICI NEL TAB 2 CON QUESTA:

        g1, g2 = st.columns([2, 1])
        with g1:
            st.caption("Cinetica di Deplezione Glicogeno (Non-Lineare)")
            
            max_y = max(start_tank, 800)
            
            bands = pd.DataFrame([
                {"Zone": "Critical (<180g)", "Start": 0, "End": 180, "Color": "#FFCDD2"}, 
                {"Zone": "Warning (180-350g)", "Start": 180, "End": 350, "Color": "#FFE0B2"}, 
                {"Zone": "Optimal (>350g)", "Start": 350, "End": max_y + 100, "Color": "#C8E6C9"} 
            ])
            
            base = alt.Chart(df_sim).encode(x=alt.X('Time (min)', title='Durata (min)'))

            # Linea Glicogeno
            line = base.mark_area(
                line={'color':'#D32F2F'}, 
                color=alt.Gradient(
                    gradient='linear',
                    stops=[alt.GradientStop(color='white', offset=0),
                           alt.GradientStop(color='#D32F2F', offset=1)],
                    x1=1, x2=1, y1=1, y2=0
                ),
                opacity=0.6
            ).encode(
                y=alt.Y('Glicogeno Residuo (g)', title='Glicogeno Muscolare (g)'),
                tooltip=['Time (min)', 'Glicogeno Residuo (g)']
            )
            
            # Linea Ossidazione Esogena (Sovrapposta asse destro o tooltip)
            # Per pulizia la mettiamo come linea tratteggiata che mostra il rateo di assorbimento
            # Poiché la scala è diversa (g vs g/min), è meglio fare un grafico separato sotto o un tooltip avanzato.
            # Qui manteniamo il focus sul serbatoio.
            
            zones = alt.Chart(bands).mark_rect(opacity=0.3).encode(
                y='Start',
                y2='End',
                color=alt.Color('Color', scale=None), 
                tooltip='Zone' 
            )
            
            chart = (zones + line).properties(height=300).interactive()
            st.altair_chart(chart, use_container_width=True)
            
            # NUOVO GRAFICO: CINETICA ASSORBIMENTO
            st.caption("Cinetica Ossidazione Esogena (Ritardo Gastrico)")
            exo_chart = base.mark_line(color='#1E88E5', strokeWidth=3).encode(
                y=alt.Y('CHO Esogeni (g/min)', title='Ossidazione Esogena Reale (g/min)'),
                tooltip=['Time (min)', 'CHO Esogeni (g/min)']
            ).properties(height=150)
            
            # Aggiungiamo linea target (quello che l'utente mangia)
            target_line = alt.Chart(pd.DataFrame({'y': [carb_intake/60]})).mark_rule(color='gray', strokeDash=[5,5]).encode(y='y')
            
            st.altair_chart(exo_chart + target_line, use_container_width=True)
            st.caption("*La linea tratteggiata indica l'ingestione, la linea blu l'ossidazione reale effettiva (con ritardo fisiologico).*")

        with g2:
            st.caption("Ossidazione Lipidica Cumulativa")
            st.line_chart(df_sim.set_index("Time (min)")["Lipidi Ossidati (g)"], color="#FFA500")
            
            # Aggiunta: Accumulo Intestinale
            st.caption("Accumulo Intestinale Stimato")
            # Calcoliamo accumulo cumulativo per il grafico
            # (Approssimazione visiva basata sui dati stats medi, per un grafico preciso servirebbe colonna dedicata nel DF)
            # Creiamo una colonna fittizia nel df per visualizzarlo
            df_sim['Gut Load'] = (df_sim['Time (min)'] * (carb_intake/60 * 0.8)) - df_sim['CHO Esogeni (g/min)'].cumsum()
            # Fix valori negativi iniziali o artefatti
            df_sim['Gut Load'] = df_sim['Gut Load'].clip(lower=0)
            
            st.area_chart(df_sim.set_index("Time (min)")["Gut Load"], color="#8D6E63")
            st.caption("*Carboidrati ingeriti ma non ancora ossidati (Rischio GI).*")

# ... (RESTO DEL CODICE INVARIATO) ...
