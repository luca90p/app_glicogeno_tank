import streamlit as st
import pandas as pd
from dataclasses import dataclass
from enum import Enum

# --- 1. CONFIGURAZIONE E PARAMETRI ---

class Sex(Enum):
    MALE = "Uomo"
    FEMALE = "Donna"

class TrainingStatus(Enum):
    SEDENTARY = (13.0, "Sedentario / Low Carb")
    RECREATIONAL = (18.0, "Attivo / Amatore")
    ENDURANCE_TRAINED = (22.0, "Allenato (Endurance)")
    ELITE_OPTIMIZED = (25.0, "Elite / Pro")
    CARBO_LOADED = (32.0, "Carico Carboidrati (Supercompensazione)")

    def __init__(self, val, label):
        self.val = val
        self.label = label

class SportType(Enum):
    CYCLING = (0.63, "Ciclismo (Gambe)")
    RUNNING = (0.75, "Corsa (Gambe + Core)")
    TRIATHLON = (0.85, "Triathlon")
    XC_SKIING = (0.95, "Sci di Fondo (Total Body)")
    SWIMMING = (0.80, "Nuoto")
    ROWING = (0.85, "Canottaggio")

    def __init__(self, val, label):
        self.val = val
        self.label = label

@dataclass
class Subject:
    weight_kg: float
    body_fat_pct: float
    sex: Sex
    status: TrainingStatus
    sport: SportType
    liver_glycogen_g: float = 100.0

    @property
    def lean_body_mass(self) -> float:
        return self.weight_kg * (1.0 - self.body_fat_pct)

    @property
    def muscle_fraction(self) -> float:
        base = 0.50 if self.sex == Sex.MALE else 0.42
        if self.status in [TrainingStatus.ELITE_OPTIMIZED, TrainingStatus.CARBO_LOADED]:
            base += 0.03
        return base

# --- 2. LOGICA DI CALCOLO ---

def calculate_tank(subject: Subject):
    # Massa Magra
    lbm = subject.lean_body_mass
    # Massa Muscolare Totale
    total_muscle = lbm * subject.muscle_fraction
    # Massa Muscolare Attiva (Specifici per lo sport)
    active_muscle = total_muscle * subject.sport.val
    
    # Glicogeno Muscolare Utile
    muscle_glycogen = active_muscle * subject.status.val
    
    # Totali
    total_glycogen = muscle_glycogen + subject.liver_glycogen_g
    total_kcal = total_glycogen * 4.1 # 1g CHO ≈ 4.1 kcal

    return {
        "Massa Magra (kg)": lbm,
        "Muscoli Attivi (kg)": active_muscle,
        "Glicogeno Muscolare (g)": muscle_glycogen,
        "Glicogeno Epatico (g)": subject.liver_glycogen_g,
        "TOTALE (g)": total_glycogen,
        "TOTALE (kcal)": total_kcal
    }

# --- 3. INTERFACCIA STREAMLIT ---

st.set_page_config(page_title="Glycogen Tank Estimator", page_icon="🔋")

st.title("🔋 Glycogen Tank Estimator")
st.markdown("Stima la capacità di stoccaggio di glicogeno muscolare ed epatico basata su parametri fisiologici.")

# --- SEZIONE INFORMATIVA (EXPANDER) ---
with st.expander("📖 Dettagli del Modello Matematico e Fonti Scientifiche"):
    st.markdown("""
    Questo calcolatore utilizza un modello **"a imbuto"** per stimare il glicogeno utile, partendo dal peso corporeo fino alla singola fibra muscolare attiva.
    
    ### 📐 L'Equazione
    $$
    G_{totale} = \\underbrace{[Peso \\cdot (1 - BF) \\cdot K_{massa} \\cdot K_{sport} \\cdot [G]_{conc}]}_{Muscolo} + G_{fegato}
    $$
    
    ### 🔬 Parametri e Fonti
    
    | Parametro | Descrizione | Fonte Scientifica |
    | :--- | :--- | :--- |
    | **$K_{massa}$** | % di Massa Magra composta da muscolo scheletrico (0.42-0.53) | *Wang et al. (2001), J Appl Physiol* |
    | **$K_{sport}$** | % di muscolatura attiva nel gesto (es. Ciclismo ~63%) | *Joyner & Coyle (2008); Volianitis et al. (2003)* |
    | **$[G]_{conc}$** | Concentrazione di glicogeno (13-32 g/kg umido) | *Areta & Hopkins (2018); Bergström & Hultman (1966)* |
    | **$G_{fegato}$** | Riserva epatica standard (80-110 g) | *Nilsson & Hultman (1973)* |
    
    *Nota: I valori di concentrazione sono convertiti da mmol/kg (peso secco) a g/kg (peso umido) assumendo un contenuto idrico del muscolo del 77%.*
    """)

# --- SIDEBAR (INPUT) ---
st.sidebar.header("Parametri Atleta")

weight = st.sidebar.slider("Peso Corporeo (kg)", 40.0, 120.0, 70.0, step=0.5)
body_fat = st.sidebar.slider("Massa Grassa (%)", 3.0, 40.0, 15.0, step=0.5) / 100.0

sex_option = st.sidebar.radio("Sesso", [s.value for s in Sex])
# Mappa la stringa scelta all'Enum
sex_enum = next(s for s in Sex if s.value == sex_option)

st.sidebar.subheader("Livello & Sport")

# Selectbox per Status
status_options = {s.label: s for s in TrainingStatus}
selected_status_label = st.sidebar.selectbox("Stato di Allenamento", list(status_options.keys()), index=2)
status_enum = status_options[selected_status_label]

# Selectbox per Sport
sport_options = {s.label: s for s in SportType}
selected_sport_label = st.sidebar.selectbox("Sport Praticato", list(sport_options.keys()), index=0)
sport_enum = sport_options[selected_sport_label]

# --- CALCOLO ---
player = Subject(
    weight_kg=weight,
    body_fat_pct=body_fat,
    sex=sex_enum,
    status=status_enum,
    sport=sport_enum
)

results = calculate_tank(player)

# --- OUTPUT DASHBOARD ---

# 1. Metriche Principali
col1, col2, col3 = st.columns(3)
col1.metric("Glicogeno Totale", f"{int(results['TOTALE (g)'])} g", delta_color="normal")
col2.metric("Energia Disponibile", f"{int(results['TOTALE (kcal)'])} kcal", help="Calorie derivanti esclusivamente dai carboidrati stoccati")
col3.metric("Muscoli Attivi", f"{results['Muscoli Attivi (kg)']:.1f} kg", help="Massa muscolare effettivamente coinvolta nel gesto atletico")

st.markdown("---")

# 2. Visualizzazione Grafica (Bar Chart)
st.subheader("Ripartizione del Serbatoio")

# Creiamo un DataFrame per il grafico
df_chart = pd.DataFrame({
    'Fonte': ['Muscoli Attivi', 'Fegato'],
    'Grammi': [results['Glicogeno Muscolare (g)'], results['Glicogeno Epatico (g)']]
})

# Usiamo le colonne per mettere grafico e dettagli vicini
c_chart, c_text = st.columns([2, 1])

with c_chart:
    st.bar_chart(df_chart, x='Fonte', y='Grammi', color=["#FF4B4B"])

with c_text:
    st.info(f"""
    **Dettagli Tecnici:**
    
    * **Concentrazione:** {status_enum.val} g/kg
    * **Fattore Sport:** {sport_enum.val*100:.0f}% della muscolatura
    * **Massa Magra:** {results['Massa Magra (kg)']:.1f} kg
    """)
    
    if results['TOTALE (g)'] > 700:
        st.success("Livello da Atleta Elite! 🚀")
    elif results['TOTALE (g)'] < 350:
        st.warning("Livello basso. Attenzione alle crisi di fame.")
    else:
        st.info("Livello nella media atletica. 👍")

# 3. Spiegazione
st.markdown("---")
st.markdown("""
### 📚 Come leggere i dati
* **Muscoli Attivi:** Non tutto il glicogeno del corpo è disponibile. Nel ciclismo, ad esempio, il glicogeno nelle braccia non può essere usato dalle gambe. Questo modello calcola solo il carburante "utile".
* **Energia:** Rappresenta la durata teorica prima dell'esaurimento (bonk) se si bruciassero solo carboidrati (cosa che non avviene mai al 100%, ma è un buon indicatore di limite).
""")