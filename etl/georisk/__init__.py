"""ETL del sistema de evaluación de riesgo delictivo de la ZMG.

Módulos:
    config      alcance, rutas, CRS y credenciales
    fuentes     catálogo de fuentes oficiales y descarga con caché
    taxonomia   delitos canónicos, pesos de severidad y perfiles de riesgo
    nombres     normalización y empate de nombres de colonia
    geografia   carga de polígonos de colonia y municipio
    incidencia  carga de la incidencia delictiva por colonia
    riesgo      cálculo del índice
    exportar    GeoJSON y metadatos para el frontend
    carga_db    escritura a PostGIS
    cli         línea de comandos
"""

__version__ = "0.1.0"
