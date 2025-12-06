import streamlit as st
import xml.etree.ElementTree as ET
import math
import pandas as pd
import numpy as np
import io
import fitparse
import altair as alt
from data_models import SportType

# --- SISTEMA DI PROTEZIONE ---
def check_password():
    def password_entered():
        if st.session_state["password"] == "glicogeno2025": 
            st.session_state["password_correct"] = True
            del st.session_state["password"]  
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Inserisci Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Inserisci Password", type="password", on_change=password_entered, key="password")
        st.error("Password errata.")
        return False
    else:
        return True

# ==============================================================================
# MODULO CALCOLO POTENZA NORMALIZZATA (NP)
# ==============================================================================
def calculate_normalized_power(df):
    if 'power' not in df.columns: return 0
    rolling_pwr = df['power'].rolling(window=30, min_periods=1).mean()
    return (rolling_pwr ** 4).mean() ** 0.25

# ==============================================================================
# MODULO FIT PARSER & PLOTTING
# ==============================================================================

def process_fit_data(fit_file_object):
    """
    Legge file .FIT, normalizza, pulisce pause e restituisce DataFrame.
    """
    try:
        fit_file_object.seek(0)
        fitfile = fitparse.FitFile(fit_file_object)
    except Exception as e:
        return None, f"Errore file FIT: {e}"

    data_list = []
    for record in fitfile.get_messages("record"):
        r_data = {}
        for field in record: r_data[field.name] = field.value
        if 'timestamp' in r_data: data_list.append(r_data)

    if not data_list: return None, "Nessun dato record."

    df_raw = pd.DataFrame(data_list)
    df_raw = df_raw.set_index('timestamp').sort_index()
    
    # Normalizzazione Temporale (1s)
    if not df_raw.empty:
        full_idx = pd.date_range(start=df_raw.index.min(), end=df_raw.index.max(), freq='1s')
        # Forward fill limitato (max 5 sec) per evitare di inventare dati in pause lunghe
        df_raw = df_raw.reindex(full_idx).ffill(limit=5).fillna(0)

    col_map = {
        'power': ['power', 'accumulated_power'],
        'speed': ['enhanced_speed', 'speed'],
        'altitude': ['enhanced_altitude', 'altitude'],
        'heart_rate': ['heart_rate'],
        'cadence': ['cadence'],
        'distance': ['distance']
    }

    df_clean = pd.DataFrame(index=df_raw.index)
    for std, alts in col_map.items():
        for alt in alts:
            if alt in df_raw.columns:
                df_clean[std] = df_raw[alt]
                break 
    
    # Conversione Speed m/s -> km/h
    if 'speed' in df_clean.columns:
        if df_clean['speed'].max() < 100: 
            df_clean['speed_kmh'] = df_clean['speed'] * 3.6
        else:
            df_clean['speed_kmh'] = df_clean['speed']
    else:
        df_clean['speed_kmh'] = 0

    # --- ALGORITMO FILTRO PAUSE MIGLIORATO ---
    # 1. Soglia velocità: < 2.5 km/h è pausa (camminata lenta/fermo)
    # 2. Potenza zero: Se power=0 E speed < 5 km/h per più di 10s -> Pausa
    # 3. Cadenza zero: Se cadenza=0 E speed < 5 km/h -> Pausa (Ciclismo)
    
    is_stopped = df_clean['speed_kmh'] < 2.5
    
    # Maschera finale
    df_final = df_clean[~is_stopped].copy()
    
    # Ricalcolo asse temporale continuo (Moving Time)
    df_final['moving_time_min'] = np.arange(len(df_final)) / 60.0
    
    return df_final, None

def create_fit_plot(df):
    """Genera grafico ALTAIR a 4 pannelli: Power, HR, Cadence, Altitude."""
    # Resampling per performance grafica
    plot_df = df.reset_index()
    if len(plot_df) > 5000: plot_df = plot_df.iloc[::10, :] # Downsample più aggressivo per velocità
    
    base = alt.Chart(plot_df).encode(x=alt.X('moving_time_min', title='Tempo in Movimento (min)'))
    charts = []
    
    # 1. POTENZA
    if 'power' in df.columns and df['power'].max() > 0:
        c_pwr = base.mark_area(color='#FF4B4B', opacity=0.6, line=True).encode(
            y=alt.Y('power', title='Watt'),
            tooltip=['moving_time_min', 'power']
        ).properties(height=150, title="Potenza")
        charts.append(c_pwr)
    
    # 2. CARDIO
    if 'heart_rate' in df.columns and df['heart_rate'].max() > 0:
        c_hr = base.mark_line(color='#A020F0').encode(
            y=alt.Y('heart_rate', title='BPM', scale=alt.Scale(zero=False)),
            tooltip=['moving_time_min', 'heart_rate']
        ).properties(height=150, title="Frequenza Cardiaca")
        charts.append(c_hr)
        
    # 3. ALTIMETRIA (Nuovo!)
    if 'altitude' in df.columns:
        # Area grigia stile Strava
        min_alt = df['altitude'].min()
        c_alt = base.mark_area(color='#90A4AE', opacity=0.4, line={'color':'#546E7A'}).encode(
            y=alt.Y('altitude', title='Metri', scale=alt.Scale(domain=[min_alt, df['altitude'].max()])),
            tooltip=['moving_time_min', 'altitude']
        ).properties(height=150, title="Profilo Altimetrico")
        charts.append(c_alt)

    # 4. CADENZA
    if 'cadence' in df.columns and df['cadence'].max() > 0:
        c_cad = base.transform_filter(alt.datum.cadence > 0).mark_circle(color='#00FF00', size=5, opacity=0.2).encode(
            y=alt.Y('cadence', title='RPM'),
            tooltip=['moving_time_min', 'cadence']
        ).properties(height=100, title="Cadenza")
        charts.append(c_cad)

    if charts:
        return alt.vconcat(*charts).resolve_scale(x='shared')
    else:
        return alt.Chart(pd.DataFrame({'T':['Nessun dato valido']})).mark_text().encode(text='T')

def parse_fit_file_wrapper(uploaded_file, sport_type):
    """Wrapper che estrae dati e calcola statistiche avanzate."""
    df, error = process_fit_data(uploaded_file)
    if error or df is None or df.empty: return [], 0, 0, 0, 0, 0, 0, None

    # Medie su tempo in movimento
    avg_power = df['power'].mean() if 'power' in df.columns else 0
    avg_hr = df['heart_rate'].mean() if 'heart_rate' in df.columns else 0
    norm_power = calculate_normalized_power(df) if 'power' in df.columns else 0
    
    # Statistiche extra per Dashboard
    total_duration_min = math.ceil(len(df) / 60)
    
    dist = 0
    if 'distance' in df.columns:
        dist = (df['distance'].max() - df['distance'].min()) / 1000.0 # km
    elif 'speed_kmh' in df.columns:
        # Stima distanza se manca colonna
        dist = (df['speed_kmh'].mean() * (total_duration_min/60))
        
    elev_gain = 0
    if 'altitude' in df.columns:
        # Calcolo guadagno positivo
        deltas = df['altitude'].diff()
        elev_gain = deltas[deltas > 0].sum()
    
    work_kj = 0
    if 'power' in df.columns:
        work_kj = (avg_power * (total_duration_min * 60)) / 1000
    
    # Resampling per logica simulatore (1 min)
    df_res = df.resample('1T').mean()
    series = []
    target = 'power' if sport_type == SportType.CYCLING and 'power' in df.columns else 'heart_rate'
    if target in df_res.columns:
        series = [float(x) for x in df_res[target].fillna(0).tolist()]
    
    return series, total_duration_min, avg_power, avg_hr, norm_power, dist, elev_gain, work_kj, df

# ==============================================================================
# PARSING METABOLICO (VERSIONE ROBUSTA & DEBUG)
# ==============================================================================
def parse_metabolic_report(uploaded_file):
    try:
        df = None
        # --- 1. GESTIONE FILE CSV / TXT ---
        if uploaded_file.name.lower().endswith(('.csv', '.txt')):
            content = uploaded_file.getvalue().decode('latin-1', errors='replace')
            lines = content.splitlines()
            
            # A. TROVA LA RIGA DI INTESTAZIONE (HEADER)
            header_row = None
            # Termini chiave da cercare (tutti maiuscoli)
            must_have = ["CHO", "FAT"]
            # Almeno uno di questi per l'intensità
            intensity_opts = ["WR", "WATT", "POW", "FC", "HR", "BPM", "SPEED", "VEL", "KM/H"]

            for i, line in enumerate(lines[:300]):
                l_up = line.upper()
                # Cerca riga con CHO, FAT e almeno un indicatore di intensità
                # Nota: Aggiungiamo separatori di controllo per evitare falsi positivi (es. "SPEED" in "XSPEED")
                if all(t in l_up for t in must_have) and any(t in l_up for t in intensity_opts):
                    header_row = i
                    break
            
            if header_row is None:
                return None, None, "Intestazione non trovata. Verifica che il file abbia colonne CHO, FAT e WR/FC."

            # B. DETERMINA IL SEPARATORE
            h_line = lines[header_row]
            sep = ',' 
            if h_line.count(';') > h_line.count(','): sep = ';'
            elif h_line.count('\t') > h_line.count(','): sep = '\t'

            # C. LEGGI DATAFRAME
            uploaded_file.seek(0)
            try:
                # skipinitialspace=True aiuta se ci sono spazi dopo la virgola (es. "WR, FC")
                df = pd.read_csv(uploaded_file, header=header_row, sep=sep, decimal=',', 
                               encoding='latin-1', engine='python', skipinitialspace=True)
            except:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, header=header_row, sep=sep, decimal='.', 
                               encoding='latin-1', engine='python', skipinitialspace=True)

        elif uploaded_file.name.lower().endswith(('.xls', '.xlsx')):
            df = pd.read_excel(uploaded_file)
        else:
            return None, None, "Formato file non supportato."

        if df is None or df.empty: 
            return None, None, "File vuoto."

        # --- 3. MAPPATURA INTELLIGENTE ---
        # Pulizia nomi colonne: Rimuove spazi e trasforma in maiuscolo
        df.columns = [str(c).strip().upper() for c in df.columns]
        cols = df.columns.tolist()
        
        col_map = {}

        def find_exact_or_partial(targets):
            # 1. Cerca corrispondenza esatta (Priorità alta)
            for col in cols:
                if col in targets: return col
            # 2. Cerca corrispondenza parziale (es. "WR (WATT)" contiene "WR")
            for col in cols:
                for t in targets:
                    # Evitiamo match corti pericolosi (es. "V" in "V'O2")
                    if t in col:
                        # Se il target è cortissimo (es "V"), deve essere isolato o quasi
                        if len(t) < 2 and len(col) > 3: continue 
                        return col
            return None

        # Mappatura
        col_map['CHO'] = find_exact_or_partial(['CHO', 'CARBOHYDRATES', 'V\'CO2']) # Fallback
        col_map['FAT'] = find_exact_or_partial(['FAT', 'LIPIDS'])
        
        # Intensità (Cerca nell'ordine: Watt -> Speed -> FC)
        watt_c = find_exact_or_partial(['WR', 'WATT', 'POWER', 'POW', 'LOAD'])
        speed_c = find_exact_or_partial(['SPEED', 'VEL', 'KM/H', 'V']) # 'V' minuscola nel file orig
        fc_c = find_exact_or_partial(['FC', 'HR', 'HEART', 'BPM', 'HF'])
        
        int_type = None
        if watt_c: 
            col_map['Intensity'] = watt_c; int_type = 'watt'
        elif speed_c: 
            col_map['Intensity'] = speed_c; int_type = 'speed'
        elif fc_c: 
            col_map['Intensity'] = fc_c; int_type = 'hr'

        # CHECK ERRORI CON DEBUG INFO
        if not (col_map.get('CHO') and col_map.get('FAT') and int_type):
             # Restituisce l'elenco delle colonne lette per capire cosa manca
             missing = []
             if not col_map.get('CHO'): missing.append("CHO")
             if not col_map.get('FAT'): missing.append("FAT")
             if not int_type: missing.append("INTENSITY (WR/FC/Speed)")
             
             return None, None, f"⚠️ Colonne mancanti: {missing}. \n\nColonne lette dal file: {cols}"

        # --- 4. ESTRAZIONE DATI ---
        clean_df = pd.DataFrame()
        clean_df['Intensity'] = pd.to_numeric(df[col_map['Intensity']], errors='coerce')
        clean_df['CHO'] = pd.to_numeric(df[col_map['CHO']], errors='coerce')
        clean_df['FAT'] = pd.to_numeric(df[col_map['FAT']], errors='coerce')
        
        # Pulizia NaN e Zeri
        clean_df.dropna(inplace=True)
        clean_df = clean_df[clean_df['Intensity'] > 0]
        
        # Ordinamento
        clean_df = clean_df.sort_values('Intensity').reset_index(drop=True)
        
        # Check Unità Misura (Se CHO max < 8, probabilmente sono g/min -> converti in g/h)
        if not clean_df.empty and clean_df['CHO'].max() < 8.0:
            clean_df['CHO'] *= 60
            clean_df['FAT'] *= 60
            
        return clean_df, int_type, None

    except Exception as e:
        return None, None, f"Errore critico parser: {str(e)}"

# --- ZWO ---
def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
        intensity_series = [] 
        total_duration_sec = 0
        total_weighted_if = 0
        for steady_state in root.findall('.//SteadyState'):
            try:
                dur = int(steady_state.get('Duration'))
                pwr = float(steady_state.get('Power'))
                for _ in range(math.ceil(dur / 60)): intensity_series.append(pwr)
                total_duration_sec += dur
                total_weighted_if += pwr * (dur / 60) 
            except: continue
        total_min = math.ceil(total_duration_sec / 60)
        avg_val = 0
        if total_min > 0:
            avg_if = total_weighted_if / total_min
            if sport_type == SportType.CYCLING: avg_val = avg_if * ftp_watts
            elif sport_type == SportType.RUNNING: avg_val = avg_if * thr_hr
            else: avg_val = avg_if * 180 
            return intensity_series, total_min, avg_val, avg_val
        return [], 0, 0, 0
    except: return [], 0, 0, 0

# --- ZONE ---
def calculate_zones_cycling(ftp):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(ftp*p)} W"} for i, p in enumerate([0.55, 0.75, 0.90, 1.05, 1.20])]
def calculate_zones_running_hr(thr):
    return [{"Zona": f"Z{i+1}", "Valore": f"{int(thr*p)} bpm"} for i, p in enumerate([0.85, 0.89, 0.94, 0.99, 1.02])]


