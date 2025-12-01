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
Applicazione avanzata per la modellazione delle riserve di glicogeno. 
Supporta **Atleti Ibridi** e profili metabolici personalizzati da test di laboratorio.
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

# Inizializzazione Session State per Dati Lab (se non esistono)
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
        
        # --- NUOVA SEZIONE: PROFILO METABOLICO (SPOSTATA QUI) ---
        st.markdown("---")
        # --- SEZIONE PROFILO METABOLICO MULTIPOINT ---
        st.markdown("---")
        with st.expander("🧬 Profilo Metabolico Avanzato (Curva a 3 Punti)", expanded=False):
            st.info("Inserisci i dati reali dal tuo test per 3 intensità chiave. Il simulatore interpolerà i consumi.")
            active_lab = st.checkbox("Usa Curva Metabolica Reale", value=st.session_state.get('use_lab_data', False))
            
            if active_lab:
                # Recuperiamo i dati calcolati o usiamo default
                # Punti suggeriti dall'analisi del file
                
                st.markdown("**1. Zona Z2 (Aerobica / FatMax)**")
                c1, c2, c3 = st.columns(3)
                z2_hr = c1.number_input("FC (bpm)", 100, 200, 138, key='z2_hr')
                z2_cho = c2.number_input("CHO (g/h)", 0, 400, 75, key='z2_cho')
                z2_fat = c3.number_input("FAT (g/h)", 0, 200, 40, key='z2_fat')
                
                st.markdown("**2. Zona Z3 (Medio / Tempo)**")
                c4, c5, c6 = st.columns(3)
                z3_hr = c4.number_input("FC (bpm)", 100, 200, 158, key='z3_hr')
                z3_cho = c5.number_input("CHO (g/h)", 0, 400, 139, key='z3_cho')
                z3_fat = c6.number_input("FAT (g/h)", 0, 200, 29, key='z3_fat')
                
                st.markdown("**3. Zona Z4 (Soglia / Vo2max)**")
                c7, c8, c9 = st.columns(3)
                z4_hr = c7.number_input("FC (bpm)", 100, 220, 172, key='z4_hr')
                z4_cho = c8.number_input("CHO (g/h)", 0, 600, 219, key='z4_cho')
                z4_fat = c9.number_input("FAT (g/h)", 0, 200, 7, key='z4_fat')
                
                # Creazione Dizionario Curva
                metabolic_curve = {
                    'z2': {'hr': z2_hr, 'cho': z2_cho, 'fat': z2_fat},
                    'z3': {'hr': z3_hr, 'cho': z3_cho, 'fat': z3_fat},
                    'z4': {'hr': z4_hr, 'cho': z4_cho, 'fat': z4_fat}
                }
                
                st.session_state['use_lab_data'] = True
                st.session_state['metabolic_curve'] = metabolic_curve
                
                # Grafico anteprima curva
                df_curve = pd.DataFrame([
                    {'FC': z2_hr, 'Consumo': z2_cho, 'Tipo': 'CHO'},
                    {'FC': z3_hr, 'Consumo': z3_cho, 'Tipo': 'CHO'},
                    {'FC': z4_hr, 'Consumo': z4_cho, 'Tipo': 'CHO'},
                    {'FC': z2_hr, 'Consumo': z2_fat, 'Tipo': 'FAT'},
                    {'FC': z3_hr, 'Consumo': z3_fat, 'Tipo': 'FAT'},
                    {'FC': z4_hr, 'Consumo': z4_fat, 'Tipo': 'FAT'}
                ])
                c_chart = alt.Chart(df_curve).mark_line(point=True).encode(
                    x='FC', y='Consumo', color='Tipo'
                ).properties(height=200, title="La tua Curva Metabolica")
                st.altair_chart(c_chart, use_container_width=True)
                
            else:
                st.session_state['use_lab_data'] = False
                st.session_state['metabolic_curve'] = None

        # Setup soggetto base
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
        
        # Tabelle Zone
        st.markdown("### Zone di Allenamento (Ibrido)")
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
    
    # Recupero soglie
    user_ftp = st.session_state.get('ftp_watts_input', 250)
    user_thr = st.session_state.get('thr_hr_input', 170)
    
    st.subheader("🗓️ Diario di Avvicinamento (Multidisciplinare)")
    
    # --- NUOVO INPUT: STATO INIZIALE ---
    from data_models import GlycogenState
    st.markdown("#### Condizione di Partenza (-7 Giorni)")
    gly_states = list(GlycogenState)
    sel_state = st.selectbox("Livello di riempimento iniziale:", gly_states, format_func=lambda x: x.label, index=2)
    st.markdown("---")
    
    # FIX SESSION STATE
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
        
    tank = st.session_state['tank_data']
    subj = st.session_state['subject_struct']
    start_total = tank['actual_available_g']
    
    st.info(f"**Condizione di Partenza:** {int(start_total)}g di glicogeno disponibile.")
    
    c_s1, c_s2, c_s3 = st.columns(3)
    
    # --- 1. PROFILO SFORZO ---
    with c_s1:
        st.markdown("### 1. Profilo Sforzo")
        duration = st.number_input("Durata (min)", 60, 900, 180, step=10)
        uploaded_file = st.file_uploader("Importa File (.zwo)", type=['zwo'])
        intensity_series = None
        
        # Recupero soglie
        target_thresh_hr = st.session_state['thr_hr_input']
        target_ftp = st.session_state['ftp_watts_input']
        
        if uploaded_file:
            series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(uploaded_file, target_ftp, target_thresh_hr, subj.sport)
            
            if series:
                # Conversione IF -> Valori Assoluti per la curva
                if subj.sport == SportType.CYCLING:
                    intensity_series = [val * target_ftp for val in series]
                    st.success(f"File Bici: Convertito in Watt (Media ~{int(w_calc)} W)")
                else:
                    intensity_series = [val * target_thresh_hr for val in series]
                    st.success(f"File Corsa: Convertito in BPM (Media ~{int(hr_calc)} bpm)")
                
                duration = dur_calc
        
        # Input Manuale
        if subj.sport == SportType.CYCLING:
            val = st.number_input("Potenza Media Gara (Watt)", 100, 500, 200)
            params = {'mode': 'cycling', 'avg_watts': val, 'ftp_watts': target_ftp, 'efficiency': 22.0} # Default eff, sovrascritto dopo
            if intensity_series is None:
                params['avg_hr'] = val 
        else:
            val = st.number_input("FC Media Gara (BPM)", 100, 220, 150)
            params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': target_thresh_hr}
            
    # --- 2. STRATEGIA NUTRIZIONALE ---
    with c_s2:
        st.markdown("### 2. Strategia Nutrizionale")
        cho_h = st.slider("Target Intake (g/h)", 0, 120, 60, step=5)
        cho_unit = st.number_input("Grammi CHO per Unità (Gel)", 10, 100, 25)
        
    # --- 3. MOTORE METABOLICO (TEORICO O REALE) ---
    with c_s3:
        st.markdown("### 3. Motore Metabolico")
        mix_sel = st.selectbox("Mix Carboidrati", list(ChoMixType), format_func=lambda x: x.label)
        
        # Recupero Curva
        curve_data = st.session_state.get('metabolic_curve', None)
        use_lab_active = st.session_state.get('use_lab_data', False)
        
        # SETUP MODELLO
        if use_lab_active and curve_data:
            # --- CASO A: DATI LAB ---
            st.success("✅ **Curva Reale Attiva**")
            st.caption("Il consumo CHO/FAT sarà calcolato interpolando i dati del tuo test.")
            
            # Parametri fissi/nascosti quando si usa il Lab
            crossover_val = 70 
            tau = 20
            risk_thresh = 30
            
        else:
            # --- CASO B: MODELLO TEORICO ---
            st.info("ℹ️ **Modello Teorico**")
            st.caption("Regola i parametri per stimare il profilo metabolico.")
            
            # Slider Crossover Point (Determina la forma della curva RER)
            crossover_val = st.slider(
                "Crossover Point (% Soglia)", 
                50, 90, 75, 
                help="Intensità alla quale i CHO superano i Grassi. Un atleta 'Diesel' ha un valore più alto (es. 80%)."
            )
            
            # Slider Efficienza (Solo Ciclismo)
            if subj.sport == SportType.CYCLING:
                eff_mech = st.slider("Efficienza Meccanica (%)", 18.0, 25.0, 21.5, 0.5, help="Conversione energia in watt.")
                params['efficiency'] = eff_mech
            
            tau = st.slider("Costante Assorbimento (Tau)", 5, 60, 20)
            risk_thresh = st.slider("Soglia Tolleranza GI (g)", 10, 100, 30)

    # --- ESECUZIONE SIMULAZIONI ---
    
    # 1. Scenario A: Strategia Integrata
    df_sim, stats_sim = logic.simulate_metabolism(
        tank, duration, cho_h, cho_unit, 
        crossover_val, # Passiamo il crossover scelto
        tau, subj, params, 
        mix_type_input=mix_sel, 
        intensity_series=intensity_series,
        metabolic_curve=curve_data if use_lab_active else None
    )
    df_sim['Scenario'] = 'Strategia Integrata'
    df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']
    
    # 2. Scenario B: Riferimento (Digiuno)
    df_no, _ = logic.simulate_metabolism(
        tank, duration, 0, cho_unit, 
        crossover_val, # Passiamo il crossover scelto
        tau, subj, params, 
        mix_type_input=mix_sel, 
        intensity_series=intensity_series,
        metabolic_curve=curve_data if use_lab_active else None
    )
    df_no['Scenario'] = 'Riferimento (Digiuno)'
    df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']

    # --- DASHBOARD RISULTATI ---
    st.markdown("---")
    
    # ROW 1: BILANCIO
    r1_c1, r1_c2 = st.columns([2, 1])
    with r1_c1:
        st.markdown("#### Bilancio Energetico")
        df_melt = df_sim.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
        colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']
        
        chart_stack = alt.Chart(df_melt).mark_area().encode(
            x='Time (min)', y='g/h', 
            color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        ).properties(height=350)
        st.altair_chart(chart_stack, use_container_width=True)
        
    with r1_c2:
        st.markdown("#### KPI")
        fin_gly = stats_sim['final_glycogen']
        delta = fin_gly - start_total
        st.metric("Glicogeno Residuo", f"{int(fin_gly)} g", delta=f"{int(delta)} g")
        
        if use_lab_active:
            st.metric("Fonte Dati", "Test Lab (Reale)")
        else:
            # Mostra i parametri teorici usati
            st.metric("Modello Teorico", f"Crossover {crossover_val}%")
            
        st.metric("Intensità (IF)", f"{stats_sim['intensity_factor']:.2f}")
        st.metric("CHO Ossidati", f"{int(stats_sim['total_exo_used'] + stats_sim['total_muscle_used'] + stats_sim['total_liver_used'])} g")
        st.metric("FAT Ossidati", f"{int(stats_sim['fat_total_g'])} g")

    # ROW 2: RISCHI
    st.markdown("---")
    r2_c1, r2_c2 = st.columns(2)
    
    with r2_c1:
        st.markdown("#### Zone di Rischio")
        chart_strat = create_risk_zone_chart(df_sim, "Scenario: Con Integrazione", start_total)
        chart_fast = create_risk_zone_chart(df_no, "Scenario: Digiuno", start_total)
        st.altair_chart(alt.vconcat(chart_strat, chart_fast), use_container_width=True)
        
    with r2_c2:
        st.markdown("#### Analisi Gut Load")
        base = alt.Chart(df_sim).encode(x='Time (min)')
        area_gut = base.mark_area(color='#795548', opacity=0.6).encode(y=alt.Y('Gut Load', title='Accumulo (g)'), tooltip=['Gut Load'])
        rule = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        chart_gi = alt.layer(area_gut, rule).properties(height=350)
        st.altair_chart(chart_gi, use_container_width=True)

    # TABELLA
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
            schedule.append({"Min": current_time, "Azione": f"1 unità ({cho_unit}g)", "Tot": total_ingested})
            current_time += interval_rounded
        if schedule:
            st.table(pd.DataFrame(schedule))
            st.info(f"Portare **{len(schedule)}** unità.")




