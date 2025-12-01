import streamlit as st
import pandas as pd
import numpy as np
import altair as alt

import logic
import utils
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject
)

# --- CONFIGURAZIONE E STILE ---
st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
st.title("Glycogen Simulator Pro")
st.markdown("Strumento avanzato per la simulazione delle riserve energetiche e del metabolismo sotto sforzo.")

if not utils.check_password():
    st.stop()

# --- HELPER VISUALIZZAZIONE ---
def create_risk_zone_chart(df_data, title, max_y):
    """Genera un grafico a zone (Verde/Giallo/Rosso) per visualizzare il livello di rischio deplezione."""
    zones_df = pd.DataFrame({
        'Zone': ['Sicurezza', 'Warning', 'Critico'],
        'Start': [max_y * 0.40, max_y * 0.15, 0],
        'End':   [max_y * 1.10, max_y * 0.40, max_y * 0.15],
        'Color': ['#66BB6A', '#FFA726', '#EF5350'] 
    })
    
    background = alt.Chart(zones_df).mark_rect(opacity=0.2).encode(
        y=alt.Y('Start', title='Glicogeno Totale (g)', scale=alt.Scale(domain=[0, max_y])),
        y2='End',
        color=alt.Color('Color', scale=None),
        tooltip=['Zone']
    )
    
    area = alt.Chart(df_data).mark_area(line=True, opacity=0.8).encode(
        x='Time (min)',
        y='Residuo Totale',
        tooltip=['Time (min)', 'Residuo Totale']
    )
    
    return (background + area).properties(title=title, height=300)

# --- NAVIGAZIONE ---
tab1, tab2, tab3 = st.tabs(["1. Profilo Atleta", "2. Stato Nutrizionale", "3. Simulazione Gara"])

# =============================================================================
# TAB 1: PROFILO ATLETA
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
        
        use_smm = st.checkbox("Inserimento manuale SMM (Massa Muscolare Scheletrica)")
        muscle_mass_input = st.number_input("SMM [kg]", 10.0, 60.0, 37.4, 0.1) if use_smm else None
        
        st.markdown("---")
        st.subheader("Parametri Fisiologici")
        vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, 1)
        calculated_conc = logic.get_concentration_from_vo2max(vo2_input)
        
        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina Sportiva", list(sport_map.keys()))]
        
        # Gestione Soglie
        if s_sport == SportType.CYCLING:
            ftp_watts = st.number_input("FTP (Watt)", 100, 600, 265)
            thr_hr = 170
        else:
            ftp_watts = 265
            thr_hr = st.number_input("Soglia Anaerobica (BPM)", 100, 220, 170)
            
        max_hr = st.number_input("Frequenza Cardiaca Max (BPM)", 100, 230, 185)
        
        # Persistenza stato
        st.session_state.update({'ftp_watts_input': ftp_watts, 'thr_hr_input': thr_hr, 'max_hr_input': max_hr})
        
        subject = Subject(weight, height, bf, s_sex, calculated_conc, s_sport, muscle_mass_kg=muscle_mass_input, uses_creatine=st.checkbox("Supplementazione Creatina"))
        tank_data = logic.calculate_tank(subject)
        st.session_state['base_subject_struct'] = subject
        st.session_state['base_tank_data'] = tank_data

    with col_res:
        st.subheader("Analisi Capacità di Stoccaggio")
        st.metric("Capacità Totale Glicogeno", f"{int(tank_data['max_capacity_g'])} g")
        st.progress(100)
        
        c1, c2 = st.columns(2)
        c1.metric("Massa Muscolare Attiva", f"{tank_data['active_muscle_kg']:.1f} kg")
        c2.metric("Conc. Glicogeno Stimata", f"{calculated_conc:.1f} g/kg")
        
        st.markdown("### Zone di Allenamento")
        if s_sport == SportType.CYCLING:
            zones = utils.calculate_zones_cycling(ftp_watts)
        else:
            zones = utils.calculate_zones_running_hr(thr_hr)
        st.dataframe(pd.DataFrame(zones), hide_index=True, use_container_width=True)

# =============================================================================
# TAB 2: STATO NUTRIZIONALE
# =============================================================================
with tab2:
    if 'base_tank_data' not in st.session_state: st.stop()
    
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        st.subheader("Protocollo di Carico (48h pre-evento)")
        cho_g1 = st.number_input("CHO Assunti Ieri (g)", 0, 1200, 400, step=50)
        cho_g2 = st.number_input("CHO Assunti Altroieri (g)", 0, 1200, 400, step=50)
        
        f_map = {f.label: f for f in FatigueState}
        s_fatigue = f_map[st.selectbox("Stato di Affaticamento", list(f_map.keys()))]
        
        s_map = {s.label: s for s in SleepQuality}
        s_sleep = s_map[st.selectbox("Qualità del Sonno", list(s_map.keys()))]
        
        comb_fill, _, _, _, _ = logic.calculate_filling_factor_from_diet(weight, cho_g1, cho_g2, s_fatigue, s_sleep, 0,0,0,0)
        
        subj_prep = st.session_state['base_subject_struct']
        subj_prep.filling_factor = comb_fill
        curr_tank = logic.calculate_tank(subj_prep)
        st.session_state.update({'tank_data': curr_tank, 'subject_struct': subj_prep})
        
    with col_p2:
        st.metric("Livello Riempimento Attuale", f"{curr_tank['fill_pct']:.1f}%")
        st.progress(int(curr_tank['fill_pct']))
        
        col_m, col_l = st.columns(2)
        col_m.metric("Glicogeno Muscolare", f"{int(curr_tank['muscle_glycogen_g'])} g")
        col_l.metric("Glicogeno Epatico", f"{int(curr_tank['liver_glycogen_g'])} g")

# =============================================================================
# TAB 3: SIMULAZIONE GARA
# =============================================================================
with tab3:
    if 'tank_data' not in st.session_state: st.stop()
    
    tank = st.session_state['tank_data']
    subj = st.session_state['subject_struct']
    start_total = tank['actual_available_g']
    
    # --- CONFIGURAZIONE SIMULAZIONE ---
    c_set1, c_set2, c_set3 = st.columns(3)
    
    with c_set1:
        st.markdown("### 1. Profilo Sforzo")
        duration = st.number_input("Durata (min)", 60, 900, 180, step=10)
        
        # Gestione File Esterno
        upl_file = st.file_uploader("Upload File (.zwo)", type=['zwo'])
        intensity_series = None
        
        if upl_file:
            series, dur_calc, p_calc, hr_calc = utils.parse_zwo_file(upl_file, st.session_state['ftp_watts_input'], st.session_state['thr_hr_input'], subj.sport)
            if series:
                intensity_series = series
                duration = dur_calc
                st.success(f"File caricato: {dur_calc} min.")
        
        if subj.sport == SportType.CYCLING:
            val = st.number_input("Watt Medi Previsti", 100, 500, 200)
            params = {'mode': 'cycling', 'avg_watts': val, 'ftp_watts': st.session_state['ftp_watts_input'], 'efficiency': 22.0}
        else:
            val = st.number_input("FC Media Prevista", 100, 220, 150)
            params = {'mode': 'running', 'avg_hr': val, 'threshold_hr': st.session_state['thr_hr_input']}
            
    with c_set2:
        st.markdown("### 2. Strategia Nutrizionale")
        cho_h = st.slider("Target CHO (g/h)", 0, 120, 60, step=10)
        cho_unit = st.number_input("Grammi CHO per Unità (Gel/Barretta)", 10, 100, 25)
        
    with c_set3:
        st.markdown("### 3. Cinetica di Assorbimento")
        mix_sel = st.selectbox("Tipologia Carboidrati", list(ChoMixType), format_func=lambda x: x.label)
        tau = st.slider("Costante Tau (Assorbimento)", 5, 60, 20, help="Minore è il valore, più rapido è l'ingresso in circolo.")
        risk_thresh = st.slider("Soglia Tolleranza GI (g)", 10, 80, 30, help="Accumulo massimo tollerato nello stomaco.")

    # --- ESECUZIONE SIMULAZIONE ---
    
    # 1. Scenario con Strategia
    df_sim, stats_sim = logic.simulate_metabolism(tank, duration, cho_h, cho_unit, 70, tau, subj, params, mix_type_input=mix_sel, intensity_series=intensity_series)
    df_sim['Scenario'] = 'Strategia Integrata'
    # Calcolo esplicito per evitare KeyError
    df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']
    
    # 2. Scenario Riferimento (Digiuno/Solo Acqua)
    df_no, _ = logic.simulate_metabolism(tank, duration, 0, cho_unit, 70, tau, subj, params, mix_type_input=mix_sel, intensity_series=intensity_series)
    df_no['Scenario'] = 'Riferimento (Digiuno)'
    df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']

    # --- DASHBOARD RISULTATI ---
    st.markdown("---")
    
    # ROW 1: Grafici Bilancio e KPI
    r1_c1, r1_c2 = st.columns([2, 1])
    
    with r1_c1:
        st.markdown("#### Bilancio Energetico (Rateo Orario)")
        df_melt = df_sim.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        
        # Definizione ordine di visualizzazione (Stack)
        order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
        colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']
        
        chart_stack = alt.Chart(df_melt).mark_area().encode(
            x='Time (min)', y='g/h', 
            color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        ).properties(height=350)
        st.altair_chart(chart_stack, use_container_width=True)
        
    with r1_c2:
        st.markdown("#### KPI Prestazionali")
        fin_gly = stats_sim['final_glycogen']
        delta = fin_gly - start_total
        
        st.metric("Glicogeno Residuo Finale", f"{int(fin_gly)} g", delta=f"{int(delta)} g")
        st.metric("Intensità Media (IF)", f"{stats_sim['intensity_factor']:.2f}")
        st.metric("Carboidrati Totali Ossidati", f"{int(stats_sim['total_exo_used'] + stats_sim['total_muscle_used'] + stats_sim['total_liver_used'])} g")
        st.metric("Grassi Totali Ossidati", f"{int(stats_sim['fat_total_g'])} g")

    # ROW 2: Analisi Rischi
    st.markdown("---")
    r2_c1, r2_c2 = st.columns(2)
    
    with r2_c1:
        st.markdown("#### Analisi Deplezione e Rischio Bonk")
        chart_strat = create_risk_zone_chart(df_sim, "Scenario: Strategia Integrata", start_total)
        chart_fast = create_risk_zone_chart(df_no, "Scenario: Riferimento (Digiuno)", start_total)
        st.altair_chart(alt.vconcat(chart_strat, chart_fast), use_container_width=True)
        
    with r2_c2:
        st.markdown("#### Analisi Tolleranza Gastrointestinale (Gut Load)")
        
        # Area: Accumulo nello stomaco
        base = alt.Chart(df_sim).encode(x='Time (min)')
        area_gut = base.mark_area(color='#795548', opacity=0.6).encode(
            y=alt.Y('Gut Load', title='Accumulo Stomaco (g)'),
            tooltip=['Gut Load']
        )
        
        # Linea: Soglia di rischio
        rule = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        
        # Linee: Flussi Ingestione vs Ossidazione (Asse secondario simulato tramite layer)
        line_intake = base.mark_line(color='#1E88E5', interpolate='step-after').encode(
            y=alt.Y('Intake Cumulativo (g)', axis=alt.Axis(title='Cumulativo (g)', orient='right'))
        )
        line_ox = base.mark_line(color='#43A047').encode(
            y=alt.Y('Ossidazione Cumulativa (g)', axis=None)
        )

        chart_gi = alt.layer(area_gut, rule, line_intake, line_ox).resolve_scale(y='independent').properties(height=350)
        st.altair_chart(chart_gi, use_container_width=True)
        
        # Avvisi testuali
        max_gut = df_sim['Gut Load'].max()
        if max_gut > risk_thresh:
            st.error(f"⚠️ Attenzione: L'accumulo gastrico ({int(max_gut)}g) supera la soglia di tolleranza impostata.")
        else:
            st.success(f"✅ Tolleranza GI rispettata. Picco accumulo: {int(max_gut)}g")

    # ... (tutto il codice precedente del Tab 3 rimane uguale)

    # PIANO D'AZIONE E CRONOTABELLA
    st.markdown("---")
    st.markdown("### 📋 Cronotabella di Integrazione")

    if cho_h > 0 and cho_unit > 0:
        # Calcolo frequenza di assunzione
        units_per_hour = cho_h / cho_unit
        interval_minutes = 60 / units_per_hour
        interval_rounded = int(interval_minutes)
        
        schedule = []
        current_time = interval_rounded
        total_ingested = 0
        
        # Generazione della tabella temporale
        while current_time <= duration:
            total_ingested += cho_unit
            schedule.append({
                "Timing Gara": f"Minuto {current_time}",
                "Azione Richiesta": f"Assumere 1 unità ({cho_unit}g CHO)",
                "Totale Cumulativo": f"{total_ingested}g"
            })
            current_time += interval_rounded
            
        if schedule:
            # Visualizzazione tabellare pulita
            df_schedule = pd.DataFrame(schedule)
            st.table(df_schedule)
            
            # Riepilogo logistico
            total_units = len(schedule)
            st.info(
                f"**Riepilogo Logistico:** Preparare **{total_units} unità** totali. "
                f"Impostare un alert sull'orologio ogni **{interval_rounded} minuti**."
            )
        else:
            st.warning("La durata dell'evento è inferiore all'intervallo di assunzione calcolato. Nessuna integrazione necessaria.")
    else:
        st.info("Nessuna strategia di integrazione impostata (Target CHO = 0).")
