import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import io

# Imports dai nostri nuovi moduli
from data_models import (
    Sex, TrainingStatus, SportType, DietType, FatigueState, 
    SleepQuality, MenstrualPhase, ChoMixType, Subject
)
import logic
import utils

# --- SETUP PAGINA ---
st.set_page_config(page_title="Glycogen Simulator Pro", layout="wide")
st.title("Glycogen Simulator Pro")

if not utils.check_password():
    st.stop()

tab1, tab2, tab3 = st.tabs(["1. Profilo Base & Capacità", "2. Preparazione & Diario", "3. Simulazione & Strategia"])

# --- TAB 1: PROFILO BASE ---
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
        
        st.subheader("2. Capacità (Tank)")
        vo2_input = st.slider("VO2max (ml/kg/min)", 30, 85, 60, step=1)
        calculated_conc = logic.get_concentration_from_vo2max(vo2_input)
        
        sport_map = {s.label: s for s in SportType}
        s_sport = sport_map[st.selectbox("Disciplina", list(sport_map.keys()))]

        # Soglie per simulazione (Salvataggio in session state)
        ftp_watts = st.number_input("FTP / Soglia [Watt]", 100, 600, 265)
        st.session_state['ftp_watts_input'] = ftp_watts
        st.session_state['thr_hr_input'] = 170 # Default hidden for simplicity here
        st.session_state['max_hr_input'] = 185 # Default hidden

        use_creatine = st.checkbox("Usa Creatina")
        
        subject = Subject(
            weight_kg=weight, height_cm=height, body_fat_pct=bf, sex=s_sex,
            glycogen_conc_g_kg=calculated_conc, sport=s_sport,
            uses_creatine=use_creatine, muscle_mass_kg=muscle_mass_input
        )
        tank_data = logic.calculate_tank(subject)
        st.session_state['base_subject_struct'] = subject
        st.session_state['base_tank_data'] = tank_data

    with col_res:
        st.subheader("Riepilogo Capacità")
        st.metric("Energia Max (kcal)", f"{int(tank_data['max_capacity_g'] * 4.1)}")
        st.progress(100)
        st.json(tank_data)

# --- TAB 2: PREPARAZIONE ---
with tab2:
    if 'base_tank_data' not in st.session_state:
        st.warning("Completa Tab 1")
        st.stop()
    
    st.subheader("Stato Pre-Gara")
    weight = st.session_state['base_subject_struct'].weight_kg
    
    cho_g1 = st.number_input("CHO Giorno -1 (g)", 50, 800, 370)
    cho_g2 = st.number_input("CHO Giorno -2 (g)", 50, 800, 370)
    
    fatigue_map = {f.label: f for f in FatigueState}
    s_fatigue = fatigue_map[st.selectbox("Carico Lavoro (Pre)", list(fatigue_map.keys()))]
    
    sleep_map = {s.label: s for s in SleepQuality}
    s_sleep = sleep_map[st.selectbox("Qualità Sonno", list(sleep_map.keys()))]
    
    comb_fill, _, _, _, _ = logic.calculate_filling_factor_from_diet(
        weight, cho_g1, cho_g2, s_fatigue, s_sleep, 0,0,0,0
    )
    
    subj = st.session_state['base_subject_struct']
    subj.filling_factor = comb_fill
    current_tank = logic.calculate_tank(subj)
    st.session_state['tank_data'] = current_tank
    
    st.metric("Riempimento %", f"{current_tank['fill_pct']:.1f}%")

# --- TAB 3: SIMULAZIONE ---
with tab3:
    if 'tank_data' not in st.session_state:
        st.warning("Completa Tab 1 e 2")
        st.stop()
        
    tank = st.session_state['tank_data']
    subj = st.session_state['base_subject_struct']
    
    c1, c2 = st.columns(2)
    duration = c1.slider("Durata (min)", 30, 420, 120, 10)
    avg_w = c1.number_input("Potenza Media (Watt)", 100, 500, 200)
    
    carb_intake = c2.slider("Intake CHO (g/h)", 0, 120, 60)
    mix_type = ChoMixType.GLUCOSE_ONLY # Semplificato per demo
    
    act_params = {
        'mode': 'cycling', 
        'avg_watts': avg_w, 
        'ftp_watts': st.session_state.get('ftp_watts_input', 250)
    }
    
    df, stats = logic.simulate_metabolism(
        tank, duration, carb_intake, 25, 70, 20.0, subj, act_params, mix_type_input=mix_type
    )
    
    st.subheader("Risultati Simulazione")
    col_res1, col_res2 = st.columns(2)
    col_res1.metric("Glicogeno Residuo", f"{int(stats['final_glycogen'])} g")
    col_res2.metric("Rischio GI (Gut)", f"{int(df['Gut Load'].max())} g")
    
    chart = alt.Chart(df).mark_area(opacity=0.6).encode(
        x='Time (min)',
        y='Residuo Muscolare',
        color=alt.value('red')
    )
    st.altair_chart(chart, use_container_width=True)
    st.dataframe(df)
