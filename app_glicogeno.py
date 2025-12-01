import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import math

# IMPORTS DAI MODULI
import logic
import utils
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject
)

# --- SETUP PAGINA ---
st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
st.title("Glycogen Simulator Pro")
st.markdown("Strumento di stima delle riserve energetiche e simulazione del metabolismo sotto sforzo.")

# --- LOGIN ---
if not utils.check_password():
    st.stop()

# --- NOTE TECNICHE ---
with st.expander("📘 Note Tecniche & Fonti Scientifiche"):
    st.info("""
    **1. Stima Riserve & Capacità di Stoccaggio**
    * Basato su correlazione VO2max/Densità Glicogeno (Burke et al., 2017).
    * Capacità Max include supercompensazione (Fattore 1.25).
    
    **2. Sviluppi Recenti**
    * **RER:** Modellazione basata su Sesso, Durata e Intensità (Rothschild et al., 2022).
    * **Rischio GI:** Basato su accumulo intestinale > soglia di tolleranza.
    """)

tab1, tab2, tab3 = st.tabs(["1. Profilo Base & Capacità", "2. Preparazione & Diario", "3. Simulazione & Strategia"])

# =============================================================================
# TAB 1: PROFILO BASE
# =============================================================================
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("1. Dati Antropometrici")
        weight = st.slider("Peso Corporeo (kg)", 45.0, 100.0, 74.0, 0.5)
        height = st.slider("Altezza (cm)", 150, 210, 187, 1)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 11.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        use_smm = st.checkbox("Usa Massa Muscolare (SMM) misurata")
        muscle_mass_input = st.number_input("SMM [kg]", 10.0, 60.0, 37.4, 0.1) if use_smm else None
        
        st.markdown("---")
        st.subheader("2. Capacità (Tank)")
        
        # Stima Concentrazione
        est_method = st.radio("Metodo:", ["Basato su Livello", "Basato su VO2max"], horizontal=True, label_visibility="collapsed")
        
        if est_method == "Basato su Livello":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello Atletico", list(status_map.keys()), index=3)]
            vo2_input = 30 + ((s_status.val - 13.0) / 0.24)
            calculated_conc = s_status.val
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, step=1)
            calculated_conc = logic.get_concentration_from_vo2max(vo2_input)
            
        st.caption(f"Concentrazione stimata: **{calculated_conc:.1f} g/kg**")

        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina Sportiva", list(sport_map.keys()))]
        
        # --- SOGLIE ---
        st.markdown("#### Dati di Soglia")
        ftp_watts = 265
        thr_hr = 170
        max_hr = 185
        
        if s_sport == SportType.CYCLING:
            ftp_watts = st.number_input("FTP [Watt]", 100, 600, 265, 5)
        elif s_sport == SportType.RUNNING:
            thr_hr = st.number_input("Soglia Anaerobica (BPM)", 100, 220, 170, 1)
            max_hr = st.number_input("FC Max (BPM)", 100, 230, 185, 1)
        else:
            max_hr = st.number_input("FC Max (BPM)", 100, 230, 185, 1)
        
        # Salvataggio in session state per Tab 3
        st.session_state['ftp_watts_input'] = ftp_watts
        st.session_state['thr_hr_input'] = thr_hr
        st.session_state['max_hr_input'] = max_hr

        # Opzioni Avanzate
        with st.expander("Fattori Avanzati"):
            use_creatine = st.checkbox("Supplementazione Creatina")
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                m_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = m_map[st.selectbox("Fase Ciclo", list(m_map.keys()))]

        # Creazione Subject Base
        subject = Subject(
            weight_kg=weight, height_cm=height, body_fat_pct=bf, sex=s_sex,
            glycogen_conc_g_kg=calculated_conc, sport=s_sport,
            uses_creatine=use_creatine, menstrual_phase=s_menstrual,
            vo2max_absolute_l_min=(vo2_input*weight)/1000,
            muscle_mass_kg=muscle_mass_input
        )
        
        # Calcolo Tank Base
        tank_data = logic.calculate_tank(subject)
        st.session_state['base_subject_struct'] = subject
        st.session_state['base_tank_data'] = tank_data

    with col_res:
        st.subheader("Riepilogo Capacità Massima")
        max_cap = tank_data['max_capacity_g']
        st.write(f"**Capacità Teorica:** {int(max_cap)} g ({int(max_cap*4.1)} kcal)")
        st.progress(100)
        
        c1, c2 = st.columns(2)
        c1.metric("Massa Muscolare Attiva", f"{tank_data['active_muscle_kg']:.1f} kg")
        c2.metric("Conc. Glicogeno", f"{calculated_conc:.1f} g/kg")
        
        # Visualizzazione Zone
        st.markdown("---")
        st.markdown("**Zone di Allenamento Stimate**")
        if s_sport == SportType.CYCLING:
            st.table(pd.DataFrame(utils.calculate_zones_cycling(ftp_watts)))
        else:
            st.table(pd.DataFrame(utils.calculate_zones_running_hr(thr_hr if s_sport == SportType.RUNNING else max_hr*0.85)))

# =============================================================================
# TAB 2: PREPARAZIONE & DIARIO
# =============================================================================
with tab2:
    if 'base_tank_data' not in st.session_state:
        st.warning("Completa prima il Tab 1.")
        st.stop()
        
    subj_base = st.session_state['base_subject_struct']
    weight = subj_base.weight_kg
    
    st.subheader("Stato Pre-Gara (Analisi 48h)")
    col_prep_in, col_prep_res = st.columns([1, 1])
    
    with col_prep_in:
        diet_method = st.radio("Metodo Input Dieta:", ["Rapido (Tipo)", "Preciso (Grammi)"], horizontal=True)
        
        if diet_method == "Rapido (Tipo)":
            diet_map = {d.label: d for d in DietType}
            s_diet = diet_map[st.selectbox("Regime Nutrizionale", list(diet_map.keys()), index=1)]
            cho_g1 = weight * s_diet.ref_value
            cho_g2 = weight * s_diet.ref_value
        else:
            c_d1, c_d2 = st.columns(2)
            cho_g1 = c_d1.number_input("CHO Giorno -1 (g)", 0, 1000, 350)
            cho_g2 = c_d2.number_input("CHO Giorno -2 (g)", 0, 1000, 350)
            
        fatigue_map = {f.label: f for f in FatigueState}
        s_fatigue = fatigue_map[st.selectbox("Carico Lavoro (24h prec.)", list(fatigue_map.keys()))]
        
        sleep_map = {s.label: s for s in SleepQuality}
        s_sleep = sleep_map[st.selectbox("Qualità Sonno", list(sleep_map.keys()), index=0)]
        
        with st.expander("Attività Specifica (Opzionale)"):
            steps_m1 = st.number_input("Passi Giorno -1", 0, 30000, 5000, 1000)
            min_act_m1 = st.number_input("Minuti Sport Giorno -1", 0, 300, 30, 10)

        # Calcolo Filling Factor
        comb_fill, _, _, _, _ = logic.calculate_filling_factor_from_diet(
            weight, cho_g1, cho_g2, s_fatigue, s_sleep, steps_m1, min_act_m1, 0, 0
        )
        
        # Stato Glicemia
        has_glucose = st.checkbox("Ho misurato la Glicemia")
        glucose_val = st.number_input("mg/dL", 50, 200, 90) if has_glucose else None
        
        # Aggiornamento Subject e Tank
        subj_prep = subj_base
        subj_prep.filling_factor = comb_fill
        subj_prep.glucose_mg_dl = glucose_val
        
        current_tank = logic.calculate_tank(subj_prep)
        st.session_state['tank_data'] = current_tank
        st.session_state['subject_struct'] = subj_prep

    with col_prep_res:
        st.markdown("### Riserve Disponibili")
        fill_pct = current_tank['fill_pct']
        st.metric("Livello Riempimento", f"{fill_pct:.1f}%")
        st.progress(int(fill_pct))
        
        c1, c2 = st.columns(2)
        c1.metric("Muscolo (g)", int(current_tank['muscle_glycogen_g']))
        c2.metric("Fegato (g)", int(current_tank['liver_glycogen_g']))
        
        if fill_pct < 60:
            st.error("Rischio elevato: Riserve insufficienti.")
        elif fill_pct > 90:
            st.success("Condizione Ottimale (Ready to Race).")
        else:
            st.warning("Buono, ma attenzione sulla lunga distanza.")

    st.markdown("---")
    
    # --- DIARIO SETTIMANALE ---
    st.subheader("Diario Settimanale (Tapering)")
    with st.expander("Apri Pianificatore Settimanale", expanded=False):
        days = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
        schedule = []
        for d in days:
            c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1])
            act = c1.selectbox(f"{d} Attività", ["Riposo", "Attivo"], key=f"act_{d}", label_visibility="collapsed")
            dur = c2.number_input(f"{d} Min", 0, 300, 0, key=f"dur_{d}", label_visibility="collapsed") if act != "Riposo" else 0
            inte = c3.selectbox(f"{d} Int.", ["Bassa (Z1-Z2)", "Media (Z3)", "Alta (Z4+)"], key=f"int_{d}", label_visibility="collapsed") if act != "Riposo" else "Riposo"
            cho = c4.number_input(f"{d} CHO", 0, 1000, 300, key=f"cho_{d}", label_visibility="collapsed")
            schedule.append({"day": d, "activity": act, "duration": dur, "intensity": inte, "cho_in": cho})
            
        if st.button("Calcola Trend Settimanale"):
            # Parametri per simulazione settimanale
            init_m = st.session_state['base_tank_data']['max_capacity_g'] - 100
            init_l = 100
            max_m = init_m
            max_l = 120
            vo2 = subj_base.vo2max_absolute_l_min * 1000 / weight
            
            df_week = logic.calculate_weekly_balance(init_m, init_l, max_m, max_l, schedule, weight, vo2)
            
            chart_week = alt.Chart(df_week).mark_line(point=True).encode(
                x=alt.X('Giorno', sort=days),
                y='Totale',
                tooltip=['Giorno', 'Totale', 'Glicogeno Muscolare', 'Glicogeno Epatico']
            ).properties(height=250)
            st.altair_chart(chart_week, use_container_width=True)

with tab3:
    if 'tank_data' not in st.session_state:
        st.warning("Completa i Tab precedenti.")
        st.stop()
        
    tank = st.session_state['tank_data']
    subj = st.session_state['subject_struct']
    start_tank = tank['actual_available_g']
    
    col_param, col_strat = st.columns([1, 1])
    
    # --- PARAMETRI SFORZO ---
    with col_param:
        st.subheader("1. Parametri Gara")
        
        # Gestione File
        file_source = st.radio("Fonte Dati:", ["Manuale", "File (.zwo/.fit/.gpx)"], horizontal=True)
        intensity_series = None
        duration = 120
        avg_val = 200 # Placeholder (Watt o HR)
        
        if file_source == "File (.zwo/.fit/.gpx)":
            upl = st.file_uploader("Carica File", type=['zwo', 'gpx', 'fit', 'csv'])
            if upl:
                ftp_ref = st.session_state.get('ftp_watts_input', 250)
                thr_ref = st.session_state.get('thr_hr_input', 170)
                series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(upl, ftp_ref, thr_ref, subj.sport)
                
                if series:
                    intensity_series = series
                    duration = dur_calc
                    st.success(f"File analizzato: {dur_calc} min.")
                    if w_calc > 0: avg_val = w_calc
                    elif hr_calc > 0: avg_val = hr_calc
        
        # Input Manuali (Fallback o Override)
        if subj.sport == SportType.CYCLING:
            avg_w = st.number_input("Potenza Media (Watt)", 50, 600, int(avg_val))
            duration = st.slider("Durata (min)", 30, 600, int(duration), 10)
            act_params = {
                'mode': 'cycling', 'avg_watts': avg_w, 
                'ftp_watts': st.session_state.get('ftp_watts_input', 250),
                'efficiency': st.slider("Efficienza (%)", 18.0, 25.0, 22.0, 0.5)
            }
        elif subj.sport == SportType.RUNNING:
            avg_hr = st.number_input("FC Media (BPM)", 80, 220, int(avg_val) if int(avg_val)>0 else 150)
            duration = st.slider("Durata (min)", 30, 600, int(duration), 10)
            act_params = {
                'mode': 'running', 'avg_hr': avg_hr, 'speed_kmh': 10.0, # Semplificato
                'threshold_hr': st.session_state.get('thr_hr_input', 170)
            }
        else:
            avg_hr = st.number_input("FC Media (BPM)", 80, 220, 150)
            duration = st.slider("Durata (min)", 30, 600, int(duration), 10)
            act_params = {
                'mode': 'other', 'avg_hr': avg_hr, 
                'max_hr': st.session_state.get('max_hr_input', 185)
            }

    # --- STRATEGIA INTEGRAZIONE ---
    with col_strat:
        st.subheader("2. Nutrizione in Gara")
        
        c_i1, c_i2 = st.columns(2)
        carb_intake = c_i1.slider("Target CHO (g/h)", 0, 120, 60, 10)
        cho_unit = c_i2.number_input("g CHO per Gel/Unit", 10, 100, 25)
        
        mix_opts = list(ChoMixType)
        s_mix = st.selectbox("Mix Carboidrati", mix_opts, format_func=lambda x: x.label)
        
        with st.expander("⚙️ Calibrazione Avanzata (Cinetica)"):
            tau_val = st.slider("Tau (τ) Assorbimento (min)", 5.0, 60.0, 20.0, 
                                help="Ritardo tra ingestione e disponibilità muscolare.")
            risk_val = st.slider("Soglia Rischio GI (g)", 10, 100, 30, 
                                 help="Accumulo massimo tollerabile nello stomaco.")
            eff_ox = st.slider("Efficienza Ossidazione (%)", 0.5, 1.0, 0.8, 0.05)
            
            use_lab = st.checkbox("Usa Dati Metabolimetro")
            lab_cho = 0; lab_fat = 0
            if use_lab:
                lab_cho = st.number_input("CHO Lab (g/h)", 0, 400, 150)
                lab_fat = st.number_input("FAT Lab (g/h)", 0, 200, 40)
            
            act_params['use_lab_data'] = use_lab
            act_params['lab_cho_g_h'] = lab_cho
            act_params['lab_fat_g_h'] = lab_fat

    # --- SIMULAZIONE ---
    
    # Scenario A: Strategia
    df_sim, stats_sim = logic.simulate_metabolism(
        tank, duration, carb_intake, cho_unit, 70, tau_val, subj, act_params,
        oxidation_efficiency_input=eff_ox, mix_type_input=s_mix, intensity_series=intensity_series
    )
    df_sim['Scenario'] = 'Con Integrazione'
    # FIX: Calcolo esplicito del totale
    df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']
    
    # Scenario B: Digiuno (Confronto)
    df_no, stats_no = logic.simulate_metabolism(
        tank, duration, 0, cho_unit, 70, tau_val, subj, act_params,
        oxidation_efficiency_input=eff_ox, mix_type_input=s_mix, intensity_series=intensity_series
    )
    df_no['Scenario'] = 'Digiuno'
    # FIX: Calcolo esplicito del totale
    df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']
    
    # --- RISULTATI VISUALI ---
    st.markdown("---")
    st.subheader("Analisi Risultati")
    
    # KPI
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("IF (Intensità)", f"{stats_sim['intensity_factor']:.2f}")
    k2.metric("RER Medio", f"{stats_sim['avg_rer']:.2f}")
    k3.metric("Glicogeno Finale", f"{int(stats_sim['final_glycogen'])} g", 
              delta=f"{int(stats_sim['final_glycogen'] - start_tank)} g")
    k4.metric("Consumo Grassi", f"{int(stats_sim['fat_total_g'])} g")

    # GRAFICO 1: BILANCIO ENERGETICO (STACKED AREA)
    st.markdown("#### 📊 Mix Energetico & Fonti")
    
    df_long = df_sim.melt('Time (min)', 
                          value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'],
                          var_name='Fonte', value_name='Rate (g/h)')
    
    # Ordine logico stack
    source_order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
    colors = ['#B71C1C', '#1976D2', '#FFC107', '#E57373']
    
    chart_stack = alt.Chart(df_long).mark_area().encode(
        x='Time (min)',
        y='Rate (g/h)',
        color=alt.Color('Fonte', scale=alt.Scale(domain=source_order, range=colors), sort=source_order),
        tooltip=['Time (min)', 'Fonte', 'Rate (g/h)']
    ).properties(height=350, title="Come il corpo copre la richiesta energetica")
    
    st.altair_chart(chart_stack, use_container_width=True)
    
    # GRAFICO 2: CONFRONTO RISERVE & RISCHIO GI
    c_res, c_gut = st.columns(2)
    
    with c_res:
        st.markdown("#### 📉 Deplezione Riserve")
        
        # Uniamo i due scenari per confronto
        df_combo = pd.concat([df_sim[['Time (min)', 'Residuo Totale', 'Scenario']], 
                              df_no[['Time (min)', 'Residuo Totale', 'Scenario']]])
        
        # Aggiungiamo il residuo Muscolare ed Epatico separati per lo scenario principale
        df_sim_melt = df_sim.melt('Time (min)', value_vars=['Residuo Muscolare', 'Residuo Epatico'], var_name='Tipo', value_name='Grammi')
        
        chart_res = alt.Chart(df_sim_melt).mark_area(opacity=0.5).encode(
            x='Time (min)',
            y=alt.Y('Grammi', stack=True),
            color=alt.Color('Tipo', scale=alt.Scale(domain=['Residuo Epatico', 'Residuo Muscolare'], range=['#B71C1C', '#E57373']))
        ).properties(title="Dettaglio Riserve (Con Integrazione)")
        
        st.altair_chart(chart_res, use_container_width=True)
        
    with c_gut:
        st.markdown("#### ⚠️ Accumulo Intestinale (Gut Load)")
        
        base_gut = alt.Chart(df_sim).mark_area(color='#8D6E63', opacity=0.7).encode(
            x='Time (min)',
            y='Gut Load',
            tooltip=['Time (min)', 'Gut Load']
        )
        
        line_risk = alt.Chart(pd.DataFrame({'y': [risk_val]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        
        st.altair_chart((base_gut + line_risk).properties(title=f"Soglia Rischio: {risk_val}g"), use_container_width=True)
        
    # ALERT FINALI (FIX: Usiamo i dati dal DataFrame per sicurezza)
    min_res = stats_sim['final_glycogen']
    final_liver = df_sim['Residuo Epatico'].iloc[-1] # Lettura diretta dal DF
    
    if min_res < 50:
        st.error(f"⚠️ **ATTENZIONE:** Rischio 'Bonk' elevato! Riserve finali critiche ({int(min_res)}g).")
    elif final_liver < 15: 
        st.warning("⚠️ **Ipoglicemia:** Le riserve epatiche sono pericolosamente basse.")
    else:
        st.success("✅ **Strategia Sostenibile:** Arrivi al traguardo con energia residua.")

    # TABELLA INTEGRAZIONE
    if carb_intake > 0:
        st.markdown("#### 📋 Piano Integrazione")
        units_tot = int((duration/60) * (carb_intake/cho_unit))
        st.info(f"Assumere **1 unità ({cho_unit}g)** ogni **{int(60/(carb_intake/cho_unit))} minuti**. Totale: ~{units_tot} unità.")
