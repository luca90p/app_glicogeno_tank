import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import math

import logic
import utils
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject, IntakeMode
)

st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
st.title("Glycogen Simulator Pro")
st.markdown("""
Applicazione avanzata per la modellazione delle riserve di glicogeno. 
Supporta **Atleti Ibridi**, profili metabolici personalizzati e **Simulazione Scenari**.
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

# Funzione Helper per Grafici Standardizzati
def create_cutoff_line(cutoff_time):
    return alt.Chart(pd.DataFrame({'x': [cutoff_time]})).mark_rule(
        color='black', strokeDash=[5, 5], size=2
    ).encode(
        x='x',
        tooltip=[alt.Tooltip('x', title='Stop Assunzione (min)')]
    )

# Inizializzazione Session State
if 'use_lab_data' not in st.session_state:
    st.session_state.update({'use_lab_data': False, 'lab_cho_mean': 0, 'lab_fat_mean': 0})

tab1, tab2, tab3 = st.tabs([
    "1. Profilo Atleta & Metabolismo", 
    "2. Diario Ibrido (Tapering)", 
    "3. Simulazione Gara"
])

# =============================================================================
# TAB 1: PROFILO & METABOLISMO
# =============================================================================
with tab1:
    col_in, col_res = st.columns([1, 2])
    
    with col_in:
        st.subheader("Parametri Antropometrici")
        weight = st.slider("Peso Corporeo (kg)", 45.0, 100.0, 74.0, 0.5)
        height = st.slider("Altezza (cm)", 150, 210, 187, 1)
        bf = st.slider("Massa Grassa (%)", 4.0, 30.0, 11.0, 0.5) / 100.0
        
        sex_map = {s.value: s for s in Sex}
        s_sex = sex_map[st.radio("Sesso", list(sex_map.keys()), horizontal=True)]
        
        use_smm = st.checkbox("Usa Massa Muscolare (SMM) misurata")
        muscle_mass_input = None
        if use_smm:
            muscle_mass_input = st.number_input("SMM Misurata [kg]", 10.0, 60.0, 37.4, 0.1)
        
        st.markdown("---")
        st.subheader("Capacità & Soglie")
        
        est_method = st.radio("Metodo Stima Densità:", ["Livello Atletico", "VO2max (Lab)"], horizontal=True)
        calculated_conc = 0.0
        vo2_derived = 0.0
        
        if est_method == "Livello Atletico":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello", list(status_map.keys()), index=3)]
            calculated_conc = s_status.val
            vo2_derived = 30 + ((calculated_conc - 13.0) / 0.24)
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, 1)
            calculated_conc = logic.get_concentration_from_vo2max(vo2_input)
            vo2_derived = vo2_input
            
        
        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Sport Target (Principale)", list(sport_map.keys()))]
        
        # --- INPUT SOGLIE IBRIDE ---
        c_ftp, c_hr = st.columns(2)
        ftp_watts = c_ftp.number_input("FTP Ciclismo (Watt)", 100, 600, 265, step=5)
        thr_hr = c_hr.number_input("Soglia Anaerobica Corsa (BPM)", 100, 220, 170, step=1)
        max_hr = st.number_input("Frequenza Cardiaca Max (BPM)", 100, 230, 185, step=1)
            
        st.session_state.update({'ftp_watts_input': ftp_watts, 'thr_hr_input': thr_hr, 'max_hr_input': max_hr})
        
        # --- NUOVA SEZIONE: PROFILO METABOLICO ---
        st.markdown("---")
        with st.expander("🧬 Profilo Metabolico (Test Laboratorio)", expanded=False):
            st.info("Inserisci i dati dal test del gas (Metabolimetro) per personalizzare i consumi.")
            active_lab = st.checkbox("Attiva Profilo Metabolico Personalizzato", value=st.session_state.get('use_lab_data', False))
            
            if active_lab:
                met_method = st.radio("Metodo Inserimento:", ["Carica File (Completo)", "Manuale (3 Punti)"], horizontal=True)
                
                if met_method == "Inserimento Manuale (3 Punti)":
                    st.caption("Inserisci i dati per tre zone di intensità (Z2, Z3, Z4).")
                    st.markdown("**1. Zona Z2 (Aerobica / FatMax)**")
                    c1, c2, c3 = st.columns(3)
                    z2_hr = c1.number_input("FC (bpm)", 0, 220, 130, key='z2_hr')
                    z2_cho = c2.number_input("CHO (g/h)", 0, 500, 75, key='z2_cho')
                    z2_fat = c3.number_input("FAT (g/h)", 0, 200, 40, key='z2_fat')
                    
                    st.markdown("**2. Zona Z3 (Medio / Tempo)**")
                    c4, c5, c6 = st.columns(3)
                    z3_hr = c4.number_input("FC (bpm)", 0, 220, 155, key='z3_hr')
                    z3_cho = c5.number_input("CHO (g/h)", 0, 500, 140, key='z3_cho')
                    z3_fat = c6.number_input("FAT (g/h)", 0, 200, 29, key='z3_fat')
                    
                    st.markdown("**3. Zona Z4 (Soglia / Vo2max)**")
                    c7, c8, c9 = st.columns(3)
                    z4_hr = c7.number_input("FC (bpm)", 0, 220, 175, key='z4_hr')
                    z4_cho = c8.number_input("CHO (g/h)", 0, 600, 220, key='z4_cho')
                    z4_fat = c9.number_input("FAT (g/h)", 0, 200, 5, key='z4_fat')
                    
                    metabolic_curve = {
                        'z2': {'hr': z2_hr, 'cho': z2_cho, 'fat': z2_fat},
                        'z3': {'hr': z3_hr, 'cho': z3_cho, 'fat': z3_fat},
                        'z4': {'hr': z4_hr, 'cho': z4_cho, 'fat': z4_fat}
                    }
                    st.session_state['use_lab_data'] = True
                    st.session_state['metabolic_curve'] = metabolic_curve
                    
                    curve_df = pd.DataFrame([
                        {'Intensità': z2_hr, 'Consumo': z2_cho, 'Tipo': 'CHO'},
                        {'Intensità': z3_hr, 'Consumo': z3_cho, 'Tipo': 'CHO'},
                        {'Intensità': z4_hr, 'Consumo': z4_cho, 'Tipo': 'CHO'},
                        {'Intensità': z2_hr, 'Consumo': z2_fat, 'Tipo': 'FAT'},
                        {'Intensità': z3_hr, 'Consumo': z3_fat, 'Tipo': 'FAT'},
                        {'Intensità': z4_hr, 'Consumo': z4_fat, 'Tipo': 'FAT'}
                    ])
                    c_chart = alt.Chart(curve_df).mark_line(point=True).encode(x='Intensità', y='Consumo', color='Tipo').properties(height=200)
                    st.altair_chart(c_chart, use_container_width=True)

                elif met_method == "Carica File (Completo)":
                    upl_file = st.file_uploader("Carica Report Metabolimetro", type=['csv', 'xlsx', 'txt'])
                    if upl_file:
                        df_curve, int_type, err = utils.parse_metabolic_report(upl_file)
                        if df_curve is not None:
                            st.success(f"✅ Curva caricata con successo! ({len(df_curve)} punti). Intensità basata su: {int_type.upper()}")
                            c_chart = alt.Chart(df_curve).mark_line(point=True).encode(
                                x=alt.X('Intensity', title='Intensità'), 
                                y='CHO', color=alt.value('blue'), tooltip=['Intensity', 'CHO', 'FAT']
                            ) + alt.Chart(df_curve).mark_line(point=True).encode(
                                x='Intensity', y='FAT', color=alt.value('orange')
                            )
                            st.altair_chart(c_chart, use_container_width=True)
                            st.session_state['use_lab_data'] = True
                            st.session_state['metabolic_curve'] = df_curve
                        else:
                            st.error(f"Errore: {err}")
            else:
                st.session_state['use_lab_data'] = False
                st.session_state['metabolic_curve'] = None

        with st.expander("Opzioni Fisiologiche Aggiuntive"):
            use_creatine = st.checkbox("Usa Creatina")
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                m_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = m_map[st.selectbox("Fase Ciclo", list(m_map.keys()))]

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
        st.subheader("Analisi Tank")
        max_cap = tank_data['max_capacity_g']
        c1, c2, c3 = st.columns(3)
        c1.metric("Capacità Totale", f"{int(max_cap)} g")
        c2.metric("Energia", f"{int(max_cap*4.1)} kcal")
        c3.metric("Massa Attiva", f"{tank_data['active_muscle_kg']:.1f} kg")
        st.progress(1.0)
        st.markdown("### Zone di Allenamento")
        t_cyc, t_run = st.tabs(["Ciclismo (Power)", "Corsa (Heart Rate)"])
        with t_cyc:
            st.table(pd.DataFrame(utils.calculate_zones_cycling(ftp_watts)))
        with t_run:
            st.table(pd.DataFrame(utils.calculate_zones_running_hr(thr_hr)))

# =============================================================================
# TAB 2: DIARIO IBRIDO
# =============================================================================
with tab2:
    if 'base_tank_data' not in st.session_state:
        st.warning("⚠️ Completa prima il Tab 1.")
        st.stop()
        
    subj_base = st.session_state['base_subject_struct']
    user_ftp = st.session_state.get('ftp_watts_input', 250)
    user_thr = st.session_state.get('thr_hr_input', 170)
    
    st.subheader("🗓️ Diario di Avvicinamento (Multidisciplinare)")
    
    from data_models import GlycogenState
    st.markdown("#### Condizione di Partenza (-7 Giorni)")
    gly_states = list(GlycogenState)
    sel_state = st.selectbox("Livello di riempimento iniziale:", gly_states, format_func=lambda x: x.label, index=2)
    st.markdown("---")
    
    if "tapering_data" in st.session_state:
        if len(st.session_state["tapering_data"]) > 0:
            first_row = st.session_state["tapering_data"][0]
            if "type" not in first_row or first_row["type"] == "Allenamento":
                del st.session_state["tapering_data"]
                st.rerun()

    if "tapering_data" not in st.session_state:
        st.session_state["tapering_data"] = [
            {"day": -7, "label": "-7 Giorni", "type": "Ciclismo", "val": 180, "dur": 60, "cho": 350, "sleep": "Sufficiente (6-7h)"},
            {"day": -6, "label": "-6 Giorni", "type": "Corsa/Altro", "val": 145, "dur": 45, "cho": 350, "sleep": "Sufficiente (6-7h)"},
            {"day": -5, "label": "-5 Giorni", "type": "Riposo", "val": 0, "dur": 0, "cho": 350, "sleep": "Sufficiente (6-7h)"},
            {"day": -4, "label": "-4 Giorni", "type": "Riposo", "val": 0, "dur": 0, "cho": 300, "sleep": "Ottimale (>7h)"},
            {"day": -3, "label": "-3 Giorni", "type": "Ciclismo", "val": 200, "dur": 30, "cho": 400, "sleep": "Ottimale (>7h)"},
            {"day": -2, "label": "-2 Giorni", "type": "Riposo", "val": 0, "dur": 0, "cho": 400, "sleep": "Ottimale (>7h)"},
            {"day": -1, "label": "-1 Giorno", "type": "Riposo", "val": 0, "dur": 0, "cho": 500, "sleep": "Ottimale (>7h)"}
        ]

    cols = st.columns([1, 1.3, 1, 1.3, 1, 1.2])
    cols[0].markdown("**Countdown**")
    cols[1].markdown("**Attività**")
    cols[2].markdown("**Minuti**")
    cols[3].markdown("**Intensità (Watt o FC)**")
    cols[4].markdown("**CHO (g)**")
    cols[5].markdown("**Sonno**")
    
    sleep_opts = {"Ottimale (>7h)": 1.0, "Sufficiente (6-7h)": 0.95, "Insufficiente (<6h)": 0.85}
    type_opts = ["Riposo", "Ciclismo", "Corsa/Altro"] 
    
    input_result_data = []
    
    for i, row in enumerate(st.session_state["tapering_data"]):
        c1, c2, c3, c4, c5, c6 = st.columns([1, 1.3, 1, 1.3, 1, 1.2])
        
        if row['day'] >= -2: c1.error(f"**{row['label']}**")
        else: c1.write(f"**{row['label']}**")
            
        try: curr_idx = type_opts.index(row['type'])
        except: curr_idx = 0
        act_type = c2.selectbox(f"t_{i}", type_opts, index=curr_idx, key=f"type_{i}", label_visibility="collapsed")
        
        duration = 0
        intensity_val = 0
        calc_if = 0.0
        
        if act_type != "Riposo":
            duration = c3.number_input(f"d_{i}", 0, 600, row.get('dur', 0), step=10, key=f"dur_{i}", label_visibility="collapsed")
            val_default = row.get('val', 0) if row.get('val', 0) > 0 else 140
            intensity_val = c4.number_input(f"v_{i}", 0, 600, val_default, step=5, key=f"val_{i}", label_visibility="collapsed")
            
            if act_type == "Ciclismo":
                if user_ftp > 0:
                    calc_if = intensity_val / user_ftp
                    c4.caption(f"IF: **{calc_if:.2f}**")
            elif act_type == "Corsa/Altro":
                if user_thr > 0:
                    calc_if = intensity_val / user_thr
                    c4.caption(f"IF: **{calc_if:.2f}**")
        else:
            c3.write("-")
            c4.write("-")
        
        new_cho = c5.number_input(f"c_{i}", 0, 1500, row['cho'], step=50, key=f"cho_{i}", label_visibility="collapsed")
        sl_idx = list(sleep_opts.keys()).index(row['sleep']) if row['sleep'] in sleep_opts else 0
        new_sleep_label = c6.selectbox(f"s_{i}", list(sleep_opts.keys()), index=sl_idx, key=f"sl_{i}", label_visibility="collapsed")
        
        input_result_data.append({
            "label": row['label'], "duration": duration, "calculated_if": calc_if,
            "cho_in": new_cho, "sleep_factor": sleep_opts[new_sleep_label]
        })

    st.markdown("---")
    
    cho_d2 = input_result_data[5]['cho_in']
    cho_d1 = input_result_data[6]['cho_in']
    if cho_d2 == 0 and cho_d1 == 0:
        st.warning("⚠️ Carboidrati giorni -2/-1 a zero.")
    
    if st.button("🚀 Simula Stato Glicogeno (Race Ready)", type="primary"):
        df_trend, final_tank = logic.calculate_tapering_trajectory(subj_base, input_result_data, start_state=sel_state)
        st.session_state['tank_data'] = final_tank
        st.session_state['subject_struct'] = subj_base
        
        st.subheader("Risultato Tapering")
        r1, r2 = st.columns([2, 1])
        with r1:
            chart = alt.Chart(df_trend).mark_line(point=True, strokeWidth=3).encode(
                x=alt.X('Giorno', sort=[d['label'] for d in input_result_data], title=None),
                y=alt.Y('Totale', title='Glicogeno (g)', scale=alt.Scale(zero=False)),
                color=alt.value('#43A047'),
                tooltip=['Giorno', 'Totale', 'Muscolare', 'Epatico', 'Input CHO', alt.Tooltip('IF', format='.2f')]
            ).properties(height=300, title="Evoluzione Riserve")
            st.altair_chart(chart, use_container_width=True)
        with r2:
            final_pct = final_tank['fill_pct']
            st.metric("Riempimento Gara", f"{final_pct:.1f}%", delta=f"{int(final_tank['actual_available_g'])}g Totali")
            st.progress(final_pct / 100)
            if final_pct >= 90: st.success("✅ OTTIMALE")
            elif final_pct >= 75: st.info("⚠️ BUONO")
            else: st.error("❌ BASSO")
            st.write(f"- Muscolo: **{int(final_tank['muscle_glycogen_g'])} g**")
            st.write(f"- Fegato: **{int(final_tank['liver_glycogen_g'])} g**")

# =============================================================================
# TAB 3: SIMULAZIONE GARA & STRATEGIA
# =============================================================================
with tab3:
    if 'tank_data' not in st.session_state:
        st.stop()
        
    tank_base = st.session_state['tank_data']
    subj = st.session_state['subject_struct']
    
    # --- OVERRIDE MODE ---
    st.markdown("### 🛠️ Modalità Test / Override")
    enable_override = st.checkbox("Abilita Override Livello Iniziale (Bypassa Tab 2)", value=False)
    
    if enable_override:
        max_cap = tank_base['max_capacity_g']
        st.warning(f"Modalità Test Attiva. Max Capacità: {int(max_cap)}g")
        force_pct = st.slider("Forza Livello Riempimento (%)", 0, 120, 100, 5)
        
        forced_muscle = (max_cap - 100) * (force_pct / 100.0)
        forced_liver = 100 * (force_pct / 100.0)
        
        tank = tank_base.copy()
        tank['muscle_glycogen_g'] = forced_muscle
        tank['liver_glycogen_g'] = forced_liver
        tank['actual_available_g'] = forced_muscle + forced_liver
        tank['fill_pct'] = force_pct
        start_total = tank['actual_available_g']
        
        st.metric("Nuovo Start Glicogeno", f"{int(start_total)} g")
    else:
        tank = tank_base
        start_total = tank['actual_available_g']
        st.info(f"**Condizione di Partenza:** {int(start_total)}g di glicogeno disponibile.")
    
    c_s1, c_s2, c_s3 = st.columns(3)
    
    # --- 1. PROFILO SFORZO ---
    with c_s1:
        st.markdown("### 1. Profilo Sforzo")
        duration = st.number_input("Durata (min)", 60, 900, 180, step=10)
        uploaded_file = st.file_uploader("Importa File (.zwo)", type=['zwo'])
        intensity_series = None
        
        target_thresh_hr = st.session_state['thr_hr_input']
        target_ftp = st.session_state['ftp_watts_input']
        
        # --- UPLOAD MULTI-FORMATO (ZWO, FIT, GPX, CSV) ---
        uploaded_file = st.file_uploader("Carica File Attività", type=['zwo', 'fit', 'gpx', 'csv'])
        intensity_series = None
        fit_df = None # DataFrame per il grafico dettagliato (solo FIT)
        
        target_thresh_hr = st.session_state['thr_hr_input']
        target_ftp = st.session_state['ftp_watts_input']
        
        if uploaded_file:
            fname = uploaded_file.name.lower()
            
            # 1. GESTIONE ZWO (Allenamento Strutturato)
            if fname.endswith('.zwo'):
                st.info("File ZWO rilevato (Allenamento Strutturato)")
                series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(uploaded_file, target_ftp, target_thresh_hr, subj.sport)
                if series:
                    # Convertiamo l'IF del ZWO in valore assoluto per il motore
                    if subj.sport == SportType.CYCLING:
                        intensity_series = [val * target_ftp for val in series]
                        st.success(f"ZWO Caricato: {dur_calc} min. Avg Power: {int(w_calc)} W")
                    else:
                        intensity_series = [val * target_thresh_hr for val in series]
                        st.success(f"ZWO Caricato: {dur_calc} min. Avg HR: {int(hr_calc)} bpm")
                    duration = dur_calc

            # 2. GESTIONE FIT (Attività Reale - Parsing Avanzato)
            elif fname.endswith('.fit'):
                st.info("File FIT rilevato (Attività Reale)")
                with st.spinner("Analisi file FIT in corso..."):
                    # Chiama il wrapper in utils (che usa fitparse)
                    fit_series, fit_dur, fit_avg_w, fit_avg_hr, fit_clean_df = utils.parse_fit_file_wrapper(uploaded_file, subj.sport)
                    
                    if fit_clean_df is not None:
                        intensity_series = fit_series
                        duration = fit_dur
                        fit_df = fit_clean_df # Salviamo per il grafico di dettaglio
                        
                        msg = f"FIT Caricato: {fit_dur} min."
                        if subj.sport == SportType.CYCLING: msg += f" Avg Power: {int(fit_avg_w)} W"
                        else: msg += f" Avg HR: {int(fit_avg_hr)} bpm"
                        st.success(msg)
                        
                        # Sovrascriviamo i valori manuali per coerenza visiva
                        if subj.sport == SportType.CYCLING: val = int(fit_avg_w)
                        else: val = int(fit_avg_hr)
                    else:
                        st.error("Errore nella lettura del file FIT.")

            # 3. GESTIONE GENERICA (CSV/GPX - Logica Semplificata)
            else:
                # (Qui potresti aggiungere logica per GPX se serve, per ora gestiamo come CSV base)
                try:
                    df_activity = pd.read_csv(uploaded_file)
                    # Stima durata (assumendo 1 record = 1 secondo o 5 secondi, da adattare)
                    # Qui assumiamo un formato standard semplice
                    if 'power' in df_activity.columns and subj.sport == SportType.CYCLING:
                        intensity_series = df_activity['power'].fillna(0).tolist()
                        duration = math.ceil(len(intensity_series) / 60) # Assumendo 1s rec
                        st.success(f"CSV Caricato: {duration} min")
                    elif 'heart_rate' in df_activity.columns:
                        intensity_series = df_activity['heart_rate'].fillna(0).tolist()
                        duration = math.ceil(len(intensity_series) / 60)
                        st.success(f"CSV Caricato: {duration} min")
                except Exception as e:
                    st.warning(f"Formato file non riconosciuto o errore lettura: {e}")

        # VISUALIZZAZIONE GRAFICO DETTAGLIATO (SOLO FIT)
        if fit_df is not None:
            with st.expander("📈 Analisi Dettagliata File FIT", expanded=True):
                # Usa la funzione di plotting che abbiamo messo in utils
                st.pyplot(utils.create_fit_plot(fit_df))
        
        # Variabile VI
        vi_input = 1.0

        if subj.sport == SportType.CYCLING:
            val = st.number_input("Potenza Media Gara (Watt)", 100, 500, 200)
            params = {'mode': 'cycling', 'avg_watts': val, 'ftp_watts': target_ftp, 'efficiency': 22.0} 
            if intensity_series is None: 
                params['avg_hr'] = val
                vi_input = st.slider("Indice Variabilità (VI = NP/Avg)", 1.00, 1.30, 1.00, 0.01, 
                                     help="1.00=Crono Piatta, 1.05=Gran Fondo, 1.15+=Gara Nervosa/MTB")
                if vi_input > 1.0: st.caption(f"Potenza Normalizzata Stimata: **{int(val * vi_input)} W**")
        else:
            val = st.number_input("FC Media Gara (BPM)", 100, 220, 150)
            params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}
            
    # --- 2. STRATEGIA NUTRIZIONALE ---
    with c_s2:
        st.markdown("### 2. Strategia Nutrizionale")
        intake_mode_sel = st.radio("Modalità Assunzione:", ["Discretizzata (Gel/Barrette)", "Continuativa (Liquid/Sorsi)"])
        intake_mode_enum = IntakeMode.DISCRETE if intake_mode_sel.startswith("Discret") else IntakeMode.CONTINUOUS
        
        mix_sel = st.selectbox("Mix Carboidrati", list(ChoMixType), format_func=lambda x: x.label)
        intake_cutoff = st.slider("Stop Assunzione prima del termine (min)", 0, 60, 20, help="Evita assunzioni inutili nel finale.")
        
        cho_h = 0
        cho_unit = 0
        
        if intake_mode_enum == IntakeMode.DISCRETE:
            c_u1, c_u2 = st.columns(2)
            cho_unit = c_u1.number_input("Grammi CHO per Unità", 10, 100, 25)
            intake_interval = c_u2.number_input("Intervallo Assunzione (min)", 10, 120, 40, step=5)
            
            # FIX CALCOLO: Usiamo l'intervallo PURO per passare il parametro alla simulazione
            # (il motore deciderà poi se tagliare l'ultimo gel col cutoff)
            if intake_interval > 0:
                cho_h = (60 / intake_interval) * cho_unit
                
                # Calcolo "Reale" solo per info visiva
                feeding_window = duration - intake_cutoff
                num_intakes = 0
                for t in range(0, int(feeding_window) + 1):
                    if t == 0 or (t > 0 and t % intake_interval == 0): num_intakes += 1
                
                total_real = num_intakes * cho_unit
                rate_real = total_real / (duration / 60) if duration > 0 else 0
                
                st.info(f"Rateo Effettivo (su {duration}min): **{int(rate_real)} g/h**")
                st.caption(f"Pianificati: {num_intakes} unità ({total_real}g) fino al min {int(feeding_window)}.")
        else:
            cho_h = st.slider("Target Intake (g/h)", 0, 120, 60, step=5)
            cho_unit = 30 
            st.caption("Assunzione continua.")

    # --- 3. MOTORE METABOLICO ---
    with c_s3:
        st.markdown("### 3. Motore Metabolico")
        curve_data = st.session_state.get('metabolic_curve', None)
        use_lab_active = st.session_state.get('use_lab_data', False)
        
        if use_lab_active and curve_data is not None:
            st.success("✅ **Curva Metabolica Attiva**")
            if intensity_series:
                avg_int = sum(intensity_series)/len(intensity_series)
                st.caption(f"Input Dinamico: {int(avg_int)}")
            else:
                # Mostra se stiamo usando VI
                if vi_input > 1.0: st.caption(f"Input: {val} W (NP {int(val*vi_input)})")
                else: st.caption(f"Input Costante: {val}")
            tau = 20
            risk_thresh = 30
        else:
            st.info("ℹ️ **Modello Teorico**")
            st.caption("Regola i parametri per stimare il profilo metabolico.")
            crossover_val = st.slider("Crossover Point (% Soglia)", 50, 90, 75)
            if subj.sport == SportType.CYCLING:
                eff_mech = st.slider("Efficienza Meccanica (%)", 18.0, 25.0, 21.5, 0.5)
                params['efficiency'] = eff_mech
            tau = st.slider("Costante Assorbimento (Tau)", 5, 60, 20)
            risk_thresh = st.slider("Soglia Tolleranza GI (g)", 10, 100, 30)

    # --- SELEZIONE MODALITÀ SIMULAZIONE ---
    st.markdown("---")
    sim_mode = st.radio("Modalità Simulazione:", ["Simulazione Manuale (Verifica Tattica)", "Calcolatore Strategia Minima (Reverse)"], horizontal=True)
    
    # Oggetto cutoff line per tutti i grafici
    cutoff_line = create_cutoff_line(duration - intake_cutoff)
    
    if sim_mode == "Simulazione Manuale (Verifica Tattica)":
        
        df_sim, stats_sim = logic.simulate_metabolism(
            tank, duration, cho_h, cho_unit, 
            crossover_val if not use_lab_active else 75, 
            tau, subj, params, 
            mix_type_input=mix_sel, 
            intensity_series=intensity_series,
            metabolic_curve=curve_data if use_lab_active else None,
            intake_mode=intake_mode_enum,
            intake_cutoff_min=intake_cutoff,
            variability_index=vi_input 
        )
        df_sim['Scenario'] = 'Strategia Integrata'
        df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']
        
        df_no, _ = logic.simulate_metabolism(
            tank, duration, 0, cho_unit, 
            crossover_val if not use_lab_active else 75, 
            tau, subj, params, 
            mix_type_input=mix_sel, 
            intensity_series=intensity_series,
            metabolic_curve=curve_data if use_lab_active else None,
            intake_mode=intake_mode_enum,
            intake_cutoff_min=intake_cutoff,
            variability_index=vi_input
        )
        df_no['Scenario'] = 'Riferimento (Digiuno)'
        df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']

        # --- DASHBOARD RISULTATI ---
        st.markdown("---")
        st.subheader("Analisi Cinetica e Substrati")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Intensity Factor (IF)", f"{stats_sim['intensity_factor']:.2f}")
        c2.metric("RER Stimato (RQ)", f"{stats_sim['avg_rer']:.2f}")
        c3.metric("Ripartizione Substrati", f"{int(stats_sim['cho_pct'])}% CHO", f"{100-int(stats_sim['cho_pct'])}% FAT", delta_color="off")
        c4.metric("Glicogeno Residuo", f"{int(stats_sim['final_glycogen'])} g", delta=f"{int(stats_sim['final_glycogen'] - start_total)} g")

        st.markdown("---")
        m1, m2, m3 = st.columns(3)
        m1.metric("Uso Glicogeno Muscolare", f"{int(stats_sim['total_muscle_used'])} g")
        m2.metric("Uso Glicogeno Epatico", f"{int(stats_sim['total_liver_used'])} g")
        m3.metric("Uso CHO Esogeno", f"{int(stats_sim['total_exo_used'])} g")

        st.markdown("### 📊 Bilancio Energetico: Richiesta vs. Fonti di Ossidazione")
        
        df_melt = df_sim.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
        colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']
        
        chart_stack = alt.Chart(df_melt).mark_area().encode(
            x='Time (min)', y='g/h', 
            color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        ).properties(height=350)
        st.altair_chart(chart_stack + cutoff_line, use_container_width=True)

        st.markdown("---")
        st.markdown("#### Ossidazione Lipidica (Tasso Orario)")
        chart_fat = alt.Chart(df_sim).mark_line(color='#FFC107', strokeWidth=3).encode(
            x=alt.X('Time (min)'),
            y=alt.Y('Ossidazione Lipidica (g)', title='Grassi (g/h)'),
            tooltip=['Time (min)', 'Ossidazione Lipidica (g)']
        ).properties(height=250)
        st.altair_chart(chart_fat + cutoff_line, use_container_width=True)

        st.markdown("---")
        st.markdown("#### Confronto Riserve Nette (Svuotamento Serbatoio)")
        st.caption("Confronto: Deplezione Glicogeno Totale (Muscolo + Fegato) con Zone di Rischio")
        
        reserve_fields = ['Residuo Muscolare', 'Residuo Epatico']
        reserve_colors = ['#E57373', '#B71C1C'] 
        
        df_reserve_sim = df_sim.melt('Time (min)', value_vars=reserve_fields, var_name='Tipo', value_name='Grammi')
        df_reserve_no = df_no.melt('Time (min)', value_vars=reserve_fields, var_name='Tipo', value_name='Grammi')
        
        max_y = start_total * 1.05
        zones_df = pd.DataFrame({
            'Start': [max_y * 0.35, max_y * 0.15, 0],
            'End': [max_y * 1.10, max_y * 0.35, max_y * 0.15],
            'Color': ['#66BB6A', '#FFA726', '#EF5350'] 
        })
        
        def create_reserve_stacked_chart(df_data, title):
            bg = alt.Chart(zones_df).mark_rect(opacity=0.15).encode(
                y=alt.Y('Start', scale=alt.Scale(domain=[0, max_y]), axis=None),
                y2='End', color=alt.Color('Color', scale=None)
            )
            area = alt.Chart(df_data).mark_area().encode(
                x='Time (min)', 
                y=alt.Y('Grammi', stack='zero', title='Residuo (g)'),
                color=alt.Color('Tipo', scale=alt.Scale(domain=reserve_fields, range=reserve_colors)),
                order=alt.Order('Tipo', sort='ascending'), 
                tooltip=['Time (min)', 'Tipo', 'Grammi']
            )
            return (bg + area + cutoff_line).properties(title=title, height=300)

        c_strat, c_digi = st.columns(2)
        with c_strat:
            st.altair_chart(create_reserve_stacked_chart(df_reserve_sim, "Con Integrazione"), use_container_width=True)
        with c_digi:
            st.altair_chart(create_reserve_stacked_chart(df_reserve_no, "Digiuno (No Integrazione)"), use_container_width=True)

        st.markdown("---")
        st.markdown("#### Analisi Gut Load")
        base = alt.Chart(df_sim).encode(x='Time (min)')
        area_gut = base.mark_area(color='#795548', opacity=0.6).encode(y=alt.Y('Gut Load', title='Accumulo (g)'), tooltip=['Gut Load'])
        rule = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        chart_gi = alt.layer(area_gut, rule, cutoff_line).properties(height=350)
        st.altair_chart(chart_gi, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Analisi Criticità & Timing")
        
        liver_bonk = df_sim[df_sim['Residuo Epatico'] <= 0]
        muscle_bonk = df_sim[df_sim['Residuo Muscolare'] <= 20]
        
        bonk_time = None
        cause = None
        
        if not liver_bonk.empty:
            bonk_time = liver_bonk['Time (min)'].iloc[0]
            cause = "Esaurimento Epatico (Ipoglicemia)"
        if not muscle_bonk.empty:
            t_muscle = muscle_bonk['Time (min)'].iloc[0]
            if bonk_time is None or t_muscle < bonk_time:
                bonk_time = t_muscle
                cause = "Esaurimento Muscolare (Gambe Vuote)"
                
        c_b1, c_b2 = st.columns([2, 1])
        with c_b1:
            if bonk_time:
                st.error(f"⚠️ **CRITICITÀ RILEVATA AL MINUTO {bonk_time}**")
                st.write(f"Causa Primaria: **{cause}**")
            else:
                st.success("✅ **STRATEGIA SOSTENIBILE**")
        with c_b2:
            if bonk_time:
                 st.metric("Tempo Limite", f"{bonk_time} min", delta="Bonk!", delta_color="inverse")
            else:
                 st.metric("Buffer Energetico", "Sicuro")

        st.markdown("---")
        st.markdown("### 📋 Cronotabella Operativa")
        
        if intake_mode_enum == IntakeMode.DISCRETE and cho_h > 0 and cho_unit > 0:
            schedule = []
            current_time = intake_interval
            total_ingested = 0
            
            if intake_interval > 0:
                total_ingested += cho_unit
                schedule.append({"Minuto": 0, "Azione": f"Assumere 1 unità ({cho_unit}g CHO)", "Totale Ingerito": f"{total_ingested}g"})
                
                while current_time <= (duration - intake_cutoff):
                    total_ingested += cho_unit
                    schedule.append({
                        "Minuto": current_time,
                        "Azione": f"Assumere 1 unità ({cho_unit}g CHO)",
                        "Totale Ingerito": f"{total_ingested}g"
                    })
                    current_time += intake_interval
            
            if schedule:
                st.table(pd.DataFrame(schedule))
                st.info(f"Portare **{len(schedule)}** unità.")
            else:
                st.warning("Nessuna assunzione prevista.")

        elif intake_mode_enum == IntakeMode.CONTINUOUS and cho_h > 0:
            st.info(f"Bere continuativamente: **{cho_h} g/ora** di carboidrati.")
            effective_duration = max(0, duration - intake_cutoff)
            total_needs = (effective_duration/60) * cho_h
            st.write(f"**Totale Gara:** preparare borracce con **{int(total_needs)} g** totali.")
    
    else:
        # --- CALCOLO REVERSE STRATEGY ---
        st.subheader("🎯 Calcolatore Strategia Minima")
        st.markdown("Il sistema calcolerà l'apporto di carboidrati minimo necessario per terminare la gara senza crisi.")
        
        if st.button("Calcola Fabbisogno Minimo"):
             with st.spinner("Simulazione scenari multipli in corso..."):
                 opt_intake = logic.calculate_minimum_strategy(
                     tank, duration, subj, params, 
                     st.session_state.get('metabolic_curve'), mix_sel, intake_mode_enum, intake_cutoff,
                     variability_index=vi_input 
                 )
                 
             if opt_intake is not None:
                 if opt_intake == 0:
                      st.success("### ✅ Strategia Consigliata: Nessuna integrazione necessaria (0 g/h)")
                 elif intake_mode_enum == IntakeMode.DISCRETE and cho_unit > 0:
                     units_per_hour = opt_intake / cho_unit
                     if units_per_hour > 0:
                         interval_min = int(60 / units_per_hour)
                         st.success(f"### ✅ Strategia: Assumere 1 unità ogni {interval_min} min")
                         st.caption(f"(Equivalente a circa **{opt_intake} g/h**)")
                     else:
                         st.warning("Intake minimo troppo basso per questa unità.")
                 else:
                     st.success(f"### ✅ Strategia Consigliata: Bere {opt_intake} g/h")

                 st.write(f"Con questo apporto, arriverai al traguardo con riserve minime di sicurezza.")
                 
                 df_opt, stats_opt = logic.simulate_metabolism(
                     tank, duration, opt_intake, 25, 70, 20, subj, params, 
                     mix_type_input=mix_sel, metabolic_curve=st.session_state.get('metabolic_curve'),
                     intake_mode=intake_mode_enum, intake_cutoff_min=intake_cutoff,
                     variability_index=vi_input
                 )
                 
                 # DASHBOARD RISULTATI CALCOLO INVERSO (Identica a Manuale)
                 st.markdown("---")
                 
                 c1, c2, c3, c4 = st.columns(4)
                 c1.metric("IF", f"{stats_opt['intensity_factor']:.2f}")
                 c2.metric("RER", f"{stats_opt['avg_rer']:.2f}")
                 c3.metric("Substrati", f"{int(stats_opt['cho_pct'])}% CHO", f"{100-int(stats_opt['cho_pct'])}% FAT")
                 c4.metric("Residuo Finale", f"{int(stats_opt['final_glycogen'])} g")
                 
                 st.markdown("#### Bilancio Energetico (Strategia Minima)")
                 df_melt_opt = df_opt.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
                 order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
                 colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']
                 
                 chart_stack_opt = alt.Chart(df_melt_opt).mark_area().encode(
                    x='Time (min)', y='g/h', 
                    color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
                    tooltip=['Time (min)', 'Fonte', 'g/h']
                 ).properties(height=300)
                 st.altair_chart(chart_stack_opt + cutoff_line, use_container_width=True)
                 
                 st.markdown("#### Ossidazione Lipidica")
                 chart_fat_opt = alt.Chart(df_opt).mark_line(color='#FFC107', strokeWidth=3).encode(
                    x=alt.X('Time (min)'),
                    y=alt.Y('Ossidazione Lipidica (g)', title='Grassi (g/h)'),
                 ).properties(height=200)
                 st.altair_chart(chart_fat_opt + cutoff_line, use_container_width=True)
                 
                 st.markdown("#### Riserve Residue")
                 reserve_fields = ['Residuo Muscolare', 'Residuo Epatico']
                 df_res_opt = df_opt.melt('Time (min)', value_vars=reserve_fields, var_name='Tipo', value_name='Grammi')
                 
                 max_y = start_total * 1.05
                 zones_df = pd.DataFrame({
                    'Start': [max_y * 0.35, max_y * 0.15, 0],
                    'End': [max_y * 1.10, max_y * 0.35, max_y * 0.15],
                    'Color': ['#66BB6A', '#FFA726', '#EF5350'] 
                 })
                 
                 bg = alt.Chart(zones_df).mark_rect(opacity=0.15).encode(
                    y=alt.Y('Start', scale=alt.Scale(domain=[0, max_y]), axis=None),
                    y2='End', color=alt.Color('Color', scale=None)
                 )
                 area_opt = alt.Chart(df_res_opt).mark_area().encode(
                    x='Time (min)', 
                    y=alt.Y('Grammi', stack='zero'),
                    color=alt.Color('Tipo', scale=alt.Scale(domain=reserve_fields, range=['#E57373', '#B71C1C'])),
                    order=alt.Order('Tipo', sort='ascending')
                 )
                 st.altair_chart((bg + area_opt + cutoff_line).properties(height=300), use_container_width=True)
                 
                 st.markdown("#### Gut Load")
                 base_opt = alt.Chart(df_opt).encode(x='Time (min)')
                 area_gut_opt = base_opt.mark_area(color='#795548', opacity=0.6).encode(y='Gut Load')
                 rule_opt = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
                 st.altair_chart((area_gut_opt + rule_opt + cutoff_line).properties(height=250), use_container_width=True)

             else:
                 st.error("❌ Impossibile finire la gara!")
                 st.write("Anche con 120 g/h, le riserve si esauriscono. Devi ridurre l'intensità.")

