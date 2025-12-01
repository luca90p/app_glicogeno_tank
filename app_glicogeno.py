import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import math

import logic
import utils
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject
)

st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
st.title("Glycogen Simulator Pro")
st.markdown("""
Applicazione avanzata per la modellazione delle riserve di glicogeno muscolare ed epatico. 
Il sistema utilizza equazioni differenziali per stimare i tassi di ossidazione, l'accumulo intestinale e la cinetica di assorbimento dei carboidrati.
""")

if not utils.check_password():
    st.stop()

def create_risk_zone_chart(df_data, title, max_y):
    zones_df = pd.DataFrame({
        'Zone': ['Sicurezza', 'Attenzione', 'Critico'],
        'Start': [max_y * 0.35, max_y * 0.15, 0],
        'End':   [max_y * 1.10, max_y * 0.35, max_y * 0.15],
        'Color': ['#66BB6A', '#FFA726', '#EF5350'] 
    })
    
    background = alt.Chart(zones_df).mark_rect(opacity=0.15).encode(
        y=alt.Y('Start', title='Glicogeno Totale (g)', scale=alt.Scale(domain=[0, max_y])),
        y2='End',
        color=alt.Color('Color', scale=None, legend=None),
        tooltip=['Zone']
    )
    
    area = alt.Chart(df_data).mark_area(line=True, opacity=0.8).encode(
        x=alt.X('Time (min)', title='Durata Esercizio (min)'),
        y='Residuo Totale',
        tooltip=['Time (min)', 'Residuo Totale', 'Scenario']
    )
    
    return (background + area).properties(title=title, height=350)

tab1, tab2, tab3 = st.tabs([
    "1. Profilo Fisiologico & Capacità", 
    "2. Diario di Tapering", 
    "3. Simulazione Gara & Strategia"
])

# =============================================================================
# TAB 1: PROFILO
# =============================================================================
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("Parametri Antropometrici")
        weight = st.slider("Peso Corporeo (kg)", 45.0, 100.0, 74.0, 0.5)
        height = st.slider("Altezza (cm)", 150, 210, 187, 1)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 11.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso Biologico", list(sex_map.keys()), horizontal=True)]
        
        use_smm = st.checkbox("Usa Massa Muscolare (SMM) da Bioimpedenza/DEXA")
        muscle_mass_input = None
        if use_smm:
            muscle_mass_input = st.number_input("SMM Misurata [kg]", 10.0, 60.0, 37.4, 0.1)
        
        st.markdown("---")
        st.subheader("Stima Capacità di Stoccaggio")
        
        est_method = st.radio("Metodo di Stima Densità Glicogeno:", ["Basato su Livello Atletico (Consigliato)", "Basato su VO2max (Lab)"])
        calculated_conc = 0.0
        vo2_derived = 0.0
        
        if est_method == "Basato su Livello Atletico (Consigliato)":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello di Allenamento", list(status_map.keys()), index=3)]
            calculated_conc = s_status.val
            vo2_derived = 30 + ((calculated_conc - 13.0) / 0.24)
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, 1)
            calculated_conc = logic.get_concentration_from_vo2max(vo2_input)
            vo2_derived = vo2_input
            
        

        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina", list(sport_map.keys()))]
        
        ftp_watts = 265
        thr_hr = 170
        max_hr = 185
        
        if s_sport == SportType.CYCLING:
            ftp_watts = st.number_input("FTP (Watt)", 100, 600, 265)
        elif s_sport == SportType.RUNNING:
            thr_hr = st.number_input("Soglia Anaerobica (BPM)", 100, 220, 170)
            max_hr = st.number_input("FC Max (BPM)", 100, 230, 185)
        else:
            max_hr = st.number_input("FC Max (BPM)", 100, 230, 185)
            
        st.session_state.update({'ftp_watts_input': ftp_watts, 'thr_hr_input': thr_hr, 'max_hr_input': max_hr})
        
        with st.expander("Variabili Aggiuntive"):
            use_creatine = st.checkbox("Supplementazione Creatina (+10% Stoccaggio)")
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                m_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = m_map[st.selectbox("Fase Ciclo Mestruale", list(m_map.keys()))]

        subject = Subject(
            weight_kg=weight, height_cm=height, body_fat_pct=bf, sex=s_sex,
            glycogen_conc_g_kg=calculated_conc, sport=s_sport,
            uses_creatine=use_creatine, menstrual_phase=s_menstrual,
            vo2max_absolute_l_min=(vo2_derived*weight)/1000,
            muscle_mass_kg=muscle_mass_input
        )
        
        tank_data = logic.calculate_tank(subject)
        st.session_state['base_subject_struct'] = subject
        st.session_state['base_tank_data'] = tank_data

    with col_res:
        st.subheader("Analisi Capacità di Stoccaggio (Tank)")
        max_cap = tank_data['max_capacity_g']
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Capacità Totale", f"{int(max_cap)} g")
        c2.metric("Energia Equivalente", f"{int(max_cap*4.1)} kcal")
        c3.metric("Massa Muscolare Attiva", f"{tank_data['active_muscle_kg']:.1f} kg")
        
        st.progress(1.0)
        
        st.markdown("### Zone di Allenamento")
        if s_sport == SportType.CYCLING:
            zones = utils.calculate_zones_cycling(ftp_watts)
        else:
            zones = utils.calculate_zones_running_hr(thr_hr if s_sport == SportType.RUNNING else max_hr*0.85)
        st.table(pd.DataFrame(zones))

# =============================================================================
# TAB 2: DIARIO DI TAPERING
# =============================================================================
with tab2:
    if 'base_tank_data' not in st.session_state:
        st.warning("⚠️ Completa prima il Tab 1 (Profilo Atleta).")
        st.stop()
        
    subj_base = st.session_state['base_subject_struct']
    
    # Recuperiamo le soglie dal session state (definite nel Tab 1)
    # Default fallback se non settate (ma dovrebbero esserlo dal Tab 1)
    user_ftp = st.session_state.get('ftp_watts_input', 250)
    user_thr = st.session_state.get('thr_hr_input', 170)
    user_max_hr = st.session_state.get('max_hr_input', 185)
    
    st.subheader("🗓️ Diario di Avvicinamento (Countdown)")
    st.markdown("""
    Compila il diario. Seleziona **Allenamento** per inserire i dati specifici (Watt o FC). 
    Il sistema calcolerà automaticamente l'**Intensity Factor (IF)** basandosi sulle tue soglie.
    """)
    
    # Inizializzazione dati
    if "tapering_data" not in st.session_state:
        # Struttura di default
        st.session_state["tapering_data"] = [
            {"day": -7, "label": "-7 Giorni", "type": "Allenamento", "val": 180, "dur": 60, "cho": 350, "sleep": "Sufficiente (6-7h)"},
            {"day": -6, "label": "-6 Giorni", "type": "Allenamento", "val": 160, "dur": 60, "cho": 350, "sleep": "Sufficiente (6-7h)"},
            {"day": -5, "label": "-5 Giorni", "type": "Riposo", "val": 0, "dur": 0, "cho": 350, "sleep": "Sufficiente (6-7h)"},
            {"day": -4, "label": "-4 Giorni", "type": "Riposo", "val": 0, "dur": 0, "cho": 300, "sleep": "Ottimale (>7h)"},
            {"day": -3, "label": "-3 Giorni", "type": "Allenamento", "val": 200, "dur": 30, "cho": 400, "sleep": "Ottimale (>7h)"},
            {"day": -2, "label": "-2 Giorni", "type": "Riposo", "val": 0, "dur": 0, "cho": 400, "sleep": "Ottimale (>7h)"},
            {"day": -1, "label": "-1 Giorno", "type": "Riposo", "val": 0, "dur": 0, "cho": 500, "sleep": "Ottimale (>7h)"}
        ]

    # --- DEFINIZIONE COLONNE ---
    # Layout griglia più largo per ospitare i dati tecnici
    cols = st.columns([1, 1.2, 1, 1.2, 1, 1.2])
    cols[0].markdown("**Countdown**")
    cols[1].markdown("**Attività**")
    cols[2].markdown("**Minuti**")
    
    # Etichetta dinamica in base allo sport
    intensity_label = "Valore"
    if subj_base.sport == SportType.CYCLING:
        intensity_label = "Watt Medi"
    elif subj_base.sport == SportType.RUNNING:
        intensity_label = "FC Media"
    else:
        intensity_label = "FC Media"
        
    cols[3].markdown(f"**{intensity_label}**")
    cols[4].markdown("**CHO (g)**")
    cols[5].markdown("**Sonno**")
    
    sleep_opts = {"Ottimale (>7h)": 1.0, "Sufficiente (6-7h)": 0.95, "Insufficiente (<6h)": 0.85}
    input_result_data = []
    
    # --- CICLO DI INPUT ---
    for i, row in enumerate(st.session_state["tapering_data"]):
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1.2, 1, 1.2, 1, 1.2])
        
        # 1. Label Giorno
        if row['day'] >= -2: c1.error(f"**{row['label']}**")
        else: c1.write(f"**{row['label']}**")
            
        # 2. Aut/Aut Attività (Selectbox)
        type_opts = ["Riposo", "Allenamento"]
        curr_type_idx = 1 if row['type'] == "Allenamento" else 0
        act_type = c2.selectbox(f"t_{i}", type_opts, index=curr_type_idx, key=f"type_{i}", label_visibility="collapsed")
        
        # Variabili per i calcoli
        duration = 0
        intensity_val = 0
        calc_if = 0.0
        
        # 3 & 4. Logica Condizionale (Solo se Allenamento)
        if act_type == "Allenamento":
            # Durata
            duration = c3.number_input(f"d_{i}", 0, 600, row['dur'], step=10, key=f"dur_{i}", label_visibility="collapsed")
            
            # Valore Intensità (Watt o FC)
            val_default = row['val'] if row['val'] > 0 else 150 # Default sensato se si passa da Riposo ad Attivo
            intensity_val = c4.number_input(f"v_{i}", 0, 500, val_default, step=5, key=f"val_{i}", label_visibility="collapsed")
            
            # --- CALCOLO LIVE IF ---
            if subj_base.sport == SportType.CYCLING:
                calc_if = intensity_val / user_ftp if user_ftp > 0 else 0
            elif subj_base.sport == SportType.RUNNING:
                calc_if = intensity_val / user_thr if user_thr > 0 else 0
            else:
                # Per altri sport usiamo FC su Max HR come proxy grezzo o soglia se disponibile
                ref_hr = user_thr if user_thr > 0 else (user_max_hr * 0.85)
                calc_if = intensity_val / ref_hr if ref_hr > 0 else 0
            
            # Feedback visivo IF immediato
            if calc_if > 0:
                c4.caption(f"IF: **{calc_if:.2f}**")
                
        else:
            c3.write("-")
            c4.write("-")
        
        # 5. Carboidrati
        new_cho = c5.number_input(f"c_{i}", 0, 1500, row['cho'], step=50, key=f"cho_{i}", label_visibility="collapsed")
        
        # 6. Sonno
        sl_idx = list(sleep_opts.keys()).index(row['sleep']) if row['sleep'] in sleep_opts else 0
        new_sleep_label = c6.selectbox(f"s_{i}", list(sleep_opts.keys()), index=sl_idx, key=f"sl_{i}", label_visibility="collapsed")
        
        # Salvataggio dati per la logica
        input_result_data.append({
            "label": row['label'],
            "duration": duration,
            "calculated_if": calc_if, # Passiamo l'IF calcolato
            "cho_in": new_cho,
            "sleep_factor": sleep_opts[new_sleep_label]
        })

    st.markdown("---")
    
    # Validazione base: controlla se i giorni -2 e -1 hanno CHO (dato che sono critici per il carboloading)
    cho_d2 = input_result_data[5]['cho_in']
    cho_d1 = input_result_data[6]['cho_in']
    
    is_valid = True
    if cho_d2 == 0 and cho_d1 == 0:
        st.warning("⚠️ Non hai inserito carboidrati per i giorni **-2** e **-1**. Il riempimento sarà probabilmente basso.")
    
    if st.button("🚀 Simula Stato Glicogeno (Race Ready)", type="primary"):
        # Chiamata alla logica aggiornata
        df_trend, final_tank = logic.calculate_tapering_trajectory(subj_base, input_result_data)
        
        st.session_state['tank_data'] = final_tank
        st.session_state['subject_struct'] = subj_base
        
        st.subheader("Risultato Tapering")
        r1, r2 = st.columns([2, 1])
        
        with r1:
            # Grafico Linea
            chart = alt.Chart(df_trend).mark_line(point=True, strokeWidth=3).encode(
                x=alt.X('Giorno', sort=[d['label'] for d in input_result_data], title=None),
                y=alt.Y('Totale', title='Glicogeno Totale (g)', scale=alt.Scale(zero=False)),
                color=alt.value('#43A047'),
                tooltip=['Giorno', 'Totale', 'Muscolare', 'Epatico', 'Input CHO', alt.Tooltip('IF', format='.2f')]
            ).properties(height=300, title="Evoluzione Riserve Settimanali")
            st.altair_chart(chart, use_container_width=True)
            
        with r2:
            final_pct = final_tank['fill_pct']
            st.metric("Riempimento Gara", f"{final_pct:.1f}%", delta=f"{int(final_tank['actual_available_g'])}g Totali")
            st.progress(final_pct / 100)
            
            if final_pct >= 90: st.success("✅ **CONDIZIONE OTTIMALE**")
            elif final_pct >= 75: st.info("⚠️ **CONDIZIONE BUONA**")
            else: st.error("❌ **RISERVE BASSE**")
            
            st.write(f"- Muscolo: **{int(final_tank['muscle_glycogen_g'])} g**")
            st.write(f"- Fegato: **{int(final_tank['liver_glycogen_g'])} g**")

# =============================================================================
# TAB 3: SIMULAZIONE GARA
# =============================================================================
with tab3:
    if 'tank_data' not in st.session_state:
        st.stop()
        
    tank = st.session_state['tank_data']
    subj = st.session_state['subject_struct']
    start_total = tank['actual_available_g']
    
    st.info(f"**Condizione di Partenza:** {int(start_total)}g di glicogeno disponibile.")
    
    c_s1, c_s2, c_s3 = st.columns(3)
    with c_s1:
        st.markdown("### 1. Profilo Sforzo")
        duration = st.number_input("Durata (min)", 60, 900, 180, step=10)
        uploaded_file = st.file_uploader("Importa File (.zwo)", type=['zwo'])
        intensity_series = None
        
        if uploaded_file:
            series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(uploaded_file, st.session_state['ftp_watts_input'], st.session_state['thr_hr_input'], subj.sport)
            if series:
                intensity_series = series
                duration = dur_calc
                st.success(f"File importato: {dur_calc} min.")
        
        if subj.sport == SportType.CYCLING:
            val = st.number_input("Potenza Media (Watt)", 100, 500, 200)
            params = {'mode': 'cycling', 'avg_watts': val, 'ftp_watts': st.session_state['ftp_watts_input'], 'efficiency': 22.0}
        else:
            val = st.number_input("FC Media (BPM)", 100, 220, 150)
            params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': st.session_state['thr_hr_input']}
            
    with c_s2:
        st.markdown("### 2. Strategia Nutrizionale")
        cho_h = st.slider("Target Intake (g/h)", 0, 120, 60, step=5)
        cho_unit = st.number_input("Grammi CHO per Unità (Gel)", 10, 100, 25)
        
    with c_s3:
        st.markdown("### 3. Fisiologia Digestiva")
        mix_sel = st.selectbox("Mix Carboidrati", list(ChoMixType), format_func=lambda x: x.label)
        
        tau = st.slider("Costante Assorbimento (Tau)", 5, 60, 20)
        risk_thresh = st.slider("Soglia Tolleranza GI (g)", 10, 100, 30)

    df_sim, stats_sim = logic.simulate_metabolism(tank, duration, cho_h, cho_unit, 70, tau, subj, params, mix_type_input=mix_sel, intensity_series=intensity_series)
    df_sim['Scenario'] = 'Strategia Integrata'
    df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']
    
    df_no, _ = logic.simulate_metabolism(tank, duration, 0, cho_unit, 70, tau, subj, params, mix_type_input=mix_sel, intensity_series=intensity_series)
    df_no['Scenario'] = 'Riferimento (Digiuno)'
    df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']

    st.markdown("---")
    r1_c1, r1_c2 = st.columns([2, 1])
    
    with r1_c1:
        st.markdown("#### Bilancio Energetico e Substrati")
        df_melt = df_sim.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
        colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']
        chart_stack = alt.Chart(df_melt).mark_area().encode(
            x='Time (min)', y='g/h', color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        ).properties(height=350)
        st.altair_chart(chart_stack, use_container_width=True)
        
    with r1_c2:
        st.markdown("#### KPI Prestazionali")
        fin_gly = stats_sim['final_glycogen']
        delta = fin_gly - start_total
        st.metric("Glicogeno Residuo", f"{int(fin_gly)} g", delta=f"{int(delta)} g")
        st.metric("Intensità (IF)", f"{stats_sim['intensity_factor']:.2f}")
        st.metric("CHO Ossidati", f"{int(stats_sim['total_exo_used'] + stats_sim['total_muscle_used'] + stats_sim['total_liver_used'])} g")
        st.metric("FAT Ossidati", f"{int(stats_sim['fat_total_g'])} g")

    st.markdown("---")
    r2_c1, r2_c2 = st.columns(2)
    with r2_c1:
        st.markdown("#### Analisi Deplezione (Zone di Rischio)")
        chart_strat = create_risk_zone_chart(df_sim, "Scenario: Con Integrazione", start_total)
        chart_fast = create_risk_zone_chart(df_no, "Scenario: Digiuno (Controllo)", start_total)
        st.altair_chart(alt.vconcat(chart_strat, chart_fast), use_container_width=True)
        if fin_gly < 50: st.error("⚠️ CRITICITÀ RILEVATA: Riserve finali prossime all'esaurimento.")
        else: st.success("✅ STRATEGIA SOSTENIBILE: Riserve energetiche sufficienti.")
    with r2_c2:
        st.markdown("#### Analisi Tolleranza Gastrointestinale")
        base = alt.Chart(df_sim).encode(x='Time (min)')
        area_gut = base.mark_area(color='#795548', opacity=0.6).encode(y=alt.Y('Gut Load', title='Accumulo (g)'), tooltip=['Gut Load'])
        rule = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        line_intake = base.mark_line(color='#1E88E5', interpolate='step-after').encode(y=alt.Y('Intake Cumulativo (g)', axis=alt.Axis(title='Flusso (g)', orient='right')))
        line_ox = base.mark_line(color='#43A047').encode(y=alt.Y('Ossidazione Cumulativa (g)', axis=None))
        chart_gi = alt.layer(area_gut, rule, line_intake, line_ox).resolve_scale(y='independent').properties(height=350)
        st.altair_chart(chart_gi, use_container_width=True)
        max_gut = df_sim['Gut Load'].max()
        if max_gut > risk_thresh: st.warning(f"⚠️ Rischio Distress GI: Il picco ({int(max_gut)}g) supera la soglia.")

    st.markdown("---")
    st.markdown("### 📋 Cronotabella Operativa")
    if cho_h > 0 and cho_unit > 0:
        units_per_hour = cho_h / cho_unit
        interval_rounded = int(60 / units_per_hour)
        schedule = []
        current_time = interval_rounded
        total_ingested = 0
        while current_time <= duration:
            total_ingested += cho_unit
            schedule.append({"Timing (Min)": current_time, "Azione": f"Assumere 1 unità ({cho_unit}g CHO)", "Totale (g)": total_ingested})
            current_time += interval_rounded
        if schedule:
            st.table(pd.DataFrame(schedule))
            st.info(f"Portare **{len(schedule)}** gel totali. Alert ogni **{interval_rounded}** minuti.")
    else:
        st.info("Nessuna strategia di integrazione definita.")

