# Póster de la Exposición Final · Proyecto Modular ICOM 2026B

- `poster.pdf`: archivo final para imprimir en lona y subir a la plataforma
  (60 cm × 160 cm, vertical).
- `poster.html`: fuente editable del póster.
- `figuras/mapa-riesgo.svg`: mapa vectorial, generado del mismo GeoJSON que
  sirve la aplicación (`python3 generar_mapa.py`).
- `figuras/captura-app.jpg`: captura de la aplicación a 4320 × 2700 px.

Para regenerar el PDF después de editar el HTML (requiere Playwright):

```bash
node exportar.js
```

El script avisa si el contenido se sale del alto oficial.
