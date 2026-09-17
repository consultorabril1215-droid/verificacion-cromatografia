# Verificación de Métodos Analíticos + Estimación de Incertidumbre

Aplicación interna para la verificación de métodos analíticos (conforme a la
Guía Eurachem "La Adecuación al Uso de los Métodos Analíticos") y la
estimación de incertidumbre de medición (conforme a la Guía EURACHEM/CITAC
CG4 "Cuantificación de la Incertidumbre en Medidas Analíticas", QUAM:2012).

## Ejecutar localmente

```
pip install -r requirements.txt
streamlit run app.py
```

## Estructura

- `core/` — motor de cálculo (estadística de verificación + presupuesto de incertidumbre)
- `export/` — generación de Excel y PDF de salida
- `app.py` — interfaz Streamlit
