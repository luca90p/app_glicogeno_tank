import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
from data_models import SportType

# --- SISTEMA DI PROTEZIONE (LOGIN) ---
def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == "glicogeno2025": 
            st.session_state["password_correct"] = True
            del st.session_state["password"]  
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔐 Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔐 Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password errata.")
        return False
    else:
        return True

# --- LOGICA DI PARSING ZWO ---
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
    except Exception as e:
        st.error(f"Errore nella lettura del file: {e}")
        return [], 0, 0, 0

    zwo_sport_tag = root.findtext('sportType')
    
    if zwo_sport_tag:
        # Nota: usiamo sport_type.value o sport_type per confronti a seconda dell'enum
        if zwo_sport_tag.lower() == 'bike' and sport_type != SportType.CYCLING:
            st.warning(f"⚠️ File per BICI ma sport selezionato: {sport_type.label}")
        elif zwo_sport_tag.lower() == 'run' and sport_type != SportType.RUNNING:
            st.warning(f"⚠️ File per CORSA ma sport selezionato: {sport_type.label}")

    intensity_series = [] 
    total_duration_sec = 0
    total_weighted_if = 0
    
    # Trova tutti gli elementi SteadyState nel file XML
    for steady_state in root.findall('.//SteadyState'):
        try:
            duration_sec = int(steady_state.get('Duration'))
            power_ratio = float(steady_state.get('Power'))
            
            duration_min_segment = math.ceil(duration_sec / 60)
            intensity_factor = power_ratio 
            
            for _ in range(duration_min_segment):
                intensity_series.append(intensity_factor)
            
            total_duration_sec += duration_sec
            total_weighted_if += intensity_factor * (duration_sec / 60) 

        except Exception:
            continue

    total_duration_min = math.ceil(total_duration_sec / 60)
    
    avg_power = 0
    avg_hr = 0

    if total_duration_min > 0:
        avg_if = total_weighted_if / total_duration_min
        
        if sport_type == SportType.CYCLING:
            avg_power = avg_if * ftp_watts
        elif sport_type == SportType.RUNNING:
            avg_hr = avg_if * thr_hr
        else: 
            # Fallback per altri sport usando input session state se esiste, altrimenti default
            max_hr_ref = st.session_state.get('max_hr_input', 185)
            avg_hr = avg_if * max_hr_ref * 0.85 
            
        return intensity_series, total_duration_min, avg_power, avg_hr
    
    return [], 0, 0, 0

# --- FUNZIONI ZONE ---
def calculate_zones_cycling(ftp):
    return [
        {"Zona": "Z1 - Recupero Attivo", "Range %": "< 55%", "Valore": f"< {int(ftp*0.55)} W"},
        {"Zona": "Z2 - Endurance", "Range %": "56 - 75%", "Valore": f"{int(ftp*0.56)} - {int(ftp*0.75)} W"},
        {"Zona": "Z3 - Tempo", "Range %": "76 - 90%", "Valore": f"{int(ftp*0.76)} - {int(ftp*0.90)} W"},
        {"Zona": "Z4 - Soglia (FTP)", "Range %": "91 - 105%", "Valore": f"{int(ftp*0.91)} - {int(ftp*1.05)} W"},
        {"Zona": "Z5 - VO2max", "Range %": "106 - 120%", "Valore": f"{int(ftp*1.06)} - {int(ftp*1.20)} W"},
        {"Zona": "Z6 - Anaerobica", "Range %": "121 - 150%", "Valore": f"{int(ftp*1.21)} - {int(ftp*1.50)} W"},
        {"Zona": "Z7 - Neuromuscolare", "Range %": "> 150%", "Valore": f"> {int(ftp*1.50)} W"}
    ]

def calculate_zones_running_hr(thr):
    return [
        {"Zona": "Z1 - Recupero", "Range %": "< 85% LTHR", "Valore": f"< {int(thr*0.85)} bpm"},
        {"Zona": "Z2 - Aerobico", "Range %": "85 - 89% LTHR", "Valore": f"{int(thr*0.85)} - {int(thr*0.89)} bpm"},
        {"Zona": "Z3 - Tempo", "Range %": "90 - 94% LTHR", "Valore": f"{int(thr*0.90)} - {int(thr*0.94)} bpm"},
        {"Zona": "Z4 - Sub-Soglia", "Range %": "95 - 99% LTHR", "Valore": f"{int(thr*0.95)} - {int(thr*0.99)} bpm"},
        {"Zona": "Z5a - Soglia (FTP)", "Range %": "100 - 102% LTHR", "Valore": f"{int(thr*1.00)} - {int(thr*1.02)} bpm"},
        {"Zona": "Z5b - Cap. Aerobica", "Range %": "103 - 106% LTHR", "Valore": f"{int(thr*1.03)} - {int(thr*1.06)} bpm"},
        {"Zona": "Z5c - Pot. Anaerobica", "Range %": "> 106% LTHR", "Valore": f"> {int(thr*1.06)} bpm"}
    ]
