# Cartel de la Exposición Final, Proyecto Modular ICOM 2026B

- `SafeSpots_Cartel.pdf`: archivo para imprimir en lona y subir a la plataforma (60 cm x 160 cm, vertical).
- `SafeSpots_Cartel.html`: versión editable en un solo archivo.
- `poster.html` y `figuras/`: fuente del cartel.

## Cómo editar

1. Abrir `SafeSpots_Cartel.html` en Google Chrome.
2. Hacer clic sobre cualquier texto para cambiarlo, o sobre una imagen para reemplazarla.
3. "Guardar cambios" descarga una copia del archivo con las modificaciones.
4. "Exportar PDF" abre el diálogo de impresión: elegir "Guardar como PDF", márgenes "Ninguno" y activar "Gráficos de fondo". El tamaño de 60 x 160 cm ya viene configurado.

La barra superior indica si el contenido sigue cabiendo en el tamaño oficial.

## Regenerar desde la fuente

```bash
python3 generar_mapa.py
node exportar.js
```
