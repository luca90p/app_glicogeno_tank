import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import math

# Imports dai moduli locali
import logic
import utils
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject
)

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
st.title("Glycogen Simulator Pro")
st.markdown("""
Applicazione avanzata per la modellazione delle riserve di glicogeno muscolare ed epatico. 
Il sistema utilizza equazioni differenziali per stimare i tassi di ossidazione, l'accumulo intestinale e la cinetica di assorbimento dei carboidrati.
""")

# --- SISTEMA DI AUTENTICAZIONE ---
if not utils.check_password():
    st.stop()

# --- FUNZIONI DI VISUALIZZAZIONE ---
def create_risk_zone_chart(df_data, title, max_y):
    """
    Genera un grafico con bande di colore per indicare le zone di rischio deplezione.
    Verde: Zona di sicurezza.
    Giallo: Warning (riserve ridotte).
    Rosso: Criticità (rischio bonk/ipoglicemia).
    """
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

# --- STRUTTURA APPLICAZIONE ---
tab1, tab2, tab3 = st.tabs([
    "1. Profilo Fisiologico & Capacità", 
    "2. Tapering & Stato Nutrizionale", 
    "3. Simulazione Gara & Strategia"
])

# =============================================================================
# TAB 1: PROFILO FISIOLOGICO & CAPACITÀ
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
        
        # LOGICA RECUPERATA: Selezione metodo stima
        est_method = st.radio(
            "Metodo di Stima Densità Glicogeno:", 
            ["Basato su Livello Atletico (Consigliato)", "Basato su VO2max (Lab)"],
            help="La densità di glicogeno muscolare (g/kg di muscolo) varia notevolmente con l'allenamento."
        )
        
        calculated_conc = 0.0
        vo2_derived = 0.0
        
        if est_method == "Basato su Livello Atletico (Consigliato)":
            status_map = {s.label: s for s in TrainingStatus}
            s_status = status_map[st.selectbox("Livello di Allenamento", list(status_map.keys()), index=3)]
            calculated_conc = s_status.val
            # Stima inversa del VO2max solo per fini computazionali interni
            vo2_derived = 30 + ((calculated_conc - 13.0) / 0.24)
            st.info(f"Densità Stimata: {calculated_conc} g/kg (Tipica di atleti {s_status.name})")
        else:
            vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, 1)
            calculated_conc = logic.get_concentration_from_vo2max(vo2_input)
            vo2_derived = vo2_input
            st.info(f"Densità Derivata: {calculated_conc:.1f} g/kg")
            
        

        st.markdown("---")
        st.subheader("Specificità Sportiva")
        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina", list(sport_map.keys()))]
        
        # Input Soglie
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
            
        # Salvataggio stato
        st.session_state.update({'ftp_watts_input': ftp_watts, 'thr_hr_input': thr_hr, 'max_hr_input': max_hr})
        
        # Fattori avanzati
        with st.expander("Variabili Aggiuntive"):
            use_creatine = st.checkbox("Supplementazione Creatina (+10% Stoccaggio)")
            s_menstrual = MenstrualPhase.NONE
            if s_sex == Sex.FEMALE:
                m_map = {m.label: m for m in MenstrualPhase}
                s_menstrual = m_map[st.selectbox("Fase Ciclo Mestruale", list(m_map.keys()))]

        # Creazione Oggetto Subject
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
        st.caption("Il valore rappresenta la capacità fisiologica massima in condizioni di supercompensazione perfetta.")
        
        st.markdown("### Zone di Allenamento")
        if s_sport == SportType.CYCLING:
            zones = utils.calculate_zones_cycling(ftp_watts)
        else:
            zones = utils.calculate_zones_running_hr(thr_hr if s_sport == SportType.RUNNING else max_hr*0.85)
        
        df_zones = pd.DataFrame(zones)
        st.table(df_zones)

# =============================================================================
# TAB 2: TAPERING & STATO NUTRIZIONALE
# =============================================================================
with tab2:
    if 'base_tank_data' not in st.session_state:
        st.warning("Completare prima il Tab 1.")
        st.stop()
        
    subj_base = st.session_state['base_subject_struct']
    weight = subj_base.weight_kg
    
    st.subheader("Stato Nutrizionale Attuale (Ultime 48h)")
    col_p1, col_p2 = st.columns(2)
    
    with col_p1:
        st.markdown("**Carico Carboidrati Recente**")
        cho_g1 = st.number_input("CHO Ieri (g)", 0, 1500, 400, step=50, help="Carboidrati totali assunti nelle 24h precedenti")
        cho_g2 = st.number_input("CHO Altroieri (g)", 0, 1500, 400, step=50)
        
        f_map = {f.label: f for f in FatigueState}
        s_fatigue = f_map[st.selectbox("Livello di Affaticamento", list(f_map.keys()))]
        
        s_map = {s.label: s for s in SleepQuality}
        s_sleep = s_map[st.selectbox("Qualità del Sonno", list(s_map.keys()))]
        
        # Calcolo riempimento puntuale
        comb_fill, _, _, _, _ = logic.calculate_filling_factor_from_diet(weight, cho_g1, cho_g2, s_fatigue, s_sleep, 0,0,0,0)
        
        # Aggiornamento stato
        subj_prep = st.session_state['base_subject_struct']
        subj_prep.filling_factor = comb_fill
        curr_tank = logic.calculate_tank(subj_prep)
        st.session_state.update({'tank_data': curr_tank, 'subject_struct': subj_prep})
        
    with col_p2:
        st.metric("Riempimento Attuale (Filling Factor)", f"{curr_tank['fill_pct']:.1f}%")
        st.progress(curr_tank['fill_pct'] / 100.0)
        
        m_val = int(curr_tank['muscle_glycogen_g'])
        l_val = int(curr_tank['liver_glycogen_g'])
        
        chart_data = pd.DataFrame({
            'Tipo': ['Muscolare', 'Epatico'],
            'Grammi': [m_val, l_val]
        })
        
        base = alt.Chart(chart_data).encode(theta=alt.Theta("Grammi", stack=True))
        pie = base.mark_arc(outerRadius=80).encode(
            color=alt.Color("Tipo", scale=alt.Scale(range=['#E57373', '#B71C1C'])),
            tooltip=["Tipo", "Grammi"]
        )
        text = base.mark_text(radius=100).encode(
            text="Grammi",
            order=alt.Order("Grammi", sort="descending"),
            color=alt.value("black")  
        )
        st.altair_chart(pie + text, use_container_width=True)

    st.markdown("---")
    
    # --- DIARIO SETTIMANALE (FUNZIONALITA' RECUPERATA) ---
    st.subheader("Diario di Tapering (Pianificazione Settimanale)")
    # --- DIARIO DI TAPERING (COUNTDOWN) ---
    st.markdown("---")
    st.subheader("Diario di Tapering (Countdown Gara)")
    st.markdown("""
    Pianifica la settimana di avvicinamento. 
    **Nota:** I giorni **-2** e **-1** sono bloccati e sincronizzati con i dati inseriti nel pannello "Stato Nutrizionale" in alto per garantire coerenza.
    """)
    
    with st.expander("Apri/Chiudi Pianificatore Countdown", expanded=True):
        # Definizione labels relative all'evento
        days_labels = [
            "-6 Giorni", "-5 Giorni", "-4 Giorni", "-3 Giorni", 
            "-2 Giorni", "-1 Giorno", "Race Day (Gara)"
        ]
        
        weekly_schedule = []
        
        # Intestazione Colonne
        c_h1, c_h2, c_h3, c_h4 = st.columns([1.2, 1.5, 1.5, 1])
        c_h1.markdown("**Meno...**")
        c_h2.markdown("**Attività**")
        c_h3.markdown("**Intensità**")
        c_h4.markdown("**CHO (g)**")
        
        for i, d_label in enumerate(days_labels):
            c1, c2, c3, c4 = st.columns([1.2, 1.5, 1.5, 1])
            
            # Stile visuale per evidenziare i giorni bloccati
            is_day_minus_2 = (i == 4) # Indice 4 è "-2 Giorni"
            is_day_minus_1 = (i == 5) # Indice 5 è "-1 Giorno"
            is_locked = is_day_minus_2 or is_day_minus_1
            
            # Label Giorno
            if is_locked:
                c1.info(f"**{d_label}**")
            elif i == 6:
                c1.error(f"**{d_label}**") # Rosso per la gara
            else:
                c1.write(f"**{d_label}**")
            
            # Chiavi univoche per i widget
            act_key = f"act_d{i}"
            dur_key = f"dur_d{i}"
            int_key = f"int_d{i}"
            cho_key = f"cho_d{i}"
            
            # Logica Attività
            # Default: Attivo per tutti tranne magari i primi giorni di scarico, ma lasciamo scelta
            activity = c2.selectbox("", ["Riposo", "Attivo"], key=act_key, label_visibility="collapsed")
            
            duration = 0
            intensity = "Riposo"
            
            if activity == "Attivo":
                duration = c2.number_input(f"Min {i}", 0, 600, 60, key=dur_key, label_visibility="collapsed")
                intensity = c3.selectbox(f"Int {i}", ["Bassa (Z1-Z2)", "Media (Z3)", "Alta (Z4+)"], key=int_key, label_visibility="collapsed")
            else:
                c3.write(" - ")
            
            # Logica CHO (Gestione Lock)
            default_cho = 350
            if is_day_minus_2:
                default_cho = int(cho_g2) # Prende dal blocco superiore
            elif is_day_minus_1:
                default_cho = int(cho_g1) # Prende dal blocco superiore
            
            # Il widget è disabilitato se è un giorno lock
            cho_in = c4.number_input(
                f"CHO {i}", 
                0, 1500, 
                value=default_cho, 
                key=cho_key, 
                disabled=is_locked, # QUI AVVIENE IL BLOCCO
                label_visibility="collapsed"
            )
            
            weekly_schedule.append({
                "day": d_label, 
                "activity": activity, 
                "duration": duration, 
                "intensity": intensity, 
                "cho_in": cho_in
            })
            
        if st.button("Calcola Trend Tapering"):
            # Parametri simulazione settimanale
            # Assumiamo che a -7 giorni si parta con riserve non piene (allenamento cronico)
            init_muscle = tank_data['max_capacity_g'] * 0.60 
            init_liver = 80
            max_muscle = tank_data['max_capacity_g']
            max_liver = 120
            
            # Stima VO2 relativo per calcoli consumo giornaliero
            vo2_calc = subj_base.vo2max_absolute_l_min * 1000 / weight 
            
            df_week = logic.calculate_weekly_balance(init_muscle, init_liver, max_muscle, max_liver, weekly_schedule, weight, vo2_calc)
            
            # Grafico Trend
            # Usiamo un grafico a step o linea per mostrare l'accumulo
            chart_trend = alt.Chart(df_week).mark_line(point=True, strokeWidth=3).encode(
                x=alt.X('Giorno', sort=days_labels, title='Countdown'),
                y=alt.Y('Totale', title='Glicogeno Totale (g)', scale=alt.Scale(zero=False)),
                color=alt.value('#2E7D32'),
                tooltip=['Giorno', 'Totale', 'Glicogeno Muscolare', 'Glicogeno Epatico']
            ).properties(height=300, title="Carico Glicogeno Pre-Gara (Simulazione)")
            
            st.altair_chart(chart_trend, use_container_width=True)
            
            # Tabella riassuntiva pulita
            st.dataframe(df_week[['Giorno', 'Totale', 'Glicogeno Muscolare', 'Glicogeno Epatico']], hide_index=True, use_container_width=True)

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
    
    # --- INPUT SETUP ---
    c_s1, c_s2, c_s3 = st.columns(3)
    
    with c_s1:
        st.markdown("### 1. Profilo Sforzo")
        duration = st.number_input("Durata (min)", 60, 900, 180, step=10)
        
        # Caricamento File ZWO/FIT
        uploaded_file = st.file_uploader("Importa File (.zwo)", type=['zwo'])
        intensity_series = None
        
        if uploaded_file:
            series, dur_calc, w_calc, hr_calc = utils.parse_zwo_file(uploaded_file, st.session_state['ftp_watts_input'], st.session_state['thr_hr_input'], subj.sport)
            if series:
                intensity_series = series
                duration = dur_calc
                st.success(f"File importato con successo: {dur_calc} minuti.")
        
        # Parametri Manuali
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
        
        
        
        tau = st.slider("Costante Assorbimento (Tau)", 5, 60, 20, help="Tempo necessario affinché i CHO ingeriti siano disponibili nel sangue.")
        risk_thresh = st.slider("Soglia Tolleranza GI (g)", 10, 100, 30, help="Massimo accumulo gastrico tollerabile.")

    # --- CALCOLO SIMULAZIONE ---
    # Scenario A: Strategia Integrata
    df_sim, stats_sim = logic.simulate_metabolism(tank, duration, cho_h, cho_unit, 70, tau, subj, params, mix_type_input=mix_sel, intensity_series=intensity_series)
    df_sim['Scenario'] = 'Strategia Integrata'
    df_sim['Residuo Totale'] = df_sim['Residuo Muscolare'] + df_sim['Residuo Epatico']
    
    # Scenario B: Riferimento (Digiuno/Acqua)
    df_no, _ = logic.simulate_metabolism(tank, duration, 0, cho_unit, 70, tau, subj, params, mix_type_input=mix_sel, intensity_series=intensity_series)
    df_no['Scenario'] = 'Riferimento (Digiuno)'
    df_no['Residuo Totale'] = df_no['Residuo Muscolare'] + df_no['Residuo Epatico']

    # --- VISUALIZZAZIONE RISULTATI ---
    st.markdown("---")
    
    # Sezione 1: Bilancio Energetico
    r1_c1, r1_c2 = st.columns([2, 1])
    
    with r1_c1:
        st.markdown("#### Bilancio Energetico e Substrati")
        df_melt = df_sim.melt('Time (min)', value_vars=['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)'], var_name='Fonte', value_name='g/h')
        
        order = ['Glicogeno Epatico (g)', 'Carboidrati Esogeni (g)', 'Ossidazione Lipidica (g)', 'Glicogeno Muscolare (g)']
        colors = ['#B71C1C', '#1E88E5', '#FFCA28', '#EF5350']
        
        chart_stack = alt.Chart(df_melt).mark_area().encode(
            x='Time (min)', y='g/h', 
            color=alt.Color('Fonte', scale=alt.Scale(domain=order, range=colors), sort=order),
            tooltip=['Time (min)', 'Fonte', 'g/h']
        ).properties(height=350, title="Ripartizione Fonti Energetiche nel Tempo")
        st.altair_chart(chart_stack, use_container_width=True)
        
    with r1_c2:
        st.markdown("#### KPI Prestazionali")
        fin_gly = stats_sim['final_glycogen']
        delta = fin_gly - start_total
        
        st.metric("Glicogeno Residuo", f"{int(fin_gly)} g", delta=f"{int(delta)} g")
        st.metric("Intensità (IF)", f"{stats_sim['intensity_factor']:.2f}")
        st.metric("CHO Ossidati (Tot)", f"{int(stats_sim['total_exo_used'] + stats_sim['total_muscle_used'] + stats_sim['total_liver_used'])} g")
        st.metric("FAT Ossidati (Tot)", f"{int(stats_sim['fat_total_g'])} g")

    # Sezione 2: Rischi (Bonk & GI)
    st.markdown("---")
    r2_c1, r2_c2 = st.columns(2)
    
    with r2_c1:
        st.markdown("#### Analisi Deplezione (Zone di Rischio)")
        chart_strat = create_risk_zone_chart(df_sim, "Scenario: Con Integrazione", start_total)
        chart_fast = create_risk_zone_chart(df_no, "Scenario: Digiuno (Controllo)", start_total)
        st.altair_chart(alt.vconcat(chart_strat, chart_fast), use_container_width=True)
        
        if fin_gly < 50:
            st.error("⚠️ CRITICITÀ RILEVATA: Le riserve finali sono prossime all'esaurimento.")
        else:
            st.success("✅ STRATEGIA SOSTENIBILE: Riserve energetiche sufficienti.")
        
    with r2_c2:
        st.markdown("#### Analisi Tolleranza Gastrointestinale (Gut Load)")
        st.markdown("Monitoraggio dell'accumulo di carboidrati non assorbiti nello stomaco/intestino.")
        
        base = alt.Chart(df_sim).encode(x='Time (min)')
        
        # Area Accumulo
        area_gut = base.mark_area(color='#795548', opacity=0.6).encode(
            y=alt.Y('Gut Load', title='Accumulo (g)'),
            tooltip=['Gut Load']
        )
        # Linea Soglia
        rule = alt.Chart(pd.DataFrame({'y': [risk_thresh]})).mark_rule(color='red', strokeDash=[5,5]).encode(y='y')
        
        # Linee Flusso (Scala Indipendente simulata)
        line_intake = base.mark_line(color='#1E88E5', interpolate='step-after').encode(
            y=alt.Y('Intake Cumulativo (g)', axis=alt.Axis(title='Flusso Cumulativo (g)', orient='right'))
        )
        line_ox = base.mark_line(color='#43A047').encode(
            y=alt.Y('Ossidazione Cumulativa (g)', axis=None)
        )

        chart_gi = alt.layer(area_gut, rule, line_intake, line_ox).resolve_scale(y='independent').properties(height=350)
        st.altair_chart(chart_gi, use_container_width=True)
        
        max_gut = df_sim['Gut Load'].max()
        if max_gut > risk_thresh:
            st.warning(f"⚠️ Rischio Distress GI: Il picco di accumulo ({int(max_gut)}g) supera la soglia.")

    # --- CRONOTABELLA DI INTEGRAZIONE (FUNZIONALITA' RECUPERATA) ---
    st.markdown("---")
    st.markdown("### 📋 Cronotabella Operativa")
    
    if cho_h > 0 and cho_unit > 0:
        units_per_hour = cho_h / cho_unit
        interval_minutes = 60 / units_per_hour
        interval_rounded = int(interval_minutes)
        
        schedule = []
        current_time = interval_rounded
        total_ingested = 0
        unit_count = 0
        
        while current_time <= duration:
            total_ingested += cho_unit
            unit_count += 1
            schedule.append({
                "Timing (Minuto)": current_time,
                "Azione": f"Assumere 1 unità ({cho_unit}g CHO)",
                "Totale Ingerito (g)": total_ingested
            })
            current_time += interval_rounded
            
        if schedule:
            df_schedule = pd.DataFrame(schedule)
            st.table(df_schedule)
            
            st.info(f"""
            **Riepilogo Logistica Gara:**
            * Portare **{unit_count}** gel/unità totali.
            * Impostare alert dispositivo ogni **{interval_rounded}** minuti.
            * Totale carboidrati previsti: **{total_ingested}g**.
            """)
        else:
            st.warning("La durata dell'evento è troppo breve per la frequenza di integrazione impostata.")
    else:
        st.info("Nessuna strategia di integrazione definita (Target CHO = 0).")

